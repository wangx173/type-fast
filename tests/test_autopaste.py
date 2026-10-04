"""Unit tests for pasting the translation when the hotkey hides the window."""

from __future__ import annotations

import json
import os
import tempfile
import types
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from type_fast import autopaste, config, settings

_HEADLESS = os.environ.get("QT_QPA_PLATFORM") == "offscreen"


class AutopasteModuleTests(unittest.TestCase):
    def test_no_op_off_cocoa(self) -> None:
        with mock.patch.object(autopaste.hotkey, "is_cocoa", return_value=False), \
                mock.patch.object(autopaste.ctypes, "CDLL") as cdll:
            self.assertFalse(autopaste.is_supported())
            self.assertFalse(autopaste.has_permission())
            self.assertFalse(autopaste.send_paste())
            self.assertIsNone(autopaste.hotkey.pasteboard_change_count())
            self.assertIsNone(autopaste.hotkey.frontmost_app_pid())
            self.assertIsNone(autopaste.input_event_count())
        cdll.assert_not_called()

    def _fake_lib(self, permitted: bool = True) -> mock.MagicMock:
        lib = mock.MagicMock()
        lib.AXIsProcessTrusted.return_value = permitted
        lib.CGEventSourceCreate.return_value = 1
        lib.CGEventCreateKeyboardEvent.side_effect = [2, 3]
        return lib

    def test_send_paste_posts_command_v_down_and_up(self) -> None:
        lib = self._fake_lib()
        with mock.patch.object(autopaste, "_load", return_value=lib):
            self.assertTrue(autopaste.send_paste())
        self.assertEqual(
            [c.args for c in lib.CGEventCreateKeyboardEvent.call_args_list],
            [(1, 0x09, True), (1, 0x09, False)],
        )
        self.assertEqual(
            [c.args for c in lib.CGEventSetFlags.call_args_list],
            [(2, autopaste._COMMAND_FLAGS), (3, autopaste._COMMAND_FLAGS)],
        )
        self.assertTrue(autopaste._COMMAND_FLAGS & 0x00100000)  # ⌘
        self.assertEqual(
            [c.args for c in lib.CGEventPost.call_args_list],
            [(autopaste._kCGSessionEventTap, 2), (autopaste._kCGSessionEventTap, 3)],
        )
        self.assertCountEqual([c.args[0] for c in lib.CFRelease.call_args_list], [1, 2, 3])

    def test_input_event_count_sums_hardware_clicks_and_key_presses(self) -> None:
        lib = self._fake_lib()
        lib.CGEventSourceCounterForEventType.side_effect = lambda state, kind: kind
        with mock.patch.object(autopaste, "_load", return_value=lib):
            self.assertEqual(autopaste.input_event_count(), 1 + 3 + 10 + 25)
        states = {c.args[0] for c in lib.CGEventSourceCounterForEventType.call_args_list}
        self.assertEqual(states, {autopaste._kCGEventSourceStateHIDSystemState})

    def test_send_paste_needs_permission(self) -> None:
        lib = self._fake_lib(permitted=False)
        with mock.patch.object(autopaste, "_load", return_value=lib):
            self.assertFalse(autopaste.send_paste())
        lib.CGEventPost.assert_not_called()

    def test_permission_is_checked_live(self) -> None:
        lib = self._fake_lib(permitted=False)
        with mock.patch.object(autopaste, "_load", return_value=lib):
            self.assertFalse(autopaste.has_permission())
            lib.AXIsProcessTrusted.return_value = True  # allowed in System Settings
            self.assertTrue(autopaste.has_permission())
            self.assertTrue(autopaste.send_paste())

    def test_send_paste_never_leaves_a_key_down(self) -> None:
        lib = self._fake_lib()
        lib.CGEventCreateKeyboardEvent.side_effect = [2, None]
        with mock.patch.object(autopaste, "_load", return_value=lib):
            self.assertFalse(autopaste.send_paste())
        lib.CGEventPost.assert_not_called()
        self.assertCountEqual([c.args[0] for c in lib.CFRelease.call_args_list], [1, 2])


class AutoPasteSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(
            settings, "SETTINGS_FILE", Path(self.tmp.name) / "settings.json"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_and_round_trip(self) -> None:
        self.assertEqual(settings.load().auto_paste, config.DEFAULT_AUTO_PASTE)
        settings.save(settings.Settings(auto_paste=False))
        self.assertFalse(settings.load().auto_paste)

    def test_invalid_falls_back_to_default(self) -> None:
        for bad in ("no", 0, None, []):
            settings.SETTINGS_FILE.write_text(
                json.dumps({"auto_paste": bad, "tone": "Casual"}), encoding="utf-8"
            )
            loaded = settings.load()
            self.assertEqual(loaded.auto_paste, config.DEFAULT_AUTO_PASTE, bad)
            self.assertEqual(loaded.tone, "Casual")


@unittest.skipUnless(_HEADLESS, "set QT_QPA_PLATFORM=offscreen to run the headless window tests")
class WindowAutoPasteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from type_fast import app

        self.app_module = app
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(
            settings, "SETTINGS_FILE", Path(self.tmp.name) / "settings.json"
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        # Never start real translation threads.
        patcher = mock.patch.object(
            app, "threading", types.SimpleNamespace(Thread=mock.MagicMock())
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        # Run the delayed paste right away, and record it instead of posting.
        self.scheduled: list[int] = []

        def single_shot(delay: int, callback: Callable[[], None]) -> None:
            self.scheduled.append(delay)
            callback()

        patcher = mock.patch.object(app.QTimer, "singleShot", single_shot)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.send_paste = mock.MagicMock(return_value=True)
        self.has_permission = mock.MagicMock(return_value=True)
        # Stand in for your clicks and key presses: none unless a test adds some.
        self.input_count = 0
        for name, value in (
            ("send_paste", self.send_paste),
            ("is_supported", mock.MagicMock(return_value=True)),
            ("has_permission", self.has_permission),
            ("input_event_count", lambda: self.input_count),
        ):
            patcher = mock.patch.object(autopaste, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # Answer the permission alert instead of showing it: by default with
        # its default button, "Open System Settings".
        self.alerts: list[str] = []
        self.alert_choice: Callable[[QMessageBox], object] = QMessageBox.defaultButton

        def exec_alert(box: QMessageBox) -> int:
            self.alerts.append(box.text())
            return 0

        for name, value in (
            ("exec", exec_alert),
            ("clickedButton", lambda box: self.alert_choice(box)),
        ):
            patcher = mock.patch.object(app.QMessageBox, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # Stand in for the macOS pasteboard change count: it goes up with
        # every copy.
        self.change_count = 0

        def count_change() -> None:
            self.change_count += 1

        clipboard = QApplication.clipboard()
        clipboard.dataChanged.connect(count_change)
        self.addCleanup(clipboard.dataChanged.disconnect, count_change)
        patcher = mock.patch.object(
            app.hotkey, "pasteboard_change_count", lambda: self.change_count
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        # Stand in for the frontmost app: the one you go back to.
        self.frontmost_pid = 100
        patcher = mock.patch.object(
            app.hotkey, "frontmost_app_pid", lambda: self.frontmost_pid
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.open_url = mock.MagicMock()
        patcher = mock.patch.object(app.QDesktopServices, "openUrl", self.open_url)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.window = self._new_window()

    def _new_window(self) -> QMainWindow:
        window = self.app_module.MainWindow()
        self.addCleanup(self._discard, window)
        return window

    @staticmethod
    def _discard(window: QMainWindow) -> None:
        # Delete, not just close: a dismissed window that is still alive
        # re-summons itself when the app is reactivated, stealing activation
        # from windows in later tests.
        window.close()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def _type(self, text: str) -> None:
        w = self.window
        w.input.setPlainText(text)
        w.timer.stop()
        w.run_translation()

    def _finish(self, translation: str = "Bonjour.") -> None:
        """Stream ``translation`` for the request in flight and finish it."""
        w = self.window
        w.bridge.delta.emit(w._request_id, translation)
        w.bridge.finished.emit(w._request_id, translation)

    def _translate(self, text: str = "Hello.") -> None:
        """Type ``text`` and finish its translation."""
        self._type(text)
        self._finish()

    def _hotkey(self) -> None:
        w = self.window
        with mock.patch.object(w, "isActiveWindow", return_value=True):
            w.toggle_visibility()

    def test_hotkey_hide_pastes_finished_translation_once(self) -> None:
        w = self.window
        w.summon()
        self._translate()
        self._hotkey()
        self.assertFalse(w.isVisible())
        self.send_paste.assert_called_once_with()
        self.assertEqual(self.scheduled, [self.app_module._PASTE_DELAY_MS])
        # Summon and hide again without a new translation: nothing to paste.
        self._hotkey()
        self.assertTrue(w.isVisible())
        self._hotkey()
        self.send_paste.assert_called_once_with()

    def test_escape_hides_without_pasting(self) -> None:
        w = self.window
        w.summon()
        self._translate()
        w.dismiss_shortcut.activated.emit()
        self.assertFalse(w.isVisible())
        self.send_paste.assert_not_called()
        # Dismissed with Esc counts as skipped; reopening doesn't revive it.
        w.summon()
        self._hotkey()
        self.send_paste.assert_not_called()

    def test_raising_a_background_window_keeps_the_translation(self) -> None:
        w = self.window
        w.summon()
        self._translate()
        with mock.patch.object(w, "isActiveWindow", return_value=False):
            w.toggle_visibility()  # visible in the background: brought back
        self.assertTrue(w.isVisible())
        self._hotkey()
        self.send_paste.assert_called_once_with()

    def test_hide_while_translating_pastes_once_it_finishes(self) -> None:
        w = self.window
        w.summon()
        self._translate()
        w.input.setPlainText("Hello. How are you?")  # starts a new request
        self._hotkey()
        self.assertFalse(w.isVisible())
        self.send_paste.assert_not_called()  # not the stale translation
        w.bridge.delta.emit(w._request_id, "Bonjour. Comment")
        self.send_paste.assert_not_called()  # nor a partial one
        w.bridge.delta.emit(w._request_id, " allez-vous ?")
        w.bridge.finished.emit(w._request_id, "Bonjour. Comment allez-vous ?")
        self.assertEqual(QApplication.clipboard().text(), "Bonjour. Comment allez-vous ?")
        self.send_paste.assert_called_once_with()
        self.assertFalse(w._deferred_paste_timer.isActive())
        # Summon and hide again without a new translation: no second paste.
        self._hotkey()
        self._hotkey()
        self.send_paste.assert_called_once_with()

    def test_pending_change_that_starts_a_request_pastes_once_it_finishes(self) -> None:
        w = self.window
        w.summon()
        self._translate()
        w.input.setPlainText("Hello. How are")  # waits for the debounce
        self.assertTrue(w.timer.isActive())
        self._hotkey()
        self.assertFalse(w.timer.isActive())  # translated right away instead
        self.send_paste.assert_not_called()
        self._finish("Bonjour. Comment")
        self.send_paste.assert_called_once_with()

    def test_hide_while_translating_several_lines_pastes_all_of_them(self) -> None:
        w = self.window
        w.summon()
        self._type("Hello.\nWorld.")
        self._hotkey()
        self._finish("Bonjour.")  # first line; the next one starts
        self.send_paste.assert_not_called()
        self._finish("Monde.")
        self.assertEqual(QApplication.clipboard().text(), "Bonjour.\nMonde.")
        self.send_paste.assert_called_once_with()

    def test_deferred_paste_times_out(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        self._hotkey()
        self.assertTrue(w._deferred_paste_timer.isActive())
        self.assertEqual(
            w._deferred_paste_timer.interval(), self.app_module._DEFERRED_PASTE_TIMEOUT_MS
        )
        w._deferred_paste_timer.timeout.emit()  # too slow
        self._finish()
        self.send_paste.assert_not_called()
        self.assertEqual(QApplication.clipboard().text(), "Bonjour.")  # still copied

    def test_deferred_paste_dropped_when_summoned_again(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        self._hotkey()
        self._hotkey()  # summoned again before it finished
        self.assertFalse(w._deferred_paste_timer.isActive())
        self._type("Hi.")
        self._finish()
        self.send_paste.assert_not_called()

    def test_deferred_paste_dropped_when_summoned_and_hidden_before_it_runs(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        self._hotkey()
        pending: list[Callable[[], None]] = []

        def single_shot(delay: int, callback: Callable[[], None]) -> None:
            pending.append(callback)

        with mock.patch.object(self.app_module.QTimer, "singleShot", single_shot):
            self._finish()  # paste scheduled
            self._hotkey()  # summon
            self._hotkey()  # hide again, within the delay
        for callback in pending:
            callback()
        self.send_paste.assert_not_called()

    def test_deferred_paste_dropped_if_the_clipboard_changes(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        self._hotkey()
        QApplication.clipboard().setText("secret")  # copied in the other app
        self._finish()
        self.send_paste.assert_not_called()
        self.assertEqual(QApplication.clipboard().text(), "Bonjour.")  # still copied

        w.summon()
        w.input.setPlainText("Bye.")
        self._hotkey()

        def single_shot(delay: int, callback: Callable[[], None]) -> None:
            QApplication.clipboard().setText("secret")
            callback()

        with mock.patch.object(self.app_module.QTimer, "singleShot", single_shot):
            self._finish("Au revoir.")  # copied, then something else is
        self.send_paste.assert_not_called()

    def test_deferred_paste_dropped_if_you_switch_apps(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        self._hotkey()
        self.assertEqual(w._paste_target.pid, 100)
        self.frontmost_pid = 200  # you switched to another app
        self._finish()
        self.send_paste.assert_not_called()
        self.assertEqual(QApplication.clipboard().text(), "Bonjour.")

    def test_deferred_paste_dropped_if_you_switch_apps_during_the_delay(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        self._hotkey()

        def single_shot(delay: int, callback: Callable[[], None]) -> None:
            self.frontmost_pid = 200
            callback()

        with mock.patch.object(self.app_module.QTimer, "singleShot", single_shot):
            self._finish()
        self.send_paste.assert_not_called()

    def test_deferred_paste_dropped_if_you_click_or_type(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        self._hotkey()
        self.input_count += 1  # e.g. clicked another field in the same app
        self._finish()
        self.send_paste.assert_not_called()
        self.assertEqual(QApplication.clipboard().text(), "Bonjour.")

    def test_noting_the_paste_target_waits_for_the_previous_app(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        # macOS still lists Type Fast first right after hiding.
        self.frontmost_pid = os.getpid()
        checks: list[int] = []

        def single_shot(delay: int, callback: Callable[[], None]) -> None:
            checks.append(delay)
            if len(checks) == 2:
                self.frontmost_pid = 100
            callback()

        with mock.patch.object(self.app_module.QTimer, "singleShot", single_shot):
            self._hotkey()
        self.assertEqual(w._paste_target.pid, 100)
        self._finish()
        self.send_paste.assert_called_once_with()

    def test_deferred_paste_goes_to_the_first_app_if_none_was_noted(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        self.frontmost_pid = os.getpid()
        self._hotkey()  # every check still finds Type Fast
        self.assertIsNone(w._paste_target.pid)
        self.frontmost_pid = 100
        self._finish()
        self.send_paste.assert_called_once_with()

    def test_deferred_paste_retries_until_focus_comes_back(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        self.frontmost_pid = os.getpid()
        self._hotkey()  # no app noted yet
        checks: list[int] = []

        def single_shot(delay: int, callback: Callable[[], None]) -> None:
            checks.append(delay)
            if len(checks) == 3:  # the paste's delay, then two retries
                self.frontmost_pid = 100  # focus comes back on a later check
            callback()

        with mock.patch.object(self.app_module.QTimer, "singleShot", single_shot):
            self._finish()  # right after the hide
        self.send_paste.assert_called_once_with()
        self.assertEqual(len(checks), 3)

    def test_deferred_paste_dropped_if_you_type_before_an_app_is_noted(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        self.frontmost_pid = os.getpid()
        self._hotkey()  # no app noted yet
        self.input_count += 1  # e.g. ⌘Tab to another app
        self.frontmost_pid = 200
        self._finish()
        self.send_paste.assert_not_called()

    def test_deferred_paste_dropped_if_the_frontmost_app_is_unknown_or_type_fast(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        self._hotkey()
        self.frontmost_pid = None
        self._finish()
        self.send_paste.assert_not_called()

        w.summon()
        w.input.setPlainText("Bye.")
        self._hotkey()  # no app noted either
        self.assertIsNone(w._paste_target.pid)
        self._finish("Au revoir.")
        self.send_paste.assert_not_called()

        w.summon()
        w.input.setPlainText("Hi.")
        self.frontmost_pid = os.getpid()  # still Type Fast: never paste into it
        self._hotkey()
        self._finish("Salut.")
        self.send_paste.assert_not_called()

    def test_deferred_paste_times_out_between_lines(self) -> None:
        w = self.window
        w.summon()
        self._type("Hello.\nWorld.")
        self._hotkey()
        self._finish("Bonjour.")
        w._deferred_paste_timer.timeout.emit()  # too slow
        self._finish("Monde.")
        self.send_paste.assert_not_called()
        self.assertEqual(QApplication.clipboard().text(), "Bonjour.\nMonde.")

    def test_deferred_paste_dropped_after_error_on_a_later_line(self) -> None:
        w = self.window
        w.summon()
        self._type("Hello.\nWorld.")
        self._hotkey()
        self._finish("Bonjour.")
        w.bridge.error.emit(w._request_id, "boom")
        self.assertIsNone(w._deferred_paste)
        self.assertFalse(w._deferred_paste_timer.isActive())
        self.send_paste.assert_not_called()

    def test_deferred_paste_dropped_when_retranslated(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        self._hotkey()
        w._retranslate()  # e.g. the model changed from the menu while hidden
        self.assertIsNone(w._deferred_paste)
        self._finish()
        self.send_paste.assert_not_called()

    def test_deferred_paste_dropped_after_error(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        self._hotkey()
        w.bridge.error.emit(w._request_id, "boom")
        self.assertFalse(w._deferred_paste_timer.isActive())
        self.send_paste.assert_not_called()

    def test_escape_while_translating_does_not_paste_later(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        w.dismiss_shortcut.activated.emit()
        self._finish()
        self.send_paste.assert_not_called()
        self.assertIsNone(w._deferred_paste)

    def test_deferred_paste_needs_auto_paste(self) -> None:
        w = self.window
        w.summon()
        w.auto_paste_action.trigger()  # turn it off
        w.input.setPlainText("Hello.")
        self._hotkey()
        self.assertIsNone(w._deferred_paste)
        self._finish()
        self.send_paste.assert_not_called()

    def test_pending_change_that_needs_no_request_still_pastes(self) -> None:
        w = self.window
        w.summon()
        self._translate("Hello")
        w.input.setPlainText("Hello ")  # same text to translate
        self.assertTrue(w.timer.isActive())
        self._hotkey()
        self.send_paste.assert_called_once_with()

    def test_no_paste_after_error(self) -> None:
        w = self.window
        w.summon()
        self._translate()
        w.input.setPlainText("Bye.")
        w.bridge.error.emit(w._request_id, "boom")
        self._hotkey()
        self.send_paste.assert_not_called()

    def test_no_paste_after_clearing_the_input(self) -> None:
        w = self.window
        w.summon()
        self._translate()
        w.input.setPlainText("")
        w.timer.stop()
        w.run_translation()
        self._hotkey()
        self.send_paste.assert_not_called()

    def test_clearing_the_input_drops_the_translation_in_flight(self) -> None:
        w = self.window
        w.summon()
        self._type("Hello.")
        stale = w._request_id
        self._type("")
        w.bridge.delta.emit(stale, "Bonjour.")
        w.bridge.finished.emit(stale, "Bonjour.")
        self.assertEqual(w.output.toPlainText(), "")
        self.assertEqual(w.status.text(), "")
        self._hotkey()
        self.send_paste.assert_not_called()
        # Typing the same text again translates it again.
        w.summon()
        self._type("Hello.")
        self.assertEqual(w._request_id, stale + 2)
        self.assertEqual(w.status.text(), "Translating\u2026")

    def test_deleting_the_line_in_flight_drops_its_translation(self) -> None:
        w = self.window
        w.summon()
        self._translate("Hello.\n")
        self._type("Hello.\nWorld.")
        stale = w._request_id
        self._type("Hello.\n")
        w.bridge.delta.emit(stale, "Monde.")
        w.bridge.finished.emit(stale, "Monde.")
        self.assertEqual(w.output.toPlainText(), "Bonjour.")
        self._hotkey()
        self.send_paste.assert_not_called()
        # Typing the deleted line again translates it again.
        w.summon()
        self._type("Hello.\nWorld.")
        self.assertEqual(w._request_id, stale + 2)

    def test_reopening_starts_empty(self) -> None:
        w = self.window
        w.summon()
        self._translate()
        self._hotkey()
        w.summon()
        self.assertEqual(w.input.toPlainText(), "")
        self.assertEqual(w.output.toPlainText(), "")
        self.assertEqual(w.status.text(), "")
        self.assertEqual(QApplication.clipboard().text(), "Bonjour.")
        # A translation still running when the window was hidden is dropped.
        self._type("World.")
        stale = w._request_id
        w.dismiss()
        w.summon()
        w.bridge.finished.emit(stale, "Monde.")
        self.assertEqual(w.output.toPlainText(), "")
        self.assertEqual(QApplication.clipboard().text(), "Bonjour.")

    def test_finished_while_hidden_is_pasted_only_then(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        self._hotkey()  # hidden before the translation finished
        self._finish()
        self.send_paste.assert_called_once_with()
        self.assertEqual(w._paste_text, "")
        self._hotkey()  # summon
        self._hotkey()  # hide
        self.send_paste.assert_called_once_with()

    def test_no_paste_after_deleting_the_last_line(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.\nWorld.")
        w.timer.stop()
        w.run_translation()
        for chunk in ("Bonjour.", "Monde."):
            w.bridge.delta.emit(w._request_id, chunk)
            w.bridge.finished.emit(w._request_id, chunk)
        self.assertEqual(QApplication.clipboard().text(), "Bonjour.\nMonde.")
        w.input.setPlainText("Hello.\n")
        self._hotkey()
        self.assertEqual(w.output.toPlainText(), "Bonjour.")
        self.send_paste.assert_not_called()

    def test_blank_line_after_the_translation_still_pastes(self) -> None:
        w = self.window
        w.summon()
        self._translate("Hello.\n")
        w.input.setPlainText("Hello.\n\n")
        self.assertEqual(w.output.toPlainText(), "Bonjour.\n")
        self._hotkey()
        self.send_paste.assert_called_once_with()

    def test_no_paste_if_something_else_was_copied(self) -> None:
        w = self.window
        w.summon()
        self._translate()
        QApplication.clipboard().setText("secret")
        self._hotkey()
        self.send_paste.assert_not_called()

    def test_no_paste_if_the_same_text_was_copied_elsewhere(self) -> None:
        w = self.window
        w.summon()
        self._translate()
        # Same text, but another app's clipboard item (it may carry rich data).
        QApplication.clipboard().setText("Bonjour.")
        self._hotkey()
        self.send_paste.assert_not_called()

    def test_blank_line_added_while_translating_still_copies_and_pastes(self) -> None:
        w = self.window
        w.summon()
        self._type("Hello.\n")
        request = w._request_id
        w.input.setPlainText("Hello.\n\n")  # before the translation finishes
        self.assertEqual(w._request_id, request)
        w.bridge.delta.emit(request, "Bonjour.")
        w.bridge.finished.emit(request, "Bonjour.")
        self.assertEqual(w.status.text(), "Copied to clipboard \u2713")
        self.assertEqual(QApplication.clipboard().text(), "Bonjour.\n")
        self._hotkey()
        self.send_paste.assert_called_once_with()

    def test_no_paste_if_the_clipboard_changes_during_the_delay(self) -> None:
        w = self.window
        w.summon()
        self._translate()

        def single_shot(delay: int, callback: Callable[[], None]) -> None:
            QApplication.clipboard().setText("secret")
            callback()

        with mock.patch.object(self.app_module.QTimer, "singleShot", single_shot):
            self._hotkey()
        self.send_paste.assert_not_called()

    def test_no_paste_when_turned_off(self) -> None:
        w = self.window
        w.summon()
        w.auto_paste_action.trigger()  # turn it off
        self.assertFalse(w.prefs.auto_paste)
        self._translate()
        self._hotkey()
        self.send_paste.assert_not_called()

    def test_no_paste_if_summoned_again_before_it_runs(self) -> None:
        w = self.window
        w.summon()
        self._translate()
        w.show()
        w._paste_into_previous_app("Bonjour.", w._shown_count)
        self.send_paste.assert_not_called()

    def test_no_paste_if_summoned_and_hidden_again_before_it_runs(self) -> None:
        w = self.window
        w.summon()
        self._translate()
        pending: list[Callable[[], None]] = []

        def single_shot(delay: int, callback: Callable[[], None]) -> None:
            pending.append(callback)

        with mock.patch.object(self.app_module.QTimer, "singleShot", single_shot):
            self._hotkey()  # hide: paste scheduled
            self._hotkey()  # summon
            self._hotkey()  # hide again, within the delay
        for callback in pending:
            callback()
        self.send_paste.assert_not_called()

    def test_missing_permission_is_explained_before_hiding(self) -> None:
        self.has_permission.return_value = False
        w = self.window
        w.summon()
        self._translate()
        visible_during_alert: list[bool] = []
        self.alert_choice = lambda box: visible_during_alert.append(w.isVisible())
        self._hotkey()
        self.assertEqual(len(self.alerts), 1)
        self.assertEqual(visible_during_alert, [True])
        self.open_url.assert_not_called()  # "Not Now"
        self.assertFalse(w.isVisible())
        self.assertEqual(QApplication.clipboard().text(), "Bonjour.")
        # Once per launch: the next hide doesn't ask again.
        w.summon()
        self._translate()
        self._hotkey()
        self.assertEqual(len(self.alerts), 1)

    def test_missing_permission_is_explained_before_hiding_while_translating(self) -> None:
        self.has_permission.return_value = False
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        visible_during_alert: list[bool] = []
        self.alert_choice = lambda box: visible_during_alert.append(w.isVisible())
        self._hotkey()
        self.assertEqual(visible_during_alert, [True])
        self.assertFalse(w.isVisible())
        self.assertIsNotNone(w._deferred_paste)

    def test_translation_finished_during_the_alert_is_pasted(self) -> None:
        self.has_permission.return_value = False
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")

        def finish_during_alert(box: QMessageBox) -> None:
            self._finish()

        self.alert_choice = finish_during_alert
        self._hotkey()
        self.assertEqual(len(self.alerts), 1)
        self.assertIsNone(w._deferred_paste)
        self.send_paste.assert_called_once_with()

    def test_alert_opens_accessibility_settings(self) -> None:
        self.has_permission.return_value = False
        w = self.window
        w.summon()
        self._translate()
        self._hotkey()
        self.open_url.assert_called_once()
        self.assertEqual(self.open_url.call_args.args[0].toString(), autopaste.SETTINGS_URL)

    def test_permission_granted_while_running_pastes_without_relaunch(self) -> None:
        self.has_permission.return_value = False
        w = self.window
        w.summon()
        self._translate()
        self._hotkey()
        self.has_permission.return_value = True  # allowed in System Settings
        w.summon()
        self._translate()
        self._hotkey()
        self.assertEqual(len(self.alerts), 1)
        self.assertEqual(self.send_paste.call_count, 2)

    def test_no_alert_when_allowed_or_nothing_to_paste(self) -> None:
        w = self.window
        w.summon()
        self._translate()
        self._hotkey()  # allowed
        self.has_permission.return_value = False
        w.summon()
        self._hotkey()  # nothing to paste
        self.assertEqual(self.alerts, [])

    def test_menu_toggle_is_saved_and_explains_missing_permission(self) -> None:
        self.has_permission.return_value = False
        w = self.window
        self.assertTrue(w.auto_paste_action.isChecked())
        w.auto_paste_action.trigger()
        self.assertFalse(settings.load().auto_paste)
        self.assertEqual(self.alerts, [])
        w.auto_paste_action.trigger()
        self.assertTrue(settings.load().auto_paste)
        self.assertEqual(len(self.alerts), 1)
        # Explained already this launch: neither re-enabling nor a hotkey hide
        # asks again.
        w.auto_paste_action.trigger()
        w.auto_paste_action.trigger()
        w.summon()
        self._translate()
        self._hotkey()
        self.assertEqual(len(self.alerts), 1)
        self.has_permission.return_value = True
        w.auto_paste_action.trigger()
        w.auto_paste_action.trigger()
        self.assertEqual(len(self.alerts), 1)
        self.assertTrue(self._new_window().auto_paste_action.isChecked())


if __name__ == "__main__":
    unittest.main()

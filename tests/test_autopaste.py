"""Unit tests for pasting the translation when the hotkey hides the window."""

from __future__ import annotations

import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from type_fast import autopaste, settings

_HEADLESS = os.environ.get("QT_QPA_PLATFORM") == "offscreen"


class AutopasteModuleTests(unittest.TestCase):
    def test_no_op_off_cocoa(self) -> None:
        with mock.patch.object(autopaste.hotkey, "_is_cocoa", return_value=False), \
                mock.patch.object(autopaste.ctypes, "CDLL") as cdll:
            self.assertFalse(autopaste.is_supported())
            self.assertFalse(autopaste.has_permission())
            self.assertFalse(autopaste.request_permission())
            self.assertFalse(autopaste.send_paste())
        cdll.assert_not_called()

    def _fake_lib(self, permitted: bool = True) -> mock.MagicMock:
        lib = mock.MagicMock()
        lib.CGPreflightPostEventAccess.return_value = permitted
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

    def test_send_paste_needs_permission(self) -> None:
        lib = self._fake_lib(permitted=False)
        with mock.patch.object(autopaste, "_load", return_value=lib):
            self.assertFalse(autopaste.send_paste())
        lib.CGEventPost.assert_not_called()

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

    def test_default_on_and_round_trip(self) -> None:
        self.assertTrue(settings.load().auto_paste)
        settings.save(settings.Settings(auto_paste=False))
        self.assertFalse(settings.load().auto_paste)

    def test_invalid_falls_back_to_on(self) -> None:
        for bad in ("no", 0, None, []):
            settings.SETTINGS_FILE.write_text(
                json.dumps({"auto_paste": bad, "tone": "Casual"}), encoding="utf-8"
            )
            loaded = settings.load()
            self.assertTrue(loaded.auto_paste, bad)
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

        def single_shot(delay: int, callback) -> None:
            self.scheduled.append(delay)
            callback()

        patcher = mock.patch.object(app.QTimer, "singleShot", single_shot)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.send_paste = mock.MagicMock(return_value=True)
        self.request_permission = mock.MagicMock(return_value=False)
        for name, value in (
            ("send_paste", self.send_paste),
            ("request_permission", self.request_permission),
            ("is_supported", mock.MagicMock(return_value=True)),
            ("has_permission", mock.MagicMock(return_value=False)),
        ):
            patcher = mock.patch.object(autopaste, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = self._new_window()

    def _new_window(self):
        window = self.app_module.MainWindow()
        self.addCleanup(self._discard, window)
        return window

    @staticmethod
    def _discard(window) -> None:
        # Delete, not just close: a dismissed window that is still alive
        # re-summons itself when the app is reactivated, stealing activation
        # from windows in later tests.
        window.close()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def _translate(self, text: str = "Hello.") -> None:
        """Type ``text`` and finish its translation."""
        w = self.window
        w.input.setPlainText(text)
        w.timer.stop()
        w.run_translation()
        w.bridge.delta.emit(w._request_id, "Bonjour.")
        w.bridge.finished.emit(w._request_id, "Bonjour.")

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

    def test_no_paste_while_translating(self) -> None:
        w = self.window
        w.summon()
        self._translate()
        w.input.setPlainText("Hello. How are you?")  # starts a new request
        self._hotkey()
        self.send_paste.assert_not_called()

    def test_pending_change_that_starts_a_request_is_not_pasted(self) -> None:
        w = self.window
        w.summon()
        self._translate()
        w.input.setPlainText("Hello. How are")  # waits for the debounce
        self.assertTrue(w.timer.isActive())
        self._hotkey()
        self.assertFalse(w.timer.isActive())  # translated right away instead
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

    def test_finished_while_hidden_is_not_pasted_later(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("Hello.")
        self._hotkey()  # hidden before the translation finished
        w.bridge.delta.emit(w._request_id, "Bonjour.")
        w.bridge.finished.emit(w._request_id, "Bonjour.")
        self.assertTrue(w._paste_ready)
        self._hotkey()  # summon
        self._hotkey()  # hide
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
        w._paste_into_previous_app()
        self.send_paste.assert_not_called()

    def test_asks_for_permission_once_per_launch(self) -> None:
        self.send_paste.return_value = False
        w = self.window
        for _ in range(2):
            w.summon()
            self._translate()
            self._hotkey()
        self.assertEqual(self.send_paste.call_count, 2)
        self.request_permission.assert_called_once_with()

    def test_menu_toggle_is_saved_and_asks_for_permission(self) -> None:
        w = self.window
        self.assertTrue(w.auto_paste_action.isChecked())
        w.auto_paste_action.trigger()
        self.assertFalse(settings.load().auto_paste)
        self.request_permission.assert_not_called()
        w.auto_paste_action.trigger()
        self.assertTrue(settings.load().auto_paste)
        self.request_permission.assert_called_once_with()
        self.assertTrue(self._new_window().auto_paste_action.isChecked())


if __name__ == "__main__":
    unittest.main()

"""Windows UI contracts exercised with a patched platform and offscreen Qt."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from type_fast import hotkey, platform, settings, voice
from type_fast.platform import text

_HEADLESS = os.environ.get("QT_QPA_PLATFORM") == "offscreen"


class PlatformTextTests(unittest.TestCase):
    def test_windows_wording(self) -> None:
        with mock.patch.object(text.sys, "platform", "win32"):
            wording = platform.ui_text()
            self.assertEqual(wording.options_shortcut, "Ctrl+L")
            self.assertEqual(wording.paste_key, "Ctrl+V")
            self.assertEqual(wording.microphone_settings_url, "ms-settings:privacy-microphone")
            self.assertIn("Privacy & security", voice.permission_denied())
            self.assertIn("Settings \u203a System \u203a Sound", voice.permission_hint())
            for value in (voice.permission_hint(), voice.permission_denied()):
                self.assertNotIn("System Settings", value)

    def test_macos_wording_is_unchanged(self) -> None:
        with mock.patch.object(text.sys, "platform", "darwin"):
            self.assertEqual(platform.ui_text().options_shortcut, "\u2318L")
            self.assertEqual(platform.ui_text().paste_key, "\u2318V")
            self.assertIsNone(platform.ui_text().microphone_settings_url)
            self.assertEqual(
                voice.permission_denied(),
                "Type Fast doesn't have access to the microphone. Allow it in System "
                "Settings \u203a Privacy & Security \u203a Microphone, then try again.",
            )
            self.assertEqual(
                voice.permission_hint(),
                "No sound was recorded. Check that Type Fast may use the microphone in "
                "System Settings \u203a Privacy & Security \u203a Microphone, and that the "
                "right input device is selected in System Settings \u203a Sound.",
            )

    def test_windows_does_not_request_macos_permission_even_when_frozen(self) -> None:
        with (
            mock.patch.object(platform, "is_windows", return_value=True),
            mock.patch.object(voice.sys, "frozen", True, create=True),
            mock.patch.object(voice.QCoreApplication, "instance") as app,
        ):
            callback = mock.Mock()
            voice.request_permission(mock.Mock(), callback)
            callback.assert_called_once_with(True)
            app.return_value.checkPermission.assert_not_called()


@unittest.skipUnless(_HEADLESS, "set QT_QPA_PLATFORM=offscreen")
class WindowsWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from type_fast import app

        self.module = app
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self._patch(settings, "SETTINGS_FILE", Path(tmp.name) / "settings.json")
        self._patch(app, "threading", types.SimpleNamespace(Thread=mock.MagicMock()))
        self._patch(platform, "is_windows", return_value=True)
        self._patch(text, "is_windows", return_value=True)
        self._patch(hotkey, "is_windows", return_value=True)
        self._patch(app, "_VOICE_SHORTCUT_SYMBOLS", "Ctrl+Shift+M")
        self.tray_available = self._patch(app.QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
        self.balloon = self._patch(app.QSystemTrayIcon, "showMessage")
        self.quit = self._patch(app.QApplication, "quit")
        self.windows = []
        self.addCleanup(self._dispose)

    def _patch(self, obj: object, name: str, *args: object, **kwargs: object) -> object:
        patcher = mock.patch.object(obj, name, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def _window(self):
        window = self.module.MainWindow()
        self.windows.append(window)
        return window

    def _dispose(self) -> None:
        for window in self.windows:
            if window.tray_icon is not None:
                window.tray_icon.hide()
            window.hide()
            window.deleteLater()
        self.qt.sendPostedEvents(None, self.module.QEvent.DeferredDelete)

    def _leaves(self, menu):
        for action in menu.actions():
            if action.menu() is not None:
                yield from self._leaves(action.menu())
            elif not action.isSeparator():
                yield action

    def test_tray_shares_all_settings_actions_and_window_shortcuts(self) -> None:
        w = self._window()
        self.assertTrue(w.menuBar().isHidden())
        self.assertIs(w.tray_menu.actions()[1].menu(), w.settings_menu)
        for action in self._leaves(w.settings_menu):
            self.assertIn(action, w.actions())
        self.assertIn(w.set_key_action, w.actions())
        self.assertIn(w.show_options_action, w.actions())
        self.assertIn(w.record_action, w.actions())
        w.summon(compact=True)
        w.show_options_action.trigger()
        self.assertFalse(w.compact)
        with mock.patch.object(w, "_set_api_key") as open_key:
            w.set_key_action.trigger()
            open_key.assert_called_once_with()
        for menu in (w.settings_menu, w.tray_menu):
            for action in self._leaves(menu):
                for forbidden in ("\u2318", "\u2325", "\u2303", "Dock", "System Settings"):
                    self.assertNotIn(forbidden, action.text() + action.toolTip())
        self.assertIn("Ctrl+L", w.pair_button.toolTip())

    def test_focused_shortcuts_remain_reachable(self) -> None:
        from PySide6.QtTest import QTest

        w = self._window()
        w.summon(compact=True)
        self.qt.processEvents()
        with mock.patch.object(w, "_set_api_key") as open_key:
            QTest.keySequence(w.input, w.set_key_action.shortcut())
            open_key.assert_called_once_with()
        QTest.keySequence(w.input, w.show_options_action.shortcut())
        self.assertFalse(w.compact)

    def test_left_click_toggles_without_paste_and_ignores_context_activation(self) -> None:
        w = self._window()
        with mock.patch.object(w, "_raise_open_dialog", return_value=False):
            w.tray_icon.activated.emit(self.module.QSystemTrayIcon.Trigger)
            self.assertTrue(w.isVisible())
            with mock.patch.object(w, "_schedule_paste") as paste:
                w.tray_icon.activated.emit(self.module.QSystemTrayIcon.Trigger)
                self.assertFalse(w.isVisible())
                paste.assert_not_called()
            w.tray_icon.activated.emit(self.module.QSystemTrayIcon.Context)
            self.assertFalse(w.isVisible())
            w.show_action.trigger()
            self.assertTrue(w.isVisible())

    def test_close_dismisses_and_persists_notice_only_once(self) -> None:
        w = self._window()
        w.summon()
        with mock.patch.object(w, "_cancel_voice") as cancel:
            self.assertFalse(w.close())
            cancel.assert_called_with()
        self.assertFalse(w.isVisible())
        self.quit.assert_not_called()
        self.balloon.assert_called_once()
        self.assertIn("from the tray.", self.balloon.call_args.args[1])
        self.assertTrue(settings.load().tray_close_notice_shown)
        w.summon()
        w.close()
        another = self._window()
        another.close()
        self.balloon.assert_called_once()

    def test_registered_hotkey_updates_tooltip_and_close_notice(self) -> None:
        w = self._window()
        registered = hotkey.parse("Ctrl+Shift+Space")
        w.global_hotkey = mock.Mock(is_registered=True, hotkey=registered)
        w._reflect_hotkey()
        self.assertEqual(w.tray_icon.toolTip(), "Type Fast (Ctrl+Shift+Space)")
        w.close()
        self.assertIn("or with Ctrl+Shift+Space", self.balloon.call_args.args[1])
        w.global_hotkey.is_registered = False
        w._reflect_hotkey()
        self.assertEqual(w.tray_icon.toolTip(), "Type Fast")

    def test_no_tray_retains_menu_and_can_exit(self) -> None:
        self.tray_available.return_value = False
        w = self._window()
        self.assertIsNone(w.tray_icon)
        self.assertFalse(w.menuBar().isHidden())
        self.assertIn(w.quit_action, w.settings_menu.actions())
        w.summon()
        self.assertTrue(w.close())
        self.quit.assert_called_once()
        self.balloon.assert_not_called()
        self.assertFalse(w.prefs.tray_close_notice_shown)

    def test_no_tray_esc_exits_without_a_registered_recovery_hotkey(self) -> None:
        from PySide6.QtTest import QTest

        self.tray_available.return_value = False
        w = self._window()
        w.summon()
        self.qt.processEvents()
        QTest.keySequence(w.input, w.dismiss_shortcut.key())
        self.quit.assert_called_once()
        self.assertTrue(w._quitting)

    def test_no_tray_can_hide_when_a_registered_hotkey_can_restore_it(self) -> None:
        self.tray_available.return_value = False
        w = self._window()
        w.global_hotkey = mock.Mock(is_registered=True)
        w.summon()
        w.dismiss()
        self.assertFalse(w.isVisible())
        self.quit.assert_not_called()

    def test_quitting_accepts_visible_window_close_without_balloon(self) -> None:
        w = self._window()
        w.summon()
        w.quit_action.trigger()
        self.assertTrue(w.close())
        self.assertFalse(w.isVisible())
        self.balloon.assert_not_called()

    def test_visible_tray_quit_exits_the_real_application_event_loop(self) -> None:
        code = """
import tempfile
import types
from pathlib import Path
from unittest import mock
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from type_fast import app, platform, settings
qt = QApplication([])
qt.setQuitOnLastWindowClosed(False)
with tempfile.TemporaryDirectory() as tmp, \\
     mock.patch.object(platform, "is_windows", return_value=True), \\
     mock.patch.object(settings, "SETTINGS_FILE", Path(tmp) / "settings.json"), \\
     mock.patch.object(app, "threading", types.SimpleNamespace(Thread=mock.MagicMock())), \\
     mock.patch.object(app.QSystemTrayIcon, "isSystemTrayAvailable", return_value=True):
    window = app.MainWindow()
    window.summon()
    QTimer.singleShot(0, window.quit_action.trigger)
    QTimer.singleShot(500, lambda: qt.exit(91))
    raise SystemExit(qt.exec())
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_show_options_from_tray_restores_hidden_and_minimized_window(self) -> None:
        w = self._window()
        w.summon(compact=True)
        w.dismiss()
        w.show_options_action.trigger()
        self.assertTrue(w.isVisible())
        self.assertFalse(w.compact)
        w.input.setPlainText("Keep current text")
        w.showMinimized()
        w.show_options_action.trigger()
        self.assertFalse(w.isMinimized())
        self.assertFalse(w.compact)
        self.assertEqual(w.input.toPlainText(), "Keep current text")

    def test_quit_cancels_recording_releases_hotkeys_and_hides_tray(self) -> None:
        w = self._window()
        with (
            mock.patch.object(w, "_cancel_voice") as cancel,
            mock.patch.object(w.global_hotkey, "unregister") as unregister,
            mock.patch.object(w.voice_hotkey, "unregister") as voice_unregister,
        ):
            w.quit_action.trigger()
            cancel.assert_called_once_with()
            unregister.assert_called_once_with()
            voice_unregister.assert_called_once_with()
        self.assertFalse(w.tray_icon.isVisible())
        self.quit.assert_called_once()

    def test_tray_recording_shows_ui_before_capture_and_preserves_transcript(self) -> None:
        w = self._window()
        w.prefs.voice_input = True
        w._reflect_voice()
        w.dismiss()
        recorder = mock.Mock(recording=False)
        w.recorder = recorder

        def start() -> None:
            self.assertTrue(w.isVisible())
            self.assertFalse(w.isMinimized())
            recorder.recording = True

        def stop() -> voice.Recording:
            recorder.recording = False
            return voice.Recording(b"\x00\x10\x00\x20", 16000, 1)

        recorder.start.side_effect = start
        recorder.stop.side_effect = stop
        provider = self.module.providers.active_provider()
        with (
            mock.patch.object(provider, "is_configured", return_value=True),
            mock.patch.object(self.module.providers, "get_client", return_value=mock.sentinel.client),
            mock.patch.object(voice, "request_permission", side_effect=lambda ctx, cb: cb(True)),
        ):
            w.record_action.trigger()
            recorder.start.assert_called_once_with()
            w.record_action.trigger()
            recorder.stop.assert_called_once_with()
            w._on_transcribed(w._voice_id, "Dictation from the tray")
        w.show_action.trigger()
        self.assertEqual(w.input.toPlainText(), "Dictation from the tray")
        w.showMinimized()
        with mock.patch.object(w, "_start_recording") as start_recording:
            w.record_action.trigger()
            start_recording.assert_called_once_with()
            self.assertFalse(w.isMinimized())

    def test_activation_does_not_resurrect_dismissed_windows_window(self) -> None:
        w = self._window()
        w.summon()
        w.dismiss()
        w._on_app_state_changed(self.module.Qt.ApplicationActive)
        self.assertFalse(w.isVisible())

    def test_windows_never_shows_accessibility_prompt(self) -> None:
        w = self._window()
        with mock.patch.object(self.module, "QMessageBox") as box:
            w._ask_paste_permission()
            self.assertFalse(w._needs_paste_permission())
            box.assert_not_called()

    def test_microphone_denial_opens_windows_privacy_url(self) -> None:
        w = self._window()
        w._mic_request = w._voice_id
        with (
            mock.patch.object(self.module, "QMessageBox") as box_type,
            mock.patch.object(self.module.QDesktopServices, "openUrl", return_value=True) as open_url,
        ):
            box = box_type.return_value
            button = mock.Mock()
            box.addButton.side_effect = [button, mock.Mock()]
            box.clickedButton.return_value = button
            w._on_mic_permission(w._voice_id, False)
            box.setText.assert_called_once_with(voice.permission_denied())
            self.assertEqual(box.addButton.call_args_list[0].args[0], "Open Settings")
            self.assertEqual(open_url.call_args.args[0].toString(), "ms-settings:privacy-microphone")

    def test_settings_link_failure_is_visible_and_transcription_errors_have_no_link(self) -> None:
        w = self._window()
        with (
            mock.patch.object(self.module, "QMessageBox") as box_type,
            mock.patch.object(self.module.QDesktopServices, "openUrl", return_value=False),
        ):
            box = box_type.return_value
            button = mock.Mock()
            box.addButton.side_effect = [button, mock.Mock()]
            box.clickedButton.return_value = button
            w._voice_failed(voice.permission_hint(), microphone_settings=True)
            self.assertIn("Could not open Settings", box_type.warning.call_args.args[2])
            box_type.reset_mock()
            w._voice_failed("Transcription request failed")
            box_type.assert_not_called()
            box_type.warning.assert_called_once_with(w, "Voice Input", "Transcription request failed")

    def test_notice_settings_validate_booleans(self) -> None:
        for value in ("true", 1, None, []):
            settings.SETTINGS_FILE.write_text(
                json.dumps({"tray_close_notice_shown": value}), encoding="utf-8"
            )
            self.assertFalse(settings.load().tray_close_notice_shown)

    def test_macos_keeps_menu_normal_close_and_reactivation(self) -> None:
        with mock.patch.object(platform, "is_windows", return_value=False):
            w = self._window()
            self.assertIsNone(w.tray_icon)
            self.assertFalse(w.menuBar().isHidden())
            w.summon()
            w.dismiss()
            w._on_app_state_changed(self.module.Qt.ApplicationActive)
            self.assertTrue(w.isVisible())
            self.assertTrue(w.close())
            self.quit.assert_not_called()
            self.balloon.assert_not_called()

    def test_windows_main_keeps_application_alive_on_last_close(self) -> None:
        with (
            mock.patch.object(self.module, "QApplication") as app_type,
            mock.patch.object(self.module, "MainWindow"),
        ):
            instance = app_type.instance.return_value
            self.module.main()
            instance.setQuitOnLastWindowClosed.assert_called_once_with(False)

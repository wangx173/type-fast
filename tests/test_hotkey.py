"""Unit tests for the global show/hide hotkey and Spotlight-style toggling."""

from __future__ import annotations

import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QKeyCombination, Qt
from PySide6.QtGui import QKeySequence

from type_fast import config, hotkey, settings

_HEADLESS = os.environ.get("QT_QPA_PLATFORM") == "offscreen"


class ParseTests(unittest.TestCase):
    def test_canonical_text_and_order(self) -> None:
        self.assertEqual(str(hotkey.parse("Option+Space")), "Option+Space")
        self.assertEqual(str(hotkey.parse("Cmd+Shift+T")), "Shift+Cmd+T")
        self.assertEqual(
            str(hotkey.parse("cmd+shift+option+ctrl+t")), "Ctrl+Option+Shift+Cmd+T"
        )

    def test_symbols(self) -> None:
        self.assertEqual(hotkey.parse("Option+Space").symbols(), "\u2325Space")
        self.assertEqual(
            hotkey.parse("Ctrl+Option+Shift+Cmd+T").symbols(),
            "\u2303\u2325\u21e7\u2318T",
        )
        self.assertEqual(hotkey.parse("Cmd+Return").symbols(), "\u2318\u21a9")

    def test_case_insensitive_and_aliases(self) -> None:
        expected = hotkey.parse("Ctrl+Option+Cmd+K")
        for text in (
            "control+alt+command+k",
            "CTRL+OPT+CMD+K",
            "\u2303+\u2325+\u2318+K",
            "\u2303\u2325\u2318K",
            " Command + Alt + Control + k ",
        ):
            self.assertEqual(hotkey.parse(text), expected, text)
        self.assertEqual(hotkey.parse("cmd+enter").key, "Return")
        self.assertEqual(hotkey.parse("cmd+esc").key, "Escape")
        self.assertEqual(hotkey.parse("cmd+backspace").key, "Delete")

    def test_round_trip(self) -> None:
        for text in ("Option+Space", "Shift+Cmd+T", "Ctrl+Option+K", "F5", "Cmd+-"):
            self.assertEqual(str(hotkey.parse(text)), text)

    def test_invalid(self) -> None:
        for text in (
            "", "Space", "A", "Shift+A", "Shift+Space",  # no real modifier
            "Cmd+Foo", "Cmd", "Cmd+Shift",  # unknown or missing key
            "Cmd+A+B", "Cmd++", "Hyper+A",  # malformed
        ):
            self.assertIsNone(hotkey.parse(text), text)
        self.assertIsNone(hotkey.parse(None))  # type: ignore[arg-type]

    def test_function_key_needs_no_modifier(self) -> None:
        self.assertEqual(str(hotkey.parse("f5")), "F5")
        self.assertEqual(str(hotkey.parse("shift+F12")), "Shift+F12")

    def test_carbon_codes(self) -> None:
        key = hotkey.parse("Option+Space")
        self.assertEqual(key.keycode, 0x31)
        self.assertEqual(key.carbon_modifiers, 0x0800)
        key = hotkey.parse("Ctrl+Option+Shift+Cmd+A")
        self.assertEqual(key.keycode, 0x00)
        self.assertEqual(key.carbon_modifiers, 0x1000 | 0x0800 | 0x0200 | 0x0100)

    def test_constructor_validates_names(self) -> None:
        with self.assertRaises(ValueError):
            hotkey.Hotkey(("Cmd",), "Nope")
        with self.assertRaises(ValueError):
            hotkey.Hotkey(("Hyper",), "A")
        self.assertFalse(hotkey.Hotkey(("Shift",), "A").is_valid)


class QtConversionTests(unittest.TestCase):
    def test_mac_modifier_mapping(self) -> None:
        # On macOS Qt's ControlModifier is ⌘ and MetaModifier is ⌃.
        combo = QKeyCombination(Qt.ControlModifier, Qt.Key_T)
        self.assertEqual(str(hotkey.from_qt(combo)), "Cmd+T")
        combo = QKeyCombination(Qt.MetaModifier, Qt.Key_T)
        self.assertEqual(str(hotkey.from_qt(combo)), "Ctrl+T")
        combo = QKeyCombination(Qt.AltModifier, Qt.Key_Space)
        self.assertEqual(str(hotkey.from_qt(combo)), "Option+Space")

    def test_sequence_and_round_trip(self) -> None:
        for text in ("Ctrl+Option+Shift+Cmd+K", "Option+Space", "F5", "Cmd+/"):
            key = hotkey.parse(text)
            self.assertEqual(hotkey.from_qt(hotkey.to_qt(key)), key, text)
        self.assertIsNone(hotkey.from_qt(QKeySequence()))

    def test_shifted_symbols_map_to_physical_key(self) -> None:
        combo = QKeyCombination(Qt.ControlModifier | Qt.ShiftModifier, Qt.Key_Exclam)
        self.assertEqual(str(hotkey.from_qt(combo)), "Shift+Cmd+1")

    def test_unsupported_and_invalid(self) -> None:
        self.assertIsNone(hotkey.from_qt(QKeyCombination(Qt.ControlModifier, Qt.Key_Shift)))
        bare = hotkey.from_qt(QKeyCombination(Qt.NoModifier, Qt.Key_A))
        self.assertIsNotNone(bare)
        self.assertFalse(bare.is_valid)

    def test_keypad_keys_rejected_but_arrows_allowed(self) -> None:
        keypad_1 = QKeyCombination(Qt.ControlModifier | Qt.KeypadModifier, Qt.Key_1)
        self.assertIsNone(hotkey.from_qt(keypad_1))
        # macOS flags the arrow keys as keypad keys.
        arrow = QKeyCombination(Qt.AltModifier | Qt.KeypadModifier, Qt.Key_Up)
        self.assertEqual(str(hotkey.from_qt(arrow)), "Option+Up")


class GlobalHotkeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    @unittest.skipUnless(_HEADLESS, "registration is only skipped headless")
    def test_register_is_safe_noop_when_unsupported(self) -> None:
        gh = hotkey.GlobalHotkey()
        self.assertFalse(gh.is_supported())
        self.assertFalse(gh.register(hotkey.parse("Ctrl+Option+Cmd+F12")))
        self.assertFalse(gh.is_registered)
        gh.unregister()  # no-op, no raise
        hotkey.activate_app()
        hotkey.hide_app()

    def test_register_rejects_invalid_hotkey(self) -> None:
        gh = hotkey.GlobalHotkey()
        self.assertFalse(gh.register(hotkey.Hotkey(("Shift",), "A")))
        self.assertFalse(gh.is_registered)

    def test_register_requests_exclusive_hotkey(self) -> None:
        # Without kEventHotKeyExclusive, macOS "accepts" combos it reserves
        # (⌘Space, ⌘Tab) and the hotkey silently never fires.
        calls = []

        def register(keycode, modifiers, _id, _target, options, ref):
            calls.append((keycode, modifiers, options))
            ref._obj.value = 1
            return 0

        lib = mock.Mock()
        lib.RegisterEventHotKey.side_effect = register
        carbon = mock.Mock(lib=lib, targets={})
        carbon.ensure_handler.return_value = True
        gh = hotkey.GlobalHotkey()
        with mock.patch.object(hotkey, "_load_carbon", return_value=carbon), \
                mock.patch.object(hotkey, "_is_cocoa", return_value=True), \
                mock.patch.object(hotkey, "_carbon", carbon):
            self.assertTrue(gh.register(hotkey.parse("Option+Space")))
            gh.unregister()
        self.assertEqual(calls, [(0x31, 0x0800, 1)])


class HotkeySettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(
            settings, "SETTINGS_FILE", Path(self.tmp.name) / "settings.json"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _load(self, data: object) -> settings.Settings:
        settings.SETTINGS_FILE.write_text(json.dumps(data), encoding="utf-8")
        return settings.load()

    def test_default(self) -> None:
        self.assertEqual(settings.load().hotkey, config.DEFAULT_HOTKEY)
        self.assertIsNotNone(hotkey.parse(config.DEFAULT_HOTKEY))
        self.assertEqual(self._load({"tone": "Casual"}).hotkey, config.DEFAULT_HOTKEY)

    def test_round_trip(self) -> None:
        settings.save(settings.Settings(hotkey="Ctrl+Option+K"))
        self.assertEqual(settings.load().hotkey, "Ctrl+Option+K")

    def test_canonicalized(self) -> None:
        self.assertEqual(self._load({"hotkey": "cmd+shift+t"}).hotkey, "Shift+Cmd+T")

    def test_empty_means_disabled(self) -> None:
        self.assertEqual(self._load({"hotkey": ""}).hotkey, "")
        self.assertEqual(self._load({"hotkey": "  "}).hotkey, "")

    def test_invalid_falls_back(self) -> None:
        for bad in ("Shift+A", "Cmd+Nope", "garbage", 42, None, []):
            self.assertEqual(self._load({"hotkey": bad}).hotkey, config.DEFAULT_HOTKEY, bad)


@unittest.skipUnless(_HEADLESS, "set QT_QPA_PLATFORM=offscreen to run the headless window tests")
class WindowHotkeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

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
        self.window = app.MainWindow()
        self.addCleanup(self.window.close)

    def test_owns_hotkey_and_shows_hint(self) -> None:
        w = self.window
        self.assertIsInstance(w.global_hotkey, hotkey.GlobalHotkey)
        self.assertFalse(w.global_hotkey.is_registered)  # never grabbed headless
        self.assertIn("\u2325Space", w.hotkey_label.text())

    def test_toggle_shows_and_hides(self) -> None:
        w = self.window
        self.assertFalse(w.isVisible())
        w.toggle_visibility()
        self.assertTrue(w.isVisible())
        self.assertTrue(w.input.hasFocus() or not w.isActiveWindow())
        with mock.patch.object(w, "isActiveWindow", return_value=True):
            w.toggle_visibility()
        self.assertFalse(w.isVisible())

    def test_toggle_raises_visible_but_inactive_window(self) -> None:
        w = self.window
        w.summon()
        with mock.patch.object(w, "isActiveWindow", return_value=False):
            w.toggle_visibility()
        self.assertTrue(w.isVisible())

    def test_app_reactivation_restores_dismissed_window_only(self) -> None:
        w = self.window
        w._on_app_state_changed(Qt.ApplicationActive)
        self.assertFalse(w.isVisible())  # never dismissed: left alone
        w.summon()
        w.dismiss()
        w._on_app_state_changed(Qt.ApplicationInactive)
        self.assertFalse(w.isVisible())
        w._on_app_state_changed(Qt.ApplicationActive)
        self.assertTrue(w.isVisible())

    def test_summon_puts_cursor_at_end(self) -> None:
        w = self.window
        w.input.setPlainText("hello")
        w.input.moveCursor(self.app_module.QTextCursor.Start)
        w.summon()
        self.assertEqual(w.input.textCursor().position(), len("hello"))

    def test_escape_dismisses_from_input(self) -> None:
        from PySide6.QtTest import QTest

        w = self.window
        w.summon()
        self.assertTrue(QTest.qWaitForWindowActive(w))
        w.input.setFocus()
        QTest.keyClick(w.input, Qt.Key_Escape)
        self.assertFalse(w.isVisible())

    def test_apply_hotkey_persists(self) -> None:
        w = self.window
        self.assertTrue(w._apply_hotkey("cmd+shift+y"))
        self.assertEqual(w.prefs.hotkey, "Shift+Cmd+Y")
        self.assertEqual(settings.load().hotkey, "Shift+Cmd+Y")
        self.assertIn("\u21e7\u2318Y", w.hotkey_label.text())

    def test_apply_empty_disables(self) -> None:
        w = self.window
        self.assertTrue(w._apply_hotkey(""))
        self.assertEqual(settings.load().hotkey, "")
        self.assertEqual(w.hotkey_label.text(), "Hotkey off")
        self.assertEqual(self.app_module.MainWindow().prefs.hotkey, "")

    def test_apply_invalid_is_rejected(self) -> None:
        w = self.window
        with mock.patch.object(self.app_module.QMessageBox, "warning") as warning:
            self.assertFalse(w._apply_hotkey("Shift+A"))
        warning.assert_called_once()
        self.assertEqual(w.prefs.hotkey, config.DEFAULT_HOTKEY)
        self.assertFalse(settings.SETTINGS_FILE.exists())

    def test_registration_failure_keeps_previous(self) -> None:
        w = self.window
        previous = w.prefs.hotkey
        with mock.patch.object(
            hotkey.GlobalHotkey, "is_supported", staticmethod(lambda: True)
        ), mock.patch.object(
            w.global_hotkey, "register", side_effect=[False, True]
        ) as register, mock.patch.object(self.app_module.QMessageBox, "warning") as warning:
            self.assertFalse(w._apply_hotkey("Cmd+Space"))
        warning.assert_called_once()
        # Tried the new combo, then restored the previous one.
        self.assertEqual(str(register.call_args_list[0].args[0]), "Cmd+Space")
        self.assertEqual(str(register.call_args_list[-1].args[0]), previous)
        self.assertEqual(w.prefs.hotkey, previous)
        self.assertFalse(settings.SETTINGS_FILE.exists())
        self.assertIn("Keeping", warning.call_args.args[2])

    def test_registration_failure_reports_failed_restore(self) -> None:
        w = self.window
        with mock.patch.object(
            hotkey.GlobalHotkey, "is_supported", staticmethod(lambda: True)
        ), mock.patch.object(
            w.global_hotkey, "register", return_value=False
        ), mock.patch.object(self.app_module.QMessageBox, "warning") as warning:
            self.assertFalse(w._apply_hotkey("Cmd+Space"))
        message = warning.call_args.args[2]
        self.assertIn("could not be restored", message)
        self.assertNotIn("Keeping", message)
        self.assertIn("unavailable", w.hotkey_label.text())

    def test_dialog_records_and_validates(self) -> None:
        dialog = self.app_module.HotkeyDialog("Option+Space", self.window)
        self.assertEqual(
            hotkey.from_qt(dialog.editor.keySequence()), hotkey.parse("Option+Space")
        )
        dialog.editor.setKeySequence(QKeySequence(QKeyCombination(Qt.NoModifier, Qt.Key_A)))
        with mock.patch.object(self.app_module.QMessageBox, "warning") as warning:
            dialog.accept()
        warning.assert_called_once()
        self.assertNotEqual(dialog.result(), dialog.DialogCode.Accepted)
        dialog.editor.setKeySequence(
            QKeySequence(QKeyCombination(Qt.ControlModifier | Qt.AltModifier, Qt.Key_K))
        )
        dialog.accept()
        self.assertEqual(dialog.chosen, "Option+Cmd+K")
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)

    def test_dialog_cancel_restores_registration(self) -> None:
        w = self.window
        calls: list[str] = []
        with mock.patch.object(
            self.app_module.HotkeyDialog, "exec", return_value=0
        ), mock.patch.object(w, "_register_hotkey", lambda: calls.append("restore")):
            w._set_hotkey()
        self.assertEqual(calls, ["restore"])
        self.assertEqual(w.prefs.hotkey, config.DEFAULT_HOTKEY)


if __name__ == "__main__":
    unittest.main()

"""Unit tests for the global show/hide hotkey and Spotlight-style toggling."""

from __future__ import annotations

import json
import ctypes
import runpy
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QKeyCombination, QThread, Qt
from PySide6.QtGui import QKeySequence

from type_fast import config, hotkey, platform, settings
from type_fast.platform import macos, windows

_HEADLESS = os.environ.get("QT_QPA_PLATFORM") == "offscreen"


class ParseTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(hotkey, "is_windows", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

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
    def setUp(self) -> None:
        patcher = mock.patch.object(hotkey, "is_windows", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

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
        gh = platform.GlobalHotkey()
        self.assertFalse(gh.is_supported())
        self.assertFalse(gh.register(hotkey.parse("Ctrl+Option+Cmd+F12")))
        self.assertFalse(gh.is_registered)
        gh.unregister()  # no-op, no raise
        platform.activate_app()
        platform.hide_app()

    def test_register_rejects_invalid_hotkey(self) -> None:
        gh = platform.GlobalHotkey()
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
        gh = macos.GlobalHotkey()
        with mock.patch.object(macos, "_load_carbon", return_value=carbon), \
                mock.patch.object(macos, "is_cocoa", return_value=True), \
                mock.patch.object(macos, "_carbon", carbon):
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

    def test_default_avoids_common_conflicts(self) -> None:
        default = hotkey.parse(config.DEFAULT_HOTKEY)
        self.assertEqual(str(default), config.DEFAULT_HOTKEY)  # canonical form
        taken = {
            "Cmd+Space", "Option+Cmd+Space",  # Spotlight
            "Ctrl+Space", "Ctrl+Option+Space",  # input sources
            "Ctrl+Cmd+Space",  # Character Viewer
            "Option+Space",  # non-breaking space; Alfred, Raycast, ChatGPT
        }
        self.assertNotIn(str(default), taken)

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

        patcher = mock.patch.object(hotkey, "is_windows", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
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
        self.assertIsInstance(w.global_hotkey, platform.GlobalHotkey)
        self.assertFalse(w.global_hotkey.is_registered)  # never grabbed headless
        self.assertIn(hotkey.parse(config.DEFAULT_HOTKEY).symbols(), w.hotkey_label.text())

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

    def test_hotkey_summons_compact_ui(self) -> None:
        w = self.window
        w.toggle_visibility()
        self.assertTrue(w.compact)
        self.assertFalse(w.options_bar.isVisibleTo(w))
        for label in (w.input_label, w.output_label, w.model_label, w.hotkey_label):
            self.assertFalse(label.isVisibleTo(w))
        self.assertTrue(w.pair_button.isVisibleTo(w))
        self.assertEqual(w.pair_button.text(), "English \u2192 Japanese")
        self.assertTrue(w.input.isVisibleTo(w))
        self.assertTrue(w.output.isVisibleTo(w))

    def test_compact_ui_expands_on_click(self) -> None:
        w = self.window
        w.toggle_visibility()
        w.pair_button.click()
        self.assertFalse(w.compact)
        self.assertTrue(w.options_bar.isVisibleTo(w))
        self.assertFalse(w.pair_button.isVisibleTo(w))

    def test_compact_ui_is_keyboard_reachable(self) -> None:
        w = self.window
        w.toggle_visibility()
        self.assertTrue(w.pair_button.focusPolicy() & Qt.TabFocus)
        self.assertEqual(
            w.show_options_action.shortcut(), QKeySequence("Ctrl+L")
        )
        w.show_options_action.trigger()
        self.assertFalse(w.compact)
        self.assertTrue(w.options_bar.isVisibleTo(w))

    def test_non_hotkey_summon_shows_full_ui(self) -> None:
        w = self.window
        w.toggle_visibility()
        w.dismiss()
        w._on_app_state_changed(Qt.ApplicationActive)  # Dock icon / Cmd-Tab
        self.assertFalse(w.compact)
        self.assertTrue(w.options_bar.isVisibleTo(w))

    def test_pair_label_follows_languages(self) -> None:
        w = self.window
        w._apply_languages(config.AUTO_SOURCE, "Korean", False)
        self.assertEqual(w.pair_button.text(), "Auto-detect \u2192 Korean")

    def test_summon_puts_cursor_at_end(self) -> None:
        w = self.window
        w.summon()
        w.input.setPlainText("hello")
        w.input.moveCursor(self.app_module.QTextCursor.Start)
        w.summon()  # raising the shown window keeps its input
        self.assertEqual(w.input.toPlainText(), "hello")
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
            platform.GlobalHotkey, "is_supported", staticmethod(lambda: True)
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
            platform.GlobalHotkey, "is_supported", staticmethod(lambda: True)
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

    def _record(self, dialog, mods, key, native_key: int) -> None:
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QApplication

        for kind in (QKeyEvent.KeyPress, QKeyEvent.KeyRelease):
            event = QKeyEvent(kind, key, mods, 0, native_key, 0, "")
            QApplication.sendEvent(dialog.editor, event)

    def test_dialog_registers_physical_key_on_other_layouts(self) -> None:
        dialog = self.app_module.HotkeyDialog("", self.window)
        # Dvorak: the key that types "T" sits where U.S. "K" is (kVK_ANSI_K).
        with mock.patch.object(hotkey, "uses_native_keycodes", return_value=True):
            self._record(dialog, Qt.AltModifier, Qt.Key_T, 0x28)
        self.assertEqual(hotkey.from_qt(dialog.editor.keySequence()), hotkey.parse("Option+T"))
        dialog.accept()
        self.assertEqual(dialog.chosen, "Option+K")

    def test_dialog_ignores_focus_traversal_keys(self) -> None:
        dialog = self.app_module.HotkeyDialog("Option+Space", self.window)
        with mock.patch.object(hotkey, "uses_native_keycodes", return_value=True):
            self._record(dialog, Qt.NoModifier, Qt.Key_Tab, 0x30)
        self.assertIsNone(dialog._native_key)
        dialog.accept()
        self.assertEqual(dialog.chosen, "Option+Space")

    def test_dialog_rejects_unknown_physical_key(self) -> None:
        dialog = self.app_module.HotkeyDialog("", self.window)
        with mock.patch.object(hotkey, "uses_native_keycodes", return_value=True):
            self._record(dialog, Qt.AltModifier, Qt.Key_T, 0x5D)  # JIS ¥ key
        with mock.patch.object(self.app_module.QMessageBox, "warning") as warning:
            dialog.accept()
        warning.assert_called_once()
        self.assertNotEqual(dialog.result(), dialog.DialogCode.Accepted)

    def test_dialog_ignores_native_keys_off_cocoa(self) -> None:
        dialog = self.app_module.HotkeyDialog("", self.window)
        with mock.patch.object(hotkey, "uses_native_keycodes", return_value=False):
            self._record(dialog, Qt.AltModifier, Qt.Key_T, 0x28)
        dialog.accept()
        self.assertEqual(dialog.chosen, "Option+T")

    def test_dialog_cancel_restores_registration(self) -> None:
        w = self.window
        calls: list[str] = []
        with mock.patch.object(
            self.app_module.HotkeyDialog, "exec", return_value=0
        ), mock.patch.object(w, "_register_hotkey", lambda: calls.append("restore")):
            w._set_hotkey()
        self.assertEqual(calls, ["restore"])
        self.assertEqual(w.prefs.hotkey, config.DEFAULT_HOTKEY)

    def test_dialog_releases_and_restores_voice_hotkey(self) -> None:
        w = self.window
        calls: list[str] = []
        with mock.patch.object(
            self.app_module.HotkeyDialog, "exec",
            side_effect=lambda: calls.append("dialog") or 0,
        ), mock.patch.object(
            w.voice_hotkey, "unregister", lambda: calls.append("release")
        ), mock.patch.object(
            w, "_register_voice_hotkey", lambda: calls.append("restore")
        ):
            w._set_hotkey()
        self.assertEqual(calls, ["release", "dialog", "restore"])

    def test_owns_voice_hotkey(self) -> None:
        w = self.window
        self.assertIsInstance(w.voice_hotkey, platform.GlobalHotkey)
        self.assertIsNot(w.voice_hotkey, w.global_hotkey)
        self.assertFalse(w.voice_hotkey.is_registered)  # never grabbed headless
        self.assertIn("unavailable", w.hotkey_label.text())


class WindowsMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(hotkey, "is_windows", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_all_canonical_keys_have_virtual_keys(self) -> None:
        self.assertEqual(set(hotkey.VIRTUAL_KEYS), set(hotkey.KEYCODES))
        for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
            self.assertEqual(hotkey.Hotkey(("Ctrl",), c).vk, ord(c))
        for n in range(1, 21):
            self.assertEqual(hotkey.Hotkey((), f"F{n}").vk, 0x70 + n - 1)
        for key, vk in {
            "Space": 0x20, "Return": 0x0D, "Escape": 0x1B, "Tab": 0x09,
            "Delete": 0x08, "Left": 0x25, "Up": 0x26, "Right": 0x27,
            "Down": 0x28, "Home": 0x24, "End": 0x23, "PageUp": 0x21,
            "PageDown": 0x22, ";": 0xBA, "=": 0xBB, ",": 0xBC,
            "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0, "[": 0xDB,
            "\\": 0xDC, "]": 0xDD, "'": 0xDE,
        }.items():
            self.assertEqual(hotkey.Hotkey(("Ctrl",), key).vk, vk, key)

    def test_windows_labels_and_canonical_storage(self) -> None:
        key = hotkey.parse("Cmd+Shift+Option+Ctrl+K")
        self.assertEqual(key.symbols(), "Ctrl+Alt+Shift+Win+K")
        self.assertEqual(str(key), "Ctrl+Option+Shift+Cmd+K")
        self.assertEqual(key.win32_modifiers, 0x0F)
        for name, mask in {"Ctrl": 2, "Option": 1, "Shift": 4, "Cmd": 8}.items():
            self.assertEqual(hotkey.Hotkey((name,), "K").win32_modifiers, mask)
        self.assertEqual(hotkey.parse("Ctrl+Delete").symbols(), "Ctrl+Backspace")

    def test_windows_qt_mapping_and_round_trip(self) -> None:
        for flag, name in (
            (Qt.ControlModifier, "Ctrl"), (Qt.AltModifier, "Option"),
            (Qt.ShiftModifier, "Shift"), (Qt.MetaModifier, "Cmd"),
        ):
            self.assertEqual(str(hotkey.from_qt(QKeyCombination(flag, Qt.Key_K))),
                             f"{name}+K")
        for key in hotkey.KEYCODES:
            value = hotkey.Hotkey(("Ctrl", "Option", "Shift", "Cmd"), key)
            self.assertEqual(hotkey.from_qt(hotkey.to_qt(value)), value)

    def test_windows_validity_and_missing_vk(self) -> None:
        self.assertIsNone(hotkey.parse("Shift+A"))
        self.assertIsNotNone(hotkey.parse("Shift+F12"))
        for modifier in ("Ctrl", "Option", "Cmd"):
            self.assertTrue(hotkey.Hotkey((modifier,), "K").is_valid)
        with mock.patch.dict(hotkey.VIRTUAL_KEYS, {}, clear=True):
            self.assertFalse(hotkey.Hotkey(("Ctrl",), "K").is_valid)
            self.assertIsNone(hotkey.from_qt(QKeyCombination(Qt.ControlModifier, Qt.Key_K)))

    def test_platform_defaults(self) -> None:
        for os_name, show, voice in (
            ("win32", "Ctrl+Shift+Space", "Ctrl+Shift+M"),
            ("darwin", "Shift+Cmd+Space", "Shift+Cmd+M"),
        ):
            with mock.patch("sys.platform", os_name):
                values = runpy.run_path(config.__file__)
            self.assertEqual(values["DEFAULT_HOTKEY"], show)
            self.assertEqual(values["VOICE_HOTKEY"], voice)


class WindowsRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.lib = mock.Mock()
        self.lib.RegisterHotKey.return_value = 1
        self.lib.UnregisterHotKey.return_value = 1
        with mock.patch.object(ctypes, "WinDLL", return_value=self.lib, create=True):
            self.native = windows._Win32()
        for patcher in (
            mock.patch.object(windows, "_win32", self.native),
            mock.patch.object(windows, "is_windows", return_value=True),
            mock.patch.object(hotkey, "is_windows", return_value=True),
            mock.patch.object(ctypes, "get_last_error", return_value=1409, create=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.show = windows.GlobalHotkey()
        self.voice = windows.GlobalHotkey()
        self.addCleanup(self.voice.unregister)
        self.addCleanup(self.show.unregister)

    def _dispatch(self, target, event_type=b"windows_dispatcher_MSG", code=windows.WM_HOTKEY):
        message = windows._MSG()
        message.message = code
        message.wParam = target._id
        return self.native.nativeEventFilter(event_type, ctypes.addressof(message))

    def test_two_hotkeys_route_independently(self) -> None:
        show_calls, voice_calls = [], []
        self.show.activated.connect(lambda: show_calls.append(QThread.currentThread()))
        self.voice.activated.connect(lambda: voice_calls.append(QThread.currentThread()))
        self.assertTrue(self.show.register(hotkey.parse("Ctrl+Shift+Space")))
        self.assertTrue(self.voice.register(hotkey.parse("Ctrl+Shift+M")))
        self.assertNotEqual(self.show._id, self.voice._id)
        self.assertEqual(self.lib.RegisterHotKey.call_args_list, [
            mock.call(None, self.show._id, 0x4006, 0x20),
            mock.call(None, self.voice._id, 0x4006, 0x4D),
        ])
        self.assertEqual(self._dispatch(self.show), (True, 0))
        self.assertEqual(show_calls, [self.app.thread()])
        self.assertEqual(voice_calls, [])
        self.assertEqual(self._dispatch(self.voice), (True, 0))
        self.assertEqual(voice_calls, [self.app.thread()])
        self.assertEqual(self._dispatch(self.show, b"other"), (False, 0))
        self.assertEqual(self._dispatch(self.show, code=0x100), (False, 0))
        self.show.unregister()
        self.assertEqual(self._dispatch(self.show), (False, 0))
        self.assertTrue(self.native.installed)
        self.voice.unregister()
        self.assertFalse(self.native.installed)

    def test_replacement_and_conflict(self) -> None:
        self.assertTrue(self.show.register(hotkey.parse("Ctrl+Shift+Space")))
        self.lib.RegisterHotKey.return_value = 0
        with self.assertLogs(windows.__name__, level="WARNING") as logs:
            self.assertFalse(self.show.register(hotkey.parse("Ctrl+Option+K")))
        self.assertIn("1409", logs.output[0])
        self.lib.UnregisterHotKey.assert_called_once_with(None, self.show._id)
        self.assertFalse(self.show.is_registered)
        self.assertIsNone(self.show.hotkey)
        self.assertFalse(self.native.installed)
        self.lib.RegisterHotKey.return_value = 1
        self.assertTrue(self.show.register(hotkey.parse("Ctrl+Shift+Space")))

    def test_invalid_replacement_unregisters_and_quit_cleans_both(self) -> None:
        self.assertTrue(self.show.register(hotkey.parse("Ctrl+Shift+Space")))
        with self.assertLogs(windows.__name__, level="WARNING"):
            self.assertFalse(self.show.register(hotkey.Hotkey(("Shift",), "K")))
        self.assertFalse(self.show.is_registered)
        self.assertTrue(self.show.register(hotkey.parse("Ctrl+Shift+Space")))
        self.assertTrue(self.voice.register(hotkey.parse("Ctrl+Shift+M")))
        self.app.aboutToQuit.emit()
        self.assertEqual(self.native.targets, {})
        self.show.unregister()
        self.voice.unregister()
        self.assertEqual(self.lib.UnregisterHotKey.call_count, 3)

    def test_qobject_destruction_unregisters(self) -> None:
        from PySide6.QtCore import QCoreApplication, QEvent

        self.assertTrue(self.show.register(hotkey.parse("Ctrl+K")))
        self.show.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.lib.UnregisterHotKey.assert_called_once_with(None, self.show._id)
        self.assertEqual(self.native.targets, {})

    def test_registration_requires_gui_thread(self) -> None:
        with mock.patch.object(windows, "_on_gui_thread", return_value=False):
            with self.assertLogs(windows.__name__, level="ERROR"):
                self.assertFalse(self.show.register(hotkey.parse("Ctrl+K")))
        self.lib.RegisterHotKey.assert_not_called()


@unittest.skipUnless(_HEADLESS, "set QT_QPA_PLATFORM=offscreen for window tests")
class WindowsWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from type_fast import app

        self.app_module = app
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patcher in (
            mock.patch.object(hotkey, "is_windows", return_value=True),
            mock.patch.object(settings, "SETTINGS_FILE", Path(self.tmp.name) / "settings.json"),
            mock.patch.object(app, "threading", types.SimpleNamespace(Thread=mock.Mock())),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = app.MainWindow()
        self.addCleanup(self.window.close)

    def test_recorder_names_validity_and_layout_key(self) -> None:
        from PySide6.QtWidgets import QLabel

        dialog = self.app_module.HotkeyDialog("", self.window)
        self.addCleanup(dialog.close)
        text = dialog.findChild(QLabel).text()
        self.assertIn("Include Ctrl, Alt, or Win", text)
        self.assertIn("Avoid Win shortcuts", text)
        dialog.editor.setKeySequence(
            QKeySequence(QKeyCombination(Qt.ShiftModifier, Qt.Key_K))
        )
        with mock.patch.object(self.app_module.QMessageBox, "warning") as warning:
            dialog.accept()
        self.assertIn("Include Ctrl, Alt, or Win", warning.call_args.args[2])
        dialog.editor.setKeySequence(
            QKeySequence(QKeyCombination(Qt.ControlModifier | Qt.AltModifier, Qt.Key_K))
        )
        dialog.accept()
        self.assertEqual(dialog.chosen, "Ctrl+Option+K")
        self.assertFalse(hotkey.uses_native_keycodes())

    def test_recorder_preserves_windows_vk_on_other_layouts(self) -> None:
        for qt_key, vk, expected in (
            (Qt.Key_Slash, 0x37, "Ctrl+Shift+7"),  # German Shift+7
            (Qt.Key_Ampersand, 0x31, "Ctrl+Shift+1"),  # AZERTY digit row
        ):
            with self.subTest(vk=vk):
                dialog = self.app_module.HotkeyDialog("", self.window)
                self.addCleanup(dialog.close)
                WindowHotkeyTests._record(
                    self, dialog, Qt.ControlModifier | Qt.ShiftModifier, qt_key, vk
                )
                dialog.accept()
                self.assertEqual(dialog.chosen, expected)
                with mock.patch.object(self.window.global_hotkey, "register",
                                       return_value=True) as register:
                    self.assertTrue(self.window._apply_hotkey(dialog.chosen))
                self.assertEqual(register.call_args.args[0].vk, vk)

    def test_recorder_rejects_unknown_windows_vk(self) -> None:
        dialog = self.app_module.HotkeyDialog("", self.window)
        self.addCleanup(dialog.close)
        WindowHotkeyTests._record(self, dialog, Qt.ControlModifier, Qt.Key_K, 0xFF)
        with mock.patch.object(self.app_module.QMessageBox, "warning") as warning:
            dialog.accept()
        warning.assert_called_once()
        self.assertNotEqual(dialog.result(), dialog.DialogCode.Accepted)

    def test_apply_save_footer_conflict_restore_disable_and_quit(self) -> None:
        w = self.window
        with mock.patch.object(platform.GlobalHotkey, "is_supported", return_value=True), \
                mock.patch.object(w.global_hotkey, "register", return_value=True) as register, \
                mock.patch.object(platform.GlobalHotkey, "is_registered",
                                  new_callable=mock.PropertyMock, return_value=True):
            self.assertTrue(w._apply_hotkey("Ctrl+Option+K"))
            self.assertEqual(register.call_args.args[0], hotkey.parse("Ctrl+Option+K"))
            self.assertEqual(settings.load().hotkey, "Ctrl+Option+K")
            self.assertIn("Ctrl+Alt+K", w.hotkey_label.text())
            with mock.patch.object(w.global_hotkey, "register", side_effect=[False, True]), \
                    mock.patch.object(self.app_module.QMessageBox, "warning") as warning:
                self.assertFalse(w._apply_hotkey("Ctrl+Option+J"))
            self.assertIn("Keeping Ctrl+Alt+K", warning.call_args.args[2])
            self.assertIn("Windows or another app", warning.call_args.args[2])
            self.assertNotIn("macOS", warning.call_args.args[2])
            self.assertEqual(settings.load().hotkey, "Ctrl+Option+K")
        with mock.patch.object(w.global_hotkey, "unregister") as unregister:
            self.assertTrue(w._apply_hotkey(""))
            unregister.assert_called()
        self.assertEqual(settings.load().hotkey, "")
        self.assertEqual(w.hotkey_label.text(), "Hotkey off")


if __name__ == "__main__":
    unittest.main()

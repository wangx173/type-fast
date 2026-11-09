"""Backend selection and portable application integration."""

from __future__ import annotations

import os
import types
import unittest
from unittest import mock

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from type_fast import autopaste, hotkey, platform
from type_fast.platform import macos, null, windows


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(platform, "_backend", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_os_and_qt_platform_must_both_match(self) -> None:
        for os_name, qt_name, expected in (
            ("darwin", "cocoa", macos),
            ("win32", "windows", windows),
            ("darwin", "offscreen", null),
            ("win32", "offscreen", null),
            ("linux", "offscreen", null),
            ("linux", "xcb", null),
            ("darwin", "windows", null),
            ("win32", "cocoa", null),
        ):
            with self.subTest(os=os_name, qt=qt_name), \
                    mock.patch.object(platform, "_backend", None), \
                    mock.patch.object(platform, "sys", types.SimpleNamespace(platform=os_name)), \
                    mock.patch.object(platform.QGuiApplication, "instance", return_value=object()), \
                    mock.patch.object(platform.QGuiApplication, "platformName", return_value=qt_name):
                self.assertIs(platform._get_backend(), expected)

    def test_pre_application_calls_do_not_cache_null(self) -> None:
        with mock.patch.object(platform.QGuiApplication, "instance", return_value=None):
            self.assertIs(platform._get_backend(), null)
            self.assertFalse(platform.GlobalHotkey.is_supported())
            self.assertIsNone(platform._backend)
        with mock.patch.object(platform, "sys", types.SimpleNamespace(platform="darwin")), \
                mock.patch.object(platform.QGuiApplication, "instance", return_value=object()), \
                mock.patch.object(platform.QGuiApplication, "platformName", return_value="cocoa"):
            self.assertIs(platform._get_backend(), macos)

    def test_backend_is_selected_once(self) -> None:
        with mock.patch.object(platform, "sys", types.SimpleNamespace(platform="win32")), \
                mock.patch.object(platform.QGuiApplication, "instance", return_value=object()), \
                mock.patch.object(platform.QGuiApplication, "platformName", return_value="windows"):
            self.assertIs(platform._get_backend(), windows)
        with mock.patch.object(platform.QGuiApplication, "platformName", return_value="offscreen"):
            self.assertIs(platform._get_backend(), windows)

    def test_null_and_windows_are_safe_noops(self) -> None:
        for backend in (null, windows):
            with self.subTest(backend=backend.__name__), \
                    mock.patch.object(platform, "_backend", backend), \
                    mock.patch.object(macos.ctypes, "CDLL") as cdll:
                gh = platform.GlobalHotkey()
                self.assertFalse(gh.is_supported())
                self.assertFalse(gh.register(hotkey.parse("Option+Space")))
                self.assertFalse(gh.is_registered)
                self.assertIsNone(gh.hotkey)
                gh.unregister()
                platform.activate_app()
                platform.hide_app()
                self.assertIsNone(platform.clipboard_change_count())
                self.assertIsNone(platform.frontmost_app_pid())
                self.assertIsNone(platform.input_event_count())
                self.assertIsNone(platform.paste_settings_url())
                self.assertFalse(platform.paste_supported())
                self.assertFalse(platform.paste_permission_granted())
                self.assertFalse(platform.send_paste())
                self.assertFalse(hotkey.uses_native_keycodes())
                self.assertFalse(autopaste.is_supported())
                self.assertFalse(autopaste.has_permission())
                self.assertFalse(autopaste.send_paste())
                cdll.assert_not_called()

    def test_hotkey_facade_forwards_registration_and_signal(self) -> None:
        class FakeHotkey(QObject):
            activated = Signal()

            def __init__(self, parent: QObject) -> None:
                super().__init__(parent)
                self.hotkey = None

            @staticmethod
            def is_supported() -> bool:
                return True

            @property
            def is_registered(self) -> bool:
                return self.hotkey is not None

            def register(self, key: hotkey.Hotkey) -> bool:
                self.hotkey = key
                return True

            def unregister(self) -> None:
                self.hotkey = None

        with mock.patch.object(platform.QGuiApplication, "instance", return_value=None):
            gh = platform.GlobalHotkey()
            callback = mock.Mock()
            gh.activated.connect(callback)
            key = hotkey.parse("Option+Space")
            self.assertFalse(gh.register(key))
            self.assertFalse(gh.is_registered)
            self.assertIsNone(gh.hotkey)
            gh.unregister()
            self.assertEqual(gh.children(), [])
            self.assertIsNone(platform._backend)

        with mock.patch.object(platform, "_backend", types.SimpleNamespace(GlobalHotkey=FakeHotkey)):
            self.assertTrue(gh.is_supported())
            self.assertTrue(gh.register(key))
            self.assertEqual(gh.hotkey, key)
            self.assertTrue(gh.is_registered)
            gh.children()[0].activated.emit()
            callback.assert_called_once_with()
            gh.unregister()
            self.assertFalse(gh.is_registered)
            self.assertIsNone(gh.hotkey)

    def test_native_operations_forward_to_selected_backend(self) -> None:
        backend = mock.Mock()
        with mock.patch.object(platform, "_backend", backend):
            platform.activate_app()
            platform.hide_app()
            for name in (
                "clipboard_change_count", "frontmost_app_pid", "input_event_count",
                "paste_supported", "paste_permission_granted", "send_paste",
                "uses_native_keycodes",
            ):
                self.assertIs(getattr(platform, name)(), getattr(backend, name).return_value)
                getattr(backend, name).assert_called_once_with()
            self.assertIs(platform.paste_settings_url(), backend.PASTE_SETTINGS_URL)
        backend.activate_app.assert_called_once_with()
        backend.hide_app.assert_called_once_with()


@unittest.skipUnless(os.environ.get("QT_QPA_PLATFORM") == "offscreen", "headless window tests")
class PortableWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_windows_translation_clipboard_and_escape(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from type_fast import app, settings

        with mock.patch.object(platform, "_backend", windows), \
                mock.patch.object(settings, "load", return_value=settings.Settings()), \
                mock.patch.object(app, "threading", types.SimpleNamespace(Thread=mock.Mock())), \
                mock.patch.object(app.QMessageBox, "warning") as warning:
            window = app.MainWindow()
            try:
                window.summon()
                self.assertTrue(QTest.qWaitForWindowActive(window))
                self.assertIn("unavailable", window.hotkey_label.text())
                self.assertFalse(window.global_hotkey.is_registered)
                self.assertFalse(window.voice_hotkey.is_registered)
                self.assertFalse(window._needs_paste_permission())
                window.input.setPlainText("Hello.")
                window.bridge.delta.emit(window._request_id, "Bonjour.")
                window.bridge.finished.emit(window._request_id, "Bonjour.")
                self.assertEqual(window.output.toPlainText(), "Bonjour.")
                self.assertEqual(QApplication.clipboard().text(), "Bonjour.")
                window.input.setFocus()
                QTest.keyClick(window.input, Qt.Key_Escape)
                self.assertFalse(window.isVisible())
                warning.assert_not_called()
            finally:
                window.close()
                window.deleteLater()

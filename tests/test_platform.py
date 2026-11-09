"""Backend selection and portable application integration."""

from __future__ import annotations

import os
import ctypes
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


class WindowsNativeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lib = mock.Mock()
        self.lib.GetAsyncKeyState.return_value = 0
        with mock.patch.object(ctypes, "WinDLL", return_value=self.lib, create=True):
            self.native = windows._Win32()
        for patcher in (
            mock.patch.object(windows, "_win32", self.native),
            mock.patch.object(windows, "is_windows", return_value=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _pid(self, hwnd, pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32)).contents.value = (
            os.getpid() if hwnd == 20 else 100
        )
        return 1

    def test_activation_remembers_external_window_and_restore_consumes_it(self) -> None:
        self.lib.GetWindowThreadProcessId.side_effect = self._pid
        self.lib.GetForegroundWindow.return_value = 10
        self.lib.SetForegroundWindow.return_value = 1
        self.lib.IsWindow.return_value = 1
        window = mock.Mock()
        window.winId.return_value = 20
        windows.activate_app(window)
        self.assertEqual(self.native.previous_window, 10)
        self.lib.GetForegroundWindow.return_value = 20
        windows.activate_app()
        self.assertEqual(self.native.previous_window, 10)
        self.lib.GetForegroundWindow.return_value = 10
        self.assertTrue(windows.hide_app())
        self.assertIsNone(self.native.previous_window)
        self.assertEqual(self.lib.ShowWindow.call_args_list,
                         [mock.call(20, 5), mock.call(20, 5), mock.call(20, 0)])
        self.assertEqual(self.lib.SetForegroundWindow.call_args_list,
                         [mock.call(20), mock.call(20), mock.call(10)])
        self.assertFalse(windows.hide_app())

    def test_activation_falls_back_to_qt_and_invalid_restore_is_skipped(self) -> None:
        self.lib.GetWindowThreadProcessId.side_effect = self._pid
        self.lib.GetForegroundWindow.return_value = 10
        self.lib.SetForegroundWindow.return_value = 0
        window = mock.Mock()
        window.winId.return_value = 20
        with self.assertLogs(windows.__name__, level="WARNING"):
            windows.activate_app(window)
        window.raise_.assert_called_once_with()
        window.activateWindow.assert_called_once_with()
        self.lib.IsWindow.return_value = 0
        self.lib.SetForegroundWindow.reset_mock()
        self.assertFalse(windows.hide_app())
        self.lib.SetForegroundWindow.assert_not_called()

    def test_failed_restoration_returns_false(self) -> None:
        self.native.previous_window = 10
        self.lib.IsWindow.return_value = 1
        self.lib.SetForegroundWindow.return_value = 0
        with self.assertLogs(windows.__name__, level="WARNING"):
            self.assertFalse(windows.hide_app())

    def test_unknown_foreground_discards_prior_destination(self) -> None:
        window = mock.Mock()
        window.winId.return_value = 20
        self.lib.SetForegroundWindow.return_value = 1
        self.lib.IsWindow.return_value = 1
        for hwnd in (None, 30):
            with self.subTest(hwnd=hwnd):
                self.native.previous_window = 10
                self.lib.GetForegroundWindow.return_value = hwnd
                self.lib.GetWindowThreadProcessId.return_value = 0
                if hwnd:
                    with self.assertLogs(windows.__name__, level="WARNING"):
                        windows.activate_app(window)
                else:
                    windows.activate_app(window)
                self.assertIsNone(self.native.previous_window)
                self.lib.SetForegroundWindow.reset_mock()
                self.assertFalse(windows.hide_app())
                self.lib.SetForegroundWindow.assert_not_called()

    def test_clipboard_foreground_and_last_input_wrappers(self) -> None:
        self.lib.GetClipboardSequenceNumber.return_value = 0xFFFFFFFF
        self.lib.GetForegroundWindow.return_value = 10
        self.lib.GetWindowThreadProcessId.side_effect = self._pid

        def last_input(pointer):
            info = ctypes.cast(pointer, ctypes.POINTER(windows._LASTINPUTINFO)).contents
            self.assertEqual(info.cbSize, 8)
            info.dwTime = 0xFFFFFFFF
            return 1

        self.lib.GetLastInputInfo.side_effect = last_input
        self.assertEqual(windows.clipboard_change_count(), 0xFFFFFFFF)
        self.lib.GetClipboardSequenceNumber.return_value = 0
        with self.assertLogs(windows.__name__, level="WARNING"):
            self.assertIsNone(windows.clipboard_change_count())
        self.assertEqual(windows.frontmost_app_pid(), 100)
        self.assertEqual(windows.input_event_count(), 0xFFFFFFFF)
        self.assertTrue(windows.paste_supported())
        self.assertTrue(windows.paste_permission_granted())
        self.lib.GetForegroundWindow.return_value = None
        self.assertIsNone(windows.frontmost_app_pid())
        self.lib.GetLastInputInfo.side_effect = None
        self.lib.GetLastInputInfo.return_value = 0
        with self.assertLogs(windows.__name__, level="WARNING"):
            self.assertIsNone(windows.input_event_count())

    def test_send_input_sequence_and_native_layout(self) -> None:
        self.lib.SendInput.return_value = 4
        self.assertTrue(windows.send_paste())
        count, events, size = self.lib.SendInput.call_args.args
        self.assertEqual(count, 4)
        self.assertEqual(size, 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        self.assertEqual([(e.type, e.ki.wVk, e.ki.dwFlags) for e in events],
                         [(1, 0x11, 0), (1, 0x56, 0), (1, 0x56, 2), (1, 0x11, 2)])
        self.assertTrue(all(e.ki.wScan == e.ki.time == e.ki.dwExtraInfo == 0
                            for e in events))
        self.assertIs(self.lib.GetForegroundWindow.restype, ctypes.c_void_p)
        self.assertEqual(self.lib.SendInput.argtypes,
                         [ctypes.c_uint32, ctypes.POINTER(windows._INPUT), ctypes.c_int])

    def test_blocked_or_partial_send_input_releases_keys_and_keeps_clipboard(self) -> None:
        for sent in (0, 1, 2, 3):
            with self.subTest(sent=sent):
                self.lib.SendInput.reset_mock()
                self.lib.SendInput.return_value = sent
                with self.assertLogs(windows.__name__, level="WARNING"):
                    self.assertFalse(windows.send_paste())
                count, events, _ = self.lib.SendInput.call_args.args
                self.assertEqual(count, 2)
                self.assertEqual([(e.ki.wVk, e.ki.dwFlags) for e in events],
                                 [(0x56, 2), (0x11, 2)])
        self.lib.SetClipboardData.assert_not_called()

    def test_send_input_skips_each_held_modifier(self) -> None:
        for key in windows._MODIFIER_KEYS:
            with self.subTest(key=key):
                self.lib.GetAsyncKeyState.side_effect = lambda vk: 0x8000 if vk == key else 0
                with self.assertLogs(windows.__name__, level="WARNING"):
                    self.assertFalse(windows.send_paste())
        self.lib.SendInput.assert_not_called()

    def test_partial_send_reports_incomplete_cleanup(self) -> None:
        for released in (0, 1, 2):
            with self.subTest(released=released):
                self.lib.SendInput.side_effect = [1, released]
                with self.assertLogs(windows.__name__, level="WARNING") as logs:
                    self.assertFalse(windows.send_paste())
                cleanup_logs = [line for line in logs.output if "cleanup inserted" in line]
                self.assertEqual(len(cleanup_logs), 0 if released == 2 else 1)

    def test_key_wait_polls_registered_trigger_and_all_modifiers(self) -> None:
        import weakref

        target = mock.Mock()
        target.hotkey.vk = 0x7B  # custom F12 hotkey
        self.native.targets[1] = weakref.ref(target)
        down = {0x7B}
        self.lib.GetAsyncKeyState.side_effect = lambda vk: 0x8000 if vk in down else 1
        callbacks = []
        result = mock.Mock()
        with mock.patch.object(windows.QTimer, "singleShot",
                               side_effect=lambda delay, cb: callbacks.append((delay, cb))), \
                mock.patch.object(windows.time, "monotonic", return_value=0):
            windows.wait_for_paste_keys(result)
            result.assert_not_called()
            self.assertEqual(callbacks[0][0], 20)
            down.clear()
            callbacks.pop()[1]()
        result.assert_called_once_with(True)
        queried = {call.args[0] for call in self.lib.GetAsyncKeyState.call_args_list}
        self.assertEqual(queried, {*windows._MODIFIER_KEYS, 0x7B})

    def test_key_wait_timeout_is_one_second_even_if_timer_is_late(self) -> None:
        self.lib.GetAsyncKeyState.return_value = 0x8000
        callbacks = []
        now = [0.0]
        result = mock.Mock()
        with mock.patch.object(windows.QTimer, "singleShot",
                               side_effect=lambda delay, cb: callbacks.append((delay, cb))), \
                mock.patch.object(windows.time, "monotonic", side_effect=lambda: now[0]):
            windows.wait_for_paste_keys(result)
            self.assertEqual(callbacks[0][0], 20)
            now[0] = 1.02
            self.lib.GetAsyncKeyState.return_value = 0
            with self.assertLogs(windows.__name__, level="WARNING"):
                callbacks.pop()[1]()
        result.assert_called_once_with(False)


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

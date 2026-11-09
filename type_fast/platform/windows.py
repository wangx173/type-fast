"""Win32 global hotkeys, foreground restoration, and clipboard-based auto-paste."""

from __future__ import annotations

import ctypes
import itertools
import logging
import os
import sys
import time
import weakref
from collections.abc import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QThread, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from ..hotkey import Hotkey
from .null import (
    PASTE_SETTINGS_URL,
    uses_native_keycodes,
)

_log = logging.getLogger(__name__)
WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
_MODIFIER_KEYS = (0x10, 0x11, 0x12, 0x5B, 0x5C)
_KEY_RELEASE_TIMEOUT = 1.0
_KEY_RELEASE_POLL_MS = 20


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("dwTime", ctypes.c_uint32)]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_int32), ("dy", ctypes.c_int32),
        ("mouseData", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_uint32), ("wParamL", ctypes.c_uint16),
        ("wParamH", ctypes.c_uint16),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", ctypes.c_uint32), ("data", _INPUTUNION)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


class _MSG(ctypes.Structure):
    # Fixed-width Win32 fields, with pointer-sized WPARAM/LPARAM on 32/64 bit.
    _fields_ = [
        ("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint32),
        ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint32), ("pt", _POINT),
    ]


def is_windows() -> bool:
    app = QGuiApplication.instance()
    return (
        sys.platform == "win32" and app is not None
        and QGuiApplication.platformName() == "windows"
    )


def _on_gui_thread() -> bool:
    app = QGuiApplication.instance()
    return app is not None and QThread.currentThread() == app.thread()


class _Win32(QAbstractNativeEventFilter):
    """One retained filter routes thread hotkeys to weak QObject targets."""

    def __init__(self) -> None:
        super().__init__()
        lib = ctypes.WinDLL("user32", use_last_error=True)
        lib.RegisterHotKey.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32,
        ]
        lib.RegisterHotKey.restype = ctypes.c_int
        lib.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.UnregisterHotKey.restype = ctypes.c_int
        for name, args, result in (
            ("GetForegroundWindow", [], ctypes.c_void_p),
            ("ShowWindow", [ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
            ("SetForegroundWindow", [ctypes.c_void_p], ctypes.c_int),
            ("IsWindow", [ctypes.c_void_p], ctypes.c_int),
            ("GetWindowThreadProcessId",
             [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)], ctypes.c_uint32),
            ("GetClipboardSequenceNumber", [], ctypes.c_uint32),
            ("GetLastInputInfo", [ctypes.POINTER(_LASTINPUTINFO)], ctypes.c_int),
            ("GetAsyncKeyState", [ctypes.c_int], ctypes.c_int16),
            ("SendInput", [ctypes.c_uint32, ctypes.POINTER(_INPUT), ctypes.c_int],
             ctypes.c_uint32),
        ):
            function = getattr(lib, name)
            function.argtypes = args
            function.restype = result
        self.lib = lib
        self.previous_window: int | None = None
        self.app_window: weakref.ReferenceType[QWidget] | None = None
        self.targets: dict[int, weakref.ReferenceType[GlobalHotkey]] = {}
        self.installed = False

    def ensure_filter(self) -> None:
        if not self.installed:
            QGuiApplication.instance().installNativeEventFilter(self)
            self.installed = True

    def remove_filter_if_idle(self) -> None:
        if self.installed and not self.targets:
            app = QGuiApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self)
            self.installed = False

    def nativeEventFilter(self, event_type, message):
        if event_type not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        msg = _MSG.from_address(int(message))
        if msg.message != WM_HOTKEY or msg.hwnd:
            return False, 0
        ref = self.targets.get(msg.wParam)
        target = ref() if ref is not None else None
        if target is None:
            return False, 0
        target.activated.emit()
        return True, 0


_win32: _Win32 | None = None


def _load_win32() -> _Win32 | None:
    global _win32
    if _win32 is None:
        try:
            _win32 = _Win32()
        except (OSError, AttributeError):
            _log.exception("Could not load Windows native bindings")
    return _win32


def _native() -> _Win32 | None:
    return _load_win32() if is_windows() else None


def _window_pid(lib, hwnd: int | None) -> int | None:
    if not hwnd:
        return None
    pid = ctypes.c_uint32()
    if not lib.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or not pid.value:
        _log.warning("Could not determine the foreground window process")
        return None
    return pid.value


def activate_app(window: QWidget | None = None) -> None:
    native = _native()
    if native is None:
        return
    if window is not None:
        native.app_window = weakref.ref(window)
    window = native.app_window() if native.app_window is not None else None
    if window is None:
        return
    foreground = native.lib.GetForegroundWindow()
    pid = _window_pid(native.lib, foreground)
    if pid is not None and pid != os.getpid():
        native.previous_window = foreground
    hwnd = int(window.winId())
    native.lib.ShowWindow(hwnd, 5)  # SW_SHOW
    if not native.lib.SetForegroundWindow(hwnd):
        _log.warning("SetForegroundWindow failed while showing Type Fast")
        window.raise_()
        window.activateWindow()


def hide_app() -> bool:
    native = _native()
    if native is None:
        return False
    window = native.app_window() if native.app_window is not None else None
    if window is not None:
        native.lib.ShowWindow(int(window.winId()), 0)  # SW_HIDE
    previous, native.previous_window = native.previous_window, None
    if previous and native.lib.IsWindow(previous):
        if not native.lib.SetForegroundWindow(previous):
            _log.warning("SetForegroundWindow failed while restoring the previous app")
            return False
        return native.lib.GetForegroundWindow() == previous
    return False


def clipboard_change_count() -> int | None:
    native = _native()
    return native.lib.GetClipboardSequenceNumber() if native is not None else None


def frontmost_app_pid() -> int | None:
    native = _native()
    if native is None:
        return None
    return _window_pid(native.lib, native.lib.GetForegroundWindow())


def input_event_count() -> int | None:
    native = _native()
    if native is None:
        return None
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not native.lib.GetLastInputInfo(ctypes.byref(info)):
        _log.warning("GetLastInputInfo failed")
        return None
    return info.dwTime


def paste_supported() -> bool:
    return _native() is not None


def paste_permission_granted() -> bool:
    return paste_supported()


def _paste_keys(native: _Win32) -> tuple[int, ...]:
    keys = set(_MODIFIER_KEYS)
    for ref in native.targets.values():
        target = ref()
        if target is not None and target.hotkey is not None:
            vk = target.hotkey.vk
            if vk is not None:
                keys.add(vk)
    return tuple(sorted(keys))


def _keys_down(native: _Win32, keys: tuple[int, ...]) -> bool:
    return any(native.lib.GetAsyncKeyState(key) & 0x8000 for key in keys)


def wait_for_paste_keys(callback: Callable[[bool], None]) -> None:
    """Wait without blocking Qt; the triggering keys must also be released."""
    native = _native()
    if native is None:
        callback(False)
        return
    keys = _paste_keys(native)
    deadline = time.monotonic() + _KEY_RELEASE_TIMEOUT

    def poll() -> None:
        if time.monotonic() > deadline:
            _log.warning("Auto-paste skipped: hotkey keys were not released within 1 second")
            callback(False)
        elif not _keys_down(native, keys):
            callback(True)
        elif time.monotonic() >= deadline:
            _log.warning("Auto-paste skipped: hotkey keys were not released within 1 second")
            callback(False)
        else:
            QTimer.singleShot(_KEY_RELEASE_POLL_MS, poll)

    poll()


def send_paste() -> bool:
    native = _native()
    if native is None:
        return False
    if _keys_down(native, _paste_keys(native)):
        _log.warning("Auto-paste skipped: a shortcut key is still held")
        return False
    events = (_INPUT * 4)()
    for event, vk, flags in zip(events, (0x11, 0x56, 0x56, 0x11), (0, 0, 2, 2)):
        event.type = 1  # INPUT_KEYBOARD
        event.ki = _KEYBDINPUT(vk, 0, flags, 0, 0)
    sent = native.lib.SendInput(4, events, ctypes.sizeof(_INPUT))
    if sent != 4:
        _log.warning("SendInput inserted %s of 4 paste events; text remains on the clipboard", sent)
        # A partial insertion may have left Ctrl or V down. Release only our keys.
        releases = (_INPUT * 2)(events[2], events[3])
        native.lib.SendInput(2, releases, ctypes.sizeof(_INPUT))
        return False
    return True


def _release(hotkey_id: int) -> None:
    win32 = _win32
    if win32 is None or hotkey_id not in win32.targets:
        return
    if not win32.lib.UnregisterHotKey(None, hotkey_id):
        _log.warning("UnregisterHotKey failed for id %s: error %s",
                     hotkey_id, ctypes.get_last_error())
    win32.targets.pop(hotkey_id)
    win32.remove_filter_if_idle()


class GlobalHotkey(QObject):
    """A GUI-thread Win32 hotkey with independent registration and activation."""

    activated = Signal()
    _ids = itertools.count(1)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._id = next(self._ids)
        self._hotkey: Hotkey | None = None
        hotkey_id = self._id
        self.destroyed.connect(lambda: _release(hotkey_id))
        app = QGuiApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.unregister)

    @staticmethod
    def is_supported() -> bool:
        return is_windows() and _load_win32() is not None

    @property
    def is_registered(self) -> bool:
        return _win32 is not None and self._id in _win32.targets

    @property
    def hotkey(self) -> Hotkey | None:
        return self._hotkey if self.is_registered else None

    def register(self, hotkey: Hotkey) -> bool:
        if not _on_gui_thread():
            _log.error("Windows hotkeys must be registered on the GUI thread")
            return False
        self.unregister()
        if not hotkey.is_valid or hotkey.vk is None or self._id > 0xBFFF:
            _log.warning("Invalid Windows hotkey or exhausted application hotkey IDs")
            return False
        if not self.is_supported():
            return False
        win32 = _load_win32()
        if win32 is None:
            return False
        win32.ensure_filter()
        if not win32.lib.RegisterHotKey(
            None, self._id, hotkey.win32_modifiers | MOD_NOREPEAT, hotkey.vk
        ):
            _log.warning("RegisterHotKey failed for %s: error %s",
                         hotkey, ctypes.get_last_error())
            win32.remove_filter_if_idle()
            return False
        win32.targets[self._id] = weakref.ref(self)
        self._hotkey = hotkey
        return True

    def unregister(self) -> None:
        if self.is_registered and not _on_gui_thread():
            _log.error("Windows hotkeys must be unregistered on the GUI thread")
            return
        _release(self._id)
        self._hotkey = None

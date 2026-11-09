"""Win32 global hotkeys; foreground restoration and auto-paste remain deferred."""

from __future__ import annotations

import ctypes
import itertools
import logging
import sys
import weakref

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QThread, Signal
from PySide6.QtGui import QGuiApplication

from ..hotkey import Hotkey
from .null import (
    PASTE_SETTINGS_URL,
    activate_app,
    clipboard_change_count,
    frontmost_app_pid,
    hide_app,
    input_event_count,
    paste_permission_granted,
    paste_supported,
    send_paste,
    uses_native_keycodes,
)

_log = logging.getLogger(__name__)
WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000


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
        self.lib = lib
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
            _log.exception("Could not load Windows global hotkey bindings")
    return _win32


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

"""OS integration, selected once after the Qt GUI application starts.

Imports happen before QApplication exists. Calls made before then use null
without caching it, so a later Cocoa or Windows application selects correctly.
Offscreen and all other unsupported Qt platforms always use null.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Protocol

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication

from ..hotkey import Hotkey
from . import null

_backend: ModuleType | None = None


def _get_backend() -> ModuleType:
    global _backend
    if _backend is None:
        if QGuiApplication.instance() is None:
            return null
        qt_platform = QGuiApplication.platformName()
        if sys.platform == "darwin" and qt_platform == "cocoa":
            from . import macos

            _backend = macos
        elif sys.platform == "win32" and qt_platform == "windows":
            from . import windows

            _backend = windows
        else:
            _backend = null
    return _backend


class _HotkeyBackend(Protocol):
    @property
    def is_registered(self) -> bool: ...

    @property
    def hotkey(self) -> Hotkey | None: ...

    def register(self, hotkey: Hotkey) -> bool: ...

    def unregister(self) -> None: ...


class GlobalHotkey(QObject):
    """A backend-independent global hotkey with a Qt activation signal."""

    activated = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._impl: _HotkeyBackend | None = None

    @staticmethod
    def is_supported() -> bool:
        return _get_backend().GlobalHotkey.is_supported()

    @property
    def is_registered(self) -> bool:
        return self._impl is not None and self._impl.is_registered

    @property
    def hotkey(self) -> Hotkey | None:
        return self._impl.hotkey if self._impl is not None else None

    def register(self, hotkey: Hotkey) -> bool:
        if self._impl is None:
            backend_module = _get_backend()
            if _backend is None:
                return False
            backend = backend_module.GlobalHotkey(self)
            backend.activated.connect(self.activated.emit)
            self._impl = backend
        return self._impl.register(hotkey)

    def unregister(self) -> None:
        if self._impl is not None:
            self._impl.unregister()


def activate_app() -> None:
    _get_backend().activate_app()


def hide_app() -> None:
    _get_backend().hide_app()


def clipboard_change_count() -> int | None:
    return _get_backend().clipboard_change_count()


def frontmost_app_pid() -> int | None:
    return _get_backend().frontmost_app_pid()


def uses_native_keycodes() -> bool:
    return _get_backend().uses_native_keycodes()


def paste_supported() -> bool:
    return _get_backend().paste_supported()


def paste_permission_granted() -> bool:
    return _get_backend().paste_permission_granted()


def input_event_count() -> int | None:
    return _get_backend().input_event_count()


def send_paste() -> bool:
    return _get_backend().send_paste()


def paste_settings_url() -> str | None:
    return _get_backend().PASTE_SETTINGS_URL

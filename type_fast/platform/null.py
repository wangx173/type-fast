"""Safe no-op integration for unsupported or headless Qt platforms."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..hotkey import Hotkey

PASTE_SETTINGS_URL: str | None = None


class GlobalHotkey(QObject):
    activated = Signal()

    @staticmethod
    def is_supported() -> bool:
        return False

    @property
    def is_registered(self) -> bool:
        return False

    @property
    def hotkey(self) -> Hotkey | None:
        return None

    def register(self, hotkey: Hotkey) -> bool:
        return False

    def unregister(self) -> None:
        pass


def activate_app() -> None:
    pass


def hide_app() -> None:
    pass


def clipboard_change_count() -> int | None:
    return None


def frontmost_app_pid() -> int | None:
    return None


def uses_native_keycodes() -> bool:
    return False


def paste_supported() -> bool:
    return False


def paste_permission_granted() -> bool:
    return False


def input_event_count() -> int | None:
    return None


def send_paste() -> bool:
    return False

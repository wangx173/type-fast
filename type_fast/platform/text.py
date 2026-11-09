"""Platform-specific UI wording, independent of the native Qt backend."""

from __future__ import annotations

import sys
from dataclasses import dataclass


def is_windows() -> bool:
    return sys.platform == "win32"


@dataclass(frozen=True)
class PlatformText:
    options_shortcut: str
    paste_key: str
    microphone_privacy: str
    input_device: str
    microphone_settings_url: str | None


_MACOS = PlatformText(
    "\u2318L",
    "\u2318V",
    "System Settings \u203a Privacy & Security \u203a Microphone",
    "System Settings \u203a Sound",
    None,
)
_WINDOWS = PlatformText(
    "Ctrl+L",
    "Ctrl+V",
    "Settings \u203a Privacy & security \u203a Microphone",
    "Settings \u203a System \u203a Sound",
    "ms-settings:privacy-microphone",
)


def ui_text() -> PlatformText:
    return _WINDOWS if is_windows() else _MACOS

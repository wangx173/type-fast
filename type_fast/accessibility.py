"""macOS Accessibility permission helpers.

Global hotkey monitoring and simulated keystrokes (used for auto-paste) both
require the app to be trusted for Accessibility access. This module wraps the
relevant ApplicationServices calls so the rest of the app can check and
request that permission without sprinkling PyObjC calls everywhere.
"""

from __future__ import annotations

try:
    from ApplicationServices import (
        AXIsProcessTrusted,
        AXIsProcessTrustedWithOptions,
    )
    from CoreFoundation import CFDictionaryCreate

    _AVAILABLE = True
except ImportError:  # pragma: no cover - non-macOS or missing pyobjc extras
    _AVAILABLE = False


def available() -> bool:
    """Return True if the Accessibility APIs are importable on this platform."""
    return _AVAILABLE


def is_trusted() -> bool:
    """Return True if this process currently has Accessibility access.

    Returns False (rather than raising) when the Accessibility APIs are not
    available, e.g. when running on a non-macOS platform or without the
    optional PyObjC Accessibility extras installed.
    """
    if not _AVAILABLE:
        return False
    return bool(AXIsProcessTrusted())


def prompt_for_trust() -> bool:
    """Ask macOS to prompt the user to grant Accessibility access.

    Shows the system "<App> would like to control this computer..." dialog if
    the process is not already trusted. Returns the trust state at the time of
    the call (the user's response, if any, only takes effect after they grant
    access in System Settings, so callers should re-check with
    :func:`is_trusted` afterward rather than relying on this return value
    reflecting the eventual outcome).

    Never raises: PyObjC bridging calls here can fail in unexpected ways, and
    this is meant to be a safe wrapper callers can use from UI code without a
    try/except of their own.
    """
    if not _AVAILABLE:
        return False
    try:
        options = CFDictionaryCreate(
            None,
            ["AXTrustedCheckOptionPrompt"],
            [True],
            1,
            None,
            None,
        )
        return bool(AXIsProcessTrustedWithOptions(options))
    except Exception:
        return False


SETTINGS_URL = (
    "x-apple.systempreferences:com.apple.preference.security"
    "?Privacy_Accessibility"
)


def open_settings() -> None:
    """Open System Settings directly to the Accessibility privacy pane.

    Never raises: the lazy AppKit/Foundation imports and URL-opening calls
    below can fail (missing extras, Objective-C bridging errors), and this
    should degrade to a no-op rather than crash the caller.
    """
    if not _AVAILABLE:
        return
    try:
        from AppKit import NSWorkspace
        from Foundation import NSURL

        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(SETTINGS_URL))
    except Exception:
        pass


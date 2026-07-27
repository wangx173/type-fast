"""Frontmost-app tracking and simulated paste, used for the auto-paste flow.

When the user summons Type Fast with the global hotkey, we remember whichever
app was frontmost at that moment. Once a translation finishes, we reactivate
that app and simulate Cmd+V so the translated text lands directly in the
field the user was typing into, instead of requiring a manual app switch and
paste.
"""

from __future__ import annotations

import time

try:
    from AppKit import NSRunningApplication, NSWorkspace, NSApplicationActivateIgnoringOtherApps
    import Quartz

    _AVAILABLE = True
except ImportError:  # pragma: no cover - non-macOS or missing pyobjc extras
    _AVAILABLE = False

# Virtual keycode for "V" on a US keyboard layout (kVK_ANSI_V).
_KEYCODE_V = 0x09

# How long to wait after reactivating the target app before sending Cmd+V, so
# the app has finished becoming key/frontmost and will receive the keystroke.
_ACTIVATE_SETTLE_SECONDS = 0.05


def available() -> bool:
    """Return True if the frontmost-app APIs are importable on this platform."""
    return _AVAILABLE


def frontmost_app_pid() -> int | None:
    """Return the PID of the current frontmost app, or None if unavailable."""
    if not _AVAILABLE:
        return None
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return None
    return int(app.processIdentifier())


def activate_pid(pid: int) -> bool:
    """Bring the app with the given PID to the front. Returns success."""
    if not _AVAILABLE:
        return False
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is None:
        return False
    return bool(app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps))


def simulate_paste() -> None:
    """Simulate a Cmd+V keystroke via a synthetic CGEvent.

    Requires Accessibility (AXIsProcessTrusted) access; posted events are
    silently ignored by macOS otherwise.
    """
    if not _AVAILABLE:
        return
    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)

    key_down = Quartz.CGEventCreateKeyboardEvent(source, _KEYCODE_V, True)
    Quartz.CGEventSetFlags(key_down, Quartz.kCGEventFlagMaskCommand)
    key_up = Quartz.CGEventCreateKeyboardEvent(source, _KEYCODE_V, False)
    Quartz.CGEventSetFlags(key_up, Quartz.kCGEventFlagMaskCommand)

    Quartz.CGEventPost(Quartz.kCGHIDEventTap, key_down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, key_up)


def paste_into_pid(pid: int) -> bool:
    """Reactivate the app at ``pid`` and simulate Cmd+V into it.

    Returns True if activation succeeded (the paste itself is fire-and-forget,
    since CGEventPost has no success signal). Callers should treat clipboard
    copy as the reliable fallback regardless of this return value.
    """
    if not activate_pid(pid):
        return False
    time.sleep(_ACTIVATE_SETTLE_SECONDS)
    simulate_paste()
    return True

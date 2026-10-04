"""Paste into the frontmost app with a synthetic ⌘V (macOS).

When the show/hide hotkey hides the window, the previous app gets focus back
and the finished translation is on the clipboard (or soon will be, once it
finishes); posting ⌘V there pastes it, so you don't have to.

Posting keystrokes to another app needs the Accessibility permission (System
Settings › Privacy & Security › Accessibility). Without it nothing is posted,
and the translation is still on the clipboard to paste by hand.

The ⌘V uses the physical V key of the U.S. layout. That is V on QWERTY, QWERTZ,
AZERTY, and Colemak, but not on Dvorak.

Everything here is a safe no-op off macOS or under a non-Cocoa Qt platform
(e.g. ``QT_QPA_PLATFORM=offscreen`` in tests and CI).
"""

from __future__ import annotations

import ctypes

from . import hotkey

_APP_SERVICES = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
_kCGEventSourceStateCombinedSessionState = 0
_kCGEventSourceStateHIDSystemState = 1
_kCGSessionEventTap = 1
# kCGEventLeftMouseDown, kCGEventRightMouseDown, kCGEventKeyDown,
# kCGEventOtherMouseDown: the clicks and key presses that can move the caret.
_INPUT_EVENT_TYPES = (1, 3, 10, 25)
# Physical V key; the same U.S.-layout table the hotkey uses.
_kVK_ANSI_V = hotkey.KEYCODES["V"]
# kCGEventFlagMaskCommand, plus the left-Command device bit that some apps check.
_COMMAND_FLAGS = 0x00100000 | 0x00000008
# Opens System Settings › Privacy & Security › Accessibility.
SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"

_lib: ctypes.CDLL | None = None
_lib_failed = False


def _load() -> ctypes.CDLL | None:
    """Return the Core Graphics bindings, or None off macOS/Cocoa."""
    global _lib, _lib_failed
    if not hotkey.is_cocoa():
        return None
    if _lib is None and not _lib_failed:
        try:
            lib = ctypes.CDLL(_APP_SERVICES)
            lib.AXIsProcessTrusted.argtypes = []
            lib.AXIsProcessTrusted.restype = ctypes.c_bool
            lib.CGEventSourceCreate.argtypes = [ctypes.c_int32]
            lib.CGEventSourceCreate.restype = ctypes.c_void_p
            lib.CGEventCreateKeyboardEvent.argtypes = [
                ctypes.c_void_p,  # CGEventSourceRef
                ctypes.c_uint16,  # CGKeyCode
                ctypes.c_bool,  # keyDown
            ]
            lib.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
            lib.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
            lib.CGEventSetFlags.restype = None
            lib.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
            lib.CGEventPost.restype = None
            lib.CFRelease.argtypes = [ctypes.c_void_p]
            lib.CFRelease.restype = None
            lib.CGEventSourceCounterForEventType.argtypes = [ctypes.c_int32, ctypes.c_uint32]
            lib.CGEventSourceCounterForEventType.restype = ctypes.c_uint32
            _lib = lib
        except (OSError, AttributeError):
            _lib_failed = True
    return _lib


def is_supported() -> bool:
    """True when ⌘V can be posted here (macOS + Cocoa)."""
    return _load() is not None


def has_permission() -> bool:
    """True when this app has the Accessibility permission.

    The answer is live, so a permission granted while the app runs counts
    right away. (``CGPreflightPostEventAccess`` would keep its first answer
    until the app is relaunched.)
    """
    lib = _load()
    return bool(lib and lib.AXIsProcessTrusted())


def input_event_count() -> int | None:
    """Return how many key presses and mouse clicks you have made, or None.

    It counts hardware input only, in any app, so a change shows that you
    clicked or typed somewhere since an earlier call; keystrokes posted by
    apps, such as :func:`send_paste`, don't count. None off macOS/Cocoa.
    """
    lib = _load()
    if lib is None:
        return None
    return sum(
        lib.CGEventSourceCounterForEventType(_kCGEventSourceStateHIDSystemState, kind)
        for kind in _INPUT_EVENT_TYPES
    )


def send_paste() -> bool:
    """Post ⌘V to the frontmost app.

    Returns False, posting nothing, when unsupported or not permitted.
    """
    lib = _load()
    if lib is None or not lib.AXIsProcessTrusted():
        return False
    source = lib.CGEventSourceCreate(_kCGEventSourceStateCombinedSessionState)
    # Create both events before posting either, so a key is never left down.
    events = [
        lib.CGEventCreateKeyboardEvent(source, _kVK_ANSI_V, key_down)
        for key_down in (True, False)
    ]
    try:
        if not all(events):
            return False
        for event in events:
            # Explicit flags, so modifiers still held from the hotkey don't leak in.
            lib.CGEventSetFlags(event, _COMMAND_FLAGS)
            lib.CGEventPost(_kCGSessionEventTap, event)
        return True
    finally:
        for ref in (*events, source):
            if ref:
                lib.CFRelease(ref)

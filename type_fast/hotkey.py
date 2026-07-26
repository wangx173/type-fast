"""Global (system-wide) hotkey to toggle the Type Fast window.

Implemented with an ``NSEvent`` global monitor, which observes key-down events
system-wide without needing the app to be focused. Like the auto-paste flow in
:mod:`type_fast.focus`, this requires the app to be trusted for Accessibility
access; without it, macOS simply never delivers events to the monitor, so the
hotkey silently becomes a no-op rather than raising an error.
"""

from __future__ import annotations

from typing import Callable, Optional

try:
    from AppKit import NSEvent, NSEventMaskKeyDown

    _AVAILABLE = True
except ImportError:  # pragma: no cover - non-macOS or missing pyobjc extras
    _AVAILABLE = False

# Default shortcut: Option+Command+Space.
# NSEvent modifier flag bits (NSEventModifierFlagOption / Command) and the
# virtual keycode for the Space bar (kVK_Space).
_MOD_OPTION = 1 << 19
_MOD_COMMAND = 1 << 20
_DEFAULT_MODIFIER_MASK = _MOD_OPTION | _MOD_COMMAND
_KEYCODE_SPACE = 0x31

# Modifier bits NSEvent may also set that we don't care about (caps lock,
# function, numeric pad, help); masked off before comparing.
_RELEVANT_MODIFIER_MASK = _MOD_OPTION | _MOD_COMMAND | (1 << 17) | (1 << 18)  # + Shift, Control


class GlobalHotkey:
    """Registers a global key-down monitor and invokes a callback on match.

    Only one shortcut (Option+Command+Space, matching the Phase 1 plan) is
    supported for now; extending this to a configurable shortcut is left as
    follow-up work once the basic flow is validated.
    """

    def __init__(
        self,
        on_trigger: Callable[[], None],
        keycode: int = _KEYCODE_SPACE,
        modifier_mask: int = _DEFAULT_MODIFIER_MASK,
    ) -> None:
        self._on_trigger = on_trigger
        self._keycode = keycode
        self._modifier_mask = modifier_mask
        self._monitor: Optional[object] = None

    @staticmethod
    def available() -> bool:
        return _AVAILABLE

    def _handle_event(self, event) -> None:
        if event.keyCode() != self._keycode:
            return
        modifiers = event.modifierFlags() & _RELEVANT_MODIFIER_MASK
        if modifiers != self._modifier_mask:
            return
        self._on_trigger()

    def start(self) -> bool:
        """Install the global monitor if not already running.

        Returns True if the monitor is installed and running (whether it was
        just installed by this call or already running from a previous
        call), or False if unsupported on this platform. Calling this
        multiple times is safe and treated as "ensure started" rather than
        "start once, fail thereafter".
        """
        if not _AVAILABLE:
            return False
        if self._monitor is not None:
            return True
        self._monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, self._handle_event
        )
        return self._monitor is not None

    def stop(self) -> None:
        """Remove the global monitor, if installed."""
        if self._monitor is not None:
            NSEvent.removeMonitor_(self._monitor)
            self._monitor = None

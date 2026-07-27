"""Global (system-wide) hotkey to toggle the Type Fast window.

Implemented with an ``NSEvent`` global monitor, which observes key-down events
system-wide without needing the app to be focused. Like the auto-paste flow in
:mod:`type_fast.focus`, this requires the app to be trusted for Accessibility
access; without it, macOS simply never delivers events to the monitor, so the
hotkey silently becomes a no-op rather than raising an error.

The shortcut itself is configurable via :func:`type_fast.config.hotkey_spec`
(an environment variable or fallback file, same pattern as the provider
credentials) using a human-readable ``"+"``-separated spec such as
``"option+command+space"`` or ``"control+shift+t"`` — see :func:`parse_hotkey`
for the exact syntax and supported modifier/key names.
"""

from __future__ import annotations

import sys
from typing import Callable, Optional

from . import config

try:
    from AppKit import NSEvent, NSEventMaskKeyDown

    _AVAILABLE = True
except ImportError:  # pragma: no cover - non-macOS or missing pyobjc extras
    _AVAILABLE = False

# NSEvent modifier flag bits (see AppKit's NSEventModifierFlags).
_MOD_SHIFT = 1 << 17
_MOD_CONTROL = 1 << 18
_MOD_OPTION = 1 << 19
_MOD_COMMAND = 1 << 20

# Default shortcut: Option+Command+Space.
_DEFAULT_MODIFIER_MASK = _MOD_OPTION | _MOD_COMMAND
_KEYCODE_SPACE = 0x31

# Modifier bits NSEvent may also set that we don't care about (caps lock,
# function, numeric pad, help); masked off before comparing.
_RELEVANT_MODIFIER_MASK = _MOD_SHIFT | _MOD_CONTROL | _MOD_OPTION | _MOD_COMMAND

_MODIFIER_ALIASES = {
    "cmd": _MOD_COMMAND,
    "command": _MOD_COMMAND,
    "opt": _MOD_OPTION,
    "option": _MOD_OPTION,
    "alt": _MOD_OPTION,
    "ctrl": _MOD_CONTROL,
    "control": _MOD_CONTROL,
    "shift": _MOD_SHIFT,
}

# macOS virtual keycodes (HIToolbox's kVK_* constants) for the keys we accept
# in a hotkey spec: letters, digits, and a handful of common named keys.
_KEYCODE_BY_NAME = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05,
    "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C,
    "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11, "1": 0x12,
    "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17, "9": 0x19,
    "7": 0x1A, "8": 0x1C, "0": 0x1D, "o": 0x1F, "u": 0x20, "i": 0x22,
    "p": 0x23, "l": 0x25, "j": 0x26, "k": 0x28, "n": 0x2D, "m": 0x2E,
    "tab": 0x30, "space": _KEYCODE_SPACE, "return": 0x24, "enter": 0x24,
    "escape": 0x35, "esc": 0x35, "delete": 0x33,
}


def parse_hotkey(spec: str) -> tuple[int, int]:
    """Parse a human-readable hotkey spec into an ``(keycode, modifier_mask)`` pair.

    ``spec`` is a ``"+"``-separated list of tokens, case-insensitive, with
    exactly one token naming a key (see :data:`_KEYCODE_BY_NAME` for the
    supported keys — letters, digits, and ``space``/``tab``/``return``/
    ``enter``/``escape``/``esc``/``delete``) and the rest naming modifiers
    (``cmd``/``command``, ``opt``/``option``/``alt``, ``ctrl``/``control``,
    ``shift``). For example: ``"option+command+space"`` or ``"ctrl+shift+t"``.

    Raises:
        ValueError: If ``spec`` is empty, names zero or more than one key, or
            references an unrecognized modifier/key name.
    """
    if not spec or not spec.strip():
        raise ValueError("hotkey spec must not be empty")

    modifier_mask = 0
    key_tokens = []
    for raw_token in spec.split("+"):
        token = raw_token.strip().lower()
        if not token:
            raise ValueError(f"empty token in hotkey spec {spec!r}")
        if token in _MODIFIER_ALIASES:
            modifier_mask |= _MODIFIER_ALIASES[token]
        else:
            key_tokens.append(token)

    if len(key_tokens) != 1:
        raise ValueError(
            f"hotkey spec {spec!r} must name exactly one non-modifier key, "
            f"found {len(key_tokens)}: {key_tokens!r}"
        )

    key = key_tokens[0]
    if key not in _KEYCODE_BY_NAME:
        raise ValueError(f"unrecognized key {key!r} in hotkey spec {spec!r}")

    return _KEYCODE_BY_NAME[key], modifier_mask


class GlobalHotkey:
    """Registers a global key-down monitor and invokes a callback on match.

    By default the shortcut is read from :func:`type_fast.config.hotkey_spec`
    (falling back to Option+Command+Space if unset or invalid); pass explicit
    ``keycode``/``modifier_mask`` to override that, which is mainly useful for
    tests.
    """

    def __init__(
        self,
        on_trigger: Callable[[], None],
        *,
        keycode: Optional[int] = None,
        modifier_mask: Optional[int] = None,
    ) -> None:
        self._on_trigger = on_trigger
        if keycode is None or modifier_mask is None:
            parsed_keycode, parsed_modifier_mask = self._resolve_configured_hotkey()
            if keycode is None:
                keycode = parsed_keycode
            if modifier_mask is None:
                modifier_mask = parsed_modifier_mask
        self._keycode = keycode
        self._modifier_mask = modifier_mask
        self._monitor: Optional[object] = None

    @staticmethod
    def _resolve_configured_hotkey() -> tuple[int, int]:
        """Parse the configured hotkey spec, falling back to the default.

        A malformed user-supplied spec (bad env var or config file) must
        never prevent the app from starting; it's reported on stderr and the
        default shortcut is used instead.
        """
        try:
            return parse_hotkey(config.hotkey_spec())
        except ValueError as exc:
            print(
                f"type-fast: invalid hotkey configuration ({exc}); "
                "falling back to the default shortcut",
                file=sys.stderr,
            )
            return _KEYCODE_SPACE, _DEFAULT_MODIFIER_MASK

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

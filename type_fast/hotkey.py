"""Portable hotkey parsing, canonical names, and Qt conversions."""

from __future__ import annotations

from dataclasses import dataclass
import sys

from PySide6.QtCore import QKeyCombination, Qt
from PySide6.QtGui import QKeySequence

# --- Modifiers ---------------------------------------------------------------

CTRL, OPTION, SHIFT, CMD = "Ctrl", "Option", "Shift", "Cmd"

# Canonical (Apple) order.
MODIFIERS = (CTRL, OPTION, SHIFT, CMD)

MODIFIER_SYMBOLS = {CTRL: "\u2303", OPTION: "\u2325", SHIFT: "\u21e7", CMD: "\u2318"}

# Carbon modifier masks (Events.h).
CARBON_MODIFIERS = {CMD: 0x0100, SHIFT: 0x0200, OPTION: 0x0800, CTRL: 0x1000}
WIN32_MODIFIERS = {CTRL: 0x0002, OPTION: 0x0001, SHIFT: 0x0004, CMD: 0x0008}
_WINDOWS_LABELS = {CTRL: "Ctrl", OPTION: "Alt", SHIFT: "Shift", CMD: "Win"}


def is_windows() -> bool:
    """Select Windows names and Qt mappings, including before Qt starts."""
    return sys.platform == "win32"

_MODIFIER_ALIASES = {
    "ctrl": CTRL, "control": CTRL, "ctl": CTRL, "\u2303": CTRL, "^": CTRL,
    "option": OPTION, "opt": OPTION, "alt": OPTION, "\u2325": OPTION,
    "shift": SHIFT, "\u21e7": SHIFT,
    "cmd": CMD, "command": CMD, "\u2318": CMD,
}

# --- Keys --------------------------------------------------------------------

# Canonical key name -> macOS virtual keycode (kVK_* in Events.h; ANSI layout).
KEYCODES: dict[str, int] = {
    "A": 0x00, "S": 0x01, "D": 0x02, "F": 0x03, "H": 0x04, "G": 0x05,
    "Z": 0x06, "X": 0x07, "C": 0x08, "V": 0x09, "B": 0x0B, "Q": 0x0C,
    "W": 0x0D, "E": 0x0E, "R": 0x0F, "Y": 0x10, "T": 0x11, "O": 0x1F,
    "U": 0x20, "I": 0x22, "P": 0x23, "L": 0x25, "J": 0x26, "K": 0x28,
    "N": 0x2D, "M": 0x2E,
    "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17,
    "9": 0x19, "7": 0x1A, "8": 0x1C, "0": 0x1D,
    "=": 0x18, "-": 0x1B, "]": 0x1E, "[": 0x21, "'": 0x27, ";": 0x29,
    "\\": 0x2A, ",": 0x2B, "/": 0x2C, ".": 0x2F, "`": 0x32,
    "Return": 0x24, "Tab": 0x30, "Space": 0x31, "Delete": 0x33, "Escape": 0x35,
    "Home": 0x73, "PageUp": 0x74, "End": 0x77, "PageDown": 0x79,
    "Left": 0x7B, "Right": 0x7C, "Down": 0x7D, "Up": 0x7E,
    "F1": 0x7A, "F2": 0x78, "F3": 0x63, "F4": 0x76, "F5": 0x60, "F6": 0x61,
    "F7": 0x62, "F8": 0x64, "F9": 0x65, "F10": 0x6D, "F11": 0x67, "F12": 0x6F,
    "F13": 0x69, "F14": 0x6B, "F15": 0x71, "F16": 0x6A, "F17": 0x40,
    "F18": 0x4F, "F19": 0x50, "F20": 0x5A,
}

_KEY_FOR_KEYCODE = {code: name for name, code in KEYCODES.items()}

VIRTUAL_KEYS: dict[str, int] = {
    **{c: ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
    **{f"F{n}": 0x70 + n - 1 for n in range(1, 21)},
    "Space": 0x20, "Return": 0x0D, "Escape": 0x1B, "Tab": 0x09,
    "Delete": 0x08, "Home": 0x24, "End": 0x23,
    "PageUp": 0x21, "PageDown": 0x22,
    "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28,
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE,
    "/": 0xBF, "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}
_KEY_FOR_VIRTUAL_KEY = {code: name for name, code in VIRTUAL_KEYS.items()}

FUNCTION_KEYS = frozenset(f"F{n}" for n in range(1, 21))
_ARROW_KEYS = frozenset({"Left", "Right", "Up", "Down"})

_KEY_ALIASES = {name.lower(): name for name in KEYCODES}
_KEY_ALIASES.update({
    "enter": "Return", "esc": "Escape", "backspace": "Delete",
    "spacebar": "Space", "pgup": "PageUp", "pgdn": "PageDown",
})

# Compact display form for keys that have a conventional macOS symbol.
_KEY_SYMBOLS = {
    "Return": "\u21a9", "Tab": "\u21e5", "Delete": "\u232b", "Escape": "\u238b",
    "Left": "\u2190", "Right": "\u2192", "Up": "\u2191", "Down": "\u2193",
    "Home": "\u2196", "End": "\u2198", "PageUp": "\u21de", "PageDown": "\u21df",
}

# Qt key -> canonical key name. Shifted US-layout symbols map back to their
# physical key (Qt reports e.g. ⇧1 as Key_Exclam), since hotkeys are physical.
_QT_KEYS: dict[int, str] = {}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    _QT_KEYS[ord(_c)] = _c
for _n in range(1, 21):
    _QT_KEYS[int(getattr(Qt.Key, f"Key_F{_n}"))] = f"F{_n}"
for _qt_name, _name in {
    "Key_Space": "Space", "Key_Return": "Return", "Key_Enter": "Return",
    "Key_Tab": "Tab", "Key_Backtab": "Tab", "Key_Escape": "Escape",
    "Key_Backspace": "Delete", "Key_Home": "Home", "Key_End": "End",
    "Key_PageUp": "PageUp", "Key_PageDown": "PageDown",
    "Key_Left": "Left", "Key_Right": "Right", "Key_Up": "Up", "Key_Down": "Down",
    "Key_Minus": "-", "Key_Underscore": "-", "Key_Equal": "=", "Key_Plus": "=",
    "Key_BracketLeft": "[", "Key_BraceLeft": "[",
    "Key_BracketRight": "]", "Key_BraceRight": "]",
    "Key_Semicolon": ";", "Key_Colon": ";",
    "Key_Apostrophe": "'", "Key_QuoteDbl": "'",
    "Key_Comma": ",", "Key_Less": ",", "Key_Period": ".", "Key_Greater": ".",
    "Key_Slash": "/", "Key_Question": "/", "Key_Backslash": "\\", "Key_Bar": "\\",
    "Key_QuoteLeft": "`", "Key_AsciiTilde": "`",
    "Key_Exclam": "1", "Key_At": "2", "Key_NumberSign": "3", "Key_Dollar": "4",
    "Key_Percent": "5", "Key_AsciiCircum": "6", "Key_Ampersand": "7",
    "Key_Asterisk": "8", "Key_ParenLeft": "9", "Key_ParenRight": "0",
}.items():
    _QT_KEYS[int(getattr(Qt.Key, _qt_name))] = _name

# Canonical key name -> preferred Qt key (first mapping wins: unshifted keys).
_QT_KEY_FOR_NAME: dict[str, int] = {}
for _code, _name in _QT_KEYS.items():
    _QT_KEY_FOR_NAME.setdefault(_name, _code)
for _name, _qt_name in {
    "-": "Key_Minus", "=": "Key_Equal", "[": "Key_BracketLeft",
    "]": "Key_BracketRight", ";": "Key_Semicolon", "'": "Key_Apostrophe",
    ",": "Key_Comma", ".": "Key_Period", "/": "Key_Slash",
    "\\": "Key_Backslash", "`": "Key_QuoteLeft", "Return": "Key_Return",
    "Tab": "Key_Tab",
}.items():
    _QT_KEY_FOR_NAME[_name] = int(getattr(Qt.Key, _qt_name))
del _c, _n, _code, _name, _qt_name

# On macOS Qt swaps Control and Meta by default: ControlModifier is ⌘ Command
# and MetaModifier is ⌃ Control. Alt is ⌥ Option.
_QT_MODIFIERS = (
    (Qt.KeyboardModifier.MetaModifier, CTRL),
    (Qt.KeyboardModifier.AltModifier, OPTION),
    (Qt.KeyboardModifier.ShiftModifier, SHIFT),
    (Qt.KeyboardModifier.ControlModifier, CMD),
)
_WINDOWS_QT_MODIFIERS = (
    (Qt.KeyboardModifier.ControlModifier, CTRL),
    (Qt.KeyboardModifier.AltModifier, OPTION),
    (Qt.KeyboardModifier.ShiftModifier, SHIFT),
    (Qt.KeyboardModifier.MetaModifier, CMD),
)


def _qt_modifiers() -> tuple[tuple[Qt.KeyboardModifier, str], ...]:
    return _WINDOWS_QT_MODIFIERS if is_windows() else _QT_MODIFIERS


@dataclass(frozen=True)
class Hotkey:
    """A key plus modifiers, kept in canonical modifier order.

    Construction validates the names (raising :class:`ValueError`) but not the
    "needs a modifier" rule; check :attr:`is_valid` for that.
    """

    modifiers: tuple[str, ...]
    key: str

    def __post_init__(self) -> None:
        unknown = set(self.modifiers) - set(MODIFIERS)
        if unknown:
            raise ValueError(f"unknown modifier(s): {sorted(unknown)}")
        if self.key not in KEYCODES:
            raise ValueError(f"unsupported key: {self.key!r}")
        ordered = tuple(m for m in MODIFIERS if m in self.modifiers)
        object.__setattr__(self, "modifiers", ordered)

    @property
    def is_valid(self) -> bool:
        """True unless the hotkey would swallow typing or Windows auto-paste.

        It needs ⌘, ⌃ or ⌥ (Shift alone is not enough), except for F-keys.
        """
        if is_windows() and self.vk is None:
            return False
        if is_windows() and self.vk == 0x56 and self.win32_modifiers == 0x0002:
            return False
        if self.key in FUNCTION_KEYS:
            return True
        return bool({CTRL, OPTION, CMD} & set(self.modifiers))

    @property
    def keycode(self) -> int:
        """The macOS virtual keycode of :attr:`key`."""
        return KEYCODES[self.key]

    @property
    def carbon_modifiers(self) -> int:
        """The Carbon modifier mask for :attr:`modifiers`."""
        mask = 0
        for modifier in self.modifiers:
            mask |= CARBON_MODIFIERS[modifier]
        return mask

    @property
    def vk(self) -> int | None:
        """Win32 virtual key; canonical Delete means Backspace on both OSes."""
        return VIRTUAL_KEYS.get(self.key)

    @property
    def win32_modifiers(self) -> int:
        """Win32 MOD_* flags, excluding registration-only MOD_NOREPEAT."""
        return sum(WIN32_MODIFIERS[m] for m in self.modifiers)

    def symbols(self) -> str:
        """OS display form: macOS symbols or Windows Ctrl+Alt+Shift+Win."""
        if is_windows():
            key = "Backspace" if self.key == "Delete" else self.key
            return "+".join((*(_WINDOWS_LABELS[m] for m in self.modifiers), key))
        mods = "".join(MODIFIER_SYMBOLS[m] for m in self.modifiers)
        return mods + _KEY_SYMBOLS.get(self.key, self.key)

    def __str__(self) -> str:
        return "+".join((*self.modifiers, self.key))


def parse(text: str) -> Hotkey | None:
    """Parse ``text`` into a valid :class:`Hotkey`, or return None.

    Accepts ``+``-separated tokens in any case and order, modifier aliases and
    symbols (``"⌥⌘T"`` works too). Returns None for unknown keys, a missing or
    repeated key, or a combination that fails :attr:`Hotkey.is_valid`.
    """
    if not isinstance(text, str):
        return None
    modifiers: set[str] = set()
    key: str | None = None
    parts = text.strip().split("+")
    for part in parts:
        token = part.strip()
        # Peel off leading modifier symbols, e.g. "⌥⌘T".
        while token and token[0] in _MODIFIER_ALIASES and len(token) > 1:
            modifiers.add(_MODIFIER_ALIASES[token[0]])
            token = token[1:].strip()
        if not token:
            return None
        lowered = token.lower()
        if lowered in _MODIFIER_ALIASES:
            modifiers.add(_MODIFIER_ALIASES[lowered])
        elif lowered in _KEY_ALIASES and key is None:
            key = _KEY_ALIASES[lowered]
        else:
            return None
    if key is None:
        return None
    hotkey = Hotkey(tuple(modifiers), key)
    return hotkey if hotkey.is_valid else None


def from_qt(
    combo: QKeyCombination | QKeySequence, *, native_virtual_key: int | None = None
) -> Hotkey | None:
    """Convert a Qt key combination (or the first one in a sequence).

    Uses macOS's swapped Control/Meta mapping, or Windows's Ctrl/Win mapping.
    A captured Windows VK takes precedence over layout-dependent Qt characters.
    Returns None for an empty sequence, a bare modifier, an
    unsupported key, or a numeric-keypad key. The result may still fail :attr:`Hotkey.is_valid` so that
    callers can explain why.
    """
    if isinstance(combo, QKeySequence):
        if combo.count() == 0:
            return None
        combo = combo[0]
    qt_key = int(combo.key())
    if qt_key in {
        Qt.Key_Shift, Qt.Key_Control, Qt.Key_Meta, Qt.Key_Alt,
        Qt.Key_AltGr, Qt.Key_CapsLock,
    }:
        return None
    name = (
        key_for_virtual_key(native_virtual_key)
        if is_windows() and native_virtual_key is not None else _QT_KEYS.get(qt_key)
    )
    if name is None:
        return None
    mods = combo.keyboardModifiers()
    # Numeric-keypad keys have their own keycodes, so don't silently map e.g.
    # ⌘+keypad-1 onto ⌘1. macOS also flags the arrow keys as keypad keys.
    if mods & Qt.KeyboardModifier.KeypadModifier and name not in _ARROW_KEYS:
        return None
    modifiers = tuple(m for flag, m in _qt_modifiers() if mods & flag)
    result = Hotkey(modifiers, name)
    return None if is_windows() and result.vk is None else result


def key_for_keycode(keycode: int) -> str | None:
    """Return the canonical key name for a macOS virtual keycode, if supported.

    Keycodes identify *physical* keys, named here after the U.S. layout. Use
    this with ``QKeyEvent.nativeVirtualKey()`` so a hotkey recorded on another
    layout (Dvorak, AZERTY, ...) registers the key that was actually pressed.
    """
    return _KEY_FOR_KEYCODE.get(keycode)


def key_for_virtual_key(vk: int) -> str | None:
    """Return the canonical name of a Windows VK, independent of Qt's text."""
    return _KEY_FOR_VIRTUAL_KEY.get(vk)


def to_qt(hotkey: Hotkey) -> QKeySequence:
    """Return a :class:`QKeySequence` for ``hotkey`` (inverse of :func:`from_qt`)."""
    mods = Qt.KeyboardModifier.NoModifier
    for flag, modifier in _qt_modifiers():
        if modifier in hotkey.modifiers:
            mods |= flag
    return QKeySequence(QKeyCombination(mods, Qt.Key(_QT_KEY_FOR_NAME[hotkey.key])))


def uses_native_keycodes() -> bool:
    """True when Qt native keycodes are macOS virtual keycodes."""
    from . import platform

    return platform.uses_native_keycodes()

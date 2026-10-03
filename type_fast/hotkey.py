"""Global show/hide hotkey for type-fast (macOS).

Hotkeys are written in a canonical, human-readable form using macOS modifier
names in Apple's order (Ctrl, Option, Shift, Cmd), e.g. ``"Option+Space"``,
``"Shift+Cmd+T"``, ``"Ctrl+Option+K"`` or ``"F5"``. :func:`parse` accepts that
form case-insensitively, plus common aliases (``Command``/``⌘``, ``Alt``/
``Opt``/``⌥``, ``Control``/``⌃``, ``⇧``, ``Enter``, ``Esc``, ``Backspace``), and
:meth:`Hotkey.symbols` renders the compact menu-style form (``"⌥Space"``).

:class:`GlobalHotkey` registers a system-wide hotkey through the Carbon
``RegisterEventHotKey`` API via :mod:`ctypes`. Unlike ``NSEvent`` monitors this
needs no Accessibility permission and *consumes* the keystroke, which is what
makes a Spotlight-style toggle possible. Qt's Cocoa event loop pumps the main
run loop, so hotkey events are delivered on the main (GUI) thread.

Everything here is a safe no-op off macOS or under a non-Cocoa Qt platform
(e.g. ``QT_QPA_PLATFORM=offscreen`` in tests and CI), so real global hotkeys are
never grabbed there.
"""

from __future__ import annotations

import ctypes
import itertools
import sys
import weakref
from dataclasses import dataclass

from PySide6.QtCore import QKeyCombination, QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence

# --- Modifiers ---------------------------------------------------------------

CTRL, OPTION, SHIFT, CMD = "Ctrl", "Option", "Shift", "Cmd"

# Canonical (Apple) order.
MODIFIERS = (CTRL, OPTION, SHIFT, CMD)

MODIFIER_SYMBOLS = {CTRL: "\u2303", OPTION: "\u2325", SHIFT: "\u21e7", CMD: "\u2318"}

# Carbon modifier masks (Events.h).
CARBON_MODIFIERS = {CMD: 0x0100, SHIFT: 0x0200, OPTION: 0x0800, CTRL: 0x1000}

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
        """True unless the hotkey would swallow ordinary typing.

        It needs ⌘, ⌃ or ⌥ (Shift alone is not enough), except for F-keys.
        """
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

    def symbols(self) -> str:
        """Compact macOS display form, e.g. ``"⌥Space"`` or ``"⌃⌥⇧⌘T"``."""
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


def from_qt(combo: QKeyCombination | QKeySequence) -> Hotkey | None:
    """Convert a Qt key combination (or the first one in a sequence).

    Applies the macOS Qt mapping (ControlModifier = ⌘, MetaModifier = ⌃,
    AltModifier = ⌥). Returns None for an empty sequence, a bare modifier, an
    unsupported key, or a numeric-keypad key. The result may still fail :attr:`Hotkey.is_valid` so that
    callers can explain why.
    """
    if isinstance(combo, QKeySequence):
        if combo.count() == 0:
            return None
        combo = combo[0]
    name = _QT_KEYS.get(int(combo.key()))
    if name is None:
        return None
    mods = combo.keyboardModifiers()
    # Numeric-keypad keys have their own keycodes, so don't silently map e.g.
    # ⌘+keypad-1 onto ⌘1. macOS also flags the arrow keys as keypad keys.
    if mods & Qt.KeyboardModifier.KeypadModifier and name not in _ARROW_KEYS:
        return None
    modifiers = tuple(m for flag, m in _QT_MODIFIERS if mods & flag)
    return Hotkey(modifiers, name)


def key_for_keycode(keycode: int) -> str | None:
    """Return the canonical key name for a macOS virtual keycode, if supported.

    Keycodes identify *physical* keys, named here after the U.S. layout. Use
    this with ``QKeyEvent.nativeVirtualKey()`` so a hotkey recorded on another
    layout (Dvorak, AZERTY, ...) registers the key that was actually pressed.
    """
    return _KEY_FOR_KEYCODE.get(keycode)


def to_qt(hotkey: Hotkey) -> QKeySequence:
    """Return a :class:`QKeySequence` for ``hotkey`` (inverse of :func:`from_qt`)."""
    mods = Qt.KeyboardModifier.NoModifier
    for flag, modifier in _QT_MODIFIERS:
        if modifier in hotkey.modifiers:
            mods |= flag
    return QKeySequence(QKeyCombination(mods, Qt.Key(_QT_KEY_FOR_NAME[hotkey.key])))


# --- Platform checks ---------------------------------------------------------


def is_cocoa() -> bool:
    """True on macOS with a running Qt GUI app on the native Cocoa platform."""
    if sys.platform != "darwin":
        return False
    app = QGuiApplication.instance()
    return app is not None and QGuiApplication.platformName() == "cocoa"


def uses_native_keycodes() -> bool:
    """True when ``QKeyEvent.nativeVirtualKey()`` holds macOS virtual keycodes."""
    return is_cocoa()


def _fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


# --- Carbon (RegisterEventHotKey) -------------------------------------------

_CARBON_PATH = "/System/Library/Frameworks/Carbon.framework/Carbon"
_kEventClassKeyboard = _fourcc("keyb")
_kEventHotKeyPressed = 5
_kEventParamDirectObject = _fourcc("----")
_typeEventHotKeyID = _fourcc("hkid")
_SIGNATURE = _fourcc("TFhk")
_noErr = 0
_eventNotHandledErr = -9874
# Fail with eventHotKeyExistsErr instead of silently succeeding when macOS
# already reserves the combination (e.g. ⌘Space for Spotlight, ⌘Tab).
_kEventHotKeyExclusive = 1

# OSStatus handler(EventHandlerCallRef, EventRef, void *userData)
_EventHandlerProc = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
)


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class _Carbon:
    """Process-wide Carbon bindings plus one shared hotkey event handler.

    The handler (and its ctypes callback) lives for the whole process at module
    level, so the C side can never call into a freed callback even if a
    :class:`GlobalHotkey` is garbage-collected. It dispatches by hotkey id.
    """

    def __init__(self) -> None:
        lib = ctypes.CDLL(_CARBON_PATH)
        lib.GetApplicationEventTarget.argtypes = []
        lib.GetApplicationEventTarget.restype = ctypes.c_void_p
        lib.InstallEventHandler.argtypes = [
            ctypes.c_void_p,  # EventTargetRef
            _EventHandlerProc,  # EventHandlerUPP
            ctypes.c_ulong,  # ItemCount
            ctypes.POINTER(_EventTypeSpec),
            ctypes.c_void_p,  # userData
            ctypes.POINTER(ctypes.c_void_p),  # EventHandlerRef *
        ]
        lib.InstallEventHandler.restype = ctypes.c_int32
        lib.RemoveEventHandler.argtypes = [ctypes.c_void_p]
        lib.RemoveEventHandler.restype = ctypes.c_int32
        lib.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32,  # keycode
            ctypes.c_uint32,  # modifiers
            _EventHotKeyID,  # by value
            ctypes.c_void_p,  # EventTargetRef
            ctypes.c_uint32,  # OptionBits
            ctypes.POINTER(ctypes.c_void_p),  # EventHotKeyRef *
        ]
        lib.RegisterEventHotKey.restype = ctypes.c_int32
        lib.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        lib.UnregisterEventHotKey.restype = ctypes.c_int32
        lib.GetEventParameter.argtypes = [
            ctypes.c_void_p,  # EventRef
            ctypes.c_uint32,  # EventParamName
            ctypes.c_uint32,  # EventParamType
            ctypes.c_void_p,  # EventParamType *outActualType
            ctypes.c_ulong,  # ByteCount bufferSize
            ctypes.c_void_p,  # ByteCount *outActualSize
            ctypes.c_void_p,  # void *outData
        ]
        lib.GetEventParameter.restype = ctypes.c_int32
        self.lib = lib
        self.callback = _EventHandlerProc(self._on_event)
        self.handler: ctypes.c_void_p | None = None
        self.targets: dict[int, weakref.ref[GlobalHotkey]] = {}

    def _on_event(self, _call_ref: int, event: int, _user_data: int) -> int:
        try:
            hotkey_id = _EventHotKeyID()
            status = self.lib.GetEventParameter(
                event,
                _kEventParamDirectObject,
                _typeEventHotKeyID,
                None,
                ctypes.sizeof(hotkey_id),
                None,
                ctypes.byref(hotkey_id),
            )
            if status != _noErr or hotkey_id.signature != _SIGNATURE:
                return _eventNotHandledErr
            ref = self.targets.get(hotkey_id.id)
            target = ref() if ref is not None else None
            if target is None:
                return _eventNotHandledErr
            target.activated.emit()
            return _noErr
        except Exception:  # never let an exception cross into C
            return _eventNotHandledErr

    def ensure_handler(self) -> bool:
        if self.handler is not None:
            return True
        spec = _EventTypeSpec(_kEventClassKeyboard, _kEventHotKeyPressed)
        handler = ctypes.c_void_p()
        status = self.lib.InstallEventHandler(
            self.lib.GetApplicationEventTarget(),
            self.callback,
            1,
            ctypes.byref(spec),
            None,
            ctypes.byref(handler),
        )
        if status != _noErr:
            return False
        self.handler = handler
        return True

    def remove_handler_if_idle(self) -> None:
        if self.handler is not None and not self.targets:
            self.lib.RemoveEventHandler(self.handler)
            self.handler = None


_carbon: _Carbon | None = None
_carbon_failed = False


def _load_carbon() -> _Carbon | None:
    global _carbon, _carbon_failed
    if _carbon is None and not _carbon_failed:
        try:
            _carbon = _Carbon()
        except (OSError, AttributeError):
            _carbon_failed = True
    return _carbon


def _release(state: dict) -> None:
    """Unregister a hotkey's Carbon registration (idempotent)."""
    carbon = _carbon
    ref = state.pop("ref", None)
    if carbon is None:
        return
    if ref is not None:
        carbon.lib.UnregisterEventHotKey(ref)
    carbon.targets.pop(state["id"], None)
    carbon.remove_handler_if_idle()


class GlobalHotkey(QObject):
    """A system-wide hotkey that emits :attr:`activated` when pressed."""

    activated = Signal()

    _ids = itertools.count(1)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hotkey: Hotkey | None = None
        # Mutable state shared with the finalizer so a collected instance still
        # releases its registration.
        self._state: dict = {"id": next(GlobalHotkey._ids)}
        weakref.finalize(self, _release, self._state)

    @staticmethod
    def is_supported() -> bool:
        """True when global hotkeys can be registered here (macOS + Cocoa)."""
        return is_cocoa() and _load_carbon() is not None

    @property
    def is_registered(self) -> bool:
        return self._state.get("ref") is not None

    @property
    def hotkey(self) -> Hotkey | None:
        """The currently registered hotkey, if any."""
        return self._hotkey if self.is_registered else None

    def register(self, hotkey: Hotkey) -> bool:
        """Register ``hotkey``, replacing any previous one; never raises.

        Returns False when unsupported (not macOS, Carbon unavailable, non-Cocoa
        Qt platform), when ``hotkey`` is invalid, or when macOS refuses it (e.g.
        it is reserved by macOS or already taken in this process). The previous hotkey is released in every case.
        """
        self.unregister()
        if not hotkey.is_valid or not self.is_supported():
            return False
        carbon = _load_carbon()
        if carbon is None:
            return False
        try:
            if not carbon.ensure_handler():
                return False
            ref = ctypes.c_void_p()
            status = carbon.lib.RegisterEventHotKey(
                hotkey.keycode,
                hotkey.carbon_modifiers,
                _EventHotKeyID(_SIGNATURE, self._state["id"]),
                carbon.lib.GetApplicationEventTarget(),
                _kEventHotKeyExclusive,
                ctypes.byref(ref),
            )
        except Exception:
            carbon.remove_handler_if_idle()
            return False
        if status != _noErr or not ref.value:
            carbon.remove_handler_if_idle()
            return False
        self._state["ref"] = ref
        carbon.targets[self._state["id"]] = weakref.ref(self)
        self._hotkey = hotkey
        return True

    def unregister(self) -> None:
        """Release the hotkey, if registered."""
        self._hotkey = None
        try:
            _release(self._state)
        except Exception:
            pass


# --- App activation and pasteboard (libobjc) ---------------------------------

_objc: ctypes.CDLL | None = None


def _send(receiver: int | None, selector: str, restype=ctypes.c_void_p,
          argtypes: tuple = (), args: tuple = ()):
    """Call ``objc_msgSend`` with an explicitly typed prototype.

    arm64 requires objc_msgSend to be called through a correctly typed,
    non-variadic function pointer, so a prototype is built per signature.
    """
    assert _objc is not None
    proto = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)
    msg_send = proto(ctypes.cast(_objc.objc_msgSend, ctypes.c_void_p).value)
    return msg_send(receiver, _objc.sel_registerName(selector.encode()), *args)


def _objc_class(name: str) -> int | None:
    """Return the Objective-C class ``name``, or None when unavailable."""
    global _objc
    if not is_cocoa():
        return None
    try:
        if _objc is None:
            lib = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
            lib.objc_getClass.argtypes = [ctypes.c_char_p]
            lib.objc_getClass.restype = ctypes.c_void_p
            lib.sel_registerName.argtypes = [ctypes.c_char_p]
            lib.sel_registerName.restype = ctypes.c_void_p
            _objc = lib
        return _objc.objc_getClass(name.encode()) or None
    except (OSError, AttributeError):
        return None


def _ns_app() -> int | None:
    """Return ``[NSApplication sharedApplication]`` or None when unavailable."""
    cls = _objc_class("NSApplication")
    return _send(cls, "sharedApplication") if cls else None


def pasteboard_change_count() -> int | None:
    """Return the general pasteboard's change count, or None off macOS/Cocoa.

    It goes up each time anything is copied, in any app.
    """
    cls = _objc_class("NSPasteboard")
    board = _send(cls, "generalPasteboard") if cls else None
    return _send(board, "changeCount", ctypes.c_long) if board else None


def frontmost_app_pid() -> int | None:
    """Return the process id of the frontmost app.

    None off macOS/Cocoa, or when macOS reports no frontmost app.
    """
    cls = _objc_class("NSWorkspace")
    workspace = _send(cls, "sharedWorkspace") if cls else None
    app = _send(workspace, "frontmostApplication") if workspace else None
    return _send(app, "processIdentifier", ctypes.c_int32) if app else None


def activate_app() -> None:
    """Unhide and bring this app to the front (no-op off macOS/Cocoa)."""
    app = _ns_app()
    if not app:
        return
    _send(app, "unhide:", None, (ctypes.c_void_p,), (None,))
    _send(app, "activateIgnoringOtherApps:", None, (ctypes.c_bool,), (True,))


def hide_app() -> None:
    """Hide this app so the previously active app regains focus (like Spotlight)."""
    app = _ns_app()
    if app:
        _send(app, "hide:", None, (ctypes.c_void_p,), (None,))

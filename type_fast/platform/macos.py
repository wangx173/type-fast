"""Native macOS integration: Carbon hotkeys, app focus, and auto-paste."""

from __future__ import annotations

import ctypes
import itertools
import sys
import weakref

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication

from .. import hotkey
from ..hotkey import Hotkey

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


def clipboard_change_count() -> int | None:
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
PASTE_SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"

_lib: ctypes.CDLL | None = None
_lib_failed = False


def _load() -> ctypes.CDLL | None:
    """Return the Core Graphics bindings, or None off macOS/Cocoa."""
    global _lib, _lib_failed
    if not is_cocoa():
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


def paste_supported() -> bool:
    """True when ⌘V can be posted here (macOS + Cocoa)."""
    return _load() is not None


def paste_permission_granted() -> bool:
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

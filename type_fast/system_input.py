"""System-wide translate-in-place via a global hotkey (Phase 2a).

Registers a global hotkey with ``pynput``. When pressed, it copies the current
selection from whatever app is frontmost (via a synthetic Cmd+C), translates it
with the existing :func:`type_fast.translator.translate_stream`, and pastes the
result back over the selection (via a synthetic Cmd+V), restoring the user's
previous clipboard afterwards.

Requires the macOS Accessibility permission (and possibly Input Monitoring) for
the running process. See the README for the one-time permission setup.
"""

from __future__ import annotations

import threading
import time

from AppKit import NSPasteboard, NSPasteboardTypeString
from pynput import keyboard
from pynput.keyboard import Controller, Key

from . import config
from .translator import translate_stream

_kbd = Controller()

# When True, the pipeline prints each stage (hotkey fired, copied text,
# translation, paste) to help diagnose why nothing appears to happen.
VERBOSE = False
VERBOSE = False


def _log(message: str) -> None:
    if VERBOSE:
        print(f"[type-fast] {message}")


# Modifier keys the user may still be physically holding from the hotkey when
# the action fires. If we synthesize Cmd+C / Cmd+V while one of these is held,
# the OS sees the extra modifier (e.g. Cmd+Shift+V instead of Cmd+V) and the
# copy/paste silently fails. Release them first.
_MODIFIERS = (Key.cmd, Key.shift, Key.ctrl, Key.alt)


def _release_held_modifiers() -> None:
    for mod in _MODIFIERS:
        try:
            _kbd.release(mod)
        except Exception:
            pass


def _read_selection_via_copy(
    timeout: float = config.COPY_POLL_TIMEOUT_SECONDS,
) -> str:
    """Copy the current selection and return it as plain text.

    Synthesizes Cmd+C and waits for the pasteboard ``changeCount`` to increment
    (rather than sleeping a fixed time) to avoid reading stale clipboard data.
    Returns an empty string if nothing was copied within ``timeout`` seconds.
    """
    pasteboard = NSPasteboard.generalPasteboard()
    before = pasteboard.changeCount()

    # Make sure no hotkey modifier is still held, then send a clean Cmd+C.
    _release_held_modifiers()
    time.sleep(config.KEY_SETTLE_SECONDS)
    with _kbd.pressed(Key.cmd):
        _kbd.press("c")
        _kbd.release("c")

    deadline = time.time() + timeout
    while pasteboard.changeCount() == before and time.time() < deadline:
        time.sleep(0.01)

    return pasteboard.stringForType_(NSPasteboardTypeString) or ""


def _paste_text(text: str) -> None:
    """Paste ``text`` as plain text, preserving the user's previous clipboard.

    Snapshots the current plain-text clipboard, writes ``text``, synthesizes
    Cmd+V, then restores the snapshot after a short settle delay so the paste
    has time to be consumed by the target app.
    """
    pasteboard = NSPasteboard.generalPasteboard()
    saved = pasteboard.stringForType_(NSPasteboardTypeString)

    pasteboard.clearContents()
    pasteboard.setString_forType_(text, NSPasteboardTypeString)

    # Make sure no hotkey modifier is still held, then send a clean Cmd+V.
    _release_held_modifiers()
    time.sleep(config.KEY_SETTLE_SECONDS)
    with _kbd.pressed(Key.cmd):
        _kbd.press("v")
        _kbd.release("v")

    def _restore() -> None:
        time.sleep(config.PASTE_SETTLE_SECONDS)
        pasteboard.clearContents()
        if saved is not None:
            pasteboard.setString_forType_(saved, NSPasteboardTypeString)

    threading.Thread(target=_restore, daemon=True).start()


def translate_selection(
    source: str = config.DEFAULT_SOURCE,
    target: str = config.DEFAULT_TARGET,
) -> None:
    """Translate the current selection in place.

    Reads the selection; if nothing is selected, does nothing. Otherwise
    translates it and pastes the result back over the selection.
    """
    text = _read_selection_via_copy().strip()
    if not text:
        _log(
            "no text captured (nothing selected, or Cmd+C was blocked / not "
            "permitted). Check Accessibility permission."
        )
        return
    _log(f"captured: {text!r}")

    try:
        result = "".join(translate_stream(text, source, target)).strip()
    except Exception as exc:  # API/network/auth errors
        _log(f"translation error: {exc}")
        return

    if not result:
        _log("translation returned empty")
        return
    _log(f"translated -> {result!r}; pasting")
    _paste_text(result)


def run_hotkey_listener() -> keyboard.GlobalHotKeys:
    """Register and start the global hotkey listener; return it."""

    def _on_activate() -> None:
        # Run the translation off the listener thread so the hotkey handler
        # never blocks on the network call.
        _log("hotkey fired")
        threading.Thread(target=translate_selection, daemon=True).start()

    listener = keyboard.GlobalHotKeys({config.HOTKEY: _on_activate})
    listener.start()
    return listener


def main() -> None:
    import sys

    if "--debug" in sys.argv:
        _run_key_debugger()
        return

    global VERBOSE
    if "--verbose" in sys.argv or "-v" in sys.argv:
        VERBOSE = True

    listener = run_hotkey_listener()
    print(
        f"type-fast hotkey listener running. Press {config.HOTKEY} to translate "
        f"the current selection ({config.DEFAULT_SOURCE} -> {config.DEFAULT_TARGET}).\n"
        "Override the hotkey with the TYPE_FAST_HOTKEY env var, e.g.\n"
        "    export TYPE_FAST_HOTKEY='<cmd>+<shift>+j'\n"
        "Run with --verbose to print each stage (hotkey/copy/translate/paste).\n"
        "Run with --debug to check whether key events reach the app (permissions).\n"
        "Press Ctrl+C here to quit."
    )
    try:
        listener.join()
    except KeyboardInterrupt:
        listener.stop()
        print("\nStopped.")


def _run_key_debugger() -> None:
    """Print every key press so you can verify the listener receives events.

    If NOTHING prints when you type (with another app focused), macOS is not
    delivering key events to this process -> grant Input Monitoring AND
    Accessibility to the app you launched this from (Terminal / your editor)
    in System Settings -> Privacy & Security, then restart.
    """
    print(
        "Key debug mode. Focus another app and type. Each key press should print "
        "here.\nIf nothing prints, grant Input Monitoring + Accessibility to this "
        "terminal.\nPress Ctrl+C to quit."
    )

    def _on_press(key) -> None:
        print(f"key: {key!r}")

    listener = keyboard.Listener(on_press=_on_press)
    listener.start()
    try:
        listener.join()
    except KeyboardInterrupt:
        listener.stop()
        print("\nStopped.")


if __name__ == "__main__":
    main()

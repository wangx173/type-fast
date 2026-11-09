"""Windows native integration is deferred; use the safe null implementation."""

from .null import (
    GlobalHotkey,
    PASTE_SETTINGS_URL,
    activate_app,
    clipboard_change_count,
    frontmost_app_pid,
    hide_app,
    input_event_count,
    paste_permission_granted,
    paste_supported,
    send_paste,
    uses_native_keycodes,
)

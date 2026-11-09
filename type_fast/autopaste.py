"""Compatibility entry points; OS integration lives in type_fast.platform."""

from .platform import (
    input_event_count,
    paste_permission_granted as has_permission,
    paste_supported as is_supported,
    send_paste,
)

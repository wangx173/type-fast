"""Read/write access to the system's currently focused UI element.

Used to anchor the Phase 2 overlay near the field the user is editing and,
where the focused element supports it, inject translated text directly into
it via the Accessibility API instead of going through the clipboard. Like the
hotkey and auto-paste flows in :mod:`type_fast.hotkey`/:mod:`type_fast.focus`,
this requires the process to be Accessibility-trusted; without it, every
function below returns ``None``/``False`` rather than raising, so callers can
always fall back to the Phase 1 clipboard/auto-paste flow.
"""

from __future__ import annotations

from typing import Optional

try:
    from ApplicationServices import (
        AXUIElementCopyAttributeValue,
        AXUIElementCreateSystemWide,
        AXUIElementIsAttributeSettable,
        AXUIElementSetAttributeValue,
        AXValueGetValue,
        kAXFocusedUIElementAttribute,
        kAXPositionAttribute,
        kAXSizeAttribute,
        kAXValueAttribute,
        kAXValueCGPointType,
        kAXValueCGSizeType,
    )

    _AVAILABLE = True
except ImportError:  # pragma: no cover - non-macOS or missing pyobjc extras
    _AVAILABLE = False

# AXError success code (kAXErrorSuccess).
_AX_SUCCESS = 0


def available() -> bool:
    """Return True if the Accessibility element APIs are importable here."""
    return _AVAILABLE


def focused_element() -> Optional[object]:
    """Return the AXUIElement for the system's focused UI element, or None.

    Returns None when unavailable, untrusted, or when no element is currently
    focused (e.g. focus is on something that isn't a standard accessible
    element) — callers should treat that as "fall back to Phase 1 behavior".
    """
    if not _AVAILABLE:
        return None
    system_wide = AXUIElementCreateSystemWide()
    err, element = AXUIElementCopyAttributeValue(
        system_wide, kAXFocusedUIElementAttribute, None
    )
    if err != _AX_SUCCESS or element is None:
        return None
    return element


def element_bounds(element: object) -> Optional[tuple[float, float, float, float]]:
    """Return ``(x, y, width, height)`` of ``element`` in screen coordinates.

    This anchors the overlay near the field the user is editing, using the
    element's own frame rather than the exact caret position within it — a
    finer-grained caret rect would need the parameterized bounds-for-range
    attribute, which not every app implements consistently. Anchoring on the
    field itself is a reasonable approximation for a popup overlay.
    """
    if not _AVAILABLE or element is None:
        return None
    err, pos_value = AXUIElementCopyAttributeValue(element, kAXPositionAttribute, None)
    if err != _AX_SUCCESS or pos_value is None:
        return None
    err, size_value = AXUIElementCopyAttributeValue(element, kAXSizeAttribute, None)
    if err != _AX_SUCCESS or size_value is None:
        return None

    ok, point = AXValueGetValue(pos_value, kAXValueCGPointType, None)
    if not ok:
        return None
    ok, size = AXValueGetValue(size_value, kAXValueCGSizeType, None)
    if not ok:
        return None
    return (point.x, point.y, size.width, size.height)


def is_value_settable(element: object) -> bool:
    """Return True if ``element``'s text value can be set directly.

    Many web/Electron/canvas-based text areas don't expose a settable
    ``AXValue`` even when they otherwise participate in the Accessibility
    tree; this lets callers detect that up front and fall back to
    clipboard+paste instead of silently failing.
    """
    if not _AVAILABLE or element is None:
        return False
    err, settable = AXUIElementIsAttributeSettable(element, kAXValueAttribute, None)
    return err == _AX_SUCCESS and bool(settable)


def set_value(element: object, text: str) -> bool:
    """Set the focused element's text value directly. Returns success."""
    if not _AVAILABLE or element is None:
        return False
    err = AXUIElementSetAttributeValue(element, kAXValueAttribute, text)
    return err == _AX_SUCCESS

"""Unit tests for the app icon assets and how the app and build use them."""

from __future__ import annotations

import os
import re
import struct
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

_HEADLESS = os.environ.get("QT_QPA_PLATFORM") == "offscreen"

ROOT = Path(__file__).resolve().parent.parent
SVG_PATH = ROOT / "assets" / "icon" / "type-fast.svg"
ICNS_PATH = ROOT / "assets" / "icon" / "TypeFast.icns"
ICO_PATH = ROOT / "assets" / "icon" / "TypeFast.ico"
PNG_PATH = ROOT / "type_fast" / "resources" / "icon.png"

# icns element types for every size in a full .iconset (16 to 1024 px,
# including the @2x variants), as written by ``iconutil``.
_ICNS_TYPES = {
    b"ic04", b"ic05", b"ic07", b"ic08", b"ic09",
    b"ic10", b"ic11", b"ic12", b"ic13", b"ic14",
}


def _icns_types(data: bytes) -> set[bytes]:
    magic, total = struct.unpack(">4sI", data[:8])
    if magic != b"icns" or total != len(data):
        raise ValueError("not a valid .icns file")
    types, offset = set(), 8
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("truncated .icns element header")
        kind, length = struct.unpack(">4sI", data[offset:offset + 8])
        if length < 8 or offset + length > len(data):
            raise ValueError("corrupt .icns element")
        types.add(kind)
        offset += length
    return types


class IconAssetTests(unittest.TestCase):
    def test_svg_master_is_square_and_self_contained(self) -> None:
        root = ET.parse(SVG_PATH).getroot()
        self.assertEqual(root.get("viewBox"), "0 0 1024 1024")
        tags = {el.tag.rsplit("}", 1)[-1] for el in root.iter()}
        # Plain paths only: no fonts, embedded images, or filters, which keeps
        # the art original and renderable by Qt's SVG renderer.
        self.assertFalse(tags & {"text", "image", "filter", "use", "style"}, tags)

    def test_icns_has_every_size(self) -> None:
        types = _icns_types(ICNS_PATH.read_bytes())
        self.assertLessEqual(_ICNS_TYPES, types)

    def test_ico_has_every_size(self) -> None:
        data = ICO_PATH.read_bytes()
        reserved, kind, count = struct.unpack_from("<HHH", data)
        self.assertEqual((reserved, kind, count), (0, 1, 6))
        sizes = set()
        for index in range(count):
            width, height, _, _, planes, bits, length, offset = struct.unpack_from(
                "<BBBBHHII", data, 6 + index * 16,
            )
            size = (width or 256, height or 256)
            sizes.add(size)
            self.assertEqual((planes, bits), (1, 32))
            self.assertGreaterEqual(offset, 6 + count * 16)
            self.assertGreater(length, 0)
            self.assertLessEqual(offset + length, len(data))
            self.assertEqual(data[offset:offset + 8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack_from(">II", data, offset + 16), size)
        self.assertEqual(sizes, {(size, size) for size in (16, 24, 32, 48, 64, 256)})

    def test_build_uses_the_icon(self) -> None:
        spec = (ROOT / "Type Fast.spec").read_text(encoding="utf-8")
        self.assertRegex(spec, r'icon="assets/icon/TypeFast\.icns"')
        self.assertRegex(spec, r'icon="assets/icon/TypeFast\.ico"')
        self.assertIn('("type_fast/resources/icon.png", "type_fast/resources")', spec)
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertTrue(
            re.search(r'type_fast = \[[^\]]*"resources/\*\.png"', pyproject),
            "icon.png must ship as package data",
        )


@unittest.skipUnless(_HEADLESS, "set QT_QPA_PLATFORM=offscreen to run the headless icon tests")
class IconRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_svg_renders(self) -> None:
        from PySide6.QtSvg import QSvgRenderer

        renderer = QSvgRenderer(str(SVG_PATH))
        self.assertTrue(renderer.isValid())
        self.assertEqual(renderer.defaultSize().width(), 1024)
        self.assertEqual(renderer.defaultSize().height(), 1024)

    def test_app_icon_loads(self) -> None:
        from PySide6.QtGui import QImage

        from type_fast import app

        self.assertEqual(app.ICON_PATH, PNG_PATH)
        image = QImage(str(app.ICON_PATH))
        self.assertEqual((image.width(), image.height()), (512, 512))
        icon = app.app_icon()
        self.assertFalse(icon.isNull())
        self.assertFalse(icon.pixmap(32, 32).isNull())

    def test_windows_icon_small_sizes_load(self) -> None:
        from PySide6.QtGui import QIcon

        icon = QIcon(str(ICO_PATH))
        self.assertFalse(icon.isNull())
        for size in (16, 32, 256):
            pixmap = icon.pixmap(size, size)
            self.assertFalse(pixmap.isNull())
            self.assertEqual((pixmap.width(), pixmap.height()), (size, size))


if __name__ == "__main__":
    unittest.main()

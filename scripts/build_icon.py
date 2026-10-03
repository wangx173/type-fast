"""Regenerate the app icon files from the SVG master.

Renders ``assets/icon/type-fast.svg`` with Qt's SVG renderer (part of PySide6,
already a dependency) and writes:

* ``assets/icon/TypeFast.icns`` — the macOS app icon used by the PyInstaller
  bundle, built from a temporary ``.iconset`` with ``iconutil`` (macOS only).
* ``type_fast/resources/icon.png`` — the 512 px window/Dock icon the app sets
  at runtime, so the icon also shows when running from source.

Run from the repository root after editing the SVG::

    python scripts/build_icon.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SVG_PATH = ROOT / "assets" / "icon" / "type-fast.svg"
ICNS_PATH = ROOT / "assets" / "icon" / "TypeFast.icns"
PNG_PATH = ROOT / "type_fast" / "resources" / "icon.png"
PNG_SIZE = 512

# The base sizes ``iconutil`` expects in an .iconset, each at 1x and 2x.
ICONSET_SIZES = (16, 32, 128, 256, 512)


def render(renderer: QSvgRenderer, size: int) -> QImage:
    """Render the SVG into a transparent ``size`` x ``size`` image."""
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def save(image: QImage, path: Path) -> None:
    if not image.save(str(path), "PNG"):
        raise RuntimeError(f"could not write {path}")


def main() -> int:
    if shutil.which("iconutil") is None:
        print("error: iconutil not found; building the .icns requires macOS",
              file=sys.stderr)
        return 1

    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        print(f"error: could not load {SVG_PATH}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "TypeFast.iconset"
        iconset.mkdir()
        for size in ICONSET_SIZES:
            save(render(renderer, size), iconset / f"icon_{size}x{size}.png")
            save(render(renderer, size * 2),
                 iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS_PATH)],
            check=True,
        )

    PNG_PATH.parent.mkdir(parents=True, exist_ok=True)
    save(render(renderer, PNG_SIZE), PNG_PATH)

    for path in (ICNS_PATH, PNG_PATH):
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

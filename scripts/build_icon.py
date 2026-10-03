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

# Render without a display; this must be set before PySide6 is imported.
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
    """Write ``image`` to ``path`` as a PNG."""
    if not image.save(str(path), "PNG"):
        raise OSError(f"could not write PNG to {path}; check that its folder "
                      "exists and is writable")


def main() -> int:
    if shutil.which("iconutil") is None:
        print("error: iconutil not found; building the .icns requires macOS",
              file=sys.stderr)
        return 1

    # Qt needs a live QGuiApplication to render; keep a reference until done.
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        print(f"error: could not load {SVG_PATH}", file=sys.stderr)
        return 1

    # Build both files in a temporary folder first, so a failure never leaves
    # a new .icns next to a stale PNG (or the other way around).
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "TypeFast.iconset"
        iconset.mkdir()
        for size in ICONSET_SIZES:
            save(render(renderer, size), iconset / f"icon_{size}x{size}.png")
            save(render(renderer, size * 2),
                 iconset / f"icon_{size}x{size}@2x.png")
        icns = Path(tmp) / ICNS_PATH.name
        result = subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"error: iconutil failed: {result.stderr.strip()}",
                  file=sys.stderr)
            return 1
        png = Path(tmp) / PNG_PATH.name
        save(render(renderer, PNG_SIZE), png)

        PNG_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(icns, ICNS_PATH)
        shutil.copyfile(png, PNG_PATH)

    for path in (ICNS_PATH, PNG_PATH):
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

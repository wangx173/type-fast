"""Export the Windows ICO from the SVG master using the app's Qt dependency."""

from pathlib import Path
import struct

from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
SIZES = (16, 24, 32, 48, 64, 256)


def main() -> None:
    renderer = QSvgRenderer(str(ROOT / "assets/icon/type-fast.svg"))
    if not renderer.isValid():
        raise RuntimeError("Cannot render the SVG icon master")
    entries, images = [], []
    offset = 6 + len(SIZES) * 16
    for size in SIZES:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, "PNG"):
            raise RuntimeError(f"Cannot encode the {size}px icon")
        png = bytes(data)
        entries.append(struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset,
        ))
        images.append(png)
        offset += len(png)
    (ROOT / "assets/icon/TypeFast.ico").write_bytes(
        struct.pack("<HHH", 0, 1, len(SIZES)) + b"".join(entries + images),
    )


if __name__ == "__main__":
    main()

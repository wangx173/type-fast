"""Render the demo GIF and screenshots in docs/images from the real window.

Run on macOS from the repository root, after installing the app and Pillow:

    pip install -e . pillow
    python scripts/make_screenshots.py

It writes demo.gif (and demo.png, a still of its last step), hotkey.png, and
languages.png. The Type Fast window is the real ``MainWindow`` drawn with
sample text; the desktop, the chat app, and the key badges around it are drawn
by this script. It reads no API key, sends no requests, registers no hotkey,
and uses a throwaway home folder, so none of your settings appear. Nothing is
shown on screen, though Python may appear in the Dock while it runs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent

# Everything is drawn at 2x (Retina); the GIF is scaled down from that.
SCALE = 2
GIF_SCALE = 1.5

# The "screen" of the demo, in points.
SCENE_W, SCENE_H = 820, 560
TITLE_H = 28
SHADOW_MARGIN = 40

# The chat app behind Type Fast.
CHAT_X, CHAT_Y, CHAT_W, CHAT_H = 110, 24, 600, 480
COMPOSE_H = 36

# The Type Fast window as summoned by the hotkey (compact layout), centered in
# the upper part of the screen like MainWindow._center_on_cursor_screen.
POPUP_W, POPUP_H = 460, 240
POPUP_X = (SCENE_W - POPUP_W) // 2
POPUP_Y = (SCENE_H - POPUP_H - TITLE_H) // 4

ACCENT = "#007aff"
CONTACT = "Yuki Tanaka"
INCOMING = "お疲れさまです！明日は東京オフィスに来られますか？"
TYPED = "Yes, I will! Are you free for lunch?"
# Ending a sentence translates right away (MainWindow._on_text_changed), so
# the first sentence is translated while the rest is still being typed.
PARTIAL = ("Yes, I will!", "はい、伺います！")
TRANSLATION = "はい、伺います！ランチはご一緒できますか？"

WINDOW_BUTTONS = ("#ff5f57", "#febc2e", "#28c840")

BUSY = ("Translating\u2026", "busy")
COPIED = ("Copied to clipboard \u2713", "done")


@dataclass(frozen=True)
class Frame:
    """One step of the demo, shown for ``ms`` milliseconds."""

    ms: int
    caret: bool = False  # caret in the chat app's message box
    compose: str = ""  # text in the chat app's message box
    sent: bool = False  # the reply has been sent
    popup: float = 0.0  # Type Fast window opacity; 0 is hidden
    typed: str = ""
    output: str = ""
    status: tuple[str, str] = ("", "")
    badge: tuple[str, str] | None = None  # (keys, caption)


def timeline() -> list[Frame]:
    show = ("\u21e7\u2318Space", "Show Type Fast")
    hide = ("\u21e7\u2318Space", "Hide Type Fast")

    # Typing in the chat app's message box, with a blinking caret.
    frames = [Frame(700, caret=True), Frame(500), Frame(700, caret=True)]
    frames.append(Frame(300, caret=True, badge=show))
    # The hotkey fades Type Fast in (MainWindow.summon); with the default Light
    # transparency it is 95% opaque while in use.
    for opacity in (0.35, 0.7, 0.95):
        frames.append(Frame(50, popup=opacity, badge=show))
    popup = Frame(0, popup=0.95)

    output, status = "", ("", "")
    ends = sorted(set(range(2, len(TYPED), 2)) | {len(PARTIAL[0]), len(TYPED)})
    for end in ends:
        typed = TYPED[:end]
        frames.append(replace(popup, ms=80, typed=typed, output=output, status=status,
                              badge=show if end <= 6 else None))
        if typed == PARTIAL[0]:
            frames += _streaming(replace(popup, typed=typed), PARTIAL[1], hold=700)
            output, status = PARTIAL[1], COPIED
    done = replace(popup, typed=TYPED, output=TRANSLATION, status=COPIED)
    frames += _streaming(done, TRANSLATION, hold=1600)

    frames.append(replace(done, ms=350, badge=hide))
    # Hiding is instant (MainWindow.dismiss), and the chat app is active again.
    frames.append(Frame(500, caret=True, badge=hide))
    frames.append(Frame(1000, caret=True, compose=TRANSLATION, badge=("\u2318V", "Paste")))
    frames.append(Frame(2600, caret=True, sent=True, badge=("\u23ce", "Send")))
    return frames


def _streaming(base: Frame, text: str, hold: int) -> list[Frame]:
    """A translation of ``text`` streaming in, then copied to the clipboard."""
    frames = [replace(base, ms=250, output="", status=BUSY)]
    for end in range(3, len(text), 3):
        frames.append(replace(base, ms=70, output=text[:end], status=BUSY))
    frames.append(replace(base, ms=hold, output=text, status=COPIED))
    return frames


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out", type=Path, default=ROOT / "docs" / "images", help="output folder"
    )
    args = parser.parse_args()
    if sys.platform != "darwin":
        sys.exit("Run this on macOS; the window is drawn with the native style.")
    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit("Pillow is required: pip install pillow")

    with tempfile.TemporaryDirectory() as home:
        # type_fast finds ~/.type-fast when it is imported, so isolate it first.
        os.environ["HOME"] = home
        for name in list(os.environ):
            if name.startswith(("OPENAI_", "AZURE_AI_")):
                del os.environ[name]
        sys.path.insert(0, str(ROOT))
        Renderer(args.out).run()


class Renderer:
    def __init__(self, out: Path) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        self.out = out
        self.app = QApplication.instance() or QApplication([])
        self.app.setApplicationName("Type Fast")
        hints = self.app.styleHints()
        if hasattr(hints, "setColorScheme"):
            hints.setColorScheme(Qt.ColorScheme.Light)

    def run(self) -> None:
        from type_fast import app as tf
        from type_fast import hotkey, providers

        patches = (
            # Show the hotkey hint as if registered, without registering it.
            mock.patch.object(hotkey.GlobalHotkey, "register", return_value=True),
            mock.patch.object(
                hotkey.GlobalHotkey,
                "is_registered",
                new_callable=mock.PropertyMock,
                return_value=True,
            ),
            mock.patch.object(hotkey, "activate_app"),
            mock.patch.object(hotkey, "hide_app"),
            mock.patch.object(providers, "has_credentials", return_value=True),
            mock.patch.object(tf.MainWindow, "run_translation"),
        )
        for patch in patches:
            patch.start()
        try:
            self.out.mkdir(parents=True, exist_ok=True)
            self._demo(tf)
            self._hotkey_png(tf)
            self._languages_png(tf)
        finally:
            for patch in reversed(patches):
                patch.stop()

    def _window(self, tf, source: str, target: str, tone: str, compact: bool, size):
        """A Type Fast window with the given settings, never shown."""
        from type_fast import settings

        settings.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        settings.SETTINGS_FILE.write_text(
            json.dumps({"source": source, "target": target, "tone": tone}),
            encoding="utf-8",
        )
        window = tf.MainWindow()
        window.resize(*size)
        window.set_compact(compact)
        # The window is never shown, so draw the input box as focused.
        central = window.centralWidget()
        central.setStyleSheet(
            central.styleSheet()
            + "\nQPlainTextEdit#inputBox { border: 1px solid palette(highlight); }"
        )
        window.input.blockSignals(True)
        self._render(window)  # lay it out
        return window

    @staticmethod
    def _fill(window, typed: str, output: str, status: tuple[str, str]) -> None:
        from PySide6.QtGui import QTextCursor

        window.input.setPlainText(typed)
        window.input.moveCursor(QTextCursor.End)
        window.output.setPlainText(output)
        window._set_status(*status)

    @staticmethod
    def _render(window, caret: bool = False):
        """The window's contents, with a caret in the input box if ``caret``."""
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPainter

        image = _image(window.width(), window.height())
        window.render(image)
        if caret:
            rect = window.input.cursorRect()
            top = window.input.viewport().mapTo(window, rect.topLeft())
            painter = QPainter(image)
            painter.fillRect(QRectF(top.x(), top.y() + 1, 1.5, rect.height() - 2), QColor(ACCENT))
            painter.end()
        return image

    def _demo(self, tf) -> None:
        window = self._window(tf, "English", "Japanese", "Polite", True, (POPUP_W, POPUP_H))
        popups: dict = {}
        chats: dict = {}
        steps = []
        for frame in timeline():
            popup = None
            if frame.popup:
                key = (frame.typed, frame.output, frame.status)
                if key not in popups:
                    self._fill(window, *key)
                    popups[key] = _shadowed(_framed(self._render(window, caret=True), "Type Fast"))
                popup = popups[key]
            # The chat app is inactive while Type Fast is in front.
            key = (frame.caret, frame.compose, frame.sent, not frame.popup)
            if key not in chats:
                chats[key] = _shadowed(_framed(_chat(*key[:3]), "Chat", active=key[3]))
            steps.append((_scene(chats[key], popup, frame.popup, frame.badge), frame.ms))
        _save_gif(steps, self.out / "demo.gif")
        path = self.out / "demo.png"
        _to_pil(steps[-1][0]).save(path, optimize=True)
        print(f"wrote {path}")

    def _hotkey_png(self, tf) -> None:
        window = self._window(tf, "Japanese", "English", "Polite", True, (POPUP_W, POPUP_H))
        self._fill(
            window,
            "今夜の夕食、何時にする？",
            "What time do you want to have dinner tonight?",
            COPIED,
        )
        _save_png(_shadowed(_framed(self._render(window), "Type Fast")), self.out / "hotkey.png")

    def _languages_png(self, tf) -> None:
        from type_fast import config

        window = self._window(tf, config.AUTO_SOURCE, "Spanish", "Business", False, (600, 400))
        self._fill(
            window,
            "Hi team, the release is moving to Friday. Please send any last "
            "changes by Thursday noon.",
            "Hola, equipo: el lanzamiento se traslada al viernes. Les ruego que "
            "envíen los últimos cambios antes del jueves al mediodía.",
            COPIED,
        )
        _save_png(_shadowed(_framed(self._render(window), "Type Fast")), self.out / "languages.png")


# --- Drawing ---------------------------------------------------------------


def _image(width: float, height: float):
    """A transparent 2x image of ``width`` x ``height`` points."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage

    image = QImage(round(width * SCALE), round(height * SCALE), QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(SCALE)
    image.fill(Qt.transparent)
    return image


def _size(image) -> tuple[float, float]:
    return image.width() / SCALE, image.height() / SCALE


def _font(size: int, bold: bool = False):
    from PySide6.QtGui import QFont

    font = QFont()
    font.setPixelSize(size)
    font.setBold(bold)
    return font


def _painter(image):
    from PySide6.QtGui import QPainter

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    return painter


def _framed(content, title: str, active: bool = True):
    """``content`` in a macOS-style window with a title bar."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QPainterPath, QPalette, QPen
    from PySide6.QtWidgets import QApplication

    width, height = _size(content)
    bounds = QRectF(0, 0, width, height + TITLE_H)
    image = _image(bounds.width(), bounds.height())
    painter = _painter(image)
    outline = QPainterPath()
    outline.addRoundedRect(bounds, 10, 10)
    painter.setClipPath(outline)
    painter.fillRect(bounds, QApplication.palette().color(QPalette.Window))
    painter.drawImage(QRectF(0, TITLE_H, width, height), content)
    painter.setPen(Qt.NoPen)
    for index, color in enumerate(WINDOW_BUTTONS):
        painter.setBrush(QColor(color if active else "#d1d1d6"))
        painter.drawEllipse(QRectF(13 + index * 20, TITLE_H / 2 - 6, 12, 12))
    painter.setPen(QColor("#3a3a3c" if active else "#a1a1a6"))
    painter.setFont(_font(13, bold=True))
    painter.drawText(QRectF(0, 0, width, TITLE_H), Qt.AlignCenter, title)
    painter.setClipping(False)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor(0, 0, 0, 40), 1))
    painter.drawPath(outline)
    painter.end()
    return image


def _shadowed(window):
    """``window`` with a soft drop shadow, on a transparent margin."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPixmap
    from PySide6.QtWidgets import (
        QGraphicsDropShadowEffect,
        QGraphicsPixmapItem,
        QGraphicsScene,
    )

    width, height = _size(window)
    image = _image(width + 2 * SHADOW_MARGIN, height + 2 * SHADOW_MARGIN)
    scene = QGraphicsScene(0, 0, *_size(image))
    item = QGraphicsPixmapItem(QPixmap.fromImage(window))
    item.setTransformationMode(Qt.SmoothTransformation)
    item.setPos(QPointF(SHADOW_MARGIN, SHADOW_MARGIN))
    effect = QGraphicsDropShadowEffect()
    effect.setBlurRadius(36)
    effect.setOffset(0, 10)
    effect.setColor(QColor(0, 0, 0, 80))
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    painter = _painter(image)
    # The default target is the image's size in pixels, not points.
    scene.render(painter, scene.sceneRect(), scene.sceneRect())
    painter.end()
    return image


def _bubble_size(text: str):
    """The size of a chat bubble holding ``text``."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QFontMetricsF

    bounds = QFontMetricsF(_font(14)).boundingRect(QRectF(0, 0, 420, 1000), Qt.TextWordWrap, text)
    return bounds.adjusted(0, 0, 24, 14).size()


def _bubble(painter, x: float, y: float, text: str, fill: str, color: str, right: bool = False):
    """Draw a chat bubble from ``x`` (its right edge if ``right``); return its bottom."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor

    size = _bubble_size(text)
    rect = QRectF(x - size.width() if right else x, y, size.width(), size.height())
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(fill))
    painter.drawRoundedRect(rect, 16, 16)
    painter.setPen(QColor(color))
    painter.setFont(_font(14))
    painter.drawText(rect.adjusted(12, 7, -12, -7), Qt.TextWordWrap, text)
    return rect.bottom()


def _chat(caret: bool, compose: str, sent: bool):
    """The contents of a simple chat app, below its title bar."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QPen

    width, height = CHAT_W, CHAT_H - TITLE_H
    image = _image(width, height)
    image.fill(QColor("#ffffff"))
    painter = _painter(image)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#f08c3c"))
    painter.drawEllipse(QRectF(18, 10, 36, 36))
    painter.setPen(QColor("#ffffff"))
    painter.setFont(_font(14, bold=True))
    painter.drawText(QRectF(18, 10, 36, 36), Qt.AlignCenter, "YT")
    painter.setPen(QColor("#1d1d1f"))
    painter.drawText(QRectF(66, 11, 300, 18), Qt.AlignLeft | Qt.AlignVCenter, CONTACT)
    painter.setPen(QColor("#6e6e73"))
    painter.setFont(_font(11))
    painter.drawText(QRectF(66, 29, 300, 16), Qt.AlignLeft | Qt.AlignVCenter, "Tokyo office")
    painter.setPen(QPen(QColor("#e5e5ea"), 1))
    painter.drawLine(0, 56, width, 56)

    # Messages sit just above the message box, newest last, so they stay in
    # view below Type Fast.
    box = QRectF(16, height - COMPOSE_H - 14, width - 32, COMPOSE_H)
    bubbles = [(20, INCOMING, "#e9e9eb", "#1d1d1f", False)]
    if sent:
        bubbles.append((width - 20, TRANSLATION, ACCENT, "#ffffff", True))
    y = box.top() - 14 - sum(_bubble_size(text).height() + 8 for _, text, *_ in bubbles)
    painter.setPen(QColor("#8e8e93"))
    painter.setFont(_font(11))
    painter.drawText(QRectF(0, y - 22, width, 16), Qt.AlignCenter, "Today 16:42")
    for x, text, fill, color, right in bubbles:
        y = _bubble(painter, x, y, text, fill, color, right) + 8

    painter.setPen(QPen(QColor("#d1d1d6"), 1))
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(box, COMPOSE_H / 2, COMPOSE_H / 2)
    text_rect = box.adjusted(16, 0, -16, 0)
    font = _font(14)
    painter.setFont(font)
    if compose:
        painter.setPen(QColor("#1d1d1f"))
        drawn = painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, compose)
        caret_x = drawn.right() + 1
    else:
        painter.setPen(QColor("#8e8e93"))
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, f"Message {CONTACT}")
        caret_x = text_rect.left() - 1
    if caret:
        painter.fillRect(QRectF(caret_x, box.center().y() - 9, 1.5, 18), QColor(ACCENT))
    painter.end()
    return image


def _wallpaper():
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QColor, QLinearGradient

    image = _image(SCENE_W, SCENE_H)
    painter = _painter(image)
    gradient = QLinearGradient(QPointF(0, 0), QPointF(SCENE_W, SCENE_H))
    gradient.setColorAt(0, QColor("#a8c0ff"))
    gradient.setColorAt(1, QColor("#c9b6f2"))
    painter.fillRect(QRectF(0, 0, SCENE_W, SCENE_H), gradient)
    painter.end()
    return image


def _scene(chat, popup, opacity: float, badge):
    """One frame: the desktop, the chat app, Type Fast, and a key badge.

    ``chat`` and ``popup`` are windows already drawn with their shadows.
    """
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFontMetricsF

    image = _wallpaper()
    painter = _painter(image)
    for window, x, y, alpha in ((chat, CHAT_X, CHAT_Y, 1.0), (popup, POPUP_X, POPUP_Y, opacity)):
        if window is not None:
            painter.setOpacity(alpha)
            painter.drawImage(
                QRectF(x - SHADOW_MARGIN, y - SHADOW_MARGIN, *_size(window)), window
            )
    painter.setOpacity(1.0)

    if badge is not None:
        keys, caption = badge
        key_font, caption_font = _font(20, bold=True), _font(14)
        key_w = QFontMetricsF(key_font).horizontalAdvance(keys)
        caption_w = QFontMetricsF(caption_font).horizontalAdvance(caption)
        rect = QRectF(0, SCENE_H - 52, key_w + caption_w + 46, 38)
        rect.moveLeft((SCENE_W - rect.width()) / 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(28, 28, 30, 225))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(key_font)
        painter.drawText(rect.adjusted(16, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, keys)
        painter.setPen(QColor("#d1d1d6"))
        painter.setFont(caption_font)
        painter.drawText(
            rect.adjusted(16 + key_w + 14, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, caption
        )
    painter.end()
    return image


# --- Saving ----------------------------------------------------------------


def _to_pil(image, scale: float = GIF_SCALE / SCALE):
    """Convert a QImage to an RGB Pillow image, resized by ``scale``."""
    from PIL import Image
    from PySide6.QtGui import QImage

    rgba = image.convertToFormat(QImage.Format_RGBA8888)
    pil = Image.frombuffer(
        "RGBA", (rgba.width(), rgba.height()), bytes(rgba.constBits()), "raw", "RGBA",
        rgba.bytesPerLine(), 1,
    ).convert("RGB")
    size = (round(pil.width * scale), round(pil.height * scale))
    return pil.resize(size, Image.LANCZOS) if size != pil.size else pil


def _save_gif(steps, path: Path) -> None:
    from PIL import Image
    from type_fast.app import _TEXT_COLORS

    frames = [_to_pil(image) for image, _ in steps]
    # One shared palette and no dithering, so unchanged areas stay identical
    # between frames and only the changes are stored.
    picks = (frames[0], frames[len(frames) // 2], frames[-1])
    width, height = frames[0].size
    sample = Image.new("RGB", (width, height * len(picks) + 64))
    for index, frame in enumerate(picks):
        sample.paste(frame, (0, height * index))
    # Small but important colors (window buttons, status text) would otherwise
    # be merged into their neighbors.
    swatches = (*WINDOW_BUTTONS, ACCENT, *_TEXT_COLORS["light"].values())
    for index, color in enumerate(swatches):
        sample.paste(color, (index * 64, height * len(picks), index * 64 + 64, height * len(picks) + 64))
    palette = sample.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    quantized = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    quantized[0].save(
        path,
        save_all=True,
        append_images=quantized[1:],
        duration=[ms for _, ms in steps],
        loop=0,
        optimize=True,
    )
    print(f"wrote {path} ({len(frames)} frames, {path.stat().st_size // 1024} KB)")


def _save_png(image, path: Path) -> None:
    image.save(str(path))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()

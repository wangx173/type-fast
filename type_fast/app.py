"""PySide6 PoC window for type-fast.

A small always-on-top window with an input box, a streamed output box, and an
English <-> Japanese direction toggle. Typing triggers a translation after a
short idle debounce, or immediately when the input ends in sentence-ending
punctuation or Enter is pressed. Translation runs on a worker thread and streams
results back to the UI via Qt signals so the interface never freezes.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QPlainTextEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import config
from .translator import translate_stream

# Characters that, when at the end of the input, trigger an immediate
# translation instead of waiting for the idle debounce.
_SENTENCE_ENDINGS = (".", "!", "?", "\u3002", "\uff01", "\uff1f")

_DIRECTIONS = [
    ("English \u2192 Japanese", "English", "Japanese"),
    ("Japanese \u2192 English", "Japanese", "English"),
]


class Bridge(QObject):
    """Thread-safe channel for streaming results back to the UI thread."""

    started = Signal(int)
    delta = Signal(int, str)
    error = Signal(int, str)


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("type-fast")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        self.direction = QComboBox()
        self.direction.addItems([label for label, _, _ in _DIRECTIONS])

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Type here\u2026")

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Translation appears here\u2026")

        layout = QVBoxLayout(self)
        for widget in (self.direction, self.input, self.output):
            layout.addWidget(widget)

        # Monotonic id identifying the most recent translation request so that
        # superseded, slower in-flight translations are discarded.
        self._request_id = 0

        self.bridge = Bridge()
        self.bridge.started.connect(self._on_started)
        self.bridge.delta.connect(self._on_delta)
        self.bridge.error.connect(self._on_error)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(config.DEBOUNCE_MS)
        self.timer.timeout.connect(self.run_translation)

        self.input.textChanged.connect(self._on_text_changed)
        self.direction.currentIndexChanged.connect(self._on_text_changed)

    def _on_text_changed(self) -> None:
        text = self.input.toPlainText()
        if text.rstrip().endswith(_SENTENCE_ENDINGS):
            self.timer.stop()
            self.run_translation()
        else:
            self.timer.start()

    def run_translation(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            return

        _, source, target = _DIRECTIONS[self.direction.currentIndex()]

        self._request_id += 1
        request_id = self._request_id
        self.bridge.started.emit(request_id)

        thread = threading.Thread(
            target=self._translate_worker,
            args=(request_id, text, source, target),
            daemon=True,
        )
        thread.start()

    def _translate_worker(
        self, request_id: int, text: str, source: str, target: str
    ) -> None:
        def superseded() -> bool:
            return request_id != self._request_id

        try:
            for chunk in translate_stream(
                text, source, target, should_cancel=superseded
            ):
                if superseded():
                    return
                self.bridge.delta.emit(request_id, chunk)
        except Exception as exc:  # surface API/network errors in the UI
            self.bridge.error.emit(request_id, str(exc))

    def _on_started(self, request_id: int) -> None:
        if request_id == self._request_id:
            self.output.clear()

    def _on_delta(self, request_id: int, chunk: str) -> None:
        if request_id == self._request_id:
            self.output.insertPlainText(chunk)

    def _on_error(self, request_id: int, message: str) -> None:
        if request_id == self._request_id:
            self.output.setPlainText(f"[error] {message}")


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(420, 320)
    window.show()
    app.exec()


if __name__ == "__main__":
    main()

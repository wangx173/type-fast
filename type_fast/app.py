"""PySide6 PoC window for type-fast.

A small always-on-top window with an input box, a streamed output box, and an
English <-> Japanese direction toggle. Typing triggers a translation after a
short idle debounce, or immediately when a line ends (Enter) or the input ends
in sentence-ending punctuation. Translation runs on a worker thread and streams
results back to the UI via Qt signals so the interface never freezes.

To keep cost down, only the *active* (current) line of the input is ever sent.
Once you move to the next line, the finished line's translation is frozen and
reused verbatim, so completed lines are never re-translated as you keep typing.
Freezing on newline (rather than punctuation) is language-agnostic, so it works
the same for English, Japanese, and future languages. Editing inside a frozen
prefix transparently re-translates from that point.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QAction, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import accessibility, config, focus, providers
from .hotkey import GlobalHotkey
from .providers import openai as openai_provider
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
    finished = Signal(int, str)
    error = Signal(int, str)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Type Fast")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        self.direction = QComboBox()
        self.direction.addItems([label for label, _, _ in _DIRECTIONS])

        self.input_label = QLabel()
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Type here\u2026")

        self.output_label = QLabel()
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Translation appears here\u2026")

        self.status = QLabel()
        self.status.setAlignment(Qt.AlignRight)
        self.status.setStyleSheet("color: gray;")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(8)
        layout.addWidget(self.direction)
        layout.addWidget(self.input_label)
        layout.addWidget(self.input)
        layout.addWidget(self.output_label)
        layout.addWidget(self.output)
        layout.addWidget(self.status)
        self.setCentralWidget(central)

        self._build_menu()
        self._update_labels()
        self._reflect_key_status()

        # PID of the app that was frontmost when the global hotkey last showed
        # this window, so a finished translation can be auto-pasted back into
        # it. None until the hotkey has been used at least once.
        self._previous_app_pid: int | None = None

        self._hotkey = GlobalHotkey(self._toggle_via_hotkey)
        self._hotkey_active = self._hotkey.start()

        # Monotonic id identifying the most recent translation request so that
        # superseded, slower in-flight translations are discarded.
        self._request_id = 0

        # The last (frozen_src, active, source, target, should_freeze) actually
        # sent, used to skip redundant requests when nothing relevant changed.
        # ``should_freeze`` is part of the key so that adding a newline (which
        # must advance the freeze boundary) is never skipped as a duplicate.
        self._last_sent_key: tuple[str, str, str, str, bool] | None = None

        # Source prefix whose translation is finalized, and its translation.
        # Only the input text *after* ``_frozen_src`` is ever sent to the API.
        self._frozen_src = ""
        self._frozen_out = ""
        # Target language the frozen translation is written in; a direction
        # change invalidates it.
        self._frozen_target = _DIRECTIONS[0][2]

        # Display prefix (frozen translations + separator) shown while the
        # active line streams, plus how to freeze that line once it lands:
        # (should_freeze, frozen_src_after_freeze, display_prefix).
        self._active_prefix = ""
        self._pending_freeze: tuple[bool, str, str] = (False, "", "")

        self.bridge = Bridge()
        self.bridge.started.connect(self._on_started)
        self.bridge.delta.connect(self._on_delta)
        self.bridge.finished.connect(self._on_finished)
        self.bridge.error.connect(self._on_error)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(config.DEBOUNCE_MS)
        self.timer.timeout.connect(self.run_translation)

        self.input.textChanged.connect(self._on_text_changed)
        self.direction.currentIndexChanged.connect(self._on_text_changed)
        self.direction.currentIndexChanged.connect(self._update_labels)

    def _build_menu(self) -> None:
        # On macOS this becomes part of the global menu bar at the top of the
        # screen. "Set OpenAI API Key…" lands in the app menu automatically
        # because of its role-like text, so we add it to a Settings menu too.
        menu = self.menuBar().addMenu("Settings")
        self.set_key_action = QAction("Set OpenAI API Key\u2026", self)
        self.set_key_action.setShortcut(QKeySequence("Ctrl+,"))
        self.set_key_action.triggered.connect(self._set_api_key)
        menu.addAction(self.set_key_action)

        self.grant_access_action = QAction(
            "Grant Accessibility Access\u2026 (for hotkey \u0026 auto-paste)", self
        )
        self.grant_access_action.triggered.connect(self._request_accessibility_access)
        menu.addAction(self.grant_access_action)

    def _reflect_key_status(self) -> None:
        if not providers.has_credentials():
            self.status.setText("No API key set \u2014 Settings \u203a Set OpenAI API Key\u2026")
        elif accessibility.available() and not accessibility.is_trusted():
            self.status.setText(
                "Accessibility access not granted \u2014 hotkey/auto-paste disabled"
            )
        else:
            self.status.setText("")

    def _request_accessibility_access(self) -> None:
        # Triggers the system permission dialog (if not already trusted) and
        # opens the Accessibility settings pane so the user can flip it on;
        # macOS only applies the change after it is granted there.
        accessibility.prompt_for_trust()
        accessibility.open_settings()
        self._reflect_key_status()

    def _toggle_via_hotkey(self) -> None:
        # NSEvent global monitor callbacks land on the main run loop, but Qt
        # widget calls should still go through Qt's own thread affinity, so we
        # only touch Qt objects here (no cross-thread bridging needed since
        # this runs on the same run loop Qt is integrated with).
        if self.isVisible() and self.isActiveWindow():
            self.hide()
            return
        self._previous_app_pid = focus.frontmost_app_pid()
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def _set_api_key(self) -> None:
        current = ""
        try:
            current = openai_provider.get_api_key()
        except openai_provider.MissingAPIKeyError:
            pass
        key, ok = QInputDialog.getText(
            self,
            "Set OpenAI API Key",
            "Enter your OpenAI API key (stored in ~/.type-fast/api_key):",
            QLineEdit.Password,
            current,
        )
        if not ok:
            return
        key = key.strip()
        if not key:
            return
        openai_provider.save_api_key(key)
        providers.reset_client()  # so the next translation uses the new key
        self._reflect_key_status()

    def _update_labels(self) -> None:
        _, source, target = _DIRECTIONS[self.direction.currentIndex()]
        self.input_label.setText(source)
        self.output_label.setText(target)

    def _on_text_changed(self) -> None:
        text = self.input.toPlainText()
        # Pressing Enter (line ends) or finishing a sentence translates now;
        # otherwise wait for the idle debounce.
        if text.endswith("\n") or text.rstrip().endswith(_SENTENCE_ENDINGS):
            self.timer.stop()
            self.run_translation()
        else:
            self.timer.start()

    def run_translation(self) -> None:
        full = self.input.toPlainText()
        _, source, target = _DIRECTIONS[self.direction.currentIndex()]

        # A direction change makes the frozen translation the wrong language.
        if target != self._frozen_target:
            self._frozen_src = ""
            self._frozen_out = ""
            self._frozen_target = target

        # If the frozen prefix was edited, drop it and re-translate from there.
        if not full.startswith(self._frozen_src):
            self._frozen_src = ""
            self._frozen_out = ""

        if not full.strip():
            self._frozen_src = ""
            self._frozen_out = ""
            self._last_sent_key = None
            self.output.clear()
            return

        rest = full[len(self._frozen_src):]
        newline = rest.find("\n")
        if newline == -1:
            # Still typing the current (last) line; not yet frozen.
            active = rest.strip()
            should_freeze = False
            frozen_after = self._frozen_src
        else:
            # The current line is complete (a newline follows); freeze it.
            active = rest[:newline].strip()
            should_freeze = True
            frozen_after = self._frozen_src + rest[: newline + 1]

        if not active:
            if should_freeze and frozen_after != self._frozen_src:
                # Blank completed line: advance the boundary, preserve the gap,
                # and continue with any following lines.
                self._frozen_src = frozen_after
                if self._frozen_out:
                    self._frozen_out += "\n"
                self._last_sent_key = None
                self.output.setPlainText(self._frozen_out)
                self.run_translation()
            else:
                self.output.setPlainText(self._frozen_out)
            return

        key = (self._frozen_src, active, source, target, should_freeze)
        if key == self._last_sent_key:
            return
        self._last_sent_key = key

        # Frozen lines are joined to the active line with a newline.
        self._active_prefix = self._frozen_out + ("\n" if self._frozen_out else "")
        self._pending_freeze = (should_freeze, frozen_after, self._active_prefix)

        self._request_id += 1
        request_id = self._request_id
        self.bridge.started.emit(request_id)

        thread = threading.Thread(
            target=self._translate_worker,
            args=(request_id, active, source, target),
            daemon=True,
        )
        thread.start()

    def _translate_worker(
        self, request_id: int, text: str, source: str, target: str
    ) -> None:
        def superseded() -> bool:
            return request_id != self._request_id

        chunks: list[str] = []
        try:
            for chunk in translate_stream(
                text, source, target, should_cancel=superseded
            ):
                if superseded():
                    return
                chunks.append(chunk)
                self.bridge.delta.emit(request_id, chunk)
            if not superseded():
                self.bridge.finished.emit(request_id, "".join(chunks))
        except Exception as exc:  # surface API/network errors in the UI
            self.bridge.error.emit(request_id, str(exc))

    def _on_started(self, request_id: int) -> None:
        if request_id == self._request_id:
            self.status.setText("Translating\u2026")
            self.output.setPlainText(self._active_prefix)
            self.output.moveCursor(QTextCursor.End)

    def _on_delta(self, request_id: int, chunk: str) -> None:
        if request_id == self._request_id:
            self.output.insertPlainText(chunk)

    def _on_finished(self, request_id: int, translation: str) -> None:
        if request_id != self._request_id:
            return
        should_freeze, frozen_after, prefix = self._pending_freeze
        if should_freeze:
            self._frozen_src = frozen_after
            self._frozen_out = prefix + translation
            # Continue translating any lines after the one just frozen.
            if len(self.input.toPlainText()) > len(self._frozen_src):
                self.run_translation()
                return
        # Nothing left to translate: auto-copy the finished translation, then
        # try to hand it straight back to whichever app the user came from.
        self._copy_output_to_clipboard()
        self._auto_paste_into_previous_app()

    def _on_error(self, request_id: int, message: str) -> None:
        if request_id == self._request_id:
            self.status.setText("")
            self.output.setPlainText(f"[error] {message}")

    def _copy_output_to_clipboard(self) -> None:
        text = self.output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status.setText("Copied to clipboard \u2713")

    def _auto_paste_into_previous_app(self) -> None:
        # Only attempt this if the window was summoned via the hotkey (so we
        # know which app to paste back into) and Accessibility access has
        # been granted; otherwise the clipboard copy above is the fallback.
        if self._previous_app_pid is None:
            return
        if not (accessibility.available() and accessibility.is_trusted()):
            return
        pasted = focus.paste_into_pid(self._previous_app_pid)
        self._previous_app_pid = None
        if pasted:
            self.status.setText("Pasted \u2713")
            self.hide()


def main() -> None:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Type Fast")
    app.setApplicationDisplayName("Type Fast")
    window = MainWindow()
    window.resize(460, 380)
    window.show()
    app.exec()


if __name__ == "__main__":
    main()

"""PySide6 PoC window for type-fast.

A small window, summoned on demand Spotlight-style with a configurable global
hotkey (⇧⌘Space by default; Settings › Set Show/Hide Hotkey…). Pressing the
hotkey again, or Esc, dismisses it and hands focus back to the previous app.
Dismissing with the hotkey also pastes a finished translation there (Settings ›
Auto-Paste Translation); Esc just hides the window.
While shown it stays on top of other windows. Summoned by the hotkey it is
compact: only the boxes and a one-line "English → Japanese" direction, which
expands to the full pickers when clicked. It has an input box, a streamed
output box, and source/target language pickers (any pair from :data:`config.LANGUAGES`, with
optional auto-detection of the source) plus a swap button. Typing triggers a translation after a
short idle debounce, or immediately when a line ends (Enter) or the input ends
in sentence-ending punctuation. Translation runs on a worker thread and streams
results back to the UI via Qt signals so the interface never freezes.

To keep cost down, only the *active* (current) line of the input is ever sent.
Once you move to the next line, the finished line's translation is frozen and
reused verbatim, so completed lines are never re-translated as you keep typing.
Freezing on newline (rather than punctuation) is language-agnostic, so it works
the same for every supported language. Editing inside a frozen
prefix transparently re-translates from that point.

A tone selector next to the language pickers controls the register of the
translation (polite, casual, business, ... or a custom instruction), and the
model can be switched from Settings › Set Model…. Changing the languages, tone,
or model re-translates everything with the new settings. The language pair and
tone (and the hotkey) are remembered across launches.

Because the window floats above other apps, it is slightly see-through, fades
in when summoned, and fades further while you work in another app (hovering or
returning to it brings it back). The strength is chosen in Settings › Window
Transparency and remembered too.
"""

from __future__ import annotations

import string
import threading

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCursor,
    QDesktopServices,
    QGuiApplication,
    QKeySequence,
    QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import autopaste, config, hotkey, providers, settings
from .providers import openai as openai_provider
from .translator import translate_stream

# Characters that, when at the end of the input, trigger an immediate
# translation instead of waiting for the idle debounce.
# Covers Latin, CJK full-width, Arabic (\u061f), and Devanagari (\u0964) marks.
_SENTENCE_ENDINGS = (
    ".", "!", "?", "\u3002", "\uff01", "\uff1f", "\u061f", "\u0964",
)

_AUTO_LABEL = "Auto-detect"

# How long the window takes to fade between opacities, in milliseconds.
_FADE_MS = 160

# How often to check whether the pointer is over the window while another app
# is active, in milliseconds.
_HOVER_POLL_MS = 120

# How long to let the previous app take focus back before pasting into it, in
# milliseconds. Short enough to feel instant.
_PASTE_DELAY_MS = 100

# Styles for the main window. Neutral gray tints read well in both light and
# dark mode; ``palette(...)`` colors follow the system appearance and accent
# color, so the sheet is re-applied when the color scheme changes. Only named
# widgets are styled, so the language and tone pickers keep their native look.
# ``$muted``, ``$busy``, and ``$done`` are small-text colors picked per light
# or dark mode (see _TEXT_COLORS) to keep the text readable.
_STYLE_SHEET = """
QPlainTextEdit#inputBox, QTextEdit#outputBox {
    border: 1px solid rgba(128, 128, 128, 0.3);
    border-radius: 10px;
    padding: 6px 8px;
    font-size: 15px;
    background: palette(base);
    selection-background-color: palette(highlight);
}
QTextEdit#outputBox {
    background: rgba(128, 128, 128, 0.08);
}
QPlainTextEdit#inputBox:focus, QTextEdit#outputBox:focus {
    border: 1px solid palette(highlight);
}
QLabel#caption {
    color: $muted;
    font-size: 11px;
    font-weight: 600;
    padding-left: 2px;
}
QLabel#footnote, QLabel#status {
    color: $muted;
    font-size: 11px;
}
QLabel#status[state="busy"] {
    color: $busy;
}
QLabel#status[state="done"] {
    color: $done;
}
QToolButton#pairChip {
    color: palette(text);
    background: rgba(128, 128, 128, 0.14);
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 2px 10px;
    font-size: 12px;
}
QToolButton#pairChip:hover {
    background: rgba(128, 128, 128, 0.24);
}
QToolButton#pairChip:focus {
    border: 1px solid palette(highlight);
}
QToolButton#swapButton {
    border: 1px solid transparent;
    border-radius: 12px;
    min-width: 24px;
    min-height: 24px;
    font-size: 15px;
}
QToolButton#swapButton:hover {
    background: rgba(128, 128, 128, 0.18);
}
QToolButton#swapButton:focus {
    border: 1px solid palette(highlight);
}
QToolButton#swapButton:pressed {
    background: rgba(128, 128, 128, 0.3);
}
QToolButton#swapButton:disabled {
    color: rgba(128, 128, 128, 0.4);
}
"""

# Small-text colors for light and dark mode. Each keeps at least 4.5:1 contrast
# against the window background (about #ececec light, #323232 dark) while the
# window is in use with the Off, Light, or Medium transparency, whatever is
# behind it. Strong and the faded background state trade contrast for
# see-through on purpose.
_TEXT_COLORS = {
    "light": {"muted": "#56565a", "busy": "#0a56ba", "done": "#17662b"},
    "dark": {"muted": "#b3b3b7", "busy": "#71b9ff", "done": "#5fd47c"},
}


def _is_dark_mode() -> bool:
    """Whether the app is using a dark appearance."""
    app = QGuiApplication.instance()
    if app is None:
        return False
    hints = app.styleHints()
    scheme = hints.colorScheme() if hasattr(hints, "colorScheme") else None
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    return app.palette().window().color().lightness() < 128


def _language_label(name: str) -> str:
    """Return the picker label for ``name``, with its native name if different."""
    native = config.LANGUAGES[name]
    return name if native == name else f"{name} \u00b7 {native}"


class HotkeyDialog(QDialog):
    """Records a new show/hide hotkey.

    After ``exec()`` returns Accepted, :attr:`chosen` holds the canonical
    hotkey text, or "" to disable the hotkey.
    """

    def __init__(self, current: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set Show/Hide Hotkey")
        self.chosen = current
        # macOS virtual keycode of the last key pressed in the recorder. Carbon
        # registers physical keys, while Qt reports layout-dependent keys, so
        # this keeps non-U.S. layouts (Dvorak, AZERTY, ...) correct.
        self._native_key: int | None = None
        self._pending_native_key: int | None = None

        info = QLabel(
            "Press the key combination that shows and hides Type Fast from any "
            "app. Include \u2318, \u2303, or \u2325 (or use an F-key).\n"
            "Avoid \u2318Space (Spotlight) and \u2303Space (switch input "
            "source); macOS keeps those for itself."
        )
        info.setWordWrap(True)

        self.editor = QKeySequenceEdit()
        if hasattr(self.editor, "setMaximumSequenceLength"):
            self.editor.setMaximumSequenceLength(1)
        if hasattr(self.editor, "setClearButtonEnabled"):
            self.editor.setClearButtonEnabled(True)
        parsed = hotkey.parse(current) if current else None
        if parsed is not None:
            self.editor.setKeySequence(hotkey.to_qt(parsed))

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults
        )
        self.reset_button = buttons.button(QDialogButtonBox.RestoreDefaults)
        self.reset_button.setText("Reset to Default")
        self.disable_button = buttons.addButton("Disable", QDialogButtonBox.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.reset_button.clicked.connect(lambda: self._finish(config.DEFAULT_HOTKEY))
        self.disable_button.clicked.connect(lambda: self._finish(""))

        self.editor.installEventFilter(self)
        for child in self.editor.findChildren(QWidget):
            child.installEventFilter(self)
        # Only keys that change the recorded sequence count; e.g. Tab moves
        # focus out of the editor without being recorded.
        self.editor.keySequenceChanged.connect(self._on_sequence_changed)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addWidget(self.editor)
        layout.addWidget(buttons)
        self.editor.setFocus()

    _MODIFIER_KEYS = frozenset(
        {Qt.Key_Shift, Qt.Key_Control, Qt.Key_Meta, Qt.Key_Alt, Qt.Key_AltGr, Qt.Key_CapsLock}
    )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.KeyPress
            and event.key() not in self._MODIFIER_KEYS
            and hotkey.uses_native_keycodes()
        ):
            self._pending_native_key = event.nativeVirtualKey()
        return super().eventFilter(watched, event)

    def _on_sequence_changed(self, sequence: QKeySequence) -> None:
        self._native_key = None if sequence.isEmpty() else self._pending_native_key
        self._pending_native_key = None

    def _finish(self, text: str) -> None:
        self.chosen = text
        super().accept()

    def accept(self) -> None:
        sequence = self.editor.keySequence()
        if sequence.isEmpty():
            self._finish("")
            return
        parsed = hotkey.from_qt(sequence)
        if parsed is not None and self._native_key is not None:
            physical = hotkey.key_for_keycode(self._native_key)
            parsed = hotkey.Hotkey(parsed.modifiers, physical) if physical else None
        if parsed is None:
            QMessageBox.warning(
                self, "Set Show/Hide Hotkey", "That key can\u2019t be used as a hotkey."
            )
            return
        if not parsed.is_valid:
            QMessageBox.warning(
                self,
                "Set Show/Hide Hotkey",
                f"{parsed.symbols()} would get in the way of normal typing. "
                "Include \u2318 Command, \u2303 Control, or \u2325 Option "
                "(or use an F-key).",
            )
            return
        self._finish(str(parsed))


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

        self.prefs = settings.load()

        self.source_lang = QComboBox()
        self.source_lang.setToolTip("Language you type in")
        self.source_lang.addItem(_AUTO_LABEL, config.AUTO_SOURCE)
        self.target_lang = QComboBox()
        self.target_lang.setToolTip("Language to translate into")
        for name in config.LANGUAGES:
            self.source_lang.addItem(_language_label(name), name)
            self.target_lang.addItem(_language_label(name), name)
        self.swap_button = QToolButton()
        self.swap_button.setObjectName("swapButton")
        self.swap_button.setText("\u21c4")
        self.swap_button.setToolTip("Swap languages")
        self.swap_button.setCursor(Qt.PointingHandCursor)
        self._select_languages(self.prefs.source, self.prefs.target)

        self.tone = QComboBox()
        self.tone.setToolTip("Tone of the translation")
        for name in config.TONES:
            self.tone.addItem(name, name)
        self.tone.addItem(f"{config.CUSTOM_TONE}\u2026", config.CUSTOM_TONE)
        self.tone.setCurrentIndex(self.tone.findData(self.prefs.tone))
        self._update_tone_tooltip()

        self.input_label = QLabel()
        self.input_label.setObjectName("caption")
        self.input = QPlainTextEdit()
        self.input.setObjectName("inputBox")
        self.input.setPlaceholderText("Type here\u2026")

        self.output_label = QLabel()
        self.output_label.setObjectName("caption")
        self.output = QTextEdit()
        self.output.setObjectName("outputBox")
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Translation appears here\u2026")
        for box in (self.input, self.output):
            # The rounded border highlights focus; skip the square macOS ring.
            box.setAttribute(Qt.WA_MacShowFocusRect, False)

        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.model_label = QLabel()
        self.model_label.setObjectName("footnote")

        self.hotkey_label = QLabel()
        self.hotkey_label.setObjectName("footnote")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(6)
        # Language and tone pickers; hidden in compact mode (see set_compact).
        self.options_bar = QWidget()
        controls = QHBoxLayout(self.options_bar)
        controls.setContentsMargins(0, 0, 0, 4)
        controls.setSpacing(6)
        controls.addWidget(self.source_lang, 1)
        controls.addWidget(self.swap_button)
        controls.addWidget(self.target_lang, 1)
        controls.addWidget(self.tone)
        layout.addWidget(self.options_bar)

        # Compact mode shows only the direction, e.g. "English → Japanese";
        # clicking it brings the pickers back.
        self.pair_button = QToolButton()
        self.pair_button.setObjectName("pairChip")
        # Reachable with Tab, but clicking it doesn't pull focus from the input.
        self.pair_button.setFocusPolicy(Qt.TabFocus)
        self.pair_button.setCursor(Qt.PointingHandCursor)
        self.pair_button.setToolTip("Show language and tone options (\u2318L)")
        self.pair_button.clicked.connect(lambda: self.set_compact(False))
        self.pair_button.hide()
        layout.addWidget(self.pair_button, 0, Qt.AlignLeft)
        layout.addWidget(self.input_label)
        layout.addWidget(self.input, 1)
        layout.addSpacing(2)
        layout.addWidget(self.output_label)
        layout.addWidget(self.output, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(2, 2, 2, 0)
        footer.setSpacing(12)
        footer.addWidget(self.model_label)
        footer.addWidget(self.hotkey_label)
        footer.addWidget(self.status, 1)
        layout.addLayout(footer)
        self.setCentralWidget(central)
        self._apply_style()
        app = QGuiApplication.instance()
        hints = app.styleHints() if app is not None else None
        if hints is not None and hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._apply_style)

        # The window floats above other apps, so it is slightly see-through and
        # fades further while you work elsewhere (see _update_opacity).
        self._hovered = False
        self._opacity_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._opacity_anim.setDuration(_FADE_MS)
        self._opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
        # macOS sends no Enter/Leave events while another app is active, so
        # hover is detected by polling the pointer while in the background.
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(_HOVER_POLL_MS)
        self._hover_timer.timeout.connect(self._poll_hover)
        if app is not None:
            app.focusWindowChanged.connect(self._on_focus_window_changed)
        self.setWindowOpacity(self._target_opacity())

        self._build_menu()
        self._update_labels()
        self._reflect_key_status()
        self._reflect_model()

        # Esc dismisses the window, even while typing in the input box
        # (QPlainTextEdit does not claim Esc, so the window shortcut wins).
        self.dismiss_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.dismiss_shortcut.setContext(Qt.WindowShortcut)
        self.dismiss_shortcut.activated.connect(self.dismiss)

        # Global show/hide hotkey (Spotlight-style). ``_dismissed`` records
        # that the window was hidden on purpose (hotkey or Esc), so that
        # reactivating the app (Dock icon, ⌘Tab) brings it back.
        self._dismissed = False
        self.compact = False
        # The finished translation that hiding with the hotkey should paste,
        # or "" (see dismiss); each one is pasted at most once.
        self._paste_text = ""
        # A missing permission is explained at most once per launch.
        self._asked_paste_permission = False
        # Bumped each time the window appears, so a paste still waiting from
        # an earlier hide is dropped (see dismiss).
        self._shown_count = 0
        self.global_hotkey = hotkey.GlobalHotkey(self)
        self.global_hotkey.activated.connect(self.toggle_visibility)
        self._register_hotkey()
        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_app_state_changed)

        # Monotonic id identifying the most recent translation request so that
        # superseded, slower in-flight translations are discarded.
        self._request_id = 0
        # Whether that request is still running.
        self._translating = False

        # The last (frozen_src, active, source, target, tone, model,
        # should_freeze) actually sent, used to skip redundant requests when
        # nothing relevant changed. ``should_freeze`` is part of the key so that
        # adding a newline (which must advance the freeze boundary) is never
        # skipped as a duplicate.
        self._last_sent_key: tuple[str, str, str, str, str, str, bool] | None = None

        # Source prefix whose translation is finalized, and its translation.
        # Only the input text *after* ``_frozen_src`` is ever sent to the API.
        self._frozen_src = ""
        self._frozen_out = ""
        # (source, target, tone, model) the frozen translation was produced
        # with; a language, tone, or model change invalidates it.
        self._frozen_context: tuple[str, str, str, str] | None = None

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
        self.source_lang.activated.connect(self._on_source_activated)
        self.target_lang.activated.connect(self._on_target_activated)
        self.swap_button.clicked.connect(self._swap_languages)
        self.tone.activated.connect(self._on_tone_activated)

    def _build_menu(self) -> None:
        # On macOS this becomes part of the global menu bar at the top of the
        # screen. "Set OpenAI API Key…" lands in the app menu automatically
        # because of its role-like text, so we add it to a Settings menu too.
        menu = self.menuBar().addMenu("Settings")
        self.set_key_action = QAction("Set OpenAI API Key\u2026", self)
        self.set_key_action.setShortcut(QKeySequence("Ctrl+,"))
        self.set_key_action.triggered.connect(self._set_api_key)
        menu.addAction(self.set_key_action)

        self.set_model_action = QAction("Set Model\u2026", self)
        self.set_model_action.triggered.connect(self._set_model)
        menu.addAction(self.set_model_action)

        self.set_custom_tone_action = QAction("Set Custom Tone\u2026", self)
        self.set_custom_tone_action.triggered.connect(self._set_custom_tone)
        menu.addAction(self.set_custom_tone_action)

        # Keyboard route out of the compact layout (see set_compact).
        self.show_options_action = QAction("Show Language && Tone Options", self)
        self.show_options_action.setShortcut(QKeySequence("Ctrl+L"))  # ⌘L on macOS
        self.show_options_action.triggered.connect(lambda: self.set_compact(False))
        menu.addAction(self.show_options_action)

        self.set_hotkey_action = QAction("Set Show/Hide Hotkey\u2026", self)
        self.set_hotkey_action.triggered.connect(self._set_hotkey)
        menu.addAction(self.set_hotkey_action)

        self.auto_paste_action = QAction("Auto-Paste Translation", self, checkable=True)
        self.auto_paste_action.setChecked(self.prefs.auto_paste)
        self.auto_paste_action.setToolTip(
            "Hiding Type Fast with the show/hide hotkey pastes the translation "
            "into your app (needs Accessibility permission)"
        )
        self.auto_paste_action.triggered.connect(self._set_auto_paste)
        menu.addAction(self.auto_paste_action)

        transparency_menu = menu.addMenu("Window Transparency")
        self.transparency_group = QActionGroup(self)
        self.transparency_group.setExclusive(True)
        for name in config.TRANSPARENCY:
            action = QAction(name, self, checkable=True)
            action.setData(name)
            action.setChecked(name == self.prefs.transparency)
            self.transparency_group.addAction(action)
            transparency_menu.addAction(action)
        self.transparency_group.triggered.connect(
            lambda action: self._apply_transparency(action.data())
        )

    # --- Appearance -------------------------------------------------------

    def _apply_style(self, *_args: object) -> None:
        """(Re-)apply the style sheet so ``palette(...)`` colors stay current."""
        colors = _TEXT_COLORS["dark" if _is_dark_mode() else "light"]
        self.centralWidget().setStyleSheet(string.Template(_STYLE_SHEET).substitute(colors))

    def _set_status(self, text: str, state: str = "") -> None:
        """Show ``text`` in the status line; ``state`` is "", "busy", or "done"."""
        self.status.setText(text)
        if self.status.property("state") != state:
            self.status.setProperty("state", state)
            # Dynamic properties only restyle after a re-polish.
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)

    def _opacities(self) -> tuple[float, float]:
        return config.TRANSPARENCY.get(
            self.prefs.transparency, config.TRANSPARENCY[config.DEFAULT_TRANSPARENCY]
        )

    def _is_engaged(self) -> bool:
        """Whether you are using the window: it or one of its dialogs is focused, or it is hovered."""
        return (
            self._hovered
            or self.isActiveWindow()
            or QApplication.activeWindow() is not None
        )

    def _target_opacity(self, engaged: bool | None = None) -> float:
        focused, background = self._opacities()
        if engaged is None:
            engaged = self._is_engaged()
        return focused if engaged else background

    def _update_opacity(self, start: float | None = None, engaged: bool | None = None) -> None:
        """Fade to the opacity for the current state, optionally from ``start``.

        ``engaged`` overrides the detected state, e.g. while summoning, before
        macOS has finished activating the window.
        """
        target = self._target_opacity(engaged)
        animation = self._opacity_anim
        if animation.state() == QPropertyAnimation.Running and animation.endValue() == target:
            return
        animation.stop()
        current = self.windowOpacity() if start is None else start
        if not self.isVisible() or abs(current - target) < 0.005:
            self.setWindowOpacity(target)
            return
        animation.setStartValue(current)
        animation.setEndValue(target)
        animation.start()

    def _on_focus_window_changed(self, _window: object) -> None:
        self._sync_hover_tracking()
        self._update_opacity()

    def _sync_hover_tracking(self) -> None:
        """Poll for hover only while the window is shown and the app is inactive."""
        if self.isVisible() and QApplication.activeWindow() is None:
            if not self._hover_timer.isActive():
                self._poll_hover()
                self._hover_timer.start()
        else:
            self._hover_timer.stop()

    def _poll_hover(self) -> None:
        hovered = self.isVisible() and self.frameGeometry().contains(QCursor.pos())
        if hovered != self._hovered:
            self._hovered = hovered
            self._update_opacity()

    def _apply_transparency(self, name: str) -> None:
        if name not in config.TRANSPARENCY:
            return
        self.prefs.transparency = name
        for action in self.transparency_group.actions():
            action.setChecked(action.data() == name)
        self._update_opacity()
        self._save_prefs("Window Transparency", "window transparency")

    def enterEvent(self, event: QEvent) -> None:
        self._hovered = True
        self._update_opacity()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hovered = False
        self._update_opacity()
        super().leaveEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.ActivationChange:
            self._sync_hover_tracking()
            self._update_opacity()
        super().changeEvent(event)

    def hideEvent(self, event: QEvent) -> None:
        self._hover_timer.stop()
        self._hovered = False
        super().hideEvent(event)

    # --- Show/hide --------------------------------------------------------

    def toggle_visibility(self) -> None:
        """Hide the window if it is shown and focused, otherwise summon it.

        A window summoned this way (by the global hotkey) is compact.
        """
        modal = QApplication.activeModalWidget()
        if modal is not None:
            # Don't hide the window out from under an open dialog.
            hotkey.activate_app()
            modal.raise_()
            modal.activateWindow()
            return
        if self.isVisible() and self.isActiveWindow() and not self.isMinimized():
            self.dismiss(paste=True)
        else:
            self.summon(compact=True)

    def summon(self, compact: bool = False) -> None:
        """Show, raise, and focus the window, Spotlight-style.

        With ``compact``, only the input and output boxes and the language
        direction are shown (see :meth:`set_compact`).
        """
        self._dismissed = False
        self.set_compact(compact)
        appearing = not self.isVisible()
        if appearing:
            # Whatever finished while hidden (or was dismissed with Esc) has
            # been seen or skipped; don't paste it on the next hide.
            self._paste_text = ""
            self._shown_count += 1
            self._center_on_cursor_screen()
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        if appearing:
            self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()
        hotkey.activate_app()
        self.input.setFocus()
        self.input.moveCursor(QTextCursor.End)
        # Fade in, Spotlight-style. Activation may land a moment later; the
        # focus change then retargets the fade.
        self._update_opacity(start=0.0 if appearing else None, engaged=True)

    def set_compact(self, compact: bool) -> None:
        """Switch between the minimal and the full layout.

        The minimal layout hides the language and tone pickers, the box labels,
        and the model/hotkey hints, showing just the direction instead.
        """
        self.compact = compact
        self.options_bar.setVisible(not compact)
        self.pair_button.setVisible(compact)
        for widget in (self.input_label, self.output_label, self.model_label, self.hotkey_label):
            widget.setVisible(not compact)

    def dismiss(self, paste: bool = False) -> None:
        """Hide the window and return focus to the previously active app.

        With ``paste`` (the show/hide hotkey) and Auto-Paste on, a finished
        translation that hasn't been pasted yet is pasted into that app.
        """
        text = self._take_paste_text() if paste and self.prefs.auto_paste else ""
        if text and not self._asked_paste_permission and self._needs_paste_permission():
            # Explain while the window is still up; this time the translation
            # stays on the clipboard to paste by hand.
            self._ask_paste_permission()
        self._dismissed = True
        self.hide()
        hotkey.hide_app()
        if text:
            shown = self._shown_count
            QTimer.singleShot(
                _PASTE_DELAY_MS, lambda: self._paste_into_previous_app(text, shown)
            )

    def _take_paste_text(self) -> str:
        """Return the translation to paste, or "", and mark it as pasted.

        Flushes a pending debounce first: if the user typed since the last
        translation, :meth:`run_translation` runs now, and when that starts a
        new request or shortens the output, the copied text is stale, so this
        returns "".
        """
        if self.timer.isActive():
            self.timer.stop()
            self.run_translation()
        text, self._paste_text = self._paste_text, ""
        return text if self._is_pasteable(text) else ""

    def _is_pasteable(self, text: str) -> bool:
        # ⌘V pastes the clipboard, so paste only while it still holds the
        # translation shown in the window, never something copied since. The
        # window may also show blank lines typed after it.
        return (
            bool(text)
            and self.output.toPlainText().rstrip() == text.rstrip()
            and QApplication.clipboard().text() == text
        )

    def _paste_into_previous_app(self, text: str, shown: int) -> None:
        if (
            shown != self._shown_count
            or self.isVisible()
            or not self._is_pasteable(text)
        ):
            return  # summoned again, or the clipboard changed, before the paste
        autopaste.send_paste()

    @staticmethod
    def _needs_paste_permission() -> bool:
        return autopaste.is_supported() and not autopaste.has_permission()

    def _ask_paste_permission(self) -> None:
        """Explain the Accessibility permission and offer to open its settings."""
        self._asked_paste_permission = True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Allow Auto-Paste")
        box.setText("Allow Type Fast to paste translations for you?")
        box.setInformativeText(
            "Turn on Type Fast in System Settings › Privacy & Security › "
            "Accessibility. If it isn't listed, add it with +.\n\n"
            "Until then, paste the translation with ⌘V."
        )
        open_button = box.addButton("Open System Settings", QMessageBox.AcceptRole)
        box.addButton("Not Now", QMessageBox.RejectRole)
        box.setDefaultButton(open_button)
        box.exec()
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl(autopaste.SETTINGS_URL))

    def _set_auto_paste(self, enabled: bool) -> None:
        self.prefs.auto_paste = enabled
        self._save_prefs("Auto-Paste Translation", "auto-paste setting")
        if enabled and not self._asked_paste_permission and self._needs_paste_permission():
            self._ask_paste_permission()

    def _center_on_cursor_screen(self) -> None:
        """Center horizontally on the cursor's screen, in its upper part."""
        screen = (
            QGuiApplication.screenAt(QCursor.pos())
            or self.screen()
            or QGuiApplication.primaryScreen()
        )
        if screen is None:
            return
        area = screen.availableGeometry()
        frame = self.frameGeometry()
        x = area.x() + (area.width() - frame.width()) // 2
        y = area.y() + max(0, (area.height() - frame.height()) // 4)
        self.move(x, y)

    def _on_app_state_changed(self, state: Qt.ApplicationState) -> None:
        # Reactivating the app (Dock icon, ⌘Tab) while dismissed shows the window.
        if state == Qt.ApplicationActive and self._dismissed and not self.isVisible():
            self.summon()

    # --- Hotkey settings --------------------------------------------------

    def _register_hotkey(self) -> bool:
        """(Re-)register the saved hotkey and reflect the outcome.

        Returns False if a saved hotkey could not be registered.
        """
        parsed = hotkey.parse(self.prefs.hotkey) if self.prefs.hotkey else None
        if parsed is None:
            self.global_hotkey.unregister()
            ok = True
        else:
            ok = self.global_hotkey.register(parsed)
        self._reflect_hotkey()
        return ok

    def _reflect_hotkey(self) -> None:
        parsed = hotkey.parse(self.prefs.hotkey) if self.prefs.hotkey else None
        where = "Settings \u203a Set Show/Hide Hotkey\u2026"
        if parsed is None:
            text, tip = "Hotkey off", f"No show/hide hotkey \u2014 set one in {where}"
        elif self.global_hotkey.is_registered:
            text = f"{parsed.symbols()} to show/hide"
            tip = f"Press {parsed.symbols()} in any app to show or hide Type Fast \u2014 change it in {where}"
        elif not hotkey.GlobalHotkey.is_supported():
            text = f"{parsed.symbols()} (inactive)"
            tip = "Global hotkeys are only available in the macOS app"
        else:
            text = f"{parsed.symbols()} unavailable"
            tip = (
                f"{parsed.symbols()} could not be registered (it may be used by "
                f"macOS or another app) \u2014 choose another in {where}"
            )
        self.hotkey_label.setText(text)
        self.hotkey_label.setToolTip(tip)
        self.set_hotkey_action.setToolTip(tip)

    def _set_hotkey(self) -> None:
        # Release the current hotkey while recording, or pressing it would
        # toggle the window instead of being captured by the dialog.
        self.global_hotkey.unregister()
        dialog = HotkeyDialog(self.prefs.hotkey, self)
        if dialog.exec() == QDialog.Accepted:
            self._apply_hotkey(dialog.chosen)
        else:
            self._register_hotkey()  # cancelled: restore the previous hotkey

    def _apply_hotkey(self, text: str) -> bool:
        """Switch to hotkey ``text`` ("" disables it) and save it.

        Returns False, keeping the previous hotkey registered, if ``text`` is
        invalid or macOS refuses to register it.
        """
        title = "Set Show/Hide Hotkey"
        text = text.strip()
        parsed = hotkey.parse(text) if text else None
        if text and parsed is None:
            QMessageBox.warning(self, title, f"\u201c{text}\u201d is not a valid hotkey.")
            self._register_hotkey()
            return False
        if parsed is None:
            self.global_hotkey.unregister()
        elif not self.global_hotkey.register(parsed) and hotkey.GlobalHotkey.is_supported():
            # The previous hotkey was released while recording; restore it first
            # so the message reports what is actually active.
            restored = self._register_hotkey()
            previous = hotkey.parse(self.prefs.hotkey) if self.prefs.hotkey else None
            if previous is None:
                keeping = "The hotkey stays off."
            elif restored:
                keeping = f"Keeping {previous.symbols()}."
            else:
                keeping = (
                    f"{previous.symbols()} could not be restored either, so the hotkey "
                    "is off until you choose another."
                )
            QMessageBox.warning(
                self,
                title,
                f"{parsed.symbols()} could not be registered; it may already be used "
                f"by macOS or another app. {keeping}",
            )
            return False
        # Registration is skipped on unsupported platforms; still save the choice.
        self.prefs.hotkey = str(parsed) if parsed else ""
        self._reflect_hotkey()
        self._save_prefs(title, "hotkey")
        return True

    def _reflect_model(self) -> None:
        provider = providers.active_provider()
        self.model_label.setText(f"Model: {providers.get_model()}")
        self.model_label.setToolTip(
            f"Provider: {provider.DISPLAY_NAME} \u2014 change it in Settings \u203a Set Model\u2026"
        )

    def _set_model(self) -> None:
        provider = providers.active_provider()
        env = providers.model_env_override()
        if env:
            QMessageBox.information(
                self,
                "Set Model",
                f"The model is pinned by the {env} environment variable "
                f"({providers.get_model()}). Unset it to choose a model here.",
            )
            return
        current = providers.get_model()
        choices = list(config.MODEL_CHOICES)
        if current not in choices:
            choices.insert(0, current)
        model, ok = QInputDialog.getItem(
            self,
            "Set Model",
            f"{provider.DISPLAY_NAME} model or deployment name\n"
            f"(stored in {provider.MODEL_FILE}; leave blank for "
            f"the default, {config.DEFAULT_MODEL}):",
            choices,
            choices.index(current),
            True,
        )
        if not ok:
            return
        try:
            providers.save_model(model)
        except OSError as exc:
            QMessageBox.warning(
                self, "Set Model", f"Could not save the model to {provider.MODEL_FILE}:\n{exc}"
            )
            return
        self._reflect_model()
        self._retranslate()

    def _update_tone_tooltip(self) -> None:
        self.tone.setToolTip(
            f"Tone of the translation: {self.prefs.instruction()}"
        )

    def _on_tone_activated(self, index: int) -> None:
        tone = self.tone.itemData(index)
        if tone == config.CUSTOM_TONE and not self.prefs.custom_tone.strip():
            # Custom needs an instruction; ask for one (reverts on cancel).
            self._set_custom_tone()
            return
        self._apply_tone(tone)

    def _set_custom_tone(self) -> None:
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Set Custom Tone",
            "Describe the tone for translations, e.g. \"Playful, with a light "
            "touch of humor\" or \"Humble keigo (\u8b19\u8b72\u8a9e) for a client\":",
            self.prefs.custom_tone,
        )
        text = text.strip()
        if not ok or not text:
            # Keep the combo box in sync with the tone actually in use.
            self.tone.setCurrentIndex(self.tone.findData(self.prefs.tone))
            return
        self.prefs.custom_tone = text
        self._apply_tone(config.CUSTOM_TONE)

    def _apply_tone(self, tone: str) -> None:
        self.prefs.tone = tone
        self.tone.setCurrentIndex(self.tone.findData(tone))
        self._update_tone_tooltip()
        self._save_prefs("Tone", "tone")
        self._retranslate()

    def _save_prefs(self, title: str, what: str) -> None:
        try:
            settings.save(self.prefs)
        except OSError as exc:
            # A dialog, not the status line, which the retranslation overwrites.
            QMessageBox.warning(
                self,
                title,
                f"The {what} applies now but could not be saved to "
                f"{settings.SETTINGS_FILE}, so it will be lost on restart:\n{exc}",
            )

    def _select_languages(self, source: str, target: str) -> None:
        """Show ``source``/``target`` in the pickers and record them in prefs."""
        self.prefs.source = source
        self.prefs.target = target
        self.source_lang.setCurrentIndex(self.source_lang.findData(source))
        self.target_lang.setCurrentIndex(self.target_lang.findData(target))
        # Auto-detect can't become a target, so there is nothing to swap.
        self.swap_button.setEnabled(source != config.AUTO_SOURCE)

    def _on_source_activated(self, index: int) -> None:
        source = self.source_lang.itemData(index)
        target = self.prefs.target
        if source == target:
            # Picking the target language as the source swaps the pair.
            previous = self.prefs.source
            if previous == config.AUTO_SOURCE:
                target = self._other_language(source)
            else:
                target = previous
        self._apply_languages(source, target)

    def _on_target_activated(self, index: int) -> None:
        target = self.target_lang.itemData(index)
        source = self.prefs.source
        if source == target:
            # Picking the source language as the target swaps the pair.
            source = self.prefs.target
        self._apply_languages(source, target)

    def _swap_languages(self) -> None:
        if self.prefs.source != config.AUTO_SOURCE:
            self._apply_languages(self.prefs.target, self.prefs.source)

    @staticmethod
    def _other_language(language: str) -> str:
        """Return a sensible language different from ``language``."""
        for candidate in (config.DEFAULT_UI_SOURCE, config.DEFAULT_UI_TARGET):
            if candidate != language:
                return candidate
        return next(name for name in config.LANGUAGES if name != language)

    def _apply_languages(self, source: str, target: str) -> None:
        if (source, target) == (self.prefs.source, self.prefs.target):
            return
        self._select_languages(source, target)
        self._update_labels()
        self._save_prefs("Languages", "language pair")
        self._retranslate()

    def _retranslate(self) -> None:
        """Re-run the translation now (e.g. after a tone or model change)."""
        self.timer.stop()
        self.run_translation()

    def _reflect_key_status(self) -> None:
        if providers.has_credentials():
            self._set_status("")
        else:
            self._set_status("No API key set \u2014 Settings \u203a Set OpenAI API Key\u2026")

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
        self._reflect_model()

    def _update_labels(self) -> None:
        source, target = self.prefs.source, self.prefs.target
        self.input_label.setText(
            _AUTO_LABEL if source == config.AUTO_SOURCE else _language_label(source)
        )
        self.output_label.setText(_language_label(target))
        self.pair_button.setText(
            f"{_AUTO_LABEL if source == config.AUTO_SOURCE else source} \u2192 {target}"
        )

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
        source, target = self.prefs.source, self.prefs.target
        tone = self.prefs.instruction()
        model = providers.get_model()

        # A language, tone, or model change makes the frozen translation stale.
        context = (source, target, tone, model)
        if context != self._frozen_context:
            self._frozen_src = ""
            self._frozen_out = ""
            self._frozen_context = context

        # If the frozen prefix was edited, drop it and re-translate from there.
        if not full.startswith(self._frozen_src):
            self._frozen_src = ""
            self._frozen_out = ""

        if not full.strip():
            self._cancel_translation()
            self._frozen_src = ""
            self._frozen_out = ""
            self._last_sent_key = None
            self._paste_text = ""
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
            # The line being translated, if any, was deleted.
            self._cancel_translation()
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

        key = (self._frozen_src, active, source, target, tone, model, should_freeze)
        if key == self._last_sent_key:
            return
        self._last_sent_key = key

        # Frozen lines are joined to the active line with a newline.
        self._active_prefix = self._frozen_out + ("\n" if self._frozen_out else "")
        self._pending_freeze = (should_freeze, frozen_after, self._active_prefix)

        self._request_id += 1
        request_id = self._request_id
        self._translating = True
        self.bridge.started.emit(request_id)

        thread = threading.Thread(
            target=self._translate_worker,
            args=(request_id, active, source, target, tone, model),
            daemon=True,
        )
        thread.start()

    def _cancel_translation(self) -> None:
        """Drop the request still running, if any, so its result never lands."""
        if self._translating:
            self._translating = False
            self._request_id += 1
            self._last_sent_key = None
            self._set_status("")

    def _translate_worker(
        self,
        request_id: int,
        text: str,
        source: str,
        target: str,
        tone: str,
        model: str,
    ) -> None:
        def superseded() -> bool:
            return request_id != self._request_id

        chunks: list[str] = []
        try:
            for chunk in translate_stream(
                text,
                source,
                target,
                tone=tone,
                model=model,
                should_cancel=superseded,
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
            self._paste_text = ""
            self._set_status("Translating\u2026", "busy")
            self.output.setPlainText(self._active_prefix)
            self.output.moveCursor(QTextCursor.End)

    def _on_delta(self, request_id: int, chunk: str) -> None:
        if request_id == self._request_id:
            self.output.insertPlainText(chunk)

    def _on_finished(self, request_id: int, translation: str) -> None:
        if request_id != self._request_id:
            return
        self._translating = False
        should_freeze, frozen_after, prefix = self._pending_freeze
        if should_freeze:
            self._frozen_src = frozen_after
            self._frozen_out = prefix + translation
            # Continue translating any lines after the one just frozen.
            if len(self.input.toPlainText()) > len(self._frozen_src):
                self.run_translation()
                return
        # Nothing left to translate: auto-copy the finished translation.
        self._copy_output_to_clipboard()

    def _on_error(self, request_id: int, message: str) -> None:
        if request_id == self._request_id:
            self._translating = False
            self._paste_text = ""
            self._set_status("")
            self.output.setPlainText(f"[error] {message}")

    def _copy_output_to_clipboard(self) -> None:
        text = self.output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self._paste_text = text
            self._set_status("Copied to clipboard \u2713", "done")


def main() -> None:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Type Fast")
    app.setApplicationDisplayName("Type Fast")
    window = MainWindow()
    window.resize(460, 380)
    # Show on launch so first-time users see the window (and its hotkey hint).
    window.summon()
    app.exec()


if __name__ == "__main__":
    main()

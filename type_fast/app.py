"""PySide6 PoC window for type-fast.

A small window, summoned on demand Spotlight-style with a configurable global
hotkey (⇧⌘Space by default; Settings › Set Show/Hide Hotkey…). Pressing the
hotkey again, or Esc, dismisses it and hands focus back to the previous app.
Dismissing with the hotkey also pastes the translation there, waiting up to 5
seconds for it to finish if needed (Settings › Auto-Paste Translation); Esc
just hides the window.
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
translation (polite, casual, business, ... or a custom instruction). The
provider (OpenAI or Azure AI Foundry) is picked in Settings › Provider and
shown with the model at the bottom of the window. Each provider has its own
submenu under Settings: OpenAI's holds the API key and the model (picked from
OpenAI's models), and Azure AI Foundry's holds the endpoint, key, and the name
of the deployment to use (Foundry can only use models you deployed).
Changing the languages, tone, provider, or model re-translates everything
with the new settings. The language pair and
tone (and the hotkey) are remembered across launches.

Because the window floats above other apps, it is slightly see-through, fades
in when summoned, and fades further while you work in another app (hovering or
returning to it brings it back). The strength is chosen in Settings › Window
Transparency and remembered too.
"""

from __future__ import annotations

import os
import string
import threading
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

from openai import OpenAI
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
    QIcon,
    QKeySequence,
    QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
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
from .providers import azure as azure_provider, openai as openai_provider
from .translator import translate_stream

# Characters that, when at the end of the input, trigger an immediate
# translation instead of waiting for the idle debounce.
# Covers Latin, CJK full-width, Arabic (\u061f), and Devanagari (\u0964) marks.
_SENTENCE_ENDINGS = (
    ".", "!", "?", "\u3002", "\uff01", "\uff1f", "\u061f", "\u0964",
)

_AUTO_LABEL = "Auto-detect"

# Menu items for OpenAI's own settings, in Settings › OpenAI (Azure AI Foundry's
# are defined in providers/azure.py).
_OPENAI_KEY_ITEM = "Set API Key\u2026"
_OPENAI_MODEL_ITEM = "Set Model\u2026"
# Where to find them, as shown in hints (e.g. "Settings › OpenAI › Set API Key…").
_OPENAI_KEY_PATH = f"Settings \u203a {openai_provider.DISPLAY_NAME} \u203a {_OPENAI_KEY_ITEM}"
_OPENAI_MODEL_PATH = f"Settings \u203a {openai_provider.DISPLAY_NAME} \u203a {_OPENAI_MODEL_ITEM}"

# How long the window takes to fade between opacities, in milliseconds.
_FADE_MS = 160

# How often to check whether the pointer is over the window while another app
# is active, in milliseconds.
_HOVER_POLL_MS = 120

# How long to let the previous app take focus back before pasting into it, or
# before noting which app that is (see MainWindow._remember_paste_target), in
# milliseconds. Short enough to feel instant.
_PASTE_DELAY_MS = 100

# How many times, _PASTE_DELAY_MS apart, to look for the app that got focus
# back while Type Fast is still listed as the frontmost app (or none is), both
# to note it and to paste into it.
_PASTE_TARGET_TRIES = 5

# How long a paste waits for a translation still running when the hotkey hid
# the window, in milliseconds. Later, the translation is only copied.
_DEFERRED_PASTE_TIMEOUT_MS = 5000


class _DeferredPaste(NamedTuple):
    """A hotkey hide whose paste waits for the translation still running."""

    shown: int  # MainWindow._shown_count at the hide
    change_count: int | None  # pasteboard change count at the hide


class _PasteTarget(NamedTuple):
    """Where a deferred paste may land: the app that got focus back."""

    shown: int  # MainWindow._shown_count at the hide
    pid: int | None  # that app's process id; None until noted
    input_count: int | None  # your clicks and key presses at the hide


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
_ERROR_COLORS = {"light": "#b8000f", "dark": "#ff7b72"}


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


_FOUNDRY_GUIDE_URL = "https://github.com/wangx173/type-fast/blob/main/docs/foundry-setup.md"


class AzureSetupDialog(QDialog):
    """Asks for the Azure AI Foundry endpoint, API key, and deployment name.

    After ``exec()`` returns Accepted, :attr:`endpoint`, :attr:`api_key`, and
    :attr:`model` hold the trimmed values (``model`` may be blank).
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        env_overrides: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set Up Azure AI Foundry")
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model

        info = QLabel(
            "Enter your Foundry resource's endpoint and API key (Keys and "
            "Endpoint in the Azure portal) and the name of your model "
            f'deployment. New to Foundry? See the <a href="{_FOUNDRY_GUIDE_URL}">'
            "setup guide</a>."
        )
        info.setWordWrap(True)
        info.setOpenExternalLinks(True)
        # Let Tab reach the link and Return open it, not just a mouse click.
        info.setTextInteractionFlags(Qt.TextBrowserInteraction)

        self.endpoint_edit = QLineEdit(endpoint)
        self.endpoint_edit.setPlaceholderText("https://<resource>.services.ai.azure.com")
        self.key_edit = QLineEdit(api_key)
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("Key 1 or Key 2")
        self.model_edit = QLineEdit(model)
        self.model_edit.setPlaceholderText(config.DEFAULT_OPENAI_MODEL)

        form = QFormLayout()
        # macOS keeps fields at their hint width; widen them to show endpoints.
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.addRow("Endpoint:", self.endpoint_edit)
        form.addRow("API key:", self.key_edit)
        form.addRow("Deployment:", self.model_edit)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(
            f"color: {_ERROR_COLORS['dark' if _is_dark_mode() else 'light']};"
        )
        self.error_label.hide()

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addLayout(form)
        if env_overrides:
            note = QLabel(
                f"{', '.join(env_overrides)} "
                f"{'is' if len(env_overrides) == 1 else 'are'} set in the environment "
                "and take precedence over what you save here."
            )
            note.setWordWrap(True)
            layout.addWidget(note)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setMinimumWidth(460)

    def _problem(self, endpoint: str, api_key: str, model: str) -> tuple[str, QLineEdit | None]:
        """Return what is wrong with the entered values and the field to fix."""
        url = QUrl(endpoint)
        if (
            url.scheme().lower() != "https"
            or not url.host()
            or url.hasQuery()
            or url.hasFragment()
            or any(c.isspace() for c in endpoint)
            or not azure_provider.has_supported_path(endpoint)
        ):
            return (
                "Enter the endpoint as an https:// URL, e.g. "
                "https://<resource>.services.ai.azure.com. It can end in /openai/v1 "
                "or /api/projects/<project>, but not other paths, ?\u2026, or #\u2026.",
                self.endpoint_edit,
            )
        if not api_key or any(c.isspace() for c in api_key):
            return "Enter the API key (it can't contain spaces).", self.key_edit
        problem = azure_provider.deployment_problem(model)
        if problem:
            return problem, self.model_edit
        return "", None

    def accept(self) -> None:
        endpoint = self.endpoint_edit.text().strip()
        api_key = self.key_edit.text().strip()
        model = self.model_edit.text().strip()
        problem, field = self._problem(endpoint, api_key, model)
        for edit in (self.endpoint_edit, self.key_edit, self.model_edit):
            edit.setAccessibleDescription(problem if edit is field else "")
        if field is not None:
            self.error_label.setText(problem)
            self.error_label.show()
            # Moving focus makes VoiceOver read the field and its error.
            field.setFocus()
            return
        self.endpoint, self.api_key, self.model = endpoint, api_key, model
        super().accept()


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
        self._reflect_provider()

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
        # The pasteboard change count right after that copy (None off macOS).
        self._copy_change_count: int | None = None
        # A missing permission is explained at most once per launch.
        self._asked_paste_permission = False
        # Bumped each time the window appears, so a paste still waiting from
        # an earlier hide is dropped (see dismiss).
        self._shown_count = 0
        # A hotkey hide whose paste waits for the translation still running,
        # or None; the paste happens once it finishes (see _on_finished),
        # unless something is copied in the meantime. Timing out, summoning,
        # an error, or re-translating drops it (see _cancel_deferred_paste).
        self._deferred_paste: _DeferredPaste | None = None
        self._deferred_paste_timer = QTimer(self)
        self._deferred_paste_timer.setSingleShot(True)
        self._deferred_paste_timer.setInterval(_DEFERRED_PASTE_TIMEOUT_MS)
        self._deferred_paste_timer.timeout.connect(self._cancel_deferred_paste)
        # Where such a hide's paste may land: the app that got focus back,
        # once noted, as long as you haven't clicked or typed since the hide.
        # Until an app is noted, the first one other than Type Fast counts.
        self._paste_target: _PasteTarget | None = None
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

        # The last (frozen_src, active, source, target, tone, *provider state,
        # should_freeze) actually sent, used to skip redundant requests when
        # nothing relevant changed. The provider state (see _provider_state)
        # is the provider, its endpoint and key, and the model, so its length
        # depends on the provider. ``should_freeze`` is part of the key so that
        # adding a newline (which must advance the freeze boundary) is never
        # skipped as a duplicate.
        self._last_sent_key: tuple[str | bool, ...] | None = None

        # Source prefix whose translation is finalized, and its translation.
        # Only the input text *after* ``_frozen_src`` is ever sent to the API.
        self._frozen_src = ""
        self._frozen_out = ""
        # (source, target, tone, *provider state) the frozen translation was
        # produced with; changing any of them invalidates it.
        self._frozen_context: tuple[str, ...] | None = None

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
        # screen. Each provider's own settings (credentials, model or
        # deployment) live in a submenu named after it; the rest are shared.
        menu = self.menuBar().addMenu("Settings")

        # Which service translates; the checked item is the one in use.
        provider_menu = menu.addMenu("Provider")
        self.provider_group = QActionGroup(self)
        self.provider_group.setExclusive(True)
        self.provider_actions: dict[str, QAction] = {}
        for provider in providers.PROVIDERS:
            action = QAction(provider.DISPLAY_NAME, self, checkable=True)
            action.setData(provider.NAME)
            self.provider_group.addAction(action)
            provider_menu.addAction(action)
            self.provider_actions[provider.NAME] = action
        self.provider_group.triggered.connect(
            lambda action: self._choose_provider(action.data())
        )
        menu.addSeparator()

        # OpenAI: an API key and a model picked from OpenAI's models.
        self.openai_menu = menu.addMenu(openai_provider.DISPLAY_NAME)
        self.set_key_action = QAction(_OPENAI_KEY_ITEM, self)
        self.set_key_action.setShortcut(QKeySequence("Ctrl+,"))
        # The lambdas drop QAction's ``checked`` argument, which would
        # otherwise arrive as ``switch=False`` and skip the switch prompt.
        self.set_key_action.triggered.connect(lambda: self._set_api_key())
        self.openai_menu.addAction(self.set_key_action)

        self.set_model_action = QAction(_OPENAI_MODEL_ITEM, self)
        self.set_model_action.triggered.connect(self._set_model)
        self.openai_menu.addAction(self.set_model_action)

        # Azure AI Foundry: the endpoint, key, and the name of a model you
        # deployed. There's no model list here: only your deployments work.
        self.azure_menu = menu.addMenu(azure_provider.DISPLAY_NAME)
        self.set_up_azure_action = QAction(azure_provider.SETUP_ITEM.replace("&", "&&"), self)
        self.set_up_azure_action.triggered.connect(lambda: self._set_up_azure())
        self.azure_menu.addAction(self.set_up_azure_action)

        self.set_deployment_action = QAction(azure_provider.DEPLOYMENT_ITEM, self)
        self.set_deployment_action.triggered.connect(self._set_deployment)
        self.azure_menu.addAction(self.set_deployment_action)
        menu.addSeparator()

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
            # Start empty each time; the last translation stays on the
            # clipboard. Whatever finished while hidden is dropped, so the
            # next hide doesn't paste it.
            self._paste_text = ""
            self._cancel_deferred_paste()
            self._paste_target = None
            self._shown_count += 1
            self._clear_input()
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

    def _clear_input(self) -> None:
        self.input.clear()
        self.timer.stop()
        # Empty input: drops any translation still running and clears the output.
        self.run_translation()
        self._set_status("")

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
        translation that hasn't been pasted yet is pasted into that app. If
        the translation is still running, the window hides right away and the
        paste waits for it to finish (see :meth:`_on_finished`).
        """
        paste = paste and self.prefs.auto_paste
        text = self._take_paste_text() if paste else ""
        if (
            (text or (paste and self._translating))
            and not self._asked_paste_permission
            and self._needs_paste_permission()
        ):
            # Explain while the window is still up; this time the translation
            # stays on the clipboard to paste by hand.
            self._ask_paste_permission()
            if not text:
                # The translation may have finished while the alert was up.
                text = self._take_paste_text()
        defer = paste and not text and self._translating
        self._dismissed = True
        self.hide()
        hotkey.hide_app()
        shown = self._shown_count
        if text:
            self._schedule_paste(text, shown)
        elif defer:
            self._deferred_paste = _DeferredPaste(shown, hotkey.pasteboard_change_count())
            self._deferred_paste_timer.start()
            self._paste_target = _PasteTarget(shown, None, autopaste.input_event_count())
            QTimer.singleShot(_PASTE_DELAY_MS, lambda: self._remember_paste_target(shown))

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
        # item Type Fast copied, never something copied since, even with the
        # same text. The window may also show blank lines typed after it.
        return (
            bool(text)
            and self.output.toPlainText().rstrip() == text.rstrip()
            and QApplication.clipboard().text() == text
            and hotkey.pasteboard_change_count() == self._copy_change_count
        )

    def _schedule_paste(self, text: str, shown: int) -> None:
        """Paste ``text`` once the previous app has focus back."""
        QTimer.singleShot(_PASTE_DELAY_MS, lambda: self._paste_into_previous_app(text, shown))

    def _paste_into_previous_app(
        self, text: str, shown: int, tries: int = _PASTE_TARGET_TRIES
    ) -> None:
        """Paste ``text`` into the app that got focus back after the hide with ``shown``.

        Nothing is pasted if the window was summoned again or the clipboard
        changed. A deferred paste (one with a :class:`_PasteTarget` for this
        hide; :meth:`summon` clears it) also waits for focus to come back and
        is dropped if you switched apps, or clicked or typed, since the hide.
        """
        if shown != self._shown_count or self.isVisible() or not self._is_pasteable(text):
            return  # summoned again, or the clipboard changed, before the paste
        target = self._paste_target
        if target is not None and target.shown == shown:
            # A deferred paste: only into the app that got focus back.
            pid = hotkey.frontmost_app_pid()
            if not self._is_other_app(pid):
                if tries > 1:  # macOS may not have handed focus back yet
                    QTimer.singleShot(
                        _PASTE_DELAY_MS,
                        lambda: self._paste_into_previous_app(text, shown, tries - 1),
                    )
                return
            if target.pid not in (None, pid):
                return  # you switched apps
            if autopaste.input_event_count() != target.input_count:
                return  # you clicked or typed, maybe somewhere else
        autopaste.send_paste()

    def _remember_paste_target(self, shown: int, tries: int = _PASTE_TARGET_TRIES) -> None:
        """Note the app that got focus back after the hide with ``shown``.

        macOS may still list Type Fast as the frontmost app for a moment, so
        this looks again a few times. If it never finds another app, the
        deferred paste goes to the first one frontmost when it runs.
        """
        target = self._paste_target
        if target is None or target.shown != shown or self.isVisible():
            return
        pid = hotkey.frontmost_app_pid()
        if self._is_other_app(pid):
            self._paste_target = target._replace(pid=pid)
        elif tries > 1:
            QTimer.singleShot(
                _PASTE_DELAY_MS, lambda: self._remember_paste_target(shown, tries - 1)
            )

    @staticmethod
    def _is_other_app(pid: int | None) -> bool:
        """True for a known frontmost app that isn't Type Fast."""
        return pid is not None and pid != os.getpid()

    def _take_deferred_paste(self) -> int | None:
        """Return the hide's _shown_count of a paste waiting for this translation.

        Call just before copying the finished translation. Returns None, and
        drops the waiting paste, when there is none or something was copied
        since the hide.
        """
        deferred = self._deferred_paste
        self._cancel_deferred_paste()
        if deferred is None or hotkey.pasteboard_change_count() != deferred.change_count:
            return None
        return deferred.shown

    def _paste_deferred(self, shown: int) -> None:
        """Paste the just-copied translation that a hotkey hide was waiting for."""
        text, self._paste_text = self._paste_text, ""
        if self._is_pasteable(text):
            self._schedule_paste(text, shown)

    def _cancel_deferred_paste(self) -> None:
        """Drop a paste still waiting for its translation.

        A translation that finishes later is still copied.
        """
        self._deferred_paste = None
        self._deferred_paste_timer.stop()

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
        if state == Qt.ApplicationActive:
            # Settings may have changed outside the app (e.g. the setup script);
            # if so, apply them to the current text too, not just the footer.
            if self._provider_state() != self._reflected_provider_state:
                self._after_provider_change()
            else:
                # Only display details (e.g. pinned vs automatic) may differ.
                self._reflect_provider()
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

    def _provider_state(self, provider: ModuleType | None = None) -> tuple[str, ...]:
        """The settings a translation depends on: provider, endpoint, key, model."""
        provider = provider or providers.active_provider()
        return (provider.NAME, *provider.client_key(), provider.get_model())

    def _reflect_provider(self) -> None:
        """Show the active provider and model in the footer, menu, and status."""
        self._reflected_provider_state = self._provider_state()
        provider = providers.active_provider()
        model = providers.get_model()
        self.model_label.setText(f"{provider.SHORT_NAME} \u00b7 {model}")
        how = "" if providers.get_choice() else " (chosen automatically)"
        lines = [f"Provider: {provider.DISPLAY_NAME}{how}"]
        if provider is azure_provider:
            if azure_provider.endpoint_host():
                lines.append(f"Endpoint: {azure_provider.endpoint_host()}")
            lines.append(f"Deployment: {model}")
            change = azure_provider.DEPLOYMENT_PATH
        else:
            lines.append(f"Model: {model}")
            change = _OPENAI_MODEL_PATH
        lines.append(f"Change them in Settings \u203a Provider and {change}")
        self.model_label.setToolTip("\n".join(lines))
        self.model_label.setAccessibleDescription(" ".join(lines))
        self.provider_actions[provider.NAME].setChecked(True)
        self._reflect_key_status()

    def _missing_setup_message(self, provider: ModuleType) -> str:
        if provider is azure_provider:
            return f"Azure AI Foundry isn't set up \u2014 {azure_provider.SETUP_PATH}"
        return f"No API key set \u2014 {_OPENAI_KEY_PATH}"

    def _reflect_key_status(self) -> None:
        provider = providers.active_provider()
        if not provider.is_configured():
            self._set_status(self._missing_setup_message(provider))
        elif self.status.text() in {
            self._missing_setup_message(p) for p in providers.PROVIDERS
        }:
            # Only clear our own hint, not e.g. a translation in progress.
            self._set_status("")

    def _after_provider_change(self) -> None:
        providers.reset_client()  # so the next translation uses the new settings
        self._reflect_provider()
        # The same text may have failed with the old settings; send it again.
        self._last_sent_key = None
        self._retranslate()

    def _choose_provider(self, name: str) -> None:
        """Switch to provider ``name``, setting it up first if needed."""
        provider = providers.by_name(name)
        if provider is None:
            return
        if not provider.is_configured():
            # Setting it up switches to it; cancelling keeps the current one.
            if provider is azure_provider:
                self._set_up_azure(switch=True)
            else:
                self._set_api_key(switch=True)
            self._reflect_provider()
            return
        if self._save_provider_choice(name):
            self._after_provider_change()
        else:
            self._reflect_provider()

    def _save_provider_choice(self, name: str) -> bool:
        try:
            providers.set_choice(name)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Provider",
                f"Could not save the provider to {providers.PROVIDER_FILE}:\n{exc}",
            )
            return False
        return True

    def _confirm_switch(self, provider: ModuleType) -> bool:
        """Ask whether to start using ``provider`` now."""
        answer = QMessageBox.question(
            self,
            "Provider",
            f"Use {provider.DISPLAY_NAME} for translations now?\n"
            f"You can switch any time in Settings \u203a Provider.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        return answer == QMessageBox.Yes

    def _finish_setup(
        self, provider: ModuleType, before: ModuleType, switch: bool | None
    ) -> None:
        """After ``provider`` is set up, switch to it if wanted, and refresh.

        ``before`` is the provider that was active before the setup. If you
        don't switch, it stays active even if the automatic choice would now
        pick ``provider``.
        """
        if switch is None:
            switch = before is not provider and self._confirm_switch(provider)
        if switch:
            self._save_provider_choice(provider.NAME)
        elif providers.active_provider() is not before:
            self._save_provider_choice(before.NAME)
        self._after_provider_change()

    def _ask_azure_settings(self) -> tuple[str, str, str] | None:
        """Show the Foundry setup dialog; return (endpoint, key, model) or None."""
        dialog = AzureSetupDialog(
            azure_provider.get_endpoint(),
            azure_provider.get_api_key(),
            azure_provider.saved_model(),
            azure_provider.env_overrides(),
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.endpoint, dialog.api_key, dialog.model

    def _set_up_azure(self, switch: bool | None = None) -> bool:
        """Set up Azure AI Foundry; return True if the settings were saved.

        ``switch`` says whether to start using it; None asks when it isn't
        already the active provider.
        """
        values = self._ask_azure_settings()
        if values is None:
            return False
        before = providers.active_provider()
        # Once Foundry is set up, the automatic choice picks it. Unless we're
        # switching anyway, pin the current provider first, so a failure to
        # save the choice can't switch providers behind your back.
        pinned = (
            switch is not True
            and before is not azure_provider
            and providers.get_choice() is None
        )
        if pinned and not self._save_provider_choice(before.NAME):
            return False
        try:
            azure_provider.save_settings(*values)
        except OSError as exc:
            if pinned:
                try:
                    providers.set_choice(None)  # back to automatic, as before
                except OSError:
                    pass
            QMessageBox.warning(
                self,
                "Set Up Azure AI Foundry",
                f"Could not save the settings to {azure_provider.ENDPOINT_FILE.parent}:\n{exc}",
            )
            return False
        self._finish_setup(azure_provider, before, switch)
        return True

    def _model_pinned(self, provider: ModuleType, title: str, what: str) -> bool:
        """Say so and return True if an env var pins ``provider``'s model."""
        env = providers.model_env_override(provider)
        if env:
            QMessageBox.information(
                self,
                title,
                f"The {what} is pinned by the {env} environment variable "
                f"({provider.get_model()}). Unset it to choose one here.",
            )
        return env is not None

    @staticmethod
    def _not_in_use_note(provider: ModuleType, what: str) -> str:
        """A prompt note saying ``provider`` isn't in use yet, if it isn't."""
        active = providers.active_provider()
        if active is provider:
            return ""
        return (
            f"\n\n{active.DISPLAY_NAME} is in use now; this {what} is used "
            f"once you switch to {provider.DISPLAY_NAME}."
        )

    def _save_model(
        self, provider: ModuleType, model: str, title: str, what: str
    ) -> None:
        """Save ``provider``'s model; refresh only if it is the one in use."""
        try:
            provider.save_model(model)
        except OSError as exc:
            QMessageBox.warning(
                self,
                title,
                f"Could not save the {what} to {provider.MODEL_FILE}:\n{exc}",
            )
            return
        if self._provider_state() != self._reflected_provider_state:
            self._reflect_provider()
            self._retranslate()

    def _set_model(self) -> None:
        """Pick the OpenAI model, whichever provider is active.

        Azure AI Foundry has no model list: it can only use models you have
        deployed, so it gets a deployment name instead (see _set_deployment).
        """
        title = "Set OpenAI Model"
        if self._model_pinned(openai_provider, title, "OpenAI model"):
            return
        current = openai_provider.get_model()
        choices = list(config.MODEL_CHOICES)
        if current not in choices:
            choices.insert(0, current)
        prompt = (
            f"OpenAI model (stored in {openai_provider.MODEL_FILE}; leave blank "
            f"for the default, {config.DEFAULT_OPENAI_MODEL}):"
        )
        prompt += self._not_in_use_note(openai_provider, "model")
        model, ok = QInputDialog.getItem(
            self, title, prompt, choices, choices.index(current), True
        )
        if ok:
            self._save_model(openai_provider, model, title, "OpenAI model")

    def _set_deployment(self) -> None:
        """Type the name of the Azure AI Foundry deployment to use."""
        if not azure_provider.is_configured():
            # The deployment is asked for along with the endpoint and key.
            self._set_up_azure()
            return
        title = "Set Azure AI Foundry Deployment"
        if self._model_pinned(azure_provider, title, "deployment"):
            return
        prompt = (
            "Deployment name, exactly as shown in the Foundry portal\n"
            f"(stored in {azure_provider.MODEL_FILE}; leave blank for "
            f"{config.DEFAULT_OPENAI_MODEL}):"
        ) + self._not_in_use_note(azure_provider, "deployment")
        model = azure_provider.saved_model()
        while True:
            model, ok = QInputDialog.getText(
                self, title, prompt, QLineEdit.Normal, model
            )
            if not ok:
                return
            model = model.strip()
            problem = azure_provider.deployment_problem(model)
            if not problem:
                break
            QMessageBox.warning(self, title, problem)
        self._save_model(azure_provider, model, title, "deployment name")

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
        # A paste waiting from a hotkey hide was for the old translation.
        self._cancel_deferred_paste()
        self.timer.stop()
        self.run_translation()

    def _set_api_key(self, switch: bool | None = None) -> bool:
        """Set the OpenAI API key; return True if one was saved.

        ``switch`` says whether to start using OpenAI; None asks when it isn't
        already the active provider.
        """
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
            return False
        key = key.strip()
        if not key:
            return False
        before = providers.active_provider()
        try:
            openai_provider.save_api_key(key)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Set OpenAI API Key",
                f"Could not save the key to {openai_provider.API_KEY_FILE}:\n{exc}",
            )
            return False
        self._finish_setup(openai_provider, before, switch)
        return True

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
        provider = providers.active_provider()
        model = provider.get_model()
        provider_state = self._provider_state(provider)

        # A language, tone, provider, endpoint, key, or model change makes the
        # frozen translation stale.
        context = (source, target, tone, *provider_state)
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

        key = (self._frozen_src, active, source, target, tone, *provider_state, should_freeze)
        if key == self._last_sent_key:
            return
        self._last_sent_key = key

        # Frozen lines are joined to the active line with a newline.
        self._active_prefix = self._frozen_out + ("\n" if self._frozen_out else "")
        self._pending_freeze = (should_freeze, frozen_after, self._active_prefix)

        # Bind the request to this provider's client now, so a switch made
        # before the worker starts can't send it with other settings.
        client: OpenAI | Exception
        try:
            client = providers.get_client(provider)
        except Exception as exc:  # reported by the worker, like API errors
            client = exc

        self._request_id += 1
        request_id = self._request_id
        self._translating = True
        self.bridge.started.emit(request_id)

        thread = threading.Thread(
            target=self._translate_worker,
            args=(request_id, active, source, target, tone, model, client),
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
        client: OpenAI | Exception,
    ) -> None:
        def superseded() -> bool:
            return request_id != self._request_id

        chunks: list[str] = []
        try:
            if isinstance(client, Exception):
                raise client
            for chunk in translate_stream(
                text,
                source,
                target,
                tone=tone,
                model=model,
                client=client,
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
                if self._translating:
                    return
                # Only blank lines followed: nothing more to translate.
        # Nothing left to translate: auto-copy the finished translation.
        deferred = self._take_deferred_paste()
        self._copy_output_to_clipboard()
        if deferred is not None:
            self._paste_deferred(deferred)

    def _on_error(self, request_id: int, message: str) -> None:
        if request_id == self._request_id:
            self._translating = False
            self._paste_text = ""
            self._cancel_deferred_paste()
            self._set_status("")
            self.output.setPlainText(f"[error] {message}")

    def _copy_output_to_clipboard(self) -> None:
        text = self.output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self._copy_change_count = hotkey.pasteboard_change_count()
            self._paste_text = text
            self._set_status("Copied to clipboard \u2713", "done")


# The Dock and window icon, set at runtime in every run mode (Type Fast.spec
# bundles it into the .app). Finder uses assets/icon/TypeFast.icns instead.
ICON_PATH = Path(__file__).resolve().parent / "resources" / "icon.png"


def app_icon() -> QIcon:
    """Return the Type Fast icon (empty if the image file is missing)."""
    return QIcon(str(ICON_PATH))


def main() -> None:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Type Fast")
    app.setApplicationDisplayName("Type Fast")
    app.setWindowIcon(app_icon())
    window = MainWindow()
    window.resize(460, 380)
    # Show on launch so first-time users see the window (and its hotkey hint).
    window.summon()
    app.exec()


if __name__ == "__main__":
    main()

"""PySide6 PoC window for type-fast.

A small window, summoned on demand Spotlight-style with a configurable global
hotkey (⌥Space by default; Settings › Set Show/Hide Hotkey…). Pressing the
hotkey again, or Esc, dismisses it and hands focus back to the previous app.
While shown it stays on top of other windows. It has an input box, a streamed
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
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import (
    QAction,
    QCursor,
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

from . import config, hotkey, providers, settings
from .providers import openai as openai_provider
from .translator import translate_stream

# Characters that, when at the end of the input, trigger an immediate
# translation instead of waiting for the idle debounce.
# Covers Latin, CJK full-width, Arabic (\u061f), and Devanagari (\u0964) marks.
_SENTENCE_ENDINGS = (
    ".", "!", "?", "\u3002", "\uff01", "\uff1f", "\u061f", "\u0964",
)

_AUTO_LABEL = "Auto-detect"


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

        info = QLabel(
            "Press the key combination that shows and hides Type Fast from any "
            "app. Include \u2318, \u2303, or \u2325 (or use an F-key).\n"
            "\u2318Space is Spotlight\u2019s shortcut unless you change it in "
            "System Settings."
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

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addWidget(self.editor)
        layout.addWidget(buttons)
        self.editor.setFocus()

    def _finish(self, text: str) -> None:
        self.chosen = text
        super().accept()

    def accept(self) -> None:
        sequence = self.editor.keySequence()
        if sequence.isEmpty():
            self._finish("")
            return
        parsed = hotkey.from_qt(sequence)
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
        self.swap_button.setText("\u21c4")
        self.swap_button.setToolTip("Swap languages")
        self._select_languages(self.prefs.source, self.prefs.target)

        self.tone = QComboBox()
        self.tone.setToolTip("Tone of the translation")
        for name in config.TONES:
            self.tone.addItem(name, name)
        self.tone.addItem(f"{config.CUSTOM_TONE}\u2026", config.CUSTOM_TONE)
        self.tone.setCurrentIndex(self.tone.findData(self.prefs.tone))
        self._update_tone_tooltip()

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

        self.model_label = QLabel()
        self.model_label.setStyleSheet("color: gray;")

        self.hotkey_label = QLabel()
        self.hotkey_label.setStyleSheet("color: gray;")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(8)
        controls = QHBoxLayout()
        controls.addWidget(self.source_lang, 1)
        controls.addWidget(self.swap_button)
        controls.addWidget(self.target_lang, 1)
        controls.addWidget(self.tone)
        layout.addLayout(controls)
        layout.addWidget(self.input_label)
        layout.addWidget(self.input)
        layout.addWidget(self.output_label)
        layout.addWidget(self.output)
        footer = QHBoxLayout()
        footer.addWidget(self.model_label)
        footer.addWidget(self.hotkey_label)
        footer.addWidget(self.status, 1)
        layout.addLayout(footer)
        self.setCentralWidget(central)

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
        self.global_hotkey = hotkey.GlobalHotkey(self)
        self.global_hotkey.activated.connect(self.toggle_visibility)
        self._register_hotkey()
        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_app_state_changed)

        # Monotonic id identifying the most recent translation request so that
        # superseded, slower in-flight translations are discarded.
        self._request_id = 0

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

        self.set_hotkey_action = QAction("Set Show/Hide Hotkey\u2026", self)
        self.set_hotkey_action.triggered.connect(self._set_hotkey)
        menu.addAction(self.set_hotkey_action)

    # --- Show/hide --------------------------------------------------------

    def toggle_visibility(self) -> None:
        """Hide the window if it is shown and focused, otherwise summon it."""
        modal = QApplication.activeModalWidget()
        if modal is not None:
            # Don't hide the window out from under an open dialog.
            hotkey.activate_app()
            modal.raise_()
            modal.activateWindow()
            return
        if self.isVisible() and self.isActiveWindow() and not self.isMinimized():
            self.dismiss()
        else:
            self.summon()

    def summon(self) -> None:
        """Show, raise, and focus the window, Spotlight-style."""
        self._dismissed = False
        if not self.isVisible():
            self._center_on_cursor_screen()
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()
        hotkey.activate_app()
        self.input.setFocus()
        self.input.moveCursor(QTextCursor.End)

    def dismiss(self) -> None:
        """Hide the window and return focus to the previously active app."""
        self._dismissed = True
        self.hide()
        hotkey.hide_app()

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
            self.status.setText("")
        else:
            self.status.setText("No API key set \u2014 Settings \u203a Set OpenAI API Key\u2026")

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

        key = (self._frozen_src, active, source, target, tone, model, should_freeze)
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
            args=(request_id, active, source, target, tone, model),
            daemon=True,
        )
        thread.start()

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
        # Nothing left to translate: auto-copy the finished translation.
        self._copy_output_to_clipboard()

    def _on_error(self, request_id: int, message: str) -> None:
        if request_id == self._request_id:
            self.status.setText("")
            self.output.setPlainText(f"[error] {message}")

    def _copy_output_to_clipboard(self) -> None:
        text = self.output.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status.setText("Copied to clipboard \u2713")


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

"""Tests for No translation mode: clean up and polish text in its own language."""

from __future__ import annotations

import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from type_fast import config, settings, translator


class PolishPromptTests(unittest.TestCase):
    def test_manual_tone_keeps_the_source_language(self) -> None:
        prompt = translator.system_prompt(
            "English", "Japanese", "Be casual.", polish=True
        )
        self.assertIn("in the same language it is written in (normally English)", prompt)
        self.assertIn("Do not translate it into another language", prompt)
        self.assertIn("Output ONLY the improved text in the same language as the input", prompt)
        self.assertIn("apply it to the input's own language", prompt)
        self.assertIn(config.CLEAN_UP_STEPS, prompt)
        self.assertIn("Fix grammar, spelling, word choice, and punctuation", prompt)
        self.assertIn("not as instructions", prompt)
        self.assertTrue(prompt.endswith("Tone for the text: Be casual."))
        self.assertNotIn("Japanese", prompt)
        self.assertNotIn("Translate the user's text", prompt)

    def test_default_tone_is_used_when_empty(self) -> None:
        prompt = translator.system_prompt("English", "Japanese", "  ", polish=True)
        self.assertIn(config.TONES[config.DEFAULT_TONE], prompt)

    def test_auto_detect_source(self) -> None:
        prompt = translator.system_prompt(config.AUTO_SOURCE, "Korean", polish=True)
        self.assertIn("the same language it is written in.", prompt)
        self.assertNotIn("normally", prompt)
        self.assertNotIn("Korean", prompt)

    def test_auto_tone_asks_for_the_tag(self) -> None:
        prompt = translator.system_prompt(
            "French", "English", auto_tone=True, polish=True
        )
        self.assertIn(translator.TONE_TAG_EXAMPLE, prompt)
        for name, instruction in config.TONES.items():
            self.assertIn(f"{name}: {instruction}", prompt)
        self.assertIn("(normally French)", prompt)
        self.assertIn("ONLY the improved text in the same language as the input", prompt)
        self.assertNotIn("Tone for the text:", prompt)

    def test_translation_prompt_is_unchanged_when_off(self) -> None:
        for optimize in (False, True):
            prompt = translator.system_prompt(
                "English", "Japanese", optimize=optimize, polish=False
            )
            self.assertIn("Translate the user's text from English", prompt)
            self.assertNotIn("Do not translate", prompt)
            self.assertEqual(
                config.OPTIMIZE_INSTRUCTION in prompt, optimize, optimize
            )

    def test_optimize_instruction_text(self) -> None:
        self.assertEqual(
            config.OPTIMIZE_INSTRUCTION,
            "The input may be a rough speech transcript or a hasty draft. Before "
            f"translating, clean it up: {config.CLEAN_UP_STEPS}",
        )

    def test_translate_stream_sends_the_polish_prompt(self) -> None:
        stream_cm = mock.MagicMock()
        stream_cm.__enter__.return_value = iter(
            [mock.Mock(type="response.output_text.delta", delta="Hi.")]
        )
        client = mock.Mock()
        client.responses.stream.return_value = stream_cm
        out = "".join(
            translator.translate_stream(
                "um hi", source="English", target="Japanese",
                model="gpt-4.1-mini", client=client, polish=True,
            )
        )
        self.assertEqual(out, "Hi.")
        system = client.responses.stream.call_args.kwargs["input"][0]["content"]
        self.assertIn("Do not translate it into another language", system)


class PolishSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(
            settings, "SETTINGS_FILE", Path(self.tmp.name) / "settings.json"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_is_off(self) -> None:
        self.assertFalse(settings.load().polish)

    def test_round_trip_keeps_the_target(self) -> None:
        settings.save(settings.Settings(source="English", target="Korean", polish=True))
        loaded = settings.load()
        self.assertTrue(loaded.polish)
        self.assertEqual((loaded.source, loaded.target), ("English", "Korean"))

    def test_invalid_values_fall_back_to_off(self) -> None:
        for value in ("yes", 1, None, [True]):
            settings.SETTINGS_FILE.write_text(
                json.dumps({"polish": value}), encoding="utf-8"
            )
            self.assertFalse(settings.load().polish, value)


class _InlineThread:
    """Stand-in for ``threading.Thread`` that runs its target on ``start()``."""

    def __init__(self, target, args=(), daemon=None) -> None:
        self._target, self._args = target, args

    def start(self) -> None:
        self._target(*self._args)


@unittest.skipUnless(
    os.environ.get("QT_QPA_PLATFORM") == "offscreen",
    "set QT_QPA_PLATFORM=offscreen to run the headless window tests",
)
class WindowPolishTests(unittest.TestCase):
    # _translate_worker(request_id, text, source, target, tone, model,
    #                   auto_tone, optimize, polish, client)

    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from type_fast import app

        self.app_module = app
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(
            settings, "SETTINGS_FILE", Path(self.tmp.name) / "settings.json"
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(
            app, "threading", types.SimpleNamespace(Thread=_InlineThread)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls: list[tuple] = []
        self.window = self._new_window()

    def _new_window(self):
        w = self.app_module.MainWindow()
        self.addCleanup(w.close)
        w._translate_worker = lambda *args: self.calls.append(args)
        return w

    def _pick(self, combo, value: str) -> None:
        combo.activated.emit(combo.findData(value))

    def _polish_on(self) -> None:
        self._pick(self.window.target_lang, config.SAME_AS_INPUT)

    def test_same_as_input_is_the_first_target(self) -> None:
        w = self.window
        self.assertEqual(w.target_lang.itemData(0), config.SAME_AS_INPUT)
        self.assertIn("no translation", w.target_lang.itemText(0).lower())

    def test_picking_same_as_input_polishes(self) -> None:
        w = self.window
        w.input.setPlainText("um so hello")
        self._polish_on()
        self.assertTrue(w.prefs.polish)
        self.assertEqual(w.prefs.target, config.DEFAULT_UI_TARGET)
        self.assertEqual(w.target_lang.currentData(), config.SAME_AS_INPUT)
        self.assertFalse(w.swap_button.isEnabled())
        self.assertIn("No translation", w.swap_button.toolTip())
        self.assertEqual(w.swap_button.accessibleName(), "Swap languages")
        self.assertIn("No translation", w.swap_button.accessibleDescription())
        self.assertEqual(w.pair_button.text(), "English \u00b7 No translation")
        self.assertEqual(w.output_label.text(), "English (cleaned up)")
        self.assertEqual(w.output.placeholderText(), "Cleaned-up text appears here\u2026")
        args = self.calls[-1]
        self.assertEqual(args[1], "um so hello")
        self.assertTrue(args[7])  # clean-up is always on
        self.assertTrue(args[8])
        self.assertTrue(settings.load().polish)

    def test_auto_detect_labels(self) -> None:
        w = self.window
        self._pick(w.source_lang, config.AUTO_SOURCE)
        self.assertIn("Auto-detect", w.swap_button.toolTip())
        self._polish_on()
        self.assertEqual(w.pair_button.text(), "Auto-detect \u00b7 No translation")
        self.assertEqual(w.output_label.text(), "Same as input (cleaned up)")
        self.assertIn("No translation", w.swap_button.toolTip())

    def test_picking_a_language_restores_translation(self) -> None:
        w = self.window
        w.input.setPlainText("hello.")
        self._polish_on()
        self._pick(w.target_lang, "French")
        self.assertFalse(w.prefs.polish)
        self.assertEqual(w.target_lang.currentData(), "French")
        self.assertTrue(w.swap_button.isEnabled())
        self.assertEqual(w.swap_button.toolTip(), "Swap languages")
        self.assertEqual(w.swap_button.accessibleDescription(), "")
        self.assertEqual(w.pair_button.text(), "English \u2192 French")
        self.assertEqual(w.output.placeholderText(), "Translation appears here\u2026")
        self.assertFalse(self.calls[-1][8])
        self.assertEqual(self.calls[-1][2:4], ("English", "French"))
        self.assertFalse(settings.load().polish)

    def test_picking_the_source_language_leaves_polish_by_swapping(self) -> None:
        w = self.window
        self._polish_on()
        self._pick(w.target_lang, "English")
        self.assertFalse(w.prefs.polish)
        self.assertEqual(
            (w.source_lang.currentData(), w.target_lang.currentData()),
            ("Japanese", "English"),
        )

    def test_swap_does_nothing_while_polishing(self) -> None:
        w = self.window
        self._polish_on()
        w._swap_languages()
        self.assertEqual((w.prefs.source, w.prefs.target), ("English", "Japanese"))
        self.assertTrue(w.prefs.polish)

    def test_source_change_keeps_the_hidden_target_valid(self) -> None:
        w = self.window
        self._pick(w.source_lang, "French")
        self._polish_on()
        # Picking the hidden target as the source swaps it, like a swap would.
        self._pick(w.source_lang, "Japanese")
        self.assertTrue(w.prefs.polish)
        self.assertEqual((w.prefs.source, w.prefs.target), ("Japanese", "French"))
        self.assertEqual(w.target_lang.currentData(), config.SAME_AS_INPUT)
        self.assertEqual(w.pair_button.text(), "Japanese \u00b7 No translation")
        # From Auto-detect there is no previous language to take.
        self._pick(w.source_lang, config.AUTO_SOURCE)
        self._pick(w.source_lang, "French")
        self.assertEqual(w.prefs.source, "French")
        self.assertNotIn(w.prefs.target, ("French", config.AUTO_SOURCE))

    def test_restored_on_new_window(self) -> None:
        self._polish_on()
        w2 = self._new_window()
        self.assertTrue(w2.prefs.polish)
        self.assertEqual(w2.target_lang.currentData(), config.SAME_AS_INPUT)
        self.assertFalse(w2.swap_button.isEnabled())
        self._pick(w2.target_lang, "Thai")
        self.assertEqual(w2.target_lang.currentData(), "Thai")

    def test_toggling_polish_invalidates_frozen_lines(self) -> None:
        w = self.window
        w.input.setPlainText("line one\n")
        w._on_finished(w._request_id, "un")  # freezes line one
        w.input.setPlainText("line one\nline two.")
        self.assertEqual(self.calls[-1][1], "line two.")
        self._polish_on()
        self.assertEqual(self.calls[-1][1], "line one")
        self.assertTrue(self.calls[-1][8])

    def test_status_says_polishing(self) -> None:
        w = self.window
        self._polish_on()
        w._on_started(w._request_id)
        self.assertEqual(w.status.text(), "Cleaning up\u2026")


if __name__ == "__main__":
    unittest.main()

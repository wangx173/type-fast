"""Tests for multi-language support: settings, prompt, and the window pickers."""

from __future__ import annotations

import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from type_fast import config, settings, translator


class LanguageSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(
            settings, "SETTINGS_FILE", Path(self.tmp.name) / "settings.json"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write(self, data: object) -> None:
        settings.SETTINGS_FILE.write_text(json.dumps(data), encoding="utf-8")

    def test_defaults(self) -> None:
        loaded = settings.load()
        self.assertEqual(
            (loaded.source, loaded.target),
            (config.DEFAULT_UI_SOURCE, config.DEFAULT_UI_TARGET),
        )

    def test_round_trip_keeps_languages_and_tone(self) -> None:
        settings.save(
            settings.Settings(source=config.AUTO_SOURCE, target="Korean", tone="Casual")
        )
        loaded = settings.load()
        self.assertEqual(loaded.source, config.AUTO_SOURCE)
        self.assertEqual(loaded.target, "Korean")
        self.assertEqual(loaded.tone, "Casual")

    def test_settings_from_tone_only_file_keep_default_languages(self) -> None:
        self._write({"tone": "Formal", "custom_tone": ""})
        loaded = settings.load()
        self.assertEqual(loaded.tone, "Formal")
        self.assertEqual(loaded.source, config.DEFAULT_UI_SOURCE)
        self.assertEqual(loaded.target, config.DEFAULT_UI_TARGET)

    def test_invalid_languages_restore_default_pair(self) -> None:
        for data in (
            {"source": "Klingon", "target": "French"},
            {"source": "French", "target": "Klingon"},
            {"source": ["English"], "target": {}},
            {"source": "French", "target": config.AUTO_SOURCE},
            {"source": "French"},
            {"target": "French"},
        ):
            self._write(data)
            loaded = settings.load()
            self.assertEqual(
                (loaded.source, loaded.target),
                (config.DEFAULT_UI_SOURCE, config.DEFAULT_UI_TARGET),
                data,
            )

    def test_same_source_and_target_falls_back_to_default_pair(self) -> None:
        self._write({"source": "French", "target": "French"})
        loaded = settings.load()
        self.assertEqual(
            (loaded.source, loaded.target),
            (config.DEFAULT_UI_SOURCE, config.DEFAULT_UI_TARGET),
        )


class PromptTests(unittest.TestCase):
    def test_prompt_names_both_languages(self) -> None:
        prompt = translator.system_prompt("Korean", "Spanish")
        self.assertIn("from Korean", prompt)
        self.assertIn("into natural Spanish", prompt)
        self.assertNotIn("romaji", prompt)

    def test_auto_source(self) -> None:
        prompt = translator.system_prompt(config.AUTO_SOURCE, "German")
        self.assertIn("auto-detect", prompt)


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
class WindowLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from type_fast import app

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(
            settings, "SETTINGS_FILE", Path(self.tmp.name) / "settings.json"
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        # Run the translation "thread" inline so recorded calls are visible
        # as soon as run_translation() returns (no race with a real thread).
        patcher = mock.patch.object(
            app, "threading", types.SimpleNamespace(Thread=_InlineThread)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls: list[tuple] = []
        self.window = app.MainWindow()
        self.window._translate_worker = lambda *args: self.calls.append(args)

    def _pick(self, combo, value: str) -> None:
        combo.activated.emit(combo.findData(value))

    def _pair(self) -> tuple[str, str]:
        w = self.window
        return (w.source_lang.currentData(), w.target_lang.currentData())

    def test_pickers_list_all_languages(self) -> None:
        w = self.window
        self.assertEqual(w.source_lang.count(), len(config.LANGUAGES) + 1)
        self.assertEqual(w.target_lang.count(), len(config.LANGUAGES))
        self.assertEqual(self._pair(), (config.DEFAULT_UI_SOURCE, config.DEFAULT_UI_TARGET))

    def test_change_target_retranslates_and_persists(self) -> None:
        w = self.window
        w.input.setPlainText("hello.")
        self._pick(w.target_lang, "French")
        self.assertEqual(self.calls[-1][2:4], ("English", "French"))
        self.assertEqual(w.output_label.text(), "French \u00b7 Fran\u00e7ais")
        self.assertEqual(settings.load().target, "French")

    def test_swap(self) -> None:
        w = self.window
        w.input.setPlainText("hello.")
        w.swap_button.click()
        self.assertEqual(self._pair(), ("Japanese", "English"))
        self.assertEqual(self.calls[-1][2:4], ("Japanese", "English"))

    def test_picking_same_language_swaps(self) -> None:
        w = self.window
        self._pick(w.target_lang, "English")
        self.assertEqual(self._pair(), ("Japanese", "English"))
        self._pick(w.source_lang, "English")
        self.assertEqual(self._pair(), ("English", "Japanese"))

    def test_auto_detect_source(self) -> None:
        w = self.window
        self._pick(w.source_lang, config.AUTO_SOURCE)
        self.assertFalse(w.swap_button.isEnabled())
        self.assertEqual(w.input_label.text(), "Auto-detect")
        # Choosing the current target as source from auto picks another target.
        self._pick(w.source_lang, "Japanese")
        self.assertEqual(self._pair(), ("Japanese", "English"))
        self.assertTrue(w.swap_button.isEnabled())

    def test_language_change_invalidates_frozen_lines(self) -> None:
        w = self.window
        w.input.setPlainText("line one\n")
        self.assertEqual(self.calls[-1][1], "line one")
        w._on_finished(w._request_id, "un")  # freezes line one
        w.input.setPlainText("line one\nline two.")
        self.assertEqual(self.calls[-1][1], "line two.")
        self._pick(w.target_lang, "German")
        # The frozen line is stale, so translation restarts from line one.
        self.assertEqual(self.calls[-1][1], "line one")
        self.assertEqual(self.calls[-1][3], "German")

    def test_restored_on_new_window(self) -> None:
        from type_fast import app

        self._pick(self.window.source_lang, "Korean")
        self._pick(self.window.target_lang, "Thai")
        w2 = app.MainWindow()
        self.assertEqual(
            (w2.source_lang.currentData(), w2.target_lang.currentData()),
            ("Korean", "Thai"),
        )


if __name__ == "__main__":
    unittest.main()

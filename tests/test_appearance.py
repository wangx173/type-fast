"""Unit tests for the window's styling and translucency."""

from __future__ import annotations

import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from type_fast import config, settings

_HEADLESS = os.environ.get("QT_QPA_PLATFORM") == "offscreen"


class TransparencySettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(
            settings, "SETTINGS_FILE", Path(self.tmp.name) / "settings.json"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _load(self, data: object) -> settings.Settings:
        settings.SETTINGS_FILE.write_text(json.dumps(data), encoding="utf-8")
        return settings.load()

    def test_presets_are_sane(self) -> None:
        self.assertIn(config.DEFAULT_TRANSPARENCY, config.TRANSPARENCY)
        self.assertEqual(config.TRANSPARENCY["Off"], (1.0, 1.0))
        for name, (focused, background) in config.TRANSPARENCY.items():
            # Never fully invisible, and never more opaque in the background.
            self.assertTrue(0.3 <= background <= focused <= 1.0, name)

    def test_default_is_slightly_transparent(self) -> None:
        focused, background = config.TRANSPARENCY[config.DEFAULT_TRANSPARENCY]
        self.assertLess(focused, 1.0)
        self.assertGreaterEqual(focused, 0.9)  # still easy to read while typing
        self.assertLess(background, focused)
        self.assertEqual(settings.load().transparency, config.DEFAULT_TRANSPARENCY)

    def test_round_trip(self) -> None:
        settings.save(settings.Settings(transparency="Strong"))
        self.assertEqual(settings.load().transparency, "Strong")

    def test_invalid_falls_back(self) -> None:
        for bad in ("Opaque", "", 0.5, None, []):
            self.assertEqual(
                self._load({"transparency": bad}).transparency,
                config.DEFAULT_TRANSPARENCY,
                bad,
            )
        # Other settings are unaffected by a bad transparency value.
        self.assertEqual(self._load({"tone": "Casual", "transparency": 1}).tone, "Casual")


@unittest.skipUnless(_HEADLESS, "set QT_QPA_PLATFORM=offscreen to run the headless window tests")
class WindowAppearanceTests(unittest.TestCase):
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
            app, "threading", types.SimpleNamespace(Thread=mock.MagicMock())
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.window = app.MainWindow()
        self.addCleanup(self.window.close)

    def _settle(self, engaged: bool) -> float:
        """Recompute the opacity as if (not) engaged and finish any fade."""
        w = self.window
        with mock.patch.object(w, "_is_engaged", return_value=engaged):
            w._update_opacity()
        w._opacity_anim.setCurrentTime(w._opacity_anim.duration())
        return w.windowOpacity()

    def test_style_sheet_applied(self) -> None:
        w = self.window
        self.assertIn("#inputBox", w.centralWidget().styleSheet())
        self.assertEqual(w.input.objectName(), "inputBox")
        self.assertEqual(w.output.objectName(), "outputBox")
        self.assertEqual(w.pair_button.objectName(), "pairChip")
        # Re-applying (e.g. on a light/dark switch) is safe.
        w._apply_style(None)
        self.assertIn("#outputBox", w.centralWidget().styleSheet())

    def test_status_state(self) -> None:
        w = self.window
        w._set_status("Translating\u2026", "busy")
        self.assertEqual(w.status.property("state"), "busy")
        w._copy_output_to_clipboard()  # nothing to copy: unchanged
        self.assertEqual(w.status.property("state"), "busy")
        w.output.setPlainText("hola")
        w._copy_output_to_clipboard()
        self.assertEqual(w.status.text(), "Copied to clipboard \u2713")
        self.assertEqual(w.status.property("state"), "done")
        w._on_error(w._request_id, "boom")
        self.assertEqual(w.status.property("state"), "")

    def test_translucent_when_focused_fades_in_background(self) -> None:
        focused, background = config.TRANSPARENCY[config.DEFAULT_TRANSPARENCY]
        self.window.summon()
        self.assertAlmostEqual(self._settle(True), focused, places=2)
        self.assertAlmostEqual(self._settle(False), background, places=2)
        self.assertAlmostEqual(self._settle(True), focused, places=2)

    def test_hover_restores_opacity(self) -> None:
        # macOS sends no Enter/Leave events to an inactive app, so hover is
        # polled from the pointer position while another app is active.
        from PySide6.QtCore import QPoint

        w = self.window
        focused, background = config.TRANSPARENCY[config.DEFAULT_TRANSPARENCY]
        w.summon()
        inside = w.frameGeometry().center()
        outside = w.frameGeometry().bottomRight() + QPoint(50, 50)
        pointer = types.SimpleNamespace(pos=lambda: outside)
        with mock.patch.object(w, "isActiveWindow", return_value=False), mock.patch.object(
            self.app_module.QApplication, "activeWindow", return_value=None
        ), mock.patch.object(self.app_module, "QCursor", pointer):
            w._on_focus_window_changed(None)
            self.assertTrue(w._hover_timer.isActive())
            w._opacity_anim.setCurrentTime(w._opacity_anim.duration())
            self.assertAlmostEqual(w.windowOpacity(), background, places=2)

            pointer.pos = lambda: inside
            w._poll_hover()
            self.assertTrue(w._hovered)
            w._opacity_anim.setCurrentTime(w._opacity_anim.duration())
            self.assertAlmostEqual(w.windowOpacity(), focused, places=2)

            pointer.pos = lambda: outside
            w._poll_hover()
            self.assertFalse(w._hovered)
            w._opacity_anim.setCurrentTime(w._opacity_anim.duration())
            self.assertAlmostEqual(w.windowOpacity(), background, places=2)

        w.hide()  # dismissing stops polling (see hideEvent)
        self.assertFalse(w._hover_timer.isActive())

    def test_no_hover_polling_while_app_active(self) -> None:
        w = self.window
        w.summon()
        with mock.patch.object(
            self.app_module.QApplication, "activeWindow", return_value=w
        ):
            w._on_focus_window_changed(w)
        self.assertFalse(w._hover_timer.isActive())

    def test_summon_fades_in_from_invisible(self) -> None:
        w = self.window
        focused, _ = config.TRANSPARENCY[config.DEFAULT_TRANSPARENCY]
        w.summon()
        anim = w._opacity_anim
        self.assertEqual(anim.startValue(), 0.0)
        self.assertAlmostEqual(anim.endValue(), focused, places=2)
        anim.setCurrentTime(anim.duration())
        self.assertAlmostEqual(w.windowOpacity(), focused, places=2)

    def test_menu_changes_and_saves_transparency(self) -> None:
        w = self.window
        names = [a.data() for a in w.transparency_group.actions()]
        self.assertEqual(names, list(config.TRANSPARENCY))
        checked = w.transparency_group.checkedAction()
        self.assertEqual(checked.data(), config.DEFAULT_TRANSPARENCY)

        off = next(a for a in w.transparency_group.actions() if a.data() == "Off")
        off.trigger()
        self.assertEqual(w.prefs.transparency, "Off")
        self.assertEqual(settings.load().transparency, "Off")
        self.assertEqual(w.transparency_group.checkedAction().data(), "Off")
        w.summon()
        self.assertAlmostEqual(self._settle(False), 1.0, places=2)
        self.assertAlmostEqual(self._settle(True), 1.0, places=2)

    def test_saved_transparency_restored(self) -> None:
        settings.save(settings.Settings(transparency="Medium"))
        w = self.app_module.MainWindow()
        self.addCleanup(w.close)
        self.assertEqual(w.prefs.transparency, "Medium")
        self.assertEqual(w.transparency_group.checkedAction().data(), "Medium")


if __name__ == "__main__":
    unittest.main()

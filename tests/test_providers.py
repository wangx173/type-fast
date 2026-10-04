"""Tests for choosing the provider, saving Foundry settings, and the provider UI."""

from __future__ import annotations

import os
import stat
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from type_fast import config, providers, settings
from type_fast.providers import azure as azure_provider, openai as openai_provider

_HEADLESS = os.environ.get("QT_QPA_PLATFORM") == "offscreen"

ENDPOINT = "https://example.services.ai.azure.com"


class _IsolatedProviders(unittest.TestCase):
    """Points every provider file at a temp dir and clears provider env vars."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for target, attr, name in [
            (providers, "PROVIDER_FILE", "provider"),
            (openai_provider, "MODEL_FILE", "openai_model"),
            (openai_provider, "API_KEY_FILE", "api_key"),
            (azure_provider, "MODEL_FILE", "azure_ai_model"),
            (azure_provider, "ENDPOINT_FILE", "azure_ai_endpoint"),
            (azure_provider, "API_KEY_FILE", "azure_ai_api_key"),
        ]:
            patcher = mock.patch.object(target, attr, root / name)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("OPENAI_", "AZURE_AI_"))
        }
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        providers.reset_client()
        self.addCleanup(providers.reset_client)

    def set_up_openai(self) -> None:
        openai_provider.save_api_key("sk-test")

    def set_up_azure(self, model: str = "") -> None:
        azure_provider.save_settings(ENDPOINT, "azure-key", model)


class ProviderChoiceTests(_IsolatedProviders):
    def test_automatic_prefers_configured_azure(self) -> None:
        self.assertIsNone(providers.get_choice())
        self.assertIs(providers.active_provider(), openai_provider)
        self.set_up_openai()
        self.assertIs(providers.active_provider(), openai_provider)
        self.set_up_azure()
        self.assertIs(providers.active_provider(), azure_provider)

    def test_saved_choice_wins(self) -> None:
        self.set_up_openai()
        self.set_up_azure()
        providers.set_choice("openai")
        self.assertEqual(providers.PROVIDER_FILE.read_text(), "openai")
        self.assertIs(providers.active_provider(), openai_provider)
        providers.set_choice(None)
        self.assertFalse(providers.PROVIDER_FILE.exists())
        self.assertIs(providers.active_provider(), azure_provider)

    def test_chosen_provider_without_setup_has_no_credentials(self) -> None:
        self.set_up_openai()
        providers.set_choice("azure")
        self.assertIs(providers.active_provider(), azure_provider)
        self.assertFalse(providers.has_credentials())
        with self.assertRaises(azure_provider.MissingCredentialsError):
            providers.get_client()

    def test_invalid_choice_is_automatic(self) -> None:
        self.set_up_azure()
        providers.PROVIDER_FILE.write_text("bogus\n")
        self.assertIsNone(providers.get_choice())
        self.assertIs(providers.active_provider(), azure_provider)
        with self.assertRaises(ValueError):
            providers.set_choice("bogus")

    def test_client_rebuilt_when_provider_or_credentials_change(self) -> None:
        self.set_up_openai()
        self.set_up_azure()
        with mock.patch.object(
            azure_provider, "build_client", side_effect=lambda: object()
        ), mock.patch.object(openai_provider, "build_client", side_effect=lambda: object()):
            first = providers.get_client()
            self.assertIs(providers.get_client(), first)
            azure_provider.save_settings(ENDPOINT, "rotated-key", "")
            second = providers.get_client()
            self.assertIsNot(second, first)
            providers.set_choice("openai")
            self.assertIsNot(providers.get_client(), second)


class AzureSettingsTests(_IsolatedProviders):
    def test_save_settings_round_trip(self) -> None:
        self.set_up_azure("translate")
        self.assertEqual(azure_provider.get_endpoint(), ENDPOINT)
        self.assertEqual(azure_provider.get_api_key(), "azure-key")
        self.assertEqual(azure_provider.get_model(), "translate")
        self.assertEqual(azure_provider.endpoint_host(), "example.services.ai.azure.com")
        self.set_up_azure("")
        self.assertEqual(azure_provider.get_model(), config.DEFAULT_MODEL)

    def test_key_file_is_private_even_if_it_existed(self) -> None:
        azure_provider.API_KEY_FILE.write_text("old")
        azure_provider.API_KEY_FILE.chmod(0o644)
        self.set_up_azure()
        mode = stat.S_IMODE(azure_provider.API_KEY_FILE.stat().st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(azure_provider.API_KEY_FILE.read_text(), "azure-key")

    def test_openai_key_file_is_private(self) -> None:
        openai_provider.API_KEY_FILE.write_text("a much longer old key")
        openai_provider.API_KEY_FILE.chmod(0o644)
        self.set_up_openai()
        mode = stat.S_IMODE(openai_provider.API_KEY_FILE.stat().st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(openai_provider.API_KEY_FILE.read_text(), "sk-test")

    def test_save_settings_needs_endpoint_and_key(self) -> None:
        with self.assertRaises(ValueError):
            azure_provider.save_settings(ENDPOINT, " ", "")
        self.assertFalse(azure_provider.ENDPOINT_FILE.exists())

    def test_base_url_normalization(self) -> None:
        for endpoint in (
            ENDPOINT,
            ENDPOINT + "/",
            ENDPOINT + "/openai/v1",
            ENDPOINT + "/openai/v1/",
            ENDPOINT + "/api/projects/type-fast",
            ENDPOINT + "/api/projects/type-fast/",
        ):
            self.assertEqual(
                azure_provider._base_url(endpoint), ENDPOINT + "/openai/v1", endpoint
            )

    def test_malformed_endpoint_has_no_host(self) -> None:
        os.environ["AZURE_AI_ENDPOINT"] = "https://["
        self.assertEqual(azure_provider.endpoint_host(), "")

    def test_env_overrides_listed(self) -> None:
        self.assertEqual(azure_provider.env_overrides(), [])
        os.environ["AZURE_AI_ENDPOINT"] = ENDPOINT
        self.assertEqual(azure_provider.env_overrides(), ["AZURE_AI_ENDPOINT"])


@unittest.skipUnless(_HEADLESS, "set QT_QPA_PLATFORM=offscreen to run the headless window tests")
class WindowProviderTests(_IsolatedProviders):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        super().setUp()
        from type_fast import app

        self.app_module = app
        patcher = mock.patch.object(
            settings, "SETTINGS_FILE", Path(self.tmp.name) / "settings.json"
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        # Never start real translation threads.
        self.thread = mock.MagicMock()
        patcher = mock.patch.object(
            app, "threading", types.SimpleNamespace(Thread=self.thread)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_window(self):
        window = self.app_module.MainWindow()
        self.addCleanup(window.close)
        return window

    def checked_provider(self, window) -> str:
        return window.provider_group.checkedAction().data()

    def test_shows_active_provider(self) -> None:
        self.set_up_azure("translate")
        w = self.make_window()
        self.assertEqual(w.model_label.text(), "Azure \u00b7 translate")
        tip = w.model_label.toolTip()
        self.assertIn("Provider: Azure AI Foundry (chosen automatically)", tip)
        self.assertIn("Endpoint: example.services.ai.azure.com", tip)
        self.assertNotIn("azure-key", tip)
        self.assertEqual(self.checked_provider(w), "azure")
        self.assertEqual(w.status.text(), "")

    def test_missing_setup_status_names_the_provider(self) -> None:
        w = self.make_window()
        self.assertEqual(w.model_label.text(), f"OpenAI \u00b7 {config.DEFAULT_MODEL}")
        self.assertIn("Set OpenAI API Key", w.status.text())
        providers.set_choice("azure")
        w._reflect_provider()
        self.assertIn("Set Up Azure AI Foundry", w.status.text())
        self.assertEqual(self.checked_provider(w), "azure")

    def test_switching_saves_choice_and_retranslates(self) -> None:
        self.set_up_openai()
        self.set_up_azure()
        w = self.make_window()
        w.input.setPlainText("hello")
        w._retranslate()
        sent = self.thread.call_count
        w.provider_actions["openai"].trigger()
        self.assertEqual(providers.get_choice(), "openai")
        self.assertEqual(self.checked_provider(w), "openai")
        self.assertTrue(w.model_label.text().startswith("OpenAI \u00b7 "))
        self.assertIn("Provider: OpenAI\n", w.model_label.toolTip() + "\n")
        # Same model name, different provider: translated again.
        self.assertEqual(self.thread.call_count, sent + 1)

    def test_choosing_unconfigured_provider_cancelled_keeps_current(self) -> None:
        self.set_up_openai()
        w = self.make_window()
        with mock.patch.object(w, "_ask_azure_settings", return_value=None) as ask:
            w.provider_actions["azure"].trigger()
        ask.assert_called_once()
        self.assertIsNone(providers.get_choice())
        self.assertEqual(self.checked_provider(w), "openai")
        self.assertFalse(azure_provider.ENDPOINT_FILE.exists())

    def test_choosing_unconfigured_provider_sets_it_up_and_switches(self) -> None:
        self.set_up_openai()
        w = self.make_window()
        values = (ENDPOINT + "/api/projects/p", "azure-key", "translate")
        with mock.patch.object(w, "_ask_azure_settings", return_value=values), mock.patch.object(
            w, "_confirm_switch"
        ) as confirm:
            w.provider_actions["azure"].trigger()
        confirm.assert_not_called()
        self.assertEqual(providers.get_choice(), "azure")
        self.assertEqual(w.model_label.text(), "Azure \u00b7 translate")
        self.assertEqual(
            stat.S_IMODE(azure_provider.API_KEY_FILE.stat().st_mode), 0o600
        )

    def test_setting_up_other_provider_asks_before_switching(self) -> None:
        self.set_up_openai()
        w = self.make_window()
        values = (ENDPOINT, "azure-key", "")
        with mock.patch.object(w, "_ask_azure_settings", return_value=values), mock.patch.object(
            w, "_confirm_switch", return_value=False
        ) as confirm:
            w.set_up_azure_action.trigger()
        confirm.assert_called_once_with(azure_provider)
        # Declining keeps OpenAI, even though Foundry is now configured.
        self.assertEqual(providers.get_choice(), "openai")
        self.assertEqual(self.checked_provider(w), "openai")
        self.assertTrue(azure_provider.is_configured())
        with mock.patch.object(w, "_ask_azure_settings", return_value=values), mock.patch.object(
            w, "_confirm_switch", return_value=True
        ):
            w.set_up_azure_action.trigger()
        self.assertEqual(providers.get_choice(), "azure")
        self.assertEqual(self.checked_provider(w), "azure")

    def test_updating_active_provider_does_not_ask(self) -> None:
        self.set_up_azure()
        w = self.make_window()
        values = (ENDPOINT, "rotated-key", "translate")
        with mock.patch.object(w, "_ask_azure_settings", return_value=values), mock.patch.object(
            w, "_confirm_switch"
        ) as confirm:
            w.set_up_azure_action.trigger()
        confirm.assert_not_called()
        self.assertIsNone(providers.get_choice())
        self.assertEqual(w.model_label.text(), "Azure \u00b7 translate")

    def test_fixing_settings_resends_the_same_text(self) -> None:
        self.set_up_azure("translate")
        w = self.make_window()
        w.input.setPlainText("hello")
        w._retranslate()
        sent = self.thread.call_count
        w._retranslate()
        self.assertEqual(self.thread.call_count, sent)  # deduplicated
        values = (ENDPOINT, "rotated-key", "translate")
        with mock.patch.object(w, "_ask_azure_settings", return_value=values):
            w.set_up_azure_action.trigger()
        self.assertEqual(self.thread.call_count, sent + 1)

    def test_setup_dialog_keeps_saved_deployment(self) -> None:
        azure_provider.MODEL_FILE.write_text("translate", encoding="utf-8")
        w = self.make_window()
        dialog = mock.MagicMock()
        dialog.return_value.exec.return_value = 0
        with mock.patch.object(self.app_module, "AzureSetupDialog", dialog):
            self.assertIsNone(w._ask_azure_settings())
        self.assertEqual(dialog.call_args.args[2], "translate")

    def test_app_activation_picks_up_outside_changes(self) -> None:
        self.set_up_openai()
        w = self.make_window()
        self.assertEqual(self.checked_provider(w), "openai")
        self.set_up_azure("translate")
        providers.set_choice("azure")
        from PySide6.QtCore import Qt

        w._on_app_state_changed(Qt.ApplicationActive)
        self.assertEqual(self.checked_provider(w), "azure")
        self.assertEqual(w.model_label.text(), "Azure \u00b7 translate")

    def test_app_activation_retranslates_only_after_changes(self) -> None:
        from PySide6.QtCore import Qt

        self.set_up_azure("translate")
        w = self.make_window()
        w.input.setPlainText("hello")
        w._retranslate()
        sent = self.thread.call_count
        w._on_app_state_changed(Qt.ApplicationActive)
        self.assertEqual(self.thread.call_count, sent)  # nothing changed
        azure_provider.save_model("other")  # e.g. the setup script ran
        w._on_app_state_changed(Qt.ApplicationActive)
        self.assertEqual(self.thread.call_count, sent + 1)
        self.assertEqual(w.model_label.text(), "Azure \u00b7 other")

    def test_azure_dialog_validates_input(self) -> None:
        from PySide6.QtWidgets import QDialog

        dialog = self.app_module.AzureSetupDialog("", "", "", ["AZURE_AI_API_KEY"])
        self.addCleanup(dialog.close)
        dialog.endpoint_edit.setText("http://example.com")
        dialog.key_edit.setText("k")
        dialog.accept()
        self.assertNotEqual(dialog.result(), QDialog.Accepted)
        self.assertIn("https://", dialog.error_label.text())
        for bad in (ENDPOINT + "?api-version=2024-10-21", ENDPOINT + "#keys"):
            dialog.endpoint_edit.setText(bad)
            dialog.accept()
            self.assertNotEqual(dialog.result(), QDialog.Accepted)
            self.assertIn("https://", dialog.error_label.text())
        dialog.endpoint_edit.setText(ENDPOINT)
        dialog.key_edit.setText("has space")
        dialog.accept()
        self.assertIn("API key", dialog.error_label.text())
        self.assertIn("API key", dialog.key_edit.accessibleDescription())
        self.assertEqual(dialog.endpoint_edit.accessibleDescription(), "")
        dialog.key_edit.setText(" azure-key ")
        dialog.model_edit.setText("translate")
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(
            (dialog.endpoint, dialog.api_key, dialog.model),
            (ENDPOINT, "azure-key", "translate"),
        )


if __name__ == "__main__":
    unittest.main()

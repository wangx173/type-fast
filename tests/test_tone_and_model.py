"""Unit tests for the tone prompt, tone settings, and model selection."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from type_fast import config, providers, settings, translator
from type_fast.providers import azure as azure_provider, openai as openai_provider


class SystemPromptTests(unittest.TestCase):
    def test_default_tone_is_polite(self) -> None:
        prompt = translator.system_prompt("English", "Japanese")
        self.assertIn(config.TONES[config.DEFAULT_TONE], prompt)

    def test_custom_tone_is_included(self) -> None:
        prompt = translator.system_prompt("auto", "English", "Sound like a pirate.")
        self.assertIn("Sound like a pirate.", prompt)
        self.assertNotIn(config.TONES[config.DEFAULT_TONE], prompt)

    def test_blank_tone_falls_back_to_default(self) -> None:
        prompt = translator.system_prompt("English", "Japanese", "   ")
        self.assertIn(config.TONES[config.DEFAULT_TONE], prompt)


class ToneSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(
            settings, "SETTINGS_FILE", Path(self.tmp.name) / "settings.json"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_defaults_when_missing(self) -> None:
        loaded = settings.load()
        self.assertEqual(loaded.tone, config.DEFAULT_TONE)
        self.assertEqual(loaded.instruction(), config.TONES[config.DEFAULT_TONE])

    def test_round_trip(self) -> None:
        settings.save(settings.Settings(tone="Casual", custom_tone="x"))
        loaded = settings.load()
        self.assertEqual(loaded.tone, "Casual")
        self.assertEqual(loaded.custom_tone, "x")
        self.assertEqual(loaded.instruction(), config.TONES["Casual"])

    def test_custom_tone_instruction(self) -> None:
        tone = settings.Settings(tone=config.CUSTOM_TONE, custom_tone=" Be terse. ")
        self.assertEqual(tone.instruction(), "Be terse.")

    def test_empty_custom_tone_falls_back(self) -> None:
        tone = settings.Settings(tone=config.CUSTOM_TONE, custom_tone="")
        self.assertEqual(tone.instruction(), config.TONES[config.DEFAULT_TONE])

    def test_invalid_file_falls_back(self) -> None:
        settings.SETTINGS_FILE.write_text("{not json", encoding="utf-8")
        self.assertEqual(settings.load().tone, config.DEFAULT_TONE)
        settings.SETTINGS_FILE.write_text('{"tone": "Bogus"}', encoding="utf-8")
        self.assertEqual(settings.load().tone, config.DEFAULT_TONE)
        for bad in ('{"tone": []}', '{"tone": {}}', '{"tone": 1, "custom_tone": []}', "[]"):
            settings.SETTINGS_FILE.write_text(bad, encoding="utf-8")
            loaded = settings.load()
            self.assertEqual(loaded.tone, config.DEFAULT_TONE, bad)
            self.assertEqual(loaded.custom_tone, "", bad)


class ModelSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for target, attr, name in [
            (openai_provider, "MODEL_FILE", "openai_model"),
            (openai_provider, "API_KEY_FILE", "api_key"),
            (azure_provider, "MODEL_FILE", "azure_ai_model"),
            (azure_provider, "ENDPOINT_FILE", "azure_ai_endpoint"),
            (azure_provider, "API_KEY_FILE", "azure_ai_api_key"),
            (providers, "PROVIDER_FILE", "provider"),
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

    def test_openai_default_model(self) -> None:
        self.assertEqual(providers.get_model(), config.DEFAULT_MODEL)
        self.assertIsNone(providers.model_env_override())

    def test_saved_model_is_used_and_blank_restores_default(self) -> None:
        providers.save_model("gpt-4.1")
        self.assertEqual(providers.get_model(), "gpt-4.1")
        providers.save_model("  ")
        self.assertFalse(openai_provider.MODEL_FILE.exists())
        self.assertEqual(providers.get_model(), config.DEFAULT_MODEL)

    def test_env_overrides_saved_model(self) -> None:
        providers.save_model("gpt-4.1")
        os.environ["OPENAI_MODEL"] = "gpt-4o"
        self.assertEqual(providers.get_model(), "gpt-4o")
        self.assertEqual(providers.model_env_override(), "OPENAI_MODEL")

    def test_azure_model_saved_when_azure_active(self) -> None:
        os.environ["AZURE_AI_ENDPOINT"] = "https://example.services.ai.azure.com"
        os.environ["AZURE_AI_API_KEY"] = "key"
        providers.save_model("my-deployment")
        self.assertEqual(azure_provider.MODEL_FILE.read_text(), "my-deployment")
        self.assertFalse(openai_provider.MODEL_FILE.exists())
        self.assertEqual(providers.get_model(), "my-deployment")


class TranslateStreamTests(unittest.TestCase):
    def _run(self, model: str) -> dict:
        stream_cm = mock.MagicMock()
        stream_cm.__enter__.return_value = iter(
            [mock.Mock(type="response.output_text.delta", delta="hi")]
        )
        client = mock.Mock()
        client.responses.stream.return_value = stream_cm
        with mock.patch.object(providers, "get_client", return_value=client):
            out = list(
                translator.translate_stream("hello", tone="Be casual.", model=model)
            )
        self.assertEqual(out, ["hi"])
        return client.responses.stream.call_args.kwargs

    def test_passes_model_tone_and_temperature(self) -> None:
        kwargs = self._run("gpt-4.1")
        self.assertEqual(kwargs["model"], "gpt-4.1")
        self.assertEqual(kwargs["temperature"], config.DEFAULT_TEMPERATURE)
        self.assertIn("Be casual.", kwargs["input"][0]["content"])

    def test_reasoning_models_omit_temperature(self) -> None:
        for model in ("gpt-5-mini", "o4-mini", "GPT-5"):
            self.assertNotIn("temperature", self._run(model))

    def test_uses_the_client_it_is_given(self) -> None:
        stream_cm = mock.MagicMock()
        stream_cm.__enter__.return_value = iter([])
        client = mock.Mock()
        client.responses.stream.return_value = stream_cm
        with mock.patch.object(
            providers, "get_client", side_effect=AssertionError("resolved again")
        ):
            list(translator.translate_stream("hello", model="m", client=client))
        client.responses.stream.assert_called_once()

    def test_retries_without_temperature_when_rejected(self) -> None:
        import openai

        # Build the error without an HTTP response object so the test does not
        # depend on the openai SDK's transport library.
        rejection = openai.BadRequestError.__new__(openai.BadRequestError)
        Exception.__init__(rejection, "Unsupported parameter: 'temperature'")
        def ok_cm() -> mock.MagicMock:
            cm = mock.MagicMock()
            cm.__enter__.return_value = iter(
                [mock.Mock(type="response.output_text.delta", delta="hi")]
            )
            return cm

        bad_cm = mock.MagicMock()
        bad_cm.__enter__.side_effect = rejection
        client = mock.Mock()
        client.responses.stream.side_effect = [bad_cm, ok_cm(), ok_cm()]
        self.addCleanup(translator._models_without_temperature.clear)
        with mock.patch.object(providers, "get_client", return_value=client):
            first = list(translator.translate_stream("hello", model="my-deploy"))
            second = list(translator.translate_stream("hello", model="my-deploy"))
        self.assertEqual(first, ["hi"])
        self.assertEqual(second, ["hi"])
        calls = client.responses.stream.call_args_list
        self.assertIn("temperature", calls[0].kwargs)
        self.assertNotIn("temperature", calls[1].kwargs)
        self.assertNotIn("temperature", calls[2].kwargs)  # remembered

    def test_no_retry_when_cancelled(self) -> None:
        import openai

        rejection = openai.BadRequestError.__new__(openai.BadRequestError)
        Exception.__init__(rejection, "Unsupported parameter: 'temperature'")
        bad_cm = mock.MagicMock()
        bad_cm.__enter__.side_effect = rejection
        client = mock.Mock()
        client.responses.stream.return_value = bad_cm
        self.addCleanup(translator._models_without_temperature.clear)
        with mock.patch.object(providers, "get_client", return_value=client):
            out = list(
                translator.translate_stream(
                    "hello", model="my-deploy", should_cancel=lambda: True
                )
            )
        self.assertEqual(out, [])
        self.assertEqual(client.responses.stream.call_count, 1)


if __name__ == "__main__":
    unittest.main()

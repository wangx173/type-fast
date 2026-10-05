"""Unit tests for the tone prompt, tone settings, and model selection."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Optional
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
        self.assertEqual(providers.get_model(), config.DEFAULT_OPENAI_MODEL)
        self.assertIsNone(providers.model_env_override())

    def test_saved_model_is_used_and_blank_restores_default(self) -> None:
        providers.save_model("gpt-4.1")
        self.assertEqual(providers.get_model(), "gpt-4.1")
        providers.save_model("  ")
        self.assertFalse(openai_provider.MODEL_FILE.exists())
        self.assertEqual(providers.get_model(), config.DEFAULT_OPENAI_MODEL)

    def test_env_overrides_saved_model(self) -> None:
        providers.save_model("gpt-4.1")
        os.environ["OPENAI_MODEL"] = "gpt-4o"
        self.assertEqual(providers.get_model(), "gpt-4o")
        self.assertEqual(providers.model_env_override(), "OPENAI_MODEL")

    def test_defaults_are_per_provider(self) -> None:
        self.assertEqual(config.DEFAULT_OPENAI_MODEL, "gpt-5.4-mini")
        self.assertEqual(config.MODEL_CHOICES[0], config.DEFAULT_OPENAI_MODEL)
        # Foundry keeps the deployment name its setup script and guide create.
        self.assertEqual(config.DEFAULT_AZURE_MODEL, "gpt-4.1-mini")
        self.assertEqual(azure_provider.get_model(), config.DEFAULT_AZURE_MODEL)

    def test_azure_model_saved_when_azure_active(self) -> None:
        os.environ["AZURE_AI_ENDPOINT"] = "https://example.services.ai.azure.com"
        os.environ["AZURE_AI_API_KEY"] = "key"
        providers.save_model("my-deployment")
        self.assertEqual(azure_provider.MODEL_FILE.read_text(), "my-deployment")
        self.assertFalse(openai_provider.MODEL_FILE.exists())
        self.assertEqual(providers.get_model(), "my-deployment")


class ReasoningEffortTests(unittest.TestCase):
    def test_fastest_supported_effort(self) -> None:
        cases = {
            "gpt-5.4-mini": "none",
            "GPT-5.4-Nano": "none",
            "gpt-5.6-luna": "none",
            "gpt-5.5": "none",
            "gpt-5.1": "none",
            "gpt-6-luna": "none",
            "gpt-6-sol": "none",
            "gpt-6-astra": "low",  # doesn't support "none"
            "gpt-6.1-sol": "low",
        }
        for model, effort in cases.items():
            self.assertEqual(config.reasoning_effort(model), effort, model)

    def test_other_models_send_no_effort(self) -> None:
        for model in ("gpt-4.1-mini", "gpt-4o", "gpt-5", "gpt-5-mini", "o4-mini", "translate"):
            self.assertIsNone(config.reasoning_effort(model), model)

    def test_temperature_only_without_reasoning(self) -> None:
        self.assertTrue(config.supports_temperature("gpt-5.4-mini", "none"))
        self.assertFalse(config.supports_temperature("gpt-6-astra", "low"))
        self.assertFalse(config.supports_temperature("gpt-6-luna"))
        self.assertTrue(config.supports_temperature("gpt-4.1-mini"))


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

    def test_non_reasoning_models_send_no_reasoning(self) -> None:
        for model in ("gpt-4.1", "gpt-5-mini", "my-deploy"):
            self.assertNotIn("reasoning", self._run(model))

    def test_newer_models_turn_reasoning_off(self) -> None:
        for model in ("gpt-5.4-mini", "gpt-6-luna"):
            kwargs = self._run(model)
            self.assertEqual(kwargs["reasoning"], {"effort": "none"})
            self.assertEqual(kwargs["temperature"], config.DEFAULT_TEMPERATURE)

    def test_models_without_none_use_low_effort(self) -> None:
        kwargs = self._run("gpt-6-astra")
        self.assertEqual(kwargs["reasoning"], {"effort": "low"})
        self.assertNotIn("temperature", kwargs)

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

    def test_superseded_before_start_sends_nothing(self) -> None:
        client = mock.Mock()
        out = list(
            translator.translate_stream(
                "hello", model="m", client=client, should_cancel=lambda: True
            )
        )
        self.assertEqual(out, [])
        client.responses.stream.assert_not_called()

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

    @staticmethod
    def _rejection(message: str, param: Optional[str] = None) -> Exception:
        import openai

        error = openai.BadRequestError.__new__(openai.BadRequestError)
        Exception.__init__(error, message)
        error.param = param
        return error

    @staticmethod
    def _ok_cm() -> mock.MagicMock:
        cm = mock.MagicMock()
        cm.__enter__.return_value = iter(
            [mock.Mock(type="response.output_text.delta", delta="hi")]
        )
        return cm

    def _bad_cm(self, message: str, param: Optional[str] = None) -> mock.MagicMock:
        cm = mock.MagicMock()
        cm.__enter__.side_effect = self._rejection(message, param)
        return cm

    def test_reasoning_rejection_is_recognized_by_its_param(self) -> None:
        # The API names the field in ``param``; the message may not mention it.
        client = mock.Mock()
        client.responses.stream.side_effect = [
            self._bad_cm(
                "Unsupported value: 'none' is not supported with the "
                "'gpt-6-sol-pro' model.",
                param="reasoning.effort",
            ),
            self._ok_cm(),
        ]
        self.addCleanup(translator._reasoning_fallbacks.clear)
        self.addCleanup(translator._models_without_temperature.clear)
        with mock.patch.object(providers, "get_client", return_value=client):
            out = list(translator.translate_stream("hello", model="gpt-6-sol-pro"))
        self.assertEqual(out, ["hi"])
        retry = client.responses.stream.call_args_list[1].kwargs
        self.assertEqual(retry["reasoning"], {"effort": "low"})
        self.assertNotIn("temperature", retry)

    def test_param_takes_precedence_over_the_message(self) -> None:
        import openai

        client = mock.Mock()
        client.responses.stream.return_value = self._bad_cm(
            "Input is too long for this temperature setting", param="input"
        )
        with mock.patch.object(providers, "get_client", return_value=client):
            with self.assertRaises(openai.BadRequestError):
                list(translator.translate_stream("hello", model="gpt-5.4-mini"))
        self.assertEqual(client.responses.stream.call_count, 1)

    def test_falls_back_to_low_effort_and_remembers_it(self) -> None:
        client = mock.Mock()
        client.responses.stream.side_effect = [
            self._bad_cm("Unsupported value: 'reasoning.effort' does not support 'none'"),
            self._ok_cm(),
            self._ok_cm(),
        ]
        self.addCleanup(translator._reasoning_fallbacks.clear)
        self.addCleanup(translator._models_without_temperature.clear)
        with mock.patch.object(providers, "get_client", return_value=client):
            first = list(translator.translate_stream("hello", model="gpt-5.4-pro"))
            second = list(translator.translate_stream("hello", model="gpt-5.4-pro"))
        self.assertEqual(first, ["hi"])
        self.assertEqual(second, ["hi"])
        calls = client.responses.stream.call_args_list
        self.assertEqual(calls[0].kwargs["reasoning"], {"effort": "none"})
        self.assertIn("temperature", calls[0].kwargs)
        # With reasoning on, the model gets no temperature either.
        for call in calls[1:]:
            self.assertEqual(call.kwargs["reasoning"], {"effort": "low"})
            self.assertNotIn("temperature", call.kwargs)

    def test_retries_without_reasoning_when_low_is_rejected_too(self) -> None:
        client = mock.Mock()
        client.responses.stream.side_effect = [
            self._bad_cm("Unsupported value: 'none'", param="reasoning.effort"),
            self._bad_cm("Unsupported value: 'low'", param="reasoning.effort"),
            self._ok_cm(),
            self._ok_cm(),
        ]
        self.addCleanup(translator._reasoning_fallbacks.clear)
        self.addCleanup(translator._models_without_temperature.clear)
        with mock.patch.object(providers, "get_client", return_value=client):
            first = list(translator.translate_stream("hello", model="gpt-5.4-pro"))
            second = list(translator.translate_stream("hello", model="gpt-5.4-pro"))
        self.assertEqual(first, ["hi"])
        self.assertEqual(second, ["hi"])
        calls = client.responses.stream.call_args_list
        self.assertEqual(calls[1].kwargs["reasoning"], {"effort": "low"})
        for call in calls[2:]:  # back at its default effort, and remembered
            self.assertNotIn("reasoning", call.kwargs)
            self.assertNotIn("temperature", call.kwargs)

    def test_unsupported_reasoning_setting_is_dropped_without_trying_low(self) -> None:
        client = mock.Mock()
        client.responses.stream.side_effect = [
            self._bad_cm("Unsupported parameter: 'reasoning'", param="reasoning"),
            self._ok_cm(),
        ]
        self.addCleanup(translator._reasoning_fallbacks.clear)
        self.addCleanup(translator._models_without_temperature.clear)
        with mock.patch.object(providers, "get_client", return_value=client):
            list(translator.translate_stream("hello", model="gpt-5.4-mini"))
        self.assertNotIn("reasoning", client.responses.stream.call_args_list[1].kwargs)

    def test_rejections_are_remembered_per_endpoint(self) -> None:
        foundry = mock.Mock(base_url="https://foundry.example/openai/v1/")
        foundry.responses.stream.side_effect = [
            self._bad_cm("Unsupported value", param="reasoning.effort"),
            self._ok_cm(),
        ]
        openai_client = mock.Mock(base_url="https://api.openai.com/v1/")
        openai_client.responses.stream.return_value = self._ok_cm()
        self.addCleanup(translator._reasoning_fallbacks.clear)
        self.addCleanup(translator._models_without_temperature.clear)
        list(translator.translate_stream("hello", model="gpt-5.4-mini", client=foundry))
        list(
            translator.translate_stream("hello", model="gpt-5.4-mini", client=openai_client)
        )
        sent = openai_client.responses.stream.call_args.kwargs
        self.assertEqual(sent["reasoning"], {"effort": "none"})
        self.assertIn("temperature", sent)

    def test_retries_are_bounded(self) -> None:
        import openai

        client = mock.Mock()
        client.responses.stream.side_effect = [
            self._bad_cm("Unsupported parameter", param="temperature"),
            self._bad_cm("Unsupported value", param="reasoning.effort"),
            self._bad_cm("Unsupported value", param="reasoning.effort"),
            self._bad_cm("Unsupported parameter", param="reasoning"),
            self._ok_cm(),
        ]
        self.addCleanup(translator._reasoning_fallbacks.clear)
        self.addCleanup(translator._models_without_temperature.clear)
        with mock.patch.object(providers, "get_client", return_value=client):
            with self.assertRaises(openai.BadRequestError):
                list(translator.translate_stream("hello", model="gpt-5.4-pro"))
        self.assertEqual(client.responses.stream.call_count, 4)

    def test_no_retry_when_cancelled_after_reasoning_rejection(self) -> None:
        client = mock.Mock()
        client.responses.stream.return_value = self._bad_cm(
            "Unsupported value", param="reasoning.effort"
        )
        self.addCleanup(translator._reasoning_fallbacks.clear)
        cancel = iter([False])
        with mock.patch.object(providers, "get_client", return_value=client):
            out = list(
                translator.translate_stream(
                    "hello", model="gpt-6-astra", should_cancel=lambda: next(cancel, True)
                )
            )
        self.assertEqual(out, [])
        self.assertEqual(client.responses.stream.call_count, 1)

    def test_temperature_error_is_checked_before_reasoning(self) -> None:
        client = mock.Mock()
        client.responses.stream.side_effect = [
            self._bad_cm("'temperature' is not supported with this reasoning setting"),
            self._ok_cm(),
        ]
        self.addCleanup(translator._reasoning_fallbacks.clear)
        self.addCleanup(translator._models_without_temperature.clear)
        with mock.patch.object(providers, "get_client", return_value=client):
            out = list(translator.translate_stream("hello", model="gpt-6-luna"))
        self.assertEqual(out, ["hi"])
        retry = client.responses.stream.call_args_list[1].kwargs
        self.assertNotIn("temperature", retry)
        self.assertEqual(retry["reasoning"], {"effort": "none"})

    def test_unrelated_errors_are_not_retried(self) -> None:
        import openai

        client = mock.Mock()
        client.responses.stream.return_value = self._bad_cm("Invalid model")
        with mock.patch.object(providers, "get_client", return_value=client):
            with self.assertRaises(openai.BadRequestError):
                list(translator.translate_stream("hello", model="gpt-5.4-mini"))
        self.assertEqual(client.responses.stream.call_count, 1)

    def test_no_retry_when_cancelled(self) -> None:
        import openai

        rejection = openai.BadRequestError.__new__(openai.BadRequestError)
        Exception.__init__(rejection, "Unsupported parameter: 'temperature'")
        bad_cm = mock.MagicMock()
        bad_cm.__enter__.side_effect = rejection
        client = mock.Mock()
        client.responses.stream.return_value = bad_cm
        self.addCleanup(translator._models_without_temperature.clear)
        # Superseded after the first attempt was sent, before the retry.
        cancel = iter([False])
        with mock.patch.object(providers, "get_client", return_value=client):
            out = list(
                translator.translate_stream(
                    "hello", model="my-deploy", should_cancel=lambda: next(cancel, True)
                )
            )
        self.assertEqual(out, [])
        self.assertEqual(client.responses.stream.call_count, 1)


if __name__ == "__main__":
    unittest.main()

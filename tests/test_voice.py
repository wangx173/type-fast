"""Unit tests for voice input, Auto tone detection, and input clean-up."""

from __future__ import annotations

import array
import io
import json
import os
import tempfile
import types
import unittest
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from unittest import mock

import openai

from type_fast import config, providers, settings, translator
from type_fast.providers import azure as azure_provider, openai as openai_provider

if TYPE_CHECKING:
    from type_fast.app import MainWindow

_HEADLESS = os.environ.get("QT_QPA_PLATFORM") == "offscreen"


def _isolate_provider_state(test: unittest.TestCase, root: Path) -> None:
    """Point provider files at ``root`` and hide OPENAI_*/AZURE_AI_* env vars."""
    for target, attr, name in [
        (openai_provider, "MODEL_FILE", "openai_model"),
        (openai_provider, "API_KEY_FILE", "api_key"),
        (openai_provider, "TRANSCRIBE_MODEL_FILE", "openai_transcribe_model"),
        (azure_provider, "MODEL_FILE", "azure_ai_model"),
        (azure_provider, "ENDPOINT_FILE", "azure_ai_endpoint"),
        (azure_provider, "API_KEY_FILE", "azure_ai_api_key"),
        (azure_provider, "TRANSCRIBE_MODEL_FILE", "azure_ai_transcribe_model"),
        (providers, "PROVIDER_FILE", "provider"),
    ]:
        patcher = mock.patch.object(target, attr, root / name)
        patcher.start()
        test.addCleanup(patcher.stop)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("OPENAI_", "AZURE_AI_"))
    }
    patcher = mock.patch.dict(os.environ, env, clear=True)
    patcher.start()
    test.addCleanup(patcher.stop)


def _pcm(*samples: int) -> bytes:
    return array.array("h", samples).tobytes()


def _api_error(cls: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    # Build the error without an HTTP response object so the test does not
    # depend on the openai SDK's transport library.
    error = cls.__new__(cls)
    Exception.__init__(error, "nope")
    error.message = "nope"
    error.status_code = status
    return error


class SystemPromptTests(unittest.TestCase):
    def test_auto_tone_lists_presets_and_asks_for_tag(self) -> None:
        prompt = translator.system_prompt("English", "Japanese", auto_tone=True)
        for name, instruction in config.TONES.items():
            self.assertIn(f"{name}: {instruction}", prompt)
        self.assertIn(translator.TONE_TAG_EXAMPLE, prompt)
        self.assertNotIn("Tone for the translation:", prompt)

    def test_auto_tone_ignores_explicit_tone(self) -> None:
        prompt = translator.system_prompt(
            "English", "Japanese", "Pirate speak.", auto_tone=True
        )
        self.assertNotIn("Pirate speak.", prompt)

    def test_optimize_adds_clean_up_instruction(self) -> None:
        for auto in (False, True):
            prompt = translator.system_prompt(
                "English", "Japanese", auto_tone=auto, optimize=True
            )
            self.assertIn(config.OPTIMIZE_INSTRUCTION, prompt)

    def test_defaults_are_unchanged(self) -> None:
        prompt = translator.system_prompt("English", "Japanese")
        self.assertNotIn(config.OPTIMIZE_INSTRUCTION, prompt)
        self.assertNotIn(translator.TONE_TAG_EXAMPLE, prompt)
        self.assertIn(config.TONES[config.DEFAULT_TONE], prompt)


class ToneTagTests(unittest.TestCase):
    def _strip(self, chunks: list[str]) -> tuple[list[str], list[str]]:
        tones: list[str] = []
        out = list(translator._strip_tone_tag(iter(chunks), tones.append))
        return out, tones

    def test_whole_tag_in_one_chunk(self) -> None:
        out, tones = self._strip(["[Tone: Business]\nこんにちは"])
        self.assertEqual("".join(out), "こんにちは")
        self.assertEqual(tones, ["Business"])

    def test_tag_split_across_chunks(self) -> None:
        chunks = ["[", "To", "ne:", " Cas", "ual", "]", "\n", "やあ", "！"]
        out, tones = self._strip(chunks)
        self.assertEqual("".join(out), "やあ！")
        self.assertEqual(tones, ["Casual"])

    def test_tag_never_leaks_into_any_chunk(self) -> None:
        text = "[Tone: Polite]\nお世話になっております。"
        for size in range(1, len(text) + 1):
            chunks = [text[i:i + size] for i in range(0, len(text), size)]
            out, tones = self._strip(chunks)
            with self.subTest(size=size):
                self.assertTrue(all("[" not in c and "Tone" not in c for c in out))
                self.assertEqual("".join(out), "お世話になっております。")
                self.assertEqual(tones, ["Polite"])

    def test_missing_tag_passes_text_through(self) -> None:
        out, tones = self._strip(["Bonjour", " à tous"])
        self.assertEqual("".join(out), "Bonjour à tous")
        self.assertEqual(tones, [])

    def test_bracketed_text_that_is_not_a_tag_is_kept(self) -> None:
        out, tones = self._strip(["[", "To", "do] list"])
        self.assertEqual("".join(out), "[Todo] list")
        self.assertEqual(tones, [])

    def test_unfinished_tag_at_end_is_kept(self) -> None:
        out, tones = self._strip(["[Tone: Bus"])
        self.assertEqual("".join(out), "[Tone: Bus")
        self.assertEqual(tones, [])

    def test_tag_only_yields_nothing(self) -> None:
        out, tones = self._strip(["[Tone: Tech]", "\n"])
        self.assertEqual("".join(out), "")
        self.assertEqual(tones, ["Tech"])

    def test_name_is_normalized_to_preset(self) -> None:
        _, tones = self._strip(["[tone: business]\nx"])
        self.assertEqual(tones, ["Business"])
        _, tones = self._strip(["[TONE:  friendly ]x"])
        self.assertEqual(tones, ["Friendly"])

    def test_translate_stream_strips_tag_only_in_auto_mode(self) -> None:
        def run(auto: bool) -> tuple[str, list[str], dict]:
            stream_cm = mock.MagicMock()
            stream_cm.__enter__.return_value = iter(
                [
                    mock.Mock(type="response.output_text.delta", delta=d)
                    for d in ("[Tone: Business]", "\nHi")
                ]
            )
            client = mock.Mock()
            client.responses.stream.return_value = stream_cm
            tones: list[str] = []
            out = "".join(
                translator.translate_stream(
                    "hello", model="gpt-4.1-mini", client=client,
                    auto_tone=auto, optimize=True, on_tone=tones.append,
                )
            )
            return out, tones, client.responses.stream.call_args.kwargs

        out, tones, kwargs = run(True)
        self.assertEqual(out, "Hi")
        self.assertEqual(tones, ["Business"])
        self.assertIn(translator.TONE_TAG_EXAMPLE, kwargs["input"][0]["content"])
        self.assertIn(config.OPTIMIZE_INSTRUCTION, kwargs["input"][0]["content"])
        out, tones, _ = run(False)
        self.assertEqual(out, "[Tone: Business]\nHi")
        self.assertEqual(tones, [])


class VoiceSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "settings.json"
        patcher = mock.patch.object(settings, "SETTINGS_FILE", self.file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_defaults(self) -> None:
        prefs = settings.load()
        self.assertEqual(prefs.voice_input, config.DEFAULT_VOICE_INPUT)
        self.assertEqual(prefs.optimize_voice, config.DEFAULT_OPTIMIZE_VOICE)
        self.assertEqual(prefs.optimize_typed, config.DEFAULT_OPTIMIZE_TYPED)

    def test_round_trip(self) -> None:
        prefs = settings.load()
        prefs.tone = config.AUTO_TONE
        prefs.voice_input = False
        prefs.optimize_voice = False
        prefs.optimize_typed = True
        settings.save(prefs)
        loaded = settings.load()
        self.assertEqual(loaded.tone, config.AUTO_TONE)
        self.assertFalse(loaded.voice_input)
        self.assertFalse(loaded.optimize_voice)
        self.assertTrue(loaded.optimize_typed)
        self.assertEqual(loaded.instruction(), config.AUTO_TONE_INSTRUCTION)

    def test_invalid_values_fall_back_to_defaults(self) -> None:
        self.file.write_text(
            json.dumps(
                {"voice_input": "yes", "optimize_voice": 1, "optimize_typed": None}
            ),
            encoding="utf-8",
        )
        prefs = settings.load()
        self.assertEqual(prefs.voice_input, config.DEFAULT_VOICE_INPUT)
        self.assertEqual(prefs.optimize_voice, config.DEFAULT_OPTIMIZE_VOICE)
        self.assertEqual(prefs.optimize_typed, config.DEFAULT_OPTIMIZE_TYPED)


class TranscribeModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        _isolate_provider_state(self, Path(self.tmp.name))

    def test_default_save_clear_and_env_override(self) -> None:
        for provider in (openai_provider, azure_provider):
            with self.subTest(provider=provider.NAME):
                self.assertEqual(
                    provider.get_transcribe_model(), config.DEFAULT_TRANSCRIBE_MODEL
                )
                provider.save_transcribe_model("whisper")
                self.assertEqual(provider.get_transcribe_model(), "whisper")
                with mock.patch.dict(os.environ, {provider.TRANSCRIBE_MODEL_ENV: "env-stt"}):
                    self.assertEqual(provider.get_transcribe_model(), "env-stt")
                provider.save_transcribe_model("  ")
                self.assertEqual(
                    provider.get_transcribe_model(), config.DEFAULT_TRANSCRIBE_MODEL
                )

    def test_active_provider_model(self) -> None:
        openai_provider.save_transcribe_model("whisper-1")
        with mock.patch.object(providers, "active_provider", return_value=openai_provider):
            self.assertEqual(providers.get_transcribe_model(), "whisper-1")


class AudioHelperTests(unittest.TestCase):
    def test_pcm_to_wav(self) -> None:
        from type_fast import voice

        pcm = _pcm(0, 1000, -1000, 0)
        data = voice.pcm_to_wav(pcm, 16000)
        with wave.open(io.BytesIO(data)) as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), 16000)
            self.assertEqual(wav.readframes(4), pcm)

    def test_is_silent(self) -> None:
        from type_fast import voice

        self.assertTrue(voice.is_silent(b""))
        self.assertTrue(voice.is_silent(_pcm(0, 0, 0)))
        self.assertTrue(voice.is_silent(_pcm(10, -64, 30)))
        self.assertFalse(voice.is_silent(_pcm(0, 2000, 0)))
        self.assertFalse(voice.is_silent(_pcm(0, -2000, 0)))

    def test_recording_seconds(self) -> None:
        from type_fast import voice

        self.assertEqual(voice.Recording(_pcm(*([0] * 16000)), 16000, 1).seconds, 1.0)
        self.assertEqual(voice.Recording(b"", 0, 1).seconds, 0.0)

    def test_to_int16(self) -> None:
        from PySide6.QtMultimedia import QAudioFormat

        from type_fast import voice

        fmt = QAudioFormat.SampleFormat
        pcm = _pcm(1, -2, 3)
        self.assertEqual(voice.to_int16(pcm + b"\x00", fmt.Int16), pcm)
        self.assertEqual(
            voice.to_int16(bytes([128, 255, 0]), fmt.UInt8), _pcm(0, 127 << 8, -32768)
        )
        self.assertEqual(
            voice.to_int16(array.array("i", [1 << 16, -(1 << 16)]).tobytes(), fmt.Int32),
            _pcm(1, -1),
        )
        self.assertEqual(
            voice.to_int16(array.array("f", [0.0, 1.0, -2.0]).tobytes(), fmt.Float),
            _pcm(0, 32767, -32767),
        )
        with self.assertRaises(voice.VoiceError):
            voice.to_int16(b"", fmt.Unknown)

    def test_downsample(self) -> None:
        from PySide6.QtMultimedia import QAudioFormat

        from type_fast import voice

        fmt = QAudioFormat.SampleFormat
        # 48 kHz stereo: keep the left channel of every third frame.
        frames = [(i, -i) for i in range(9)]
        stereo = _pcm(*(s for frame in frames for s in frame))
        self.assertEqual(
            voice.downsample(stereo, fmt.Int16, 48000, 2), (_pcm(0, 3, 6), 16000, 1)
        )
        # 44.1 kHz float mono: every second sample, at 22.05 kHz.
        floats = array.array("f", [0.0, 0.5, 1.0, -1.0]).tobytes()
        data, rate, channels = voice.downsample(floats, fmt.Float, 44100, 1)
        self.assertEqual((rate, channels), (22050, 1))
        self.assertEqual(voice.to_int16(data, fmt.Float), _pcm(0, 32767))
        # 16 kHz mono and unknown formats are left alone.
        pcm = _pcm(1, 2, 3)
        self.assertEqual(voice.downsample(pcm, fmt.Int16, 16000, 1), (pcm, 16000, 1))
        self.assertEqual(voice.downsample(b"xy", fmt.Unknown, 48000, 2), (b"xy", 48000, 2))

    def test_downsampled_long_recording_fits_upload_limit(self) -> None:
        from PySide6.QtMultimedia import QAudioFormat

        from type_fast import voice

        seconds = config.MAX_RECORDING_SECONDS
        raw = bytes(48000 * 2 * 4 * seconds)  # 48 kHz stereo float
        data, rate, channels = voice.downsample(
            raw, QAudioFormat.SampleFormat.Float, 48000, 2
        )
        self.assertEqual((rate, channels), (16000, 1))
        self.assertEqual(len(data), 16000 * 4 * seconds)


class TranscribeTests(unittest.TestCase):
    def setUp(self) -> None:
        from type_fast import voice

        self.voice = voice

    def test_sends_wav_language_and_prompt(self) -> None:
        client = mock.Mock()
        client.audio.transcriptions.create.return_value = mock.Mock(text=" Hello. ")
        text = self.voice.transcribe(
            client, "gpt-4o-transcribe", b"RIFF", language="en", prompt="Clean."
        )
        self.assertEqual(text, "Hello.")
        kwargs = client.audio.transcriptions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-4o-transcribe")
        self.assertEqual(kwargs["file"], ("speech.wav", b"RIFF", "audio/wav"))
        self.assertEqual(kwargs["language"], "en")
        self.assertEqual(kwargs["prompt"], "Clean.")

    def test_omits_unknown_language_and_prompt(self) -> None:
        client = mock.Mock()
        client.audio.transcriptions.create.return_value = mock.Mock(text="hi")
        self.voice.transcribe(client, "whisper-1", b"RIFF")
        kwargs = client.audio.transcriptions.create.call_args.kwargs
        self.assertNotIn("language", kwargs)
        self.assertNotIn("prompt", kwargs)

    def test_missing_azure_deployment_is_explained(self) -> None:
        client = mock.Mock()
        client.audio.transcriptions.create.side_effect = _api_error(
            openai.NotFoundError, 404
        )
        with self.assertRaises(self.voice.VoiceError) as ctx:
            self.voice.transcribe(client, "stt", b"RIFF", provider=azure_provider)
        message = str(ctx.exception)
        self.assertIn("speech-to-text deployment", message)
        self.assertIn("\u201cstt\u201d", message)
        self.assertIn(self.voice.TRANSCRIBE_MENU_PATH, message)

    def test_bad_openai_model_is_explained(self) -> None:
        client = mock.Mock()
        client.audio.transcriptions.create.side_effect = _api_error(
            openai.BadRequestError, 400
        )
        with self.assertRaises(self.voice.VoiceError) as ctx:
            self.voice.transcribe(client, "gpt-4.1", b"RIFF", provider=openai_provider)
        message = str(ctx.exception)
        self.assertIn("couldn't transcribe", message)
        self.assertIn("Choose a transcription model", message)

    def test_other_errors_propagate(self) -> None:
        client = mock.Mock()
        client.audio.transcriptions.create.side_effect = _api_error(
            openai.AuthenticationError, 401
        )
        with self.assertRaises(openai.AuthenticationError):
            self.voice.transcribe(client, "whisper-1", b"RIFF")


class _InlineThread:
    """Stand-in for threading.Thread that runs the target synchronously."""

    def __init__(
        self, target: Callable[..., None], args: tuple = (), daemon: bool = False
    ) -> None:
        self._target, self._args = target, args

    def start(self) -> None:
        self._target(*self._args)


class _FakeRecorder:
    def __init__(self, pcm: bytes = b"") -> None:
        self.recording = False
        self.pcm = pcm
        self.cancelled = False

    def start(self) -> None:
        self.recording = True

    def stop(self):  # noqa: ANN201 - returns voice.Recording
        from type_fast import voice

        self.recording = False
        return voice.Recording(self.pcm, 16000, 1)

    def cancel(self) -> None:
        self.recording = False
        self.cancelled = True


@unittest.skipUnless(_HEADLESS, "set QT_QPA_PLATFORM=offscreen to run the headless window tests")
class WindowVoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from type_fast import app  # deferred: imports Qt

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        patcher = mock.patch.object(settings, "SETTINGS_FILE", root / "settings.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        _isolate_provider_state(self, root)
        patcher = mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(
            providers, "get_client", return_value=mock.sentinel.client
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(
            app, "threading", types.SimpleNamespace(Thread=_InlineThread)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(app.QMessageBox, "warning")
        self.warnings = patcher.start()
        self.addCleanup(patcher.stop)
        self.calls: list[tuple] = []
        self.app_module = app

    def _window(self, pcm: bytes = _pcm(0, 3000, -3000)) -> MainWindow:
        window = self.app_module.MainWindow()
        self.addCleanup(window.close)
        window._translate_worker = lambda *args: self.calls.append(args)
        window.recorder = _FakeRecorder(pcm)
        window._reflect_voice()
        return window

    # _translate_worker(request_id, text, source, target, tone, model,
    #                   auto_tone, optimize, polish, client)

    def test_auto_is_the_first_tone(self) -> None:
        combo = self._window().tone
        self.assertEqual(combo.itemData(0), config.AUTO_TONE)
        self.assertEqual(combo.count(), len(config.TONES) + 2)

    def test_auto_tone_is_sent_and_persisted(self) -> None:
        w = self._window()
        w.input.setPlainText("Please review the attached report.")
        w.tone.activated.emit(w.tone.findData(config.AUTO_TONE))
        args = self.calls[-1]
        self.assertTrue(args[6])
        self.assertIs(args[-1], mock.sentinel.client)
        self.assertEqual(settings.load().tone, config.AUTO_TONE)
        self.assertEqual(w.pair_button.text(), "English \u2192 Japanese \u00b7 Auto")

    def test_detected_tone_is_shown_and_reset(self) -> None:
        w = self._window()
        w.tone.activated.emit(w.tone.findData(config.AUTO_TONE))
        w.input.setPlainText("Please review the attached report.")
        w.run_translation()
        w._on_tone_detected(w._request_id - 1, "Casual")  # stale: ignored
        self.assertEqual(w.tone.itemText(0), "Auto")
        w._on_tone_detected(w._request_id, "Business")
        self.assertEqual(w.tone.itemText(0), "Auto \u00b7 Business")
        self.assertIn("Auto \u00b7 Business", w.pair_button.text())
        self.assertIn("Detected: Business", w.tone.toolTip())
        w.input.clear()
        w.run_translation()  # what the debounce timer does
        self.assertEqual(w.tone.itemText(0), "Auto")
        self.assertEqual(w.pair_button.text(), "English \u2192 Japanese \u00b7 Auto")

    def test_detection_ignored_outside_auto(self) -> None:
        w = self._window()
        w.input.setPlainText("Hello there.")
        w.run_translation()
        w._on_tone_detected(w._request_id, "Business")
        self.assertEqual(w.pair_button.text(), "English \u2192 Japanese")

    def test_worker_reports_detected_tone(self) -> None:
        w = self.app_module.MainWindow()
        self.addCleanup(w.close)
        seen: list[tuple[int, str]] = []
        w.bridge.tone_detected.connect(lambda rid, name: seen.append((rid, name)))

        def fake_stream(*args: object, **kwargs: object):  # noqa: ANN202
            self.assertTrue(kwargs["auto_tone"])
            self.assertTrue(kwargs["optimize"])
            kwargs["on_tone"]("Tech")
            yield "ok"

        w._request_id = 7
        with mock.patch.object(self.app_module, "translate_stream", fake_stream):
            w._translate_worker(7, "hi", "English", "Japanese", "x", "m",
                                True, True, False, mock.sentinel.client)
        self.assertEqual(seen, [(7, "Tech")])

    def test_typed_input_is_not_cleaned_up_by_default(self) -> None:
        w = self._window()
        w.input.setPlainText("um so hello")
        w.run_translation()
        self.assertFalse(self.calls[-1][7])

    def test_optimize_typed_setting(self) -> None:
        w = self._window()
        w.optimize_typed_action.trigger()
        self.assertTrue(settings.load().optimize_typed)
        w.input.setPlainText("um so hello")
        w.run_translation()
        self.assertTrue(self.calls[-1][7])

    def test_record_transcribe_and_translate(self) -> None:
        w = self._window()
        w.input.setPlainText("Hello")
        w.input.moveCursor(w.input.textCursor().MoveOperation.End)
        with mock.patch.object(
            self.app_module.voice, "transcribe", return_value="how are you?"
        ) as transcribe:
            w.toggle_recording()
            self.assertTrue(w.recorder.recording)
            self.assertTrue(w.mic_button.isChecked())
            self.assertTrue(w.status.text().startswith("Listening"))
            self.assertEqual(w.record_action.text(), "Stop Recording")
            w.toggle_recording()
        args, kwargs = transcribe.call_args
        self.assertIs(args[0], mock.sentinel.client)
        self.assertEqual(args[1], config.DEFAULT_TRANSCRIBE_MODEL)
        self.assertTrue(args[2].startswith(b"RIFF"))
        self.assertEqual(kwargs["language"], "en")
        self.assertNotIn("prompt", kwargs)
        self.assertEqual(w.input.toPlainText(), "Hello how are you?")
        self.assertFalse(w.mic_button.isChecked())
        self.assertTrue(w.mic_button.isEnabled())
        self.assertEqual(w.status.text(), "Translating\u2026")
        args = self.calls[-1]
        self.assertEqual(args[1], "Hello how are you?")
        self.assertTrue(args[7])  # spoken input is cleaned up
        self.warnings.assert_not_called()

    def test_auto_source_sends_no_language_hint(self) -> None:
        w = self._window()
        w.prefs.source = config.AUTO_SOURCE
        with mock.patch.object(
            self.app_module.voice, "transcribe", return_value="hi"
        ) as transcribe:
            w.toggle_recording()
            w.toggle_recording()
        self.assertIsNone(transcribe.call_args.kwargs["language"])

    def test_silent_recording_shows_permission_hint(self) -> None:
        w = self._window(pcm=_pcm(0, 0, 0))
        with mock.patch.object(self.app_module.voice, "transcribe") as transcribe:
            w.toggle_recording()
            w.toggle_recording()
        transcribe.assert_not_called()
        self.assertIn(self.app_module.voice.PERMISSION_HINT, self.warnings.call_args.args)
        self.assertEqual(self.calls, [])

    def test_transcription_error_is_shown(self) -> None:
        w = self._window()
        with mock.patch.object(
            self.app_module.voice, "transcribe",
            side_effect=self.app_module.voice.VoiceError("no deployment"),
        ):
            w.toggle_recording()
            w.toggle_recording()
        self.assertIn("no deployment", self.warnings.call_args.args)
        self.assertFalse(w._transcribing)
        self.assertTrue(w.mic_button.isEnabled())

    def test_empty_transcript_does_not_translate(self) -> None:
        w = self._window()
        with mock.patch.object(self.app_module.voice, "transcribe", return_value=" "):
            w.toggle_recording()
            w.toggle_recording()
        self.assertEqual(w.input.toPlainText(), "")
        self.assertEqual(self.calls, [])
        self.assertEqual(w.status.text(), "No speech was recognized")

    def test_stale_transcript_is_dropped(self) -> None:
        w = self._window()
        w._voice_id = 3
        w._transcribing = True
        w._cancel_voice()
        w._on_transcribed(3, "late text")
        self.assertEqual(w.input.toPlainText(), "")
        self.assertFalse(w._transcribing)

    def test_dismiss_cancels_recording(self) -> None:
        w = self._window()
        w.toggle_recording()
        self.assertTrue(w.recorder.recording)
        w.dismiss()
        self.assertTrue(w.recorder.cancelled)
        self.assertFalse(w.mic_button.isChecked())
        self.assertEqual(w.status.text(), "")

    def test_hiding_or_minimizing_cancels_recording(self) -> None:
        from PySide6.QtCore import Qt

        w = self._window()
        w.show()
        w.toggle_recording()
        w.hide()  # e.g. ⌘W or another path that skips dismiss()
        self.assertTrue(w.recorder.cancelled)
        self.assertFalse(w.mic_button.isChecked())

        w.recorder = _FakeRecorder(_pcm(0, 3000))
        w.toggle_recording()
        w._on_app_state_changed(Qt.ApplicationHidden)  # ⌘H
        self.assertTrue(w.recorder.cancelled)

        w.recorder = _FakeRecorder(_pcm(0, 3000))
        w.show()
        w.toggle_recording()
        w.showMinimized()
        self.assertTrue(w.recorder.cancelled)

    def test_transcript_gets_spaces_around_it(self) -> None:
        w = self._window()
        w.input.setPlainText("Hello there")
        cursor = w.input.textCursor()
        cursor.setPosition(5)
        w.input.setTextCursor(cursor)
        w._insert_transcript("my friend")
        self.assertEqual(w.input.toPlainText(), "Hello my friend there")
        # Replacing a selected word keeps the neighbouring spaces single.
        w.input.setPlainText("Hello X there")
        cursor = w.input.textCursor()
        cursor.setPosition(6)
        cursor.setPosition(7, cursor.MoveMode.KeepAnchor)
        w.input.setTextCursor(cursor)
        w._insert_transcript("big")
        self.assertEqual(w.input.toPlainText(), "Hello big there")
        w.input.setPlainText("Hello,")
        w.input.moveCursor(w.input.textCursor().MoveOperation.Start)
        w._insert_transcript("Oh")
        self.assertEqual(w.input.toPlainText(), "Oh Hello,")

    def test_replacing_dictated_text_makes_input_typed(self) -> None:
        w = self._window()
        w._insert_transcript("um so hello")
        self.assertTrue(self.calls[-1][7])
        w.input.selectAll()
        w.input.insertPlainText("typed instead")  # before the debounce fires
        w.run_translation()
        self.assertFalse(self.calls[-1][7])

    def test_clearing_dictated_text_makes_input_typed(self) -> None:
        w = self._window()
        w._insert_transcript("um so hello")
        w.input.clear()
        w.input.insertPlainText("typed")  # before the debounce fires
        w.run_translation()
        self.assertFalse(self.calls[-1][7])

    def test_editing_around_dictated_text_keeps_it_spoken(self) -> None:
        w = self._window()
        w._insert_transcript("um so hello")
        w.input.moveCursor(w.input.textCursor().MoveOperation.End)
        w.input.insertPlainText(" there")
        w.run_translation()
        self.assertTrue(self.calls[-1][7])

    def test_permission_denied(self) -> None:
        w = self._window()
        with mock.patch.object(
            self.app_module.voice, "request_permission",
            side_effect=lambda ctx, cb: cb(False),
        ):
            w.toggle_recording()
        self.assertFalse(w.recorder.recording)
        self.assertIn(self.app_module.voice.PERMISSION_DENIED, self.warnings.call_args.args)

    def test_recording_needs_a_configured_provider(self) -> None:
        w = self._window()
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            w.toggle_recording()
        self.assertFalse(w.recorder.recording)
        self.assertTrue(w.status.text().startswith("No API key set"))

    def test_disabling_voice_input_hides_mic(self) -> None:
        w = self._window()
        self.assertFalse(w.mic_button.isHidden())
        self.assertEqual(w.mic_button.accessibleName(), "Voice input")
        w.toggle_recording()
        w.voice_input_action.trigger()
        self.assertFalse(settings.load().voice_input)
        self.assertTrue(w.recorder.cancelled)
        self.assertTrue(w.mic_button.isHidden())
        self.assertFalse(w.record_action.isEnabled())
        w.toggle_recording()
        self.assertFalse(w.recorder.recording)

    def test_set_openai_transcribe_model(self) -> None:
        w = self._window()
        with mock.patch.object(
            self.app_module.QInputDialog, "getItem", return_value=("whisper-1", True)
        ):
            w.set_transcribe_model_action.trigger()
        self.assertEqual(openai_provider.get_transcribe_model(), "whisper-1")

    def test_set_azure_transcribe_deployment_validates(self) -> None:
        w = self._window()
        answers = iter([("my stt", True), ("my-stt", True)])
        with mock.patch.object(
            providers, "active_provider", return_value=azure_provider
        ), mock.patch.object(
            self.app_module.QInputDialog, "getText", side_effect=lambda *a: next(answers)
        ):
            w._set_transcribe_model()
        self.warnings.assert_called_once()
        self.assertEqual(azure_provider.get_transcribe_model(), "my-stt")

    def test_pinned_transcribe_model_is_not_changed(self) -> None:
        w = self._window()
        with mock.patch.dict(os.environ, {"OPENAI_TRANSCRIBE_MODEL": "env-stt"}), \
                mock.patch.object(self.app_module.QMessageBox, "information") as info, \
                mock.patch.object(self.app_module.QInputDialog, "getItem") as get_item:
            w._set_transcribe_model()
        info.assert_called_once()
        get_item.assert_not_called()


if __name__ == "__main__":
    unittest.main()

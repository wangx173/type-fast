"""Voice input: record from the default microphone and transcribe the speech.

:class:`Recorder` captures 16 kHz mono 16-bit audio with Qt Multimedia (falling
back to the microphone's preferred format, reduced to one channel near 16 kHz
and converted to 16-bit, so long recordings stay small enough to upload), and
:func:`transcribe` sends it as a WAV file to the active provider's
speech-to-text model (``client.audio.transcriptions``), which works for both
OpenAI and Microsoft Azure AI Foundry deployments.

macOS asks for microphone access the first time the packaged app records; that
needs ``NSMicrophoneUsageDescription`` in the bundle's Info.plist (see
``Type Fast.spec``). When access is denied, macOS hands the app silent audio, so
a silent recording is reported with a hint to check the privacy settings.
"""

from __future__ import annotations

import array
import io
import sys
import wave
from dataclasses import dataclass
from types import ModuleType
from typing import Callable, Optional

import openai
from PySide6.QtCore import (
    QBuffer,
    QCoreApplication,
    QIODevice,
    QMicrophonePermission,
    QObject,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices, QtAudio

from . import config

SAMPLE_RATE = 16000
# Peak 16-bit amplitude at or below which a recording counts as silent. Real
# speech, even quiet, peaks far higher; denied access yields all zeros.
SILENCE_PEAK = 64

TRANSCRIBE_MENU_PATH = "Settings \u203a Voice Input \u203a Set Transcription Model\u2026"
PERMISSION_HINT = (
    "No sound was recorded. Check that Type Fast may use the microphone in "
    "System Settings \u203a Privacy & Security \u203a Microphone, and that the "
    "right input device is selected in System Settings \u203a Sound."
)
PERMISSION_DENIED = (
    "Type Fast doesn't have access to the microphone. Allow it in System "
    "Settings \u203a Privacy & Security \u203a Microphone, then try again."
)


class VoiceError(RuntimeError):
    """A recording or transcription problem with a message for the user."""


@dataclass
class Recording:
    """Raw 16-bit little-endian PCM audio."""

    pcm: bytes
    rate: int
    channels: int

    @property
    def seconds(self) -> float:
        frame = 2 * self.channels
        return len(self.pcm) / frame / self.rate if self.rate and frame else 0.0

    def wav(self) -> bytes:
        return pcm_to_wav(self.pcm, self.rate, self.channels)


def pcm_to_wav(pcm: bytes, rate: int, channels: int = 1, sample_width: int = 2) -> bytes:
    """Wrap raw PCM samples in a WAV container."""
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return out.getvalue()


def is_silent(pcm: bytes, peak: int = SILENCE_PEAK) -> bool:
    """Return True if 16-bit ``pcm`` never rises above ``peak`` (or is empty)."""
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if not samples:
        return True
    return max(max(samples), -min(samples)) <= peak


def to_int16(data: bytes, sample_format: QAudioFormat.SampleFormat) -> bytes:
    """Convert raw samples in ``sample_format`` to 16-bit little-endian PCM."""
    fmt = QAudioFormat.SampleFormat
    if sample_format == fmt.Int16:
        return data[: len(data) // 2 * 2]
    if sample_format == fmt.UInt8:
        out = array.array("h", ((b - 128) << 8 for b in data))
    elif sample_format == fmt.Int32:
        src = array.array("i")
        src.frombytes(data[: len(data) // 4 * 4])
        out = array.array("h", (s >> 16 for s in src))
    elif sample_format == fmt.Float:
        src = array.array("f")
        src.frombytes(data[: len(data) // 4 * 4])
        out = array.array(
            "h", (int(max(-1.0, min(1.0, s)) * 32767) for s in src)
        )
    else:
        raise VoiceError("The microphone uses an unsupported audio format.")
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


_TYPECODES = {
    QAudioFormat.SampleFormat.UInt8: "B",
    QAudioFormat.SampleFormat.Int16: "h",
    QAudioFormat.SampleFormat.Int32: "i",
    QAudioFormat.SampleFormat.Float: "f",
}


def downsample(
    data: bytes, sample_format: QAudioFormat.SampleFormat, rate: int, channels: int
) -> tuple[bytes, int, int]:
    """Reduce raw samples to one channel near :data:`SAMPLE_RATE`.

    Keeps the first channel and every n-th frame, where n is the whole number
    of times ``rate`` exceeds 16 kHz (48 kHz becomes 16 kHz, 44.1 kHz becomes
    22.05 kHz). That's plenty for speech and keeps a long recording well under
    the transcription upload limit. Returns ``(data, rate, channels)``.
    """
    channels = max(1, channels)
    factor = max(1, rate // SAMPLE_RATE)
    code = _TYPECODES.get(sample_format)
    if code is None or (channels == 1 and factor == 1):
        return data, rate, channels
    samples = array.array(code)
    samples.frombytes(data[: len(data) // samples.itemsize * samples.itemsize])
    return samples[:: channels * factor].tobytes(), rate // factor, 1


def request_permission(context: QObject, callback: Callable[[bool], None]) -> None:
    """Ask macOS for microphone access, then call ``callback(granted)``.

    Only the packaged app can ask: Qt refuses the request when the running
    executable's Info.plist lacks ``NSMicrophoneUsageDescription``, which is
    the case for ``python -m type_fast``. There the recording starts directly
    and macOS asks on behalf of the terminal app instead.
    """
    app = QCoreApplication.instance()
    if app is None or not getattr(sys, "frozen", False):
        callback(True)
        return
    permission = QMicrophonePermission()
    status = app.checkPermission(permission)
    if status == Qt.PermissionStatus.Granted:
        callback(True)
    elif status == Qt.PermissionStatus.Denied:
        callback(False)
    else:
        app.requestPermission(
            permission,
            context,
            lambda p: callback(app.checkPermission(p) == Qt.PermissionStatus.Granted),
        )


class Recorder(QObject):
    """Records the default microphone into memory until :meth:`stop`."""

    # Emitted when the recording reaches the length limit and stops by itself.
    limit_reached = Signal()

    def __init__(
        self, parent: Optional[QObject] = None,
        max_seconds: int = config.MAX_RECORDING_SECONDS,
    ) -> None:
        super().__init__(parent)
        self._source: Optional[QAudioSource] = None
        self._buffer: Optional[QBuffer] = None
        self._format = QAudioFormat()
        self._limit = QTimer(self)
        self._limit.setSingleShot(True)
        self._limit.setInterval(max_seconds * 1000)
        self._limit.timeout.connect(self.limit_reached)

    @property
    def recording(self) -> bool:
        return self._source is not None

    def start(self) -> None:
        """Start recording; raises :class:`VoiceError` if that isn't possible."""
        if self._source is not None:
            return
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            raise VoiceError(
                "No microphone found. Connect one or pick an input device in "
                "System Settings \u203a Sound."
            )
        fmt = QAudioFormat()
        fmt.setSampleRate(SAMPLE_RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
        self._format = fmt
        self._buffer = QBuffer(self)
        self._buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self._source = QAudioSource(device, fmt, self)
        self._source.start(self._buffer)
        if self._source.error() != QtAudio.Error.NoError:
            self._release()
            raise VoiceError(
                f"Couldn't open the microphone \u201c{device.description()}\u201d."
            )
        self._limit.start()

    def stop(self) -> Recording:
        """Stop recording and return the captured audio as 16-bit PCM."""
        if self._source is None or self._buffer is None:
            return Recording(b"", SAMPLE_RATE, 1)
        self._source.stop()
        data = bytes(self._buffer.data())
        fmt = self._format
        self._release()
        data, rate, channels = downsample(
            data,
            fmt.sampleFormat(),
            fmt.sampleRate() or SAMPLE_RATE,
            fmt.channelCount() or 1,
        )
        return Recording(to_int16(data, fmt.sampleFormat()), rate, channels)

    def cancel(self) -> None:
        """Stop recording and discard the audio."""
        if self._source is not None:
            self._source.stop()
        self._release()

    def _release(self) -> None:
        self._limit.stop()
        if self._source is not None:
            self._source.deleteLater()
            self._source = None
        if self._buffer is not None:
            self._buffer.close()
            self._buffer.deleteLater()
            self._buffer = None


def transcribe(
    client: openai.OpenAI,
    model: str,
    wav: bytes,
    *,
    language: Optional[str] = None,
    prompt: Optional[str] = None,
    provider: Optional[ModuleType] = None,
) -> str:
    """Transcribe ``wav`` audio with ``model`` and return the text.

    Args:
        client: Client of the provider to use.
        model: Speech-to-text model, or the Foundry deployment name.
        wav: The audio as a WAV file.
        language: Optional ISO-639-1 code of the spoken language.
        prompt: Optional style guide for the transcript.
        provider: The provider module behind ``client``, used to word errors.

    Raises:
        VoiceError: If the model or deployment can't transcribe audio.
    """
    params: dict[str, object] = {}
    if language:
        params["language"] = language
    if prompt:
        params["prompt"] = prompt
    try:
        result = client.audio.transcriptions.create(
            model=model, file=("speech.wav", wav, "audio/wav"), **params
        )
    except (openai.NotFoundError, openai.BadRequestError) as exc:
        raise VoiceError(_model_problem(model, provider, exc)) from exc
    text = getattr(result, "text", result)
    return str(text or "").strip()


def _model_problem(
    model: str, provider: Optional[ModuleType], exc: openai.APIStatusError
) -> str:
    name = getattr(provider, "DISPLAY_NAME", "The provider")
    is_azure = getattr(provider, "NAME", "") == "azure"
    kind = "speech-to-text deployment" if is_azure else "speech-to-text model"
    if isinstance(exc, openai.NotFoundError):
        what = f"{name} has no {kind} named \u201c{model}\u201d."
    else:
        detail = getattr(exc, "message", "") or str(exc)
        what = f"{name} couldn't transcribe with \u201c{model}\u201d: {detail}"
    fix = (
        "Deploy a transcription model such as gpt-4o-transcribe or whisper in "
        f"Foundry, then enter its deployment name in {TRANSCRIBE_MENU_PATH}"
        if is_azure
        else f"Choose a transcription model in {TRANSCRIBE_MENU_PATH}"
    )
    return f"{what} {fix}"

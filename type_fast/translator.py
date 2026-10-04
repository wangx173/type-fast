"""Streaming translation via the OpenAI Responses API.

The core entry point is :func:`translate_stream`, a generator that yields chunks
of the translated text as they arrive. The source and target languages are
configurable, so the same function handles any pair from
:data:`type_fast.config.LANGUAGES` (or auto-detected source text).

The underlying client (OpenAI or Microsoft Azure AI Foundry) is built by
:mod:`type_fast.providers`.
"""

from __future__ import annotations

from typing import Callable, Iterator, Optional

import openai

from . import config, providers

# Models (or deployments) that rejected ``temperature`` at runtime. Lets custom
# Azure deployment names backed by reasoning models work despite not matching
# :data:`config.NO_TEMPERATURE_MODEL_PREFIXES`.
_models_without_temperature: set[str] = set()


def system_prompt(source: str, target: str, tone: Optional[str] = None) -> str:
    """Build a strict translation system prompt for the given language pair.

    Args:
        source: Source language name, or ``"auto"`` to auto-detect.
        target: Target language name.
        tone: Instruction describing the desired tone/register of the
            translation. Defaults to the :data:`config.DEFAULT_TONE` preset.
    """
    src = (
        "the source language (auto-detect it)"
        if source == config.AUTO_SOURCE
        else source
    )
    tone = (tone or "").strip() or config.TONES[config.DEFAULT_TONE]
    return (
        f"You are a translation engine. Translate the user's text from {src} "
        f"into natural {target}. Output ONLY the {target} translation. "
        "Do not add romanization, transliteration, explanations, notes, or quotes. "
        "Preserve the original meaning. "
        f"Tone for the translation: {tone}"
    )


def translate_stream(
    text: str,
    source: str = config.DEFAULT_SOURCE,
    target: str = config.DEFAULT_TARGET,
    *,
    tone: Optional[str] = None,
    model: Optional[str] = None,
    client: Optional[openai.OpenAI] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Iterator[str]:
    """Yield translated text chunks for ``text`` as they stream from the model.

    Args:
        text: The text to translate.
        source: Source language name, or ``"auto"`` to auto-detect.
        target: Target language name.
        tone: Tone/register instruction for the translation (see
            :func:`system_prompt`).
        model: Model/deployment to use; defaults to the active provider's
            configured model.
        client: Client to send the request with; defaults to the active
            provider's client. Pass one together with ``model`` to pin both to
            the same provider.
        should_cancel: Optional callback polled between chunks; when it returns
            ``True`` the stream is abandoned. Useful when a newer translation
            supersedes this one on a worker thread.

    Yields:
        Successive pieces of the translated text.
    """
    text = text.strip()
    if not text:
        return

    client = client or providers.get_client()
    model = model or providers.get_model()
    use_temperature = (
        config.supports_temperature(model)
        and model not in _models_without_temperature
    )
    try:
        yield from _stream(client, model, text, source, target, tone,
                           use_temperature, should_cancel)
    except openai.BadRequestError as exc:
        # The request is rejected before any output streams, so retrying is safe.
        if not use_temperature or "temperature" not in str(exc).lower():
            raise
        _models_without_temperature.add(model)
        if should_cancel is not None and should_cancel():
            return
        yield from _stream(client, model, text, source, target, tone,
                           False, should_cancel)


def _stream(
    client: openai.OpenAI,
    model: str,
    text: str,
    source: str,
    target: str,
    tone: Optional[str],
    use_temperature: bool,
    should_cancel: Optional[Callable[[], bool]],
) -> Iterator[str]:
    params = {"temperature": config.DEFAULT_TEMPERATURE} if use_temperature else {}
    with client.responses.stream(
        model=model,
        input=[
            {"role": "system", "content": system_prompt(source, target, tone)},
            {"role": "user", "content": text},
        ],
        **params,
    ) as stream:
        for event in stream:
            if should_cancel is not None and should_cancel():
                break
            if event.type == "response.output_text.delta":
                yield event.delta

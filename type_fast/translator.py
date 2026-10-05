"""Streaming translation via the OpenAI Responses API.

The core entry point is :func:`translate_stream`, a generator that yields chunks
of the translated text as they arrive. The source and target languages are
configurable, so the same function handles any pair from
:data:`type_fast.config.LANGUAGES` (or auto-detected source text).

The underlying client (OpenAI or Microsoft Azure AI Foundry) is built by
:mod:`type_fast.providers`.
"""

from __future__ import annotations

import threading
from typing import Callable, Iterator, Optional

import openai

from . import config, providers

# Both stores below are keyed by (endpoint, model name), so an OpenAI model and
# a Foundry deployment with the same name are tracked separately.

# Models (or deployments) that rejected ``temperature`` at runtime. Lets custom
# Azure deployment names backed by reasoning models work despite not matching
# :data:`config.NO_TEMPERATURE_MODEL_PREFIXES`.
_models_without_temperature: set[tuple[str, str]] = set()

# Reasoning effort to use instead for models (or deployments) that rejected
# theirs at runtime, such as variants of a :data:`config.REASONING_EFFORTS`
# family that don't support its effort: ``"low"`` after ``"none"`` was
# rejected, or None to omit the setting after ``"low"`` was rejected too.
_reasoning_fallbacks: dict[tuple[str, str], Optional[str]] = {}
# Translations run on overlapping worker threads; this makes each step down
# atomic so a stored None is never overwritten with "low".
_reasoning_fallbacks_lock = threading.Lock()


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

    Newer reasoning models are asked for their fastest reasoning effort (see
    :func:`config.reasoning_effort`). If the request is rejected because of
    ``temperature``, it is retried without it; if reasoning effort ``"none"``
    is rejected, it is retried with ``"low"``, and then without the setting.
    The model is remembered so later requests skip the rejected settings.

    Yields:
        Successive pieces of the translated text.
    """
    text = text.strip()
    if not text:
        return

    if should_cancel is not None and should_cancel():
        return  # superseded before it started: don't open a request
    client = client or providers.get_client()
    model = model or providers.get_model()
    key = (str(getattr(client, "base_url", "")), model)
    effort = _reasoning_fallbacks.get(key, config.reasoning_effort(model))
    use_temperature = (
        config.supports_temperature(model, effort)
        and key not in _models_without_temperature
    )
    while True:
        try:
            yield from _stream(client, model, text, source, target, tone,
                               use_temperature, effort, should_cancel)
            return
        except openai.BadRequestError as exc:
            # The request is rejected before any output streams, so retrying is
            # safe. Each retry relaxes one setting, so this ends after at most
            # three. The error names the rejected field in ``param`` when it
            # can; otherwise look for it in the message, checking temperature
            # first because its error can mention reasoning too.
            rejected = str(getattr(exc, "param", None) or exc).lower()
            if use_temperature and "temperature" in rejected:
                _models_without_temperature.add(key)
                use_temperature = False
            elif effort is not None and "reasoning" in rejected:
                # Try low effort next, unless the whole setting is unsupported.
                unsupported = (
                    rejected == "reasoning"
                    or getattr(exc, "code", None) == "unsupported_parameter"
                )
                effort = "low" if effort == "none" and not unsupported else None
                # Only ever step down: a concurrent request may have already
                # learned that the setting must be omitted, so adopt that.
                with _reasoning_fallbacks_lock:
                    if _reasoning_fallbacks.get(key, "") is None:
                        effort = None
                    else:
                        _reasoning_fallbacks[key] = effort
                # With reasoning on, a reasoning model rejects temperature.
                use_temperature = (
                    use_temperature and config.supports_temperature(model, effort)
                )
            else:
                raise
        if should_cancel is not None and should_cancel():
            return


def _stream(
    client: openai.OpenAI,
    model: str,
    text: str,
    source: str,
    target: str,
    tone: Optional[str],
    use_temperature: bool,
    effort: Optional[str],
    should_cancel: Optional[Callable[[], bool]],
) -> Iterator[str]:
    params: dict[str, object] = {}
    if use_temperature:
        params["temperature"] = config.DEFAULT_TEMPERATURE
    if effort is not None:
        params["reasoning"] = {"effort": effort}
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

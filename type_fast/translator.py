"""Streaming translation via the OpenAI Responses API.

The core entry point is :func:`translate_stream`, a generator that yields chunks
of the translated text as they arrive. The source and target languages are
configurable so the same function supports English -> Japanese, Japanese ->
English, and additional language pairs in the future.
"""

from __future__ import annotations

from typing import Callable, Iterator, Optional

from openai import OpenAI

from . import config

# The client is created lazily so importing this module never fails when the
# API key is absent (e.g. during import checks or tests).
_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.get_api_key())
    return _client


def system_prompt(source: str, target: str) -> str:
    """Build a strict translation system prompt for the given language pair."""
    src = "the source language (auto-detect it)" if source == "auto" else source
    return (
        f"You are a translation engine. Translate the user's text from {src} "
        f"into natural {target}. Output ONLY the {target} translation. "
        "Do not add romaji, transliteration, explanations, notes, or quotes. "
        "Preserve meaning and tone, and default to a polite register."
    )


def translate_stream(
    text: str,
    source: str = config.DEFAULT_SOURCE,
    target: str = config.DEFAULT_TARGET,
    *,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Iterator[str]:
    """Yield translated text chunks for ``text`` as they stream from OpenAI.

    Args:
        text: The text to translate.
        source: Source language name, or ``"auto"`` to auto-detect.
        target: Target language name.
        should_cancel: Optional callback polled between chunks; when it returns
            ``True`` the stream is abandoned. Useful when a newer translation
            supersedes this one on a worker thread.

    Yields:
        Successive pieces of the translated text.
    """
    text = text.strip()
    if not text:
        return

    client = _get_client()
    with client.responses.stream(
        model=config.DEFAULT_MODEL,
        input=[
            {"role": "system", "content": system_prompt(source, target)},
            {"role": "user", "content": text},
        ],
        temperature=config.DEFAULT_TEMPERATURE,
    ) as stream:
        for event in stream:
            if should_cancel is not None and should_cancel():
                break
            if event.type == "response.output_text.delta":
                yield event.delta

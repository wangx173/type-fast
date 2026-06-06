"""Configuration for type-fast.

Centralizes the API-key source, the default model, the default language pair,
and the input debounce interval so they are easy to change in one place.

The API key is read from the ``OPENAI_API_KEY`` environment variable for this
PoC. A later iteration can replace :func:`get_api_key` with macOS Keychain
storage (via the ``keyring`` package) without touching the rest of the app.
"""

from __future__ import annotations

import os

DEFAULT_MODEL = "gpt-4.1-mini"

# Low temperature keeps translations faithful and deterministic.
DEFAULT_TEMPERATURE = 0.2

# Default language pair. ``source="auto"`` lets the model detect the input
# language, which supports bidirectional translation and future languages.
DEFAULT_SOURCE = "auto"
DEFAULT_TARGET = "Japanese"

# Milliseconds of idle time after typing stops before a translation fires.
DEBOUNCE_MS = 500


class MissingAPIKeyError(RuntimeError):
    """Raised when the OpenAI API key is not configured."""


def get_api_key() -> str:
    """Return the OpenAI API key from the environment.

    Raises:
        MissingAPIKeyError: If ``OPENAI_API_KEY`` is not set.
    """
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise MissingAPIKeyError(
            "OPENAI_API_KEY is not set. Export it before running type-fast, e.g.:\n"
            "    export OPENAI_API_KEY='sk-...'"
        )
    return key

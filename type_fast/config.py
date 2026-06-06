"""Configuration for type-fast.

Centralizes the API-key source, the default model, the default language pair,
and the input debounce interval so they are easy to change in one place.

The API key is read from the ``OPENAI_API_KEY`` environment variable, or, when
that is not set (e.g. when the packaged ``.app`` is launched from Finder, which
does not inherit your shell environment), from the file ``~/.type-fast/api_key``.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL = "gpt-4.1-mini"

# Low temperature keeps translations faithful and deterministic.
DEFAULT_TEMPERATURE = 0.2

# Default language pair. ``source="auto"`` lets the model detect the input
# language, which supports bidirectional translation and future languages.
DEFAULT_SOURCE = "auto"
DEFAULT_TARGET = "Japanese"

# Milliseconds of idle time after typing stops before a translation fires.
DEBOUNCE_MS = 500

# Fallback key file, used when OPENAI_API_KEY is not in the environment.
API_KEY_FILE = Path.home() / ".type-fast" / "api_key"


class MissingAPIKeyError(RuntimeError):
    """Raised when the OpenAI API key is not configured."""


def get_api_key() -> str:
    """Return the OpenAI API key.

    Looks first at the ``OPENAI_API_KEY`` environment variable, then at the
    ``~/.type-fast/api_key`` file (so the packaged app works when launched from
    Finder, which does not inherit the shell environment).

    Raises:
        MissingAPIKeyError: If no key is found in either location.
    """
    key = os.environ.get("OPENAI_API_KEY")
    if not key and API_KEY_FILE.is_file():
        key = API_KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        raise MissingAPIKeyError(
            "No OpenAI API key found. Either set the OPENAI_API_KEY environment "
            f"variable, or write your key to {API_KEY_FILE}:\n"
            f"    mkdir -p {API_KEY_FILE.parent}\n"
            f"    echo 'sk-...' > {API_KEY_FILE}"
        )
    return key


def has_api_key() -> bool:
    """Return True if an API key is configured (env var or key file)."""
    if os.environ.get("OPENAI_API_KEY"):
        return True
    return API_KEY_FILE.is_file() and bool(
        API_KEY_FILE.read_text(encoding="utf-8").strip()
    )


def save_api_key(key: str) -> None:
    """Write ``key`` to the key file with owner-only permissions."""
    key = key.strip()
    API_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    API_KEY_FILE.write_text(key, encoding="utf-8")
    API_KEY_FILE.chmod(0o600)

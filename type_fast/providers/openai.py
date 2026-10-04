"""OpenAI provider: credentials, model, and client construction.

The API key is read from the ``OPENAI_API_KEY`` environment variable, or, when
that is not set, from the fallback file ``~/.type-fast/api_key``. The model is
read from ``OPENAI_MODEL`` or ``~/.type-fast/openai_model`` (settable in the app
via Settings › Set Model…), defaulting to :data:`type_fast.config.DEFAULT_MODEL`.
This is the default provider (see :mod:`type_fast.providers` for how one is chosen).
"""

from __future__ import annotations

from openai import OpenAI

from .. import config
from ._common import CONFIG_DIR, from_env_or_file, write_or_clear, write_private

NAME = "openai"
DISPLAY_NAME = "OpenAI"
SHORT_NAME = "OpenAI"

# Fallback key file, used when OPENAI_API_KEY is not in the environment.
API_KEY_FILE = CONFIG_DIR / "api_key"

# Model override: environment variable, then fallback file, then the default.
MODEL_ENV = "OPENAI_MODEL"
MODEL_FILE = CONFIG_DIR / "openai_model"


class MissingAPIKeyError(RuntimeError):
    """Raised when the OpenAI API key is not configured."""


def _api_key() -> str:
    """Return the configured OpenAI API key, or an empty string."""
    return from_env_or_file("OPENAI_API_KEY", API_KEY_FILE)


def is_configured() -> bool:
    """Return True if an OpenAI API key is available."""
    return bool(_api_key())


def get_model() -> str:
    """Return the model name used for OpenAI requests (or the shared default)."""
    return from_env_or_file(MODEL_ENV, MODEL_FILE) or config.DEFAULT_MODEL


def save_model(model: str) -> None:
    """Persist ``model`` to the model file; a blank value restores the default."""
    write_or_clear(MODEL_FILE, model)


def get_api_key() -> str:
    """Return the OpenAI API key.

    Raises:
        MissingAPIKeyError: If no key is found in the environment or key file.
    """
    key = _api_key()
    if not key:
        raise MissingAPIKeyError(
            "No OpenAI API key found. Either set the OPENAI_API_KEY environment "
            f"variable, or write your key to {API_KEY_FILE}:\n"
            f"    mkdir -p {API_KEY_FILE.parent}\n"
            f"    echo 'sk-...' > {API_KEY_FILE}"
        )
    return key


def save_api_key(key: str) -> None:
    """Write ``key`` to the key file with owner-only permissions."""
    write_private(API_KEY_FILE, key)


def client_key() -> tuple[str, ...]:
    """Return the settings the client is built from, to detect changes."""
    return (_api_key(),)


def build_client() -> OpenAI:
    """Build an OpenAI client for the standard OpenAI API."""
    return OpenAI(api_key=get_api_key())

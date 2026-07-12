"""OpenAI provider: credentials, model, and client construction.

The API key is read from the ``OPENAI_API_KEY`` environment variable, or, when
that is not set, from the fallback file ``~/.type-fast/api_key``. This is the
default provider, used whenever Azure AI Foundry is not configured.
"""

from __future__ import annotations

from openai import OpenAI

from .. import config
from ._common import CONFIG_DIR, from_env_or_file

NAME = "openai"

# Fallback key file, used when OPENAI_API_KEY is not in the environment.
API_KEY_FILE = CONFIG_DIR / "api_key"


class MissingAPIKeyError(RuntimeError):
    """Raised when the OpenAI API key is not configured."""


def _api_key() -> str:
    """Return the configured OpenAI API key, or an empty string."""
    return from_env_or_file("OPENAI_API_KEY", API_KEY_FILE)


def is_configured() -> bool:
    """Return True if an OpenAI API key is available."""
    return bool(_api_key())


def get_model() -> str:
    """Return the model name used for OpenAI requests."""
    return config.DEFAULT_MODEL


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
    key = key.strip()
    API_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    API_KEY_FILE.write_text(key, encoding="utf-8")
    API_KEY_FILE.chmod(0o600)


def build_client() -> OpenAI:
    """Build an OpenAI client for the standard OpenAI API."""
    return OpenAI(api_key=get_api_key())

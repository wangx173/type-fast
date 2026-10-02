"""Microsoft (Azure AI) Foundry provider: credentials, model, and client.

Configured via ``AZURE_AI_ENDPOINT`` and ``AZURE_AI_API_KEY`` (and optionally
``AZURE_AI_MODEL`` to pick a deployment), each with a matching ``~/.type-fast/``
fallback file. Foundry is reached through its OpenAI-compatible ``/openai/v1``
endpoint, so the standard OpenAI client and Responses API calls work unchanged.
"""

from __future__ import annotations

from openai import OpenAI

from .. import config
from ._common import CONFIG_DIR, from_env_or_file, write_or_clear

NAME = "azure"
DISPLAY_NAME = "Azure AI Foundry"

# Fallback files, used when the matching environment variables are not set.
ENDPOINT_FILE = CONFIG_DIR / "azure_ai_endpoint"
API_KEY_FILE = CONFIG_DIR / "azure_ai_api_key"
MODEL_FILE = CONFIG_DIR / "azure_ai_model"
MODEL_ENV = "AZURE_AI_MODEL"


def get_endpoint() -> str:
    """Return the configured Foundry endpoint, or an empty string."""
    return from_env_or_file("AZURE_AI_ENDPOINT", ENDPOINT_FILE)


def get_api_key() -> str:
    """Return the configured Foundry API key, or an empty string."""
    return from_env_or_file("AZURE_AI_API_KEY", API_KEY_FILE)


def get_model() -> str:
    """Return the Foundry model/deployment name (or the shared default)."""
    return from_env_or_file(MODEL_ENV, MODEL_FILE) or config.DEFAULT_MODEL


def save_model(model: str) -> None:
    """Persist ``model`` to the model file; a blank value restores the default."""
    write_or_clear(MODEL_FILE, model)


def is_configured() -> bool:
    """Return True when both a Foundry endpoint and API key are available."""
    return bool(get_endpoint() and get_api_key())


def _base_url(endpoint: str) -> str:
    """Normalize a Foundry endpoint to its OpenAI-compatible ``/openai/v1`` base.

    Accepts a bare resource endpoint (``https://<res>.services.ai.azure.com``)
    or one that already includes the ``/openai/v1`` path, and returns a base URL
    the OpenAI client can append ``/responses`` to.
    """
    base = endpoint.strip().rstrip("/")
    if not base.endswith("/openai/v1"):
        base = f"{base}/openai/v1"
    return base


def build_client() -> OpenAI:
    """Build an OpenAI client pointed at the Foundry endpoint."""
    return OpenAI(base_url=_base_url(get_endpoint()), api_key=get_api_key())

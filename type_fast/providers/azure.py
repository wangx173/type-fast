"""Microsoft (Azure AI) Foundry provider: credentials, model, and client.

Configured via ``AZURE_AI_ENDPOINT`` and ``AZURE_AI_API_KEY`` (and optionally
``AZURE_AI_MODEL`` to pick a deployment), each with a matching ``~/.type-fast/``
fallback file. The files can also be written from the app (Settings › Set Up
Azure AI Foundry…). Foundry is reached through its OpenAI-compatible
``/openai/v1`` endpoint, so the standard OpenAI client and Responses API calls
work unchanged.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from openai import OpenAI

from .. import config
from ._common import CONFIG_DIR, from_env_or_file, write_or_clear, write_private

NAME = "azure"
DISPLAY_NAME = "Azure AI Foundry"
SHORT_NAME = "Azure"

# Fallback files, used when the matching environment variables are not set.
ENDPOINT_FILE = CONFIG_DIR / "azure_ai_endpoint"
API_KEY_FILE = CONFIG_DIR / "azure_ai_api_key"
MODEL_FILE = CONFIG_DIR / "azure_ai_model"
ENDPOINT_ENV = "AZURE_AI_ENDPOINT"
API_KEY_ENV = "AZURE_AI_API_KEY"
MODEL_ENV = "AZURE_AI_MODEL"

# The Foundry portal shows a project endpoint (``…/api/projects/<name>``); the
# OpenAI-compatible API lives at the resource root instead.
_PROJECT_PATH = re.compile(r"/api/projects(/.*)?$", re.IGNORECASE)


class MissingCredentialsError(RuntimeError):
    """Raised when Azure AI Foundry is selected but not set up."""


def get_endpoint() -> str:
    """Return the configured Foundry endpoint, or an empty string."""
    return from_env_or_file(ENDPOINT_ENV, ENDPOINT_FILE)


def get_api_key() -> str:
    """Return the configured Foundry API key, or an empty string."""
    return from_env_or_file(API_KEY_ENV, API_KEY_FILE)


def saved_model() -> str:
    """Return the deployment name from the environment or file, or ""."""
    return from_env_or_file(MODEL_ENV, MODEL_FILE)


def get_model() -> str:
    """Return the Foundry model/deployment name (or the shared default)."""
    return saved_model() or config.DEFAULT_MODEL


def save_model(model: str) -> None:
    """Persist ``model`` to the model file; a blank value restores the default."""
    write_or_clear(MODEL_FILE, model)


def env_overrides() -> list[str]:
    """Return the Foundry environment variables that override the saved files."""
    return [
        name
        for name in (ENDPOINT_ENV, API_KEY_ENV, MODEL_ENV)
        if os.environ.get(name, "").strip()
    ]


def save_settings(endpoint: str, api_key: str, model: str) -> None:
    """Save the endpoint, API key (owner-only), and deployment name to files.

    A blank ``model`` restores the default deployment name.
    """
    endpoint = endpoint.strip()
    api_key = api_key.strip()
    if not endpoint or not api_key:
        raise ValueError("Both an endpoint and an API key are needed.")
    write_or_clear(ENDPOINT_FILE, endpoint)
    write_private(API_KEY_FILE, api_key)
    save_model(model)


def is_configured() -> bool:
    """Return True when both a Foundry endpoint and API key are available."""
    return bool(get_endpoint() and get_api_key())


def endpoint_host() -> str:
    """Return the host name of the configured endpoint, or an empty string."""
    return urlsplit(get_endpoint()).hostname or ""


def _base_url(endpoint: str) -> str:
    """Normalize a Foundry endpoint to its OpenAI-compatible ``/openai/v1`` base.

    Accepts a bare resource endpoint (``https://<res>.services.ai.azure.com``),
    a project endpoint (``…/api/projects/<name>``), or one that already
    includes the ``/openai/v1`` path, and returns a base URL the OpenAI client
    can append ``/responses`` to.
    """
    base = endpoint.strip().rstrip("/")
    base = _PROJECT_PATH.sub("", base)
    if not base.endswith("/openai/v1"):
        base = f"{base}/openai/v1"
    return base


def client_key() -> tuple[str, ...]:
    """Return the settings the client is built from, to detect changes."""
    return (get_endpoint(), get_api_key())


def build_client() -> OpenAI:
    """Build an OpenAI client pointed at the Foundry endpoint.

    Raises:
        MissingCredentialsError: If the endpoint or API key is missing.
    """
    if not is_configured():
        raise MissingCredentialsError(
            "Azure AI Foundry isn't set up. Choose Settings \u203a Set Up Azure "
            "AI Foundry\u2026 and enter your endpoint and API key, or switch to "
            "OpenAI in Settings \u203a Provider."
        )
    return OpenAI(base_url=_base_url(get_endpoint()), api_key=get_api_key())

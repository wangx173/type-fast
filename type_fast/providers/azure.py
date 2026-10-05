"""Microsoft (Azure AI) Foundry provider: credentials, model, and client.

Configured via ``AZURE_AI_ENDPOINT`` and ``AZURE_AI_API_KEY`` (and optionally
``AZURE_AI_MODEL`` to pick a deployment), each with a matching ``~/.type-fast/``
fallback file. The files can also be written from the app (Settings › Azure AI
Foundry › Set Endpoint, Key & Deployment… or Set Deployment…). Foundry is
reached through its OpenAI-compatible ``/openai/v1`` endpoint, so the standard
OpenAI client and Responses API calls work unchanged.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from openai import OpenAI

from .. import config
from ._common import CONFIG_DIR, from_env_or_file, write_or_clear, write_private

NAME = "azure"
DISPLAY_NAME = "Azure AI Foundry"
SHORT_NAME = "Azure"

# This provider's items in the app's Settings › Azure AI Foundry submenu. They
# live here so the error below can point at them.
SETUP_ITEM = "Set Endpoint, Key & Deployment\u2026"
DEPLOYMENT_ITEM = "Set Deployment\u2026"
SETUP_PATH = f"Settings \u203a {DISPLAY_NAME} \u203a {SETUP_ITEM}"
DEPLOYMENT_PATH = f"Settings \u203a {DISPLAY_NAME} \u203a {DEPLOYMENT_ITEM}"

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
_OPENAI_V1_PATH = re.compile(r"/openai/v1$", re.IGNORECASE)
# Endpoint paths _base_url() understands: none, /openai/v1, or a project.
_SUPPORTED_PATH = re.compile(r"(/openai/v1|/api/projects/[^/]+)?/?", re.IGNORECASE)


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
    """Return the Foundry model/deployment name (or the default deployment)."""
    return saved_model() or config.DEFAULT_AZURE_MODEL


def save_model(model: str) -> None:
    """Persist ``model`` to the model file; a blank value restores the default."""
    write_or_clear(MODEL_FILE, model)


def deployment_problem(model: str) -> str | None:
    """Return why ``model`` can't be a deployment name, or None if it can."""
    if any(c.isspace() for c in model):
        return "The deployment name can't contain spaces."
    return None


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
    files = (ENDPOINT_FILE, API_KEY_FILE, MODEL_FILE)
    previous = {path: _read_for_restore(path) for path in files}
    try:
        write_or_clear(ENDPOINT_FILE, endpoint)
        write_private(API_KEY_FILE, api_key)
        save_model(model)
    except BaseException:
        # Don't leave a mix of old and new settings behind.
        for path, value in previous.items():
            _restore(path, value)
        raise


_UNREADABLE = object()


def _read_for_restore(path: Path) -> object:
    """Return the text of ``path``, None if it doesn't exist, or _UNREADABLE."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        return _UNREADABLE


def _restore(path: Path, value: object) -> None:
    """Put back what :func:`_read_for_restore` returned, as far as possible."""
    if value is _UNREADABLE:
        return
    try:
        if value is None:
            path.unlink(missing_ok=True)
        elif path == API_KEY_FILE:
            write_private(path, str(value))
        else:
            path.write_text(str(value), encoding="utf-8")
    except OSError:
        pass


def is_configured() -> bool:
    """Return True when both a Foundry endpoint and API key are available."""
    return bool(get_endpoint() and get_api_key())


def endpoint_host() -> str:
    """Return the host name of the configured endpoint, or an empty string."""
    try:
        return urlsplit(get_endpoint()).hostname or ""
    except ValueError:  # e.g. "https://[" from the environment or a file
        return ""


def has_supported_path(endpoint: str) -> bool:
    """Return True if ``endpoint`` has no path, ``/openai/v1``, or a project path."""
    try:
        path = urlsplit(endpoint.strip()).path
    except ValueError:
        return False
    return _SUPPORTED_PATH.fullmatch(path) is not None


def _base_url(endpoint: str) -> str:
    """Normalize a Foundry endpoint to its OpenAI-compatible ``/openai/v1`` base.

    Accepts a bare resource endpoint (``https://<res>.services.ai.azure.com``),
    a project endpoint (``…/api/projects/<name>``), or one that already
    includes the ``/openai/v1`` path, and returns a base URL the OpenAI client
    can append ``/responses`` to.
    """
    base = endpoint.strip().rstrip("/")
    base = _PROJECT_PATH.sub("", base)
    base = _OPENAI_V1_PATH.sub("", base)
    return f"{base}/openai/v1"


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
            f"{DISPLAY_NAME} isn't set up. Choose {SETUP_PATH} and enter your "
            "endpoint and API key, or switch to OpenAI in Settings \u203a Provider."
        )
    return OpenAI(base_url=_base_url(get_endpoint()), api_key=get_api_key())

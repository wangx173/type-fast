"""Provider selection and a cached client for the active provider.

Azure AI Foundry is selected when it is configured (endpoint + API key);
otherwise the default OpenAI provider is used. The client is built lazily and
cached, so importing this package never fails when credentials are absent.
"""

from __future__ import annotations

from types import ModuleType
from typing import Optional

from openai import OpenAI

from . import azure as azure_provider, openai as openai_provider

_client: Optional[OpenAI] = None
_client_provider: Optional[str] = None


def active_provider() -> ModuleType:
    """Return the module for the currently active provider."""
    if azure_provider.is_configured():
        return azure_provider
    return openai_provider


def has_credentials() -> bool:
    """Return True if any provider is configured (OpenAI or Azure Foundry)."""
    return azure_provider.is_configured() or openai_provider.is_configured()


def get_model() -> str:
    """Return the model/deployment name for the active provider."""
    return active_provider().get_model()


def get_client() -> OpenAI:
    """Return the cached client for the active provider, building it if needed.

    The cache is keyed on the active provider so that a runtime provider change
    (e.g. Azure credentials appearing) rebuilds the client and keeps it in sync
    with :func:`get_model`.
    """
    global _client, _client_provider
    provider = active_provider()
    if _client is None or _client_provider != provider.NAME:
        _client = provider.build_client()
        _client_provider = provider.NAME
    return _client


def reset_client() -> None:
    """Discard the cached client so the next call picks up new credentials."""
    global _client, _client_provider
    _client = None
    _client_provider = None

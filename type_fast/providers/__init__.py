"""Provider selection and a cached client for the active provider.

The provider chosen in Settings › Provider is saved to ``~/.type-fast/provider``
(``openai`` or ``azure``). Without a saved choice, Azure AI Foundry is used when
it is configured (endpoint + API key) and OpenAI otherwise. The client is built
lazily and cached, so importing this package never fails when credentials are
absent.
"""

from __future__ import annotations

import os
import threading
from types import ModuleType
from typing import Optional

from openai import OpenAI

from . import azure as azure_provider, openai as openai_provider
from ._common import CONFIG_DIR, write_or_clear

# Every provider, in the order the app lists them.
PROVIDERS: tuple[ModuleType, ...] = (openai_provider, azure_provider)

# The saved provider choice; missing means "automatic".
PROVIDER_FILE = CONFIG_DIR / "provider"

_client_lock = threading.Lock()  # translation workers call get_client()
_client: Optional[OpenAI] = None
_client_key: Optional[tuple[str, ...]] = None


def by_name(name: str) -> Optional[ModuleType]:
    """Return the provider module called ``name``, or None."""
    for provider in PROVIDERS:
        if provider.NAME == name:
            return provider
    return None


def get_choice() -> Optional[str]:
    """Return the saved provider name, or None when none (or an invalid one) is saved."""
    try:
        name = PROVIDER_FILE.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None
    return name if by_name(name) is not None else None


def set_choice(name: Optional[str]) -> None:
    """Save ``name`` as the provider to use; None goes back to automatic."""
    if name is not None and by_name(name) is None:
        raise ValueError(f"Unknown provider: {name}")
    write_or_clear(PROVIDER_FILE, name or "")


def active_provider() -> ModuleType:
    """Return the module for the currently active provider."""
    chosen = by_name(get_choice() or "")
    if chosen is not None:
        return chosen
    if azure_provider.is_configured():
        return azure_provider
    return openai_provider


def has_credentials() -> bool:
    """Return True if the active provider is set up."""
    return active_provider().is_configured()


def get_model() -> str:
    """Return the model/deployment name for the active provider."""
    return active_provider().get_model()


def model_env_override() -> Optional[str]:
    """Return the env var name if it currently pins the active provider's model.

    An environment variable takes precedence over the saved model file, so a
    model chosen in the app has no effect while this returns a name.
    """
    env = active_provider().MODEL_ENV
    return env if os.environ.get(env, "").strip() else None


def save_model(model: str) -> None:
    """Save ``model`` for the active provider (blank restores the default)."""
    active_provider().save_model(model)


def get_client() -> OpenAI:
    """Return the cached client for the active provider, building it if needed.

    The cache is keyed on the active provider and its endpoint and key, so
    switching provider or changing credentials (in the app or in the files)
    rebuilds the client and keeps it in sync with :func:`get_model`.
    """
    global _client, _client_key
    with _client_lock:
        provider = active_provider()
        key = (provider.NAME, *provider.client_key())
        if _client is None or _client_key != key:
            _client = provider.build_client()
            _client_key = key
        return _client


def reset_client() -> None:
    """Discard the cached client so the next call picks up new credentials."""
    global _client, _client_key
    with _client_lock:
        _client = None
        _client_key = None

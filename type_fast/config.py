"""Shared, provider-agnostic configuration for type-fast.

Holds the default model, temperature, default language pair, and the input
debounce interval so they are easy to change in one place. Provider-specific
credential handling and client construction live in :mod:`type_fast.providers`
(one module per provider).
"""

from __future__ import annotations

from .providers._common import CONFIG_DIR, from_env_or_file

DEFAULT_MODEL = "gpt-4.1-mini"

# Low temperature keeps translations faithful and deterministic.
DEFAULT_TEMPERATURE = 0.2

# Default language pair. ``source="auto"`` lets the model detect the input
# language, which supports bidirectional translation and future languages.
DEFAULT_SOURCE = "auto"
DEFAULT_TARGET = "Japanese"

# Milliseconds of idle time after typing stops before a translation fires.
DEBOUNCE_MS = 500

# Default global hotkey that summons Type Fast (see type_fast.hotkey for the
# spec syntax: "+"-separated modifiers plus exactly one key, e.g.
# "control+option+t"). Overridable per-user the same way the OpenAI/Azure
# credentials are: an environment variable, or a fallback file, for the
# packaged .app case where launching from Finder doesn't inherit your shell
# environment.
DEFAULT_HOTKEY = "option+command+space"


def hotkey_spec() -> str:
    """Return the configured global hotkey spec.

    Reads ``TYPE_FAST_HOTKEY``, falling back to ``~/.type-fast/hotkey``, and
    finally to :data:`DEFAULT_HOTKEY` if neither is set.
    """
    return from_env_or_file("TYPE_FAST_HOTKEY", CONFIG_DIR / "hotkey") or DEFAULT_HOTKEY

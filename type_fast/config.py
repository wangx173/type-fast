"""Shared, provider-agnostic configuration for type-fast.

Holds the default model, temperature, default language pair, and the input
debounce interval so they are easy to change in one place. Provider-specific
credential handling and client construction live in :mod:`type_fast.providers`
(one module per provider).
"""

from __future__ import annotations

DEFAULT_MODEL = "gpt-4.1-mini"

# Low temperature keeps translations faithful and deterministic.
DEFAULT_TEMPERATURE = 0.2

# Default language pair. ``source="auto"`` lets the model detect the input
# language, which supports bidirectional translation and future languages.
DEFAULT_SOURCE = "auto"
DEFAULT_TARGET = "Japanese"

# Milliseconds of idle time after typing stops before a translation fires.
DEBOUNCE_MS = 500


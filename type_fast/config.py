"""Shared, provider-agnostic configuration for type-fast.

Holds the default model, temperature, default language pair, translation tone
presets, and the input debounce interval so they are easy to change in one
place. Provider-specific credential handling and client construction live in
:mod:`type_fast.providers` (one module per provider).
"""

from __future__ import annotations

DEFAULT_MODEL = "gpt-4.1-mini"

# Models offered in Settings › Set Model…. The dialog is editable, so any other
# model (or Azure AI Foundry deployment) name can be typed in as well.
MODEL_CHOICES = (
    "gpt-4.1-mini",
    "gpt-4.1",
    "gpt-4.1-nano",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
)

# Low temperature keeps translations faithful and deterministic.
DEFAULT_TEMPERATURE = 0.2

# Model-name prefixes for reasoning models that reject the ``temperature``
# sampling parameter; requests to these models omit it.
NO_TEMPERATURE_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def supports_temperature(model: str) -> bool:
    """Return False for reasoning models that do not accept ``temperature``."""
    return not model.strip().lower().startswith(NO_TEMPERATURE_MODEL_PREFIXES)


# Default language pair. ``source="auto"`` lets the model detect the input
# language, which supports bidirectional translation and future languages.
DEFAULT_SOURCE = "auto"
DEFAULT_TARGET = "Japanese"

# Tone presets for the translated text: display name -> prompt instruction.
TONES = {
    "Polite": "Use a polite, courteous register.",
    "Casual": "Use a casual, relaxed, conversational register, as between friends.",
    "Formal": "Use a formal register suitable for official documents.",
    "Business": "Use a professional business register suitable for work emails and meetings.",
    "Friendly": "Use a warm, friendly, approachable tone.",
    "Neutral": "Mirror the register of the original text without making it more or less formal.",
}
DEFAULT_TONE = "Polite"

# Pseudo-tone whose instruction is free text written by the user.
CUSTOM_TONE = "Custom"

# Milliseconds of idle time after typing stops before a translation fires.
DEBOUNCE_MS = 500

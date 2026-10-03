"""Shared, provider-agnostic configuration for type-fast.

Holds the default model, temperature, supported languages and the default
language pair, translation tone presets, the input debounce interval, the
default show/hide hotkey, and the window transparency presets so they are easy
to change in one place.
Provider-specific credential handling and client construction live in
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


# Supported languages: English name (used in the prompt) -> native name (shown
# alongside it in the language pickers). Add an entry here to support another
# language.
LANGUAGES = {
    "English": "English",
    "Japanese": "日本語",
    "Chinese (Simplified)": "简体中文",
    "Chinese (Traditional)": "繁體中文",
    "Korean": "한국어",
    "Spanish": "Español",
    "French": "Français",
    "German": "Deutsch",
    "Italian": "Italiano",
    "Portuguese": "Português",
    "Russian": "Русский",
    "Vietnamese": "Tiếng Việt",
    "Thai": "ไทย",
    "Indonesian": "Bahasa Indonesia",
    "Hindi": "हिन्दी",
    "Arabic": "العربية",
}

# Source value that lets the model detect the input language.
AUTO_SOURCE = "auto"

# Default language pair used by :func:`type_fast.translator.translate_stream`.
DEFAULT_SOURCE = AUTO_SOURCE
DEFAULT_TARGET = "Japanese"

# Default language pair shown in the window on first launch.
DEFAULT_UI_SOURCE = "English"
DEFAULT_UI_TARGET = "Japanese"

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

# Default global show/hide hotkey (see :mod:`type_fast.hotkey` for the format).
# ⇧⌘Space is unused by macOS by default. It avoids Spotlight (⌘Space, ⌥⌘Space),
# input-source switching (⌃Space, ⌃⌥Space), and ⌥Space, which types a
# non-breaking space and is claimed by launchers such as Alfred, Raycast, and
# ChatGPT. Users can pick any combination in Settings › Set Show/Hide Hotkey….
DEFAULT_HOTKEY = "Shift+Cmd+Space"

# Window transparency presets: name -> (opacity while you are using Type Fast,
# opacity while it sits in the background). The window stays on top of other
# apps, so it fades further once you click elsewhere and comes back to the first
# value when you return to it or hover over it. Pick one in Settings › Window
# Transparency.
TRANSPARENCY = {
    "Off": (1.0, 1.0),
    "Light": (0.95, 0.75),
    "Medium": (0.88, 0.6),
    "Strong": (0.8, 0.45),
}
DEFAULT_TRANSPARENCY = "Light"

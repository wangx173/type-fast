"""Persistent user preferences: languages, No translation mode, tone, hotkey,
transparency, auto-paste, and voice input.

Stored as JSON in ``~/.type-fast/settings.json`` so the chosen languages,
whether No translation mode is on, the tone, any custom tone instruction, the
global show/hide hotkey, the window transparency, whether hiding with the hotkey
pastes the translation, and the voice input and input clean-up switches survive
restarts. A missing, unreadable, or invalid file (or field) falls back to the defaults in
:mod:`type_fast.config`. The hotkey is stored in canonical form (e.g.
``"Shift+Cmd+Space"``, see :mod:`type_fast.hotkey`); an empty string disables it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from . import config, hotkey as hotkey_module
from .providers._common import CONFIG_DIR

SETTINGS_FILE = CONFIG_DIR / "settings.json"


@dataclass
class Settings:
    """The language pair, No translation mode, tone, custom tone, hotkey,
    transparency, auto-paste, and voice input switches."""

    source: str = config.DEFAULT_UI_SOURCE
    target: str = config.DEFAULT_UI_TARGET
    # No translation mode: polish the input in its own language. ``target``
    # keeps the last translation target so turning it off restores the pair.
    polish: bool = config.DEFAULT_POLISH
    tone: str = config.DEFAULT_TONE
    custom_tone: str = ""
    # Canonical hotkey text; "" means the global hotkey is disabled.
    hotkey: str = config.DEFAULT_HOTKEY
    # Name of a :data:`config.TRANSPARENCY` preset.
    transparency: str = config.DEFAULT_TRANSPARENCY
    # Paste the translation into your app when the hotkey hides the window.
    auto_paste: bool = config.DEFAULT_AUTO_PASTE
    # Show the mic button and register the global ⇧⌘M voice hotkey.
    voice_input: bool = config.DEFAULT_VOICE_INPUT
    # Clean up filler words and false starts in spoken / typed input.
    optimize_voice: bool = config.DEFAULT_OPTIMIZE_VOICE
    optimize_typed: bool = config.DEFAULT_OPTIMIZE_TYPED

    def instruction(self) -> str:
        """Return the prompt instruction for the selected tone."""
        if self.tone == config.AUTO_TONE:
            return config.AUTO_TONE_INSTRUCTION
        if self.tone == config.CUSTOM_TONE:
            custom = self.custom_tone.strip()
            return custom or config.TONES[config.DEFAULT_TONE]
        return config.TONES.get(self.tone, config.TONES[config.DEFAULT_TONE])


def _pick(value: object, valid: set[str], default: str) -> str:
    return value if isinstance(value, str) and value in valid else default


def _pick_hotkey(value: object) -> str:
    """Return the canonical hotkey text, "" if disabled, else the default."""
    if isinstance(value, str):
        if not value.strip():
            return ""
        parsed = hotkey_module.parse(value)
        if parsed is not None:
            return str(parsed)
    return config.DEFAULT_HOTKEY


def _pick_bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def load() -> Settings:
    """Load saved settings, falling back to defaults on any problem."""
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    # The pair is validated as a unit: if either side is missing, invalid, or
    # both are the same, restore the whole default pair.
    source, target = data.get("source"), data.get("target")
    languages = set(config.LANGUAGES)
    if not (
        isinstance(source, str)
        and isinstance(target, str)
        and source in languages | {config.AUTO_SOURCE}
        and target in languages
        and source != target
    ):
        source, target = config.DEFAULT_UI_SOURCE, config.DEFAULT_UI_TARGET
    custom = data.get("custom_tone")
    return Settings(
        source=source,
        target=target,
        polish=_pick_bool(data.get("polish"), config.DEFAULT_POLISH),
        tone=_pick(
            data.get("tone"),
            set(config.TONES) | {config.CUSTOM_TONE, config.AUTO_TONE},
            config.DEFAULT_TONE,
        ),
        custom_tone=custom if isinstance(custom, str) else "",
        hotkey=_pick_hotkey(data.get("hotkey")),
        transparency=_pick(
            data.get("transparency"),
            set(config.TRANSPARENCY),
            config.DEFAULT_TRANSPARENCY,
        ),
        auto_paste=_pick_bool(data.get("auto_paste"), config.DEFAULT_AUTO_PASTE),
        voice_input=_pick_bool(data.get("voice_input"), config.DEFAULT_VOICE_INPUT),
        optimize_voice=_pick_bool(
            data.get("optimize_voice"), config.DEFAULT_OPTIMIZE_VOICE
        ),
        optimize_typed=_pick_bool(
            data.get("optimize_typed"), config.DEFAULT_OPTIMIZE_TYPED
        ),
    )


def save(settings: Settings) -> None:
    """Write ``settings`` to the settings file."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

"""Persistent user preferences: languages, tone, hotkey, and transparency.

Stored as JSON in ``~/.type-fast/settings.json`` so the chosen languages, tone,
any custom tone instruction, the global show/hide hotkey, and the window
transparency survive restarts. A
missing, unreadable, or invalid file (or field) falls back to the defaults in
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
    """The selected language pair, tone, custom tone, hotkey, and transparency."""

    source: str = config.DEFAULT_UI_SOURCE
    target: str = config.DEFAULT_UI_TARGET
    tone: str = config.DEFAULT_TONE
    custom_tone: str = ""
    # Canonical hotkey text; "" means the global hotkey is disabled.
    hotkey: str = config.DEFAULT_HOTKEY
    # Name of a :data:`config.TRANSPARENCY` preset.
    transparency: str = config.DEFAULT_TRANSPARENCY

    def instruction(self) -> str:
        """Return the prompt instruction for the selected tone."""
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
        tone=_pick(
            data.get("tone"),
            set(config.TONES) | {config.CUSTOM_TONE},
            config.DEFAULT_TONE,
        ),
        custom_tone=custom if isinstance(custom, str) else "",
        hotkey=_pick_hotkey(data.get("hotkey")),
        transparency=_pick(
            data.get("transparency"),
            set(config.TRANSPARENCY),
            config.DEFAULT_TRANSPARENCY,
        ),
    )


def save(settings: Settings) -> None:
    """Write ``settings`` to the settings file."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

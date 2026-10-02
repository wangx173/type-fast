"""Persistent user preferences: language pair and translation tone.

Stored as JSON in ``~/.type-fast/settings.json`` so the chosen languages, tone,
and any custom tone instruction survive restarts. A missing, unreadable, or
invalid file (or field) falls back to the defaults in :mod:`type_fast.config`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from . import config
from .providers._common import CONFIG_DIR

SETTINGS_FILE = CONFIG_DIR / "settings.json"


@dataclass
class Settings:
    """The selected language pair, tone preset, and custom tone instruction."""

    source: str = config.DEFAULT_UI_SOURCE
    target: str = config.DEFAULT_UI_TARGET
    tone: str = config.DEFAULT_TONE
    custom_tone: str = ""

    def instruction(self) -> str:
        """Return the prompt instruction for the selected tone."""
        if self.tone == config.CUSTOM_TONE:
            custom = self.custom_tone.strip()
            return custom or config.TONES[config.DEFAULT_TONE]
        return config.TONES.get(self.tone, config.TONES[config.DEFAULT_TONE])


def _pick(value: object, valid: set[str], default: str) -> str:
    return value if isinstance(value, str) and value in valid else default


def load() -> Settings:
    """Load saved settings, falling back to defaults on any problem."""
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    languages = set(config.LANGUAGES)
    source = _pick(
        data.get("source"), languages | {config.AUTO_SOURCE}, config.DEFAULT_UI_SOURCE
    )
    target = _pick(data.get("target"), languages, config.DEFAULT_UI_TARGET)
    if source == target:
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
    )


def save(settings: Settings) -> None:
    """Write ``settings`` to the settings file."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

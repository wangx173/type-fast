"""Persistent user preferences for the translation tone.

Stored as JSON in ``~/.type-fast/settings.json`` so the chosen tone (and any
custom tone instruction) survives restarts. A missing or unreadable file falls
back to the defaults in :mod:`type_fast.config`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from . import config
from .providers._common import CONFIG_DIR

SETTINGS_FILE = CONFIG_DIR / "settings.json"


@dataclass
class ToneSettings:
    """The selected tone preset and the user's custom tone instruction."""

    tone: str = config.DEFAULT_TONE
    custom_tone: str = ""

    def instruction(self) -> str:
        """Return the prompt instruction for the selected tone."""
        if self.tone == config.CUSTOM_TONE:
            custom = self.custom_tone.strip()
            return custom or config.TONES[config.DEFAULT_TONE]
        return config.TONES.get(self.tone, config.TONES[config.DEFAULT_TONE])


def load() -> ToneSettings:
    """Load saved tone settings, falling back to defaults on any problem."""
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ToneSettings()
    if not isinstance(data, dict):
        return ToneSettings()
    tone = data.get("tone")
    custom = data.get("custom_tone")
    valid = set(config.TONES) | {config.CUSTOM_TONE}
    return ToneSettings(
        tone=tone if tone in valid else config.DEFAULT_TONE,
        custom_tone=custom if isinstance(custom, str) else "",
    )


def save(settings: ToneSettings) -> None:
    """Write ``settings`` to the settings file."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

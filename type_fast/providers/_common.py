"""Helpers shared by the provider modules.

Credentials are read from an environment variable, or, when that is not set
(e.g. when the packaged ``.app`` is launched from Finder, which does not inherit
your shell environment), from a fallback file under ``~/.type-fast/``.
"""

from __future__ import annotations

import os
from pathlib import Path

# Directory holding the fallback credential files.
CONFIG_DIR = Path.home() / ".type-fast"


def from_env_or_file(env_var: str, file_path: Path) -> str:
    """Return ``env_var`` if set, else the trimmed contents of ``file_path``."""
    value = os.environ.get(env_var)
    if not value and file_path.is_file():
        value = file_path.read_text(encoding="utf-8").strip()
    return (value or "").strip()

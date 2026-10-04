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
    value = (os.environ.get(env_var) or "").strip()
    if not value and file_path.is_file():
        value = file_path.read_text(encoding="utf-8").strip()
    return value


def write_or_clear(file_path: Path, value: str) -> None:
    """Write ``value`` to ``file_path``, or delete the file if it is blank."""
    value = value.strip()
    if not value:
        file_path.unlink(missing_ok=True)
        return
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(value, encoding="utf-8")


def write_private(file_path: Path, value: str) -> None:
    """Write ``value`` to ``file_path`` so only your account can read it.

    The file is created with owner-only permissions, and an existing file is
    restricted before anything is written to it.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(file_path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.ftruncate(fd, 0)
        os.write(fd, value.strip().encode("utf-8"))
    finally:
        os.close(fd)

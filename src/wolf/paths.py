"""Filesystem locations shared by installed WOLF commands."""

from __future__ import annotations

import os
from pathlib import Path


def state_root() -> Path:
    """Return WOLF's user state root, honoring the test/development override."""
    configured = os.environ.get("WOLF_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".wolf").resolve()


def environments_dir() -> Path:
    return state_root() / "envs"


def processes_dir() -> Path:
    return state_root() / "config"

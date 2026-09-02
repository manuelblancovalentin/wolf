"""Filesystem locations shared by installed WOLF commands."""

from __future__ import annotations

import os
from pathlib import Path

from wolf.config import ConfigStore, xdg_cache_root, xdg_data_root


def state_root() -> Path:
    """Return WOLF's data root, honoring the compatibility/test override."""
    configured = os.environ.get("WOLF_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    configured = ConfigStore().get("paths.data")
    return Path(configured).expanduser().resolve() if configured else xdg_data_root()


def environments_dir() -> Path:
    if os.environ.get("WOLF_HOME"):
        return state_root() / "envs"
    configured = ConfigStore().get("paths.environments")
    return Path(configured).expanduser().resolve() if configured else state_root() / "environments"


def processes_dir() -> Path:
    return state_root() / ("config" if os.environ.get("WOLF_HOME") else "processes")


def packages_dir() -> Path:
    if os.environ.get("WOLF_HOME"):
        return state_root() / "packages"
    configured = ConfigStore().get("paths.packages")
    return Path(configured).expanduser().resolve() if configured else state_root() / "packages"


def cache_dir() -> Path:
    if os.environ.get("WOLF_HOME"):
        return state_root() / "cache"
    configured = ConfigStore().get("paths.cache")
    return Path(configured).expanduser().resolve() if configured else xdg_cache_root()


def registries_dir() -> Path:
    return state_root() / "registries"

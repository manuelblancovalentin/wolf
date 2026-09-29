"""Filesystem locations shared by installed WOLF commands."""

from __future__ import annotations

import os
from pathlib import Path
import sys

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


def builtin_flow_root(name: str) -> Path:
    """Locate a WOLF-shipped default flow's real, editable Tcl scripts.

    These are ordinary files WOLF ships and never regenerates -- readable,
    browsable, and the recommended `wolf flow init --from` source for a
    project that wants its own editable clone. This only resolves the
    bundled default; an environment whose flow package is installed uses
    that package's own content path instead.
    """
    configured = os.environ.get("WOLF_LEGACY_ROOT")
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser() / "flows" / name)
    # Source and editable installs.
    candidates.append(Path(__file__).resolve().parents[2] / "flows" / name)
    # Conventional data-files location for a regular installation.
    candidates.append(Path(sys.prefix) / "share" / "wolf" / "flows" / name)
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    raise FileNotFoundError(
        f"WOLF's built-in {name!r} flow scripts could not be located; reinstall WOLF"
    )

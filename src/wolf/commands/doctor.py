"""Basic, backend-neutral installation diagnostics."""

from __future__ import annotations

import argparse
import os
import platform
import shutil

from wolf import __version__
from wolf import ui
from wolf.paths import packages_dir, state_root
from wolf.config import ConfigStore
from wolf.paths import registries_dir
from wolf.registry import RegistryManager
from wolf.backend.orfs import _runtime_diagnostic


def _optional_tool(name: str) -> str:
    location = shutil.which(name)
    if location:
        return f"available ({location}; optional, not required)"
    return "unavailable (optional, not required)"


def _package_root_status() -> str:
    root = packages_dir()
    probe = root
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if probe.is_dir() and os.access(probe, os.W_OK | os.X_OK):
        return f"available ({root}; writable when created)"
    return f"unavailable ({root}; nearest existing parent is not writable)"


def command_doctor(_args: argparse.Namespace) -> int:
    git = shutil.which("git")
    ui.key_value("WOLF version", f"{__version__} (available)")
    ui.key_value("Python", f"{platform.python_version()} (available)")
    ui.key_value("Operating system", f"{platform.platform()} (available)")
    config = ConfigStore()
    config_valid = True
    try:
        config.load()
        ui.key_value("Configuration", f"valid ({config.path})" if config.path.exists()
                     else f"valid defaults ({config.path} not created)")
    except ValueError as error:
        config_valid = False
        ui.key_value("Configuration", f"invalid ({error})")
    if config_valid:
        ui.key_value("WOLF state root", f"{state_root()} (available)")
    ui.key_value("Git", "available (" + git + ")" if git else "unavailable")
    if config_valid:
        ui.key_value("Package store", _package_root_status())
        registry_root = registries_dir()
        ui.key_value("Registry store", f"available ({registry_root})")
        try:
            manager = RegistryManager()
            for spec in manager.specs():
                ui.key_value(f"Registry {spec.name}", manager.status(spec))
        except ValueError as error:
            ui.key_value("Configured registries", f"invalid ({error})")
        preferred = config.get("container.preferred_runtime")
        if preferred:
            diagnostic = _runtime_diagnostic(preferred)
            ui.key_value("Preferred runtime", f"{preferred}: {diagnostic.detail}")
        else:
            ui.key_value("Preferred runtime", "not configured (optional)")
    ui.key_value("Docker", _optional_tool("docker"))
    ui.key_value("Podman", _optional_tool("podman"))
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("doctor", help="report basic WOLF runtime facts")
    parser.set_defaults(
        handler=command_doctor,
        ui_kind="wolf",
        ui_section="Installation diagnostics",
    )

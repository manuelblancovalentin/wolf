"""Basic, backend-neutral installation diagnostics."""

from __future__ import annotations

import argparse
import platform
import shutil

from wolf import __version__
from wolf import ui
from wolf.paths import state_root


def _optional_tool(name: str) -> str:
    location = shutil.which(name)
    if location:
        return f"available ({location}; optional, not required)"
    return "unavailable (optional, not required)"


def command_doctor(_args: argparse.Namespace) -> int:
    git = shutil.which("git")
    ui.key_value("WOLF version", f"{__version__} (available)")
    ui.key_value("Python", f"{platform.python_version()} (available)")
    ui.key_value("Operating system", f"{platform.platform()} (available)")
    ui.key_value("WOLF state root", f"{state_root()} (available)")
    ui.key_value("Git", "available (" + git + ")" if git else "unavailable")
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

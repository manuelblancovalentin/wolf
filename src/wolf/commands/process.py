"""Read-only compatibility view of configured processes."""

from __future__ import annotations

import argparse

from wolf.paths import processes_dir
from wolf import ui


def command_list(_args: argparse.Namespace) -> int:
    root = processes_dir()
    names = sorted(path.name for path in root.iterdir() if path.is_dir()) if root.is_dir() else []
    if not names:
        ui.info("No WOLF processes found.")
        return 0
    for name in names:
        ui.entry(name)
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("process", help="inspect legacy process definitions")
    commands = parser.add_subparsers(dest="process_command", required=True)
    list_parser = commands.add_parser("list", help="list configured processes")
    list_parser.set_defaults(
        handler=command_list,
        ui_kind="process",
        ui_section="Available processes",
    )

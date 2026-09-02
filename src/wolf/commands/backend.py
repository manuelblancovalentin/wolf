"""Inspect WOLF's built-in backend registry."""

from __future__ import annotations

import argparse

from wolf import ui
from wolf.backend import backend_names, get_backend


def command_list(_args: argparse.Namespace) -> int:
    for name in backend_names():
        backend = get_backend(name)
        ui.entry(f"{backend.name} — {backend.description}")
    return 0


def command_info(args: argparse.Namespace) -> int:
    backend = get_backend(args.name)
    ui.key_value("Name", backend.name)
    ui.key_value("Description", backend.description)
    ui.key_value("Legacy adapter", backend.adapter_filename)
    if hasattr(backend, "execution_style"):
        ui.key_value("Execution style", backend.execution_style)
    ui.key_value("Local validation", "")
    for item in backend.validate():
        status = "available" if item.available else "unavailable"
        ui.key_value(f"  {item.name}", f"{status} ({item.detail})")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("backend", help="inspect built-in execution backends")
    commands = parser.add_subparsers(dest="backend_command", required=True)

    list_parser = commands.add_parser("list", help="list built-in backends")
    list_parser.set_defaults(
        handler=command_list,
        ui_kind="wolf",
        ui_section="Available backends",
    )

    info_parser = commands.add_parser("info", help="show backend details")
    info_parser.add_argument("name")
    info_parser.set_defaults(
        handler=command_info,
        ui_kind="wolf",
        ui_section="Backend details",
    )

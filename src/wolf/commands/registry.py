"""Manage configured package-manifest registries."""

from __future__ import annotations

import argparse

from wolf import __version__, ui
from wolf.package.registry import registry_root
from wolf.registry import RegistryManager


def command_list(_args: argparse.Namespace) -> int:
    ui.key_value("NAME", "TYPE     STATUS       REVISION")
    ui.key_value("builtin", f"builtin  ready        {__version__}")
    manager = RegistryManager()
    for spec in manager.specs():
        revision = manager.revision(spec)
        ui.key_value(spec.name, f"{spec.type:<8} {manager.status(spec):<12} {(revision or '-')[:12]}")
    return 0


def command_add(args: argparse.Namespace) -> int:
    spec = RegistryManager().add(args.name, args.source, args.type, args.priority)
    ui.success(f"Added {spec.type} registry {spec.name}")
    return 0


def command_info(args: argparse.Namespace) -> int:
    if args.name == "builtin":
        ui.key_value("Registry", "builtin")
        ui.key_value("Type", "builtin")
        ui.key_value("Location", registry_root())
        ui.key_value("Revision", __version__)
        ui.key_value("Status", "ready")
        return 0
    manager = RegistryManager()
    spec = manager.get(args.name)
    ui.key_value("Registry", spec.name)
    ui.key_value("Type", spec.type)
    ui.key_value("Source", spec.source)
    ui.key_value("Location", manager.content_root(spec))
    ui.key_value("Priority", spec.priority)
    ui.key_value("Revision", manager.revision(spec) or "not applicable")
    ui.key_value("Status", manager.status(spec))
    return 0


def command_sync(args: argparse.Namespace) -> int:
    selected = RegistryManager().sync(args.name)
    for spec in selected:
        if spec.type == "git":
            ui.success(f"Synchronized registry {spec.name}")
        else:
            ui.info(f"Local registry {spec.name} uses its current files")
    return 0


def command_remove(args: argparse.Namespace) -> int:
    spec = RegistryManager().remove(args.name)
    ui.success(f"Removed registry {spec.name}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("registry", help="manage package-manifest registries")
    commands = parser.add_subparsers(dest="registry_command", required=True)
    list_parser = commands.add_parser("list", help="list configured registries")
    list_parser.set_defaults(handler=command_list, ui_kind="wolf", ui_section="Package registries")
    add_parser = commands.add_parser("add", help="add a local or Git registry")
    add_parser.add_argument("name")
    add_parser.add_argument("source")
    add_parser.add_argument("--type", choices=("git", "local"))
    add_parser.add_argument("--priority", type=int, default=100)
    add_parser.set_defaults(handler=command_add, ui_kind="wolf", ui_section="Add package registry")
    info_parser = commands.add_parser("info", help="show registry details")
    info_parser.add_argument("name")
    info_parser.set_defaults(handler=command_info, ui_kind="wolf", ui_section="Registry information")
    sync_parser = commands.add_parser("sync", help="explicitly update Git registries")
    sync_parser.add_argument("name", nargs="?")
    sync_parser.set_defaults(handler=command_sync, ui_kind="wolf", ui_section="Registry synchronization")
    remove_parser = commands.add_parser("remove", help="remove a configured registry")
    remove_parser.add_argument("name")
    remove_parser.set_defaults(handler=command_remove, ui_kind="wolf", ui_section="Remove package registry")

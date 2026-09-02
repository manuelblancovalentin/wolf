"""Inspect and update persistent global WOLF configuration."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess

from wolf import ui
from wolf.config import CONFIG_KEYS, ConfigStore


def _display(value) -> str:
    if value is None:
        return "not configured"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def command_list(_args: argparse.Namespace) -> int:
    store = ConfigStore()
    ui.key_value("Configuration file", store.path)
    for key in CONFIG_KEYS:
        ui.key_value(key, _display(store.get(key)))
    return 0


def command_get(args: argparse.Namespace) -> int:
    print(_display(ConfigStore().get(args.key)))
    return 0


def _parse_value(key: str, raw: str):
    if key == "shell.prompt":
        values = {"true": True, "false": False}
        if raw.lower() not in values:
            raise ValueError("shell.prompt must be true or false")
        return values[raw.lower()]
    if key == "container.preferred_runtime" and raw not in {"podman", "docker"}:
        raise ValueError("container.preferred_runtime must be podman or docker")
    return raw


def command_set(args: argparse.Namespace) -> int:
    value = ConfigStore().set(args.key, _parse_value(args.key, args.value))
    ui.success(f"Set {args.key} = {_display(value)}")
    return 0


def command_unset(args: argparse.Namespace) -> int:
    ConfigStore().unset(args.key)
    ui.success(f"Unset {args.key}")
    return 0


def command_path(_args: argparse.Namespace) -> int:
    print(ConfigStore().path)
    return 0


def command_edit(_args: argparse.Namespace) -> int:
    store = ConfigStore()
    if not store.path.exists():
        store.write(store.load())
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        raise ValueError("set VISUAL or EDITOR before using wolf config edit")
    return subprocess.run([*shlex.split(editor), str(store.path)], check=False).returncode


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("config", help="manage global WOLF configuration")
    commands = parser.add_subparsers(dest="config_command", required=True)
    list_parser = commands.add_parser("list", help="show effective configuration")
    list_parser.set_defaults(handler=command_list, ui_kind="wolf", ui_section="Global configuration")
    get_parser = commands.add_parser("get", help="print one effective value")
    get_parser.add_argument("key", choices=CONFIG_KEYS)
    get_parser.set_defaults(handler=command_get, suppress_ui=True)
    set_parser = commands.add_parser("set", help="persist one value")
    set_parser.add_argument("key", choices=CONFIG_KEYS)
    set_parser.add_argument("value")
    set_parser.set_defaults(handler=command_set, ui_kind="wolf", ui_section="Global configuration")
    unset_parser = commands.add_parser("unset", help="remove one persisted value")
    unset_parser.add_argument("key", choices=CONFIG_KEYS)
    unset_parser.set_defaults(handler=command_unset, ui_kind="wolf", ui_section="Global configuration")
    path_parser = commands.add_parser("path", help="print the configuration file path")
    path_parser.set_defaults(handler=command_path, suppress_ui=True)
    edit_parser = commands.add_parser("edit", help="open configuration in VISUAL or EDITOR")
    edit_parser.set_defaults(handler=command_edit, suppress_ui=True)

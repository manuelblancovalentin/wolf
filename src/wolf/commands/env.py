"""Compatibility-oriented environment commands."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex

from wolf.legacy import LegacyCommandError, run_env
from wolf.paths import environments_dir
from wolf import ui


_VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _environment_path(name: str) -> Path:
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError(f"invalid environment name: {name!r}")
    return environments_dir() / name


def _existing_environment(name: str) -> Path:
    path = _environment_path(name)
    if not path.is_dir():
        raise ValueError(f"WOLF environment {name!r} does not exist")
    return path


def _environment_names() -> list[str]:
    root = environments_dir()
    if not root.is_dir():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir())


def _read_variables(path: Path) -> list[tuple[str, str]]:
    variables = []
    variables_file = path / "vars.env"
    if not variables_file.is_file():
        return variables
    for line in variables_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        try:
            parsed = shlex.split(raw_value, posix=True)
            value = parsed[0] if len(parsed) == 1 else raw_value
        except ValueError:
            value = raw_value
        variables.append((key, value))
    return variables


def command_list(_args: argparse.Namespace) -> int:
    names = _environment_names()
    if not names:
        ui.info("No WOLF environments found.")
        return 0
    for name in names:
        ui.entry(name)
    return 0


def command_create(args: argparse.Namespace) -> int:
    path = _environment_path(args.name)
    if path.exists() or path.is_symlink():
        raise ValueError(f"WOLF environment {args.name!r} already exists")
    if os.environ.get("WOLF_ENV_NAME"):
        raise ValueError("deactivate the current WOLF environment before creating one")
    run_env(["create", "--name", args.name])
    if not path.is_dir():
        raise LegacyCommandError("legacy environment creation did not create the environment")
    ui.success(f"Created WOLF environment {args.name!r} at {path}")
    return 0


def command_show(args: argparse.Namespace) -> int:
    path = _existing_environment(args.name)
    ui.key_value("Name", args.name)
    ui.key_value("Path", path)

    variables = _read_variables(path)
    ui.key_value("Variables", "")
    if variables:
        for key, value in variables:
            ui.key_value(f"  {key}", value)
    else:
        ui.info("No stored variables.")

    bucket_file = path / "bucket.p"
    bucket_count = 0
    if bucket_file.is_file():
        bucket_count = sum(
            1
            for line in bucket_file.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("source ")
        )
    ui.key_value("Bucket inputs", bucket_count)
    return 0


def command_remove(args: argparse.Namespace) -> int:
    path = _existing_environment(args.name)
    if os.environ.get("WOLF_ENV_NAME"):
        raise ValueError("deactivate the current WOLF environment before removing one")
    if not args.yes:
        answer = input(f"Remove WOLF environment {args.name!r} permanently? [y/N] ")
        if answer.lower() not in {"y", "yes"}:
            ui.info(f"WOLF environment {args.name!r} was not removed")
            return 0
    run_env(["remove", "--yes", "--name", args.name])
    if path.exists() or path.is_symlink():
        raise LegacyCommandError("legacy environment removal did not remove the environment")
    ui.success(f"Removed WOLF environment {args.name!r}")
    return 0


def command_set(args: argparse.Namespace) -> int:
    path = _existing_environment(args.name)
    if not _VARIABLE_NAME.fullmatch(args.key):
        raise ValueError(f"invalid environment variable name: {args.key!r}")
    legacy_error = None
    try:
        run_env(["set", args.name, args.key, args.value], environment_name=args.name)
    except LegacyCommandError as error:
        # Legacy Bash may return the status of its in-process export even after
        # correctly persisting a value containing whitespace. Verify the file
        # postcondition before deciding whether the operation failed.
        legacy_error = error
    values = dict(_read_variables(path))
    if values.get(args.key) != args.value.replace('"', ""):
        if legacy_error is not None:
            raise legacy_error
        raise LegacyCommandError("legacy environment variable update was not persisted")
    if legacy_error is not None and str(legacy_error) != "legacy environment operation failed":
        raise legacy_error
    ui.success(f"Set {args.key} in WOLF environment {args.name!r}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("env", help="manage WOLF environments")
    commands = parser.add_subparsers(dest="env_command", required=True)

    list_parser = commands.add_parser("list", help="list environments")
    list_parser.set_defaults(
        handler=command_list,
        ui_kind="env",
        ui_section="Available environments",
    )

    create_parser = commands.add_parser("create", help="create an environment")
    create_parser.add_argument("name")
    create_parser.set_defaults(
        handler=command_create,
        ui_kind="env",
        ui_section="Environment creation",
    )

    show_parser = commands.add_parser("show", help="show environment state")
    show_parser.add_argument("name")
    show_parser.set_defaults(
        handler=command_show,
        ui_kind="env",
        ui_section="Environment details",
    )

    remove_parser = commands.add_parser("remove", help="remove an environment")
    remove_parser.add_argument("name")
    remove_parser.add_argument("-y", "--yes", action="store_true", help="do not prompt")
    remove_parser.set_defaults(
        handler=command_remove,
        ui_kind="env",
        ui_section="Environment removal",
    )

    set_parser = commands.add_parser("set", help="persist an environment variable")
    set_parser.add_argument("name")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    set_parser.set_defaults(
        handler=command_set,
        ui_kind="env",
        ui_section="Environment update",
    )

"""Compatibility-oriented environment commands."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile

import yaml

from wolf.environment import ENVIRONMENT_FILENAME, load_environment, normalize_environment
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
    if args.from_file:
        source = Path(args.from_file).expanduser().resolve()
        # Validate before creating any environment state.
        load_environment(source, expected_name=args.name)
        root = path.parent
        root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{args.name}-", dir=root))
        try:
            normalize_environment(source, staging / ENVIRONMENT_FILENAME, name=args.name)
            staging.replace(path)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        ui.success(f"Created declarative WOLF environment {args.name!r} at {path}")
        return 0
    run_env(["create", "--name", args.name])
    if not path.is_dir():
        raise LegacyCommandError("legacy environment creation did not create the environment")
    ui.success(f"Created WOLF environment {args.name!r} at {path}")
    return 0


def command_remove(args: argparse.Namespace) -> int:
    path = _existing_environment(args.name)
    if os.environ.get("WOLF_ENV_NAME") or os.environ.get("WOLF_ACTIVE_ENV") == args.name:
        raise ValueError("deactivate the current WOLF environment before removing one")
    if not args.yes:
        answer = input(f"Remove WOLF environment {args.name!r} permanently? [y/N] ")
        if answer.lower() not in {"y", "yes"}:
            ui.info(f"WOLF environment {args.name!r} was not removed")
            return 0
    if (path / ENVIRONMENT_FILENAME).is_file():
        shutil.rmtree(path)
    else:
        run_env(["remove", "--yes", "--name", args.name])
    if path.exists() or path.is_symlink():
        raise LegacyCommandError("legacy environment removal did not remove the environment")
    ui.success(f"Removed WOLF environment {args.name!r}")
    return 0


def command_set(args: argparse.Namespace) -> int:
    path = _existing_environment(args.name)
    manifest = path / ENVIRONMENT_FILENAME
    if manifest.is_file():
        _set_declarative_value(manifest, args.key, args.value, args.name)
        ui.success(f"Set {args.key} in WOLF environment {args.name!r}")
        return 0
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


def _structured_parts(key: str) -> list[str | int]:
    parts: list[str | int] = []
    for item in key.split("."):
        if not item:
            raise ValueError(f"invalid structured environment key: {key!r}")
        parts.append(int(item) if item.isdigit() else item)
    return parts


def _set_declarative_value(path: Path, key: str, raw_value: str, name: str) -> None:
    if key in {"schema", "name"}:
        raise ValueError(f"wolf env set cannot change {key}; edit or clone the environment instead")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    parts = _structured_parts(key)
    current = data
    for index, part in enumerate(parts[:-1]):
        field = ".".join(str(value) for value in parts[: index + 1])
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                raise ValueError(f"structured environment path does not exist: {field}")
        elif not isinstance(current, dict) or part not in current:
            raise ValueError(f"structured environment path does not exist: {field}")
        current = current[part]
    final = parts[-1]
    if isinstance(final, int):
        if not isinstance(current, list) or final >= len(current):
            raise ValueError(f"structured environment path does not exist: {key}")
    elif not isinstance(current, dict):
        raise ValueError(f"structured environment parent is not a mapping: {key}")
    current[final] = yaml.safe_load(raw_value)
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    try:
        load_environment(temporary, expected_name=name)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def command_clone(args: argparse.Namespace) -> int:
    source = _existing_environment(args.source)
    destination = _environment_path(args.destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"WOLF environment {args.destination!r} already exists")
    manifest = source / ENVIRONMENT_FILENAME
    if not manifest.is_file():
        raise ValueError("wolf env clone currently supports declarative-v1 environments only")
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["name"] = args.destination
    root = destination.parent
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{args.destination}-", dir=root))
    try:
        target = staging / ENVIRONMENT_FILENAME
        target.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        load_environment(target, expected_name=args.destination)
        staging.replace(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    ui.success(f"Cloned WOLF environment {args.source!r} to {args.destination!r}")
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
    create_parser.add_argument("--from", dest="from_file", metavar="FILE",
                               help="create from a declarative WOLF YAML file")
    create_parser.set_defaults(
        handler=command_create,
        ui_kind="env",
        ui_section="Environment creation",
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

    clone_parser = commands.add_parser("clone", help="clone a declarative environment")
    clone_parser.add_argument("source")
    clone_parser.add_argument("destination")
    clone_parser.set_defaults(
        handler=command_clone,
        ui_kind="env",
        ui_section="Environment clone",
    )

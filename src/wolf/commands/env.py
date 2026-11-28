"""Compatibility-oriented environment commands."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile
from typing import Optional

import yaml

from wolf.backend.cadence_genus_setup import (
    DESIGN_SETUP_ALLOWED_KEYS, design_setup_path, flow_design_setup_keys, set_design_setup_value,
)
from wolf.commands.common import resolve_environment_name
from wolf.environment import (
    ENVIRONMENT_FILENAME, environment_manifest, load_environment, normalize_environment,
    profile_semantics, resolve_flow_design_setup_template, resolve_stored_path,
)
from wolf.legacy import LegacyCommandError, run_env
from wolf.paths import environments_dir
from wolf.project_tree import (
    PER_DESIGN_INPUT_CATEGORIES, SHARED_LIB_SUBDIRS, link_environment_file, scaffold_project_tree,
)
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


def command_menu(args: argparse.Namespace) -> int:
    from wolf.env_menu import EnvWizardApp

    name = resolve_environment_name(args.name)
    EnvWizardApp(name).run()
    return 0


def command_remove(args: argparse.Namespace) -> int:
    name = resolve_environment_name(args.name)
    path = _existing_environment(name)
    if os.environ.get("WOLF_ENV_NAME") or os.environ.get("WOLF_ACTIVE_ENV") == name:
        raise ValueError("deactivate the current WOLF environment before removing one")
    if not args.yes:
        answer = input(f"Remove WOLF environment {name!r} permanently? [y/N] ")
        if answer.lower() not in {"y", "yes"}:
            ui.info(f"WOLF environment {name!r} was not removed")
            return 0
    if (path / ENVIRONMENT_FILENAME).is_file():
        shutil.rmtree(path)
    else:
        run_env(["remove", "--yes", "--name", name])
    if path.exists() or path.is_symlink():
        raise LegacyCommandError("legacy environment removal did not remove the environment")
    ui.success(f"Removed WOLF environment {name!r}")
    return 0


def _project_root_and_design_name(manifest: Path, name: str) -> tuple[Path, str]:
    """Resolve an environment's project.root + design name the same
    lightweight way `wolf env auto-setup` already does (profile_semantics,
    not a full ResolvedContext -- no package install required just to set
    a design-level knob or refresh the inputs/env/ reproducibility link)."""
    profile = load_environment(manifest, expected_name=name)
    if not profile.project_root:
        raise ValueError(
            f"environment {name!r} has no project.root configured; "
            "add `project: {root: /path/to/project}` to its wolf.yaml first"
        )
    project_root = resolve_stored_path(profile.project_root, profile.path.parent)
    design_name = profile_semantics(profile)["design"]
    if not design_name:
        raise ValueError(
            f"environment {name!r} has no resolvable design name yet; "
            "set `design: {name: ...}` or `design: {package: rtl/...}` first"
        )
    return project_root, design_name


def _design_setup_path_for_environment(manifest: Path, name: str) -> Path:
    project_root, design_name = _project_root_and_design_name(manifest, name)
    return design_setup_path(project_root, design_name)


def _extra_design_setup_keys(manifest: Path, name: str) -> frozenset[str]:
    """This environment's flow package's own declared design-setup
    keys, if any -- best-effort: a flow package that isn't resolvable
    yet (not installed, no flow selected) simply contributes no extra
    keys, the same as `_sync_reproducibility_link`'s own tolerance for
    "not resolvable yet, not an error"."""
    try:
        profile = load_environment(manifest, expected_name=name)
        flow_package = profile.flow.package if profile.flow else None
        template_path, _source = resolve_flow_design_setup_template(
            flow_package, override=profile.env_vars.get("DESIGN_SETUP_TEMPLATE"),
        )
        return flow_design_setup_keys(template_path)
    except Exception:
        return frozenset()


def _sync_reproducibility_link(manifest: Path, name: str) -> None:
    """Keep inputs/env/<design>/wolf.<name>.yaml pointed at this
    environment's own wolf.yaml after any `wolf env set`/`unset` -- same
    link `wolf env menu`'s own save already maintains. Project root or
    design name not (yet) resolvable just means there is nothing to link
    yet, not a failed set/unset."""
    try:
        project_root, design_name = _project_root_and_design_name(manifest, name)
    except ValueError:
        return
    link_environment_file(project_root, design_name, name, manifest)
    _sync_description_file(manifest, name, project_root, design_name)


def _sync_description_file(manifest: Path, name: str, project_root: Path, design_name: str) -> None:
    """Refresh this environment's sanitized description (a real file,
    never a link -- see `wolf.env_describe`) next to its definition in
    the project, same trigger as the reproducibility link above. A
    description-building failure must never fail a `wolf env set`/
    `unset`; this is best-effort bookkeeping, not the operation itself."""
    try:
        from wolf.env_describe import build_description, write_description

        profile = load_environment(manifest, expected_name=name)
        semantics = profile_semantics(profile)
        variables = dict(profile.env_vars or {})
        description = build_description(
            name, variables,
            design_name=semantics.get("design"),
            process=semantics.get("technology"),
            metal_stack=profile.technology.metal_stack if profile.technology else None,
            project_root=project_root,
        )
        write_description(project_root, design_name, name, description)
    except Exception:
        pass


def command_set(args: argparse.Namespace) -> int:
    name = resolve_environment_name(args.name)
    path = _existing_environment(name)
    manifest = path / ENVIRONMENT_FILENAME
    if manifest.is_file():
        key_root = args.key.split(".", 1)[0]
        extra_keys = _extra_design_setup_keys(manifest, name)
        if key_root in DESIGN_SETUP_ALLOWED_KEYS or key_root in extra_keys:
            setup_path = _design_setup_path_for_environment(manifest, name)
            set_design_setup_value(
                setup_path, args.key, yaml.safe_load(args.value), extra_keys=extra_keys,
            )
            _sync_reproducibility_link(manifest, name)
            ui.success(f"Set {args.key} in {setup_path}")
            return 0
        _set_declarative_value(manifest, args.key, args.value, name)
        _sync_reproducibility_link(manifest, name)
        ui.success(f"Set {args.key} in WOLF environment {name!r}")
        return 0
    if not _VARIABLE_NAME.fullmatch(args.key):
        raise ValueError(f"invalid environment variable name: {args.key!r}")
    legacy_error = None
    try:
        run_env(["set", name, args.key, args.value], environment_name=name)
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
    ui.success(f"Set {args.key} in WOLF environment {name!r}")
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


def _unset_declarative_value(path: Path, key: str, name: str) -> None:
    """Remove one dotted key from wolf.yaml, pruning now-empty parent
    mappings -- the wolf.yaml-side counterpart to `_set_declarative_value`,
    same atomic write pattern. A key, or any segment of its path, that
    simply isn't set is a no-op, not an error (mirrors
    cadence_genus_setup.set_design_setup_value's own unset semantics)."""
    if key in {"schema", "name"}:
        raise ValueError(f"wolf env unset cannot remove {key}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    parts = _structured_parts(key)
    chain: list = [data]
    node = data
    for part in parts[:-1]:
        if isinstance(part, int):
            if not isinstance(node, list) or part >= len(node):
                return
        elif not isinstance(node, dict) or part not in node:
            return
        node = node[part]
        chain.append(node)
    final = parts[-1]
    if isinstance(final, int):
        if isinstance(node, list) and final < len(node):
            del node[final]
    elif isinstance(node, dict):
        node.pop(final, None)
    for index in range(len(chain) - 1, 0, -1):
        if isinstance(chain[index], dict) and not chain[index]:
            parent = chain[index - 1]
            if isinstance(parent, dict):
                parent.pop(parts[index - 1], None)
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    try:
        load_environment(temporary, expected_name=name)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def command_unset(args: argparse.Namespace) -> int:
    name = resolve_environment_name(args.name)
    path = _existing_environment(name)
    manifest = path / ENVIRONMENT_FILENAME
    if not manifest.is_file():
        raise ValueError(
            "wolf env unset supports declarative-v1 environments only; "
            "edit the legacy vars.env file directly to remove a legacy variable"
        )
    key_root = args.key.split(".", 1)[0]
    extra_keys = _extra_design_setup_keys(manifest, name)
    if key_root in DESIGN_SETUP_ALLOWED_KEYS or key_root in extra_keys:
        setup_path = _design_setup_path_for_environment(manifest, name)
        set_design_setup_value(setup_path, args.key, None, extra_keys=extra_keys)
        _sync_reproducibility_link(manifest, name)
        ui.success(f"Unset {args.key} in {setup_path}")
        return 0
    _unset_declarative_value(manifest, args.key, name)
    _sync_reproducibility_link(manifest, name)
    ui.success(f"Unset {args.key} in WOLF environment {name!r}")
    return 0


def command_clone(args: argparse.Namespace) -> int:
    source = _existing_environment(resolve_environment_name(args.source))
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


def command_auto_setup(args: argparse.Namespace) -> int:
    name = resolve_environment_name(args.name)
    environment_directory = _existing_environment(name)
    manifest = environment_manifest(environment_directory)
    if manifest is None:
        raise ValueError(
            "wolf env auto-setup supports declarative-v1 environments only; "
            "the legacy vars.env format has its own scaffold via the Bash wolf env"
        )
    profile = load_environment(manifest, expected_name=name)
    if not profile.project_root:
        raise ValueError(
            f"environment {name!r} has no project.root configured; "
            "add `project: {root: /path/to/project}` to its wolf.yaml first"
        )
    project_root = resolve_stored_path(profile.project_root, profile.path.parent)
    design_name = profile_semantics(profile)["design"]
    if not design_name:
        raise ValueError(
            f"environment {name!r} has no resolvable design name yet; "
            "set `design: {name: ...}` or `design: {package: rtl/...}` first"
        )

    planned: list[Path] = [
        project_root,
        project_root / "inputs",
        project_root / "outputs",
        project_root / "outputs" / design_name,
        project_root / "workspace",
    ]
    for category in PER_DESIGN_INPUT_CATEGORIES:
        planned.append(project_root / "inputs" / category / design_name)
    for shared in SHARED_LIB_SUBDIRS:
        planned.append(project_root / "inputs" / "lib" / shared)
    created = set(scaffold_project_tree(project_root, design_name))
    link_environment_file(project_root, design_name, name, manifest)

    for path in planned:
        relative = path.relative_to(project_root) if path != project_root else Path(".")
        ui.key_value(str(relative), "created" if path in created else "already present")
    ui.success(f"Project directory structure ready at {project_root}")
    return 0


def command_describe(args: argparse.Namespace) -> int:
    from wolf.env_describe import build_description, write_description

    write_target: Optional[tuple[Path, str]] = None  # (project_root, design_name)

    if args.file:
        manifest = Path(args.file).expanduser().resolve()
        name = resolve_environment_name(args.name) if args.name else manifest.stem
        profile = load_environment(manifest, expected_name=name)
        semantics = profile_semantics(profile)
        variables = dict(profile.env_vars or {})
        project_root = (
            resolve_stored_path(profile.project_root, profile.path.parent)
            if profile.project_root else None
        )
        design_name = semantics.get("design")
        process = semantics.get("technology")
        metal_stack = profile.technology.metal_stack if profile.technology else None
    else:
        name = resolve_environment_name(args.name)
        path = _existing_environment(name)
        manifest = path / ENVIRONMENT_FILENAME
        if manifest.is_file():
            profile = load_environment(manifest, expected_name=name)
            semantics = profile_semantics(profile)
            variables = dict(profile.env_vars or {})
            project_root = (
                resolve_stored_path(profile.project_root, profile.path.parent)
                if profile.project_root else None
            )
            metal_stack = profile.technology.metal_stack if profile.technology else None
            design_name = semantics.get("design")
            process = semantics.get("technology")
        else:
            values = dict(_read_variables(path))
            variables = {
                key: value for key, value in values.items()
                if key not in {"DESIGN_NAME", "PROCESS", "METAL_STACK", "PROJ_DIR"}
            }
            project_root = Path(values["PROJ_DIR"]).expanduser() if values.get("PROJ_DIR") else None
            metal_stack = values.get("METAL_STACK")
            design_name = values.get("DESIGN_NAME")
            process = values.get("PROCESS")
        if project_root and design_name:
            write_target = (project_root, design_name)

    description = build_description(
        name, variables, design_name=design_name, process=process,
        metal_stack=metal_stack, project_root=project_root,
    )
    if write_target:
        write_description(write_target[0], write_target[1], name, description)

    if args.json:
        import json
        print(json.dumps(description, sort_keys=True, indent=2))
        return 0
    ui.key_value("Environment", description["environment"])
    ui.key_value("Design", description["design"] or "unknown")
    ui.key_value("Process", description["process"] or "unknown")
    ui.key_value("Metal stack", description["metal_stack"] or "unknown")
    ui.key_value("Variables", "")
    for key, value in sorted(description["variables"].items()):
        ui.key_value(f"  {key}", value if value is not None else "<unset>")
    ui.key_value("Activate and work with this design", "")
    for line in description["activation_commands"]:
        ui.info(f"    {line}")
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

    menu_parser = commands.add_parser("menu", help="interactively create or edit an environment")
    menu_parser.add_argument("name", nargs="?", help="defaults to the active environment")
    menu_parser.set_defaults(handler=command_menu, suppress_ui=True)

    remove_parser = commands.add_parser("remove", help="remove an environment")
    remove_parser.add_argument("name", nargs="?", help="defaults to the active environment")
    remove_parser.add_argument("-y", "--yes", action="store_true", help="do not prompt")
    remove_parser.set_defaults(
        handler=command_remove,
        ui_kind="env",
        ui_section="Environment removal",
    )

    set_parser = commands.add_parser("set", help="persist an environment variable")
    set_parser.add_argument("name", nargs="?", help="defaults to the active environment")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    set_parser.set_defaults(
        handler=command_set,
        ui_kind="env",
        ui_section="Environment update",
    )

    unset_parser = commands.add_parser(
        "unset", help="remove an environment variable or design-level setup.yaml key"
    )
    unset_parser.add_argument("name", nargs="?", help="defaults to the active environment")
    unset_parser.add_argument("key")
    unset_parser.set_defaults(
        handler=command_unset,
        ui_kind="env",
        ui_section="Environment update",
    )

    clone_parser = commands.add_parser("clone", help="clone a declarative environment")
    clone_parser.add_argument("source", nargs="?", help="defaults to the active environment")
    clone_parser.add_argument("destination")
    clone_parser.set_defaults(
        handler=command_clone,
        ui_kind="env",
        ui_section="Environment clone",
    )

    auto_setup_parser = commands.add_parser(
        "auto-setup", help="scaffold a project's inputs/outputs/workspace directories"
    )
    auto_setup_parser.add_argument("name", nargs="?", help="defaults to the active environment")
    auto_setup_parser.set_defaults(
        handler=command_auto_setup,
        ui_kind="env",
        ui_section="Project directory structure",
    )

    describe_parser = commands.add_parser(
        "describe", help="print a sanitized, website-safe description of an environment",
    )
    describe_parser.add_argument("name", nargs="?", help="defaults to the active environment")
    describe_parser.add_argument("--file", help="describe a wolf.yaml file directly, not a stored environment")
    describe_parser.add_argument("--json", action="store_true", help="emit wolf.describe/v1 JSON")
    describe_parser.set_defaults(
        handler=command_describe,
        ui_kind="env",
        ui_section="Environment description",
    )

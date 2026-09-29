"""Bootstrap project-owned, independently editable copies of flow scripts."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

import yaml

from wolf import ui
from wolf.context import resolve_cli_path


def command_init(args: argparse.Namespace) -> int:
    invocation = Path.cwd()
    source = resolve_cli_path(args.source, invocation)
    if not source.is_dir():
        raise ValueError(f"flow source directory does not exist: {source}")
    destination = resolve_cli_path(args.destination, invocation)
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"flow destination already exists: {destination}")
    manifest_path = resolve_cli_path(args.manifest, invocation)
    if manifest_path.exists():
        raise ValueError(f"flow manifest already exists: {manifest_path}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=False)

    scripts_metadata = {"root": "."}
    if args.setup_common_template:
        scripts_metadata["setup_common_template"] = args.setup_common_template
    if args.setup_host_template:
        scripts_metadata["setup_host_template"] = args.setup_host_template
    if args.flow_template:
        scripts_metadata["flow_template"] = args.flow_template

    manifest = {
        "schema_version": 1,
        "kind": "flow",
        "name": args.name,
        "description": args.description or f"Editable flow scripts copied from {source}",
        "source": {
            "type": "local-path",
            "root": str(destination),
            "revision": args.revision,
        },
        "license": {"name": args.license} if args.license else {},
        "validation": {"required_paths": list(args.required_path or [])},
        "metadata": {
            "flow": {
                "name": args.name,
                "backend": args.backend,
                "scripts": scripts_metadata,
            },
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    ui.success(f"Copied flow scripts to {destination}")
    ui.key_value("Manifest", manifest_path)
    ui.info(
        "Register a registry directory containing this manifest with: "
        "wolf registry add <name> <registry-dir> --type local"
    )
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "flow", help="bootstrap independently editable, project-owned flow scripts"
    )
    commands = parser.add_subparsers(dest="flow_command", required=True)
    init_parser = commands.add_parser(
        "init",
        help="copy a base flow's scripts into a new directory the caller can freely edit",
    )
    init_parser.add_argument("name", help="flow package name, e.g. ibex-fabulous-genus-tsmc65")
    init_parser.add_argument(
        "--from", dest="source", required=True, help="base flow scripts directory to copy"
    )
    init_parser.add_argument(
        "--to", dest="destination", required=True,
        help="destination directory for the new, independently editable copy",
    )
    init_parser.add_argument(
        "--manifest", required=True, help="path to write the flow package manifest"
    )
    init_parser.add_argument(
        "--backend", required=True, help="backend this flow targets, e.g. cadence-flowtool"
    )
    init_parser.add_argument(
        "--revision", required=True,
        help="human-readable provenance label for this copy, e.g. a project repo commit",
    )
    init_parser.add_argument("--description")
    init_parser.add_argument("--license")
    init_parser.add_argument(
        "--setup-common-template", dest="setup_common_template",
        help="path, relative to --to, of the common setup template",
    )
    init_parser.add_argument(
        "--setup-host-template", dest="setup_host_template",
        help="path, relative to --to, of the host-specific setup template",
    )
    init_parser.add_argument(
        "--flow-template", dest="flow_template",
        help="path, relative to --to, of the flow step template",
    )
    init_parser.add_argument(
        "--required-path", dest="required_path", action="append",
        help="relative path that must exist for this flow to validate; repeatable",
    )
    init_parser.set_defaults(handler=command_init, ui_kind="flow", ui_section="Flow scripts")

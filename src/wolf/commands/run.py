"""Thin installed-CLI bridge to the existing generic shell runner."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from wolf import ui
from wolf.backend import get_backend
from wolf.commands.env import _environment_path, _read_variables
from wolf.context import ResolvedContext, resolve_context
from wolf.context import resolve_cli_path
from wolf.environment import (
    environment_manifest,
    load_environment,
    resolve_declarative_environment,
)
from wolf.legacy import run_legacy
from wolf.paths import state_root


def _context(args: argparse.Namespace) -> ResolvedContext:
    environment_name = args.environment or os.environ.get("WOLF_ACTIVE_ENV") or os.environ.get("WOLF_ENV_NAME")
    environment_directory = None
    values: dict[str, str] = {}
    if environment_name:
        environment_directory = _environment_path(environment_name)
        if not environment_directory.is_dir():
            raise ValueError(f"WOLF environment {environment_name!r} does not exist")
        manifest = environment_manifest(environment_directory)
        if manifest:
            if args.process:
                raise ValueError("--process is a legacy override; use a pdk package in wolf.yaml")
            workspace = (
                resolve_cli_path(args.workspace, Path.cwd()) if args.workspace else None
            )
            return resolve_declarative_environment(
                load_environment(manifest, expected_name=environment_name),
                state_root=state_root(),
                environment_directory=environment_directory,
                design_override=args.design,
                backend_override=args.backend,
                workspace_override=workspace,
                run_tag=args.runtag,
            )
        values.update(_read_variables(environment_directory))
    for name in ("DESIGN_NAME", "PROCESS", "BACKEND", "WORKSPACE_DIR", "RUNTAG"):
        if os.environ.get(name):
            values.setdefault(name, os.environ[name])
    cli_paths = {"WORKSPACE_DIR": args.workspace} if args.workspace else {}
    overrides = {
        "DESIGN_NAME": args.design or "",
        "PROCESS": args.process or "",
        "BACKEND": args.backend or "",
        "RUNTAG": args.runtag or "",
    }
    return resolve_context(
        values,
        state_root=state_root(),
        environment_name=environment_name,
        environment_directory=environment_directory,
        invocation_directory=Path.cwd(),
        cli_paths=cli_paths,
        overrides=overrides,
    )


def _summary(context: ResolvedContext) -> None:
    ui.key_value("Environment", context.environment_name or "shell/CLI")
    ui.key_value("Format", context.format)
    ui.key_value("Design", context.design_name)
    if context.design_top:
        ui.key_value("Top", context.design_top)
    ui.key_value("Technology", context.process)
    if context.flow_name:
        ui.key_value("Flow", context.flow_name)
    ui.key_value("Backend", context.backend)
    ui.key_value("Workspace root", context.workspace_root)
    ui.key_value("Run directory", context.run_directory)
    for package, revision in sorted(context.package_revisions.items()):
        ui.key_value(f"Package {package}", revision)
    for clock in context.clocks:
        ui.key_value(f"Clock {clock.name}", f"{clock.port} @ {clock.period_ps:g} ps")


def command_run(args: argparse.Namespace) -> int:
    context = _context(args)
    backend_environment = get_backend(context.backend).prepare_execution(context)
    _summary(context)
    if backend_environment.get("WOLF_RESOLVED_MANIFEST"):
        ui.key_value("Resolved manifest", backend_environment["WOLF_RESOLVED_MANIFEST"])
    if backend_environment.get("ORFS_DESIGN_CONFIG"):
        ui.key_value("ORFS design config", backend_environment["ORFS_DESIGN_CONFIG"])
        ui.key_value("ORFS SDC", backend_environment["ORFS_SDC_FILE"])
        ui.key_value("ORFS flow variant", backend_environment["ORFS_FLOW_VARIANT"])
    if args.plan:
        return 0
    environment = os.environ.copy()
    environment.update(context.values)
    environment.update(backend_environment)
    environment["WOLF_HOME"] = str(context.state_root)
    if context.environment_directory:
        environment["WOLF_ENV_DIR"] = str(context.environment_directory)
    if context.environment_name:
        environment["WOLF_ENV_NAME"] = context.environment_name
    runner_args = ["--backend", context.backend, "--design", context.design_name,
                   "--process", context.process, "--runtag", context.run_tag]
    if args.yes:
        runner_args.append("--yes")
    if args.from_stage:
        runner_args.extend(["-from", args.from_stage])
    if args.to_stage:
        runner_args.extend(["-to", args.to_stage])
    runner_args.extend(args.passthrough)
    return run_legacy(runner_args, environment)


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("run", help="resolve and run the selected WOLF environment")
    parser.add_argument("--environment", help="named WOLF environment to resolve")
    parser.add_argument("--design")
    parser.add_argument("--process")
    parser.add_argument("--backend")
    parser.add_argument("--workspace", help="invocation-relative workspace override")
    parser.add_argument("--runtag")
    parser.add_argument("-from", dest="from_stage")
    parser.add_argument("-to", dest="to_stage")
    parser.add_argument("-y", "--yes", action="store_true")
    parser.add_argument("--plan", action="store_true", help="show resolved paths without execution")
    parser.add_argument("passthrough", nargs=argparse.REMAINDER)
    parser.set_defaults(handler=command_run, ui_kind="run", ui_section="Resolved run")

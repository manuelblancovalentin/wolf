"""Display the active WOLF environment as semantic resolved information."""

from __future__ import annotations

import argparse
import os

from wolf import ui
from wolf.commands.env import _environment_path, _read_variables
from wolf.commands.run import _context
from wolf.environment import environment_manifest, load_environment, profile_semantics
from wolf.package.registry import PackageRegistry
from wolf.package.store import PackageStore


def command_info(args: argparse.Namespace) -> int:
    name = args.environment or os.environ.get("WOLF_ACTIVE_ENV")
    if not name:
        raise ValueError(
            "no WOLF environment is active; use wolf info <environment> or "
            "wolf activate <environment>"
        )
    path = _environment_path(name)
    if not path.is_dir():
        raise ValueError(f"active WOLF environment {name!r} does not exist")
    manifest = environment_manifest(path)
    if manifest:
        return _declarative_info(name, path, manifest)
    values = dict(_read_variables(path))
    ui.key_value("Environment", name)
    ui.key_value("Environment location", path)
    ui.key_value("Format", "legacy")
    try:
        context = _context(argparse.Namespace(environment=name, workspace=None, design=None,
                                              process=None, backend=None, runtag=None))
    except ValueError:
        context = None
    if context:
        ui.key_value("Experiment", "")
        ui.key_value("  Design", context.design_name)
        ui.key_value("  Technology", context.process)
        ui.key_value("  Backend", context.backend)
        ui.key_value("Workspace", "")
        configured = values.get("WORKSPACE_DIR")
        if configured:
            ui.key_value("  Configured", configured)
        ui.key_value("  Resolved root", context.workspace_root)
        ui.key_value("  Prospective run", context.run_directory)
    else:
        ui.info("Environment is partial; supply remaining run inputs explicitly.")
    for label, key in (("Constraints", "CONSTRAINTS_FILE"), ("ORFS root", "ORFS_ROOT")):
        if values.get(key):
            ui.key_value(label, values[key])
    overrides = [key for key in ("OPENROAD_HIERARCHICAL", "SWAP_ARITH_OPERATORS") if key in values]
    if overrides:
        ui.key_value("Backend overrides", ", ".join(f"{key}={values[key]}" for key in overrides))
    return 0


def _declarative_info(name, path, manifest) -> int:
    profile = load_environment(manifest, expected_name=name)
    semantics = profile_semantics(profile)
    ui.key_value("Environment", name)
    ui.key_value("Environment location", path)
    ui.key_value("Format", "declarative-v1")
    ui.key_value("Experiment", "")
    for label, reference, value in (
        ("Design", profile.design, semantics["design"]),
        ("Technology", profile.technology, semantics["technology"]),
        ("Flow", profile.flow, semantics["flow"]),
    ):
        if reference and reference.package:
            ui.key_value(f"  {label} package", reference.package)
        if value:
            ui.key_value(f"  {label}", value)
    if semantics["top"]:
        ui.key_value("  Top", semantics["top"])
    if semantics["backend"]:
        ui.key_value("  Backend", semantics["backend"])

    for reference in (profile.design, profile.technology, profile.flow):
        if reference and reference.package:
            package = PackageRegistry().get(reference.package)
            status = PackageStore().status(package)
            ui.key_value(f"  {reference.package}", f"{package.revision} ({status})")
    if profile.clocks:
        ui.key_value("Constraints", "")
        for clock in profile.clocks:
            ui.key_value(f"  {clock.name}", f"{clock.port} @ {clock.period_ps:g} ps")
    if profile.workspace_root:
        ui.key_value("Workspace", "")
        ui.key_value("  Configured", profile.workspace_root)
        ui.key_value("  Resolved", profile.path.parent.joinpath(profile.workspace_root).resolve()
                     if not os.path.isabs(profile.workspace_root) else profile.workspace_root)
    if profile.threads:
        ui.key_value("Resources", "")
        ui.key_value("  Threads", profile.threads)
    for backend_name, overrides in profile.backend_overrides.items():
        ui.key_value(f"Backend overrides ({backend_name})", "")
        make = overrides.get("make", {})
        if isinstance(make, dict):
            for key, value in make.items():
                ui.key_value(f"  {key}", "<empty>" if value == "" else value)
    missing = [
        field for field, value in (
            ("design", semantics["design"]), ("technology", semantics["technology"]),
            ("flow", semantics["flow"]), ("backend", semantics["backend"]),
            ("workspace.root", profile.workspace_root),
        ) if not value
    ]
    if missing:
        ui.info("Environment is partial; unresolved: " + ", ".join(missing))
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("info", help="show a stored or active WOLF environment")
    parser.add_argument("environment", nargs="?")
    parser.set_defaults(handler=command_info, ui_kind="env", ui_section="Active WOLF environment")

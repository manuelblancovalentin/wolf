"""Display the active WOLF environment as semantic resolved information."""

from __future__ import annotations

import argparse
import os

from wolf import ui
from wolf.commands.common import resolve_environment_name
from wolf.commands.env import _environment_path, _read_variables
from wolf.commands.run import _context
from wolf.environment import environment_manifest, load_environment, profile_semantics
from wolf.package.registry import PackageRegistry
from wolf.package.store import PackageStore
from wolf.paths import builtin_flow_root


def command_info(args: argparse.Namespace) -> int:
    name = resolve_environment_name(args.environment)
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


def _print_override(prefix: str, value) -> None:
    """Print one backend.<name> override tree entry -- generic over
    whatever shape a given backend's own overrides happen to be (ORFS's
    make.*, cadence-flowtool's inject.<step>.<phase>/active_views.{setup,
    hold}/genus.set_db.*/flowtool.*/postsyn_netlists, or anything a
    future backend adds), rather than hardcoding one backend's schema."""
    if isinstance(value, dict):
        for key, sub in sorted(value.items()):
            _print_override(f"{prefix}.{key}", sub)
    elif isinstance(value, list):
        ui.key_value(f"  {prefix}", ", ".join(str(item) for item in value) if value else "<empty>")
    else:
        ui.key_value(f"  {prefix}", "<empty>" if value == "" else value)


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
        elif label == "Flow" and not (reference and reference.package) and semantics["backend"]:
            # No flow package at all -- WOLF's own bundled flow, same
            # label env_menu.py's own flow row already uses for this case.
            ui.key_value(f"  {label}", "WOLF's bundled flow")
    if semantics["top"]:
        ui.key_value("  Top", semantics["top"])
    if semantics["backend"]:
        ui.key_value("  Backend", semantics["backend"])

    for reference in (profile.design, profile.technology, profile.flow):
        if reference and reference.package:
            package = PackageRegistry().get(reference.package)
            store = PackageStore()
            status = store.status(package)
            ui.key_value(f"  {reference.package}", f"{package.revision} ({status})")
            installed = store.read(package)
            if installed:
                ui.key_value("    Location", installed.content_path)
    if semantics["backend"] == "cadence-flowtool" and not (profile.flow and profile.flow.package):
        # No flow package at all -- WOLF's own bundled flow, the Tcl
        # scripts an environment like this one actually runs (scripts.*
        # under the run directory are a per-run snapshot of these, not
        # the editable source -- see docs/CADENCE_GENUS.md's "scripts.*"
        # section).
        ui.key_value("  Flow scripts", builtin_flow_root("cadence-genus"))
    if (
        profile.clocks or profile.constraint_files or profile.constraint_lines
        or profile.floorplan_def or profile.power_nets or profile.ground_nets
    ):
        ui.key_value("Constraints", "")
        for clock in profile.clocks:
            ui.key_value(f"  {clock.name}", f"{clock.port} @ {clock.period_ps:g} ps")
        for path in profile.constraint_files:
            ui.key_value("  File", path)
        for line in profile.constraint_lines:
            ui.key_value("  Line", line)
        if profile.floorplan_def:
            ui.key_value("  Floorplan DEF", profile.floorplan_def)
        if profile.power_nets:
            ui.key_value("  Power nets", ", ".join(profile.power_nets))
        if profile.ground_nets:
            ui.key_value("  Ground nets", ", ".join(profile.ground_nets))
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
        for key, value in sorted(overrides.items()):
            _print_override(key, value)
    missing = [
        field for field, value in (
            ("design", semantics["design"]), ("technology", semantics["technology"]),
            # "flow" is satisfied by a direct backend selection too --
            # WOLF's own bundled flow (flow: {backend: ...}, no package)
            # is a complete, valid flow choice, not a missing one.
            ("flow", semantics["flow"] or semantics["backend"]),
            ("backend", semantics["backend"]),
        ) if not value
    ]
    if not profile.workspace_root and not profile.project_root:
        # workspace.root defaults to <project.root>/workspace once a
        # project root is set -- only a genuine gap (neither set) leaves
        # nowhere for a run to actually land.
        missing.append("workspace.root")
    if missing:
        ui.info("Environment is partial; unresolved: " + ", ".join(missing))
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("info", help="show a stored or active WOLF environment")
    parser.add_argument("environment", nargs="?")
    parser.set_defaults(handler=command_info, ui_kind="env", ui_section="Active WOLF environment")

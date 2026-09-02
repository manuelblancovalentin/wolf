"""Display the active WOLF environment as semantic resolved information."""

from __future__ import annotations

import argparse
import os

from wolf import ui
from wolf.commands.env import _environment_path, _read_variables
from wolf.commands.run import _context


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
    values = dict(_read_variables(path))
    ui.key_value("Environment", name)
    ui.key_value("Environment location", path)
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


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("info", help="show a stored or active WOLF environment")
    parser.add_argument("environment", nargs="?")
    parser.set_defaults(handler=command_info, ui_kind="env", ui_section="Active WOLF environment")

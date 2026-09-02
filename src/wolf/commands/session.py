"""Internal machine-readable validation used by shell integration."""

from __future__ import annotations

import argparse
import json

from wolf.commands.env import _environment_path


def command_shell_activate(args: argparse.Namespace) -> int:
    path = _environment_path(args.environment)
    if not path.is_dir():
        raise ValueError(f"WOLF environment {args.environment!r} does not exist")
    print(json.dumps({"environment": args.environment, "path": str(path)}))
    return 0


def command_deactivate(_args: argparse.Namespace) -> int:
    # Outside the Bash wrapper, deactivation cannot mutate a parent shell.
    print("No WOLF shell integration is active. Load shell/wolf.bash first.")
    return 0


def command_activate(_args: argparse.Namespace) -> int:
    print("WOLF activation requires the Bash integration; source shell/wolf.bash in this shell.")
    return 2


def register(subparsers: argparse._SubParsersAction) -> None:
    internal = subparsers.add_parser("_shell-activate", help=argparse.SUPPRESS)
    internal.add_argument("environment")
    internal.set_defaults(handler=command_shell_activate, ui_kind="env", ui_section="Shell integration")
    activate = subparsers.add_parser("activate", help="activate a WOLF environment in the current shell")
    activate.add_argument("environment")
    activate.set_defaults(handler=command_activate, ui_kind="env", ui_section="WOLF environment activation")
    deactivate = subparsers.add_parser("deactivate", help="deactivate the current WOLF environment")
    deactivate.set_defaults(handler=command_deactivate, ui_kind="env", ui_section="WOLF environment deactivation")

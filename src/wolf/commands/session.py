"""Internal machine-readable validation used by shell integration."""

from __future__ import annotations

import argparse
import json

from wolf.commands.env import _environment_path
from wolf.environment import environment_manifest, load_environment


def command_shell_activate(args: argparse.Namespace) -> int:
    path = _environment_path(args.environment)
    if not path.is_dir():
        raise ValueError(f"WOLF environment {args.environment!r} does not exist")
    env_vars: dict[str, str] = {}
    manifest = environment_manifest(path)
    if manifest:
        profile = load_environment(manifest, expected_name=args.environment)
        env_vars = dict(profile.env_vars)
    print(json.dumps({"environment": args.environment, "path": str(path), "env": env_vars}))
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
    internal.set_defaults(
        handler=command_shell_activate, ui_kind="env", ui_section="Shell integration",
        suppress_ui=True,
    )
    activate = subparsers.add_parser("activate", help="activate a WOLF environment in the current shell")
    activate.add_argument("environment")
    activate.set_defaults(handler=command_activate, ui_kind="env", ui_section="WOLF environment activation")
    deactivate = subparsers.add_parser("deactivate", help="deactivate the current WOLF environment")
    deactivate.set_defaults(handler=command_deactivate, ui_kind="env", ui_section="WOLF environment deactivation")

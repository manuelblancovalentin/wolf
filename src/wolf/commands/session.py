"""Managed interactive Bash session for WOLF environment activation."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile

from wolf import ui
from wolf.commands.env import _environment_path
from wolf.paths import state_root


def _active_name() -> str | None:
    return os.environ.get("WOLF_ACTIVE_ENV")


def command_activate(args: argparse.Namespace) -> int:
    if _active_name():
        raise ValueError("a WOLF-managed shell is already active; deactivate it before activating another environment")
    environment = _environment_path(args.environment)
    if not environment.is_dir():
        raise ValueError(f"WOLF environment {args.environment!r} does not exist")
    with tempfile.NamedTemporaryFile("w", prefix="wolf-shell-", suffix=".bash", delete=False) as stream:
        stream.write(
            "wolf() {\n"
            "  if [ \"$1\" = deactivate ]; then exit 0; fi\n"
            "  command wolf \"$@\"\n"
            "}\n"
            "PS1=\"(wolf:${WOLF_ACTIVE_ENV}) ${PS1:-\\u@\\h:\\w\\$ }\"\n"
        )
        rcfile = Path(stream.name)
    environment_values = os.environ.copy()
    environment_values.update(
        {
            "WOLF_ACTIVE_ENV": args.environment,
            "WOLF_HOME": str(state_root()),
            "WOLF_MANAGED_SHELL": "1",
        }
    )
    try:
        return subprocess.call(["bash", "--noprofile", "--norc", "--rcfile", str(rcfile), "-i"], env=environment_values)
    finally:
        rcfile.unlink(missing_ok=True)


def command_deactivate(_args: argparse.Namespace) -> int:
    if not _active_name() or not os.environ.get("WOLF_MANAGED_SHELL"):
        ui.info("No WOLF-managed shell is active. Use wolf activate <environment> to start one.")
        return 0
    ui.error("wolf deactivate must be invoked through the WOLF shell function.")
    return 2


def register(subparsers: argparse._SubParsersAction) -> None:
    activate = subparsers.add_parser("activate", help="open a managed Bash shell for an environment")
    activate.add_argument("environment")
    activate.set_defaults(handler=command_activate, ui_kind="env", ui_section="WOLF environment activation")
    deactivate = subparsers.add_parser("deactivate", help="leave the managed WOLF shell")
    deactivate.set_defaults(handler=command_deactivate, ui_kind="env", ui_section="WOLF environment deactivation")

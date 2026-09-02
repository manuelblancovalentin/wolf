"""Installed WOLF command-line interface."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys
from typing import Optional

from wolf import __version__
from wolf.commands import backend, completion, doctor, env, info, package, process, run, session
from wolf.backend import UnknownBackendError
from wolf.legacy import LegacyCommandError
from wolf import ui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wolf",
        description="WOLF EDA workflow and environment manager",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    env.register(subparsers)
    process.register(subparsers)
    backend.register(subparsers)
    package.register_package(subparsers)
    package.register_install(subparsers)
    run.register(subparsers)
    doctor.register(subparsers)
    info.register(subparsers)
    session.register(subparsers)
    completion.register(subparsers, build_parser)
    public_commands = [name for name in subparsers.choices if not name.startswith("_")]
    subparsers.metavar = "{" + ",".join(public_commands) + "}"
    subparsers._choices_actions = [
        action
        for action in subparsers._choices_actions
        if not action.dest.startswith("_")
    ]
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    machine_completion = arguments[:1] == ["_complete"]
    if not machine_completion and ("-h" in arguments or "--help" in arguments):
        kind = arguments[0] if arguments and arguments[0] in {"env", "process"} else "wolf"
        ui.header(kind)
    parser = build_parser()
    args = parser.parse_args(arguments)
    if not getattr(args, "suppress_ui", False):
        ui.header(args.ui_kind, args.ui_section)
    try:
        return args.handler(args)
    except (LegacyCommandError, UnknownBackendError, ValueError) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

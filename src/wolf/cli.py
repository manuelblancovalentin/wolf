"""Installed WOLF command-line interface."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys
from typing import Optional

from wolf import __version__
from wolf.commands import backend, doctor, env, info, process, run, session
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
    run.register(subparsers)
    doctor.register(subparsers)
    info.register(subparsers)
    session.register(subparsers)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if "-h" in arguments or "--help" in arguments:
        kind = arguments[0] if arguments and arguments[0] in {"env", "process"} else "wolf"
        ui.header(kind)
    parser = build_parser()
    args = parser.parse_args(arguments)
    ui.header(args.ui_kind, args.ui_section)
    try:
        return args.handler(args)
    except (LegacyCommandError, UnknownBackendError, ValueError) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

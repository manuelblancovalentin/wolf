"""Launch `wolf monitor`, a full-screen Textual TUI for watching a WOLF run."""

from __future__ import annotations

import argparse

from wolf import ui
from wolf.commands.common import resolve_environment_name
from wolf.status import select_run


def command_monitor(args: argparse.Namespace) -> int:
    environment = resolve_environment_name(args.environment, required=False)
    run = select_run(environment, args.run)
    if run is None:
        if args.run:
            raise ValueError(f"WOLF run {args.run!r} does not exist")
        if environment:
            ui.info(f"No run is available for WOLF environment {environment!r}.")
            return 0
        raise ValueError("no active WOLF environment; use --run PATH")
    from wolf.monitor_app import MonitorApp

    MonitorApp(run).run()
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "monitor", help="full-screen live TUI for watching a WOLF run (richer than status --watch)",
    )
    parser.add_argument("--run", help="run directory or active-environment run ID")
    parser.add_argument("--environment", help="environment used for latest-run lookup")
    parser.set_defaults(handler=command_monitor, suppress_ui=True)

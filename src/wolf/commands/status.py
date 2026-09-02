"""Inspect execution state and optional results for a WOLF run."""

from __future__ import annotations

import argparse
import json
import os

from wolf import ui
from wolf.status import load_status, render_human, select_run


def command_status(args: argparse.Namespace) -> int:
    environment = args.environment or os.environ.get("WOLF_ACTIVE_ENV")
    run = select_run(environment, args.run)
    if run is None:
        if args.run:
            raise ValueError(f"WOLF run {args.run!r} does not exist")
        if environment:
            ui.info(f"No run is available for WOLF environment {environment!r}.")
            return 0
        raise ValueError("no active WOLF environment; use --run PATH")
    status = load_status(run)
    if args.json:
        print(json.dumps(status.as_dict(), sort_keys=True, indent=2))
    else:
        render_human(status)
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("status", help="inspect execution state of a WOLF run")
    parser.add_argument("--run", help="run directory or active-environment run ID")
    parser.add_argument("--environment", help="environment used for latest-run lookup")
    parser.add_argument("--json", action="store_true", help="emit wolf.status/v1 JSON")
    parser.set_defaults(handler=command_status, ui_kind="run", ui_section="WOLF run status")

"""Inspect execution state and optional results for a WOLF run."""

from __future__ import annotations

import argparse
import json
import time

from wolf import ui
from wolf.backend import get_backend
from wolf.commands.common import resolve_environment_name
from wolf.status import load_status, render_human, render_live, select_run


_WATCH_POLL_SECONDS = 1.5
_WATCH_REFRESH_PER_SECOND = 8


def _resolve_run(args: argparse.Namespace):
    environment = resolve_environment_name(args.environment, required=False)
    run = select_run(environment, args.run)
    if run is None:
        if args.run:
            raise ValueError(f"WOLF run {args.run!r} does not exist")
        if environment:
            ui.info(f"No run is available for WOLF environment {environment!r}.")
            return None
        raise ValueError("no active WOLF environment; use --run PATH")
    return run


def _live_frame(run):
    """One fresh (status, renderable) pair for the --watch loop -- the
    expanded step tree only exists when some stage is actually running
    and the active backend has real sub-stage detail to offer (see
    Backend.stage_step_detail; ORFS, with no finer-than-stage
    granularity, simply returns ())."""
    status = load_status(run)
    running_stage = next((stage.name for stage in status.stages if stage.status == "running"), None)
    detail = ()
    if running_stage:
        try:
            detail = get_backend(status.backend).stage_step_detail(run, running_stage)
        except (ValueError, AttributeError, OSError):
            detail = ()
    active_elapsed = status.metrics.get("cadence.active_stage_elapsed_seconds")
    return status, render_live(status, detail, active_elapsed)


def _watch(run) -> int:
    from rich.live import Live

    try:
        status, renderable = _live_frame(run)
        with Live(renderable, console=ui.console, refresh_per_second=_WATCH_REFRESH_PER_SECOND) as live:
            while status.state not in ("completed", "failed"):
                time.sleep(_WATCH_POLL_SECONDS)
                status, renderable = _live_frame(run)
                live.update(renderable)
    except KeyboardInterrupt:
        return 0
    ui.success("Run completed.") if status.state == "completed" else ui.error("Run failed.")
    return 0 if status.state == "completed" else 1


def command_status(args: argparse.Namespace) -> int:
    run = _resolve_run(args)
    if run is None:
        return 0
    if args.watch:
        if args.json:
            raise ValueError("--watch and --json are mutually exclusive")
        return _watch(run)
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
    parser.add_argument(
        "--watch", action="store_true",
        help="auto-refresh in place (live spinner/tree for the active stage) until the run finishes",
    )
    parser.set_defaults(handler=command_status, ui_kind="run", ui_section="WOLF run status")

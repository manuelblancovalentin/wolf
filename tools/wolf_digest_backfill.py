#!/usr/bin/env python3
"""Backfill `wolf.digest.json` for runs that already exist, from before
wolf wrote one itself.

Standalone and outside wolf on purpose: this is a one-time operation the
project owner runs by hand, not a `wolf` subcommand wolf would silently
re-run on every deploy. It reuses wolf's own `flow.status`/`flow.metrics`
parsers (no new parsing logic lives here) and never opens a stage report
or log -- only `wolf.resolved.yaml` (wolf's own small manifest, when one
exists) and the handful of small, already-parsed files those parsers
read.

Every run's own design/process identity comes from wolf.resolved.yaml
when present, and otherwise from the run directory's own path shape
(`<workspace>/<design>/<design>.<process>/<design>.<N>`, confirmed real
by wolf's own `resolve_context`) -- never from opening anything inside
the run.

Prints counts only, per run: how many stages are known, in which state,
how many metrics and which checks were found, and the digest's own size
in bytes. Never a metric value, a report line, or any path beyond the
one the caller already gave it.

Usage:
    wolf_digest_backfill.py RUN_DIR [RUN_DIR ...] [--project-root PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def _identity_from_resolved_manifest(run_directory: Path):
    manifest = run_directory / "wolf.resolved.yaml"
    if not manifest.is_file():
        return None, None, None
    try:
        import yaml

        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None, None
    if not isinstance(data, dict):
        return None, None, None
    backend = data.get("backend", {})
    backend_name = backend.get("name") if isinstance(backend, dict) else None
    return data.get("design_name"), data.get("process"), backend_name


def _identity_from_path(run_directory: Path):
    """`<workspace>/<design>/<design>.<process>/<design>.<N>` -- the one
    real on-disk convention `resolve_context` itself builds; parsed from
    directory names only, nothing opened."""
    process_directory = run_directory.parent
    design_directory = process_directory.parent
    design = design_directory.name
    process_dir_name = process_directory.name
    prefix = f"{design}."
    process = process_dir_name[len(prefix):] if process_dir_name.startswith(prefix) else None
    return design, process


def _run_number(run_directory: Path, design: str) -> str:
    name = run_directory.name
    prefix = f"{design}."
    return name[len(prefix):] if design and name.startswith(prefix) else name


def backfill_one(run_directory: Path, *, project_root: Path | None) -> dict:
    from wolf.digest import build_digest, write_digest

    design, process, backend = _identity_from_resolved_manifest(run_directory)
    if not design or not process:
        path_design, path_process = _identity_from_path(run_directory)
        design = design or path_design
        process = process or path_process
    backend = backend or "cadence-flowtool"

    context = SimpleNamespace(
        design_name=design or "unknown", process=process or "unknown",
        backend=backend, technology=None,
    )
    run_number = _run_number(run_directory, design or "")
    digest = build_digest(context, run_directory, run_number=run_number)
    write_digest(run_directory, digest, project_root=project_root, design_name=design)

    stage_counts: dict[str, int] = {}
    for stage in digest["stages"]:
        stage_counts[stage["status"]] = stage_counts.get(stage["status"], 0) + 1
    size_bytes = len(json.dumps(digest, sort_keys=True).encode("utf-8"))
    return {
        "run_directory": str(run_directory),
        "stages_total": len(digest["stages"]),
        "stage_counts": stage_counts,
        "metrics_found": len(digest["metrics"]),
        "drc_found": "drc" in digest["checks"],
        "lvs_found": "lvs" in digest["checks"],
        "digest_bytes": size_bytes,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directories", nargs="+", help="one or more existing run directories")
    parser.add_argument(
        "--project-root", help="also write the shared/wolf-digests/ copy under this project root",
    )
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).expanduser().resolve() if args.project_root else None

    for raw in args.run_directories:
        run_directory = Path(raw).expanduser().resolve()
        try:
            summary = backfill_one(run_directory, project_root=project_root)
        except Exception as error:  # noqa: BLE001 - report and continue with the next run
            print(f"{run_directory}: FAILED ({type(error).__name__})")
            continue
        counts = " ".join(f"{state}={count}" for state, count in sorted(summary["stage_counts"].items()))
        print(
            f"{summary['run_directory']}: stages={summary['stages_total']} ({counts}) "
            f"metrics={summary['metrics_found']} drc_found={summary['drc_found']} "
            f"lvs_found={summary['lvs_found']} digest_bytes={summary['digest_bytes']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Self-check: run wolf's digest-building logic against one real run
directory and print only counts -- never a metric value, never report
text, never a path beyond the one the caller gave it. This is how the
new (and still-unverified-against-a-real-report) DRC/LVS parser and the
attempt counter get confirmed against reality, without this tool, or
whoever runs it, ever having to look at a real report's content.

Nothing here is written to disk -- this never calls `write_digest`, only
`build_digest` -- so it is safe to run against a production run
directory with no side effect at all.

Usage:
    wolf_digest_selfcheck.py RUN_DIR
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory")
    parser.add_argument(
        "--backend", default="cadence-flowtool",
        help="backend to assume when the run has no wolf.resolved.yaml of its own",
    )
    args = parser.parse_args(argv)
    run_directory = Path(args.run_directory).expanduser().resolve()

    from wolf.backend.cadence_genus import genus_run_checks, genus_run_qor, stage_attempt_counts
    from wolf.digest import build_digest

    context = SimpleNamespace(
        design_name="n/a", process="n/a", backend=args.backend, technology=None,
    )
    digest = build_digest(context, run_directory, run_number="n/a")

    attempts = stage_attempt_counts(run_directory)
    qor = genus_run_qor(run_directory)
    checks = genus_run_checks(run_directory)

    stage_counts: dict[str, int] = {}
    for stage in digest["stages"]:
        stage_counts[stage["status"]] = stage_counts.get(stage["status"], 0) + 1

    inferred_count = sum(1 for stage in digest["stages"] if stage.get("inferred"))

    print(f"run directory: {run_directory}")
    print(f"stages known: {len(digest['stages'])}")
    summary = ", ".join(f"{k}={v}" for k, v in sorted(stage_counts.items())) or "(none)"
    print(f"stage status counts: {summary}")
    print(f"stages whose status came from the tolerant (older-flow-revision) fallback: {inferred_count}")
    print(f"stages with an attempt count (flow.status.d present): {len(attempts)}")
    print(f"stages with at least one QoR report parsed: {len(qor)}")
    for kind in ("drc", "lvs"):
        if kind in checks:
            print(f"{kind}: parsed ok, status={checks[kind]['status']}, violation_count={checks[kind]['violations']}")
        else:
            print(f"{kind}: no recognizable report found (parser may need adjusting -- see docs/DIGEST.md)")
    print(f"metrics extracted: {len(digest['metrics'])}")
    print(f"digest size if written now: {len(json.dumps(digest, sort_keys=True).encode('utf-8'))} bytes "
          f"(cap: 65536 bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

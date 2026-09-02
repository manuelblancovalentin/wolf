#!/usr/bin/env python3

"""Check the acceptance metrics of the opt-in Ibex ORFS regression."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, Iterable, Optional, Tuple


def flatten_metrics(value: Any, prefix: str = "") -> Dict[str, Any]:
    flattened: Dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            child_key = f"{prefix}__{key}" if prefix else str(key)
            flattened.update(flatten_metrics(child, child_key))
    else:
        flattened[prefix] = value
    return flattened


def metric(metrics: Dict[str, Any], *needles: str) -> Tuple[str, Any]:
    for key, value in metrics.items():
        lowered = key.lower()
        if all(needle in lowered for needle in needles):
            return key, value
    raise KeyError(" / ".join(needles))


def metrics_file(reports_dir: Path) -> Path:
    metadata = reports_dir / "metadata.json"
    if not metadata.is_file():
        raise RuntimeError(f"expected ORFS metadata file: {metadata}")
    return metadata


def final_timing_counts(reports_dir: Path) -> Tuple[int, int]:
    report = reports_dir / "6_finish.rpt"
    if not report.is_file():
        raise RuntimeError(f"expected ORFS final timing report: {report}")
    text = report.read_text(encoding="utf-8", errors="replace")
    counts = []
    for kind in ("setup", "hold"):
        match = re.search(
            rf"finish {kind}_violation_count[\s-]+{kind} violation count (\d+)",
            text,
        )
        if match is None:
            raise RuntimeError(f"missing {kind} violation count in {report}")
        counts.append(int(match.group(1)))
    return tuple(counts)  # type: ignore[return-value]


def main(argv: Optional[Iterable[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("usage: check_orfs_ibex.py REPORTS_DIR", file=sys.stderr)
        return 2

    result_file = metrics_file(Path(arguments[0]))
    metrics = flatten_metrics(json.loads(result_file.read_text(encoding="utf-8")))
    try:
        drc_key, drc_errors = metric(metrics, "detailedroute", "drc", "error")
        setup_ws_key, setup_ws = metric(metrics, "finish", "setup", "ws")
        setup_paths, hold_paths = final_timing_counts(Path(arguments[0]))
    except (KeyError, RuntimeError) as error:
        print(f"missing required ORFS metric: {error}", file=sys.stderr)
        return 2

    print(f"metrics: {result_file}")
    print(f"setup violation count: {setup_paths} (6_finish.rpt)")
    print(f"hold violation count: {hold_paths} (6_finish.rpt)")
    print(f"detailed-route DRC errors: {drc_errors} ({drc_key})")
    print(f"final worst setup slack: {float(setup_ws):.3f} ps ({setup_ws_key})")

    failures = []
    if float(setup_paths) != 0:
        failures.append("setup violations are nonzero")
    if float(hold_paths) != 0:
        failures.append("hold violations are nonzero")
    if float(drc_errors) != 0:
        failures.append("detailed-route DRC errors are nonzero")
    if failures:
        print("ORFS Ibex regression failed: " + "; ".join(failures), file=sys.stderr)
        return 1
    print("ORFS Ibex regression is timing-clean and detailed-route DRC-clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

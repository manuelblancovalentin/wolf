#!/usr/bin/env python3

"""Check the acceptance metrics of the opt-in Ibex ORFS regression."""

from __future__ import annotations

import json
from pathlib import Path
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


def main(argv: Optional[Iterable[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("usage: check_orfs_ibex.py REPORTS_DIR", file=sys.stderr)
        return 2

    result_file = metrics_file(Path(arguments[0]))
    metrics = flatten_metrics(json.loads(result_file.read_text(encoding="utf-8")))
    try:
        setup_paths_key, setup_paths = metric(metrics, "setup", "violating", "path")
        hold_paths_key, hold_paths = metric(metrics, "hold", "violating", "path")
        drc_key, drc_errors = metric(metrics, "detailedroute", "drc", "error")
        setup_ws_key, setup_ws = metric(metrics, "setup", "ws")
    except KeyError as error:
        print(f"missing required ORFS metric: {error}", file=sys.stderr)
        return 2

    print(f"metrics: {result_file}")
    print(f"setup violating paths: {setup_paths} ({setup_paths_key})")
    print(f"hold violating paths: {hold_paths} ({hold_paths_key})")
    print(f"detailed-route DRC errors: {drc_errors} ({drc_key})")
    print(f"final worst setup slack: {float(setup_ws) * 1000:.3f} ps ({setup_ws_key})")

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

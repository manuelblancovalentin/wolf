"""The run digest: one small, wolf-written JSON file per run folder that
the website (or anyone else) can read instead of parsing tool reports.
Schema ``wolf.digest/v1``. See docs/DIGEST.md for the field reference.

Nothing in here ever carries a library path, a cell/instance/net name, a
host name, a user name, or raw report text -- metrics are a closed,
wolf-owned vocabulary (see ``_METRIC_MAP`` below); a metric this module
doesn't recognize by name is simply left out, not passed through.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from wolf import __version__
from wolf.status import load_status

DIGEST_SCHEMA = "wolf.digest/v1"
_SIZE_CAP_BYTES = 64 * 1024

# {internal metrics-dict key: (digest name, unit)} -- the closed
# vocabulary. A key this run's metrics happen to carry that isn't listed
# here never reaches the digest.
_RUN_METRIC_MAP: dict[str, tuple[str, str]] = {
    "cadence.total_real_seconds": ("total_real_seconds", "s"),
    "cadence.total_cpu_seconds": ("total_cpu_seconds", "s"),
    "cadence.memory_resident_mb": ("memory_resident_mb", "MB"),
    "cadence.memory_resident_peak_mb": ("memory_resident_peak_mb", "MB"),
    "timing.worst_slack_ps": ("worst_slack_ps", "ps"),
    "timing.setup_violations": ("setup_violations", "count"),
    "timing.hold_violations": ("hold_violations", "count"),
    "electrical.max_slew_violations": ("max_slew_violations", "count"),
    "electrical.max_cap_violations": ("max_cap_violations", "count"),
    "electrical.max_fanout_violations": ("max_fanout_violations", "count"),
}
_STAGE_QOR_METRIC_MAP: dict[str, tuple[str, str]] = {
    "cell_count": ("cell_count", "count"),
    "total_area_um2": ("total_area_um2", "um2"),
    "worst_slack_ps": ("worst_slack_ps", "ps"),
    "total_negative_slack_ps": ("total_negative_slack_ps", "ps"),
    "failing_endpoints": ("failing_endpoints", "count"),
    "total_w": ("total_power_w", "W"),
}
_STAGE_STATUS_MAP = {
    "complete": "succeeded", "failed": "failed", "running": "running",
    "unknown": "pending", "pending": "pending",
}


def _digest_stage_status(raw: str) -> str:
    return _STAGE_STATUS_MAP.get(raw, "pending")


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, sort_keys=True)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _trim_to_size_cap(digest: dict[str, Any]) -> dict[str, Any]:
    """Drop the least essential metrics entries (last-added first) until
    the serialized digest fits the 64 KB cap. Stage status/attempts and
    checks are never dropped -- only `metrics`, and only as a last
    resort; realistic runs (nine stages, a handful of metrics each)
    never come close to this cap."""
    while len(json.dumps(digest, sort_keys=True).encode("utf-8")) > _SIZE_CAP_BYTES:
        if digest.get("metrics"):
            digest["metrics"].pop()
        else:
            break
    return digest


def build_digest(
    context,
    run_directory: Path,
    *,
    run_number: str,
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
) -> dict[str, Any]:
    """Build the digest document for one run, from wolf's own already-
    resolved context and whatever `load_status`/the backend's QoR/check
    scan can find on disk right now -- safe to call mid-run (a stage not
    yet reached simply shows "pending", attempts 0)."""
    status = load_status(run_directory, backend_hint=context.backend)

    attempts: dict[str, int] = {}
    qor: dict[str, dict[str, dict[str, float]]] = {}
    checks: dict[str, dict[str, Any]] = {}
    inferred_stages: set[str] = set()
    if context.backend == "cadence-flowtool":
        from wolf.backend.cadence_genus import (
            genus_run_checks, genus_run_qor, genus_run_status, rollup_stage_states, stage_attempt_counts,
        )
        attempts = stage_attempt_counts(run_directory)
        qor = genus_run_qor(run_directory)
        checks = genus_run_checks(run_directory)
        # load_status already did this same rollup to get status.stages;
        # redone here only to also learn which stages, if any, needed
        # the tolerant (older-flow-revision) fallback -- see
        # rollup_stage_states's own docstring.
        _, raw_states = genus_run_status(run_directory)
        rollup_stage_states(raw_states, inferred=inferred_stages)

    stages = []
    metrics: list[dict[str, Any]] = []
    for stage in status.stages:
        digest_status = _digest_stage_status(stage.status)
        stage_attempts = attempts.get(stage.name)
        if stage_attempts is None:
            stage_attempts = 0 if digest_status == "pending" else 1
        stages.append({
            "name": stage.name,
            "status": digest_status,
            "attempts": stage_attempts,
            "elapsed_seconds": stage.elapsed_seconds,
            "inferred": stage.name in inferred_stages,
        })
        for kind, fields in qor.get(stage.name, {}).items():
            for key, value in fields.items():
                mapped = _STAGE_QOR_METRIC_MAP.get(key)
                if mapped is None:
                    continue
                name, unit = mapped
                metrics.append({"name": name, "value": value, "unit": unit, "stage": stage.name})

    for key, value in status.metrics.items():
        mapped = _RUN_METRIC_MAP.get(key)
        if mapped is None or not isinstance(value, (int, float)):
            continue
        name, unit = mapped
        metrics.append({"name": name, "value": value, "unit": unit, "stage": None})

    technology = getattr(context, "technology", None)
    metal_stack = getattr(technology, "metal_stack", None) if technology else None

    digest = {
        "schema": DIGEST_SCHEMA,
        "wolf_version": __version__,
        "design": context.design_name,
        "process": context.process,
        "metal_stack": metal_stack,
        "run_number": run_number,
        "started_at": started_at,
        "ended_at": ended_at,
        "stages": stages,
        "metrics": metrics,
        "checks": checks,
    }
    return _trim_to_size_cap(digest)


def write_digest(
    run_directory: Path,
    digest: dict[str, Any],
    *,
    project_root: Optional[Path] = None,
    design_name: Optional[str] = None,
) -> None:
    """Write the digest atomically into the run folder, and -- when the
    project root is known -- a second atomic copy under
    `<project_root>/shared/wolf-digests/`, named by design and run
    number so a later run never overwrites an earlier one's published
    copy. Both are real files, never links, per the owner's own
    instruction."""
    _atomic_write_json(run_directory / "wolf.digest.json", digest)
    if project_root is None or not design_name:
        return
    run_number = digest.get("run_number") or "0"
    shared_path = Path(project_root) / "shared" / "wolf-digests" / f"{design_name}.{run_number}.json"
    _atomic_write_json(shared_path, digest)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

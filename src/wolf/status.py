"""Shared human/JSON representation of a WOLF run's execution state."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import yaml

from wolf.backend import get_backend
from wolf.commands.env import _environment_path


STATUS_SCHEMA = "wolf.status/v1"


@dataclass(frozen=True)
class StageResult:
    name: str
    status: str
    elapsed_seconds: float | None = None
    exit_code: int | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"name": self.name, "status": self.status}
        if self.elapsed_seconds is not None:
            result["elapsed_seconds"] = self.elapsed_seconds
        if self.exit_code is not None:
            result["exit_code"] = self.exit_code
        return result


@dataclass(frozen=True)
class RunStatus:
    run_directory: Path
    environment: str | None
    run_name: str
    backend: str
    state: str
    stages: tuple[StageResult, ...]
    metrics: dict[str, Any]
    failed_stage: str | None = None
    exit_code: int | None = None

    def as_dict(self) -> dict[str, Any]:
        run = {
            "directory": str(self.run_directory), "name": self.run_name,
            "environment": self.environment, "backend": self.backend,
            "status": self.state,
        }
        elapsed = sum(stage.elapsed_seconds or 0 for stage in self.stages)
        if elapsed:
            run["elapsed_seconds"] = elapsed
        if self.failed_stage:
            run["failed_stage"] = self.failed_stage
        if self.exit_code is not None:
            run["exit_code"] = self.exit_code
        return {"schema": STATUS_SCHEMA, "run": run,
                "stages": [stage.as_dict() for stage in self.stages],
                "metrics": self.metrics}


def _manifest(run: Path) -> dict[str, Any]:
    path = run / "wolf.resolved.yaml"
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _latest_for_environment(name: str) -> Path | None:
    link = _environment_path(name) / "run.latest.d"
    if link.is_symlink() or link.is_dir():
        target = link.resolve()
        return target if target.is_dir() else None
    return None


def select_run(environment: str | None = None, selector: str | None = None) -> Path | None:
    if selector:
        candidate = Path(selector).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        candidate = candidate.resolve()
        if candidate.is_dir():
            return candidate
        if environment:
            link = _environment_path(environment) / "runs" / f"{selector}.d"
            if link.exists():
                return link.resolve()
        return None
    if not environment:
        return None
    return _latest_for_environment(environment)


def load_status(run_directory: Path) -> RunStatus:
    run = run_directory.expanduser().resolve()
    manifest = _manifest(run)
    environment = manifest.get("environment")
    backend_data = manifest.get("backend", {})
    backend = backend_data.get("name", "unknown") if isinstance(backend_data, dict) else "unknown"
    expected = []
    try:
        expected = list(get_backend(backend).stages())
    except (ValueError, AttributeError):
        pass
    recorded: dict[str, StageResult] = {}
    timing = run / "wolf.stage-results"
    if timing.is_file():
        for line in timing.read_text(encoding="utf-8").splitlines():
            parts = line.split("|")
            if len(parts) < 3:
                continue
            name, state, elapsed = parts[:3]
            try:
                elapsed_value = float(elapsed)
            except ValueError:
                elapsed_value = None
            exit_code = None
            if len(parts) > 3:
                try:
                    exit_code = int(parts[3])
                except ValueError:
                    pass
            recorded[name] = StageResult(name, state, elapsed_value, exit_code)
    stages = tuple(recorded.get(name, StageResult(name, "pending")) for name in expected)
    if not expected:
        stages = tuple(recorded.values())
    if not stages:
        state = "not started"
    elif any(stage.status == "failed" for stage in stages):
        state = "failed"
    elif all(stage.status == "complete" for stage in stages):
        state = "completed"
    elif any(stage.status in {"complete", "running"} for stage in stages):
        state = "partial/incomplete"
    else:
        state = "not started"
    failed = next((stage.name for stage in stages if stage.status == "failed"), None)
    metrics: dict[str, Any] = {}
    try:
        metrics = dict(get_backend(backend).extract_metrics(run))
    except (ValueError, OSError):
        pass
    return RunStatus(run, environment, run.name, backend, state, stages, metrics, failed)


def render_human(status: RunStatus) -> None:
    from wolf import ui
    ui.key_value("Environment", status.environment or "unknown")
    ui.key_value("Run", status.run_name)
    ui.key_value("Backend", status.backend)
    ui.key_value("Status", status.state)
    elapsed = sum(stage.elapsed_seconds or 0 for stage in status.stages)
    if elapsed:
        minutes, seconds = divmod(int(round(elapsed)), 60)
        ui.key_value("Elapsed", f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s")
    if status.failed_stage:
        ui.key_value("Failed stage", status.failed_stage)
        failed_result = next((stage for stage in status.stages if stage.name == status.failed_stage), None)
        if failed_result and failed_result.exit_code is not None:
            ui.key_value("Exit code", failed_result.exit_code)
    ui.key_value("Run directory", status.run_directory)
    if status.stages:
        ui.key_value("Stages", "")
        for stage in status.stages:
            elapsed = f"{stage.elapsed_seconds:g}s" if stage.elapsed_seconds is not None else "-"
            ui.key_value(f"  {stage.name}", f"{stage.status:<16} {elapsed}")
    labels = {
        "timing.worst_slack_ps": "Worst slack",
        "timing.setup_violations": "Setup violations",
        "timing.hold_violations": "Hold violations",
        "physical.drc_violations": "Route DRC",
        "electrical.max_slew_violations": "Max slew violations",
        "electrical.max_cap_violations": "Max cap violations",
        "electrical.max_fanout_violations": "Max fanout violations",
    }
    available = [(labels[key], value) for key, value in labels.items() if key in status.metrics]
    if available:
        ui.key_value("Metrics", "")
        for label, value in available:
            ui.key_value(f"  {label}", value)

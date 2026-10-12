"""Shared human/JSON representation of a WOLF run's execution state."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Sequence

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
    inferred = {}
    try:
        inferred = dict(get_backend(backend).infer_stage_results(run))
    except (ValueError, AttributeError, OSError):
        pass
    metrics: dict[str, Any] = {}
    try:
        metrics = dict(get_backend(backend).extract_metrics(run))
    except (ValueError, OSError):
        pass
    # "stage_elapsed_seconds" is an internal convention, not a displayed
    # metric -- a backend (so far only Cadence/Flowtool, from its own
    # flow.metrics) that has no other source of real per-stage timing
    # (unlike a generically-tracked wolf.stage-results run) uses it to
    # still populate StageResult.elapsed_seconds for a stage this run
    # has actually completed.
    stage_elapsed = metrics.pop("stage_elapsed_seconds", {})
    if not isinstance(stage_elapsed, dict):
        stage_elapsed = {}

    def _stage_result(name: str) -> StageResult:
        if name in recorded:
            return recorded[name]
        state = inferred.get(name, "unknown" if inferred else "pending")
        return StageResult(name, state, stage_elapsed.get(name))

    stages = tuple(_stage_result(name) for name in expected)
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
    elif any(stage.status == "unknown" for stage in stages):
        state = "unknown"
    else:
        state = "not started"
    failed = next((stage.name for stage in stages if stage.status == "failed"), None)
    return RunStatus(run, environment, run.name, backend, state, stages, metrics, failed)


def _format_elapsed(value: float | None) -> str:
    """Human-readable elapsed time -- HH:MM:SS, with a leading "<N>d "
    only when at least one full day has actually elapsed (a long Genus/
    Innovus run is routinely many hours, but still almost never a full
    day, so days stay out of the way until they're real)."""
    if value is None:
        return "-"
    seconds = int(round(value))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    prefix = f"{days}d " if days else ""
    return f"{prefix}{hours:02d}:{minutes:02d}:{seconds:02d}"


_STATE_STYLES = {"complete": "green", "running": "yellow", "failed": "red"}
_STATE_MARKERS = {"complete": "●", "running": "●", "failed": "●"}


def _status_cell(value: str, *, spin: bool = False):
    """A styled status cell -- plain `Text` normally, or a live
    `Spinner` in place of the usual marker when `spin` is set (the
    --watch panel's own animated "this is active right now" cue; a
    plain human/JSON render never passes it)."""
    from rich.spinner import Spinner
    from rich.text import Text

    style = _STATE_STYLES.get(value, "dim")
    if spin and value == "running":
        return Spinner("dots", text=Text(f" {value}", style=style), style=style)
    marker = _STATE_MARKERS.get(value, "○")
    return Text(f"{marker} {value}", style=style)


def _stages_table(
    status: RunStatus, *, spin: bool = False, active_stage_elapsed: float | None = None,
):
    """One row per stage -- Status/Elapsed, plus real QoR columns
    (Area/WNS/TNS/Viol/Power straight from Genus's own area/timing/
    power reports, see cadence_genus.genus_run_qor) merged in whenever
    the backend has any "cadence.qor_by_stage" data at all. QoR is the
    same per-stage granularity as Status/Elapsed, so a separate table
    repeating the same row labels was just duplication; a stage with
    no QoR of its own yet (not reached, or no report for that one kind
    yet) simply shows "-" in those columns, same convention as Elapsed.

    Shared by `render_human` (spin=False, a static snapshot) and
    `render_live` (spin=True, with a live spinner and a blinking
    elapsed time on the actively running stage)."""
    from rich.table import Table

    qor_by_stage = status.metrics.get("cadence.qor_by_stage") or {}
    table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
    table.add_column("Stage")
    table.add_column("Status")
    table.add_column("Elapsed", justify="right")
    if qor_by_stage:
        table.add_column("Area (mm²)", justify="right")
        table.add_column("WNS (ps)", justify="right")
        table.add_column("TNS (ps)", justify="right")
        table.add_column("Viol", justify="right")
        table.add_column("Power (mW)", justify="right")
    for stage in status.stages:
        if spin and stage.status == "running" and active_stage_elapsed is not None:
            elapsed_cell = _live_elapsed_text(active_stage_elapsed)
        else:
            elapsed_cell = _format_elapsed(stage.elapsed_seconds)
        row = [stage.name, _status_cell(stage.status, spin=spin), elapsed_cell]
        if qor_by_stage:
            kinds = qor_by_stage.get(stage.name, {})
            area = kinds.get("area", {})
            timing = kinds.get("timing", {})
            power = kinds.get("power", {})
            row.extend([
                f"{area['total_area_um2'] / 1e6:.2f}" if "total_area_um2" in area else "-",
                f"{timing['worst_slack_ps']:g}" if "worst_slack_ps" in timing else "-",
                f"{timing['total_negative_slack_ps']:g}" if "total_negative_slack_ps" in timing else "-",
                f"{int(timing['failing_endpoints'])}" if "failing_endpoints" in timing else "-",
                f"{power['total_w'] * 1000:.1f}" if "total_w" in power else "-",
            ])
        table.add_row(*row)
    return table


def _build_renderable(status: RunStatus):
    """The full human-readable panel (header fields, Stages table,
    Metrics table) as one Rich renderable, not yet printed -- shared by
    the plain one-shot `render_human` and the auto-refreshing
    `--watch` panel (`wolf.commands.status`), which feeds a fresh one
    of these into a `rich.live.Live` on every tick instead of piping
    plain output through an external `watch`, which strips Rich's own
    color/formatting."""
    from rich.console import Group
    from rich.table import Table
    from rich.text import Text

    lines: list[Text] = []

    def kv(key: object, value: object) -> None:
        line = Text("  ")
        line.append(str(key), style="bold blue")
        line.append(": ")
        line.append(str(value))
        lines.append(line)

    kv("Environment", status.environment or "unknown")
    kv("Run", status.run_name)
    kv("Backend", status.backend)
    kv("Status", status.state)
    total_elapsed = sum(stage.elapsed_seconds or 0 for stage in status.stages)
    if total_elapsed:
        kv("Elapsed", _format_elapsed(total_elapsed))
    if status.failed_stage:
        kv("Failed stage", status.failed_stage)
        failed_result = next((stage for stage in status.stages if stage.name == status.failed_stage), None)
        if failed_result and failed_result.exit_code is not None:
            kv("Exit code", failed_result.exit_code)
    kv("Run directory", status.run_directory)
    current_activity = status.metrics.get("cadence.current_activity")
    if current_activity:
        kv("Activity", current_activity)
    renderables: list[Any] = list(lines)

    if status.stages:
        renderables.append(Text("\nStages"))
        renderables.append(_stages_table(status))

    # label, formatter -- a formatter takes the raw metric value and
    # returns display text; plain str() is the default when a key has
    # no formatter of its own.
    metric_labels: dict[str, tuple[str, Any]] = {
        "timing.worst_slack_ps": ("Worst slack", lambda value: f"{value:g} ps"),
        "timing.setup_violations": ("Setup violations", str),
        "timing.hold_violations": ("Hold violations", str),
        "physical.drc_violations": ("Route DRC", str),
        "electrical.max_slew_violations": ("Max slew violations", str),
        "electrical.max_cap_violations": ("Max cap violations", str),
        "electrical.max_fanout_violations": ("Max fanout violations", str),
        "cadence.total_real_seconds": ("Flow elapsed", _format_elapsed),
        "cadence.total_cpu_seconds": ("Flow CPU time", _format_elapsed),
        "cadence.memory_resident_mb": ("Memory", lambda value: f"{value:g} MB"),
        "cadence.memory_resident_peak_mb": ("Memory (peak)", lambda value: f"{value:g} MB"),
    }
    available = [
        (label, formatter(status.metrics[key])) for key, (label, formatter) in metric_labels.items()
        if key in status.metrics
    ]
    if available:
        renderables.append(Text("\nMetrics"))
        table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        for label, rendered in available:
            table.add_row(label, rendered)
        renderables.append(table)

    return Group(*renderables)


def render_human(status: RunStatus) -> None:
    from wolf import ui
    ui.console.print(_build_renderable(status))


def _live_elapsed_text(value: float) -> Any:
    """A blinking elapsed-time cell -- the one visual cue that a number
    is actively ticking up in place, not a stale snapshot (the blink
    attribute isn't honored by every terminal, but degrades harmlessly
    to a plain, still-correct elapsed reading where it isn't)."""
    from rich.text import Text
    return Text(_format_elapsed(value), style="yellow blink")


def render_live(
    status: RunStatus, step_detail: Sequence[tuple[str, str, float | None]] = (),
    active_stage_elapsed: float | None = None,
):
    """The --watch panel's own renderable: the same fields/tables
    `render_human` prints, with every "running" stage shown as a live
    spinner instead of a static marker, plus (when the caller supplies
    it -- `wolf.commands.status` queries the active backend's own
    `stage_step_detail` for whichever stage is currently running) an
    expanded one-level tree of that stage's own real steps, each with
    its own spinner/marker.

    `active_stage_elapsed` (from the backend's own `extract_metrics`,
    key "cadence.active_stage_elapsed_seconds" -- see
    genus_run_active_elapsed) and a "running" step_detail entry's own
    elapsed both render as a blinking HH:MM:SS, the one visual cue that
    distinguishes "this is ticking up live" from the rest of the
    panel's otherwise-static numbers."""
    from rich.console import Group
    from rich.text import Text
    from rich.tree import Tree

    renderables: list[Any] = []
    kv_lines: list[Text] = []

    def kv(key: object, value: object) -> None:
        line = Text("  ")
        line.append(str(key), style="bold blue")
        line.append(": ")
        line.append(str(value))
        kv_lines.append(line)

    kv("Environment", status.environment or "unknown")
    kv("Run", status.run_name)
    kv("Backend", status.backend)
    kv("Status", status.state)
    total_elapsed = sum(stage.elapsed_seconds or 0 for stage in status.stages)
    if total_elapsed:
        kv("Elapsed", _format_elapsed(total_elapsed))
    if status.failed_stage:
        kv("Failed stage", status.failed_stage)
    current_activity = status.metrics.get("cadence.current_activity")
    if current_activity:
        kv("Activity", current_activity)
    renderables.extend(kv_lines)

    if status.stages:
        renderables.append(Text("\nStages"))
        renderables.append(_stages_table(status, spin=True, active_stage_elapsed=active_stage_elapsed))

    if step_detail:
        running_stage = next((stage.name for stage in status.stages if stage.status == "running"), "running")
        tree = Tree(Text(running_stage, style="bold yellow"))
        for label, state, elapsed in step_detail:
            tree.add(_step_label(label, state, elapsed))
        renderables.append(Text(""))
        renderables.append(tree)

    return Group(*renderables)


def _step_label(label: str, state: str, elapsed: float | None = None):
    """One tree row for `render_live`'s expanded stage view -- a live
    spinner for the one step actively running (plus its own blinking
    elapsed time, when the backend has a live timestamp for it -- see
    stage_step_detail), a plain marker for everything else. Spinner's
    own `text` parameter accepts any renderable and draws it right
    after the spinner glyph on the same line, so the label and elapsed
    span are built as one combined Text rather than two separate
    renderables (Rich has no "lay these out on one line" composition
    for a tree.add() child, which must be a single renderable)."""
    from rich.spinner import Spinner
    from rich.text import Text

    if state == "running":
        line = Text(f" {label}", style="yellow")
        if elapsed is not None:
            line.append(" — ", style="dim")
            line.append(_format_elapsed(elapsed), style="yellow blink")
        return Spinner("dots", text=line, style="yellow")
    marker = _STATE_MARKERS.get(state, "○")
    return Text(f"{marker} {label}", style=_STATE_STYLES.get(state, "dim"))

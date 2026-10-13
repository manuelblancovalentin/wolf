"""`wolf monitor` -- a real full-screen Textual TUI for watching a WOLF
run's live progress.

Kept separate from `wolf.commands.monitor` so Textual is only imported
when this specific subcommand actually runs, not on every WOLF
invocation (same convention as `wolf.config_menu`/`wolf.env_menu`).

This is a richer sibling of `wolf status --watch` (`wolf.commands.status`),
not a replacement -- that one stays the simple, scriptable, non-interactive
choice (pipeable, works over a flaky SSH session, no keyboard event loop).
`wolf monitor` instead gives arrow-key navigation: one real table of
stage rows (Status/Elapsed/QoR), each expandable in place into its own
step detail -- a single nested tree-table, not a table alongside a
separate detail pane -- with only one stage expanded at a time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static, Tree
from textual.widgets.tree import TreeNode

from wolf.backend import get_backend
from wolf.status import (
    RunStatus, _format_elapsed, _STATE_MARKERS, _STATE_STYLES, load_status,
)
from wolf.ui import WOLF_HEADER, _banner_text

_POLL_SECONDS = 1.5

# Fixed column widths -- the header Static and every stage row are
# built from the same widths, so a stage row's own columns line up
# with the header above it. A child step row is deliberately NOT
# forced into these same column boundaries (it has no QoR of its own,
# and Tree's own per-depth indent already pushes it right) -- just a
# marker, name, and optional elapsed.
_COLUMNS = (("Stage", 14), ("Status", 11), ("Elapsed", 12),
            ("Area (mm²)", 11), ("WNS (ps)", 9), ("TNS (ps)", 10),
            ("Viol", 5), ("Power (mW)", 11))


def _row_text(cells: tuple[str, ...], *, style: Optional[str] = None):
    from rich.text import Text

    text = Text(style=style or "")
    for (_, width), cell in zip(_COLUMNS, cells):
        text.append(f"{cell:<{width}} ")
    return text


def _header_text():
    from rich.text import Text

    text = Text(style="bold cyan")
    for name, width in _COLUMNS:
        text.append(f"{name:<{width}} ")
    return text


def _stage_row_cells(stage, qor_by_stage: dict, active_stage_elapsed: Optional[float]) -> tuple[str, ...]:
    if stage.status == "running" and active_stage_elapsed is not None:
        elapsed = _format_elapsed(active_stage_elapsed)
    else:
        elapsed = _format_elapsed(stage.elapsed_seconds)
    marker = _STATE_MARKERS.get(stage.status, "○")
    kinds = qor_by_stage.get(stage.name, {})
    area = kinds.get("area", {})
    timing = kinds.get("timing", {})
    power = kinds.get("power", {})
    return (
        stage.name,
        f"{marker} {stage.status}",
        elapsed,
        f"{area['total_area_um2'] / 1e6:.2f}" if "total_area_um2" in area else "-",
        f"{timing['worst_slack_ps']:g}" if "worst_slack_ps" in timing else "-",
        f"{timing['total_negative_slack_ps']:g}" if "total_negative_slack_ps" in timing else "-",
        f"{int(timing['failing_endpoints'])}" if "failing_endpoints" in timing else "-",
        f"{power['total_w'] * 1000:.1f}" if "total_w" in power else "-",
    )


def _step_row_text(label: str, state: str, elapsed: Optional[float]):
    from rich.text import Text

    style = _STATE_STYLES.get(state, "dim")
    marker = _STATE_MARKERS.get(state, "○")
    text = Text(f"{marker} {label}", style=style)
    if elapsed is not None:
        text.append(" — ", style="dim")
        text.append(_format_elapsed(elapsed), style=f"{style} blink")
    return text


class MonitorApp(App[None]):
    """`wolf monitor` -- one merged tree-table: every stage is a row,
    with QoR columns, expandable in place into its own step detail."""

    CSS = """
    Screen { background: $surface; }
    #info { padding: 0 1; }
    #columns-header { padding: 1 1 0 1; }
    #stages { padding: 0 1; }
    """
    TITLE = "WOLF monitor"
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, run_directory: Path):
        super().__init__()
        self._run_directory = run_directory
        self._expanded_stage: Optional[str] = None
        self._auto_expand_done = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="banner")
        yield Static(id="info")
        yield Static(_header_text(), id="columns-header")
        yield Tree("Stages", id="stages")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#banner", Static).update(_banner_text(WOLF_HEADER))
        tree = self.query_one("#stages", Tree)
        tree.show_root = False
        tree.guide_depth = 3
        # Expand/collapse is driven entirely by our own
        # on_tree_node_selected -> _expanded_stage -> _refresh loop
        # (the single-stage-at-a-time invariant lives there); Tree's
        # own native toggle-on-select would just get immediately
        # overridden by the next rebuild anyway, so turn it off rather
        # than race it.
        tree.auto_expand = False
        self._refresh()
        self.set_interval(_POLL_SECONDS, self._refresh)

    def _refresh(self) -> None:
        status = load_status(self._run_directory)
        self._update_info(status)
        if not self._auto_expand_done:
            running = next((stage.name for stage in status.stages if stage.status == "running"), None)
            if running:
                self._expanded_stage = running
                self._auto_expand_done = True
        self._update_tree(status)

    def _update_info(self, status: RunStatus) -> None:
        from rich.console import Group
        from rich.text import Text

        def kv(key: str, value: object) -> Text:
            line = Text("  ")
            line.append(key, style="bold #ad4ce5")
            line.append(": ")
            line.append(str(value))
            return line

        lines = [
            kv("Environment", status.environment or "unknown"),
            kv("Run", status.run_name),
            kv("Backend", status.backend),
            kv("Status", status.state),
        ]
        total_elapsed = sum(stage.elapsed_seconds or 0 for stage in status.stages)
        if total_elapsed:
            lines.append(kv("Elapsed", _format_elapsed(total_elapsed)))
        if status.failed_stage:
            lines.append(kv("Failed stage", status.failed_stage))
        current_activity = status.metrics.get("cadence.current_activity")
        if current_activity:
            lines.append(kv("Activity", current_activity))
        self.query_one("#info", Static).update(Group(*lines))

    def _update_tree(self, status: RunStatus) -> None:
        tree = self.query_one("#stages", Tree)
        cursor_stage = tree.cursor_node.data if tree.cursor_node else None
        tree.root.remove_children()
        qor_by_stage = status.metrics.get("cadence.qor_by_stage") or {}
        active_stage_elapsed = status.metrics.get("cadence.active_stage_elapsed_seconds")
        backend = get_backend(status.backend)
        cursor_target: Optional[TreeNode] = None
        for stage in status.stages:
            cells = _stage_row_cells(stage, qor_by_stage, active_stage_elapsed)
            style = {
                "complete": "green", "running": "yellow", "failed": "red",
            }.get(stage.status, "")
            node = tree.root.add(_row_text(cells, style=style), data=stage.name, allow_expand=True)
            if stage.name == cursor_stage:
                cursor_target = node
            if stage.name == self._expanded_stage:
                node.expand()
                try:
                    detail = backend.stage_step_detail(self._run_directory, stage.name)
                except (ValueError, AttributeError, OSError):
                    detail = ()
                for label, state, elapsed in detail:
                    node.add_leaf(_step_row_text(label, state, elapsed))
            else:
                node.collapse()
        if cursor_target is not None:
            # TreeNode._line (what move_cursor reads to pick a line) is
            # only populated when Tree's own _tree_lines is actually
            # built -- lazily, on next access, not synchronously when a
            # node is added. Referencing it here first forces that
            # build immediately; skipping this makes move_cursor read
            # a stale _line of -1, which Tree's own cursor-line
            # validation then clamps to 0 -- the real bug behind the
            # cursor always snapping back to the first row on refresh.
            tree._tree_lines  # noqa: B018 -- forces the lazy rebuild, see above
            tree.move_cursor(cursor_target)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if event.node.parent is not self.query_one("#stages", Tree).root:
            return  # A leaf step row -- nothing to toggle.
        stage_name = event.node.data
        self._expanded_stage = None if stage_name == self._expanded_stage else stage_name
        self._refresh()

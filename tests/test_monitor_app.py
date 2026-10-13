import asyncio
from pathlib import Path
import tempfile
import unittest

from textual.widgets import Tree

from wolf.monitor_app import MonitorApp


def _run_async(coro):
    return asyncio.run(coro)


class MonitorAppTests(unittest.TestCase):
    """Drives the real TUI (Textual's own headless Pilot), the same bar
    `wolf env menu`/`wolf config menu` are held to. One merged
    tree-table: every stage is a top-level row, expandable in place
    into its own step detail -- not a table alongside a separate
    detail pane."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-monitor-")
        self.root = Path(self.temporary.name)
        self.run_directory = self.root / "work" / "demo.1"
        self.run_directory.mkdir(parents=True)
        (self.run_directory / "wolf.resolved.yaml").write_text(
            "schema: wolf.resolved-run/v1\nenvironment: demo-env\n"
            "backend:\n  name: cadence-flowtool\n", encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _write_status(self, text: str) -> None:
        (self.run_directory / "flow.status").write_text(text, encoding="utf-8")

    def _write_events(self, text: str) -> None:
        (self.run_directory / "wolf.step-status").write_text(text, encoding="utf-8")

    @staticmethod
    def _stage_nodes(app):
        return list(app.query_one("#stages", Tree).root.children)

    def _node_for(self, app, stage_name):
        for node in self._stage_nodes(app):
            if node.data == stage_name:
                return node
        raise AssertionError(f"no stage row for {stage_name!r}")

    def test_the_running_stage_is_auto_expanded_on_startup(self):
        self._write_status(
            "{script flowtool status invoked arguments "
            "{-from syn_map -to syn_map -interactive}}\n"
        )
        self._write_events("block_start|starting|1700000000\n")

        async def drive():
            app = MonitorApp(self.run_directory)
            async with app.run_test(size=(160, 55)) as pilot:
                await pilot.pause()
                self.assertEqual(app._expanded_stage, "syn_map")
                nodes = self._stage_nodes(app)
                self.assertEqual(len(nodes), 9)
                syn_map = self._node_for(app, "syn_map")
                self.assertTrue(syn_map.is_expanded)
                labels = [str(child.label) for child in syn_map.children]
                self.assertTrue(any("block_start" in label for label in labels))
                # Every other stage row stays collapsed, with no
                # children materialized at all.
                other = self._node_for(app, "syn_generic")
                self.assertFalse(other.is_expanded)
                self.assertEqual(len(other.children), 0)

        _run_async(drive())

    def test_selecting_a_different_row_switches_the_expanded_stage(self):
        self._write_status(
            "{script flowtool status invoked arguments "
            "{-from syn_map -to syn_map -interactive}}\n"
        )
        self._write_events("block_start|starting|1700000000\n")

        async def drive():
            app = MonitorApp(self.run_directory)
            async with app.run_test(size=(160, 55)) as pilot:
                await pilot.pause()
                self.assertEqual(app._expanded_stage, "syn_map")
                tree = app.query_one("#stages", Tree)
                tree.move_cursor(self._node_for(app, "syn_generic"))
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app._expanded_stage, "syn_generic")
                self.assertTrue(self._node_for(app, "syn_generic").is_expanded)
                self.assertFalse(self._node_for(app, "syn_map").is_expanded)

        _run_async(drive())

    def test_selecting_the_already_expanded_row_collapses_it(self):
        self._write_status(
            "{script flowtool status invoked arguments "
            "{-from syn_map -to syn_map -interactive}}\n"
        )
        self._write_events("block_start|starting|1700000000\n")

        async def drive():
            app = MonitorApp(self.run_directory)
            async with app.run_test(size=(160, 55)) as pilot:
                await pilot.pause()
                tree = app.query_one("#stages", Tree)
                tree.move_cursor(self._node_for(app, "syn_map"))
                await pilot.press("enter")
                await pilot.pause()
                self.assertIsNone(app._expanded_stage)
                self.assertEqual(len(self._node_for(app, "syn_map").children), 0)

        _run_async(drive())

    def test_selecting_a_leaf_step_row_does_not_toggle_the_stage(self):
        """A leaf step row is itself selectable (Tree fires
        NodeSelected for it too), but it must not be mistaken for a
        stage row and toggle the expansion."""
        self._write_status(
            "{script flowtool status invoked arguments "
            "{-from syn_map -to syn_map -interactive}}\n"
        )
        self._write_events("block_start|starting|1700000000\n")

        async def drive():
            app = MonitorApp(self.run_directory)
            async with app.run_test(size=(160, 55)) as pilot:
                await pilot.pause()
                tree = app.query_one("#stages", Tree)
                leaf = self._node_for(app, "syn_map").children[0]
                tree.move_cursor(leaf)
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(app._expanded_stage, "syn_map")

        _run_async(drive())

    def test_no_running_stage_leaves_nothing_expanded_by_default(self):
        async def drive():
            app = MonitorApp(self.run_directory)
            async with app.run_test(size=(160, 55)) as pilot:
                await pilot.pause()
                self.assertIsNone(app._expanded_stage)
                self.assertEqual(len(self._stage_nodes(app)), 9)

        _run_async(drive())

    def test_qor_columns_populate_from_real_reports(self):
        reports = self.run_directory / "reports"
        reports.mkdir()
        (reports / "area.syn_generic.rpt").write_text(
            "-------------------------------------------------------------\n"
            "ESP_ASIC_TOP                 3286713 24485968.048    87.318  24486055.365 \n",
            encoding="utf-8",
        )
        (reports / "timing.syn_generic.rpt").write_text(
            " View: ALL            -607.6  -34174.8    66 \n", encoding="utf-8",
        )
        (reports / "power.syn_generic.rpt").write_text(
            "    Subtotal     1.26162e-01  8.46601e-01  1.89968e-05  9.72781e-01 100.00%\n",
            encoding="utf-8",
        )

        async def drive():
            app = MonitorApp(self.run_directory)
            async with app.run_test(size=(160, 55)) as pilot:
                await pilot.pause()
                node = self._node_for(app, "syn_generic")
                row = str(node.label)
                self.assertIn("24.49", row)
                self.assertIn("-607.6", row)
                self.assertIn("972.8", row)

        _run_async(drive())


if __name__ == "__main__":
    unittest.main()

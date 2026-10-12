import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from wolf.cli import build_parser
from wolf.commands.status import command_status
from wolf.status import _format_elapsed, load_status, render_human, select_run


class FormatElapsedTests(unittest.TestCase):
    def test_none_renders_as_a_dash(self):
        self.assertEqual(_format_elapsed(None), "-")

    def test_sub_minute_renders_as_hhmmss(self):
        self.assertEqual(_format_elapsed(45), "00:00:45")

    def test_hours_and_minutes_render_as_hhmmss(self):
        self.assertEqual(_format_elapsed(662 * 60 + 15), "11:02:15")

    def test_a_full_day_or_more_gets_a_leading_day_count(self):
        self.assertEqual(_format_elapsed(86400 + 3661), "1d 01:01:01")
        self.assertEqual(_format_elapsed(2 * 86400 + 10), "2d 00:00:10")

    def test_under_a_day_never_shows_a_day_prefix(self):
        self.assertEqual(_format_elapsed(86399), "23:59:59")


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-status-")
        self.root = Path(self.temporary.name)
        self.environment = mock.patch.dict(os.environ, {
            "HOME": str(self.root / "home"), "WOLF_HOME": str(self.root / "state"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
        }, clear=True)
        self.environment.start()
        self.env = self.root / "state" / "envs" / "golden"
        self.env.mkdir(parents=True)
        self.run = self.root / "workspace" / "ibex" / "ibex.asap7" / "ibex.1"
        self.run.mkdir(parents=True)
        (self.env / "run.latest.d").symlink_to(self.run)
        (self.run / "wolf.resolved.yaml").write_text(
            "schema: wolf.resolved-run/v1\nenvironment: golden\n"
            "backend:\n  name: orfs\n", encoding="utf-8"
        )
        (self.run / "wolf.stage-results").write_text(
            "synth|complete|34\nfloorplan|complete|8\nplace|failed|2\n", encoding="utf-8"
        )
        reports = self.run / "reports"
        reports.mkdir()
        (reports / "metadata.json").write_text(
            '{"finish": {"setup": {"ws": 13.31}}, "detailedroute": {"drc": {"errors": 0}}}'
        )
        (reports / "6_finish.rpt").write_text(
            "finish setup_violation_count setup violation count 0\n"
            "finish hold_violation_count hold violation count 0\n"
        )

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def test_latest_selection_is_cwd_independent(self):
        previous = Path.cwd()
        try:
            os.chdir("/")
            first = select_run("golden")
            os.chdir("/tmp")
            second = select_run("golden")
        finally:
            os.chdir(previous)
        self.assertEqual(first, self.run.resolve())
        self.assertEqual(first, second)

    def test_failed_status_and_metrics_are_semantic(self):
        status = load_status(self.run)
        self.assertEqual(status.state, "failed")
        self.assertEqual(status.failed_stage, "place")
        self.assertEqual(status.metrics["timing.worst_slack_ps"], 13.31)
        self.assertEqual(status.metrics["timing.setup_violations"], 0)

    def test_json_and_human_output_share_model(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            command_status(mock.Mock(run=None, environment="golden", json=True, watch=False))
        document = json.loads(output.getvalue())
        self.assertEqual(document["schema"], "wolf.status/v1")
        self.assertEqual(document["run"]["status"], "failed")
        human = io.StringIO()
        with contextlib.redirect_stdout(human):
            render_human(load_status(self.run))
        self.assertIn("Worst slack", human.getvalue())
        self.assertIn("place", human.getvalue())

    def test_no_run_is_reported_without_creating_state(self):
        result = command_status(mock.Mock(run=None, environment="missing", json=False, watch=False))
        self.assertEqual(result, 0)
        self.assertFalse((self.root / "state" / "envs" / "missing").exists())

    def test_explicit_run_path_and_frozen_provenance_are_read_only(self):
        before = (self.run / "wolf.resolved.yaml").read_bytes()
        args = mock.Mock(run=str(self.run), environment=None, json=True, watch=False)
        self.assertEqual(command_status(args), 0)
        self.assertEqual((self.run / "wolf.resolved.yaml").read_bytes(), before)

    def test_status_command_is_registered(self):
        parser = build_parser()
        args = parser.parse_args(["status", "--run", str(self.run), "--json"])
        self.assertTrue(args.json)

    def test_watch_flag_is_registered_and_defaults_to_off(self):
        parser = build_parser()
        args = parser.parse_args(["status", "--run", str(self.run)])
        self.assertFalse(args.watch)
        watching = parser.parse_args(["status", "--run", str(self.run), "--watch"])
        self.assertTrue(watching.watch)

    def test_watch_and_json_together_is_rejected(self):
        args = mock.Mock(run=str(self.run), environment=None, json=True, watch=True)
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            command_status(args)

    def test_watch_exits_once_the_run_reaches_a_terminal_state(self):
        """The --watch loop must not use the external `watch` command
        (which strips Rich's own color/formatting) -- it re-renders a
        fresh panel itself via rich.live.Live until the run's own state
        settles, then returns an exit code matching success/failure."""
        from wolf.commands import status as status_module

        statuses = [
            mock.Mock(state="running", stages=[], backend="orfs"),
            mock.Mock(state="completed", stages=[], backend="orfs"),
        ]
        with mock.patch.object(status_module, "load_status", side_effect=statuses), \
             mock.patch.object(status_module, "render_live", side_effect=[object(), object()]), \
             mock.patch.object(status_module.time, "sleep") as sleep_mock, \
             mock.patch("rich.live.Live") as live_cls:
            result = status_module._watch(self.run)
        self.assertEqual(result, 0)
        sleep_mock.assert_called_once()
        live_cls.return_value.__enter__.return_value.update.assert_called_once()

    def test_watch_returns_a_nonzero_exit_code_once_the_run_fails(self):
        from wolf.commands import status as status_module

        statuses = [mock.Mock(state="failed", stages=[], backend="orfs")]
        with mock.patch.object(status_module, "load_status", side_effect=statuses), \
             mock.patch.object(status_module, "render_live", return_value=object()), \
             mock.patch.object(status_module.time, "sleep") as sleep_mock, \
             mock.patch("rich.live.Live"):
            result = status_module._watch(self.run)
        self.assertEqual(result, 1)
        sleep_mock.assert_not_called()

    def test_watch_exits_cleanly_on_keyboard_interrupt(self):
        from wolf.commands import status as status_module

        with mock.patch.object(status_module, "load_status", side_effect=KeyboardInterrupt), \
             mock.patch("rich.live.Live"):
            result = status_module._watch(self.run)
        self.assertEqual(result, 0)

    def test_historical_orfs_run_infers_completed_stages_without_metadata(self):
        historical = self.root / "historical"
        historical.mkdir()
        (historical / "wolf.resolved.yaml").write_text(
            "schema: wolf.resolved-run/v1\nenvironment: golden\nbackend:\n  name: orfs\n",
            encoding="utf-8",
        )
        results = historical / "results"
        results.mkdir()
        for name in ("1_synth.odb", "2_floorplan.odb", "3_place.odb", "4_cts.odb", "5_route.odb", "6_final.odb", "6_final.gds"):
            (results / name).write_text("artifact", encoding="utf-8")
        reports = historical / "reports"
        reports.mkdir()
        (reports / "6_finish.rpt").write_text(
            "worst slack max 13.31\nmax slew violation count 64\n"
            "max fanout violation count 0\nmax cap violation count 0\n"
            "setup violation count 0\nhold violation count 0\n",
            encoding="utf-8",
        )
        (reports / "5_route_drc.rpt").write_text("", encoding="utf-8")
        status = load_status(historical)
        self.assertEqual(status.state, "completed")
        self.assertTrue(all(stage.status == "complete" for stage in status.stages))
        self.assertIsNone(status.stages[0].elapsed_seconds)
        self.assertEqual(status.metrics["timing.setup_violations"], 0)
        self.assertEqual(status.metrics["physical.drc_violations"], 0)

    def test_human_metrics_render_numeric_values(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            render_human(load_status(self.run))
        rendered = output.getvalue()
        self.assertIn("Setup violations", rendered)
        self.assertIn("0", rendered)
        self.assertNotIn("Setup violations         Setup violations", rendered)

    def test_stage_elapsed_seconds_from_metrics_fills_in_inferred_stages_only(self):
        """Regression: Cadence/Flowtool runs have no wolf.stage-results
        file (that's written by the generic shell-stage orchestration
        path, not a single opaque Flowtool invocation), so their only
        source of real per-stage timing is flow.metrics -- extract_metrics'
        own "stage_elapsed_seconds" convention key must fill
        StageResult.elapsed_seconds for a stage status.py otherwise only
        has an inferred bare status for, and must never override a stage
        that already has its own recorded (wolf.stage-results) timing."""
        cadence_run = self.root / "workspace" / "demo" / "demo.1"
        cadence_run.mkdir(parents=True)
        (cadence_run / "wolf.resolved.yaml").write_text(
            "schema: wolf.resolved-run/v1\nenvironment: golden\n"
            "backend:\n  name: cadence-flowtool\n", encoding="utf-8",
        )
        with mock.patch(
            "wolf.backend.cadence_flowtool.CadenceFlowtoolBackend.infer_stage_results",
            return_value={"syn_generic": "complete"},
        ), mock.patch(
            "wolf.backend.cadence_flowtool.CadenceFlowtoolBackend.extract_metrics",
            return_value={
                "cadence.total_real_seconds": 39735.0,
                "stage_elapsed_seconds": {"syn_generic": 39735.0, "syn_map": 12.0},
            },
        ):
            status = load_status(cadence_run)
        syn_generic = next(stage for stage in status.stages if stage.name == "syn_generic")
        self.assertEqual(syn_generic.elapsed_seconds, 39735.0)
        # "stage_elapsed_seconds" is internal plumbing, not a displayed
        # metric -- it must not leak into the public metrics dict.
        self.assertNotIn("stage_elapsed_seconds", status.metrics)
        self.assertEqual(status.metrics["cadence.total_real_seconds"], 39735.0)

    def test_recorded_wolf_stage_results_timing_wins_over_metrics_stage_elapsed(self):
        with mock.patch(
            "wolf.backend.orfs.OrfsBackend.extract_metrics",
            return_value={"stage_elapsed_seconds": {"synth": 999.0}},
        ):
            status = load_status(self.run)
        synth = next(stage for stage in status.stages if stage.name == "synth")
        self.assertEqual(synth.elapsed_seconds, 34.0)


if __name__ == "__main__":
    unittest.main()

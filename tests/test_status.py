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
from wolf.status import load_status, render_human, select_run


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
            command_status(mock.Mock(run=None, environment="golden", json=True))
        document = json.loads(output.getvalue())
        self.assertEqual(document["schema"], "wolf.status/v1")
        self.assertEqual(document["run"]["status"], "failed")
        human = io.StringIO()
        with contextlib.redirect_stdout(human):
            render_human(load_status(self.run))
        self.assertIn("Worst slack", human.getvalue())
        self.assertIn("place", human.getvalue())

    def test_no_run_is_reported_without_creating_state(self):
        result = command_status(mock.Mock(run=None, environment="missing", json=False))
        self.assertEqual(result, 0)
        self.assertFalse((self.root / "state" / "envs" / "missing").exists())

    def test_explicit_run_path_and_frozen_provenance_are_read_only(self):
        before = (self.run / "wolf.resolved.yaml").read_bytes()
        args = mock.Mock(run=str(self.run), environment=None, json=True)
        self.assertEqual(command_status(args), 0)
        self.assertEqual((self.run / "wolf.resolved.yaml").read_bytes(), before)

    def test_status_command_is_registered(self):
        parser = build_parser()
        args = parser.parse_args(["status", "--run", str(self.run), "--json"])
        self.assertTrue(args.json)


if __name__ == "__main__":
    unittest.main()

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from wolf.cli import build_parser
from wolf.commands.monitor import command_monitor


class CommandMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-commands-monitor-")
        self.root = Path(self.temporary.name)
        self.environment = mock.patch.dict(os.environ, {
            "HOME": str(self.root / "home"), "WOLF_HOME": str(self.root / "state"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
        }, clear=True)
        self.environment.start()
        self.env = self.root / "state" / "envs" / "golden"
        self.env.mkdir(parents=True)
        self.run = self.root / "workspace" / "demo" / "demo.1"
        self.run.mkdir(parents=True)
        (self.env / "run.latest.d").symlink_to(self.run)

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def test_monitor_command_is_registered(self):
        parser = build_parser()
        args = parser.parse_args(["monitor", "--run", str(self.run)])
        self.assertEqual(args.run, str(self.run))
        self.assertTrue(args.suppress_ui)

    def test_no_run_is_reported_without_creating_state(self):
        result = command_monitor(mock.Mock(run=None, environment="missing"))
        self.assertEqual(result, 0)
        self.assertFalse((self.root / "state" / "envs" / "missing").exists())

    def test_resolves_the_run_and_launches_the_app(self):
        with mock.patch("wolf.monitor_app.MonitorApp") as app_class:
            result = command_monitor(mock.Mock(run=None, environment="golden"))
        self.assertEqual(result, 0)
        app_class.assert_called_once_with(self.run.resolve())
        app_class.return_value.run.assert_called_once()

    def test_an_explicit_nonexistent_run_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            command_monitor(mock.Mock(run=str(self.root / "nope"), environment=None))


if __name__ == "__main__":
    unittest.main()

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from wolf.commands import session


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-session-")
        self.root = Path(self.temporary.name)
        self.environment = mock.patch.dict(os.environ, {"WOLF_HOME": str(self.root), "WOLF_ACTIVE_ENV": ""}, clear=False)
        self.environment.start()
        (self.root / "envs" / "demo").mkdir(parents=True)

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def test_activate_valid_environment_starts_managed_bash(self):
        with mock.patch("wolf.commands.session.subprocess.call", return_value=0) as call:
            self.assertEqual(session.command_activate(mock.Mock(environment="demo")), 0)
        command = call.call_args.args[0]
        self.assertIn("bash", command)
        env = call.call_args.kwargs["env"]
        self.assertEqual(env["WOLF_ACTIVE_ENV"], "demo")
        self.assertEqual(env["WOLF_MANAGED_SHELL"], "1")

    def test_activate_rejects_missing_or_nested_environment(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            session.command_activate(mock.Mock(environment="missing"))
        with mock.patch.dict(os.environ, {"WOLF_ACTIVE_ENV": "demo"}, clear=False):
            with self.assertRaisesRegex(ValueError, "already active"):
                session.command_activate(mock.Mock(environment="demo"))

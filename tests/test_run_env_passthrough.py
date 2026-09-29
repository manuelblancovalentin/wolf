import os
from pathlib import Path
import unittest
from unittest import mock

from wolf.commands import run as run_command
from wolf.commands.run import _overlay_environment
from wolf.context import ResolvedContext


class OverlayEnvironmentTests(unittest.TestCase):
    def test_overlay_sets_and_restores_previously_unset_vars(self):
        self.assertNotIn("WOLF_TEST_OVERLAY_VAR", os.environ)
        with _overlay_environment({"WOLF_TEST_OVERLAY_VAR": "1"}):
            self.assertEqual(os.environ["WOLF_TEST_OVERLAY_VAR"], "1")
        self.assertNotIn("WOLF_TEST_OVERLAY_VAR", os.environ)

    def test_overlay_restores_previous_value(self):
        os.environ["WOLF_TEST_OVERLAY_VAR"] = "original"
        try:
            with _overlay_environment({"WOLF_TEST_OVERLAY_VAR": "overridden"}):
                self.assertEqual(os.environ["WOLF_TEST_OVERLAY_VAR"], "overridden")
            self.assertEqual(os.environ["WOLF_TEST_OVERLAY_VAR"], "original")
        finally:
            os.environ.pop("WOLF_TEST_OVERLAY_VAR", None)

    def test_overlay_is_noop_for_empty_mapping(self):
        marker = object()
        with _overlay_environment({}):
            self.assertIs(marker, marker)


class GenusFastPathEnvPassthroughTests(unittest.TestCase):
    def test_declarative_genus_run_sees_declared_env_vars(self):
        root = Path("/tmp/wolf-genus-env-passthrough-test")
        context = ResolvedContext(
            state_root=root,
            environment_name="test",
            environment_directory=root / "env",
            workspace_root=root / "work",
            design_name="demo",
            process="tsmc65",
            backend="cadence-flowtool",
            run_tag="demo",
            run_directory=root / "work" / "demo" / "demo.tsmc65" / "demo",
            values={},
            format="declarative-v1",
            env_vars={"GENUS_NUM_CPUS": "64"},
        )
        args = mock.Mock(plan=False, yes=False, clean=False)
        observed = {}

        def fake_run_genus(_context, *, clean=False):
            observed["GENUS_NUM_CPUS"] = os.environ.get("GENUS_NUM_CPUS")
            return 0, root / "work" / "demo" / "demo.tsmc65" / "demo"

        backend = mock.Mock()
        backend.run_genus.side_effect = fake_run_genus
        self.assertNotIn("GENUS_NUM_CPUS", os.environ)
        with mock.patch("wolf.commands.run._context", return_value=context), mock.patch(
            "wolf.commands.run.get_backend", return_value=backend
        ):
            self.assertEqual(run_command.command_run(args), 0)
        self.assertEqual(observed["GENUS_NUM_CPUS"], "64")
        self.assertNotIn("GENUS_NUM_CPUS", os.environ)


if __name__ == "__main__":
    unittest.main()

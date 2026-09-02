import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"


class InstalledCliTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="wolf-cli-tests-")
        self.root = Path(self._temporary_directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.wolf_home = self.root / "wolf-state"
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "HOME": str(self.home),
                "WOLF_HOME": str(self.wolf_home),
                "PYTHONPATH": str(SOURCE_ROOT),
            }
        )
        self.environment.pop("WOLF_ENV_NAME", None)
        self.environment.pop("WOLF_ENV_DIR", None)
        self.environment.pop("WOLF_LEGACY_ROOT", None)

    def tearDown(self):
        self._temporary_directory.cleanup()

    def wolf(self, *arguments, input_text=None, cwd=None):
        return subprocess.run(
            [sys.executable, "-m", "wolf.cli", *arguments],
            cwd=cwd or self.root,
            env=self.environment,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def assert_success(self, result):
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )

    def create_environment(self, name="test"):
        result = self.wolf("env", "create", name)
        self.assert_success(result)
        return self.wolf_home / "envs" / name

    def test_cli_help(self):
        result = self.wolf("--help")
        self.assert_success(result)
        self.assertIn("░░░░░", result.stdout)
        self.assertIn("WOLF EDA workflow and environment manager", result.stdout)
        self.assertIn("{env,process,backend,run,doctor,activate,deactivate}", result.stdout)
        self.assertNotIn("\x1b", result.stdout)

    def test_cli_version(self):
        result = self.wolf("--version")
        self.assert_success(result)
        self.assertEqual(result.stdout.strip(), "wolf 0.1.0.dev0")

    def test_empty_environment_list(self):
        result = self.wolf("env", "list")
        self.assert_success(result)
        self.assertIn("Available environments", result.stdout)
        self.assertTrue(result.stdout.endswith(" ➤ [INFO] - No WOLF environments found.\n"))
        self.assertNotIn("\x1b", result.stdout)
        self.assertFalse(self.wolf_home.exists())

    def test_environment_listing_is_deterministic(self):
        envs = self.wolf_home / "envs"
        (envs / "zeta").mkdir(parents=True)
        (envs / "alpha").mkdir()
        result = self.wolf("env", "list")
        self.assert_success(result)
        self.assertIn("Available environments", result.stdout)
        self.assertLess(result.stdout.index("➤ alpha"), result.stdout.index("➤ zeta"))

    def test_environment_creation_uses_legacy_files(self):
        path = self.create_environment("alpha")
        self.assertTrue((path / "activate").is_file())
        self.assertTrue((path / "deactivate").is_file())
        self.assertIn('export WOLF_ENV_NAME="alpha"', (path / "activate").read_text())

    def test_environment_show(self):
        path = self.create_environment("alpha")
        (path / "vars.env").write_text('CLOCK_PERIOD="1050 ps"\n', encoding="utf-8")
        (path / "bucket.p").write_text(
            '#!/bin/bash\nsource "/tools/setup.sh"\n', encoding="utf-8"
        )
        result = self.wolf("env", "show", "alpha")
        self.assert_success(result)
        self.assertIn("Name: alpha", result.stdout)
        self.assertIn(f"Path: {path}", result.stdout)
        self.assertIn("CLOCK_PERIOD: 1050 ps", result.stdout)
        self.assertIn("Bucket inputs: 1", result.stdout)

    def test_environment_set_persists_legacy_variable_format(self):
        path = self.create_environment("alpha")
        result = self.wolf("env", "set", "alpha", "CLOCK_PERIOD", "1050 ps")
        self.assert_success(result)
        self.assertEqual(
            (path / "vars.env").read_text(encoding="utf-8"),
            'CLOCK_PERIOD="1050 ps"\n',
        )

    def test_environment_removal_and_confirmation_safeguard(self):
        path = self.create_environment("alpha")
        declined = self.wolf("env", "remove", "alpha", input_text="n\n")
        self.assert_success(declined)
        self.assertTrue(path.is_dir())
        removed = self.wolf("env", "remove", "alpha", "--yes")
        self.assert_success(removed)
        self.assertFalse(path.exists())

    def test_nonexistent_environment_errors(self):
        for arguments in (
            ("env", "show", "missing"),
            ("env", "set", "missing", "KEY", "value"),
            ("env", "remove", "missing", "--yes"),
        ):
            with self.subTest(arguments=arguments):
                result = self.wolf(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertIn("does not exist", result.stderr)

    def test_process_list(self):
        empty = self.wolf("process", "list")
        self.assert_success(empty)
        self.assertIn("Available processes", empty.stdout)
        self.assertTrue(empty.stdout.endswith(" ➤ [INFO] - No WOLF processes found.\n"))

        config = self.wolf_home / "config"
        (config / "tsmc65").mkdir(parents=True)
        (config / "asap7").mkdir()
        result = self.wolf("process", "list")
        self.assert_success(result)
        self.assertLess(result.stdout.index("➤ asap7"), result.stdout.index("➤ tsmc65"))

    def test_backend_list_and_show(self):
        listed = self.wolf("backend", "list")
        self.assert_success(listed)
        self.assertIn("Available backends", listed.stdout)
        self.assertIn("cadence-flowtool", listed.stdout)
        self.assertIn("orfs", listed.stdout)

        shown = self.wolf("backend", "show", "cadence-flowtool")
        self.assert_success(shown)
        self.assertIn("Name: cadence-flowtool", shown.stdout)
        self.assertIn("cadence-flowtool.sh", shown.stdout)

        orfs = self.wolf("backend", "show", "orfs")
        self.assert_success(orfs)
        self.assertIn("Name: orfs", orfs.stdout)
        self.assertIn("container", orfs.stdout)
        self.assertIn("ORFS_ROOT", orfs.stdout)

    def test_backend_show_rejects_unknown_backend(self):
        result = self.wolf("backend", "show", "unknown")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown WOLF backend 'unknown'", result.stderr)

    def test_doctor_is_backend_neutral(self):
        result = self.wolf("doctor")
        self.assert_success(result)
        self.assertIn("WOLF version: 0.1.0.dev0 (available)", result.stdout)
        self.assertIn(f"WOLF state root: {self.wolf_home} (available)", result.stdout)
        self.assertIn("Docker:", result.stdout)
        self.assertIn("Podman:", result.stdout)
        self.assertNotIn("Yosys", result.stdout)
        self.assertNotIn("Cadence", result.stdout)
        self.assertNotIn("\x1b", result.stdout)

    def test_run_plan_is_location_independent_for_a_named_environment(self):
        environment = self.create_environment("orfs")
        environment.joinpath("vars.env").write_text(
            "\n".join(
                (
                    'DESIGN_NAME="ibex"',
                    'PROCESS="asap7"',
                    'BACKEND="orfs"',
                    'WORKSPACE_DIR="./workspace"',
                    'DATA_DIR="./rtl"',
                    'ORFS_ROOT="./orfs/flow"',
                    'ORFS_DESIGN_CONFIG="./orfs/flow/designs/asap7/ibex/config.mk"',
                    'ORFS_SDC_FILE="./orfs/flow/designs/asap7/ibex/constraint.sdc"',
                    '',
                )
            ),
            encoding="utf-8",
        )
        from_root = self.wolf("run", "--environment", "orfs", "--plan", cwd="/")
        from_tmp = self.wolf("run", "--environment", "orfs", "--plan", cwd="/tmp")
        self.assert_success(from_root)
        self.assert_success(from_tmp)
        expected_workspace = environment / "workspace"
        expected_run = expected_workspace / "ibex" / "ibex.asap7" / "ibex"
        for result in (from_root, from_tmp):
            self.assertIn(f"Workspace root: {expected_workspace}", result.stdout)
            self.assertIn(f"Run directory: {expected_run}", result.stdout)
            self.assertIn("Design: ibex", result.stdout)
            self.assertIn("Technology: asap7", result.stdout)
            self.assertIn("Backend: orfs", result.stdout)

    def test_run_plan_cli_workspace_is_invocation_relative(self):
        invocation = self.root / "invocation"
        invocation.mkdir()
        result = self.wolf(
            "run", "--plan", "--design", "ibex", "--process", "asap7",
            "--backend", "orfs", "--workspace", "work", cwd=invocation,
        )
        self.assert_success(result)
        self.assertIn(f"Workspace root: {invocation / 'work'}", result.stdout)

    def test_ui_emits_color_for_a_color_capable_terminal(self):
        script = """
import io
from rich.console import Console
from wolf import ui

stream = io.StringIO()
ui.console = Console(
    file=stream,
    force_terminal=True,
    color_system="truecolor",
    no_color=False,
    width=140,
)
ui.header("env", "Environment test")
ui.success("[red]literal user value[/red]")
print(stream.getvalue(), end="")
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=self.root,
            env=self.environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assert_success(result)
        self.assertIn("\x1b[38;2;173;76;229m", result.stdout)
        self.assertIn("Environment test", result.stdout)
        self.assertIn("[red]literal user value[/red]", result.stdout)

    def test_wolf_home_isolates_state_from_home(self):
        real_default = self.home / ".wolf"
        sentinel = real_default / "envs" / "do-not-touch"
        sentinel.mkdir(parents=True)
        (sentinel / "sentinel").write_text("preserve", encoding="utf-8")

        path = self.create_environment("isolated")

        self.assertTrue(path.is_dir())
        self.assertEqual((sentinel / "sentinel").read_text(), "preserve")
        self.assertEqual([entry.name for entry in real_default.joinpath("envs").iterdir()], ["do-not-touch"])


if __name__ == "__main__":
    unittest.main()

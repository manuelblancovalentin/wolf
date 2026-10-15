"""`wolf env set`/`wolf env unset` routing between wolf.yaml (environment-
level) and setup.<design_name>.yaml (design-level, see
cadence_genus_setup.DESIGN_SETUP_ALLOWED_KEYS)."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

from wolf.backend.cadence_genus_setup import design_setup_path


class EnvSetUnsetDesignSetupRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-env-design-setup-")
        self.root = Path(self.temporary.name)
        self.project_root = self.root / "project"
        self.environment_directory = self.root / "wolf-home" / "envs" / "demo-env"
        self.environment_directory.mkdir(parents=True)
        (self.environment_directory / "wolf.yaml").write_text(
            yaml.safe_dump({
                "schema": "wolf.environment/v1",
                "name": "demo-env",
                "design": {"name": "demo-design"},
                "technology": {"name": "demo-tech"},
                "flow": {"backend": "cadence-flowtool"},
                "project": {"root": str(self.project_root)},
                "workspace": {"root": str(self.project_root / "workspace")},
            }),
            encoding="utf-8",
        )
        self.environment = os.environ.copy()
        self.environment.update({
            "WOLF_HOME": str(self.root / "wolf-home"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        })
        self.setup_path = design_setup_path(self.project_root, "demo-design")

    def tearDown(self):
        self.temporary.cleanup()

    def wolf(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "wolf.cli", *arguments], cwd="/",
            env=self.environment, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )

    def _wolf_yaml(self) -> dict:
        return yaml.safe_load((self.environment_directory / "wolf.yaml").read_text(encoding="utf-8"))

    def test_design_level_key_is_routed_to_setup_yaml_not_wolf_yaml(self):
        result = self.wolf(
            "env", "set", "demo-env", "add_tieoffs_cells", '["TIEHIX1", "TIELOX1"]',
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(self.setup_path.is_file())
        setup = yaml.safe_load(self.setup_path.read_text(encoding="utf-8"))
        self.assertEqual(setup["add_tieoffs_cells"], ["TIEHIX1", "TIELOX1"])
        self.assertNotIn("backend", self._wolf_yaml())

    def test_environment_level_key_still_goes_to_wolf_yaml(self):
        new_root = str(self.project_root / "workspace2")
        result = self.wolf("env", "set", "demo-env", "workspace.root", new_root)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(self._wolf_yaml()["workspace"]["root"], new_root)
        self.assertFalse(self.setup_path.exists())

    def test_nested_design_level_key(self):
        result = self.wolf(
            "env", "set", "demo-env", "active_views.setup", '["wcl"]',
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        setup = yaml.safe_load(self.setup_path.read_text(encoding="utf-8"))
        self.assertEqual(setup["active_views"], {"setup": ["wcl"]})

    def test_unset_design_level_key_removes_it_and_prunes_empty_parent(self):
        self.wolf("env", "set", "demo-env", "active_views.setup", '["wcl"]')
        result = self.wolf("env", "unset", "demo-env", "active_views.setup")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        setup = yaml.safe_load(self.setup_path.read_text(encoding="utf-8")) or {}
        self.assertEqual(setup, {})

    def test_unset_environment_level_key_goes_to_wolf_yaml(self):
        new_root = str(self.project_root / "workspace2")
        self.wolf("env", "set", "demo-env", "workspace.root", new_root)
        result = self.wolf("env", "unset", "demo-env", "workspace.root")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("workspace", self._wolf_yaml())

    def test_unset_a_key_that_was_never_set_is_a_noop(self):
        result = self.wolf("env", "unset", "demo-env", "technology.vth")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(self._wolf_yaml()["technology"], {"name": "demo-tech"})

    def test_set_refreshes_the_wolf_yaml_symlink_in_inputs_env(self):
        result = self.wolf("env", "set", "demo-env", "add_tieoffs_cells", "[]")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        link = self.project_root / "inputs" / "env" / "demo-design" / "wolf.demo-env.yaml"
        self.assertTrue(link.is_symlink())
        self.assertEqual(
            link.resolve(), (self.environment_directory / "wolf.yaml").resolve(),
        )

    def test_set_without_project_root_is_rejected_for_design_level_key(self):
        no_project_dir = self.root / "wolf-home" / "envs" / "no-project"
        no_project_dir.mkdir(parents=True)
        (no_project_dir / "wolf.yaml").write_text(
            yaml.safe_dump({
                "schema": "wolf.environment/v1",
                "name": "no-project",
                "design": {"name": "demo-design"},
                "flow": {"backend": "cadence-flowtool"},
                "workspace": {"root": str(self.root / "workspace")},
            }),
            encoding="utf-8",
        )
        result = self.wolf("env", "set", "no-project", "add_tieoffs_cells", "[]")
        self.assertEqual(result.returncode, 2)
        self.assertIn("project.root", result.stderr)

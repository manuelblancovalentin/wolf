import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]


class EnvAutoSetupTests(unittest.TestCase):
    """`wolf env auto-setup` scaffolds inputs/outputs/workspace under project.root.

    Backend-agnostic: directories only, no PDK/flow-specific content, mirroring
    the legacy Bash `wolf env auto-setup` directory spec (bin/wolf.env).
    """

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-auto-setup-")
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.env = os.environ.copy()
        self.env.update({
            "HOME": str(self.root / "home"),
            "WOLF_HOME": str(self.state),
            "WOLF_REGISTRY": str(self.root / "registry"),
            "PYTHONPATH": str(REPO_ROOT / "src"),
        })
        for key in ("WOLF_ACTIVE_ENV", "WOLF_ENV_NAME"):
            self.env.pop(key, None)

    def tearDown(self):
        self.temporary.cleanup()

    def wolf(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "wolf.cli", *args], cwd=self.root,
            env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )

    def _create(self, name, yaml_text):
        source = self.root / f"{name}.yaml"
        source.write_text(yaml_text, encoding="utf-8")
        result = self.wolf("env", "create", name, "--from", str(source))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_scaffolds_inputs_outputs_workspace_and_is_idempotent(self):
        self._create("demo", """schema: wolf.environment/v1
name: demo
design:
  name: my_design
project:
  root: ./project
""")
        result = self.wolf("env", "auto-setup", "demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        project = self.root / "project"
        for relative in (
            "inputs/calibre/my_design", "inputs/constraints/my_design", "inputs/env/my_design",
            "inputs/floorplans/my_design", "inputs/hdl/my_design", "inputs/scripts/my_design",
            "inputs/tb/my_design", "inputs/lib/gds", "inputs/lib/lef", "inputs/lib/spice",
            "inputs/lib/timing", "inputs/lib/verilog", "outputs/my_design", "workspace",
        ):
            self.assertTrue((project / relative).is_dir(), f"missing {relative}")
        self.assertIn("created", result.stdout)

        second = self.wolf("env", "auto-setup", "demo")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("already present", second.stdout)
        self.assertNotIn("inputs: created", second.stdout)

    def test_project_root_is_relative_to_the_source_yaml_not_cwd(self):
        nested = self.root / "nested"
        nested.mkdir()
        source = nested / "wolf.yaml"
        source.write_text("""schema: wolf.environment/v1
name: demo
design:
  name: my_design
project:
  root: ./project
""", encoding="utf-8")
        result = self.wolf("env", "create", "demo", "--from", str(source))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.wolf("env", "auto-setup", "demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((nested / "project" / "outputs" / "my_design").is_dir())

    def test_missing_project_root_is_a_clear_error(self):
        self._create("demo", """schema: wolf.environment/v1
name: demo
design:
  name: my_design
""")
        result = self.wolf("env", "auto-setup", "demo")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("project.root", result.stderr)

    def test_missing_design_name_is_a_clear_error(self):
        self._create("demo", """schema: wolf.environment/v1
name: demo
project:
  root: ./project
""")
        result = self.wolf("env", "auto-setup", "demo")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("design name", result.stderr)

    def test_active_environment_is_used_when_name_omitted(self):
        self._create("demo", """schema: wolf.environment/v1
name: demo
design:
  name: my_design
project:
  root: ./project
""")
        environment = dict(self.env, WOLF_ACTIVE_ENV="demo")
        result = subprocess.run(
            [sys.executable, "-m", "wolf.cli", "env", "auto-setup"], cwd=self.root,
            env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "project" / "outputs" / "my_design").is_dir())


if __name__ == "__main__":
    unittest.main()

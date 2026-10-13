import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]


class InfoCommandTests(unittest.TestCase):
    """`wolf info` on a declarative-v1 environment -- real end-to-end CLI
    runs (subprocess), the same bar other CLI-surface tests are held to,
    not just the underlying profile_semantics helper."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-info-")
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

    def test_bundled_flow_with_a_direct_backend_is_not_reported_as_unresolved(self):
        """Regression, hit for real: a real environment declaring
        flow: {backend: cadence-flowtool} (WOLF's own bundled flow, no
        flow package at all -- the common case, not an edge case) always
        reported "Environment is partial; unresolved: flow, backend"
        even though both were fully, validly set. profile_semantics only
        ever derived "backend" from an installed flow package's own
        metadata, skipping flow.backend's own direct declaration
        entirely whenever there was no package to look up."""
        self._create("demo", """schema: wolf.environment/v1
name: demo
design:
  name: my_design
flow:
  backend: cadence-flowtool
project:
  root: ./project
""")
        result = self.wolf("info", "demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Flow: WOLF's bundled flow", result.stdout)
        self.assertIn("Backend: cadence-flowtool", result.stdout)
        # technology is genuinely unset in this fixture (not what this
        # test is about) -- the real regression is flow/backend no longer
        # showing up in that unresolved list at all.
        unresolved_line = next(
            line for line in result.stdout.splitlines() if "Environment is partial" in line
        )
        self.assertNotIn("flow", unresolved_line)
        self.assertNotIn("backend", unresolved_line)

    def test_workspace_root_defaulted_from_project_root_is_not_unresolved(self):
        self._create("demo", """schema: wolf.environment/v1
name: demo
design:
  name: my_design
flow:
  backend: cadence-flowtool
project:
  root: ./project
""")
        result = self.wolf("info", "demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("workspace.root", result.stdout)

    def test_genuinely_missing_fields_are_still_reported(self):
        self._create("demo", """schema: wolf.environment/v1
name: demo
""")
        result = self.wolf("info", "demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Environment is partial; unresolved:", result.stdout)
        self.assertIn("design", result.stdout)
        self.assertIn("flow", result.stdout)
        self.assertIn("workspace.root", result.stdout)

    def test_bundled_flow_scripts_location_is_shown(self):
        self._create("demo", """schema: wolf.environment/v1
name: demo
design:
  name: my_design
flow:
  backend: cadence-flowtool
project:
  root: ./project
""")
        result = self.wolf("info", "demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Flow scripts:", result.stdout)
        self.assertIn("cadence-genus", result.stdout)

    def test_custom_backend_overrides_and_constraints_are_shown(self):
        """Everything a project can set beyond the basics -- injected
        scripts, active-view selection, power/ground nets, a floorplan
        DEF -- should actually show up in `wolf info`, not just live
        silently in wolf.yaml."""
        self._create("demo", """schema: wolf.environment/v1
name: demo
design:
  name: my_design
flow:
  backend: cadence-flowtool
constraints:
  floorplan_def: ./floorplans/my_design.def
  power_nets: [VDD, VDD1]
  ground_nets: [VSS]
project:
  root: ./project
backend:
  cadence-flowtool:
    inject:
      create_fplan:
        pre: ["./scripts/create_fplan.tcl"]
    active_views:
      setup: [wcl]
      hold: [bc]
""")
        result = self.wolf("info", "demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Floorplan DEF", result.stdout)
        self.assertIn("my_design.def", result.stdout)
        self.assertIn("Power nets: VDD, VDD1", result.stdout)
        self.assertIn("Ground nets: VSS", result.stdout)
        self.assertIn("Backend overrides (cadence-flowtool)", result.stdout)
        self.assertIn("inject.create_fplan.pre", result.stdout)
        self.assertIn("create_fplan.tcl", result.stdout)
        self.assertIn("active_views.setup: wcl", result.stdout)
        self.assertIn("active_views.hold: bc", result.stdout)


if __name__ == "__main__":
    unittest.main()

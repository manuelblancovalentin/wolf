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


class EnvSetUnsetFlowDesignSetupKeysTests(unittest.TestCase):
    """A flow package's own declared design-setup keys (handoff:
    workspace/handoff/wolf-agent-design-setup-template.md) are routed
    to setup.<design>.yaml the same way WOLF's own 26 keys are."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-env-flow-design-setup-")
        self.root = Path(self.temporary.name)
        self.project_root = self.root / "project"
        self.environment_directory = self.root / "wolf-home" / "envs" / "demo-env"
        self.environment_directory.mkdir(parents=True)
        registry = self.root / "registry"
        (registry / "flow").mkdir(parents=True)
        (registry / "flow" / "demoflow.yaml").write_text(yaml.safe_dump({
            "schema_version": 1, "kind": "flow", "name": "demoflow", "description": "demoflow",
            "source": {"type": "git", "url": "https://example.test/demoflow", "revision": "rev"},
            "validation": {"required_paths": []},
            "metadata": {"flow": {
                "name": "demoflow", "backend": "cadence-flowtool",
                "scripts": {"design_setup_template": "design_setup.template.yaml"},
            }},
        }), encoding="utf-8")
        installation = self.root / "wolf-home" / "packages" / "flow" / "demoflow" / "rev"
        content = installation / "source"
        content.mkdir(parents=True)
        (content / "design_setup.template.yaml").write_text(
            "# Description of a flow-only knob.\n"
            "# scalar. Default: standard.\n"
            "# design_flow_effort: standard\n",
            encoding="utf-8",
        )
        (installation / "installed.yaml").write_text(yaml.safe_dump({
            "package": "flow/demoflow", "revision": "rev", "source_revision": "rev",
            "content_path": "source", "installed_at": "2026-09-02T00:00:00Z",
        }), encoding="utf-8")
        (self.environment_directory / "wolf.yaml").write_text(
            yaml.safe_dump({
                "schema": "wolf.environment/v1",
                "name": "demo-env",
                "design": {"name": "demo-design"},
                "technology": {"name": "demo-tech"},
                "flow": {"package": "flow/demoflow"},
                "project": {"root": str(self.project_root)},
                "workspace": {"root": str(self.project_root / "workspace")},
                "env": {},
            }),
            encoding="utf-8",
        )
        self.environment = os.environ.copy()
        self.environment.update({
            "WOLF_HOME": str(self.root / "wolf-home"),
            "WOLF_REGISTRY": str(registry),
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

    def test_a_flow_declared_key_is_routed_to_setup_yaml(self):
        result = self.wolf("env", "set", "demo-env", "design_flow_effort", "extreme")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        setup = yaml.safe_load(self.setup_path.read_text(encoding="utf-8"))
        self.assertEqual(setup["design_flow_effort"], "extreme")

    def test_an_unrelated_unknown_key_still_fails(self):
        result = self.wolf("env", "set", "demo-env", "not_a_real_key", "1")
        self.assertNotEqual(result.returncode, 0)

    def test_unset_a_flow_declared_key(self):
        self.wolf("env", "set", "demo-env", "design_flow_effort", "extreme")
        result = self.wolf("env", "unset", "demo-env", "design_flow_effort")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        setup = yaml.safe_load(self.setup_path.read_text(encoding="utf-8")) or {}
        self.assertEqual(setup, {})

    def test_setting_a_design_level_key_generates_then_preserves_the_template(self):
        """Even a brand-new environment that never had the file at
        all gets the full commented scaffold the first time any
        design-setup key is set, and that scaffold's comments survive
        the set itself -- only the one key's own stanza is uncommented."""
        result = self.wolf("env", "set", "demo-env", "cts_max_fanout", "16")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        text = self.setup_path.read_text(encoding="utf-8")
        self.assertIn("# active_views:", text)
        self.assertIn("demoflow", text)
        self.assertIn("# design_flow_effort: standard", text)
        self.assertIn("cts_max_fanout: 16", text)
        self.assertNotIn("# cts_max_fanout: 16", text)
        setup = yaml.safe_load(text)
        self.assertEqual(setup.get("cts_max_fanout"), 16)
        self.assertNotIn("active_views", setup)

    def test_env_create_from_generates_the_template(self):
        from_file = self.root / "source.yaml"
        from_file.write_text(yaml.safe_dump({
            "schema": "wolf.environment/v1",
            "name": "created-env",
            "design": {"name": "demo-design"},
            "technology": {"name": "demo-tech"},
            "flow": {"package": "flow/demoflow"},
            "project": {"root": str(self.project_root)},
            "workspace": {"root": str(self.project_root / "workspace")},
        }), encoding="utf-8")
        result = self.wolf("env", "create", "created-env", "--from", str(from_file))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        text = self.setup_path.read_text(encoding="utf-8")
        self.assertIn("# active_views:", text)
        self.assertIn("demoflow", text)

    def test_env_create_from_with_no_project_root_does_not_fail(self):
        from_file = self.root / "source2.yaml"
        from_file.write_text(yaml.safe_dump({
            "schema": "wolf.environment/v1",
            "name": "no-project-env",
            "design": {"name": "demo-design"},
            "flow": {"backend": "cadence-flowtool"},
            "workspace": {"root": str(self.root / "workspace")},
        }), encoding="utf-8")
        result = self.wolf("env", "create", "no-project-env", "--from", str(from_file))
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_setting_design_setup_template_regenerates_the_flow_section(self):
        other_template = self.root / "other-template.yaml"
        other_template.write_text(
            "# A different flow-only knob.\n"
            "# scalar. Default: y.\n"
            "# other_flow_key: y\n",
            encoding="utf-8",
        )
        self.wolf("env", "set", "demo-env", "cts_max_fanout", "16")
        result = self.wolf(
            "env", "set", "demo-env", "env.DESIGN_SETUP_TEMPLATE", str(other_template),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        text = self.setup_path.read_text(encoding="utf-8")
        self.assertIn("other_flow_key", text)

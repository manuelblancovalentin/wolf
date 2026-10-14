import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


class FlowInitCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-flow-")
        self.root = Path(self.temporary.name)
        self.source = self.root / "base-flow"
        (self.source / "config").mkdir(parents=True)
        (self.source / "basic.tcl").write_text("puts hello\n", encoding="utf-8")
        (self.source / "flow.template.yaml").write_text("steps: {}\n", encoding="utf-8")
        self.destination = self.root / "project-copy" / "demo-flow"
        self.manifest = self.root / "registry" / "flow" / "demo-flow.yaml"
        self.environment = os.environ.copy()
        self.environment.update({
            "WOLF_HOME": str(self.root / "wolf-home"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        })

    def tearDown(self):
        self.temporary.cleanup()

    def wolf(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "wolf.cli", *arguments], cwd="/",
            env=self.environment, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )

    def test_init_copies_scripts_and_writes_manifest(self):
        result = self.wolf(
            "flow", "init", "demo-flow",
            "--from", str(self.source), "--to", str(self.destination),
            "--manifest", str(self.manifest),
            "--backend", "cadence-flowtool", "--revision", "test-1",
            "--flow-template", "flow.template.yaml",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue((self.destination / "basic.tcl").is_file())
        self.assertTrue((self.destination / "config").is_dir())
        self.assertEqual(
            (self.destination / "basic.tcl").read_text(encoding="utf-8"),
            "puts hello\n",
        )

        manifest = yaml.safe_load(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["kind"], "flow")
        self.assertEqual(manifest["source"]["type"], "local-path")
        self.assertEqual(manifest["source"]["root"], str(self.destination))
        self.assertEqual(manifest["source"]["revision"], "test-1")
        self.assertEqual(manifest["metadata"]["flow"]["backend"], "cadence-flowtool")
        self.assertEqual(
            manifest["metadata"]["flow"]["scripts"]["flow_template"],
            "flow.template.yaml",
        )

    def test_init_refuses_to_overwrite_existing_destination(self):
        self.destination.mkdir(parents=True)
        result = self.wolf(
            "flow", "init", "demo-flow",
            "--from", str(self.source), "--to", str(self.destination),
            "--manifest", str(self.manifest),
            "--backend", "cadence-flowtool", "--revision", "test-1",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("already exists", result.stderr)

    def test_init_requires_existing_source(self):
        result = self.wolf(
            "flow", "init", "demo-flow",
            "--from", str(self.root / "missing"), "--to", str(self.destination),
            "--manifest", str(self.manifest),
            "--backend", "cadence-flowtool", "--revision", "test-1",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not exist", result.stderr)


    def test_installed_flow_package_resolves_end_to_end(self):
        init = self.wolf(
            "flow", "init", "demo-flow",
            "--from", str(self.source), "--to", str(self.destination),
            "--manifest", str(self.manifest),
            "--backend", "cadence-flowtool", "--revision", "test-1",
        )
        self.assertEqual(init.returncode, 0, msg=init.stderr)
        added = self.wolf("registry", "add", "demo-registry", str(self.manifest.parent.parent), "--type", "local")
        self.assertEqual(added.returncode, 0, msg=added.stderr)
        installed = self.wolf("install", "flow/demo-flow")
        self.assertEqual(installed.returncode, 0, msg=installed.stderr)
        info = self.wolf("package", "info", "flow/demo-flow")
        self.assertEqual(info.returncode, 0, msg=info.stderr)
        self.assertIn("cadence-flowtool", info.stdout)
        self.assertIn(str(self.destination), info.stdout)



class FlowSnapshotCliTests(unittest.TestCase):
    """`wolf flow snapshot <env>` -- an inspectable, versioned, project-level
    copy of the bundled cadence-genus flow Tcl, cut only on explicit request
    (never automatically by `wolf run`), under
    inputs/flows/<design>/flow.<N>/."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-flow-snapshot-")
        self.root = Path(self.temporary.name)
        self.project_root = self.root / "project"
        self.environment = os.environ.copy()
        self.environment.update({
            "WOLF_HOME": str(self.root / "wolf-home"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        })
        env_directory = self.root / "wolf-home" / "envs" / "demo-env"
        env_directory.mkdir(parents=True)
        (env_directory / "wolf.yaml").write_text(
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
        self.flows_directory = self.project_root / "inputs" / "flows" / "demo-design"

    def tearDown(self):
        self.temporary.cleanup()

    def wolf(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "wolf.cli", *arguments], cwd="/",
            env=self.environment, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )

    def test_first_snapshot_creates_flow_1_and_a_changelog_header_row(self):
        result = self.wolf("flow", "snapshot", "demo-env")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue((self.flows_directory / "flow.1" / "synthesis.tcl").is_file())
        self.assertTrue((self.flows_directory / "flow.1" / "flow.sha256checksum").is_file())
        self.assertEqual(
            (self.flows_directory / "flow.latest").resolve(),
            (self.flows_directory / "flow.1").resolve(),
        )
        changelog = (self.flows_directory / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("| 1 |", changelog)
        self.assertIn("(initial snapshot)", changelog)

    def test_second_snapshot_with_unchanged_content_is_a_noop(self):
        first = self.wolf("flow", "snapshot", "demo-env")
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        second = self.wolf("flow", "snapshot", "demo-env")
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertIn("unchanged", second.stdout.lower())
        self.assertFalse((self.flows_directory / "flow.2").exists())

    def test_missing_project_root_is_rejected(self):
        env_directory = self.root / "wolf-home" / "envs" / "no-project"
        env_directory.mkdir(parents=True)
        (env_directory / "wolf.yaml").write_text(
            yaml.safe_dump({
                "schema": "wolf.environment/v1",
                "name": "no-project",
                "design": {"name": "demo-design"},
                "technology": {"name": "demo-tech"},
                "flow": {"backend": "cadence-flowtool"},
                "workspace": {"root": str(self.root / "workspace")},
            }),
            encoding="utf-8",
        )
        result = self.wolf("flow", "snapshot", "no-project")
        self.assertEqual(result.returncode, 2)
        self.assertIn("project.root", result.stderr)

if __name__ == "__main__":
    unittest.main()

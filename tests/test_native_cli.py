import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

from wolf.provenance import RUN_MANIFEST_FILENAME


REPO_ROOT = Path(__file__).resolve().parents[1]


class NativeEnvironmentCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-native-cli-")
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.registry = self.root / "registry"
        self.env = os.environ.copy()
        self.env.update({
            "HOME": str(self.root / "home"),
            "WOLF_HOME": str(self.state),
            "WOLF_REGISTRY": str(self.registry),
            "PYTHONPATH": str(REPO_ROOT / "src"),
        })
        self.stub_bin = self.root / "bin"
        self.stub_bin.mkdir()
        self.runtime_log = self.root / "runtime.log"
        podman = self.stub_bin / "podman"
        podman.write_text("""#!/bin/sh
printf '%s\n' "$@" >> "$WOLF_TEST_RUNTIME_LOG"
if [ "$1" = info ]; then exit 0; fi
last=""
for argument in "$@"; do last="$argument"; done
if [ -n "$WOLF_TEST_FAIL_TARGET" ] && [ "$last" = "$WOLF_TEST_FAIL_TARGET" ]; then
  exit 27
fi
exit 0
""", encoding="utf-8")
        podman.chmod(0o755)
        self.env["PATH"] = str(self.stub_bin) + os.pathsep + self.env.get("PATH", "")
        self.env["WOLF_TEST_RUNTIME_LOG"] = str(self.runtime_log)
        for key in ("WOLF_ACTIVE_ENV", "WOLF_ENV_NAME", "ORFS_ROOT"):
            self.env.pop(key, None)
        self._package("rtl", "ibex", "rtl-rev", {"design": {
            "name": "ibex", "top": "ibex_core", "sources": ["rtl/*.sv"],
            "include_dirs": ["rtl"],
        }})
        self._package("pdk", "asap7", "pdk-rev", {"technology": {"name": "asap7"}})
        self._package("flow", "orfs", "flow-rev", {
            "flow": {"name": "orfs", "backend": "orfs"}, "flow_root": "flow"
        })
        design_source = self.state / "packages" / "rtl" / "ibex" / "rtl-rev" / "source" / "rtl"
        design_source.mkdir()
        (design_source / "ibex_core.sv").write_text("module ibex_core; endmodule\n", encoding="utf-8")
        flow_root = self.state / "packages" / "flow" / "orfs" / "flow-rev" / "source" / "flow"
        collateral = flow_root / "designs" / "asap7" / "ibex"
        collateral.mkdir(parents=True)
        (flow_root / "Makefile").write_text("", encoding="utf-8")
        (flow_root / "util").mkdir()
        (collateral / "config.mk").write_text("export CORE_UTILIZATION = 40\n", encoding="utf-8")
        (collateral / "constraint.sdc").write_text(
            "set clk_name old\nset clk_port_name old_clk\nset clk_period 1000\n"
            "create_clock -name $clk_name -period $clk_period [get_ports $clk_port_name]\n",
            encoding="utf-8",
        )
        source = self.root / "wolf.yaml"
        source.write_text("""schema: wolf.environment/v1
name: native
design:
  package: rtl/ibex
technology:
  package: pdk/asap7
flow:
  package: flow/orfs
workspace:
  root: ./work
constraints:
  clocks:
    - name: core_clock
      port: clk_i
      period_ps: 1050
resources:
  threads: 8
backend:
  orfs:
    make:
      SWAP_ARITH_OPERATORS: ""
      OPENROAD_HIERARCHICAL: 0
""", encoding="utf-8")
        result = self.wolf("env", "create", "native", "--from", str(source))
        self.assertEqual(result.returncode, 0, result.stderr)

    def tearDown(self):
        self.temporary.cleanup()

    def _package(self, kind, name, revision, metadata):
        directory = self.registry / kind
        directory.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": 1, "kind": kind, "name": name, "description": name,
            "source": {"type": "git", "url": "https://example.test/source", "revision": revision},
            "validation": {"required_paths": []}, "metadata": metadata,
        }
        (directory / f"{name}.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        installation = self.state / "packages" / kind / name / revision
        (installation / "source").mkdir(parents=True)
        (installation / "installed.yaml").write_text(yaml.safe_dump({
            "package": f"{kind}/{name}", "revision": revision,
            "source_revision": revision, "content_path": "source", "installed_at": "test",
        }), encoding="utf-8")

    def wolf(self, *args, cwd=None, environment=None):
        return subprocess.run(
            [sys.executable, "-m", "wolf.cli", *args], cwd=cwd or self.root,
            env=environment or self.env, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )

    def test_info_displays_canonical_native_semantics(self):
        result = self.wolf("info", "native")
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in (
            "Format: declarative-v1", "Design package: rtl/ibex", "Design: ibex",
            "Top: ibex_core", "Technology: asap7", "Flow: orfs", "Backend: orfs",
            "core_clock: clk_i @ 1050 ps", "Threads: 8",
            "SWAP_ARITH_OPERATORS: <empty>",
        ):
            self.assertIn(expected, result.stdout)

    def test_native_plan_is_cwd_independent_and_carries_provenance(self):
        first = self.wolf("run", "--environment", "native", "--plan", cwd="/")
        second = self.wolf("run", "--environment", "native", "--plan", cwd="/tmp")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        for expected in (
            "Design: ibex", "Top: ibex_core", "Technology: asap7", "Flow: orfs",
            "Backend: orfs", "Package rtl/ibex: rtl-rev",
            "Clock core_clock: clk_i @ 1050 ps", str(self.root / "work"),
        ):
            self.assertIn(expected, first.stdout)
        manifest_line = next(
            line for line in first.stdout.splitlines() if "Resolved manifest:" in line
        )
        manifest = Path(manifest_line.split("Resolved manifest:", 1)[1].strip())
        resolved = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        self.assertEqual(resolved["backend"]["name"], "orfs")
        generated = manifest.parent
        self.assertIn("set clk_period 1050", (generated / "constraints.sdc").read_text())
        config = (generated / "config.mk").read_text()
        self.assertIn("override DESIGN_NAME := ibex_core", config)
        self.assertIn("/wolf/design/rtl/ibex_core.sv", config)

    def test_active_native_environment_and_package_design_override(self):
        active = dict(self.env, WOLF_ACTIVE_ENV="native")
        result = self.wolf("run", "--plan", cwd="/tmp", environment=active)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Environment: native", result.stdout)

    def test_real_allocation_freezes_manifest_and_associates_generated_files(self):
        result = self.wolf(
            "run", "--environment", "native", "--runtag", "frozen", "--yes",
            "-from", "synth", "-to", "synth",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.root / "work" / "ibex" / "ibex.asap7" / "frozen"
        manifest = run / RUN_MANIFEST_FILENAME
        self.assertTrue(manifest.is_file())
        frozen = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        self.assertEqual(frozen["workspace"]["run_directory"], str(run))
        self.assertEqual(frozen["packages"][0]["id"], "flow/orfs")
        revisions = {item["id"]: item["revision"] for item in frozen["packages"]}
        self.assertEqual(revisions["rtl/ibex"], "rtl-rev")
        self.assertEqual(frozen["execution"]["executor"], "container")
        self.assertEqual(frozen["execution"]["runtime"], "podman")
        self.assertEqual(
            frozen["generated"]["directory"], str(run / "backend" / "orfs")
        )
        self.assertTrue((run / "backend" / "orfs" / "config.mk").is_file())
        self.assertTrue((run / "backend" / "orfs" / "constraints.sdc").is_file())

        original = manifest.read_bytes()
        changed = self.wolf(
            "env", "set", "native", "constraints.clocks.0.period_ps", "1100"
        )
        self.assertEqual(changed.returncode, 0, changed.stderr)
        refused = self.wolf(
            "run", "--environment", "native", "--runtag", "frozen", "--yes",
            "-from", "synth", "-to", "synth",
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("different immutable provenance", refused.stderr)
        self.assertEqual(manifest.read_bytes(), original)

    def test_failed_execution_retains_frozen_manifest(self):
        failing_environment = dict(self.env, WOLF_TEST_FAIL_TARGET="synth")
        result = self.wolf(
            "run", "--environment", "native", "--runtag", "failed", "--yes",
            "-from", "synth", "-to", "synth", environment=failing_environment,
        )
        self.assertEqual(result.returncode, 27, result.stderr)
        run = self.root / "work" / "ibex" / "ibex.asap7" / "failed"
        manifest = run / RUN_MANIFEST_FILENAME
        self.assertTrue(manifest.is_file())
        self.assertEqual(
            yaml.safe_load(manifest.read_text(encoding="utf-8"))["workspace"]["run_directory"],
            str(run),
        )

    def test_plan_does_not_allocate_a_run(self):
        result = self.wolf(
            "run", "--environment", "native", "--runtag", "plan-only", "--plan",
            cwd="/tmp",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.root / "work" / "ibex" / "ibex.asap7" / "plan-only"
        self.assertFalse(run.exists())
        self.assertIn("Resolved manifest:", result.stdout)


if __name__ == "__main__":
    unittest.main()

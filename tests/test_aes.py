import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from wolf.backend.orfs_native import prepare_native_orfs
from wolf.context import ResolvedContext
from wolf.environment import load_environment, resolve_declarative_environment


class AesValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-aes-")
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.registry = self.root / "registry"
        self._env = patch.dict(os.environ, {
            "WOLF_HOME": str(self.state), "WOLF_REGISTRY": str(self.registry),
        }, clear=False)
        self._env.start()
        self._manifest("flow", "orfs", "flow-rev", {"flow": {"name": "orfs", "backend": "orfs"}, "flow_root": "flow"})
        self._manifest("pdk", "asap7", "pdk-rev", {"technology": {"name": "asap7"}})
        self._manifest("rtl", "aes", "aes-rev", {"design": {"name": "aes", "top": "aes_cipher_top", "sources": ["*.v"]}})
        flow = self.state / "packages/flow/orfs/flow-rev/source/flow"
        (flow / "designs/asap7/aes").mkdir(parents=True)
        (flow / "designs/asap7/aes/config.mk").write_text("export PLATFORM = asap7\n", encoding="utf-8")
        (flow / "designs/asap7/aes/constraint.sdc").write_text(
            "set clk_name clk\nset clk_port_name clk\nset clk_period 380\n",
            encoding="utf-8",
        )
        design = self.state / "packages/rtl/aes/aes-rev/source"
        design.mkdir(parents=True, exist_ok=True)
        (design / "aes_cipher_top.v").write_text("module aes_cipher_top(input clk); endmodule\n", encoding="utf-8")
        environment = self.state / "envs/aes"
        environment.mkdir(parents=True)
        self.profile = environment / "wolf.yaml"
        self.profile.write_text("""schema: wolf.environment/v1
name: aes
design:
  package: rtl/aes
technology:
  package: pdk/asap7
flow:
  package: flow/orfs
workspace:
  root: ./work
constraints:
  clocks:
    - name: clk
      port: clk
      period_ps: 380
""", encoding="utf-8")

    def tearDown(self):
        self._env.stop()
        self.temporary.cleanup()

    def _manifest(self, kind, name, revision, metadata):
        directory = self.registry / kind
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.yaml").write_text(yaml.safe_dump({
            "schema_version": 1, "kind": kind, "name": name,
            "description": name,
            "source": {"type": "git", "url": "https://example.invalid/source", "revision": revision},
            "validation": {"required_paths": []}, "metadata": metadata,
        }), encoding="utf-8")
        installation = self.state / "packages" / kind / name / revision
        (installation / "source").mkdir(parents=True, exist_ok=True)
        (installation / "installed.yaml").write_text(yaml.safe_dump({
            "package": f"{kind}/{name}", "revision": revision,
            "source_revision": revision, "content_path": "source", "installed_at": "test",
        }), encoding="utf-8")

    def test_aes_environment_resolves_semantics_and_is_cwd_independent(self):
        profile = load_environment(self.profile)
        before = Path.cwd()
        try:
            os.chdir("/")
            first = resolve_declarative_environment(profile, state_root=self.state, environment_directory=self.profile.parent)
            os.chdir("/tmp")
            second = resolve_declarative_environment(profile, state_root=self.state, environment_directory=self.profile.parent)
        finally:
            os.chdir(before)
        self.assertEqual(first, second)
        self.assertEqual((first.design_name, first.design_top, first.process), ("aes", "aes_cipher_top", "asap7"))
        self.assertEqual(first.clocks[0].period_ps, 380)

    def test_aes_orfs_translation_has_no_ibex_leakage(self):
        context = resolve_declarative_environment(load_environment(self.profile), state_root=self.state, environment_directory=self.profile.parent)
        output = prepare_native_orfs(context, self.state / "packages/flow/orfs/flow-rev/source/flow")
        config = Path(output["ORFS_DESIGN_CONFIG"]).read_text(encoding="utf-8")
        self.assertIn("aes_cipher_top", config)
        self.assertNotRegex(config, r"ibex|core_clock|clk_i")
        self.assertIn("set clk_period 0.38", Path(output["ORFS_SDC_FILE"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

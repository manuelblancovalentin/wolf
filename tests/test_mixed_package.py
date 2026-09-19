import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from wolf.backend.orfs_native import prepare_native_orfs
from wolf.backend.cadence_genus import prepare_genus_inputs, validate_genus
from wolf.environment import load_environment, resolve_declarative_environment


class MixedLanguagePackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wolf-mixed-package-")
        self.root = Path(self.tmp.name)
        self.state = self.root / "state"
        self.registry = self.root / "registry"
        self.env_dir = self.state / "envs" / "mixed"
        self.env_dir.mkdir(parents=True)
        self.patch = patch.dict(os.environ, {"WOLF_HOME": str(self.state), "WOLF_REGISTRY": str(self.registry)}, clear=False)
        self.patch.start()
        self._manifest("pdk", "asap7", "pdk-rev", {"technology": {"name": "asap7"}})
        self._manifest("flow", "orfs", "flow-rev", {"flow": {"name": "orfs", "backend": "orfs"}})
        self.design = self.state / "packages" / "rtl" / "ibex-fabulous-mvp" / "rtl-rev" / "source"
        self._mixed_design()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def _manifest(self, kind, name, revision, metadata):
        directory = self.registry / kind
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.yaml").write_text(yaml.safe_dump({
            "schema_version": 1, "kind": kind, "name": name, "description": name,
            "source": {"type": "git", "url": f"https://example.invalid/{name}", "revision": revision},
            "validation": {"required_paths": []}, "metadata": metadata,
        }), encoding="utf-8")
        install = self.state / "packages" / kind / name / revision
        (install / "source").mkdir(parents=True, exist_ok=True)
        (install / "installed.yaml").write_text(yaml.safe_dump({
            "package": f"{kind}/{name}", "revision": revision, "source_revision": revision,
            "content_path": "source", "installed_at": "test",
        }), encoding="utf-8")

    def _mixed_design(self):
        for relative in ("pkg.vhd", "impl.vhd", "fab.v", "work.sv"):
            path = self.design / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"-- {relative}\n", encoding="utf-8")
        (self.design / "include").mkdir()
        (self.design / "manifests").mkdir()
        files = {
            "vhdl-packages.flist": "pkg.vhd\n", "vhdl-sources.flist": "impl.vhd\n",
            "verilog-sources.flist": "work.sv\n", "fabulous-verilog-sources.flist": "fab.v\n",
            "work-verilog-sources.flist": "work.sv\n", "include-dirs.flist": "include\n",
            "defines.flist": "FABULOUS_TEST\n",
        }
        for name, text in files.items():
            (self.design / "manifests" / name).write_text(text, encoding="utf-8")
        (self.design / "manifest.toml").write_text(
            'schema_version = 1\nname = "ibex-fabulous-mvp-rtl"\ntop = "ESP_ASIC_TOP"\n'
            'vhdl_standard = "93"\nvhdl_packages = "manifests/vhdl-packages.flist"\n'
            'vhdl_sources = "manifests/vhdl-sources.flist"\nverilog_sources = "manifests/verilog-sources.flist"\n'
            'fabulous_library_sources = "manifests/fabulous-verilog-sources.flist"\n'
            'work_library_sources = "manifests/work-verilog-sources.flist"\n'
            'include_dirs = "manifests/include-dirs.flist"\ndefines = "manifests/defines.flist"\n', encoding="utf-8")
        sums = []
        for path in (self.design / "pkg.vhd", self.design / "impl.vhd", self.design / "fab.v", self.design / "work.sv"):
            sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  ./{path.relative_to(self.design)}")
        (self.design / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
        self._manifest("rtl", "ibex-fabulous-mvp", "rtl-rev", {"design": {
            "name": "ibex-fabulous-mvp", "top": "ESP_ASIC_TOP", "checksums": "SHA256SUMS",
            "manifests": {"package": "manifest.toml"},
        }})
        (self.env_dir / "wolf.yaml").write_text(
            "schema: wolf.environment/v1\nname: mixed\ndesign:\n  package: rtl/ibex-fabulous-mvp\n"
            "technology:\n  package: pdk/asap7\nflow:\n  package: flow/orfs\nworkspace:\n  root: ./work\n"
            "constraints:\n  clocks:\n    - name: core_clock\n      port: clk_i\n      period_ps: 1050\n", encoding="utf-8")

    def _context(self):
        profile = load_environment(self.env_dir / "wolf.yaml")
        return resolve_declarative_environment(profile, state_root=self.state, environment_directory=self.env_dir)

    def test_ordered_mixed_inputs_and_provenance_are_retained(self):
        context = self._context()
        self.assertEqual([source.path.name for source in context.sources], ["pkg.vhd", "impl.vhd", "work.sv", "fab.v", "work.sv"])
        self.assertEqual([source.library for source in context.sources], ["work", "work", "work", "FABULOUS_EFPGA", "work"])
        self.assertEqual([source.language for source in context.sources], ["vhdl", "vhdl", "systemverilog", "verilog", "systemverilog"])
        self.assertEqual(context.vhdl_standard, "93")
        self.assertEqual(context.defines, ("FABULOUS_TEST",))
        self.assertTrue(all(source.checksum for source in context.sources))

    def test_orfs_plan_preserves_mixed_inputs_without_changing_verilog_path(self):
        context = self._context()
        flow = self.state / "packages/flow/orfs/flow-rev/source"
        (flow / "designs/asap7/ibex-fabulous-mvp").mkdir(parents=True)
        output = prepare_native_orfs(context, flow)
        resolved = yaml.safe_load(Path(output["WOLF_RESOLVED_MANIFEST"]).read_text())
        ordered = resolved["sources"]["ordered"]
        self.assertEqual([item["library"] for item in ordered], ["work", "work", "work", "FABULOUS_EFPGA", "work"])
        self.assertEqual(resolved["sources"]["vhdl_standard"], "93")
        self.assertEqual(resolved["sources"]["defines"], ["FABULOUS_TEST"])
        self.assertEqual(len(resolved["sources"]["package_checksums"]), 4)
        config = Path(output["ORFS_DESIGN_CONFIG"]).read_text()
        self.assertIn("work.sv", config)
        self.assertNotIn("pkg.vhd", config)
        self.assertIn("VERILOG_DEFINES := FABULOUS_TEST", config)

    def test_genus_preparation_preserves_order_libraries_and_constraints(self):
        context = self._context()
        output = prepare_genus_inputs(context, self.root / "run" / "backend" / "cadence-genus")
        script = output.source_script.read_text(encoding="utf-8")
        self.assertLess(script.index("pkg.vhd"), script.index("impl.vhd"))
        self.assertIn("-library FABULOUS_EFPGA", script)
        self.assertIn("-library work", script)
        self.assertIn("set_db hdl_vhdl_read_version 93", script)
        self.assertIn("FABULOUS_TEST", script)
        self.assertIn("elaborate ESP_ASIC_TOP", output.run_script.read_text(encoding="utf-8"))
        self.assertIn("-period 1.05", output.directory.joinpath("constraints.sdc").read_text(encoding="utf-8"))
        manifest = yaml.safe_load(output.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["sources"][0]["role"], "vhdl_package")
        self.assertEqual(manifest["sources"][3]["library"], "FABULOUS_EFPGA")
        self.assertEqual(manifest["constraints"]["clocks"][0]["period_ps"], 1050)
        self.assertEqual(manifest["packages"][0]["revision"], "flow-rev")

    def test_genus_validation_is_mockable_and_checks_configured_views(self):
        context = self._context()
        checks = validate_genus(context, executable_lookup=lambda name: "/opt/cadence/genus" if name == "genus" else None)
        self.assertTrue(checks[0].available)
        context_values = dict(context.values)
        context_values["LEF_FILES"] = str(self.root / "missing.lef")
        broken = context.__class__(**{**context.__dict__, "values": context_values})
        checks = validate_genus(broken, executable_lookup=lambda name: "/opt/cadence/genus")
        self.assertFalse(next(item for item in checks if item.name == "LEF_FILES").available)


if __name__ == "__main__":
    unittest.main()

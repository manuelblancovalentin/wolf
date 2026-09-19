import hashlib
import os
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import yaml

from wolf.backend.orfs_native import prepare_native_orfs
from wolf.backend.cadence_genus import GenusValidation, prepare_genus_inputs, run_genus, validate_genus
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
            "verilog-sources.flist": "work.sv\nfab.v\n", "fabulous-verilog-sources.flist": "fab.v\n",
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
        self.assertEqual([source.path.name for source in context.sources], ["pkg.vhd", "impl.vhd", "work.sv", "fab.v"])
        self.assertEqual([source.library for source in context.sources], ["work", "work", "work", "FABULOUS_EFPGA"])
        self.assertEqual([source.language for source in context.sources], ["vhdl", "vhdl", "systemverilog", "verilog"])
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
        self.assertEqual([item["library"] for item in ordered], ["work", "work", "work", "FABULOUS_EFPGA"])
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
        self.assertIn("set_db hdl_vhdl_read_version 1993", script)
        self.assertIn("FABULOUS_TEST", script)
        run_script = output.run_script.read_text(encoding="utf-8")
        self.assertLess(run_script.index("source "), run_script.index("elaborate ESP_ASIC_TOP"))
        self.assertLess(run_script.index("elaborate ESP_ASIC_TOP"), run_script.index("read_sdc "))
        self.assertLess(run_script.index("read_sdc "), run_script.index("check_design"))
        self.assertIn("-period 1.05", output.directory.joinpath("constraints.sdc").read_text(encoding="utf-8"))
        manifest = yaml.safe_load(output.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["sources"][0]["role"], "vhdl_package")
        self.assertEqual(manifest["sources"][3]["library"], "FABULOUS_EFPGA")
        self.assertEqual(manifest["constraints"]["clocks"][0]["period_ps"], 1050)
        self.assertEqual(manifest["packages"][0]["revision"], "flow-rev")

    def test_genus_uses_systemverilog_reader_for_verilog_family_inputs(self):
        context = self._context()
        output = prepare_genus_inputs(context, self.root / "reader-modes")
        script = output.source_script.read_text(encoding="utf-8")
        self.assertIn("read_hdl -vhdl", script)
        self.assertGreaterEqual(script.count("read_hdl -sv"), 2)
        self.assertNotIn("-verilog", script)
        manifest = yaml.safe_load(output.manifest.read_text(encoding="utf-8"))
        self.assertEqual([item["language"] for item in manifest["sources"]],
                         ["vhdl", "vhdl", "systemverilog", "verilog"])
        configfsm = self.root / "reader-modes" / "ConfigFSM.v"
        configfsm.write_text("module ConfigFSM; endmodule\n", encoding="utf-8")
        source = replace(context.sources[3], path=configfsm)
        output = prepare_genus_inputs(
            replace(context, sources=context.sources[:3] + (source,)), self.root / "configfsm"
        )
        self.assertIn("read_hdl -sv", output.source_script.read_text(encoding="utf-8"))
        self.assertIn("ConfigFSM.v", output.source_script.read_text(encoding="utf-8"))

    def test_genus_normalizes_supported_vhdl_standards_but_keeps_canonical_input(self):
        context = self._context()
        for value, expected in (("93", "1993"), ("1993", "1993"), ("87", "1987"),
                                ("1987", "1987"), ("08", "2008"), ("2008", "2008")):
            with self.subTest(value=value):
                output = prepare_genus_inputs(
                    replace(context, vhdl_standard=value), self.root / "standards" / value
                )
                script = output.source_script.read_text(encoding="utf-8")
                self.assertIn(f"set_db hdl_vhdl_read_version {expected}", script)
                manifest = yaml.safe_load(output.manifest.read_text(encoding="utf-8"))
                self.assertEqual(manifest["vhdl_standard"], value)

    def test_genus_rejects_unsupported_vhdl_standard_before_preparation(self):
        with self.assertRaisesRegex(ValueError, "unsupported VHDL standard"):
            prepare_genus_inputs(replace(self._context(), vhdl_standard="2019"), self.root / "bad-standard")

    def test_genus_validation_is_mockable_and_checks_configured_views(self):
        context = self._context()
        checks = validate_genus(context, executable_lookup=lambda name: "/opt/cadence/genus" if name == "genus" else None)
        self.assertTrue(checks[0].available)
        context_values = dict(context.values)
        context_values["LEF_FILES"] = str(self.root / "missing.lef")
        broken = context.__class__(**{**context.__dict__, "values": context_values})
        checks = validate_genus(broken, executable_lookup=lambda name: "/opt/cadence/genus")
        self.assertFalse(next(item for item in checks if item.name == "LEF_FILES").available)

    def test_real_package_shape_has_347_unique_entries_and_inventory_order(self):
        manifests = self.design / "manifests"
        vhdl_packages = [f"vhdl_pkg_{index}.vhd" for index in range(71)]
        vhdl_sources = [f"vhdl_src_{index}.vhd" for index in range(158)]
        work = [f"work_{index}.sv" for index in range(88)]
        fabulous = [f"fab_{index}.v" for index in range(30)]
        combined = work[:58] + fabulous + work[58:]
        for name in vhdl_packages + vhdl_sources + work + fabulous:
            (self.design / name).write_text("-- fixture\n", encoding="utf-8")
        lists = {
            "vhdl-packages.flist": vhdl_packages, "vhdl-sources.flist": vhdl_sources,
            "verilog-sources.flist": combined, "fabulous-verilog-sources.flist": fabulous,
            "work-verilog-sources.flist": work,
        }
        for name, values in lists.items():
            (manifests / name).write_text("\n".join(values) + "\n", encoding="utf-8")
        context = self._context()
        self.assertEqual(len(context.sources), 347)
        self.assertEqual(len({source.path for source in context.sources}), 347)
        verilog = context.sources[229:]
        self.assertEqual(sum(source.library == "FABULOUS_EFPGA" for source in verilog), 30)
        self.assertEqual(sum(source.library == "work" for source in verilog), 88)
        self.assertEqual([source.path.name for source in verilog], combined)
        self.assertTrue(all(source.library == "FABULOUS_EFPGA" for source in verilog if source.path.name.startswith("fab_")))
        self.assertTrue(all(source.library == "work" for source in verilog if source.path.name.startswith("work_")))

    def test_genus_run_allocates_exact_directory_freezes_provenance_and_executes_locally(self):
        context = self._context()
        completed = Mock(returncode=0)
        with patch("wolf.backend.cadence_genus.validate_genus", return_value=(GenusValidation("genus", True, "/opt/cadence/genus"),)), \
             patch("wolf.backend.cadence_genus.subprocess.run", return_value=completed) as execute:
            status, run = run_genus(context, clean=True)
        self.assertEqual(status, 0)
        self.assertEqual(run.name, "ibex-fabulous-mvp.1")
        self.assertTrue((run / "wolf.resolved.yaml").is_file())
        self.assertTrue((run / "backend/cadence-genus/sources.tcl").is_file())
        execute.assert_called_once_with(
            ["/opt/cadence/genus", "-files", "run.tcl", "-log", "genus.log"],
            cwd=run / "backend/cadence-genus", check=False,
        )
        frozen = yaml.safe_load((run / "wolf.resolved.yaml").read_text())
        self.assertEqual(frozen["workspace"]["run_directory"], str(run.resolve()))
        self.assertEqual(frozen["execution"]["working_directory"], str((run / "backend/cadence-genus").resolve()))

    def test_genus_validation_fails_before_allocating_run(self):
        context = self._context()
        with patch("wolf.backend.cadence_genus.validate_genus", return_value=(GenusValidation("genus", False, "unavailable"),)), \
             self.assertRaisesRegex(ValueError, "validation failed"):
            run_genus(context, clean=True)
        self.assertFalse((context.workspace_root / context.design_name).exists())

    def test_genus_failure_preserves_run_and_status(self):
        context = self._context()
        with patch("wolf.backend.cadence_genus.validate_genus", return_value=(GenusValidation("genus", True, "/opt/cadence/genus"),)), \
             patch("wolf.backend.cadence_genus.subprocess.run", return_value=Mock(returncode=17)):
            status, run = run_genus(context, clean=True)
        self.assertEqual(status, 17)
        self.assertTrue((run / "wolf.resolved.yaml").is_file())
        self.assertTrue((run / "backend/cadence-genus/genus-inputs.yaml").is_file())

    def test_nested_bundle_resolves_all_347_sources_and_checksums(self):
        nested = self.state / "packages" / "rtl" / "nested" / "nested-rev" / "source" / "packages" / "demo"
        nested.mkdir(parents=True)
        manifests = nested / "manifests"
        manifests.mkdir()
        vhdl_packages = [f"sources/vhdl_pkg_{index}.vhd" for index in range(71)]
        vhdl_sources = [f"sources/vhdl_src_{index}.vhd" for index in range(158)]
        work = [f"sources/work_{index}.sv" for index in range(88)]
        fabulous = [f"sources/fab_{index}.v" for index in range(30)]
        combined = work[:58] + fabulous + work[58:]
        all_sources = vhdl_packages + vhdl_sources + combined
        for relative in all_sources:
            path = nested / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("-- nested fixture\n", encoding="utf-8")
        (nested / "include").mkdir()
        lists = {
            "vhdl-packages.flist": vhdl_packages, "vhdl-sources.flist": vhdl_sources,
            "verilog-sources.flist": combined, "fabulous-verilog-sources.flist": fabulous,
            "work-verilog-sources.flist": work, "include-dirs.flist": ["include"],
            "defines.flist": ["WT_DCACHE"],
        }
        for name, values in lists.items():
            (manifests / name).write_text("\n".join(values) + "\n", encoding="utf-8")
        (nested / "manifest.toml").write_text(
            'schema_version = 1\nname = "demo"\ntop = "ESP_ASIC_TOP"\nvhdl_standard = "93"\n'
            'vhdl_packages = "manifests/vhdl-packages.flist"\nvhdl_sources = "manifests/vhdl-sources.flist"\n'
            'verilog_sources = "manifests/verilog-sources.flist"\n'
            'fabulous_library_sources = "manifests/fabulous-verilog-sources.flist"\n'
            'work_library_sources = "manifests/work-verilog-sources.flist"\n'
            'include_dirs = "manifests/include-dirs.flist"\ndefines = "manifests/defines.flist"\n',
            encoding="utf-8")
        sums = []
        for relative in all_sources:
            path = nested / relative
            sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  ./{relative}")
        (nested / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
        self._manifest("rtl", "nested", "nested-rev", {"design": {
            "name": "nested", "top": "ESP_ASIC_TOP", "checksums": "packages/demo/SHA256SUMS",
            "manifests": {"package": "packages/demo/manifest.toml"},
        }})
        (self.env_dir / "wolf.yaml").write_text(
            "schema: wolf.environment/v1\nname: nested\ndesign:\n  package: rtl/nested\n"
            "technology:\n  package: pdk/asap7\nflow:\n  package: flow/orfs\nworkspace:\n  root: ./work\n"
            "constraints:\n  clocks:\n    - name: core_clock\n      port: clk_i\n      period_ps: 1050\n", encoding="utf-8")
        context = resolve_declarative_environment(
            load_environment(self.env_dir / "wolf.yaml"),
            state_root=self.state, environment_directory=self.env_dir,
        )
        bundle_root = nested
        self.assertEqual(len(context.sources), 347)
        self.assertEqual(len({source.path for source in context.sources}), 347)
        self.assertEqual(sum(source.role == "vhdl_package" for source in context.sources), 71)
        self.assertEqual(sum(source.role == "vhdl_implementation" for source in context.sources), 158)
        self.assertEqual(sum(source.library == "FABULOUS_EFPGA" for source in context.sources), 30)
        self.assertEqual(sum(source.library == "work" for source in context.sources), 317)
        self.assertTrue(all(path.is_relative_to(bundle_root) for path in context.source_files))
        self.assertTrue(all(path.is_relative_to(bundle_root) for path in context.include_directories))
        self.assertEqual(len(context.package_checksums), 347)
        self.assertTrue(all(source.checksum for source in context.sources))


if __name__ == "__main__":
    unittest.main()

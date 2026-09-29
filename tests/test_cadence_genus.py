import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest

import yaml

from wolf.backend.cadence_genus import (
    FLOW_GENUS_ELABORATION, FLOW_GENUS_SYN_GENERIC, FLOW_GENUS_SYN_MAP, FLOW_GENUS_SYN_OPT,
    prepare_genus_inputs,
)
from wolf.context import ResolvedContext, ResolvedSource, ResolvedTechnology
from wolf.paths import builtin_flow_root

TCLSH = shutil.which("tclsh")


class GenusSetDbOverrideTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-overrides-")
        self.root = Path(self.temporary.name)
        source_path = self.root / "top.v"
        source_path.write_text("module top; endmodule\n", encoding="utf-8")
        self.source = ResolvedSource(path=source_path, language="verilog", library="work", order=0)

    def tearDown(self):
        self.temporary.cleanup()

    def _context(self, backend_overrides=None, *, threads=None, env_vars=None) -> ResolvedContext:
        return ResolvedContext(
            state_root=self.root, environment_name="demo", environment_directory=self.root,
            workspace_root=self.root, design_name="demo", process="generic", backend="cadence-flowtool",
            run_tag="demo", run_directory=self.root / "run", values={},
            format="declarative-v1", design_top="top",
            sources=(self.source,), source_files=(self.source.path,),
            backend_overrides=backend_overrides or {}, threads=threads, env_vars=env_vars or {},
        )

    def test_no_overrides_produces_no_overrides_script(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        self.assertIsNone(inputs.overrides_script)
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn('set wolf_overrides_script ""', flow_config)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["genus_overrides"], {})

    def test_set_db_override_is_emitted_and_referenced(self):
        overrides = {"cadence-flowtool": {"genus": {"set_db": {"hdl_max_memory_address_range": 65536}}}}
        inputs = prepare_genus_inputs(self._context(overrides), self.root / "backend" / "cadence-genus")
        self.assertIsNotNone(inputs.overrides_script)
        overrides_text = inputs.overrides_script.read_text(encoding="utf-8")
        self.assertIn("set_db hdl_max_memory_address_range 65536", overrides_text)
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn(str(inputs.overrides_script), flow_config)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["genus_overrides"], {"hdl_max_memory_address_range": 65536})

    def test_string_and_boolean_overrides_are_quoted_correctly(self):
        overrides = {
            "cadence-flowtool": {"genus": {"set_db": {
                "hdl_unconnected_value": "0",
                "hdl_delete_transparent_latch": False,
            }}},
        }
        inputs = prepare_genus_inputs(self._context(overrides), self.root / "backend" / "cadence-genus")
        overrides_text = inputs.overrides_script.read_text(encoding="utf-8")
        self.assertIn('set_db hdl_delete_transparent_latch false', overrides_text)
        self.assertIn('set_db hdl_unconnected_value "0"', overrides_text)

    def test_unknown_cadence_flowtool_override_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported backend.cadence-flowtool override"):
            prepare_genus_inputs(
                self._context({"cadence-flowtool": {"bogus": {}}}),
                self.root / "backend" / "cadence-genus",
            )

    def test_unknown_genus_override_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported backend.cadence-flowtool.genus override"):
            prepare_genus_inputs(
                self._context({"cadence-flowtool": {"genus": {"bogus": {}}}}),
                self.root / "backend" / "cadence-genus",
            )

    def test_non_scalar_set_db_value_is_rejected(self):
        overrides = {"cadence-flowtool": {"genus": {"set_db": {"bad": [1, 2]}}}}
        with self.assertRaisesRegex(ValueError, "must be scalar"):
            prepare_genus_inputs(self._context(overrides), self.root / "backend" / "cadence-genus")


class GenusThreadsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-threads-")
        self.root = Path(self.temporary.name)
        source_path = self.root / "top.v"
        source_path.write_text("module top; endmodule\n", encoding="utf-8")
        self.source = ResolvedSource(path=source_path, language="verilog", library="work", order=0)

    def tearDown(self):
        self.temporary.cleanup()

    def _context(self, *, threads=None, env_vars=None) -> ResolvedContext:
        return ResolvedContext(
            state_root=self.root, environment_name="demo", environment_directory=self.root,
            workspace_root=self.root, design_name="demo", process="generic", backend="cadence-flowtool",
            run_tag="demo", run_directory=self.root / "run", values={},
            format="declarative-v1", design_top="top",
            sources=(self.source,), source_files=(self.source.path,),
            threads=threads, env_vars=env_vars or {},
        )

    def test_no_thread_source_leaves_empty_config(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn('set wolf_max_cpus_per_server ""', flow_config)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertIsNone(manifest["max_cpus_per_server"])

    def test_canonical_threads_set_max_cpus_per_server(self):
        inputs = prepare_genus_inputs(self._context(threads=32), self.root / "backend" / "cadence-genus")
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn("set wolf_max_cpus_per_server 32", flow_config)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["max_cpus_per_server"], 32)

    def test_genus_num_cpus_env_var_is_honored_when_no_canonical_threads(self):
        inputs = prepare_genus_inputs(
            self._context(env_vars={"GENUS_NUM_CPUS": "64"}), self.root / "backend" / "cadence-genus"
        )
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn("set wolf_max_cpus_per_server 64", flow_config)

    def test_canonical_threads_win_over_genus_num_cpus_env_var(self):
        inputs = prepare_genus_inputs(
            self._context(threads=32, env_vars={"GENUS_NUM_CPUS": "64"}),
            self.root / "backend" / "cadence-genus",
        )
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn("set wolf_max_cpus_per_server 32", flow_config)

    def test_non_integer_genus_num_cpus_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "env.GENUS_NUM_CPUS must be an integer"):
            prepare_genus_inputs(
                self._context(env_vars={"GENUS_NUM_CPUS": "not-a-number"}),
                self.root / "backend" / "cadence-genus",
            )


class GenusSynthesisFlowTests(unittest.TestCase):
    """Resolved-value plumbing for the selectable Genus flows.

    The actual step logic and ordering these flows run lives in the shared,
    static flows/cadence-genus/flow.tcl -- exercised end-to-end for real by
    GenusFlowExecutionTests below -- so these tests only check that
    prepare_genus_inputs resolves and records the right values for it.
    """

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-synthesis-")
        self.root = Path(self.temporary.name)
        source_path = self.root / "top.v"
        source_path.write_text("module top; endmodule\n", encoding="utf-8")
        self.source = ResolvedSource(path=source_path, language="verilog", library="work", order=0)

    def tearDown(self):
        self.temporary.cleanup()

    def _context(self, *, flow_name=None, dont_use_cells=(), floorplan_def=None,
                 technology_lefs=()) -> ResolvedContext:
        technology = None
        if dont_use_cells or technology_lefs:
            technology = ResolvedTechnology(
                package="pdk/demo", revision="1", name="demo", root=self.root,
                dont_use_cells=dont_use_cells, technology_lefs=technology_lefs,
            )
        return ResolvedContext(
            state_root=self.root, environment_name="demo", environment_directory=self.root,
            workspace_root=self.root, design_name="demo", process="generic", backend="cadence-flowtool",
            run_tag="demo", run_directory=self.root / "run", values={},
            format="declarative-v1", design_top="top", flow_name=flow_name,
            sources=(self.source,), source_files=(self.source.path,), technology=technology,
            floorplan_def=floorplan_def,
        )

    def test_default_flow_is_elaboration_only(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn(f'set wolf_flow_name "{FLOW_GENUS_ELABORATION}"', flow_config)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["flow"], FLOW_GENUS_ELABORATION)
        self.assertEqual(manifest["synthesis_stages"], [])
        self.assertIsNone(manifest["outputs"]["netlist"])

    def test_unsupported_flow_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported cadence-flowtool flow"):
            prepare_genus_inputs(
                self._context(flow_name="not-a-real-flow"), self.root / "backend" / "cadence-genus"
            )

    def test_syn_generic_flow_is_recorded(self):
        inputs = prepare_genus_inputs(
            self._context(flow_name=FLOW_GENUS_SYN_GENERIC), self.root / "backend" / "cadence-genus"
        )
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["synthesis_stages"], ["syn_generic"])
        self.assertTrue(manifest["outputs"]["netlist"].endswith("demo.generic.v"))

    def test_syn_map_flow_is_recorded(self):
        inputs = prepare_genus_inputs(
            self._context(flow_name=FLOW_GENUS_SYN_MAP), self.root / "backend" / "cadence-genus"
        )
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["synthesis_stages"], ["syn_generic", "syn_map"])
        self.assertTrue(manifest["outputs"]["netlist"].endswith("demo.mapped.v"))

    def test_syn_opt_flow_is_recorded(self):
        inputs = prepare_genus_inputs(
            self._context(flow_name=FLOW_GENUS_SYN_OPT), self.root / "backend" / "cadence-genus"
        )
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["synthesis_stages"], ["syn_generic", "syn_map", "syn_opt"])
        self.assertTrue(manifest["outputs"]["netlist"].endswith("demo.opt.v"))

    def test_dont_use_cells_are_resolved_into_flow_config(self):
        inputs = prepare_genus_inputs(
            self._context(flow_name=FLOW_GENUS_SYN_GENERIC, dont_use_cells=("*_lvt", "AOI*")),
            self.root / "backend" / "cadence-genus",
        )
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn('set wolf_dont_use_cells {"*_lvt" "AOI*"}', flow_config)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["dont_use_cells"], ["*_lvt", "AOI*"])

    def test_no_dont_use_cells_when_technology_declares_none(self):
        inputs = prepare_genus_inputs(
            self._context(flow_name=FLOW_GENUS_SYN_GENERIC), self.root / "backend" / "cadence-genus"
        )
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn("set wolf_dont_use_cells {}", flow_config)

    def test_floorplan_def_without_physical_views_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "floorplan_def requires"):
            prepare_genus_inputs(
                self._context(floorplan_def=self.root / "floor.def"),
                self.root / "backend" / "cadence-genus",
            )

    def test_floorplan_def_with_physical_views_is_resolved(self):
        lef = self.root / "tech.lef"
        lef.write_text("lef\n", encoding="utf-8")
        deff = self.root / "floor.def"
        deff.write_text("def\n", encoding="utf-8")
        inputs = prepare_genus_inputs(
            self._context(floorplan_def=deff, technology_lefs=(lef,)),
            self.root / "backend" / "cadence-genus",
        )
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn(str(deff), flow_config)
        self.assertIn(str(lef), flow_config)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["floorplan_def"], str(deff))


class GenusFlowRootTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-flow-root-")
        self.root = Path(self.temporary.name)
        source_path = self.root / "top.v"
        source_path.write_text("module top; endmodule\n", encoding="utf-8")
        self.source = ResolvedSource(path=source_path, language="verilog", library="work", order=0)

    def tearDown(self):
        self.temporary.cleanup()

    def test_default_run_uses_bundled_flow_scripts(self):
        context = ResolvedContext(
            state_root=self.root, environment_name="demo", environment_directory=self.root,
            workspace_root=self.root, design_name="demo", process="generic", backend="cadence-flowtool",
            run_tag="demo", run_directory=self.root / "run", values={},
            format="declarative-v1", design_top="top",
            sources=(self.source,), source_files=(self.source.path,),
        )
        inputs = prepare_genus_inputs(context, self.root / "backend" / "cadence-genus")
        self.assertEqual(inputs.flow_root, builtin_flow_root("cadence-genus"))
        self.assertTrue((inputs.flow_root / "flow.tcl").is_file())
        self.assertTrue((inputs.flow_root / "presentation.tcl").is_file())

    def test_installed_flow_package_overrides_the_bundled_default(self):
        custom_flow_root = self.root / "my-project-flow"
        custom_flow_root.mkdir()
        (custom_flow_root / "flow.tcl").write_text("# custom\n", encoding="utf-8")
        (custom_flow_root / "presentation.tcl").write_text("# custom\n", encoding="utf-8")
        context = ResolvedContext(
            state_root=self.root, environment_name="demo", environment_directory=self.root,
            workspace_root=self.root, design_name="demo", process="generic", backend="cadence-flowtool",
            run_tag="demo", run_directory=self.root / "run", values={},
            format="declarative-v1", design_top="top",
            sources=(self.source,), source_files=(self.source.path,),
            package_paths={"flow": custom_flow_root},
        )
        inputs = prepare_genus_inputs(context, self.root / "backend" / "cadence-genus")
        self.assertEqual(inputs.flow_root, custom_flow_root)
        run_text = inputs.run_script.read_text(encoding="utf-8")
        self.assertIn(str(custom_flow_root / "flow.tcl"), run_text)


class GenusInteractiveModeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-interactive-")
        self.root = Path(self.temporary.name)
        source_path = self.root / "top.v"
        source_path.write_text("module top; endmodule\n", encoding="utf-8")
        self.source = ResolvedSource(path=source_path, language="verilog", library="work", order=0)

    def tearDown(self):
        self.temporary.cleanup()

    def _context(self) -> ResolvedContext:
        return ResolvedContext(
            state_root=self.root, environment_name="demo", environment_directory=self.root,
            workspace_root=self.root, design_name="demo", process="generic", backend="cadence-flowtool",
            run_tag="demo", run_directory=self.root / "run", values={},
            format="declarative-v1", design_top="top",
            sources=(self.source,), source_files=(self.source.path,),
        )

    def test_batch_mode_is_the_default(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn("set wolf_interactive 0", flow_config)

    def test_interactive_flag_is_recorded(self):
        inputs = prepare_genus_inputs(
            self._context(), self.root / "backend" / "cadence-genus", interactive=True
        )
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn("set wolf_interactive 1", flow_config)
        # Both exits are always present in the shared flow.tcl; wolf_interactive
        # (read from flow-config.tcl) is what gates whether they actually run.
        flow_script = (inputs.flow_root / "flow.tcl").read_text(encoding="utf-8")
        self.assertIn("exit 1", flow_script)
        self.assertIn("exit 0", flow_script)


@unittest.skipUnless(TCLSH, "tclsh is not installed")
class GenusFlowExecutionTests(unittest.TestCase):
    """Runs the real, shipped flow.tcl end-to-end under a stubbed Genus."""

    _STUB_COMMANDS = """
proc set_db {args} { puts "STUB set_db $args" }
proc elaborate {top} { puts "STUB elaborate $top" }
proc read_sdc {f} { puts "STUB read_sdc $f" }
proc check_design {args} { puts "STUB check_design $args" }
proc report_hierarchy {args} { puts "STUB report_hierarchy $args" }
proc report_messages {args} { puts "STUB report_messages $args" }
proc report_area {args} { puts "STUB report_area $args" }
proc write_hdl {args} { puts "STUB write_hdl $args" }
proc get_db {args} { return {} }
proc all_inputs {} { return {} }
proc all_outputs {} { return {} }
proc all_registers {} { return {r1} }
proc sizeof_collection {c} { return [llength $c] }
proc group_path {args} { puts "STUB group_path $args" }
proc syn_generic {} { puts "STUB syn_generic" }
proc syn_map {} { puts "STUB syn_map" }
proc syn_opt {} { puts "STUB syn_opt" }
proc read_physical {args} { puts "STUB read_physical $args" }
proc init_design {} { puts "STUB init_design" }
proc read_def {f} { puts "STUB read_def $f" }
rename source source_orig
proc source {f} {
    if {[string match "*sources.tcl" $f]} {
        puts "STUB source sources.tcl"
    } else {
        uplevel #0 [list source_orig $f]
    }
}
"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-exec-")
        self.root = Path(self.temporary.name)
        source_path = self.root / "top.v"
        source_path.write_text("module top; endmodule\n", encoding="utf-8")
        self.source = ResolvedSource(path=source_path, language="verilog", library="work", order=0)

    def tearDown(self):
        self.temporary.cleanup()

    def _run(self, context) -> str:
        destination = self.root / "backend" / "cadence-genus"
        inputs = prepare_genus_inputs(context, destination)
        stub = self.root / "stub_run.tcl"
        stub.write_text(
            self._STUB_COMMANDS + f'source_orig {{{inputs.run_script}}}\n', encoding="utf-8"
        )
        result = subprocess.run(
            [TCLSH, str(stub)], capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        return result.stdout

    def test_elaboration_flow_runs_expected_commands_in_order(self):
        context = ResolvedContext(
            state_root=self.root, environment_name="demo", environment_directory=self.root,
            workspace_root=self.root, design_name="demo", process="generic", backend="cadence-flowtool",
            run_tag="demo", run_directory=self.root / "run", values={},
            format="declarative-v1", design_top="top",
            sources=(self.source,), source_files=(self.source.path,),
        )
        output = self._run(context)
        for expected in ("STUB elaborate top", "STUB read_sdc", "STUB check_design -unresolved",
                         "STUB report_hierarchy", "STUB report_messages"):
            self.assertIn(expected, output)
        self.assertNotIn("syn_generic", output)
        self.assertNotIn("group_path", output)

    def test_syn_opt_flow_runs_all_stages_dont_use_and_cost_groups(self):
        technology = ResolvedTechnology(
            package="pdk/demo", revision="1", name="demo", root=self.root,
            dont_use_cells=("*_lvt",),
        )
        context = ResolvedContext(
            state_root=self.root, environment_name="demo", environment_directory=self.root,
            workspace_root=self.root, design_name="demo", process="generic", backend="cadence-flowtool",
            run_tag="demo", run_directory=self.root / "run", values={},
            format="declarative-v1", design_top="top", flow_name=FLOW_GENUS_SYN_OPT,
            sources=(self.source,), source_files=(self.source.path,), technology=technology,
        )
        output = self._run(context)
        ordered = (
            "STUB elaborate top", "STUB read_sdc", "STUB set_db {} .dont_use true",
            "STUB group_path -name in2out", "STUB syn_generic", "STUB syn_map", "STUB syn_opt",
            "STUB check_design", "STUB write_hdl > outputs/demo.opt.v",
        )
        indices = [output.index(fragment) for fragment in ordered]
        self.assertEqual(indices, sorted(indices))

    def test_physical_aware_flow_reads_physical_and_inits_design(self):
        lef = self.root / "tech.lef"
        lef.write_text("lef\n", encoding="utf-8")
        technology = ResolvedTechnology(
            package="pdk/demo", revision="1", name="demo", root=self.root, technology_lefs=(lef,),
        )
        context = ResolvedContext(
            state_root=self.root, environment_name="demo", environment_directory=self.root,
            workspace_root=self.root, design_name="demo", process="generic", backend="cadence-flowtool",
            run_tag="demo", run_directory=self.root / "run", values={},
            format="declarative-v1", design_top="top",
            sources=(self.source,), source_files=(self.source.path,), technology=technology,
        )
        output = self._run(context)
        physical_index = output.index("STUB read_physical")
        elaborate_index = output.index("STUB elaborate top")
        init_index = output.index("STUB init_design")
        self.assertLess(physical_index, elaborate_index)
        self.assertLess(elaborate_index, init_index)

    def test_interactive_mode_does_not_call_exit(self):
        context = ResolvedContext(
            state_root=self.root, environment_name="demo", environment_directory=self.root,
            workspace_root=self.root, design_name="demo", process="generic", backend="cadence-flowtool",
            run_tag="demo", run_directory=self.root / "run", values={},
            format="declarative-v1", design_top="top",
            sources=(self.source,), source_files=(self.source.path,),
        )
        destination = self.root / "backend" / "cadence-genus"
        inputs = prepare_genus_inputs(context, destination, interactive=True)
        stub = self.root / "stub_run.tcl"
        stub.write_text(
            self._STUB_COMMANDS
            + f'source_orig {{{inputs.run_script}}}\n'
            + 'puts "STUB reached end of script without exiting"\n',
            encoding="utf-8",
        )
        result = subprocess.run([TCLSH, str(stub)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("STUB reached end of script without exiting", result.stdout)


if __name__ == "__main__":
    unittest.main()

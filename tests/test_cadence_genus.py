from pathlib import Path
import tempfile
import unittest

import yaml

from wolf.backend.cadence_genus import (
    FLOW_GENUS_ELABORATION, FLOW_GENUS_SYN_GENERIC, FLOW_GENUS_SYN_MAP, FLOW_GENUS_SYN_OPT,
    prepare_genus_inputs,
)
from wolf.context import ResolvedContext, ResolvedSource, ResolvedTechnology


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
        run_text = inputs.run_script.read_text(encoding="utf-8")
        self.assertNotIn("overrides.tcl", run_text)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["genus_overrides"], {})

    def test_set_db_override_is_emitted_and_sourced_before_elaborate(self):
        overrides = {"cadence-flowtool": {"genus": {"set_db": {"hdl_max_memory_address_range": 65536}}}}
        inputs = prepare_genus_inputs(self._context(overrides), self.root / "backend" / "cadence-genus")
        self.assertIsNotNone(inputs.overrides_script)
        overrides_text = inputs.overrides_script.read_text(encoding="utf-8")
        self.assertIn("set_db hdl_max_memory_address_range 65536", overrides_text)

        run_text = inputs.run_script.read_text(encoding="utf-8")
        overrides_index = run_text.index("overrides.tcl")
        elaborate_index = run_text.index("elaborate top")
        self.assertLess(overrides_index, elaborate_index)

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


class GenusThreadsAndPresentationTests(unittest.TestCase):
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

    def test_no_thread_source_emits_no_resource_step(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        run_text = inputs.run_script.read_text(encoding="utf-8")
        self.assertNotIn("max_cpus_per_server", run_text)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertIsNone(manifest["max_cpus_per_server"])

    def test_canonical_threads_set_max_cpus_per_server(self):
        inputs = prepare_genus_inputs(self._context(threads=32), self.root / "backend" / "cadence-genus")
        run_text = inputs.run_script.read_text(encoding="utf-8")
        self.assertIn("set_db max_cpus_per_server 32", run_text)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["max_cpus_per_server"], 32)

    def test_genus_num_cpus_env_var_is_honored_when_no_canonical_threads(self):
        inputs = prepare_genus_inputs(
            self._context(env_vars={"GENUS_NUM_CPUS": "64"}), self.root / "backend" / "cadence-genus"
        )
        run_text = inputs.run_script.read_text(encoding="utf-8")
        self.assertIn("set_db max_cpus_per_server 64", run_text)

    def test_canonical_threads_win_over_genus_num_cpus_env_var(self):
        inputs = prepare_genus_inputs(
            self._context(threads=32, env_vars={"GENUS_NUM_CPUS": "64"}),
            self.root / "backend" / "cadence-genus",
        )
        run_text = inputs.run_script.read_text(encoding="utf-8")
        self.assertIn("set_db max_cpus_per_server 32", run_text)
        self.assertNotIn("max_cpus_per_server 64", run_text)

    def test_non_integer_genus_num_cpus_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "env.GENUS_NUM_CPUS must be an integer"):
            prepare_genus_inputs(
                self._context(env_vars={"GENUS_NUM_CPUS": "not-a-number"}),
                self.root / "backend" / "cadence-genus",
            )

    def test_run_script_wraps_each_operation_in_a_step_banner(self):
        inputs = prepare_genus_inputs(self._context(threads=8), self.root / "backend" / "cadence-genus")
        run_text = inputs.run_script.read_text(encoding="utf-8")
        self.assertIn("proc wolf_step", run_text)
        for title in (
            "Configuring resources", "Reading sources", "Elaborating design",
            "Reading constraints", "Checking design", "Writing reports",
        ):
            self.assertIn(f'wolf_step "{title}"', run_text)
        # Steps appear in execution order.
        indices = [run_text.index(f'wolf_step "{title}"') for title in (
            "Configuring resources", "Reading sources", "Elaborating design",
            "Reading constraints", "Checking design", "Writing reports",
        )]
        self.assertEqual(indices, sorted(indices))


class GenusSynthesisFlowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-synthesis-")
        self.root = Path(self.temporary.name)
        source_path = self.root / "top.v"
        source_path.write_text("module top; endmodule\n", encoding="utf-8")
        self.source = ResolvedSource(path=source_path, language="verilog", library="work", order=0)

    def tearDown(self):
        self.temporary.cleanup()

    def _context(self, *, flow_name=None, dont_use_cells=()) -> ResolvedContext:
        technology = None
        if dont_use_cells:
            technology = ResolvedTechnology(
                package="pdk/demo", revision="1", name="demo", root=self.root,
                dont_use_cells=dont_use_cells,
            )
        return ResolvedContext(
            state_root=self.root, environment_name="demo", environment_directory=self.root,
            workspace_root=self.root, design_name="demo", process="generic", backend="cadence-flowtool",
            run_tag="demo", run_directory=self.root / "run", values={},
            format="declarative-v1", design_top="top", flow_name=flow_name,
            sources=(self.source,), source_files=(self.source.path,), technology=technology,
        )

    def test_default_flow_is_elaboration_only(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        run_text = inputs.run_script.read_text(encoding="utf-8")
        self.assertNotIn("syn_generic", run_text)
        self.assertNotIn("group_path", run_text)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["flow"], FLOW_GENUS_ELABORATION)
        self.assertEqual(manifest["synthesis_stages"], [])
        self.assertIsNone(manifest["outputs"]["netlist"])

    def test_unsupported_flow_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported cadence-flowtool flow"):
            prepare_genus_inputs(
                self._context(flow_name="not-a-real-flow"), self.root / "backend" / "cadence-genus"
            )

    def test_syn_generic_flow_groups_paths_and_writes_generic_netlist(self):
        inputs = prepare_genus_inputs(
            self._context(flow_name=FLOW_GENUS_SYN_GENERIC), self.root / "backend" / "cadence-genus"
        )
        run_text = inputs.run_script.read_text(encoding="utf-8")
        self.assertIn("group_path -name in2out -from [all_inputs] -to [all_outputs]", run_text)
        self.assertIn("group_path -name in2reg", run_text)
        self.assertIn("syn_generic", run_text)
        self.assertNotIn("syn_map", run_text)
        self.assertNotIn("syn_opt", run_text)
        # Cost grouping happens after constraints are read and before synthesis.
        constraints_index = run_text.index("Reading constraints")
        grouping_index = run_text.index("Grouping synthesis cost paths")
        synthesis_index = run_text.index('wolf_step "Synthesizing to generic gates"')
        self.assertLess(constraints_index, grouping_index)
        self.assertLess(grouping_index, synthesis_index)
        self.assertIn("write_hdl > outputs/demo.generic.v", run_text)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["synthesis_stages"], ["syn_generic"])
        self.assertTrue(manifest["outputs"]["netlist"].endswith("demo.generic.v"))

    def test_syn_map_flow_runs_generic_then_map(self):
        inputs = prepare_genus_inputs(
            self._context(flow_name=FLOW_GENUS_SYN_MAP), self.root / "backend" / "cadence-genus"
        )
        run_text = inputs.run_script.read_text(encoding="utf-8")
        generic_index = run_text.index('wolf_step "Synthesizing to generic gates"')
        map_index = run_text.index('wolf_step "Mapping to technology library"')
        self.assertLess(generic_index, map_index)
        self.assertIn("write_hdl > outputs/demo.mapped.v", run_text)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["synthesis_stages"], ["syn_generic", "syn_map"])

    def test_syn_opt_flow_runs_all_three_stages_in_order(self):
        inputs = prepare_genus_inputs(
            self._context(flow_name=FLOW_GENUS_SYN_OPT), self.root / "backend" / "cadence-genus"
        )
        run_text = inputs.run_script.read_text(encoding="utf-8")
        indices = [
            run_text.index(f'wolf_step "{title}"') for title in (
                "Synthesizing to generic gates", "Mapping to technology library",
                "Optimizing mapped netlist",
            )
        ]
        self.assertEqual(indices, sorted(indices))
        self.assertIn("write_hdl > outputs/demo.opt.v", run_text)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["synthesis_stages"], ["syn_generic", "syn_map", "syn_opt"])

    def test_dont_use_cells_applied_before_cost_grouping_when_configured(self):
        inputs = prepare_genus_inputs(
            self._context(flow_name=FLOW_GENUS_SYN_GENERIC, dont_use_cells=("*_lvt", "AOI*")),
            self.root / "backend" / "cadence-genus",
        )
        run_text = inputs.run_script.read_text(encoding="utf-8")
        self.assertIn('foreach dont_use_cell {"*_lvt" "AOI*"}', run_text)
        self.assertIn("set_db [get_db base_cells $dont_use_cell] .dont_use true", run_text)
        dont_use_index = run_text.index('wolf_step "Applying dont-use cells"')
        grouping_index = run_text.index("Grouping synthesis cost paths")
        self.assertLess(dont_use_index, grouping_index)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["dont_use_cells"], ["*_lvt", "AOI*"])

    def test_no_dont_use_step_when_technology_declares_none(self):
        inputs = prepare_genus_inputs(
            self._context(flow_name=FLOW_GENUS_SYN_GENERIC), self.root / "backend" / "cadence-genus"
        )
        run_text = inputs.run_script.read_text(encoding="utf-8")
        self.assertNotIn("dont_use_cell", run_text)


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

    def test_batch_mode_always_exits(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        run_text = inputs.run_script.read_text(encoding="utf-8")
        self.assertIn("exit 1", run_text)
        self.assertIn("exit 0", run_text)

    def test_interactive_mode_never_exits(self):
        inputs = prepare_genus_inputs(
            self._context(), self.root / "backend" / "cadence-genus", interactive=True
        )
        run_text = inputs.run_script.read_text(encoding="utf-8")
        self.assertNotIn("exit 1", run_text)
        self.assertNotIn("exit 0", run_text)
        # The error is still reported before Genus drops to its own prompt.
        self.assertIn("WOLF Genus failure", run_text)


if __name__ == "__main__":
    unittest.main()

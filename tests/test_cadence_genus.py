from pathlib import Path
import tempfile
import unittest

import yaml

from wolf.backend.cadence_genus import prepare_genus_inputs
from wolf.context import ResolvedContext, ResolvedSource


class GenusSetDbOverrideTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-overrides-")
        self.root = Path(self.temporary.name)
        source_path = self.root / "top.v"
        source_path.write_text("module top; endmodule\n", encoding="utf-8")
        self.source = ResolvedSource(path=source_path, language="verilog", library="work", order=0)

    def tearDown(self):
        self.temporary.cleanup()

    def _context(self, backend_overrides=None) -> ResolvedContext:
        return ResolvedContext(
            state_root=self.root, environment_name="demo", environment_directory=self.root,
            workspace_root=self.root, design_name="demo", process="generic", backend="cadence-flowtool",
            run_tag="demo", run_directory=self.root / "run", values={},
            format="declarative-v1", design_top="top",
            sources=(self.source,), source_files=(self.source.path,),
            backend_overrides=backend_overrides or {},
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


if __name__ == "__main__":
    unittest.main()

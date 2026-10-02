import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest

import yaml

from wolf.backend.cadence_genus import (
    FLOW_GENUS_SYN_GENERIC, FLOW_GENUS_SYN_MAP, FLOW_GENUS_SYN_OPT,
    prepare_genus_inputs,
)
from wolf.context import ResolvedContext, ResolvedSource, ResolvedTechnology
from wolf.paths import builtin_flow_root

TCLSH = shutil.which("tclsh")

_FLOW_SCRIPT_NAMES = (
    "presentation.tcl", "common_flows.tcl", "common_steps.tcl", "synthesis.tcl",
    "floorplanning.tcl", "cts.tcl", "route.tcl", "postroute.tcl",
)


def _write_fake_flow_root(directory: Path, *, tag: str = "custom") -> None:
    """A minimal but complete fake flow package: all eight files prepare_genus_inputs
    expects to find (and snapshot) in any flow_root, real or custom."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in _FLOW_SCRIPT_NAMES:
        (directory / name).write_text(f"# {tag} {name}\n", encoding="utf-8")
    (directory / "flow.template.yaml").write_text(
        "remarks: fake flow template\n"
        "init_flow_directory: ${WOLF_SCRIPTS_DIR}\n"
        "user_flow_steps:\n  - ${WOLF_FLOW_CONFIG_SCRIPT}\n"
        "flow_current: block\n",
        encoding="utf-8",
    )


def _flowtool_overrides(root: Path) -> dict:
    """A minimal fake pair of institution Flowtool templates for tests.

    WOLF ships no Cadence YAML schema of its own; these stand in for a real
    institution-supplied setup.yaml/flow.yaml template pair, using only the
    placeholder tokens WOLF documents substituting.
    """
    templates = root / "flowtool-templates"
    templates.mkdir(exist_ok=True)
    setup_template = templates / "setup.yaml.template"
    flow_template = templates / "flow.yaml.template"
    setup_template.write_text(
        "design: ${WOLF_DESIGN_NAME}\ntop: ${WOLF_DESIGN_TOP}\n"
        "scripts_dir: ${WOLF_SCRIPTS_DIR}\n", encoding="utf-8",
    )
    flow_template.write_text(
        "setup_yaml: ${WOLF_SETUP_YAML}\nscripts_dir: ${WOLF_SCRIPTS_DIR}\n"
        "reports_dir: ${WOLF_REPORTS_DIR}\noutputs_dir: ${WOLF_OUTPUTS_DIR}\n",
        encoding="utf-8",
    )
    return {"cadence-flowtool": {"flowtool": {
        "setup_template": str(setup_template), "flow_template": str(flow_template),
    }}}


class GenusFixtureTestCase(unittest.TestCase):
    """Shared scaffolding: one source file plus working flowtool templates."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-")
        self.root = Path(self.temporary.name)
        source_path = self.root / "top.v"
        source_path.write_text("module top; endmodule\n", encoding="utf-8")
        self.source = ResolvedSource(path=source_path, language="verilog", library="work", order=0)
        self.flowtool_overrides = _flowtool_overrides(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def _context(self, **overrides) -> ResolvedContext:
        backend_overrides = overrides.pop("backend_overrides", {})
        merged_overrides = {**self.flowtool_overrides, **backend_overrides}
        fields = dict(
            state_root=self.root, environment_name="demo", environment_directory=self.root,
            workspace_root=self.root, design_name="demo", process="generic", backend="cadence-flowtool",
            run_tag="demo", run_directory=self.root / "run", values={},
            format="declarative-v1", design_top="top",
            sources=(self.source,), source_files=(self.source.path,),
            backend_overrides=merged_overrides,
        )
        fields.update(overrides)
        return ResolvedContext(**fields)


class GenusFlowtoolTemplateTests(GenusFixtureTestCase):
    def test_missing_flowtool_override_uses_bundled_default(self):
        """Omitting backend.cadence-flowtool.flowtool entirely is the normal
        case: WOLF's own flow_template is used and no setup.yaml is written."""
        inputs = prepare_genus_inputs(
            self._context(backend_overrides={"cadence-flowtool": {}}),
            self.root / "backend" / "cadence-genus",
        )
        self.assertIsNone(inputs.setup_yaml)
        flow_text = inputs.flow_yaml.read_text(encoding="utf-8")
        self.assertIn("flow_current: block", flow_text)
        self.assertIn(str(inputs.scripts_directory), flow_text)
        self.assertNotIn("${", flow_text)

    def test_missing_one_template_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires .*flow_template|requires .*setup_template"):
            prepare_genus_inputs(
                self._context(backend_overrides={
                    "cadence-flowtool": {"flowtool": {"setup_template": "/nonexistent"}}
                }),
                self.root / "backend" / "cadence-genus",
            )

    def test_nonexistent_template_path_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            prepare_genus_inputs(
                self._context(backend_overrides={"cadence-flowtool": {"flowtool": {
                    "setup_template": str(self.root / "missing-setup.yaml"),
                    "flow_template": str(self.root / "missing-flow.yaml"),
                }}}),
                self.root / "backend" / "cadence-genus",
            )

    def test_unknown_flowtool_override_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported backend.cadence-flowtool.flowtool override"):
            prepare_genus_inputs(
                self._context(backend_overrides={
                    "cadence-flowtool": {"flowtool": {**self.flowtool_overrides["cadence-flowtool"]["flowtool"],
                                                       "bogus": "x"}}
                }),
                self.root / "backend" / "cadence-genus",
            )

    def test_templates_are_rendered_with_resolved_placeholders(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        setup_text = inputs.setup_yaml.read_text(encoding="utf-8")
        flow_text = inputs.flow_yaml.read_text(encoding="utf-8")
        self.assertIn("design: demo", setup_text)
        self.assertIn("top: top", setup_text)
        self.assertIn(str(inputs.scripts_directory), setup_text)
        self.assertIn(str(inputs.setup_yaml), flow_text)
        self.assertIn(str(inputs.scripts_directory), flow_text)
        self.assertNotIn("${", setup_text)
        self.assertNotIn("${", flow_text)


class GenusScriptsSnapshotTests(GenusFixtureTestCase):
    """The scripts.<N>/scripts.latest dedup mechanism for the flow scripts."""

    def test_first_run_creates_scripts_1(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        self.assertEqual(inputs.scripts_directory.name, "scripts.1")
        for name in _FLOW_SCRIPT_NAMES:
            self.assertTrue((inputs.scripts_directory / name).is_file(), name)
        latest = self.root / "backend" / "cadence-genus" / "scripts.latest"
        self.assertTrue(latest.is_symlink())
        self.assertEqual(latest.resolve(), inputs.scripts_directory.resolve())

    def test_unchanged_flow_scripts_reuse_the_same_snapshot(self):
        destination = self.root / "backend" / "cadence-genus"
        first = prepare_genus_inputs(self._context(), destination)
        second = prepare_genus_inputs(self._context(), destination)
        self.assertEqual(first.scripts_directory, second.scripts_directory)
        self.assertEqual(
            len(list(destination.glob("scripts.[0-9]*"))), 1,
            "unchanged flow scripts must not create a second snapshot",
        )

    def test_changed_flow_scripts_create_a_new_snapshot(self):
        destination = self.root / "backend" / "cadence-genus"
        custom_flow_root = self.root / "custom-flow"
        _write_fake_flow_root(custom_flow_root, tag="v1")
        context = self._context(package_paths={"flow": custom_flow_root})
        first = prepare_genus_inputs(context, destination)
        self.assertEqual(first.scripts_directory.name, "scripts.1")

        (custom_flow_root / "synthesis.tcl").write_text("# v2 -- changed\n", encoding="utf-8")
        second = prepare_genus_inputs(context, destination)
        self.assertEqual(second.scripts_directory.name, "scripts.2")
        latest = destination / "scripts.latest"
        self.assertEqual(latest.resolve(), second.scripts_directory.resolve())

    def test_resolved_value_changes_alone_do_not_create_a_new_snapshot(self):
        # scripts.<N> dedups on the flow *scripts* only; unrelated resolved
        # values (like a thread count) must not force a new snapshot.
        destination = self.root / "backend" / "cadence-genus"
        first = prepare_genus_inputs(self._context(threads=8), destination)
        second = prepare_genus_inputs(self._context(threads=32), destination)
        self.assertEqual(first.scripts_directory, second.scripts_directory)


class GenusFlowRootTests(GenusFixtureTestCase):
    def test_default_run_uses_bundled_flow_scripts(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        self.assertEqual(inputs.flow_root, builtin_flow_root("cadence-genus"))

    def test_installed_flow_package_overrides_the_bundled_default(self):
        custom_flow_root = self.root / "my-project-flow"
        _write_fake_flow_root(custom_flow_root)
        inputs = prepare_genus_inputs(
            self._context(package_paths={"flow": custom_flow_root}),
            self.root / "backend" / "cadence-genus",
        )
        self.assertEqual(inputs.flow_root, custom_flow_root)
        self.assertEqual(
            (inputs.scripts_directory / "synthesis.tcl").read_text(encoding="utf-8"),
            "# custom synthesis.tcl\n",
        )


class GenusSetDbOverrideTests(GenusFixtureTestCase):
    def test_no_overrides_produces_no_overrides_script(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        self.assertIsNone(inputs.overrides_script)
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn('set wolf_overrides_script ""', flow_config)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["genus_overrides"], {})

    def test_set_db_override_is_emitted_and_referenced(self):
        overrides = {"genus": {"set_db": {"hdl_max_memory_address_range": 65536}}}
        inputs = prepare_genus_inputs(
            self._context(backend_overrides={"cadence-flowtool": {
                **self.flowtool_overrides["cadence-flowtool"], **overrides,
            }}),
            self.root / "backend" / "cadence-genus",
        )
        self.assertIsNotNone(inputs.overrides_script)
        overrides_text = inputs.overrides_script.read_text(encoding="utf-8")
        self.assertIn("set_db hdl_max_memory_address_range 65536", overrides_text)
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn(str(inputs.overrides_script), flow_config)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["genus_overrides"], {"hdl_max_memory_address_range": 65536})

    def test_string_and_boolean_overrides_are_quoted_correctly(self):
        overrides = {"genus": {"set_db": {
            "hdl_unconnected_value": "0", "hdl_delete_transparent_latch": False,
        }}}
        inputs = prepare_genus_inputs(
            self._context(backend_overrides={"cadence-flowtool": {
                **self.flowtool_overrides["cadence-flowtool"], **overrides,
            }}),
            self.root / "backend" / "cadence-genus",
        )
        overrides_text = inputs.overrides_script.read_text(encoding="utf-8")
        self.assertIn('set_db hdl_delete_transparent_latch false', overrides_text)
        self.assertIn('set_db hdl_unconnected_value "0"', overrides_text)

    def test_unknown_cadence_flowtool_override_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported backend.cadence-flowtool override"):
            prepare_genus_inputs(
                self._context(backend_overrides={"cadence-flowtool": {
                    **self.flowtool_overrides["cadence-flowtool"], "bogus": {},
                }}),
                self.root / "backend" / "cadence-genus",
            )

    def test_unknown_genus_override_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported backend.cadence-flowtool.genus override"):
            prepare_genus_inputs(
                self._context(backend_overrides={"cadence-flowtool": {
                    **self.flowtool_overrides["cadence-flowtool"], "genus": {"bogus": {}},
                }}),
                self.root / "backend" / "cadence-genus",
            )

    def test_non_scalar_set_db_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be scalar"):
            prepare_genus_inputs(
                self._context(backend_overrides={"cadence-flowtool": {
                    **self.flowtool_overrides["cadence-flowtool"], "genus": {"set_db": {"bad": [1, 2]}},
                }}),
                self.root / "backend" / "cadence-genus",
            )


class GenusPostsynNetlistAndInjectOverrideTests(GenusFixtureTestCase):
    def test_no_postsyn_netlists_leaves_empty_config(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn("set wolf_postsyn_netlists {}", flow_config)

    def test_postsyn_netlists_are_resolved_into_flow_config(self):
        inputs = prepare_genus_inputs(
            self._context(backend_overrides={"cadence-flowtool": {
                **self.flowtool_overrides["cadence-flowtool"],
                "postsyn_netlists": ["/tiles/lut4ab.v"],
            }}),
            self.root / "backend" / "cadence-genus",
        )
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn('set wolf_postsyn_netlists {"/tiles/lut4ab.v"}', flow_config)

    def test_non_list_postsyn_netlists_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "postsyn_netlists must be a list"):
            prepare_genus_inputs(
                self._context(backend_overrides={"cadence-flowtool": {
                    **self.flowtool_overrides["cadence-flowtool"], "postsyn_netlists": "not-a-list",
                }}),
                self.root / "backend" / "cadence-genus",
            )

    def test_no_inject_leaves_no_wolf_inject_entries(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertNotIn("set wolf_inject(", flow_config)

    def test_inject_snippets_are_resolved_into_flow_config(self):
        inputs = prepare_genus_inputs(
            self._context(backend_overrides={"cadence-flowtool": {
                **self.flowtool_overrides["cadence-flowtool"],
                "inject": {"init_elaborate": {"post": ["/tmp/after.tcl", "puts {hi}"]}},
            }}),
            self.root / "backend" / "cadence-genus",
        )
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn("set wolf_inject(init_elaborate,post)", flow_config)
        self.assertIn("/tmp/after.tcl", flow_config)
        # The raw file brace-escapes "puts {hi}" to keep it one safe list
        # element (see _tcl_brace_list) -- round-trip through real tclsh to
        # prove it decodes back to the exact original strings, not just
        # check the (deliberately escaped) file text.
        if TCLSH:
            script = (
                flow_config
                + 'foreach s $wolf_inject(init_elaborate,post) { puts "ELEMENT:$s" }\n'
            )
            path = self.root / "roundtrip.tcl"
            path.write_text(script, encoding="utf-8")
            result = subprocess.run([TCLSH, str(path)], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("ELEMENT:/tmp/after.tcl", result.stdout)
            self.assertIn("ELEMENT:puts {hi}", result.stdout)
            # And prove the snippet's own braces survive as real Tcl
            # grouping (not literal backslash-brace text) once evaluated --
            # the actual way wolf_inject consumes it.
            eval_script = (
                flow_config + 'uplevel #0 [lindex $wolf_inject(init_elaborate,post) 1]\n'
            )
            eval_path = self.root / "roundtrip_eval.tcl"
            eval_path.write_text(eval_script, encoding="utf-8")
            eval_result = subprocess.run(
                [TCLSH, str(eval_path)], capture_output=True, text=True, check=False,
            )
            self.assertEqual(eval_result.returncode, 0, msg=eval_result.stdout + eval_result.stderr)
            self.assertEqual(eval_result.stdout.strip(), "hi")

    def test_inject_with_unknown_phase_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must only set pre/post"):
            prepare_genus_inputs(
                self._context(backend_overrides={"cadence-flowtool": {
                    **self.flowtool_overrides["cadence-flowtool"],
                    "inject": {"init_elaborate": {"mid": ["x"]}},
                }}),
                self.root / "backend" / "cadence-genus",
            )


class GenusThreadsTests(GenusFixtureTestCase):
    def test_no_thread_source_leaves_empty_config(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn('set wolf_max_cpus_per_server ""', flow_config)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertIsNone(manifest["max_cpus_per_server"])

    def test_canonical_threads_set_max_cpus_per_server(self):
        inputs = prepare_genus_inputs(
            self._context(threads=32), self.root / "backend" / "cadence-genus"
        )
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


class GenusSynthesisFlowTests(GenusFixtureTestCase):
    """Resolved-value plumbing for the selectable Genus flows.

    elaborate is no longer independently selectable -- it is a step inside
    the syn_generic flow now, matching real Flowtool -from/-to semantics
    (selects by flow name, not by step name within one). The actual step
    logic lives in the shared, static flows/cadence-genus/*.tcl (exercised
    end-to-end for real by GenusFlowTclSyntaxTests below via a crude
    stand-in for Flowtool's own create_flow/create_flow_step, which proves
    Tcl syntax validity and step-body behavior but cannot verify real
    Flowtool checkpoint/-write_db/-owner semantics -- only real Flowtool
    can). These tests only check that prepare_genus_inputs resolves and
    records the right values.
    """

    def _technology(self, *, dont_use_cells=(), technology_lefs=()):
        if not dont_use_cells and not technology_lefs:
            return None
        return ResolvedTechnology(
            package="pdk/demo", revision="1", name="demo", root=self.root,
            dont_use_cells=dont_use_cells, technology_lefs=technology_lefs,
        )

    def test_default_flow_is_the_complete_synthesis_flow(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["flow"], FLOW_GENUS_SYN_OPT)
        self.assertEqual(manifest["synthesis_stages"], ["syn_generic", "syn_map", "syn_opt"])
        self.assertTrue(manifest["outputs"]["netlist"].endswith("demo.opt.v"))

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

    def test_explicit_from_to_is_recorded_and_wins_over_flow_name(self):
        inputs = prepare_genus_inputs(
            self._context(flow_name=FLOW_GENUS_SYN_OPT), self.root / "backend" / "cadence-genus",
            from_stage="syn_map", to_stage="syn_map",
        )
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["from_stage"], "syn_map")
        self.assertEqual(manifest["to_stage"], "syn_map")
        # Only the stage(s) this invocation actually executes, not the
        # cumulative range flow_name would otherwise imply.
        self.assertEqual(manifest["synthesis_stages"], ["syn_map"])

    def test_from_stage_defaults_to_first_stage_when_only_to_stage_given(self):
        inputs = prepare_genus_inputs(
            self._context(), self.root / "backend" / "cadence-genus", to_stage="syn_generic",
        )
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["from_stage"], "syn_generic")
        self.assertEqual(manifest["to_stage"], "syn_generic")

    def test_unsupported_stage_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported stage"):
            prepare_genus_inputs(
                self._context(), self.root / "backend" / "cadence-genus", from_stage="not-a-stage",
            )

    def test_from_stage_after_to_stage_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "comes after"):
            prepare_genus_inputs(
                self._context(), self.root / "backend" / "cadence-genus",
                from_stage="syn_map", to_stage="syn_generic",
            )

    def test_dont_use_cells_are_resolved_into_flow_config(self):
        inputs = prepare_genus_inputs(
            self._context(flow_name=FLOW_GENUS_SYN_GENERIC,
                          technology=self._technology(dont_use_cells=("*_lvt", "AOI*"))),
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
            self._context(floorplan_def=deff, technology=self._technology(technology_lefs=(lef,))),
            self.root / "backend" / "cadence-genus",
        )
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn(str(deff), flow_config)
        self.assertIn(str(lef), flow_config)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["floorplan_def"], str(deff))


@unittest.skipUnless(TCLSH, "tclsh is not installed")
class GenusFlowTclSyntaxTests(GenusFixtureTestCase):
    """Proves the bundled flow scripts are syntactically valid and the real
    create_flow/create_flow_step structure resolves and runs as expected,
    under a crude recursive stand-in for Flowtool's own engine.

    This is NOT a substitute for real Flowtool validation: it does not
    (and cannot) verify real -write_db/-owner/checkpoint-resume semantics,
    or real attribute plumbing (flow_report_directory etc), which only
    Flowtool's own runtime provides. See docs/CADENCE_GENUS.md for the
    actual stub-design validation procedure to run on Kona before trusting
    this against a real design.
    """

    _STUB_COMMANDS = """
proc is_attribute {args} { return 0 }
proc define_attribute {args} {}
proc set_db {args} { puts "STUB set_db $args" }
proc get_db {args} { return {} }
proc elaborate {top} { puts "STUB elaborate $top" }
proc read_sdc {f} { puts "STUB read_sdc $f" }
proc check_design {args} { puts "STUB check_design $args" }
proc report_hierarchy {args} { puts "STUB report_hierarchy $args" }
proc report_messages {args} { puts "STUB report_messages $args" }
proc report_area {args} { puts "STUB report_area $args" }
proc report_timing_summary {args} { puts "STUB report_timing_summary $args" }
proc report_power {args} { puts "STUB report_power $args" }
proc report_obj {args} { return {} }
proc set_metric {args} { puts "STUB set_metric $args" }
proc write_hdl {args} { puts "STUB write_hdl $args" }
proc update_names {args} { puts "STUB update_names $args" }
proc write_design {args} { puts "STUB write_design $args" }
proc delete_obj {args} {}
proc all_inputs {} { return {} }
proc all_outputs {} { return {} }
proc all_registers {} { return {r1} }
proc sizeof_collection {c} { return [llength $c] }
proc group_path {args} { puts "STUB group_path $args" }
proc syn_generic {} { puts "STUB syn_generic" }
proc syn_map {} { puts "STUB syn_map" }
proc syn_opt {} { puts "STUB syn_opt" }
proc read_hdl {args} { puts "STUB read_hdl $args" }
proc read_physical {args} { puts "STUB read_physical $args" }
proc init_design {} { puts "STUB init_design" }
proc read_def {f} { puts "STUB read_def $f" }

# Crude, recursive stand-in for Flowtool's own engine: create_flow and
# create_flow_step both only REGISTER (name -> ordered member list, or
# name -> body); nothing runs until wolf_test_run_flow expands a flow name
# into steps (recursively, since a flow's members may themselves be other
# flows -- e.g. "synthesis" is {syn_generic syn_map syn_opt}, each of
# which is itself a flow) and runs each step's body in order. Good enough
# to prove Tcl syntax validity and real step/flow nesting behavior, not
# real Flowtool checkpointing.
array set FLOW_MEMBERS {}
array set STEP_BODIES {}

proc create_flow {args} {
    global FLOW_MEMBERS
    set name ""
    foreach {a b} $args { if {$a eq "-name"} { set name $b } }
    set FLOW_MEMBERS($name) [lindex $args end]
}

proc create_flow_step {args} {
    global STEP_BODIES
    set name [lindex $args 1]
    set body ""
    foreach a $args { if {[string length $a] > 20} { set body $a } }
    set STEP_BODIES($name) $body
}

proc wolf_test_run_flow {name} {
    global FLOW_MEMBERS STEP_BODIES
    if {[info exists FLOW_MEMBERS($name)]} {
        foreach member $FLOW_MEMBERS($name) { wolf_test_run_flow $member }
    } elseif {[info exists STEP_BODIES($name)]} {
        puts "REGISTER STEP $name"
        uplevel #0 $STEP_BODIES($name)
    } else {
        puts "UNKNOWN STEP OR FLOW: $name"
    }
}
"""

    def _run_flow_tcl(self, flow_config_text: str, *, run: str = "synthesis") -> str:
        root = builtin_flow_root("cadence-genus")
        stub = self.root / "stub_run.tcl"
        stub.write_text(
            self._STUB_COMMANDS + flow_config_text
            + f'source {{{root / "presentation.tcl"}}}\n'
            + f'source {{{root / "common_flows.tcl"}}}\n'
            + f'source {{{root / "common_steps.tcl"}}}\n'
            + f'source {{{root / "synthesis.tcl"}}}\n'
            + f'wolf_test_run_flow {run}\n',
            encoding="utf-8",
        )
        result = subprocess.run([TCLSH, str(stub)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertNotIn("UNKNOWN STEP OR FLOW", result.stdout)
        return result.stdout

    def _base_config(self, **extra) -> str:
        values = {
            "wolf_design_name": "demo", "wolf_design_top": "top",
            "wolf_reports_dir": str(self.root / "reports"), "wolf_outputs_dir": str(self.root / "outputs"),
            "wolf_handoff_dir": str(self.root / "handoff"),
            "wolf_max_cpus_per_server": '""', "wolf_technology_script": '""',
            "wolf_overrides_script": '""', "wolf_sources_script": str(self.root / "sources.tcl"),
            "wolf_constraints_file": str(self.root / "constraints.sdc"),
            "wolf_dont_use_cells": "{}", "wolf_technology_lefs": "{}", "wolf_cell_lefs": "{}",
            "wolf_floorplan_def": '""', "wolf_postsyn_netlists": "{}",
        }
        values.update(extra)
        (self.root / "reports").mkdir(exist_ok=True)
        (self.root / "outputs").mkdir(exist_ok=True)
        (self.root / "sources.tcl").write_text("# stub\n", encoding="utf-8")
        (self.root / "constraints.sdc").write_text("# stub\n", encoding="utf-8")
        lines = []
        for key, value in values.items():
            literal = value if str(value).startswith(("{", '"')) else f'"{value}"'
            lines.append(f"set {key} {literal}")
        lines.append("array set wolf_inject {}")
        return "\n".join(lines) + "\n"

    def test_full_synthesis_flow_registers_and_runs_steps_in_order(self):
        output = self._run_flow_tcl(self._base_config(wolf_dont_use_cells='{"*_lvt"}'))
        ordered = (
            "REGISTER STEP block_start", "REGISTER STEP init_elaborate", "STUB elaborate top",
            "STUB read_sdc", "REGISTER STEP set_dont_use", "STUB set_db {} .dont_use true",
            "REGISTER STEP create_cost_group", "STUB group_path -name in2out",
            "REGISTER STEP run_syn_generic", "STUB syn_generic", "REGISTER STEP block_finish",
            "REGISTER STEP run_syn_map", "STUB syn_map",
            "REGISTER STEP run_syn_opt", "STUB syn_opt",
            "REGISTER STEP genus_to_innovus", "STUB update_names", "STUB write_design",
        )
        indices = [output.index(fragment) for fragment in ordered]
        self.assertEqual(indices, sorted(indices))
        self.assertIn(f"STUB write_hdl > {self.root / 'outputs'}/demo.generic.v", output)
        self.assertIn(f"STUB write_hdl > {self.root / 'outputs'}/demo.mapped.v", output)
        self.assertIn(f"STUB write_hdl > {self.root / 'outputs'}/demo.opt.v", output)

    def test_single_stage_flows_also_resolve_and_run(self):
        self._run_flow_tcl(self._base_config(), run="syn_generic")
        self._run_flow_tcl(self._base_config(), run="syn_map")
        self._run_flow_tcl(self._base_config(), run="syn_opt")

    def test_physical_views_add_read_physical_and_init_design(self):
        lef = self.root / "tech.lef"
        output = self._run_flow_tcl(self._base_config(wolf_technology_lefs=f'{{"{lef}"}}'), run="syn_generic")
        physical_index = output.index("STUB read_physical")
        elaborate_index = output.index("STUB elaborate top")
        init_index = output.index("STUB init_design")
        self.assertLess(physical_index, elaborate_index)
        self.assertLess(elaborate_index, init_index)

    def test_no_physical_views_skips_read_physical_and_init_design(self):
        output = self._run_flow_tcl(self._base_config(), run="syn_generic")
        self.assertNotIn("read_physical", output)
        self.assertNotIn("init_design", output)

    def test_postsyn_netlists_are_read_before_handoff(self):
        output = self._run_flow_tcl(
            self._base_config(wolf_postsyn_netlists='{"/tiles/lut4ab.v"}'), run="syn_opt",
        )
        self.assertIn("STUB read_hdl -sv -library work /tiles/lut4ab.v", output)
        read_index = output.index("STUB read_hdl -sv -library work /tiles/lut4ab.v")
        write_index = output.index("STUB write_design")
        self.assertLess(read_index, write_index)

    def test_inject_hook_runs_at_the_right_point(self):
        marker = self.root / "injected-marker"
        snippet = self.root / "snippet.tcl"
        snippet.write_text(f'puts "INJECTED"\nclose [open {{{marker}}} w]\n', encoding="utf-8")
        config = self._base_config() + (
            f'set wolf_inject(init_elaborate,post) {{{{{snippet}}}}}\n'
        )
        output = self._run_flow_tcl(config, run="syn_generic")
        self.assertIn("INJECTED", output)
        self.assertTrue(marker.is_file())
        elaborate_index = output.index("STUB elaborate top")
        inject_index = output.index("INJECTED")
        dont_use_index = output.index("REGISTER STEP set_dont_use")
        self.assertLess(elaborate_index, inject_index)
        self.assertLess(inject_index, dont_use_index)


if __name__ == "__main__":
    unittest.main()

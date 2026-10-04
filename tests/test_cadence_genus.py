import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest

import yaml

from wolf.backend.cadence_genus import (
    FLOW_GENUS_SYN_GENERIC, FLOW_GENUS_SYN_MAP, FLOW_GENUS_SYN_OPT,
    _period_ns, prepare_genus_inputs,
)
from wolf.context import ResolvedContext, ResolvedSource, ResolvedTechnology, ResolvedTimingCorner
from wolf.paths import builtin_flow_root

TCLSH = shutil.which("tclsh")


class GenusPeriodNsTests(unittest.TestCase):
    """create_clock -period takes ns; period_ps/1000 must not lose magnitude.

    rstrip("0") on an integer-valued result (no decimal point) strips
    significant digits, not just padding -- 10000ps became "10" then "1".
    """

    def test_whole_nanosecond_periods_keep_their_magnitude(self):
        self.assertEqual(_period_ns(10000), "10")
        self.assertEqual(_period_ns(1000), "1")
        self.assertEqual(_period_ns(20000), "20")

    def test_fractional_periods_still_trim_padding_zeros(self):
        self.assertEqual(_period_ns(2500), "2.5")
        self.assertEqual(_period_ns(100), "0.1")

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
        "%TAG ! tag:design.stylus.cadence.com,0.1:\n---\n"
        "design: ${DESIGN_NAME}\nscripts_dir: ${SCRIPTS_DIR}\n", encoding="utf-8",
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
        self.assertIn(str(inputs.scripts_directory), setup_text)
        self.assertIn(str(inputs.setup_yaml), flow_text)
        self.assertIn(str(inputs.scripts_directory), flow_text)
        self.assertNotIn("${", setup_text)
        self.assertNotIn("${", flow_text)


class GenusSetupYamlFragmentTests(GenusFixtureTestCase):
    """setup.yaml composition: the institution's primary setup_template
    concatenated with the PDK's own technology.setup_yaml_fragment, then
    the flat legacy token set substituted -- see
    bin/backends/cadence-flowtool.sh's own _wolf_backend_prepare, which
    this mirrors (cp + tail -n +3 concatenation, then one sed pass)."""

    def _fragment(self, content: str) -> Path:
        path = self.root / "pdk-setup-fragment.yaml"
        path.write_text(
            "%TAG ! tag:design.stylus.cadence.com,0.1:\n---\n" + content, encoding="utf-8",
        )
        return path

    def test_pdk_fragment_is_concatenated_without_its_own_document_header(self):
        fragment = self._fragment("dont_use_cells:\n  - '*D0'\n")
        technology = ResolvedTechnology(
            package="pdk/demo", revision="1", name="demo", root=self.root,
            setup_yaml_fragment=fragment,
        )
        inputs = prepare_genus_inputs(
            self._context(technology=technology), self.root / "backend" / "cadence-genus",
        )
        setup_text = inputs.setup_yaml.read_text(encoding="utf-8")
        self.assertIn("dont_use_cells:\n  - '*D0'", setup_text)
        # Only the primary template's own header survives -- the fragment's
        # was dropped, so there's exactly one document-start marker.
        self.assertEqual(setup_text.count("%TAG"), 1)

    def test_flat_legacy_tokens_are_substituted(self):
        fragment = self._fragment(
            "pdk_dir: ${PDK_DIR}\nmetal_stack: ${METAL_STACK}\ntracks: ${TRACKS}\nvths: ${VTHS}\n"
            "constraints: ${CONSTRAINTS_FILES}\n"
        )
        technology = ResolvedTechnology(
            package="pdk/demo", revision="1", name="demo", root=self.root,
            track="9T", vth="lvt", metal_stack="9lmT2", setup_yaml_fragment=fragment,
        )
        inputs = prepare_genus_inputs(
            self._context(technology=technology), self.root / "backend" / "cadence-genus",
        )
        setup_text = inputs.setup_yaml.read_text(encoding="utf-8")
        self.assertIn(f"pdk_dir: {self.root}", setup_text)
        self.assertIn("metal_stack: 9lmT2", setup_text)
        self.assertIn("tracks: 9T", setup_text)
        self.assertIn("vths: lvt", setup_text)
        self.assertNotIn("${", setup_text)

    def test_technology_generic_is_a_fallback_source_for_unknown_tokens(self):
        fragment = self._fragment("io_lib_dir: ${IO_LIB_DIR}\n")
        technology = ResolvedTechnology(
            package="pdk/demo", revision="1", name="demo", root=self.root,
            setup_yaml_fragment=fragment, generic={"IO_LIB_DIR": "/asic/Library/TSMC/io"},
        )
        inputs = prepare_genus_inputs(
            self._context(technology=technology), self.root / "backend" / "cadence-genus",
        )
        setup_text = inputs.setup_yaml.read_text(encoding="utf-8")
        self.assertIn("io_lib_dir: /asic/Library/TSMC/io", setup_text)

    def test_unresolvable_token_is_flagged_not_left_blank(self):
        fragment = self._fragment("io_lib_dir: ${IO_LIB_DIR}\n")
        technology = ResolvedTechnology(
            package="pdk/demo", revision="1", name="demo", root=self.root,
            setup_yaml_fragment=fragment,
        )
        with self.assertRaisesRegex(ValueError, "undefined token.*IO_LIB_DIR"):
            prepare_genus_inputs(
                self._context(technology=technology), self.root / "backend" / "cadence-genus",
            )


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


class GenusMultiCornerMmmcTests(GenusFixtureTestCase):
    """Named MMMC corners -- technology.tcl's plain set_db library is only
    correct for one corner; several corners emit real MMMC Tcl instead."""

    def _corners(self):
        typical_lib = self.root / "typical.lib"
        worst_lib = self.root / "worst.lib"
        qrc = self.root / "worst.qrc"
        for path in (typical_lib, worst_lib, qrc):
            path.write_text(f"-- {path.name} --\n", encoding="utf-8")
        return (
            ResolvedTimingCorner(name="typical", libraries=(typical_lib,)),
            ResolvedTimingCorner(name="worst_case", libraries=(worst_lib,), qrc_tech_file=qrc),
        )

    def test_single_corner_keeps_the_plain_technology_script(self):
        """mmmc.tcl/technology.tcl are WOLF's own generation for the bundled
        default flow only -- disable the flowtool override fixture so this
        actually exercises that path (see generate_wolf_technology_scripts
        in prepare_genus_inputs)."""
        technology = ResolvedTechnology(package="pdk/demo", revision="1", name="demo", root=self.root)
        inputs = prepare_genus_inputs(
            self._context(technology=technology, backend_overrides={"cadence-flowtool": {}}),
            self.root / "backend" / "cadence-genus",
        )
        self.assertIsNone(inputs.mmmc_script)
        self.assertIsNotNone(inputs.technology_script)
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn('set wolf_mmmc_script ""', flow_config)

    def test_multiple_corners_emit_mmmc_instead_of_plain_library(self):
        technology = ResolvedTechnology(
            package="pdk/demo", revision="1", name="demo", root=self.root,
            timing_corners=self._corners(),
        )
        inputs = prepare_genus_inputs(
            self._context(technology=technology, backend_overrides={"cadence-flowtool": {}}),
            self.root / "backend" / "cadence-genus",
        )
        self.assertIsNone(inputs.technology_script)
        self.assertIsNotNone(inputs.mmmc_script)
        mmmc_text = inputs.mmmc_script.read_text(encoding="utf-8")
        self.assertIn('create_library_set -name "typical"', mmmc_text)
        self.assertIn('create_library_set -name "worst_case"', mmmc_text)
        self.assertIn('create_timing_condition -name "typical" -library_sets {"typical"}', mmmc_text)
        self.assertIn('create_rc_corner -name "worst_case"', mmmc_text)
        self.assertNotIn('create_rc_corner -name "typical"', mmmc_text)
        self.assertIn('create_delay_corner -name "typical" -timing_condition "typical"', mmmc_text)
        self.assertIn(
            'create_delay_corner -name "worst_case" -timing_condition "worst_case" -rc_corner "worst_case"',
            mmmc_text,
        )
        self.assertIn('create_analysis_view -name "typical"', mmmc_text)
        self.assertIn('create_analysis_view -name "worst_case"', mmmc_text)
        self.assertIn('set_analysis_view -setup {"typical" "worst_case"} -hold {"typical" "worst_case"}', mmmc_text)
        flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
        self.assertIn(str(inputs.mmmc_script), flow_config)
        self.assertIn('set wolf_technology_script ""', flow_config)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        corner_names = {entry["name"] for entry in manifest["technology"]["timing_corners"]}
        self.assertEqual(corner_names, {"typical", "worst_case"})


class GenusExtraConstraintsTests(GenusFixtureTestCase):
    """constraints.files/constraints.lines -- raw SDC content WOLF never parses."""

    def test_extra_files_and_lines_are_appended_after_generated_clocks(self):
        extra_sdc = self.root / "extra.sdc"
        extra_sdc.write_text("set_false_path -from [get_ports rst_n]\n", encoding="utf-8")
        from wolf.environment import ClockConstraint
        inputs = prepare_genus_inputs(
            self._context(
                clocks=(ClockConstraint("clk", "clk_i", 10000.0),),
                constraint_files=(extra_sdc,),
                constraint_lines=("set_case_analysis 0 [get_ports test_mode]",),
            ),
            self.root / "backend" / "cadence-genus",
        )
        text = (inputs.directory / "constraints.sdc").read_text(encoding="utf-8")
        clock_index = text.index("create_clock")
        file_index = text.index("set_false_path")
        line_index = text.index("set_case_analysis")
        self.assertLess(clock_index, file_index)
        self.assertLess(file_index, line_index)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["constraints"]["files"], [str(extra_sdc)])
        self.assertEqual(
            manifest["constraints"]["lines"], ["set_case_analysis 0 [get_ports test_mode]"]
        )

    def test_missing_constraint_file_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "constraints.files entry does not exist"):
            prepare_genus_inputs(
                self._context(constraint_files=(self.root / "missing.sdc",)),
                self.root / "backend" / "cadence-genus",
            )


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
proc read_mmmc {f} { puts "STUB read_mmmc $f"; uplevel #0 [list source $f] }
proc create_library_set {args} { puts "STUB create_library_set $args" }
proc create_timing_condition {args} { puts "STUB create_timing_condition $args" }
proc create_rc_corner {args} { puts "STUB create_rc_corner $args" }
proc create_delay_corner {args} { puts "STUB create_delay_corner $args" }
proc create_constraint_mode {args} { puts "STUB create_constraint_mode $args" }
proc create_analysis_view {args} { puts "STUB create_analysis_view $args" }
proc set_analysis_view {args} { puts "STUB set_analysis_view $args" }
proc all_constraint_modes {} { return {} }
proc set_interactive_constraint_modes {args} { puts "STUB set_interactive_constraint_modes $args" }

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
            "wolf_mmmc_script": '""',
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

    def test_mmmc_script_is_read_and_skips_the_plain_read_sdc(self):
        """A real mmmc.tcl (as prepare_genus_inputs would generate for a
        multi-corner technology package) must be real, valid Tcl, and
        init_elaborate must not also call read_sdc once MMMC already
        points its constraint modes at the same file."""
        mmmc = self.root / "mmmc.tcl"
        mmmc.write_text(
            'create_library_set -name "typical" -timing {"/lib/typical.lib"}\n'
            'create_timing_condition -name "typical" -library_sets {"typical"}\n'
            'create_delay_corner -name "typical" -timing_condition "typical"\n'
            'create_constraint_mode -name "typical" -sdc_files {"/x/constraints.sdc"}\n'
            'create_analysis_view -name "typical" -constraint_mode "typical" -delay_corner "typical"\n'
            'set_analysis_view -setup {"typical"} -hold {"typical"}\n',
            encoding="utf-8",
        )
        output = self._run_flow_tcl(
            self._base_config(wolf_mmmc_script=str(mmmc)), run="syn_generic",
        )
        self.assertIn(f"STUB read_mmmc {mmmc}", output)
        self.assertIn("STUB create_library_set -name typical", output)
        self.assertIn('STUB set_analysis_view -setup {"typical"} -hold {"typical"}', output)
        self.assertNotIn("STUB read_sdc", output)
        # Confirmed against a real multi-corner run: group_path otherwise
        # refuses with "SDC command requires a constraint mode specification".
        self.assertIn("STUB set_interactive_constraint_modes", output)
        # Confirmed against a real genus run: MMMC requires init_design
        # before syn_generic even with no physical (LEF) views at all.
        self.assertIn("STUB init_design", output)
        self.assertLess(output.index("STUB init_design"), output.index("STUB syn_generic"))

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

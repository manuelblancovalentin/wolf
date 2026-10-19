import json
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from wolf.backend.cadence_genus import (
    FLOW_GENUS_SYN_GENERIC, FLOW_GENUS_SYN_MAP, FLOW_GENUS_SYN_OPT,
    _RUN_MANIFEST_VOLATILE_KEYS, _extract_step_bodies, _force_freeze_run_manifest, _period_ns,
    _tcl_quote, bundled_flow_digest, flow_descendant_steps, flow_step_digests,
    prepare_genus_inputs,
)
from wolf.backend.cadence_genus_setup import design_setup_path, write_design_setup
from wolf.context import (
    CatalogFileList, CatalogLibrarySet, ResolvedContext, ResolvedSource, ResolvedTechnology,
    ResolvedTimingCorner,
)
from wolf.paths import builtin_flow_root

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

TCLSH = shutil.which("tclsh")
_REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _tcl_string_literal(value: str) -> str:
    """A double-quoted Tcl string literal for `value`, every Tcl-special
    character backslash-escaped -- evaluated by Tcl's own parser at
    runtime, so (unlike cadence_genus._tcl_list_word) this handles
    arbitrary content, including literal braces (a real inject snippet
    like "puts {hi}")."""
    escaped = (
        value.replace("\\", "\\\\").replace('"', '\\"')
        .replace("[", "\\[").replace("$", "\\$")
    )
    return f'"{escaped}"'


def _tcl_flow_config_value(value) -> str:
    """A Tcl *expression* (command substitution, not a static literal)
    that constructs `value` (the same shapes a real rendered setup.yaml
    document holds: str/int/float/bool/list/dict/None) via Tcl's own
    `list`/`dict create` commands -- correct for arbitrary string
    content, including literal braces, since Tcl itself builds the
    value rather than this code pre-rendering brace-quoted text."""
    if value is None:
        return "[list]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _tcl_string_literal(value)
    if isinstance(value, list):
        return "[list " + " ".join(_tcl_flow_config_value(item) for item in value) + "]"
    if isinstance(value, dict):
        words = []
        for key, item in value.items():
            words.append(_tcl_string_literal(str(key)))
            words.append(_tcl_flow_config_value(item))
        return "[dict create " + " ".join(words) + "]"
    raise TypeError(f"unsupported flow config value type: {type(value)!r}")


def _get_flow_config_stub(document: dict) -> str:
    """A real, working `get_flow_config` Tcl proc backed by `document`
    (the same shape a real rendered setup.yaml carries) -- mirrors
    get_flow_config's own confirmed real contract (man 20.15):

        get_flow_config [-help] <key ...>[-quiet]

    `-quiet` is only ever recognized as the *trailing* argument, exactly
    as documented -- not scanned for anywhere in `$args` -- so a call
    site that puts it first (a real regression this session: every
    `-quiet` call site originally read `get_flow_config -quiet <key>`
    instead of `get_flow_config <key> -quiet`, silently returning ""
    for a value that was actually present in setup.yaml, no error, no
    warning) fails the same way the real command does instead of this
    stub masking it by being more lenient."""
    return (
        f"set ::wolf_test_flow_config {_tcl_flow_config_value(document)}\n"
        "proc get_flow_config {args} {\n"
        "    global wolf_test_flow_config\n"
        "    set keys $args\n"
        "    set quiet 0\n"
        '    if {[llength $keys] > 0 && [lindex $keys end] eq "-quiet"} {\n'
        "        set quiet 1\n"
        "        set keys [lrange $keys 0 end-1]\n"
        "    }\n"
        "    set node $wolf_test_flow_config\n"
        "    foreach k $keys {\n"
        "        if {[dict exists $node $k]} {\n"
        "            set node [dict get $node $k]\n"
        "        } else {\n"
        "            if {$quiet} { return \"\" }\n"
        '            error "Flow setup value does not exist: $keys"\n'
        "        }\n"
        "    }\n"
        "    return $node\n"
        "}\n"
    )


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

    def _design_setup(self, data: dict, *, design_name: str = "demo", **context_overrides):
        """Write this design's setup.<design_name>.yaml (cts/tieoffs/
        clock_routing/active_views/genus_set_db/postsyn_netlists/inject --
        the design-level knobs _design_setup in cadence_genus.py reads),
        then return a context with project_root pointed at it. Replaces
        the old backend_overrides={"cadence-flowtool": {...}} fixture
        style now that those keys live in this file instead of
        wolf.yaml."""
        write_design_setup(design_setup_path(self.root, design_name), data)
        return self._context(
            project_root=self.root, design_name=design_name, **context_overrides,
        )


class CadenceGenusPackagingManifestTests(unittest.TestCase):
    """Regression: setup.template.yaml existed in flows/cadence-genus/ for
    several commits but pyproject.toml's data-files stanza never listed it,
    so a regular (non-editable) install silently shipped a flow package
    missing it -- builtin_flow_root's "share/wolf/flows" candidate then had
    no setup.template.yaml, _flowtool_templates resolved setup_template to
    None, and prepare_genus_inputs wrote no setup.yaml at all for that
    install, with flow.yaml's own design_yaml left blank: every
    get_flow_config lookup had nothing to read, regardless of anything
    else being correct. Caught by a real `wolf run` against an installed
    (not editable-source) WOLF; every dev-mode test here resolves
    builtin_flow_root's *source* candidate instead (see paths.py), so none
    of them exercised the installed-package file list.
    """

    def test_every_real_flow_file_is_listed_in_the_install_manifest(self):
        pyproject = tomllib.loads(
            (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        manifest_entries = pyproject["tool"]["setuptools"]["data-files"][
            "share/wolf/flows/cadence-genus"
        ]
        manifest_names = {Path(entry).name for entry in manifest_entries}
        real_names = {
            path.name for path in (_REPO_ROOT / "flows" / "cadence-genus").iterdir()
            if path.is_file()
        }
        self.assertEqual(
            real_names, manifest_names,
            "flows/cadence-genus/ and pyproject.toml's "
            "share/wolf/flows/cadence-genus data-files entry have drifted apart",
        )


class GenusFlowtoolTemplateTests(GenusFixtureTestCase):
    def test_missing_flowtool_override_uses_bundled_default(self):
        """Omitting backend.cadence-flowtool.flowtool entirely is the normal
        case: WOLF's own flow_template AND setup_template are both used --
        get_flow_config design_name is always available, no per-project
        configuration required (see flows/cadence-genus/setup.template.yaml)."""
        inputs = prepare_genus_inputs(
            self._context(backend_overrides={"cadence-flowtool": {}}),
            self.root / "backend" / "cadence-genus",
        )
        self.assertIsNotNone(inputs.setup_yaml)
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["design_name"], "demo")
        flow_text = inputs.flow_yaml.read_text(encoding="utf-8")
        self.assertIn("flow_current: block", flow_text)
        self.assertIn(str(inputs.scripts_directory), flow_text)
        self.assertNotIn("${", flow_text)
        # Regression, hit for real: flow.template.yaml has to set
        # design_yaml to the real setup.yaml path, or get_flow_config has
        # no file bound at all and every lookup fails silently (a -quiet
        # one just returns "") regardless of anything else being
        # correct -- this went unnoticed until a real `wolf run` because
        # nothing here asserted design_yaml was actually set.
        flow_document = yaml.safe_load(flow_text)
        self.assertEqual(flow_document["design_yaml"], str(inputs.setup_yaml))

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

    def test_default_setup_yaml_and_mmmc_tcl_are_generated_together(self):
        """Regression: setup.yaml (get_flow_config) and mmmc.tcl (WOLF's
        own plain-Tcl MMMC generation) used to be mutually exclusive, gated
        on whether a setup_template override was given -- they are now
        complementary and both always present by default for a technology
        with timing corners, since WOLF's own bundled flow steps still read
        flow-config.tcl directly while a project's injected Tcl can use
        get_flow_config instead."""
        corner = ResolvedTimingCorner(name="tt", libraries=(self.root / "tt.lib",))
        (self.root / "tt.lib").write_text("-- tt.lib --\n", encoding="utf-8")
        technology = ResolvedTechnology(
            package="pdk/demo", revision="1", name="demo", root=self.root,
            timing_corners=(corner,),
        )
        inputs = prepare_genus_inputs(
            self._context(backend_overrides={"cadence-flowtool": {}}, technology=technology),
            self.root / "backend" / "cadence-genus",
        )
        self.assertIsNotNone(inputs.setup_yaml)
        self.assertTrue(inputs.setup_yaml.is_file())
        self.assertTrue((self.root / "backend" / "cadence-genus" / "mmmc.tcl").is_file())

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
        document = yaml.safe_load(setup_text)
        self.assertEqual(document["dont_use_cells"], ["*D0"])
        # Concatenation still only ever carries the primary template's
        # document content forward (the fragment's own %TAG header line is
        # dropped before concatenation, so there was only ever one %TAG
        # directive to begin with) -- a single valid document, not two
        # merged/duplicated ones. The directive itself does not survive
        # the yaml.safe_load/safe_dump round trip design_name's always-on
        # injection now requires (see _catalog_document), same as it
        # already didn't for any tracked package with real catalog data
        # before this change.
        self.assertEqual(document["design_name"], "demo")

    def test_catalog_is_injected_with_the_confirmed_get_flow_config_keys(self):
        """library_sets/init_physical_files/std_cell_GDS_files -- the exact
        keys and nesting a real legacy synthesis.tcl's own get_flow_config
        calls expect (get_flow_config library_sets $corner library_files
        $track $vth; get_flow_config init_physical_files lef_files $track
        $vth; get_flow_config std_cell_GDS_files $track $vth), covering
        every track/vth the PDK declares, not just the one this run uses."""
        lib = self.root / "typical.lib"
        lef = self.root / "9t_lvt.lef"
        gds = self.root / "9t_lvt.gds"
        for path in (lib, lef, gds):
            path.write_text(f"-- {path.name} --\n", encoding="utf-8")
        technology = ResolvedTechnology(
            package="pdk/demo", revision="1", name="demo", root=self.root,
            track="9T", vth="lvt",
            catalog_library_sets=(
                CatalogLibrarySet(corner="bc", track="9T", vth="lvt", libraries=(lib,)),
            ),
            catalog_lef_files=(CatalogFileList(track="9T", vth="lvt", files=(lef,)),),
            catalog_gds_files=(CatalogFileList(track="9T", vth="lvt", files=(gds,)),),
        )
        inputs = prepare_genus_inputs(
            self._context(technology=technology), self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(
            document["library_sets"]["bc"]["library_files"]["9T"]["lvt"], [str(lib)],
        )
        self.assertEqual(document["init_physical_files"]["lef_files"]["9T"]["lvt"], [str(lef)])
        self.assertEqual(document["std_cell_GDS_files"]["9T"]["lvt"], [str(gds)])

    def test_design_top_and_technology_package_facts_are_injected(self):
        """design_top, dont_use_cells, technology_lefs, cell_lefs --
        package/environment-resolved facts, not user-edited setup.yaml
        content, injected the same unconditional way design_name/tracks/
        vths already were."""
        lef = self.root / "tech.lef"
        lef.write_text("-- tech.lef --\n", encoding="utf-8")
        technology = ResolvedTechnology(
            package="pdk/demo", revision="1", name="demo", root=self.root,
            dont_use_cells=("*_lvt",), technology_lefs=(lef,), cell_lefs=(lef,),
        )
        inputs = prepare_genus_inputs(
            self._context(technology=technology), self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["design_top"], "top")
        self.assertEqual(document["dont_use_cells"], ["*_lvt"])
        self.assertEqual(document["technology_lefs"], [str(lef)])
        self.assertEqual(document["cell_lefs"], [str(lef)])

    def test_run_paths_are_injected(self):
        inputs = prepare_genus_inputs(
            self._context(), self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["run_directory"], str(inputs.manifest.parent))
        self.assertEqual(document["sources_script"], str(inputs.source_script))
        self.assertIn("reports_dir", document)
        self.assertIn("outputs_dir", document)
        self.assertIn("handoff_dir", document)
        self.assertIn("constraints_file", document)

    def test_design_setup_content_is_merged_in_and_wins_over_the_catalog(self):
        """This design's own setup.<design_name>.yaml (cts/tieoffs/
        active_views/...) lands in the same rendered setup.yaml a
        project's injected Tcl reads via get_flow_config -- and, were a
        key ever to collide with a catalog/run-path key, the design
        setup's own value wins (applied last)."""
        inputs = prepare_genus_inputs(
            self._design_setup({"add_tieoffs_cells": ["TIEHIX1", "TIELOX1"]}),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["add_tieoffs_cells"], ["TIEHIX1", "TIELOX1"])
        self.assertEqual(document["design_name"], "demo")

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
        self.assertNotIn("${", setup_text)
        # Rendered as yaml lists, not bare scalars -- a real flow's own
        # synthesis.tcl loops `foreach trk [get_flow_config tracks] {
        # foreach vth [get_flow_config vths] { ... } }`, so even a single
        # value needs to actually be a list for a run selecting several
        # vths (lvt+rvt, say) to work the same way. Parsed, not a raw
        # substring match -- design_name/tracks/vths/metal_stack are now
        # always injected programmatically too (see _catalog_document),
        # which round-trips the whole document through yaml.safe_dump and
        # so no longer preserves the fragment's own inline flow-style
        # formatting verbatim.
        document = yaml.safe_load(setup_text)
        self.assertEqual(document["tracks"], ["9T"])
        self.assertEqual(document["vths"], ["lvt"])

    def test_multiple_selected_vths_render_as_a_real_list(self):
        """Confirmed real usage: a legacy setup.yaml's own `vths: ${VTHS}`
        token (VTHS a bash array) selects more than one vth so Genus can
        pick cells from whichever fits a given path -- selected_vths
        carries that full selection even though track/vth (the primary,
        used to resolve lef/gds/qrc/timing_corners) stays a single
        name."""
        fragment = self._fragment("tracks: ${TRACKS}\nvths: ${VTHS}\n")
        technology = ResolvedTechnology(
            package="pdk/demo", revision="1", name="demo", root=self.root,
            track="9T", vth="lvt", selected_tracks=("9T",), selected_vths=("lvt", "rvt"),
            setup_yaml_fragment=fragment,
        )
        inputs = prepare_genus_inputs(
            self._context(technology=technology), self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["tracks"], ["9T"])
        self.assertEqual(document["vths"], ["lvt", "rvt"])

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
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertNotIn("overrides_script", document)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["genus_overrides"], {})

    def test_set_db_override_is_emitted_and_referenced(self):
        inputs = prepare_genus_inputs(
            self._design_setup({"genus_set_db": {"hdl_max_memory_address_range": 65536}}),
            self.root / "backend" / "cadence-genus",
        )
        self.assertIsNotNone(inputs.overrides_script)
        overrides_text = inputs.overrides_script.read_text(encoding="utf-8")
        self.assertIn("set_db hdl_max_memory_address_range 65536", overrides_text)
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["overrides_script"], str(inputs.overrides_script))
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["genus_overrides"], {"hdl_max_memory_address_range": 65536})

    def test_string_and_boolean_overrides_are_quoted_correctly(self):
        inputs = prepare_genus_inputs(
            self._design_setup({"genus_set_db": {
                "hdl_unconnected_value": "0", "hdl_delete_transparent_latch": False,
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

    def test_non_scalar_set_db_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be scalar"):
            prepare_genus_inputs(
                self._design_setup({"genus_set_db": {"bad": [1, 2]}}),
                self.root / "backend" / "cadence-genus",
            )

    def test_a_commented_out_genus_set_db_block_is_not_an_override(self):
        """Regression: `genus_set_db:` left in setup.yaml with its
        mapping entries commented out parses as null, not an absent
        key -- must not raise."""
        inputs = prepare_genus_inputs(
            self._design_setup({"genus_set_db": None}),
            self.root / "backend" / "cadence-genus",
        )
        self.assertIsNone(inputs.overrides_script)


class GenusPostsynNetlistAndInjectOverrideTests(GenusFixtureTestCase):
    def test_no_postsyn_netlists_leaves_empty_config(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertNotIn("postsyn_netlists", document)

    def test_postsyn_netlists_are_resolved_into_flow_config(self):
        inputs = prepare_genus_inputs(
            self._design_setup({"postsyn_netlists": ["/tiles/lut4ab.v"]}),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["postsyn_netlists"], ["/tiles/lut4ab.v"])

    def test_non_list_postsyn_netlists_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "postsyn_netlists must be a list"):
            prepare_genus_inputs(
                self._design_setup({"postsyn_netlists": "not-a-list"}),
                self.root / "backend" / "cadence-genus",
            )

    def test_a_commented_out_postsyn_netlists_list_is_not_an_override(self):
        inputs = prepare_genus_inputs(
            self._design_setup({"postsyn_netlists": None}),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertIsNone(document["postsyn_netlists"])

    def test_a_commented_out_inject_block_is_not_an_override(self):
        inputs = prepare_genus_inputs(
            self._design_setup({"inject": None}),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertIsNone(document["inject"])

    def test_no_inject_leaves_no_inject_key(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertNotIn("inject", document)

    def test_inject_snippets_are_resolved_into_flow_config(self):
        inputs = prepare_genus_inputs(
            self._design_setup({
                "inject": {"elaborate": {"post": ["/tmp/after.tcl", "puts {hi}"]}},
            }),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(
            document["inject"], {"elaborate": {"post": ["/tmp/after.tcl", "puts {hi}"]}},
        )
        # Round-trip through presentation.tcl's own wolf_inject_for_step,
        # backed by a get_flow_config stub seeded from this exact setup.yaml
        # content -- proves the snippet strings (including one containing
        # literal braces, "puts {hi}") survive both get_flow_config's own
        # lookup and wolf_inject's eval, not just the YAML round-trip above.
        if TCLSH:
            presentation = builtin_flow_root("cadence-genus") / "presentation.tcl"
            marker = self.root / "after.tcl"
            marker.write_text('puts "FILE_SNIPPET_RAN"\n', encoding="utf-8")
            script = (
                _get_flow_config_stub({"inject": {"elaborate": {"post": [str(marker), "puts {hi}"]}}})
                + 'proc create_flow_step {args} {}\n'
                + f'source {{{presentation}}}\n'
                + 'wolf_inject_for_step elaborate post\n'
            )
            path = self.root / "roundtrip.tcl"
            path.write_text(script, encoding="utf-8")
            result = subprocess.run([TCLSH, str(path)], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("FILE_SNIPPET_RAN", result.stdout)
            self.assertIn("hi", result.stdout)

    def test_inject_with_unknown_phase_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must only set pre/post"):
            prepare_genus_inputs(
                self._design_setup({"inject": {"init_elaborate": {"mid": ["x"]}}}),
                self.root / "backend" / "cadence-genus",
            )


class GenusStepStatusFileTests(GenusFixtureTestCase):
    """prepare_genus_inputs sets wolf_run_directory (presentation.tcl's
    create_flow_step wrapper needs it to know where to write
    wolf.step-status) and truncates wolf.step-status fresh on every
    call, so a step name several stages share is never ambiguous
    within one invocation's worth of live events."""

    def test_wolf_run_directory_is_set_to_the_run_directory(self):
        destination = self.root / "backend" / "cadence-genus"
        inputs = prepare_genus_inputs(self._context(), destination)
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["run_directory"], str(destination.resolve()))

    def test_wolf_step_status_is_created_empty(self):
        destination = self.root / "backend" / "cadence-genus"
        prepare_genus_inputs(self._context(), destination)
        self.assertEqual((destination / "wolf.step-status").read_text(encoding="utf-8"), "")

    def test_a_pre_existing_wolf_step_status_is_truncated_on_the_next_call(self):
        """Regression: a stale event from an earlier invocation (e.g.
        block_start, shared by several stages) must not leak into a
        later invocation's own live view."""
        destination = self.root / "backend" / "cadence-genus"
        destination.mkdir(parents=True)
        (destination / "wolf.step-status").write_text("block_start|success|1\n", encoding="utf-8")
        prepare_genus_inputs(self._context(), destination)
        self.assertEqual((destination / "wolf.step-status").read_text(encoding="utf-8"), "")


class GenusThreadsTests(GenusFixtureTestCase):
    def test_no_thread_source_leaves_empty_config(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertNotIn("max_cpus_per_server", document)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertIsNone(manifest["max_cpus_per_server"])

    def test_canonical_threads_set_max_cpus_per_server(self):
        inputs = prepare_genus_inputs(
            self._context(threads=32), self.root / "backend" / "cadence-genus"
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["max_cpus_per_server"], 32)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["max_cpus_per_server"], 32)

    def test_genus_num_cpus_env_var_is_honored_when_no_canonical_threads(self):
        inputs = prepare_genus_inputs(
            self._context(env_vars={"GENUS_NUM_CPUS": "64"}), self.root / "backend" / "cadence-genus"
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["max_cpus_per_server"], 64)

    def test_canonical_threads_win_over_genus_num_cpus_env_var(self):
        inputs = prepare_genus_inputs(
            self._context(threads=32, env_vars={"GENUS_NUM_CPUS": "64"}),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["max_cpus_per_server"], 32)

    def test_non_integer_genus_num_cpus_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "env.GENUS_NUM_CPUS must be an integer"):
            prepare_genus_inputs(
                self._context(env_vars={"GENUS_NUM_CPUS": "not-a-number"}),
                self.root / "backend" / "cadence-genus",
            )

    def test_innovus_init_step_also_applies_the_resolved_thread_count(self):
        """Regression: resources.threads was only ever wired to Genus's own
        set_db max_cpus_per_server (synthesis.tcl's init_genus) -- Innovus
        ran single-threaded through place/CTS/route with no equivalent,
        silently, on a design large enough for that to matter. init_innovus
        re-runs at the start of every implementation stage (a separate
        Innovus invocation each time), so it must re-apply the same
        max_cpus_per_server get_flow_config already resolves for Genus,
        via Innovus's own set_multi_cpu_usage (it has no equivalent
        set_db attribute)."""
        step = builtin_flow_root("cadence-genus") / "floorplanning.tcl"
        text = step.read_text(encoding="utf-8")
        bodies = _extract_step_bodies(text)
        self.assertIn("init_innovus", bodies)
        body = bodies["init_innovus"]
        self.assertIn("get_flow_config max_cpus_per_server -quiet", body)
        self.assertIn("set_multi_cpu_usage -local_cpu $wolf_max_cpus_per_server", body)
        self.assertIn('if {$wolf_max_cpus_per_server ne ""}', body)

    def test_init_innovus_sets_ocv_analysis_before_placement(self):
        """Regression: CHKCTS-51 ("The timing analysis type is not set to
        OCV") fires on a real check_design -type cts run even though
        timing_analysis_type's own documented default is already "ocv" --
        a fresh Innovus session restored from the Genus handoff needs it
        set explicitly. Required before placement (Cadence's own
        recommendation) and by CCOpt's clock-source-latency update during
        CTS, so init_innovus (re-run at the start of every implementation
        stage) sets it unconditionally, not behind a setup.yaml key."""
        step = builtin_flow_root("cadence-genus") / "floorplanning.tcl"
        text = step.read_text(encoding="utf-8")
        bodies = _extract_step_bodies(text)
        body = bodies["init_innovus"]
        self.assertIn("set_db timing_analysis_type ocv", body)


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

    def test_unrecognized_flow_name_falls_back_to_the_complete_synthesis_flow(self):
        """flow.name is only ever a recognized shorthand for one of the
        three genus-syn-* values; anything else (the bundled flow's own
        literal "default", a real installed flow package's own manifest
        name, a typo) is just a label and must not block the sensible
        default range -- confirmed real regression: every environment
        `wolf env menu` ever wrote had flow.name literally "default",
        which broke a bare `wolf run`/`wolf run --plan` entirely."""
        for flow_name in ("not-a-real-flow", "default", "orfs"):
            with self.subTest(flow_name=flow_name):
                inputs = prepare_genus_inputs(
                    self._context(flow_name=flow_name), self.root / "backend" / "cadence-genus"
                )
                manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
                self.assertEqual(manifest["synthesis_stages"], ["syn_generic", "syn_map", "syn_opt"])

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
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["dont_use_cells"], ["*_lvt", "AOI*"])
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["dont_use_cells"], ["*_lvt", "AOI*"])

    def test_no_dont_use_cells_when_technology_declares_none(self):
        inputs = prepare_genus_inputs(
            self._context(flow_name=FLOW_GENUS_SYN_GENERIC), self.root / "backend" / "cadence-genus"
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertNotIn("dont_use_cells", document)

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
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["floorplan_def"], str(deff))
        self.assertEqual(document["technology_lefs"], [str(lef)])
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
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertNotIn("mmmc_script", document)
        self.assertEqual(document["technology_script"], str(inputs.technology_script))

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
        self.assertIn('create_timing_condition -name "typical" -library_sets {typical}', mmmc_text)
        self.assertIn('create_rc_corner -name "worst_case"', mmmc_text)
        self.assertNotIn('create_rc_corner -name "typical"', mmmc_text)
        self.assertIn('create_delay_corner -name "typical" -timing_condition "typical"', mmmc_text)
        self.assertIn(
            'create_delay_corner -name "worst_case" -timing_condition "worst_case" -rc_corner "worst_case"',
            mmmc_text,
        )
        self.assertIn('create_analysis_view -name "typical"', mmmc_text)
        self.assertIn('create_analysis_view -name "worst_case"', mmmc_text)
        self.assertIn(
            "set_analysis_view -setup {typical worst_case} -hold {typical worst_case}", mmmc_text,
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["mmmc_script"], str(inputs.mmmc_script))
        self.assertNotIn("technology_script", document)
        manifest = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
        corner_names = {entry["name"] for entry in manifest["technology"]["timing_corners"]}
        self.assertEqual(corner_names, {"typical", "worst_case"})


class GenusActiveViewsTests(GenusFixtureTestCase):
    """backend.cadence-flowtool.active_views.{setup,hold} -- narrows which
    declared analysis views genus_turn_on_analysis_views re-activates on
    the Innovus side of every implementation stage, instead of always
    re-activating every one (heavy for early place/CTS on a design with
    several corners, confirmed a real need: a project activating only its
    slowest/fastest corner through place/CTS, every corner again at
    route/signoff)."""

    def _corners(self):
        typical_lib = self.root / "typical.lib"
        worst_lib = self.root / "worst.lib"
        for path in (typical_lib, worst_lib):
            path.write_text(f"-- {path.name} --\n", encoding="utf-8")
        return (
            ResolvedTimingCorner(name="typical", libraries=(typical_lib,)),
            ResolvedTimingCorner(name="worst_case", libraries=(worst_lib,)),
        )

    def test_default_is_empty_meaning_every_declared_view(self):
        inputs = prepare_genus_inputs(
            self._context(technology=ResolvedTechnology(
                package="pdk/demo", revision="1", name="demo", root=self.root,
                timing_corners=self._corners(),
            )),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertNotIn("active_views", document)

    def test_setup_and_hold_views_are_resolved_into_flow_config(self):
        inputs = prepare_genus_inputs(
            self._design_setup(
                {"active_views": {"setup": ["worst_case"], "hold": ["typical"]}},
                technology=ResolvedTechnology(
                    package="pdk/demo", revision="1", name="demo", root=self.root,
                    timing_corners=self._corners(),
                ),
            ),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["active_views"], {"setup": ["worst_case"], "hold": ["typical"]})

    def test_a_view_name_not_declared_by_the_technology_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "names undeclared view"):
            prepare_genus_inputs(
                self._design_setup(
                    {"active_views": {"setup": ["nope"]}},
                    technology=ResolvedTechnology(
                        package="pdk/demo", revision="1", name="demo", root=self.root,
                        timing_corners=self._corners(),
                    ),
                ),
                self.root / "backend" / "cadence-genus",
            )

    def test_unsupported_active_views_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported active_views key"):
            prepare_genus_inputs(
                self._design_setup({"active_views": {"bogus": []}}),
                self.root / "backend" / "cadence-genus",
            )

    def test_a_commented_out_active_views_block_is_not_an_override(self):
        inputs = prepare_genus_inputs(
            self._design_setup({"active_views": None}),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertIsNone(document["active_views"])

    def test_a_commented_out_setup_or_hold_sub_list_is_not_an_override(self):
        inputs = prepare_genus_inputs(
            self._design_setup(
                {"active_views": {"setup": None, "hold": ["typical"]}},
                technology=ResolvedTechnology(
                    package="pdk/demo", revision="1", name="demo", root=self.root,
                    timing_corners=self._corners(),
                ),
            ),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["active_views"], {"setup": None, "hold": ["typical"]})

    def test_init_innovus_activates_views_every_stage_not_only_floorplan(self):
        """Regression, hit for real: the view-activation logic used to
        live only in genus_turn_on_analysis_views, a step that only ever
        appears in the floorplan flow's own step list -- prects/cts/
        postcts/route/postroute never re-applied it at all, even though
        each is a separate Innovus invocation restored from a checkpoint
        (same persistence-across-stages concern as thread count and
        set_cts_config). Moved into init_innovus, which already re-runs
        at the start of every implementation stage."""
        step = builtin_flow_root("cadence-genus") / "floorplanning.tcl"
        bodies = _extract_step_bodies(step.read_text(encoding="utf-8"))
        body = bodies["init_innovus"]
        self.assertIn("set_analysis_view -setup $wolf_setup_views -hold $wolf_hold_views", body)
        self.assertIn("get_flow_config active_views setup -quiet", body)
        self.assertIn("get_flow_config active_views hold -quiet", body)
        self.assertIn("if {[llength $wolf_active_setup_views]}", body)
        self.assertIn("if {[llength $wolf_active_hold_views]}", body)
        # genus_turn_on_analysis_views itself is kept as a named,
        # injectable extension point (so any existing wolf_inject hook
        # for it still fires), but the real work no longer lives there.
        self.assertNotIn("set_analysis_view", bodies["genus_turn_on_analysis_views"])


class GenusPowerGroundNetsTests(GenusFixtureTestCase):
    """constraints.power_nets/ground_nets -- a design with no power intent
    (CPF/UPF) file has no VDD/VSS nets at all once handed off to Innovus,
    and connect_global_net/route_special/add_stripes all fail with "net
    does not exist" until something creates them. Setting Genus's own
    init_power_nets/init_ground_nets before init_design (synthesis.tcl's
    run_init_design) is the real fix -- it carries through
    write_design -innovus's own handoff init script automatically,
    rather than needing a manual create_net workaround on the Innovus
    side."""

    def test_default_is_no_nets(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertNotIn("power_nets", document)
        self.assertNotIn("ground_nets", document)

    def test_resolved_nets_are_written_into_flow_config(self):
        inputs = prepare_genus_inputs(
            self._context(power_nets=("VDD", "VDD1"), ground_nets=("VSS",)),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["power_nets"], ["VDD", "VDD1"])
        self.assertEqual(document["ground_nets"], ["VSS"])

    def test_get_flow_config_exposes_power_and_ground_nets(self):
        inputs = prepare_genus_inputs(
            self._context(power_nets=("VDD",), ground_nets=("VSS",)),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["power_nets"], ["VDD"])
        self.assertEqual(document["ground_nets"], ["VSS"])

    def test_default_has_no_power_or_ground_net_keys_in_setup_yaml(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertNotIn("power_nets", document)
        self.assertNotIn("ground_nets", document)

    def test_run_init_design_applies_them_before_init_design(self):
        step = builtin_flow_root("cadence-genus") / "synthesis.tcl"
        bodies = _extract_step_bodies(step.read_text(encoding="utf-8"))
        body = bodies["run_init_design"]
        self.assertIn("get_flow_config power_nets -quiet", body)
        self.assertIn("get_flow_config ground_nets -quiet", body)
        self.assertIn("set_db init_power_nets $wolf_power_nets", body)
        self.assertIn("set_db init_ground_nets $wolf_ground_nets", body)
        # The real init_design call is the LAST occurrence of the word in
        # the step body -- an earlier one is inside a comment explaining
        # why init_design runs at all.
        self.assertLess(body.index("set_db init_power_nets"), body.rindex("init_design"))


class GenusFloorplanDefExportTests(GenusFixtureTestCase):
    """export_floorplan_def -- a durable, reloadable DEF snapshot of every
    floorplan run, independent of create_fplan's own injected Tcl, so a
    later run (e.g. after re-running synthesis, with no Innovus DB left to
    restore from) can reload it via the existing constraints.floorplan_def
    / load_floorplan read_def path instead of re-deriving the floorplan."""

    def test_step_is_part_of_the_floorplan_flow_after_commit_power_intent(self):
        flows_text = (builtin_flow_root("cadence-genus") / "common_flows.tcl").read_text(
            encoding="utf-8",
        )
        self.assertIn(
            "commit_power_intent export_floorplan_def block_finish", flows_text,
        )

    def test_step_writes_a_def_named_after_the_design_into_outputs(self):
        step = builtin_flow_root("cadence-genus") / "floorplanning.tcl"
        bodies = _extract_step_bodies(step.read_text(encoding="utf-8"))
        body = bodies["export_floorplan_def"]
        self.assertIn("set wolf_fp_def_out", body)
        self.assertIn("[get_flow_config outputs_dir]", body)
        self.assertIn("[get_flow_config design_name].floorplan.def", body)
        self.assertIn("write_def $wolf_fp_def_out", body)


class GenusCtsCellTests(GenusFixtureTestCase):
    """backend.cadence-flowtool.cts -- CCOpt buffer/inverter/clock-gating
    cell selection and timing targets, resolved into real Innovus
    cts_buffer_cells/cts_inverter_cells/cts_clock_gating_cells/
    cts_target_skew/cts_target_max_transition_time/cts_max_fanout
    attributes (set_cts_config, shared by prects and cts)."""

    def test_default_is_empty(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        for key in (
            "cts_buffer_cells", "cts_inverter_cells", "cts_clock_gating_cells",
            "cts_target_skew", "cts_max_fanout",
        ):
            self.assertNotIn(key, document)

    def test_resolved_cells_and_targets_are_written_into_flow_config(self):
        inputs = prepare_genus_inputs(
            self._design_setup({
                "cts_buffer_cells": ["BUFX*"], "cts_inverter_cells": ["INVX*"],
                "cts_clock_gating_cells": ["CKGX*"], "cts_target_skew": 0.05,
                "cts_target_max_transition_time": 0.2, "cts_max_fanout": 16,
            }),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["cts_buffer_cells"], ["BUFX*"])
        self.assertEqual(document["cts_inverter_cells"], ["INVX*"])
        self.assertEqual(document["cts_clock_gating_cells"], ["CKGX*"])
        self.assertEqual(document["cts_target_skew"], 0.05)
        self.assertEqual(document["cts_target_max_transition_time"], 0.2)
        self.assertEqual(document["cts_max_fanout"], 16)

    def test_top_and_leaf_cell_variants_are_written_into_flow_config(self):
        inputs = prepare_genus_inputs(
            self._design_setup({
                "cts_buffer_cells_top": ["BUFTOPX*"], "cts_buffer_cells_leaf": ["BUFLEAFX*"],
                "cts_inverter_cells_top": ["INVTOPX*"], "cts_inverter_cells_leaf": ["INVLEAFX*"],
            }),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["cts_buffer_cells_top"], ["BUFTOPX*"])
        self.assertEqual(document["cts_buffer_cells_leaf"], ["BUFLEAFX*"])
        self.assertEqual(document["cts_inverter_cells_top"], ["INVTOPX*"])
        self.assertEqual(document["cts_inverter_cells_leaf"], ["INVLEAFX*"])

    def test_unsupported_cts_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported setup.yaml key"):
            prepare_genus_inputs(
                self._design_setup({"bogus": []}),
                self.root / "backend" / "cadence-genus",
            )

    def test_target_skew_rejects_an_unrecognized_string(self):
        with self.assertRaisesRegex(ValueError, "cts_target_skew must be a number"):
            prepare_genus_inputs(
                self._design_setup({"cts_target_skew": "fast"}),
                self.root / "backend" / "cadence-genus",
            )

    def test_target_skew_and_transition_time_accept_the_documented_keywords(self):
        """Regression: cts_target_skew/cts_target_max_transition_time (man
        20.15) accept "default"/"auto"/"ignore"/"double" in addition to a
        numeric target -- a float-only check rejected these legitimate
        values outright."""
        for keyword in ("default", "auto", "ignore", "double"):
            inputs = prepare_genus_inputs(
                self._design_setup({
                    "cts_target_skew": keyword, "cts_target_max_transition_time": keyword,
                }),
                self.root / "backend" / "cadence-genus",
            )
            document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
            self.assertEqual(document["cts_target_skew"], keyword)
            self.assertEqual(document["cts_target_max_transition_time"], keyword)

    def test_a_commented_out_list_with_the_key_still_present_is_not_an_override(self):
        """Regression: commenting out a cts_buffer_cells list's items in
        setup.yaml (to fall back to the new library default) but leaving
        the key itself -- `cts_buffer_cells:` with nothing under it --
        parses as an explicit YAML null, not an absent key. setup.get(key,
        []) only substitutes [] when the key is missing entirely, so a
        null value reached _cell_pattern_list unchanged and raised "must
        be a list of nonempty strings" -- a real workflow this must not
        block."""
        inputs = prepare_genus_inputs(
            self._design_setup({"cts_buffer_cells": None, "cts_inverter_cells": None}),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        # Nulled-out keys pass straight through into the rendered
        # setup.yaml unchanged -- set_cts_config's own Tcl (not this
        # validator) is what turns a null/absent value into the library
        # default at get_flow_config -quiet time.
        self.assertIsNone(document["cts_buffer_cells"])
        self.assertIsNone(document["cts_inverter_cells"])

    def test_set_cts_config_is_shared_by_prects_and_cts(self):
        flows_text = (builtin_flow_root("cadence-genus") / "common_flows.tcl").read_text(
            encoding="utf-8",
        )
        self.assertIn("set_cts_config", flows_text)
        prects_line = next(line for line in flows_text.splitlines() if "set_cts_config" in line)
        self.assertIn("set_cts_config", prects_line)

    def test_set_cts_config_step_applies_every_resolved_value(self):
        step = builtin_flow_root("cadence-genus") / "common_steps.tcl"
        body = _extract_step_bodies(step.read_text(encoding="utf-8"))["set_cts_config"]
        # Cell-list attributes (including the top/leaf variants) are
        # applied via one generic foreach loop over the real set_db
        # attribute names (which, unlike the old wolf_cts_* globals,
        # are now identical to the get_flow_config keys), not one `if`
        # block per attribute -- assert the loop actually lists each one.
        for attribute in (
            "cts_buffer_cells", "cts_buffer_cells_top", "cts_buffer_cells_leaf",
            "cts_inverter_cells", "cts_inverter_cells_top", "cts_inverter_cells_leaf",
            "cts_clock_gating_cells",
        ):
            self.assertIn(attribute, body)
        self.assertIn("get_flow_config $wolf_cts_attr -quiet", body)
        self.assertIn("set_db $wolf_cts_attr $wolf_cts_value", body)
        for attribute, variable in (
            ("cts_target_skew", "wolf_cts_target_skew"),
            ("cts_target_max_transition_time", "wolf_cts_target_max_transition_time"),
            ("cts_max_fanout", "wolf_cts_max_fanout"),
        ):
            self.assertIn(f"get_flow_config {attribute} -quiet", body)
            self.assertIn(f"set_db {attribute} ${variable}", body)


@unittest.skipUnless(TCLSH, "tclsh is not installed")
class GenusCtsLibraryDefaultTests(unittest.TestCase):
    """Regression: set_cts_config used to leave cts_buffer_cells/
    cts_inverter_cells/cts_clock_gating_cells alone whenever setup.yaml
    gave no explicit value, letting CCOpt pick from the whole library
    unguided. It now defaults to the loaded library's own is_buffer/
    is_inverter/is_integrated_clock_gating cells (excluding dont_use)
    instead -- confirmed real base_cell attributes, via a real Innovus
    session -- so a project with no cts_* overrides at all still gets a
    sane, library-derived default rather than depending on a name
    pattern that might collide with an unrelated cell family."""

    # A minimal get_db stand-in covering exactly the two call shapes
    # set_cts_config makes: `get_db base_cells -if $filter` (resolved
    # against a synthetic library below) and `get_db $collection .name`
    # (the projection call, identity here since base_cells already
    # returns names).
    _STUB_LIBRARY = {
        "BUFX1": {"is_buffer": True, "is_inverter": False,
                   "is_integrated_clock_gating": False, "dont_use": False},
        "BUFX2": {"is_buffer": True, "is_inverter": False,
                   "is_integrated_clock_gating": False, "dont_use": False},
        "BUFX_OLD": {"is_buffer": True, "is_inverter": False,
                      "is_integrated_clock_gating": False, "dont_use": True},
        "INVX1": {"is_buffer": False, "is_inverter": True,
                   "is_integrated_clock_gating": False, "dont_use": False},
        "CGX1": {"is_buffer": False, "is_inverter": False,
                  "is_integrated_clock_gating": True, "dont_use": False},
    }

    def _get_db_stub(self) -> str:
        lines = ["proc get_db {args} {\n", "    global wolf_test_library\n"]
        lines.append("    if {[lindex $args 0] eq \"base_cells\"} {\n")
        lines.append("        set filt [lindex $args 2]\n")
        lines.append("        regexp {\\.(\\w+) == true} $filt -> attr\n")
        lines.append("        set matches {}\n")
        lines.append(
            "        foreach name [dict keys $wolf_test_library] {\n"
            "            set cell [dict get $wolf_test_library $name]\n"
            "            if {[dict get $cell $attr] && ![dict get $cell dont_use]} {\n"
            "                lappend matches $name\n"
            "            }\n"
            "        }\n"
            "        return $matches\n"
        )
        lines.append("    }\n")
        lines.append("    return [lindex $args 0]\n")
        lines.append("}\n")
        library_literal = "dict create " + " ".join(
            f"{name} {{{' '.join(f'{k} {1 if v else 0}' for k, v in attrs.items())}}}"
            for name, attrs in self._STUB_LIBRARY.items()
        )
        return "".join(lines) + f"set wolf_test_library [{library_literal}]\n"

    def _run(self, overrides: dict) -> subprocess.CompletedProcess:
        step = builtin_flow_root("cadence-genus") / "common_steps.tcl"
        body = _extract_step_bodies(step.read_text(encoding="utf-8"))["set_cts_config"]
        with tempfile.TemporaryDirectory(prefix="wolf-cts-default-") as tmp:
            script = Path(tmp) / "script.tcl"
            script.write_text(
                "proc wolf_inject_for_step {args} {}\n"
                "proc wolf_info {args} { puts \"INFO: $args\" }\n"
                "proc set_db {args} { puts \"SETDB: $args\" }\n"
                "namespace eval ansicolor { proc + {args} { return \"\" } }\n"
                + self._get_db_stub()
                + _get_flow_config_stub(overrides)
                + f"uplevel #0 {body}\n",
                encoding="utf-8",
            )
            return subprocess.run(
                [TCLSH, str(script)], capture_output=True, text=True, check=False,
            )

    def test_no_setup_yaml_override_defaults_from_library_attributes(self):
        result = self._run({})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("SETDB: cts_buffer_cells {BUFX1 BUFX2}", result.stdout)
        self.assertIn("SETDB: cts_inverter_cells INVX1", result.stdout)
        self.assertIn("SETDB: cts_clock_gating_cells CGX1", result.stdout)
        # BUFX_OLD is dont_use -- must never appear in the resolved default.
        self.assertNotIn("BUFX_OLD", result.stdout)
        # Regression: the resolved source (library default vs setup.yaml
        # override) must be visible in the printed INFO line, not just
        # inferable from the value itself.
        self.assertIn("cts_buffer_cells: BUFX1 BUFX2 (library default)", result.stdout)
        self.assertIn("cts_inverter_cells: INVX1 (library default)", result.stdout)
        self.assertIn("cts_clock_gating_cells: CGX1 (library default)", result.stdout)

    def test_setup_yaml_override_replaces_the_library_default_outright(self):
        result = self._run({"cts_buffer_cells": ["CUSTOMBUF1", "CUSTOMBUF2"]})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("SETDB: cts_buffer_cells {CUSTOMBUF1 CUSTOMBUF2}", result.stdout)
        self.assertNotIn("BUFX1", result.stdout)
        self.assertNotIn("BUFX2", result.stdout)
        self.assertIn(
            "cts_buffer_cells: CUSTOMBUF1 CUSTOMBUF2 (setup.yaml override)", result.stdout,
        )
        # Inverter/clock-gating still fall back to the library default.
        self.assertIn("SETDB: cts_inverter_cells INVX1", result.stdout)
        self.assertIn("SETDB: cts_clock_gating_cells CGX1", result.stdout)
        self.assertIn("cts_inverter_cells: INVX1 (library default)", result.stdout)
        self.assertIn("cts_clock_gating_cells: CGX1 (library default)", result.stdout)


class GenusTieoffTests(GenusFixtureTestCase):
    """backend.cadence-flowtool.tieoffs -- resolves add_tieoffs_cells (at
    most two: tie-high/tie-low) and its companion attributes before
    add_tieoffs's own existing guard."""

    def test_default_is_empty(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertNotIn("add_tieoffs_cells", document)
        self.assertNotIn("add_tieoffs_honor_dont_use", document)

    def test_resolved_cells_are_written_into_flow_config(self):
        inputs = prepare_genus_inputs(
            self._design_setup({
                "add_tieoffs_cells": ["TIEHIX1", "TIELOX1"], "add_tieoffs_honor_dont_use": True,
                "add_tieoffs_max_fanout": 10, "add_tieoffs_max_distance": 20.0,
            }),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["add_tieoffs_cells"], ["TIEHIX1", "TIELOX1"])
        self.assertEqual(document["add_tieoffs_honor_dont_use"], True)
        self.assertEqual(document["add_tieoffs_max_fanout"], 10)
        self.assertEqual(document["add_tieoffs_max_distance"], 20.0)

    def test_more_than_two_cells_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "at most two cells"):
            prepare_genus_inputs(
                self._design_setup({"add_tieoffs_cells": ["A", "B", "C"]}),
                self.root / "backend" / "cadence-genus",
            )

    def test_a_commented_out_add_tieoffs_cells_list_is_not_an_override(self):
        inputs = prepare_genus_inputs(
            self._design_setup({"add_tieoffs_cells": None}),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertIsNone(document["add_tieoffs_cells"])

    def test_add_tieoffs_step_resolves_and_reports(self):
        step = builtin_flow_root("cadence-genus") / "cts.tcl"
        body = _extract_step_bodies(step.read_text(encoding="utf-8"))["add_tieoffs"]
        self.assertIn("get_flow_config add_tieoffs_cells -quiet", body)
        self.assertIn("set_db add_tieoffs_cells $wolf_tieoff_cells", body)
        self.assertIn("get_db insts -if {.base_cell.name == $wolf_tie_cell}", body)
        self.assertIn("check_tieoffs", body)
        self.assertIn("wolf_error", body)


class GenusClockRoutingTests(GenusFixtureTestCase):
    """backend.cadence-flowtool.clock_routing -- a non-default route rule
    and top/trunk/leaf route types for add_clock_route_types, with layer
    names validated Tcl-side against the loaded technology (WOLF itself
    has no layer list to check against at config-generation time)."""

    def test_default_is_empty(self):
        inputs = prepare_genus_inputs(self._context(), self.root / "backend" / "cadence-genus")
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertNotIn("clock_routing_width_multiplier", document)
        self.assertNotIn("clock_routing_spacing_multiplier", document)
        self.assertNotIn("clock_routing_types", document)

    def test_resolved_rule_and_types_are_written_into_flow_config(self):
        inputs = prepare_genus_inputs(
            self._design_setup({
                "clock_routing_width_multiplier": {"M6:M5": 2.0},
                "clock_routing_spacing_multiplier": {"M6:M5": 2.0},
                "clock_routing_types": {
                    "trunk": {"route_rule": True, "top_preferred_layer": "M6",
                              "bottom_preferred_layer": "M5"},
                    "leaf": {"route_rule": True, "top_preferred_layer": "M4",
                             "bottom_preferred_layer": "M3"},
                },
            }),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertEqual(document["clock_routing_width_multiplier"], {"M6:M5": 2.0})
        self.assertEqual(document["clock_routing_spacing_multiplier"], {"M6:M5": 2.0})
        self.assertEqual(document["clock_routing_types"], {
            "trunk": {"route_rule": True, "top_preferred_layer": "M6",
                      "bottom_preferred_layer": "M5"},
            "leaf": {"route_rule": True, "top_preferred_layer": "M4",
                     "bottom_preferred_layer": "M3"},
        })

    def test_unsupported_route_type_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported clock_routing_types key"):
            prepare_genus_inputs(
                self._design_setup({"clock_routing_types": {"bogus": {}}}),
                self.root / "backend" / "cadence-genus",
            )

    def test_commented_out_clock_routing_blocks_are_not_overrides(self):
        inputs = prepare_genus_inputs(
            self._design_setup({
                "clock_routing_width_multiplier": None, "clock_routing_spacing_multiplier": None,
                "clock_routing_types": None,
            }),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        self.assertIsNone(document["clock_routing_width_multiplier"])
        self.assertIsNone(document["clock_routing_spacing_multiplier"])
        self.assertIsNone(document["clock_routing_types"])

    def test_add_clock_route_types_step_validates_layers_and_creates_rule_and_types(self):
        step = builtin_flow_root("cadence-genus") / "floorplanning.tcl"
        body = _extract_step_bodies(step.read_text(encoding="utf-8"))["add_clock_route_types"]
        self.assertIn("create_route_rule", body)
        self.assertIn("create_route_type", body)
        self.assertIn("get_db layers .name", body)
        self.assertIn("set_db cts_route_type_$wolf_type_name", body)


class GenusReportStepsTests(GenusFixtureTestCase):
    """report_check_design's stage-appropriate -type, and the previously
    empty report_early_summary_innovus/report_early_paths/
    report_late_summary_innovus -- all read-only report_timing_summary/
    report_timing commands (confirmed no optimization side effect, man
    20.15), unlike timeDesign which left these empty before."""

    def test_report_check_design_picks_cts_type_for_cts_stages(self):
        step = builtin_flow_root("cadence-genus") / "common_steps.tcl"
        body = _extract_step_bodies(step.read_text(encoding="utf-8"))["report_check_design"]
        self.assertIn('{cts postcts} $report_check_design_stage', body)
        self.assertIn("check_design -type $report_check_design_type", body)

    def test_early_and_late_summary_and_paths_use_read_only_reports(self):
        step = builtin_flow_root("cadence-genus") / "common_steps.tcl"
        bodies = _extract_step_bodies(step.read_text(encoding="utf-8"))
        self.assertIn("report_timing_summary -checks {hold drv}", bodies["report_early_summary_innovus"])
        self.assertIn("report_timing -early -nworst 5", bodies["report_early_paths"])
        self.assertIn("report_timing_summary -checks {setup drv}", bodies["report_late_summary_innovus"])


class GenusCongestionReapplyTests(GenusFixtureTestCase):
    """CMD_set_cong_aware (design_cong_effort/opt_consider_routing_congestion/
    place_global_cong_effort) was only ever in the floorplan flow, but
    run_place_opt (prects) also depends on it -- each stage is a separate
    Innovus invocation restored from a checkpoint, and whether root set_db
    attributes survive that restore is not documented, so it is re-applied
    (the same existing step, reused) at the start of prects too."""

    def test_cmd_set_cong_aware_runs_at_the_start_of_prects_too(self):
        flows_text = (builtin_flow_root("cadence-genus") / "common_flows.tcl").read_text(
            encoding="utf-8",
        )
        prects_line = next(
            line for line in flows_text.splitlines() if "init_innovus CMD_set_cong_aware" in line
        )
        self.assertIn("CMD_set_cong_aware", prects_line)


class GenusClockTreeVisibilityTests(GenusFixtureTestCase):
    """Read-only clock-tree reporting after add_clock_spec and
    add_clock_tree -- get_db clock_trees .name (already used elsewhere in
    this flow to check whether a spec exists) and report_clock_trees
    (confirmed real, read-only, man 20.15)."""

    def test_add_clock_spec_logs_clock_tree_names(self):
        step = builtin_flow_root("cadence-genus") / "floorplanning.tcl"
        body = _extract_step_bodies(step.read_text(encoding="utf-8"))["add_clock_spec"]
        self.assertIn("get_db clock_trees .name", body)
        self.assertIn("wolf_info", body)

    def test_add_clock_tree_reports_clock_tree_structure(self):
        step = builtin_flow_root("cadence-genus") / "cts.tcl"
        body = _extract_step_bodies(step.read_text(encoding="utf-8"))["add_clock_tree"]
        self.assertIn("get_db clock_trees .name", body)
        self.assertIn("report_clock_trees -out_file", body)
        self.assertIn("wolf_file", body)


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
class WolfStepStatusWrapperTests(unittest.TestCase):
    """presentation.tcl wraps Flowtool's own native create_flow_step so
    every real step writes a live wolf.step-status record as it starts,
    succeeds, or fails -- real root cause this pins: the step's own
    body is NOT always create_flow_step's last argument. Several real
    steps (synthesis.tcl's own elaborate, among others) trail it with a
    bare -write_db flag -- `create_flow_step -name X -owner wolf {BODY}
    -write_db` -- which a naive "last argument is the body" wrapper
    mistakes for the body itself, corrupting the step entirely."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-step-status-")
        self.root = Path(self.temporary.name)
        self.run_directory = self.root / "run"
        self.run_directory.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    # A native-command stand-in that finds the body the same
    # newline-based way as the real wrapper, so this test harness
    # correctly mimics Flowtool's own command regardless of whether a
    # trailing flag (like -write_db) is present.
    _NATIVE_STUB = (
        "proc create_flow_step {args} {\n"
        "    set i -1\n"
        "    foreach a $args { incr i; if {[string first \"\\n\" $a] >= 0} { break } }\n"
        "    uplevel 1 [lindex $args $i]\n"
        "}\n"
    )

    def _run(self, extra_tcl: str) -> subprocess.CompletedProcess:
        presentation = builtin_flow_root("cadence-genus") / "presentation.tcl"
        script = self.root / "script.tcl"
        script.write_text(
            self._NATIVE_STUB
            + _get_flow_config_stub({"run_directory": str(self.run_directory)})
            + f'source {{{presentation}}}\n'
            + extra_tcl,
            encoding="utf-8",
        )
        return subprocess.run([TCLSH, str(script)], capture_output=True, text=True, check=False)

    def _step_status_lines(self) -> list[str]:
        path = self.run_directory / "wolf.step-status"
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []

    def test_a_trailing_write_db_flag_does_not_corrupt_the_body(self):
        """Regression: elaborate's real shape -- this failed with
        "invalid command name "-write_db"" before the fix, because the
        wrapper mistook the trailing flag itself for the step body."""
        result = self._run(
            "create_flow_step -name elaborate -owner wolf {\n"
            "    set ::elaborate_ran 1\n"
            "} -write_db\n"
            "puts \"elaborate_ran=$::elaborate_ran\"\n"
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("elaborate_ran=1", result.stdout)
        lines = self._step_status_lines()
        self.assertEqual([line.split("|")[0:2] for line in lines], [
            ["elaborate", "starting"], ["elaborate", "success"],
        ])

    def test_a_categories_flag_before_the_body_is_still_handled(self):
        result = self._run(
            "create_flow_step -name block_finish -owner wolf -categories flow {\n"
            "    set ::ran 1\n"
            "}\n"
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        lines = self._step_status_lines()
        self.assertEqual([line.split("|")[0:2] for line in lines], [
            ["block_finish", "starting"], ["block_finish", "success"],
        ])

    def test_a_failing_step_writes_failed_and_still_raises(self):
        result = self._run(
            "create_flow_step -name bad_step -owner wolf {\n"
            "    error \"deliberate failure\"\n"
            "}\n"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("deliberate failure", result.stdout + result.stderr)
        lines = self._step_status_lines()
        self.assertEqual([line.split("|")[0:2] for line in lines], [
            ["bad_step", "starting"], ["bad_step", "failed"],
        ])

    def test_no_wolf_run_directory_set_degrades_to_writing_nothing(self):
        presentation = builtin_flow_root("cadence-genus") / "presentation.tcl"
        script = self.root / "script.tcl"
        script.write_text(
            self._NATIVE_STUB
            + _get_flow_config_stub({})
            + f'source {{{presentation}}}\n'
            "create_flow_step -name ok_step -owner wolf {\n"
            "    set ::ran 1\n"
            "}\n",
            encoding="utf-8",
        )
        result = subprocess.run([TCLSH, str(script)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(self._step_status_lines(), [])


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
proc uniquify {args} { puts "STUB uniquify $args" }
proc report_timing {args} { puts "STUB report_timing $args" }
proc read_power_intent {args} { puts "STUB read_power_intent $args" }
proc commit_power_intent {args} { puts "STUB commit_power_intent $args" }
proc set_timing_derate {args} { puts "STUB set_timing_derate $args" }
proc all_clocks {} { return {} }

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

    def _run_flow_tcl(self, document: dict, *, run: str = "synthesis", extra: str = "") -> str:
        root = builtin_flow_root("cadence-genus")
        stub = self.root / "stub_run.tcl"
        stub.write_text(
            self._STUB_COMMANDS + _get_flow_config_stub(document) + extra
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

    def _base_document(self, **overrides) -> dict:
        (self.root / "reports").mkdir(exist_ok=True)
        (self.root / "outputs").mkdir(exist_ok=True)
        (self.root / "sources.tcl").write_text("# stub\n", encoding="utf-8")
        (self.root / "constraints.sdc").write_text("# stub\n", encoding="utf-8")
        document = {
            "design_name": "demo", "design_top": "top",
            "reports_dir": str(self.root / "reports"), "outputs_dir": str(self.root / "outputs"),
            "handoff_dir": str(self.root / "handoff"),
            "sources_script": str(self.root / "sources.tcl"),
            "constraints_file": str(self.root / "constraints.sdc"),
        }
        document.update(overrides)
        return document

    def test_full_synthesis_flow_registers_and_runs_steps_in_order(self):
        output = self._run_flow_tcl(self._base_document(dont_use_cells=["*_lvt"]))
        ordered = (
            "REGISTER STEP block_start", "REGISTER STEP avoid_module_renaming",
            "REGISTER STEP read_mmmc", "REGISTER STEP apply_clock_derate",
            "REGISTER STEP read_physical", "REGISTER STEP read_hdl",
            "REGISTER STEP elaborate", "STUB elaborate top", "STUB read_sdc",
            "REGISTER STEP uniquify_modules", "STUB uniquify top",
            "REGISTER STEP preserve_blocks", "REGISTER STEP preserve_instances",
            "REGISTER STEP read_power_intent", "REGISTER STEP run_init_design",
            "REGISTER STEP read_def", "REGISTER STEP init_genus",
            "REGISTER STEP set_dont_use", "STUB set_db {} .dont_use true",
            "REGISTER STEP prevent_flattening", "REGISTER STEP max_routing_layer",
            "REGISTER STEP commit_power_intent",
            "REGISTER STEP create_cost_group", "STUB group_path -name in2out",
            "REGISTER STEP run_syn_generic", "STUB syn_generic", "REGISTER STEP block_finish",
            "REGISTER STEP report_start", "REGISTER STEP report_area_genus",
            "REGISTER STEP report_finish",
            "REGISTER STEP run_syn_map", "STUB syn_map",
            "REGISTER STEP run_syn_opt", "STUB syn_opt",
            "REGISTER STEP genus_to_innovus", "STUB update_names", "STUB write_design",
            "REGISTER STEP build_sim_testbench", "REGISTER STEP build_xsim_files",
        )
        indices = [output.index(fragment) for fragment in ordered]
        self.assertEqual(indices, sorted(indices))
        self.assertIn(f"STUB write_hdl > {self.root / 'outputs'}/demo.generic.v", output)
        self.assertIn(f"STUB write_hdl > {self.root / 'outputs'}/demo.mapped.v", output)
        self.assertIn(f"STUB write_hdl > {self.root / 'outputs'}/demo.opt.v", output)

    def test_single_stage_flows_also_resolve_and_run(self):
        self._run_flow_tcl(self._base_document(), run="syn_generic")
        self._run_flow_tcl(self._base_document(), run="syn_map")
        self._run_flow_tcl(self._base_document(), run="syn_opt")

    def test_mmmc_script_is_read_and_skips_the_plain_read_sdc(self):
        """A real mmmc.tcl (as prepare_genus_inputs would generate for a
        multi-corner technology package) must be real, valid Tcl, and
        init_elaborate must not also call read_sdc once MMMC already
        points its constraint modes at the same file."""
        mmmc = self.root / "mmmc.tcl"
        mmmc.write_text(
            'create_library_set -name "typical" -timing {/lib/typical.lib}\n'
            'create_timing_condition -name "typical" -library_sets {typical}\n'
            'create_delay_corner -name "typical" -timing_condition "typical"\n'
            'create_constraint_mode -name "typical" -sdc_files {/x/constraints.sdc}\n'
            'create_analysis_view -name "typical" -constraint_mode "typical" -delay_corner "typical"\n'
            'set_analysis_view -setup {typical} -hold {typical}\n',
            encoding="utf-8",
        )
        output = self._run_flow_tcl(
            self._base_document(mmmc_script=str(mmmc)), run="syn_generic",
        )
        self.assertIn(f"STUB read_mmmc {mmmc}", output)
        self.assertIn("STUB create_library_set -name typical", output)
        self.assertIn("STUB set_analysis_view -setup typical -hold typical", output)
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
        output = self._run_flow_tcl(self._base_document(technology_lefs=[str(lef)]), run="syn_generic")
        physical_index = output.index("STUB read_physical")
        elaborate_index = output.index("STUB elaborate top")
        init_index = output.index("STUB init_design")
        self.assertLess(physical_index, elaborate_index)
        self.assertLess(elaborate_index, init_index)

    def test_no_physical_views_skips_read_physical_and_init_design(self):
        """read_physical and run_init_design are always real, registered
        steps now (each its own banner) -- what must not happen without
        any LEF configured is the real STUB call underneath either one."""
        output = self._run_flow_tcl(self._base_document(), run="syn_generic")
        self.assertNotIn("STUB read_physical", output)
        self.assertNotIn("STUB init_design", output)
        self.assertIn("read_physical: no LEF resolved for this technology, skipping", output)
        self.assertIn("run_init_design: no physical views or MMMC active, skipping", output)

    def test_postsyn_netlists_are_read_before_handoff(self):
        output = self._run_flow_tcl(
            self._base_document(postsyn_netlists=["/tiles/lut4ab.v"]), run="syn_opt",
        )
        self.assertIn("STUB read_hdl -sv -library work /tiles/lut4ab.v", output)
        read_index = output.index("STUB read_hdl -sv -library work /tiles/lut4ab.v")
        write_index = output.index("STUB write_design")
        self.assertLess(read_index, write_index)

    def test_inject_hook_runs_at_the_right_point(self):
        marker = self.root / "injected-marker"
        snippet = self.root / "snippet.tcl"
        snippet.write_text(f'puts "INJECTED"\nclose [open {{{marker}}} w]\n', encoding="utf-8")
        document = self._base_document(inject={"elaborate": {"post": [str(snippet)]}})
        output = self._run_flow_tcl(document, run="syn_generic")
        self.assertIn("INJECTED", output)
        self.assertTrue(marker.is_file())
        elaborate_index = output.index("STUB elaborate top")
        inject_index = output.index("INJECTED")
        dont_use_index = output.index("REGISTER STEP set_dont_use")
        self.assertLess(elaborate_index, inject_index)
        self.assertLess(inject_index, dont_use_index)


class FlowMembershipTests(unittest.TestCase):
    """flow_membership/flow_descendant_steps parse create_flow's own
    member lists from common_flows.tcl -- the real flow->step tree, not
    guessed. Regression coverage for a real bug this caught: a step
    defined in floorplanning.tcl but never referenced by any create_flow
    member list is dead code Flowtool would never run -- confirmed real
    for init_implementation/add_tracks (fixed in common_flows.tcl's own
    floorplan entry) before this test existed."""

    def test_wrapped_member_lists_do_not_leave_a_stray_backslash_token(self):
        text = (
            "create_flow -name demo -owner wolf \\\n"
            "    {step_one step_two \\\n"
            "     step_three}\n"
        )
        from wolf.backend.cadence_genus import _extract_flow_members
        self.assertEqual(_extract_flow_members(text), {"demo": ("step_one", "step_two", "step_three")})

    def test_every_real_step_is_reachable_from_block_except_signoff(self):
        """signoff is the one deliberate exception (a separate, explicitly
        invoked entry point, not chained through block/implementation --
        see common_flows.tcl's own comment); every other real
        create_flow_step must be reachable, or wolf run would silently
        never execute it."""
        digests = flow_step_digests()
        reachable = set(flow_descendant_steps("block"))
        unreachable = set(digests) - reachable
        self.assertEqual(unreachable, {"schedule_signoff_subflows"})

    def test_floorplan_loads_the_genus_handoff_before_anything_else(self):
        """init_implementation (sourcing the Genus->Innovus .invs_init.tcl
        handoff) must run before any step that assumes a design is
        already loaded in Innovus -- the real bug this test pins."""
        steps = flow_descendant_steps("floorplan")
        self.assertIn("init_implementation", steps)
        self.assertEqual(steps.index("init_implementation"), 1)  # right after block_start

    def test_a_step_name_with_no_flow_definition_is_its_own_leaf(self):
        self.assertEqual(flow_descendant_steps("read_hdl", {}), ("read_hdl",))

    def test_nested_flow_references_expand_recursively_without_duplicates(self):
        membership = {
            "top": ("a", "sub"),
            "sub": ("a", "b"),  # "a" appears in both -- must not be duplicated
        }
        self.assertEqual(flow_descendant_steps("top", membership), ("a", "b"))


class RunManifestVolatilityTests(unittest.TestCase):
    """Regression: a run allocated while flows/cadence-genus/setup.template.yaml
    was missing from the install (see pyproject.toml's data-files entry)
    froze setup_yaml as null; continuing that same run after reinstalling
    correctly produces a real setup_yaml path -- a WOLF-side fix taking
    effect mid-run, not a design identity change, so run_genus's own
    volatile_keys must tolerate it the same way technology.cell_lefs/
    technology.rc_files are already tolerated via volatile_paths."""

    def test_setup_yaml_is_volatile(self):
        self.assertIn("setup_yaml", _RUN_MANIFEST_VOLATILE_KEYS)

    def test_a_real_identity_field_is_not_volatile(self):
        self.assertNotIn("dont_use_cells", _RUN_MANIFEST_VOLATILE_KEYS)
        self.assertNotIn("technology", _RUN_MANIFEST_VOLATILE_KEYS)


class ForceFreezeRunManifestTests(unittest.TestCase):
    """run_genus's force=True escape hatch: a human-judged override for a
    real mismatch _RUN_MANIFEST_VOLATILE_KEYS/_RUN_MANIFEST_VOLATILE_PATHS
    doesn't already tolerate. Must not silently discard the disagreement
    -- see _force_freeze_run_manifest's own docstring."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-force-freeze-")
        self.root = Path(self.temporary.name)
        self.run_directory = self.root / "run"
        self.run_directory.mkdir()
        self.generated_directory = self.root / "generated"
        self.generated_directory.mkdir()
        from wolf.provenance import RUN_MANIFEST_FILENAME, freeze_run_manifest
        self.source = self.root / "resolved.yaml"
        self.source.write_text(yaml.safe_dump({
            "schema": "wolf.resolved-run/v1", "design": {"name": "demo"},
            "dont_use_cells": ["OLD_CELL"],
        }, sort_keys=False), encoding="utf-8")
        freeze_run_manifest(
            self.source, self.run_directory, generated_directory=self.generated_directory,
            generated_files={},
        )
        self.manifest_path = self.run_directory / RUN_MANIFEST_FILENAME

    def tearDown(self):
        self.temporary.cleanup()

    def test_force_overwrites_a_real_mismatch_instead_of_raising(self):
        self.source.write_text(yaml.safe_dump({
            "schema": "wolf.resolved-run/v1", "design": {"name": "demo"},
            "dont_use_cells": ["NEW_CELL"],
        }, sort_keys=False), encoding="utf-8")
        from wolf.provenance import freeze_run_manifest
        with self.assertRaisesRegex(ValueError, "different immutable provenance"):
            freeze_run_manifest(self.source, self.run_directory)

        _force_freeze_run_manifest(
            self.source, self.run_directory,
            generated_directory=self.generated_directory, generated_files={},
        )
        frozen = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(frozen["dont_use_cells"], ["NEW_CELL"])

    def test_force_appends_an_audit_entry_naming_what_changed(self):
        self.source.write_text(yaml.safe_dump({
            "schema": "wolf.resolved-run/v1", "design": {"name": "demo"},
            "dont_use_cells": ["NEW_CELL"],
        }, sort_keys=False), encoding="utf-8")
        _force_freeze_run_manifest(
            self.source, self.run_directory,
            generated_directory=self.generated_directory, generated_files={},
        )
        drift_log = self.run_directory / "wolf.resolved.drift.yaml"
        self.assertTrue(drift_log.is_file())
        entries = yaml.safe_load(drift_log.read_text(encoding="utf-8"))
        self.assertEqual(len(entries), 1)
        self.assertEqual(
            entries[0]["changed_keys"]["dont_use_cells"],
            {"old": ["OLD_CELL"], "new": ["NEW_CELL"]},
        )
        self.assertIn("timestamp", entries[0])

    def test_two_forced_overrides_both_land_in_the_same_append_only_log(self):
        for new_cell in ("NEW_CELL", "NEWER_CELL"):
            self.source.write_text(yaml.safe_dump({
                "schema": "wolf.resolved-run/v1", "design": {"name": "demo"},
                "dont_use_cells": [new_cell],
            }, sort_keys=False), encoding="utf-8")
            _force_freeze_run_manifest(
                self.source, self.run_directory,
                generated_directory=self.generated_directory, generated_files={},
            )
        drift_log = self.run_directory / "wolf.resolved.drift.yaml"
        entries = yaml.safe_load(drift_log.read_text(encoding="utf-8"))
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[1]["changed_keys"]["dont_use_cells"]["new"], ["NEWER_CELL"])


class FlowIdentityTests(unittest.TestCase):
    """bundled_flow_digest/flow_step_digests back both the automatic
    identity banner flow-config.tcl's own tail prints once setup
    finishes, and the matching WOLF-side banner run.py prints right
    before `wolf run` exits (success or failure)."""

    def test_extract_step_bodies_handles_nested_braces(self):
        text = (
            "create_flow_step -name outer -owner wolf {\n"
            "    if {$::x ne \"\"} {\n"
            "        set_db foo bar\n"
            "    }\n"
            "}\n"
            "create_flow_step -name second -owner wolf {\n"
            "    puts hi\n"
            "}\n"
        )
        bodies = _extract_step_bodies(text)
        self.assertEqual(set(bodies), {"outer", "second"})
        self.assertEqual(bodies["outer"].count("{"), bodies["outer"].count("}"))
        self.assertIn("set_db foo bar", bodies["outer"])
        self.assertEqual(bodies["second"], "{\n    puts hi\n}")

    def test_every_real_create_flow_step_gets_exactly_one_digest(self):
        """Regression: two steps (commit_power_intent, report_late_paths)
        were each defined twice across different files with identical
        bodies -- harmless at runtime (same content either way) but a
        real duplication that silently collapsed to one dict entry here,
        undercounting. Fixed by keeping one definition per step name."""
        root = Path(__file__).resolve().parents[1] / "flows" / "cadence-genus"
        grep_count = sum(
            (root / name).read_text(encoding="utf-8").count("create_flow_step -name")
            for name in (
                "presentation.tcl", "common_flows.tcl", "common_steps.tcl", "synthesis.tcl",
                "floorplanning.tcl", "cts.tcl", "route.tcl", "postroute.tcl",
            )
        )
        digests = flow_step_digests()
        self.assertEqual(len(digests), grep_count)

    def test_digests_are_stable_and_short(self):
        first = flow_step_digests()
        second = flow_step_digests()
        self.assertEqual(first, second)
        for digest in first.values():
            self.assertEqual(len(digest), 12)
        self.assertEqual(len(bundled_flow_digest()), 12)

    def test_flow_config_tail_prints_the_identity_banner_but_not_report_flow(self):
        """The identity banner (wolf_step/wolf_info) runs automatically
        once setup finishes (every create_flow/create_flow_step above it
        has already registered), not something the user has to type by
        hand. The real native report_flow command is deliberately NOT
        called automatically here -- confirmed against a real run that
        invoking it this early, while Flowtool is still sourcing
        user_flow_steps, throws Flowtool's own internal Tcl error
        ("expected boolean value but got \"\"")."""
        case = GenusFixtureTestCase()
        case.setUp()
        try:
            inputs = prepare_genus_inputs(case._context(), case.root / "backend" / "cadence-genus")
            flow_config = inputs.flow_config_script.read_text(encoding="utf-8")
            self.assertNotIn("report_flow", flow_config)
            self.assertIn(f"sha256:{bundled_flow_digest()}", flow_config)
            for name, digest in flow_step_digests().items():
                self.assertIn(f"{name}: sha256:{digest}", flow_config)
        finally:
            case.tearDown()


class GenusTclListQuotingTests(GenusFixtureTestCase):
    """Regression coverage for the real production bug where every
    `$::wolf_*` list variable in the old flow-config.tcl (and mmmc.tcl's
    list-typed arguments) was written with an extra, un-stripped layer of
    quoting baked into its stored Tcl value -- invisible to a
    list-reparsing consumer (foreach/llength/lindex/concat), but
    corrupting a plain word-substitution consumer like `set_analysis_view
    -setup $wolf_setup_views`. That whole flow-config.tcl rendering layer
    is gone now (every value reaches Tcl through get_flow_config against
    the real rendered setup.yaml instead -- see _tcl_list's own docstring
    in cadence_genus.py for the full original mechanism), which is
    structurally not susceptible to this bug class any more: get_flow_config
    returns a real Tcl value Flowtool itself constructed from the YAML, not
    hand-rendered Tcl list-literal text. These tests prove that property
    against the real rendered setup.yaml and the real floorplanning.tcl
    step body, not just against the elimination of the old mechanism."""

    def _corners(self):
        wcl_lib = self.root / "wcl.lib"
        bc_lib = self.root / "bc.lib"
        for path in (wcl_lib, bc_lib):
            path.write_text(f"-- {path.name} --\n", encoding="utf-8")
        return (
            ResolvedTimingCorner(name="wcl", libraries=(wcl_lib,)),
            ResolvedTimingCorner(name="bc", libraries=(bc_lib,)),
        )

    @unittest.skipUnless(TCLSH, "tclsh is not installed")
    def test_every_list_variable_round_trips_clean_through_real_tclsh(self):
        """Render the real setup.yaml for a realistic mix of list-valued
        settings -- an empty list (dont_use_cells, left unconfigured), a
        multi-element list with a space in one element (synthetic net
        names, not real ones), and a single element containing Tcl-special
        bracket characters (a synthetic tieoff cell name) -- feed it
        through the real get_flow_config stub (backed by Tcl's own
        list/dict constructors, see _get_flow_config_stub) and assert
        llength/lindex see exactly the intended elements, with no residual
        quote or brace characters in any element."""
        inputs = prepare_genus_inputs(
            self._design_setup(
                {"add_tieoffs_cells": ["TIE[HI]"]},
                technology=ResolvedTechnology(
                    package="pdk/demo", revision="1", name="demo", root=self.root,
                    timing_corners=self._corners(),
                ),
                power_nets=("VDD", "aux supply"),
                ground_nets=("VSS",),
            ),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        probe = self.root / "probe.tcl"
        probe.write_text(
            _get_flow_config_stub(document)
            + "foreach v {dont_use_cells power_nets ground_nets add_tieoffs_cells} {\n"
            '    set value [get_flow_config $v -quiet]\n'
            '    puts "$v llength=[llength $value]"\n'
            '    foreach e $value { puts "$v elem=|$e|" }\n'
            "}\n",
            encoding="utf-8",
        )
        result = subprocess.run([TCLSH, str(probe)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        output = result.stdout
        self.assertIn("dont_use_cells llength=0", output)
        self.assertIn("power_nets llength=2", output)
        self.assertIn("power_nets elem=|VDD|", output)
        self.assertIn("power_nets elem=|aux supply|", output)
        self.assertIn("ground_nets llength=1", output)
        self.assertIn("ground_nets elem=|VSS|", output)
        self.assertIn("add_tieoffs_cells llength=1", output)
        self.assertIn("add_tieoffs_cells elem=|TIE[HI]|", output)

    @unittest.skipUnless(TCLSH, "tclsh is not installed")
    def test_active_views_reach_set_analysis_view_clean_in_init_innovus(self):
        """The exact real failure reported from production: a two-corner
        technology (named wcl/bc here, matching the real report) with
        this design's own setup.yaml active_views narrowed to one view
        each for setup/hold, run through floorplanning.tcl's real
        init_innovus step body (not a stand-in) via a stub Innovus backed
        by the real rendered setup.yaml. Before the original fix,
        set_analysis_view received the quoted/braced literal `"wcl"` (or,
        after an intermediate fix attempt, `{wcl}`) instead of a clean
        `wcl` -- which is exactly why Innovus reported "Can not find
        'analysis view' object with the name '\"wcl\"'" against the real
        design. get_flow_config structurally cannot reproduce that bug
        (it returns a real Tcl value, not rendered list-literal text),
        but this keeps the exact real scenario pinned."""
        inputs = prepare_genus_inputs(
            self._design_setup(
                {"active_views": {"setup": ["wcl"], "hold": ["bc"]}},
                technology=ResolvedTechnology(
                    package="pdk/demo", revision="1", name="demo", root=self.root,
                    timing_corners=self._corners(),
                ),
            ),
            self.root / "backend" / "cadence-genus",
        )
        document = yaml.safe_load(inputs.setup_yaml.read_text(encoding="utf-8"))
        floorplanning = builtin_flow_root("cadence-genus") / "floorplanning.tcl"
        stub = self.root / "innovus_stub.tcl"
        stub.write_text(
            _get_flow_config_stub(document)
            + 'proc get_db {args} {\n'
            '    if {[lindex $args 0] eq "analysis_views"} { return {wcl bc} }\n'
            '    return {}\n'
            '}\n'
            'proc set_db {args} {}\n'
            'proc set_multi_cpu_usage {args} {}\n'
            'proc set_analysis_view {args} { puts "CALL set_analysis_view $args" }\n'
            'proc wolf_info {msg} { puts "INFO: $msg" }\n'
            'proc wolf_step {args} {}\n'
            'proc wolf_inject_for_step {args} {}\n'
            'proc wolf_sep {} { return {} }\n'
            'array set STEP_BODIES {}\n'
            'proc create_flow_step {args} {\n'
            '    global STEP_BODIES\n'
            '    set name ""\n'
            '    foreach {a b} $args { if {$a eq "-name"} { set name $b } }\n'
            '    set STEP_BODIES($name) [lindex $args end]\n'
            '}\n'
            f'source {{{floorplanning}}}\n'
            'uplevel #0 $STEP_BODIES(init_innovus)\n',
            encoding="utf-8",
        )
        result = subprocess.run([TCLSH, str(stub)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        output = result.stdout
        self.assertIn("CALL set_analysis_view -setup wcl -hold bc", output)
        self.assertNotIn('"wcl"', output)
        self.assertNotIn("{wcl}", output)


class GenusRunStepEventsTests(unittest.TestCase):
    """genus_run_step_events reads WOLF's own live per-step record
    directly off disk (<run_directory>/wolf.step-status), written by
    presentation.tcl's create_flow_step wrapper -- a plain file read,
    bare step-name keyed, safe because the file is truncated fresh
    every flowtool invocation (see stage_step_detail's own docstring)."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-step-events-")
        self.root = Path(self.temporary.name)
        self.run_directory = self.root / "work" / "demo.1"
        self.run_directory.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def _write_events(self, text: str) -> None:
        (self.run_directory / "wolf.step-status").write_text(text, encoding="utf-8")

    def test_no_file_yet_returns_empty(self):
        from wolf.backend.cadence_genus import genus_run_step_events
        self.assertEqual(genus_run_step_events(self.run_directory), {})

    def test_parses_real_shaped_lines(self):
        from wolf.backend.cadence_genus import genus_run_step_events
        self._write_events(
            "block_start|starting|1700000000\n"
            "block_start|success|1700000001\n"
            "init_genus|starting|1700000002\n"
        )
        events = genus_run_step_events(self.run_directory)
        self.assertEqual(events, {
            "block_start": ("complete", 1700000001.0), "init_genus": ("running", 1700000002.0),
        })

    def test_a_later_line_for_the_same_name_overwrites_an_earlier_one(self):
        from wolf.backend.cadence_genus import genus_run_step_events
        self._write_events("block_start|starting|1\nblock_start|failed|2\n")
        self.assertEqual(genus_run_step_events(self.run_directory)["block_start"], ("failed", 2.0))

    def test_an_unparseable_line_is_skipped_not_an_error(self):
        from wolf.backend.cadence_genus import genus_run_step_events
        self._write_events("not a real line\nblock_start|success|1\n")
        self.assertEqual(genus_run_step_events(self.run_directory), {"block_start": ("complete", 1.0)})


class GenusRunActiveElapsedTests(unittest.TestCase):
    """genus_run_active_elapsed derives how long the current flowtool
    invocation has actually been running from wolf.step-status's own
    earliest timestamp -- real wall-clock time since the first real
    step of this invocation started, independent of flow.metrics'
    total_real_seconds (confirmed, like flow.status, not promptly
    updated during a manually-typed run_flow)."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-active-elapsed-")
        self.root = Path(self.temporary.name)
        self.run_directory = self.root / "work" / "demo.1"
        self.run_directory.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def test_no_file_yet_returns_none(self):
        from wolf.backend.cadence_genus import genus_run_active_elapsed
        self.assertIsNone(genus_run_active_elapsed(self.run_directory))

    def test_empty_file_returns_none(self):
        from wolf.backend.cadence_genus import genus_run_active_elapsed
        (self.run_directory / "wolf.step-status").write_text("", encoding="utf-8")
        self.assertIsNone(genus_run_active_elapsed(self.run_directory))

    def test_elapsed_is_measured_from_the_earliest_timestamp(self):
        from wolf.backend.cadence_genus import genus_run_active_elapsed
        import time as time_module
        now = time_module.time()
        (self.run_directory / "wolf.step-status").write_text(
            f"block_start|starting|{now - 100}\n"
            f"block_start|success|{now - 95}\n"
            f"init_genus|starting|{now - 10}\n",
            encoding="utf-8",
        )
        elapsed = genus_run_active_elapsed(self.run_directory)
        self.assertIsNotNone(elapsed)
        self.assertAlmostEqual(elapsed, 100, delta=2)


class GenusRunStepElapsedTests(unittest.TestCase):
    """genus_run_step_elapsed derives each step's own real duration
    (or how long a still-running one has been running) from
    wolf.step-status's own starting/terminal timestamp pairs -- a
    completed step's own real duration, not just "is it running"."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-step-elapsed-")
        self.root = Path(self.temporary.name)
        self.run_directory = self.root / "work" / "demo.1"
        self.run_directory.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def _write(self, text: str) -> None:
        (self.run_directory / "wolf.step-status").write_text(text, encoding="utf-8")

    def test_no_file_yet_returns_empty(self):
        from wolf.backend.cadence_genus import genus_run_step_elapsed
        self.assertEqual(genus_run_step_elapsed(self.run_directory), {})

    def test_a_completed_steps_own_duration_is_success_minus_starting(self):
        from wolf.backend.cadence_genus import genus_run_step_elapsed
        self._write("block_start|starting|100|block.synthesis.syn_map.block_start\n"
                     "block_start|success|137|block.synthesis.syn_map.block_start\n")
        elapsed = genus_run_step_elapsed(self.run_directory)
        self.assertEqual(elapsed["block.synthesis.syn_map.block_start"], 37.0)

    def test_a_zero_second_duration_is_a_real_value_not_missing(self):
        from wolf.backend.cadence_genus import genus_run_step_elapsed
        self._write("block_start|starting|100|block.synthesis.syn_map.block_start\n"
                     "block_start|success|100|block.synthesis.syn_map.block_start\n")
        elapsed = genus_run_step_elapsed(self.run_directory)
        self.assertEqual(elapsed["block.synthesis.syn_map.block_start"], 0.0)

    def test_a_still_running_steps_own_elapsed_is_now_minus_starting(self):
        from wolf.backend.cadence_genus import genus_run_step_elapsed
        import time as time_module
        self._write(f"run_syn_map|starting|{time_module.time() - 42}|"
                     "block.synthesis.syn_map.run_syn_map\n")
        elapsed = genus_run_step_elapsed(self.run_directory)
        self.assertAlmostEqual(elapsed["block.synthesis.syn_map.run_syn_map"], 42, delta=2)

    def test_a_terminal_record_with_no_starting_record_is_left_out(self):
        from wolf.backend.cadence_genus import genus_run_step_elapsed
        self._write("block_start|success|137|block.synthesis.syn_map.block_start\n")
        self.assertEqual(genus_run_step_elapsed(self.run_directory), {})

    def test_an_older_format_line_with_no_path_keys_by_bare_name(self):
        from wolf.backend.cadence_genus import genus_run_step_elapsed
        self._write("block_start|starting|100\nblock_start|success|137\n")
        elapsed = genus_run_step_elapsed(self.run_directory)
        self.assertEqual(elapsed["block_start"], 37.0)


class GenusRunStatusElapsedTests(unittest.TestCase):
    """genus_run_status_elapsed is genus_run_step_elapsed's own sibling,
    sourced from flow.status instead -- the same real starting/terminal
    timestamp pairs Flowtool itself writes per canonical path."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-flow-status-elapsed-")
        self.root = Path(self.temporary.name)
        self.run_directory = self.root / "work" / "demo.1"
        self.run_directory.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def _write(self, text: str) -> None:
        (self.run_directory / "flow.status").write_text(text, encoding="utf-8")

    def test_no_file_yet_returns_empty(self):
        from wolf.backend.cadence_genus import genus_run_status_elapsed
        self.assertEqual(genus_run_status_elapsed(self.run_directory), {})

    def test_a_completed_steps_own_duration_is_success_minus_starting(self):
        from wolf.backend.cadence_genus import genus_run_status_elapsed
        self._write(
            "{status starting time 1700000000 errors {} "
            "steps_run {str block.synthesis.syn_generic.block_start}}\n"
            "{status success time 1700000037 errors {} "
            "steps_run {str block.synthesis.syn_generic.block_start}}\n"
        )
        elapsed = genus_run_status_elapsed(self.run_directory)
        self.assertEqual(elapsed["block.synthesis.syn_generic.block_start"], 37.0)

    def test_a_still_running_steps_own_elapsed_is_now_minus_starting(self):
        from wolf.backend.cadence_genus import genus_run_status_elapsed
        import time as time_module
        self._write(
            f"{{status starting time {time_module.time() - 42} errors {{}} "
            "steps_run {str block.synthesis.syn_generic.block_start}}\n"
        )
        elapsed = genus_run_status_elapsed(self.run_directory)
        self.assertAlmostEqual(elapsed["block.synthesis.syn_generic.block_start"], 42, delta=2)

    def test_invocation_boundary_marker_lines_do_not_interfere(self):
        from wolf.backend.cadence_genus import genus_run_status_elapsed
        self._write(
            "{status starting time 1700000000 errors {} "
            "steps_run {str block.synthesis.syn_generic.block_start}}\n"
            "{script flowtool status invoked arguments {-status}}\n"
            "{status success time 1700000037 errors {} "
            "steps_run {str block.synthesis.syn_generic.block_start}}\n"
        )
        elapsed = genus_run_status_elapsed(self.run_directory)
        self.assertEqual(elapsed["block.synthesis.syn_generic.block_start"], 37.0)


class GenusRunStatusTests(unittest.TestCase):
    """genus_run_status reads Flowtool's own real per-run execution
    record directly off disk (<run_directory>/flow.status) -- a plain
    file read, no flowtool subprocess invocation at all."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-status-")
        self.root = Path(self.temporary.name)
        self.run_directory = self.root / "work" / "demo.1"
        self.run_directory.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def _write_status(self, text: str) -> None:
        (self.run_directory / "flow.status").write_text(text, encoding="utf-8")

    def test_no_flow_status_on_disk_yet_returns_empty(self):
        from wolf.backend.cadence_genus import genus_run_status
        raw, states = genus_run_status(self.run_directory)
        self.assertEqual((raw, states), ("", {}))

    def test_invocation_boundary_marker_lines_are_skipped(self):
        from wolf.backend.cadence_genus import genus_run_status
        self._write_status("{script flowtool status invoked arguments {-status}}\n")
        raw, states = genus_run_status(self.run_directory)
        self.assertEqual(states, {})
        self.assertIn("invoked", raw)

    def test_parses_real_shaped_lines_into_canonical_path_states(self):
        from wolf.backend.cadence_genus import genus_run_status
        self._write_status(
            "{status success time 1700000000 errors {} "
            "steps_run {str block.synthesis.syn_generic.block_start}}\n"
            "{status starting time 1700000001 errors {} "
            "steps_run {str block.synthesis.syn_generic.read_hdl}}\n"
            "{status success time 1700000002 errors {bad thing} "
            "steps_run {str block.synthesis.syn_generic.elaborate}}\n"
        )
        raw, states = genus_run_status(self.run_directory)
        self.assertEqual(states, {
            "block.synthesis.syn_generic.block_start": "complete",
            "block.synthesis.syn_generic.read_hdl": "running",
            # A populated errors list overrides a literal "success" status word.
            "block.synthesis.syn_generic.elaborate": "failed",
        })
        self.assertIn("block_start", raw)

    def test_a_later_record_for_the_same_path_overwrites_an_earlier_one(self):
        from wolf.backend.cadence_genus import genus_run_status
        self._write_status(
            "{status starting time 1700000000 errors {} "
            "steps_run {str block.synthesis.syn_generic.block_start}}\n"
            "{status success time 1700000001 errors {} "
            "steps_run {str block.synthesis.syn_generic.block_start}}\n"
        )
        _, states = genus_run_status(self.run_directory)
        self.assertEqual(states["block.synthesis.syn_generic.block_start"], "complete")

    def test_a_line_with_no_steps_run_or_status_is_skipped_not_an_error(self):
        from wolf.backend.cadence_genus import genus_run_status
        self._write_status("{time 1700000000 remarks {nothing useful here}}\n")
        raw, states = genus_run_status(self.run_directory)
        self.assertEqual(states, {})
        self.assertIn("nothing useful here", raw)

    def test_a_fresh_invocation_demotes_a_stale_failure_for_its_own_stage_range(self):
        """Regression, hit for real: block_start failed because of a now-
        fixed WOLF bug (report_flow being called too early); after the
        fix, flowtool was re-invoked for -from syn_map -to syn_map (an
        interactive session still sitting at the prompt, nothing logged
        yet for block_start under the new attempt) -- must read as
        "running", not stuck showing the old attempt's "failed"."""
        from wolf.backend.cadence_genus import genus_run_status
        self._write_status(
            "{status error time 1700000000 errors {} "
            "steps_run {str block.synthesis.syn_map.block_start}}\n"
            "{script flowtool status invoked arguments "
            "{-from syn_map -to syn_map -interactive}}\n"
        )
        _, states = genus_run_status(self.run_directory)
        self.assertEqual(states["block.synthesis.syn_map.block_start"], "running")

    def test_a_stale_failure_outside_the_fresh_invocations_own_range_is_left_alone(self):
        """The demotion is scoped to the new invocation's own -from/-to
        stage range -- an unrelated stage's real failure elsewhere must
        not be masked just because some other stage was re-invoked."""
        from wolf.backend.cadence_genus import genus_run_status
        self._write_status(
            "{status error time 1700000000 errors {} "
            "steps_run {str block.synthesis.syn_generic.block_start}}\n"
            "{script flowtool status invoked arguments "
            "{-from syn_map -to syn_map -interactive}}\n"
        )
        _, states = genus_run_status(self.run_directory)
        self.assertEqual(states["block.synthesis.syn_generic.block_start"], "failed")

    def test_a_failure_logged_after_the_fresh_invocation_is_not_demoted(self):
        """If the new attempt itself goes on to fail again for real
        (a fresh failure record logged after the invocation marker),
        that must stand -- the demotion only ever fills a gap where
        nothing fresher has been reported yet."""
        from wolf.backend.cadence_genus import genus_run_status
        self._write_status(
            "{script flowtool status invoked arguments "
            "{-from syn_map -to syn_map -interactive}}\n"
            "{status error time 1700000001 errors {} "
            "steps_run {str block.synthesis.syn_map.block_start}}\n"
        )
        _, states = genus_run_status(self.run_directory)
        self.assertEqual(states["block.synthesis.syn_map.block_start"], "failed")

    def _write_events(self, text: str) -> None:
        (self.run_directory / "wolf.step-status").write_text(text, encoding="utf-8")

    def test_a_live_event_promotes_a_path_flow_status_never_mentioned_at_all(self):
        """Regression, hit for real continuing past syn_map into
        syn_opt: flow.status had logged NOTHING for syn_opt yet (not
        even a stale failure to demote), but wolf.step-status already
        showed real progress -- must read as "running", not stay
        absent (which load_status renders as "unknown")."""
        from wolf.backend.cadence_genus import genus_run_status
        self._write_status(
            "{script flowtool status invoked arguments "
            "{-from syn_opt -to syn_opt -interactive}}\n"
        )
        self._write_events("block_start|starting|1700000500\n")
        _, states = genus_run_status(self.run_directory)
        self.assertEqual(states["block.synthesis.syn_opt.block_start"], "running")

    def test_the_live_event_promotion_does_not_bleed_into_an_unrelated_stage(self):
        """Regression: block_start is shared by syn_generic/syn_map/
        syn_opt (and the Innovus stages too) -- promoting it live for
        the ACTIVE invocation's own stage must not also mark every
        OTHER stage that happens to share the same bare step name as
        "running"."""
        from wolf.backend.cadence_genus import genus_run_status
        self._write_status(
            "{script flowtool status invoked arguments "
            "{-from syn_opt -to syn_opt -interactive}}\n"
        )
        self._write_events("block_start|starting|1700000500\n")
        _, states = genus_run_status(self.run_directory)
        self.assertNotIn("block.synthesis.syn_generic.block_start", states)
        self.assertNotIn("block.implementation.floorplan.block_start", states)

    def test_a_canonical_path_keyed_event_does_not_bleed_into_an_unrelated_occurrence(self):
        """Regression, hit for real continuing into syn_opt: init_genus
        is both a direct syn_opt member AND one of report_synth's own
        nested leaf steps -- a wolf.step-status line carrying its own
        canonical path (presentation.tcl's wolf_step_canonical_path)
        must be matched by that exact path, not the shared bare name,
        so syn_opt's own direct init_genus completing does not also
        mark report_synth's own unrelated, not-yet-started nested
        init_genus as complete."""
        from wolf.backend.cadence_genus import genus_run_status
        self._write_status(
            "{script flowtool status invoked arguments "
            "{-from syn_opt -to syn_opt -interactive}}\n"
        )
        self._write_events(
            "init_genus|success|1700000500|block.synthesis.syn_opt.init_genus\n"
        )
        _, states = genus_run_status(self.run_directory)
        self.assertEqual(states["block.synthesis.syn_opt.init_genus"], "complete")
        self.assertNotIn("block.synthesis.syn_opt.report_synth.init_genus", states)

    def test_a_live_event_outside_the_active_invocations_range_is_ignored(self):
        """wolf.step-status is truncated per invocation, so this
        shouldn't happen in practice, but the scoping must still hold:
        a live event for run_syn_opt (a step name unique to syn_opt)
        is not applied when the active invocation's own range is
        syn_generic only."""
        from wolf.backend.cadence_genus import genus_run_status
        self._write_status(
            "{script flowtool status invoked arguments "
            "{-from syn_generic -to syn_generic -interactive}}\n"
        )
        self._write_events("run_syn_opt|starting|1700000500\n")
        _, states = genus_run_status(self.run_directory)
        self.assertNotIn("block.synthesis.syn_opt.run_syn_opt", states)


class RollupStageStatesTests(unittest.TestCase):
    """rollup_stage_states fills in a STAGE_ORDER-level state from the
    real canonical-dotted-path-keyed detail genus_run_status reads out
    of flow.status, via stage_canonical_paths (the real create_flow
    membership tree, qualified by stage -- not a guess)."""

    def test_an_explicit_stage_level_hit_is_left_as_is(self):
        from wolf.backend.cadence_genus import rollup_stage_states
        result = rollup_stage_states({"syn_generic": "complete"}, stages=("syn_generic",))
        self.assertEqual(result["syn_generic"], "complete")

    def test_step_level_detail_alone_rolls_up_to_complete(self):
        """Every real syn_generic canonical path reporting complete, but
        no line for "syn_generic" itself -- must still roll up to
        complete."""
        from wolf.backend.cadence_genus import rollup_stage_states, stage_canonical_paths
        paths = stage_canonical_paths("syn_generic")
        states = {path: "complete" for path in paths}
        result = rollup_stage_states(states, stages=("syn_generic",))
        self.assertEqual(result["syn_generic"], "complete")

    def test_partially_complete_steps_roll_up_to_running_not_pending(self):
        from wolf.backend.cadence_genus import rollup_stage_states, stage_canonical_paths
        paths = stage_canonical_paths("syn_generic")
        states = {paths[0]: "complete", paths[1]: "pending"}
        result = rollup_stage_states(states, stages=("syn_generic",))
        self.assertEqual(result["syn_generic"], "running")

    def test_any_failed_step_rolls_up_to_failed(self):
        from wolf.backend.cadence_genus import rollup_stage_states, stage_canonical_paths
        paths = stage_canonical_paths("syn_generic")
        states = {paths[0]: "complete", paths[1]: "failed"}
        result = rollup_stage_states(states, stages=("syn_generic",))
        self.assertEqual(result["syn_generic"], "failed")

    def test_no_recognized_steps_at_all_leaves_the_stage_absent(self):
        from wolf.backend.cadence_genus import rollup_stage_states
        result = rollup_stage_states({}, stages=("syn_generic",))
        self.assertNotIn("syn_generic", result)

    def test_a_shared_step_name_alone_does_not_falsely_complete_other_stages(self):
        """Regression: block_start is a real create_flow_step shared by
        syn_generic, syn_map, AND syn_opt -- but flow.status
        disambiguates which stage actually ran it via the qualified
        canonical path (block.synthesis.syn_generic.block_start isn't
        block.synthesis.syn_map.block_start). One stage's own
        block_start reporting complete must not roll up an unrelated
        stage's distinct block_start occurrence."""
        from wolf.backend.cadence_genus import rollup_stage_states, stage_canonical_paths
        result = rollup_stage_states(
            {stage_canonical_paths("syn_generic")[0]: "complete"},
            stages=("syn_generic", "syn_map", "syn_opt"),
        )
        self.assertEqual(result["syn_generic"], "running")
        self.assertNotIn("syn_map", result)
        self.assertNotIn("syn_opt", result)

    def test_original_step_level_entries_are_preserved_alongside_the_rollup(self):
        from wolf.backend.cadence_genus import rollup_stage_states, stage_canonical_paths
        paths = stage_canonical_paths("syn_generic")
        states = {paths[0]: "complete"}
        result = rollup_stage_states(states, stages=("syn_generic",))
        self.assertEqual(result[paths[0]], "complete")


class StageCanonicalPathsTests(unittest.TestCase):
    """stage_canonical_paths computes the real dotted path flow.status
    itself uses for each STAGE_ORDER name's descendants, keeping every
    intermediate flow name (block, synthesis/implementation, the stage,
    and any further nested sub-flow) as its own path segment -- unlike
    flow_descendant_steps, which flattens those away."""

    def test_synthesis_stages_are_qualified_under_block_synthesis(self):
        from wolf.backend.cadence_genus import stage_canonical_paths
        paths = stage_canonical_paths("syn_generic")
        self.assertIn("block.synthesis.syn_generic.block_start", paths)

    def test_implementation_stages_are_qualified_under_block_implementation(self):
        from wolf.backend.cadence_genus import stage_canonical_paths
        paths = stage_canonical_paths("floorplan")
        self.assertIn("block.implementation.floorplan.block_start", paths)

    def test_a_nested_sub_flow_keeps_its_own_name_as_a_path_segment(self):
        """report_synth is itself a nested flow referenced by
        syn_generic, not a leaf step -- its own members must appear
        qualified by report_synth, not flattened straight onto
        syn_generic (matching real observed flow.status output, e.g.
        block.synthesis.syn_generic.report_synth.report_finish)."""
        from wolf.backend.cadence_genus import stage_canonical_paths
        paths = stage_canonical_paths("syn_generic")
        self.assertIn("block.synthesis.syn_generic.report_synth.report_finish", paths)

    def test_a_shared_leaf_step_is_qualified_differently_per_stage(self):
        from wolf.backend.cadence_genus import stage_canonical_paths
        generic_paths = stage_canonical_paths("syn_generic")
        map_paths = stage_canonical_paths("syn_map")
        self.assertIn("block.synthesis.syn_generic.block_start", generic_paths)
        self.assertIn("block.synthesis.syn_map.block_start", map_paths)
        self.assertNotIn("block.synthesis.syn_map.block_start", generic_paths)

    def test_canonical_paths_keep_a_step_reused_at_two_positions_within_one_stage_distinct(self):
        """Regression: syn_generic's own member list lists init_genus
        directly AND report_synth (nested) lists init_genus again --
        flow_descendant_steps' flattening collapses that to one entry
        (its `seen` set treats the second occurrence as a duplicate of
        the first), undercounting by one real invocation.
        stage_canonical_paths must not make that same mistake: the two
        occurrences sit at different structural positions
        (block.synthesis.syn_generic.init_genus vs.
        block.synthesis.syn_generic.report_synth.init_genus) and must
        both be kept, one more path than flow_descendant_steps' own
        flattened, deduplicated count."""
        from wolf.backend.cadence_genus import flow_descendant_steps, stage_canonical_paths
        paths = stage_canonical_paths("syn_generic")
        self.assertIn("block.synthesis.syn_generic.init_genus", paths)
        self.assertIn("block.synthesis.syn_generic.report_synth.init_genus", paths)
        self.assertEqual(len(paths), len(flow_descendant_steps("syn_generic")) + 1)


class StageStepDetailTests(unittest.TestCase):
    """stage_step_detail is wolf status --watch's own real backend-local
    hook for its expanded live view of whichever stage is currently
    running -- one level of a stage's own direct create_flow members,
    each paired with its current rolled-up state."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-detail-")
        self.root = Path(self.temporary.name)
        self.run_directory = self.root / "work" / "demo.1"
        self.run_directory.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def _write_status(self, text: str) -> None:
        (self.run_directory / "flow.status").write_text(text, encoding="utf-8")

    def test_unrecognized_stage_name_returns_empty(self):
        from wolf.backend.cadence_genus import stage_step_detail
        self.assertEqual(stage_step_detail(self.run_directory, "not-a-real-stage"), ())

    @staticmethod
    def _states(detail):
        return {label: state for label, state, _ in detail}

    @staticmethod
    def _elapsed(detail):
        return {label: elapsed for label, _, elapsed in detail}

    def test_no_flow_status_yet_reports_every_member_pending(self):
        from wolf.backend.cadence_genus import flow_membership, stage_step_detail
        detail = stage_step_detail(self.run_directory, "syn_map")
        self.assertEqual(
            [label for label, _, _ in detail], list(flow_membership()["syn_map"]),
        )
        self.assertTrue(all(state == "pending" for _, state, _ in detail))
        self.assertTrue(all(elapsed is None for _, _, elapsed in detail))

    def test_a_running_leaf_member_is_reported_directly(self):
        from wolf.backend.cadence_genus import stage_step_detail
        self._write_status(
            "{status starting time 1700000000 errors {} "
            "steps_run {str block.synthesis.syn_map.block_start}}\n"
        )
        detail = self._states(stage_step_detail(self.run_directory, "syn_map"))
        self.assertEqual(detail["block_start"], "running")
        self.assertEqual(detail["init_genus"], "pending")

    def test_a_nested_sub_flow_member_rolls_up_its_own_leaf_descendants(self):
        """report_synth is itself a nested flow inside syn_map, not a
        leaf -- its own reported state must be the same rollup
        rollup_stage_states uses for a whole STAGE_ORDER name:
        "complete" only once every one of its own real leaf descendants
        is accounted for, here just one ("report_start") out of nine."""
        from wolf.backend.cadence_genus import stage_step_detail
        self._write_status(
            "{status success time 1700000000 errors {} "
            "steps_run {str block.synthesis.syn_map.report_synth.report_start}}\n"
        )
        detail = self._states(stage_step_detail(self.run_directory, "syn_map"))
        self.assertEqual(detail["report_synth"], "running")

    def _write_events(self, text: str) -> None:
        (self.run_directory / "wolf.step-status").write_text(text, encoding="utf-8")

    def test_a_live_wolf_step_status_event_overrides_a_stale_flow_status_entry(self):
        """Regression, hit for real: flow.status sat unchanged for over
        an hour while a manually-typed `run_flow` visibly progressed
        past block_start -- wolf.step-status's own live event for the
        same bare step name must win."""
        from wolf.backend.cadence_genus import stage_step_detail
        self._write_status(
            "{status error time 1700000000 errors {} "
            "steps_run {str block.synthesis.syn_map.block_start}}\n"
        )
        self._write_events("block_start|success|1700000500\n")
        detail = self._states(stage_step_detail(self.run_directory, "syn_map"))
        self.assertEqual(detail["block_start"], "complete")

    def test_a_live_event_for_a_nested_sub_flows_own_leaf_also_overrides(self):
        """The live overlay must reach a nested sub-flow's own leaf
        descendants too (report_synth's own init_genus), not just a
        stage's direct members -- real progress through report_synth
        during a manually-typed run_flow must still show up."""
        from wolf.backend.cadence_genus import stage_step_detail
        self._write_events("init_genus|success|1700000500\n")
        detail = self._states(stage_step_detail(self.run_directory, "syn_map"))
        self.assertEqual(detail["report_synth"], "running")

    def test_no_live_event_for_a_member_falls_back_to_flow_status(self):
        from wolf.backend.cadence_genus import stage_step_detail
        self._write_status(
            "{status success time 1700000000 errors {} "
            "steps_run {str block.synthesis.syn_map.block_start}}\n"
        )
        self._write_events("init_genus|starting|1700000500\n")
        detail = self._states(stage_step_detail(self.run_directory, "syn_map"))
        self.assertEqual(detail["block_start"], "complete")
        self.assertEqual(detail["init_genus"], "running")

    def test_a_canonical_path_keyed_event_does_not_bleed_into_an_unrelated_occurrence(self):
        """Regression, hit for real continuing into syn_opt: init_genus
        is both a direct syn_opt member AND one of report_synth's own
        nested leaf steps. syn_opt's own direct init_genus completing
        must not falsely mark report_synth's own unrelated, not-yet-
        started nested init_genus as complete too (which would in turn
        make report_synth's own rollup show "running" from one false
        partial match) -- the real fix: a wolf.step-status line that
        carries its own canonical path (presentation.tcl's
        wolf_step_canonical_path) is matched by that exact path, not
        the shared bare name."""
        from wolf.backend.cadence_genus import stage_step_detail
        self._write_events(
            "init_genus|starting|1700000000|block.synthesis.syn_opt.init_genus\n"
            "init_genus|success|1700000001|block.synthesis.syn_opt.init_genus\n"
        )
        detail = self._states(stage_step_detail(self.run_directory, "syn_opt"))
        self.assertEqual(detail["init_genus"], "complete")
        self.assertEqual(detail["report_synth"], "pending")

    def test_a_canonical_path_keyed_event_still_reaches_its_own_real_occurrence(self):
        """The same init_genus event, this time genuinely logged for
        report_synth's own nested occurrence, must still be picked up
        there."""
        from wolf.backend.cadence_genus import stage_step_detail
        self._write_events(
            "init_genus|starting|1700000000|block.synthesis.syn_opt.report_synth.init_genus\n"
        )
        detail = self._states(stage_step_detail(self.run_directory, "syn_opt"))
        self.assertEqual(detail["report_synth"], "running")

    def test_an_older_format_line_with_no_path_still_falls_back_to_bare_name(self):
        """A session still running the previous presentation.tcl (no
        canonical path recorded yet) must keep working exactly as
        before -- same bare-name-matching behavior, not a hard
        requirement that every line carry a path."""
        from wolf.backend.cadence_genus import stage_step_detail
        self._write_events("init_genus|success|1700000000\n")
        detail = self._states(stage_step_detail(self.run_directory, "syn_opt"))
        self.assertEqual(detail["init_genus"], "complete")
        # The old, ambiguous bare-name behavior still bleeds into the
        # nested occurrence too -- an accepted limitation of the
        # fallback path, not a regression (this is exactly the
        # previously-known behavior, unchanged for old-format data).
        self.assertEqual(detail["report_synth"], "running")

    def test_a_running_leaf_members_own_elapsed_is_derived_from_its_live_timestamp(self):
        from wolf.backend.cadence_genus import stage_step_detail
        import time as time_module
        self._write_events(f"block_start|starting|{time_module.time() - 42}\n")
        elapsed = self._elapsed(stage_step_detail(self.run_directory, "syn_map"))
        self.assertIsNotNone(elapsed["block_start"])
        self.assertAlmostEqual(elapsed["block_start"], 42, delta=2)
        # Every other member (not running, or running with no live
        # timestamp) has no elapsed of its own.
        self.assertIsNone(elapsed["init_genus"])

    def test_a_nested_sub_flows_own_aggregate_row_never_gets_an_elapsed(self):
        """There is no single real "start" for a nested sub-flow's own
        aggregate state the way there is for one real leaf step."""
        from wolf.backend.cadence_genus import stage_step_detail
        import time as time_module
        self._write_events(f"report_start|starting|{time_module.time() - 5}\n")
        elapsed = self._elapsed(stage_step_detail(self.run_directory, "syn_map"))
        self.assertIsNone(elapsed["report_synth"])

    def test_a_stage_level_running_state_from_flow_status_alone_still_gets_a_live_elapsed(self):
        """flow.status's own "starting" record carries a real
        timestamp too -- genus_run_status_elapsed derives "now - that
        timestamp" from it, same as wolf.step-status would, so a step
        running per flow.status alone (no wolf.step-status entry at
        all) still shows a live elapsed, not an absent one."""
        from wolf.backend.cadence_genus import stage_step_detail
        import time as time_module
        self._write_status(
            f"{{status starting time {time_module.time() - 42} errors {{}} "
            "steps_run {str block.synthesis.syn_map.block_start}}\n"
        )
        elapsed = self._elapsed(stage_step_detail(self.run_directory, "syn_map"))
        self.assertIsNotNone(elapsed["block_start"])
        self.assertAlmostEqual(elapsed["block_start"], 42, delta=2)

    def test_a_completed_steps_own_real_duration_comes_from_flow_status(self):
        """A step that finished entirely under flow.status's own
        prompt bookkeeping (no wolf.step-status involved at all) still
        gets its own real duration, from flow.status's own starting
        and success timestamps for the same canonical path."""
        from wolf.backend.cadence_genus import stage_step_detail
        self._write_status(
            "{status starting time 1700000000 errors {} "
            "steps_run {str block.synthesis.syn_map.block_start}}\n"
            "{status success time 1700000037 errors {} "
            "steps_run {str block.synthesis.syn_map.block_start}}\n"
        )
        elapsed = self._elapsed(stage_step_detail(self.run_directory, "syn_map"))
        self.assertEqual(elapsed["block_start"], 37.0)


class CadenceFlowtoolBackendStatusTests(unittest.TestCase):
    def test_stages_returns_the_real_stage_order(self):
        from wolf.backend.cadence_flowtool import CadenceFlowtoolBackend
        from wolf.backend.cadence_genus import STAGE_ORDER
        self.assertEqual(tuple(CadenceFlowtoolBackend().stages()), STAGE_ORDER)

    def test_infer_stage_results_delegates_to_genus_run_status(self):
        from wolf.backend.cadence_flowtool import CadenceFlowtoolBackend
        with patch(
            "wolf.backend.cadence_flowtool.genus_run_status",
            return_value=("raw text", {"syn_generic": "complete"}),
        ) as mocked:
            result = CadenceFlowtoolBackend().infer_stage_results("/some/run/dir")
        mocked.assert_called_once()
        self.assertEqual(result, {"syn_generic": "complete"})

    def test_extract_metrics_delegates_to_genus_run_metrics(self):
        from wolf.backend.cadence_flowtool import CadenceFlowtoolBackend
        with patch(
            "wolf.backend.cadence_flowtool.genus_run_metrics",
            return_value={"cadence.total_real_seconds": 12.0},
        ) as mocked:
            result = CadenceFlowtoolBackend().extract_metrics("/some/run/dir")
        mocked.assert_called_once()
        self.assertEqual(result, {"cadence.total_real_seconds": 12.0})


class GenusRunMetricsTests(unittest.TestCase):
    """genus_run_metrics reads Flowtool's own real per-run flow.metrics
    JSON directly off disk -- confirmed real shape against an actual
    run: a top-level "metrics" list for the current in-progress
    snapshot (including flowtool's own free-text "flowtool.status"
    summary), total_real/total_cpu for the whole flow's cumulative
    time so far, and one "snapshots" entry per completed child stage."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-metrics-")
        self.root = Path(self.temporary.name)
        self.run_directory = self.root / "work" / "demo.1"
        self.run_directory.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def _write_metrics(self, data) -> None:
        (self.run_directory / "flow.metrics").write_text(json.dumps(data), encoding="utf-8")

    def test_no_flow_metrics_on_disk_yet_returns_empty(self):
        from wolf.backend.cadence_genus import genus_run_metrics
        self.assertEqual(genus_run_metrics(self.run_directory), {})

    def test_malformed_json_degrades_to_empty_not_an_error(self):
        from wolf.backend.cadence_genus import genus_run_metrics
        (self.run_directory / "flow.metrics").write_text("not json", encoding="utf-8")
        self.assertEqual(genus_run_metrics(self.run_directory), {})

    def test_real_shaped_file_is_parsed_into_flat_metrics_and_stage_elapsed(self):
        from wolf.backend.cadence_genus import genus_run_metrics
        self._write_metrics({
            "total_real": 39735.0,
            "total_cpu": 229818.0,
            "metrics": [
                {"name": "flow.memory.resident", "value": "39197 MB"},
                {"name": "flow.memory.resident.peak", "value": "60845 MB"},
                {
                    "name": "flowtool.status",
                    "value": "Running flows... (1 running)\n"
                             "* flow_current @ genus: block.synthesis.syn_map.block_start",
                },
            ],
            "snapshots": [
                {
                    "key": "flow:flow_current .steps flow:block .steps flow:synthesis "
                           ".steps flow:syn_generic",
                    "metrics": [{"name": "flow.realtime", "value": "39735"}],
                },
            ],
        })
        result = genus_run_metrics(self.run_directory)
        self.assertEqual(result["cadence.total_real_seconds"], 39735.0)
        self.assertEqual(result["cadence.total_cpu_seconds"], 229818.0)
        self.assertEqual(result["cadence.memory_resident_mb"], 39197.0)
        self.assertEqual(result["cadence.memory_resident_peak_mb"], 60845.0)
        self.assertIn("block.synthesis.syn_map.block_start", result["cadence.current_activity"])
        self.assertEqual(result["stage_elapsed_seconds"], {"syn_generic": 39735.0})

    def test_a_snapshot_key_not_ending_in_a_real_stage_name_is_ignored(self):
        from wolf.backend.cadence_genus import genus_run_metrics
        self._write_metrics({
            "snapshots": [
                {
                    "key": "flow:flow_current .steps flow:block .steps flow:synthesis "
                           ".steps flow:report_synth",
                    "metrics": [{"name": "flow.realtime", "value": "10"}],
                },
            ],
        })
        self.assertNotIn("stage_elapsed_seconds", genus_run_metrics(self.run_directory))

    def test_missing_memory_or_activity_fields_are_simply_left_out(self):
        from wolf.backend.cadence_genus import genus_run_metrics
        self._write_metrics({"total_real": 5.0})
        result = genus_run_metrics(self.run_directory)
        self.assertEqual(result, {"cadence.total_real_seconds": 5.0})


# Condensed but faithful to a real run's own area.syn_generic.rpt/
# timing.syn_generic.rpt/power.syn_generic.rpt (Genus 21.12-s068_1) --
# only the header boilerplate is trimmed, every data line kept verbatim.
_REAL_AREA_REPORT = """\
============================================================
  Generated by:           Genus(TM) Synthesis Solution 21.12-s068_1
  Interconnect mode:      global
  Area mode:              physical library
============================================================

                                 Instance                                                        Module                        Cell Count   Cell Area   Net Area    Total Area
-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
ESP_ASIC_TOP                                                                                                                      3286713 24485968.048    87.318  24486055.365
  fpga_data_pad                                                            iopadv                                                      64      224.651     0.000       224.651
    v[0].x0                                                                iopad_0_63                                                   1        3.510     0.000         3.510
"""

_REAL_TIMING_REPORT = """\
============================================================
  Generated by:           Genus(TM) Synthesis Solution 21.12-s068_1
============================================================

# SETUP                  WNS       TNS   FEP
# ---------------------------------------------
 View: ALL            -607.6  -34174.8    66
    Group : default   4449.5       0.0     0

# ---------------------------------------------
# DRV                        WNS  TNS  FEP
# -------------------------------------------
 View: ALL
    Check: max_transition    N/A  N/A    0
"""

_REAL_POWER_REPORT = """\
Instance: /ESP_ASIC_TOP
Power Unit: W
PDB Frames: /stim#0/frame#0
  -------------------------------------------------------------------------
    Category         Leakage     Internal    Switching        Total    Row%
  -------------------------------------------------------------------------
      memory     0.00000e+00  0.00000e+00  0.00000e+00  0.00000e+00   0.00%
    register     1.22039e-01  8.43733e-01  1.73996e-06  9.65773e-01  99.28%
  -------------------------------------------------------------------------
    Subtotal     1.26162e-01  8.46601e-01  1.89968e-05  9.72781e-01 100.00%
  Percentage          12.97%       87.03%        0.00%      100.00% 100.00%
  -------------------------------------------------------------------------
"""


class GenusQorReportParsersTests(unittest.TestCase):
    """_parse_area_report/_parse_timing_report/_parse_power_report
    against condensed-but-real Genus report text, confirmed real
    against an actual run (see docs/CADENCE_GENUS.md)."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-qor-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def _write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_area_report_reads_the_top_level_design_row_not_a_child(self):
        from wolf.backend.cadence_genus import _parse_area_report
        path = self._write("area.rpt", _REAL_AREA_REPORT)
        result = _parse_area_report(path)
        self.assertEqual(result, {
            "cell_count": 3286713.0, "cell_area_um2": 24485968.048,
            "net_area_um2": 87.318, "total_area_um2": 24486055.365,
        })

    def test_timing_report_reads_the_setup_view_all_row_not_the_empty_drv_one(self):
        from wolf.backend.cadence_genus import _parse_timing_report
        path = self._write("timing.rpt", _REAL_TIMING_REPORT)
        result = _parse_timing_report(path)
        self.assertEqual(result, {
            "worst_slack_ps": -607.6, "total_negative_slack_ps": -34174.8,
            "failing_endpoints": 66.0,
        })

    def test_power_report_reads_the_subtotal_row(self):
        from wolf.backend.cadence_genus import _parse_power_report
        path = self._write("power.rpt", _REAL_POWER_REPORT)
        result = _parse_power_report(path)
        self.assertEqual(result, {
            "leakage_w": 0.126162, "internal_w": 0.846601,
            "switching_w": 1.89968e-05, "total_w": 0.972781,
        })

    def test_a_report_missing_its_own_data_row_returns_none(self):
        from wolf.backend.cadence_genus import (
            _parse_area_report, _parse_power_report, _parse_timing_report,
        )
        empty = self._write("empty.rpt", "nothing useful here\n")
        self.assertIsNone(_parse_area_report(empty))
        self.assertIsNone(_parse_timing_report(empty))
        self.assertIsNone(_parse_power_report(empty))


class GenusRunQorTests(unittest.TestCase):
    """genus_run_qor scans <run_directory>/reports for every real
    area/timing/power.<stage>.rpt the synthesis stages have produced
    so far, mtime-cached per file since a report is Genus's own static
    snapshot, never rewritten once its own step finishes."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-genus-qor-run-")
        self.root = Path(self.temporary.name)
        self.run_directory = self.root / "work" / "demo.1"
        self.reports_directory = self.run_directory / "reports"
        self.reports_directory.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def test_no_reports_directory_yet_returns_empty(self):
        from wolf.backend.cadence_genus import genus_run_qor
        empty_run = self.root / "work" / "demo.2"
        empty_run.mkdir(parents=True)
        self.assertEqual(genus_run_qor(empty_run), {})

    def test_a_complete_stage_reports_all_three_kinds(self):
        from wolf.backend.cadence_genus import genus_run_qor
        (self.reports_directory / "area.syn_generic.rpt").write_text(_REAL_AREA_REPORT, encoding="utf-8")
        (self.reports_directory / "timing.syn_generic.rpt").write_text(_REAL_TIMING_REPORT, encoding="utf-8")
        (self.reports_directory / "power.syn_generic.rpt").write_text(_REAL_POWER_REPORT, encoding="utf-8")
        result = genus_run_qor(self.run_directory)
        self.assertEqual(set(result), {"syn_generic"})
        self.assertEqual(set(result["syn_generic"]), {"area", "timing", "power"})
        self.assertEqual(result["syn_generic"]["area"]["total_area_um2"], 24486055.365)

    def test_a_stage_with_only_some_report_kinds_shows_only_those(self):
        """report_synth hasn't finished writing every report yet --
        whatever exists is real and shown, the rest simply absent."""
        from wolf.backend.cadence_genus import genus_run_qor
        (self.reports_directory / "area.syn_map.rpt").write_text(_REAL_AREA_REPORT, encoding="utf-8")
        result = genus_run_qor(self.run_directory)
        self.assertEqual(set(result["syn_map"]), {"area"})

    def test_only_synthesis_stages_are_scanned_for_now(self):
        """Not yet scanning floorplan/route's own report files -- a
        later extension, not guessed ahead of real evidence (DRC/LVS
        reports don't exist until those stages actually run)."""
        from wolf.backend.cadence_genus import genus_run_qor
        (self.reports_directory / "area.floorplan.rpt").write_text(_REAL_AREA_REPORT, encoding="utf-8")
        self.assertEqual(genus_run_qor(self.run_directory), {})

    def test_a_reparsed_report_is_served_from_cache_until_its_mtime_changes(self):
        from wolf.backend.cadence_genus import genus_run_qor
        path = self.reports_directory / "area.syn_generic.rpt"
        path.write_text(_REAL_AREA_REPORT, encoding="utf-8")
        first = genus_run_qor(self.run_directory)
        # Rewritten with different content but the same mtime second --
        # forcing the mtime to actually change proves the cache is
        # keyed by it, not just "the path was seen before".
        import os
        import time as time_module
        new_report = _REAL_AREA_REPORT.replace("24486055.365", "1.000")
        path.write_text(new_report, encoding="utf-8")
        future = time_module.time() + 5
        os.utime(path, (future, future))
        second = genus_run_qor(self.run_directory)
        self.assertEqual(first["syn_generic"]["area"]["total_area_um2"], 24486055.365)
        self.assertEqual(second["syn_generic"]["area"]["total_area_um2"], 1.0)


class CadenceFlowtoolBackendQorTests(unittest.TestCase):
    def test_extract_metrics_includes_qor_by_stage_when_present(self):
        from wolf.backend.cadence_flowtool import CadenceFlowtoolBackend
        with patch(
            "wolf.backend.cadence_flowtool.genus_run_qor",
            return_value={"syn_generic": {"area": {"total_area_um2": 1.0}}},
        ), patch("wolf.backend.cadence_flowtool.genus_run_metrics", return_value={}), patch(
            "wolf.backend.cadence_flowtool.genus_run_active_elapsed", return_value=None,
        ):
            result = CadenceFlowtoolBackend().extract_metrics("/some/run/dir")
        self.assertEqual(result["cadence.qor_by_stage"], {"syn_generic": {"area": {"total_area_um2": 1.0}}})

    def test_extract_metrics_omits_qor_by_stage_when_empty(self):
        from wolf.backend.cadence_flowtool import CadenceFlowtoolBackend
        with patch("wolf.backend.cadence_flowtool.genus_run_qor", return_value={}), patch(
            "wolf.backend.cadence_flowtool.genus_run_metrics", return_value={},
        ), patch("wolf.backend.cadence_flowtool.genus_run_active_elapsed", return_value=None):
            result = CadenceFlowtoolBackend().extract_metrics("/some/run/dir")
        self.assertNotIn("cadence.qor_by_stage", result)


if __name__ == "__main__":
    unittest.main()

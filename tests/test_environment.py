import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from wolf.environment import load_environment, resolve_declarative_environment


class DeclarativeEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-environment-")
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.registry = self.root / "registry"
        self.environment = self.state / "envs" / "demo"
        self.environment.mkdir(parents=True)
        self.variables = patch.dict(
            os.environ,
            {"WOLF_HOME": str(self.state), "WOLF_REGISTRY": str(self.registry)},
        )
        self.variables.start()
        self._package("rtl", "ibex", "rtl-rev", {"design": {"name": "ibex", "top": "ibex_core"}})
        self._package("pdk", "asap7", "pdk-rev", {"technology": {"name": "asap7"}})
        self._package("flow", "orfs", "flow-rev", {"flow": {"name": "orfs", "backend": "orfs"}})

    def tearDown(self):
        self.variables.stop()
        self.temporary.cleanup()

    def _package(self, kind, name, revision, metadata):
        manifest = {
            "schema_version": 1,
            "kind": kind,
            "name": name,
            "description": name,
            "source": {"type": "git", "url": f"https://example.test/{name}", "revision": revision},
            "validation": {"required_paths": []},
            "metadata": metadata,
        }
        directory = self.registry / kind
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        installation = self.state / "packages" / kind / name / revision
        content = installation / "source"
        content.mkdir(parents=True)
        (installation / "installed.yaml").write_text(
            yaml.safe_dump({
                "package": f"{kind}/{name}",
                "revision": revision,
                "source_revision": revision,
                "content_path": "source",
                "installed_at": "2026-09-02T00:00:00Z",
            }),
            encoding="utf-8",
        )

    def _write(self, text, name="wolf.yaml"):
        path = self.environment / name
        path.write_text(text, encoding="utf-8")
        return path

    def _complete_yaml(self, extra=""):
        return f"""schema: wolf.environment/v1
name: demo
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
backend:
  orfs:
    make:
      SWAP_ARITH_OPERATORS: ""
      OPENROAD_HIERARCHICAL: 0
{extra}"""

    def test_parse_and_resolve_declarative_environment(self):
        profile = load_environment(self._write(self._complete_yaml()), expected_name="demo")
        context = resolve_declarative_environment(
            profile, state_root=self.state, environment_directory=self.environment
        )
        self.assertEqual(context.format, "declarative-v1")
        self.assertEqual((context.design_name, context.design_top), ("ibex", "ibex_core"))
        self.assertEqual((context.process, context.flow_name, context.backend), ("asap7", "orfs", "orfs"))
        self.assertEqual(context.workspace_root, self.environment / "work")
        self.assertEqual(context.clocks[0].period_ps, 1050)
        self.assertEqual(context.package_revisions["rtl/ibex"], "rtl-rev")
        self.assertEqual(context.backend_overrides["orfs"]["make"]["OPENROAD_HIERARCHICAL"], 0)

    def test_env_map_is_parsed_and_resolved_into_context(self):
        extra = "env:\n  GENUS_NUM_CPUS: \"64\"\n  SOME_FLAG: \"1\"\n"
        profile = load_environment(self._write(self._complete_yaml(extra)), expected_name="demo")
        context = resolve_declarative_environment(
            profile, state_root=self.state, environment_directory=self.environment
        )
        self.assertEqual(dict(context.env_vars), {"GENUS_NUM_CPUS": "64", "SOME_FLAG": "1"})

    def test_env_map_rejects_invalid_keys_and_non_string_values(self):
        cases = (
            ("env:\n  \"not valid\": \"1\"\n", "valid environment variable names"),
            ("env:\n  OK_KEY: 1\n", "must be a string"),
        )
        for index, (extra, message) in enumerate(cases):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    load_environment(self._write(self._complete_yaml(extra), f"bad-env-{index}.yaml"))

    def test_environment_values_override_package_defaults(self):
        text = self._complete_yaml().replace("  package: rtl/ibex\ntechnology:", "  package: rtl/ibex\n  name: renamed\n  top: custom_top\ntechnology:")
        context = resolve_declarative_environment(
            load_environment(self._write(text)),
            state_root=self.state,
            environment_directory=self.environment,
        )
        self.assertEqual((context.design_name, context.design_top), ("renamed", "custom_top"))

    def test_rejects_unsupported_schema_unknown_field_and_invalid_clock(self):
        cases = (
            ("schema: wolf.environment/v2\nname: demo\n", "unsupported"),
            ("schema: wolf.environment/v1\nname: demo\ndesgin: {}\n", "desgin"),
            (self._complete_yaml().replace("period_ps: 1050", "period_ps: 0"), "period_ps"),
        )
        for index, (text, message) in enumerate(cases):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                load_environment(self._write(text, f"bad-{index}.yaml"))

    def test_partial_environment_loads_but_cannot_resolve_a_run(self):
        profile = load_environment(self._write("""schema: wolf.environment/v1
name: demo
technology:
  package: pdk/asap7
flow:
  package: flow/orfs
"""))
        with self.assertRaisesRegex(ValueError, "unresolved required field: design, workspace.root"):
            resolve_declarative_environment(
                profile, state_root=self.state, environment_directory=self.environment
            )

    def test_cli_design_override_completes_partial_profile(self):
        profile = load_environment(self._write("""schema: wolf.environment/v1
name: demo
technology:
  package: pdk/asap7
flow:
  package: flow/orfs
workspace:
  root: work
"""))
        context = resolve_declarative_environment(
            profile,
            state_root=self.state,
            environment_directory=self.environment,
            design_override="rtl/ibex",
        )
        self.assertEqual(context.design_name, "ibex")

    def test_design_sources_list_mixes_package_and_local_path(self):
        local_dir = self.environment / "extra"
        local_dir.mkdir()
        local_file = local_dir / "foo.sv"
        local_file.write_text("module foo; endmodule\n", encoding="utf-8")
        text = """schema: wolf.environment/v1
name: demo
design:
  name: mixed
  top: foo
  sources:
    - package: rtl/ibex
    - path: extra/foo.sv
technology:
  package: pdk/asap7
flow:
  package: flow/orfs
workspace:
  root: ./work
"""
        context = resolve_declarative_environment(
            load_environment(self._write(text, "mixed.yaml")),
            state_root=self.state,
            environment_directory=self.environment,
        )
        self.assertEqual((context.design_name, context.design_top), ("mixed", "foo"))
        self.assertEqual(len(context.sources), 1)
        self.assertEqual(context.sources[0].language, "systemverilog")
        self.assertEqual(context.source_files, (local_file.resolve(),))
        self.assertEqual(context.package_revisions["rtl/ibex"], "rtl-rev")

    def test_design_sources_manifest_entry_resolves_a_local_manifest_toml_bundle(self):
        """A local manifest.toml (the same schema a published rtl package's
        own metadata.design.manifests.package already uses) sitting
        directly in the project tree, not wrapped in an installed
        package -- same ordering and FABULOUS_EFPGA/work library split a
        published package would get."""
        design_dir = self.environment / "inputs" / "hdl" / "mixed"
        manifests_dir = design_dir / "manifests"
        manifests_dir.mkdir(parents=True)
        for relative in ("pkg.vhd", "impl.vhd", "fab.v", "work.sv"):
            (design_dir / relative).write_text("-- fixture\n", encoding="utf-8")
        (manifests_dir / "vhdl-packages.flist").write_text("pkg.vhd\n", encoding="utf-8")
        (manifests_dir / "vhdl-sources.flist").write_text("impl.vhd\n", encoding="utf-8")
        (manifests_dir / "verilog-sources.flist").write_text("fab.v\nwork.sv\n", encoding="utf-8")
        (manifests_dir / "fabulous-verilog-sources.flist").write_text("fab.v\n", encoding="utf-8")
        (manifests_dir / "work-verilog-sources.flist").write_text("work.sv\n", encoding="utf-8")
        (design_dir / "manifest.toml").write_text(
            "\n".join([
                'schema_version = 1', 'name = "mixed-rtl"', 'top = "foo"',
                'vhdl_standard = "93"',
                'vhdl_packages = "manifests/vhdl-packages.flist"',
                'vhdl_sources = "manifests/vhdl-sources.flist"',
                'verilog_sources = "manifests/verilog-sources.flist"',
                'fabulous_library_sources = "manifests/fabulous-verilog-sources.flist"',
                'work_library_sources = "manifests/work-verilog-sources.flist"',
                "",
            ]),
            encoding="utf-8",
        )
        text = """schema: wolf.environment/v1
name: demo
design:
  name: mixed
  top: foo
  sources:
    - manifest: inputs/hdl/mixed/manifest.toml
technology:
  package: pdk/asap7
flow:
  package: flow/orfs
workspace:
  root: ./work
"""
        context = resolve_declarative_environment(
            load_environment(self._write(text, "manifest-bundle.yaml")),
            state_root=self.state,
            environment_directory=self.environment,
        )
        self.assertEqual([source.path.name for source in context.sources],
                          ["pkg.vhd", "impl.vhd", "fab.v", "work.sv"])
        self.assertEqual([source.language for source in context.sources],
                          ["vhdl", "vhdl", "verilog", "systemverilog"])
        self.assertEqual([source.library for source in context.sources],
                          ["work", "work", "FABULOUS_EFPGA", "work"])
        self.assertEqual(context.vhdl_standard, "93")

    def test_design_sources_manifest_entry_rejects_a_missing_manifest_toml(self):
        text = """schema: wolf.environment/v1
name: demo
design:
  name: mixed
  top: foo
  sources:
    - manifest: inputs/hdl/mixed/manifest.toml
technology:
  package: pdk/asap7
flow:
  package: flow/orfs
workspace:
  root: ./work
"""
        with self.assertRaisesRegex(ValueError, "does not exist"):
            resolve_declarative_environment(
                load_environment(self._write(text, "manifest-missing.yaml")),
                state_root=self.state,
                environment_directory=self.environment,
            )

    def test_design_sources_entry_requires_exactly_one_of_package_or_path(self):
        cases = (
            ("design:\n  name: mixed\n  sources:\n    - package: rtl/ibex\n      path: extra/foo.sv\n",
             "exactly one"),
            ("design:\n  name: mixed\n  sources:\n    - {}\n", "exactly one"),
            ("design:\n  name: mixed\n  sources:\n    - package: rtl/ibex\n      manifest: m.toml\n",
             "exactly one"),
        )
        for index, (design_block, message) in enumerate(cases):
            text = f"""schema: wolf.environment/v1
name: demo
{design_block}technology:
  package: pdk/asap7
flow:
  package: flow/orfs
workspace:
  root: ./work
"""
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                load_environment(self._write(text, f"bad-sources-{index}.yaml"))

    def test_resolution_is_independent_of_cwd(self):
        profile = load_environment(self._write(self._complete_yaml()))
        before = Path.cwd()
        try:
            os.chdir("/")
            first = resolve_declarative_environment(
                profile, state_root=self.state, environment_directory=self.environment
            )
            os.chdir("/tmp")
            second = resolve_declarative_environment(
                profile, state_root=self.state, environment_directory=self.environment
            )
        finally:
            os.chdir(before)
        self.assertEqual(first, second)

    def test_project_root_is_resolved_and_recorded(self):
        extra = "project:\n  root: ./project\n"
        profile = load_environment(self._write(self._complete_yaml(extra)), expected_name="demo")
        self.assertEqual(profile.project_root, "./project")
        context = resolve_declarative_environment(
            profile, state_root=self.state, environment_directory=self.environment
        )
        self.assertEqual(context.project_root, self.environment / "project")

    def test_workspace_root_defaults_under_project_root_when_omitted(self):
        text = self._complete_yaml().replace("workspace:\n  root: ./work\n", "project:\n  root: ./project\n")
        self.assertNotIn("workspace:", text)
        profile = load_environment(self._write(text), expected_name="demo")
        context = resolve_declarative_environment(
            profile, state_root=self.state, environment_directory=self.environment
        )
        self.assertEqual(context.project_root, self.environment / "project")
        self.assertEqual(context.workspace_root, self.environment / "project" / "workspace")

    def test_explicit_workspace_root_wins_over_project_default(self):
        extra = "project:\n  root: ./project\n"
        profile = load_environment(self._write(self._complete_yaml(extra)), expected_name="demo")
        context = resolve_declarative_environment(
            profile, state_root=self.state, environment_directory=self.environment
        )
        # The complete yaml already sets workspace.root to ./work explicitly.
        self.assertEqual(context.workspace_root, self.environment / "work")

    def test_no_project_root_leaves_it_unset(self):
        profile = load_environment(self._write(self._complete_yaml()), expected_name="demo")
        context = resolve_declarative_environment(
            profile, state_root=self.state, environment_directory=self.environment
        )
        self.assertIsNone(context.project_root)

    def test_constraints_files_are_resolved_relative_to_the_environment_and_recorded(self):
        extra_sdc = self.environment / "extra.sdc"
        extra_sdc.write_text("set_false_path -from [get_ports rst_n]\n", encoding="utf-8")
        extra = "  files:\n    - extra.sdc\n  lines:\n    - 'set_case_analysis 0 [get_ports test_mode]'\n"
        text = self._complete_yaml().replace(
            "constraints:\n  clocks:", f"constraints:\n{extra}  clocks:"
        )
        profile = load_environment(self._write(text, "with-extra-constraints.yaml"), expected_name="demo")
        self.assertEqual(profile.constraint_files, ("extra.sdc",))
        self.assertEqual(
            profile.constraint_lines, ("set_case_analysis 0 [get_ports test_mode]",)
        )
        context = resolve_declarative_environment(
            profile, state_root=self.state, environment_directory=self.environment
        )
        self.assertEqual(context.constraint_files, (extra_sdc.resolve(),))
        self.assertEqual(
            context.constraint_lines, ("set_case_analysis 0 [get_ports test_mode]",)
        )

    def test_constraints_files_and_lines_must_be_lists_of_strings(self):
        cases = (
            ("files", "not-a-list", "constraints.files must be a list"),
            ("files", "[1, 2]", "constraints.files must be a list"),
            ("lines", "not-a-list", "constraints.lines must be a list"),
        )
        for index, (key, value, message) in enumerate(cases):
            text = self._complete_yaml().replace(
                "constraints:\n  clocks:", f"constraints:\n  {key}: {value}\n  clocks:"
            )
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                load_environment(self._write(text, f"bad-constraints-{index}.yaml"))


class MultiCornerTechnologyTests(DeclarativeEnvironmentTests):
    """Technology packages may declare several named MMMC corners."""

    def _multicorner_package(self, name="tsmc65-multicorner"):
        # technology.timing paths are relative to the installed package's own
        # content_path (see _technology_inputs' `paths()` helper), the same as
        # the flat timing.libraries case -- not arbitrary filesystem paths.
        self._package("pdk", name, "pdk-rev", {"technology": {
            "name": name,
            "timing": {
                "corners": {
                    "typical": {"libraries": ["typical.lib"]},
                    "worst_case": {
                        "libraries": ["worst_case.lib"], "qrc_tech_file": "worst_case.qrc",
                        "format": "ecsm",
                    },
                },
            },
        }})
        content = self.state / "packages" / "pdk" / name / "pdk-rev" / "source"
        typical = content / "typical.lib"
        worst_case = content / "worst_case.lib"
        qrc = content / "worst_case.qrc"
        for path in (typical, worst_case, qrc):
            path.write_text(f"-- {path.name} --\n", encoding="utf-8")
        return typical, worst_case, qrc

    def test_multiple_named_corners_are_resolved_with_their_own_libraries(self):
        typical, worst_case, qrc = self._multicorner_package()
        text = self._complete_yaml().replace("package: pdk/asap7", "package: pdk/tsmc65-multicorner")
        context = resolve_declarative_environment(
            load_environment(self._write(text, "multicorner.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        corners = {corner.name: corner for corner in context.technology.timing_corners}
        self.assertEqual(set(corners), {"typical", "worst_case"})
        self.assertEqual(corners["typical"].libraries, (typical.resolve(),))
        self.assertEqual(corners["worst_case"].libraries, (worst_case.resolve(),))
        self.assertEqual(corners["worst_case"].qrc_tech_file, qrc.resolve())
        self.assertIsNone(corners["typical"].qrc_tech_file)
        self.assertEqual(corners["typical"].format, "liberty")
        self.assertEqual(corners["worst_case"].format, "ecsm")
        # The union, for existence/checksum bookkeeping.
        self.assertEqual(
            set(context.technology.timing_libraries), {typical.resolve(), worst_case.resolve()}
        )

    def test_corners_and_flat_libraries_are_mutually_exclusive(self):
        self._multicorner_package()
        manifest_path = self.registry / "pdk" / "tsmc65-multicorner.yaml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        data["metadata"]["technology"]["timing"]["libraries"] = ["somewhere.lib"]
        manifest_path.write_text(yaml.safe_dump(data), encoding="utf-8")
        text = self._complete_yaml().replace("package: pdk/asap7", "package: pdk/tsmc65-multicorner")
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            resolve_declarative_environment(
                load_environment(self._write(text, "conflicting.yaml")),
                state_root=self.state, environment_directory=self.environment,
            )

    def test_corner_requires_nonempty_libraries(self):
        self._package("pdk", "empty-corner", "pdk-rev", {"technology": {
            "name": "empty-corner", "timing": {"corners": {"typical": {}}}},
        })
        text = self._complete_yaml().replace("package: pdk/asap7", "package: pdk/empty-corner")
        with self.assertRaisesRegex(ValueError, "libraries must be nonempty"):
            resolve_declarative_environment(
                load_environment(self._write(text, "empty-corner.yaml")),
                state_root=self.state, environment_directory=self.environment,
            )


class MultiTrackVthTechnologyTests(DeclarativeEnvironmentTests):
    """Technology packages may declare several named track/vth combinations,
    each with its own corners, physical/behavioral views, plus a free-form
    'generic' bucket for whatever doesn't depend on track/vth at all."""

    def _write_file(self, content, name):
        path = self.state / "packages" / "pdk" / "tsmc65-tracked" / "pdk-rev" / "source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"-- {name} --\n", encoding="utf-8")
        return path

    def _tracked_package(self, *, extra_track=False):
        technology = {
            "name": "tsmc65-tracked",
            "generic": {
                "tech_layermap": "config/tsmc65.sorted.gds2map",
                "rc_corners": {
                    "rc_25C": {"temperature": 25, "qrc_tech_file": "qrc/rc_25C.captable"},
                },
            },
            "tracks": {
                "9T": {
                    "vths": {
                        "lvt": {
                            "lef": ["lef/9t_lvt.lef"],
                            "gds": ["gds/9t_lvt.gds"],
                            "verilog_models": ["verilog/9t_lvt.v"],
                            "spice_models": ["spice/9t_lvt.spi"],
                            "qrc_techfiles": ["qrc/9t_lvt.captable"],
                            "timing": {"corners": {
                                "typical": {"libraries": ["lib/9t_lvt_typical.lib"]},
                                "worst_case": {"libraries": ["lib/9t_lvt_worst.lib"]},
                            }},
                        },
                    },
                },
            },
        }
        if extra_track:
            technology["tracks"]["7T"] = {"vths": {"rvt": {
                "lef": ["lef/7t_rvt.lef"],
                "timing": {"corners": {"typical": {"libraries": ["lib/7t_rvt_typical.lib"]}}},
            }}}
        self._package("pdk", "tsmc65-tracked", "pdk-rev", {"technology": technology})
        for relative in (
            "config/tsmc65.sorted.gds2map", "qrc/rc_25C.captable",
            "lef/9t_lvt.lef", "gds/9t_lvt.gds", "verilog/9t_lvt.v", "spice/9t_lvt.spi",
            "qrc/9t_lvt.captable", "lib/9t_lvt_typical.lib", "lib/9t_lvt_worst.lib",
        ):
            self._write_file("x", relative)
        if extra_track:
            for relative in ("lef/7t_rvt.lef", "lib/7t_rvt_typical.lib"):
                self._write_file("x", relative)

    def _yaml_with_selector(self, *, track=None, vth=None, extra_track=False):
        self._tracked_package(extra_track=extra_track)
        selector = ""
        if track is not None:
            selector += f"\n  track: {track}"
        if vth is not None:
            selector += f"\n  vth: {vth}"
        return self._complete_yaml().replace(
            "package: pdk/asap7", f"package: pdk/tsmc65-tracked{selector}"
        )

    def test_single_track_vth_is_selected_automatically(self):
        text = self._yaml_with_selector()
        context = resolve_declarative_environment(
            load_environment(self._write(text, "tracked.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual((context.technology.track, context.technology.vth), ("9T", "lvt"))
        corners = {corner.name for corner in context.technology.timing_corners}
        self.assertEqual(corners, {"typical", "worst_case"})
        self.assertEqual(len(context.technology.technology_lefs), 1)
        self.assertEqual(len(context.technology.gds_files), 1)
        self.assertEqual(len(context.technology.verilog_models), 1)
        self.assertEqual(len(context.technology.spice_models), 1)
        self.assertEqual(len(context.technology.qrc_techfiles), 1)

    def test_catalog_covers_every_track_vth_not_just_the_selected_one(self):
        """A get_flow_config-driven real flow indexes library_sets/lef_files
        by whatever track/vth its own Tcl is given at run time -- the
        catalog must include every declared combination, not collapse to
        the one this particular environment happens to select."""
        text = self._yaml_with_selector(track="9T", vth="lvt", extra_track=True)
        context = resolve_declarative_environment(
            load_environment(self._write(text, "tracked.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual((context.technology.track, context.technology.vth), ("9T", "lvt"))
        library_set_keys = {
            (entry.corner, entry.track, entry.vth)
            for entry in context.technology.catalog_library_sets
        }
        self.assertEqual(library_set_keys, {
            ("typical", "9T", "lvt"), ("worst_case", "9T", "lvt"), ("typical", "7T", "rvt"),
        })
        lef_keys = {(entry.track, entry.vth) for entry in context.technology.catalog_lef_files}
        self.assertEqual(lef_keys, {("9T", "lvt"), ("7T", "rvt")})
        gds_keys = {(entry.track, entry.vth) for entry in context.technology.catalog_gds_files}
        self.assertEqual(gds_keys, {("9T", "lvt")})  # 7T/rvt never declares gds

    def test_generic_bucket_is_passed_through_verbatim(self):
        text = self._yaml_with_selector()
        context = resolve_declarative_environment(
            load_environment(self._write(text, "tracked.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual(
            context.technology.generic["tech_layermap"], "config/tsmc65.sorted.gds2map",
        )
        self.assertEqual(
            context.technology.generic["rc_corners"]["rc_25C"]["temperature"], 25,
        )

    def test_setup_yaml_fragment_resolves_to_an_existing_path(self):
        self._package("pdk", "tsmc65-tracked", "pdk-rev", {"technology": {
            "name": "tsmc65-tracked",
            "setup_yaml_fragment": "setup/tsmc65.setup.fragment.yaml",
            "tracks": {"9T": {"vths": {"lvt": {
                "timing": {"corners": {"typical": {"libraries": ["lib/9t_lvt_typical.lib"]}}},
            }}}},
        }})
        self._write_file("x", "setup/tsmc65.setup.fragment.yaml")
        self._write_file("x", "lib/9t_lvt_typical.lib")
        text = self._complete_yaml().replace("package: pdk/asap7", "package: pdk/tsmc65-tracked")
        context = resolve_declarative_environment(
            load_environment(self._write(text, "tracked.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual(
            context.technology.setup_yaml_fragment,
            context.technology.root / "setup" / "tsmc65.setup.fragment.yaml",
        )

    def test_multiple_tracks_require_explicit_selection(self):
        text = self._yaml_with_selector(extra_track=True)
        with self.assertRaisesRegex(ValueError, "technology.track and technology.vth are required"):
            resolve_declarative_environment(
                load_environment(self._write(text, "tracked.yaml")),
                state_root=self.state, environment_directory=self.environment,
            )

    def test_explicit_track_vth_selects_the_right_variant(self):
        text = self._yaml_with_selector(track="7T", vth="rvt", extra_track=True)
        context = resolve_declarative_environment(
            load_environment(self._write(text, "tracked.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual((context.technology.track, context.technology.vth), ("7T", "rvt"))
        corners = {corner.name for corner in context.technology.timing_corners}
        self.assertEqual(corners, {"typical"})

    def test_unknown_track_vth_is_rejected(self):
        text = self._yaml_with_selector(track="9T", vth="hvt")
        with self.assertRaisesRegex(ValueError, "is not declared"):
            resolve_declarative_environment(
                load_environment(self._write(text, "tracked.yaml")),
                state_root=self.state, environment_directory=self.environment,
            )

    def test_track_without_vth_is_rejected(self):
        text = self._yaml_with_selector(track="9T")
        with self.assertRaisesRegex(ValueError, "must both be set, or neither"):
            resolve_declarative_environment(
                load_environment(self._write(text, "tracked.yaml")),
                state_root=self.state, environment_directory=self.environment,
            )

    def test_track_vth_selector_requires_a_tracked_package(self):
        text = self._complete_yaml().replace(
            "package: pdk/asap7", "package: pdk/asap7\n  track: 9T\n  vth: lvt",
        )
        with self.assertRaisesRegex(ValueError, "declares a flat timing/physical section"):
            resolve_declarative_environment(
                load_environment(self._write(text, "flat-with-selector.yaml")),
                state_root=self.state, environment_directory=self.environment,
            )


class MetalStackTests(DeclarativeEnvironmentTests):
    """lef/gds/qrc_techfiles may vary by named metal stack (routing layer
    count + top-metal option, e.g. 9lmT2) within one track/vth -- a real
    TSMC65-shaped case: the same 9T/lvt cells, several metal-stack LEFs."""

    def _write_file(self, name, package="tsmc65-stacks"):
        path = self.state / "packages" / "pdk" / package / "pdk-rev" / "source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"-- {name} --\n", encoding="utf-8")
        return path

    def _stacked_package(self, *, default_metal_stack=None):
        lvt = {
            "lef": {"9lmT2": ["lef/9t_lvt_9lmT2.lef"], "7lmT1": ["lef/9t_lvt_7lmT1.lef"]},
            "gds": {"9lmT2": ["gds/9t_lvt_9lmT2.gds"], "7lmT1": ["gds/9t_lvt_7lmT1.gds"]},
            "qrc_techfiles": {
                "9lmT2": ["qrc/9t_lvt_9lmT2.captable"], "7lmT1": ["qrc/9t_lvt_7lmT1.captable"],
            },
            "timing": {"corners": {"typical": {"libraries": ["lib/9t_lvt_typical.lib"]}}},
        }
        if default_metal_stack is not None:
            lvt["default_metal_stack"] = default_metal_stack
        self._package("pdk", "tsmc65-stacks", "pdk-rev", {"technology": {
            "name": "tsmc65-stacks", "tracks": {"9T": {"vths": {"lvt": lvt}}},
        }})
        for relative in (
            "lef/9t_lvt_9lmT2.lef", "lef/9t_lvt_7lmT1.lef",
            "gds/9t_lvt_9lmT2.gds", "gds/9t_lvt_7lmT1.gds",
            "qrc/9t_lvt_9lmT2.captable", "qrc/9t_lvt_7lmT1.captable",
            "lib/9t_lvt_typical.lib",
        ):
            self._write_file(relative)

    def _yaml_with_stack(self, *, metal_stack=None):
        selector = f"\n  metal_stack: {metal_stack}" if metal_stack else ""
        return self._complete_yaml().replace(
            "package: pdk/asap7", f"package: pdk/tsmc65-stacks{selector}"
        )

    def test_explicit_metal_stack_selects_matching_lef_gds_qrc(self):
        self._stacked_package()
        context = resolve_declarative_environment(
            load_environment(self._write(self._yaml_with_stack(metal_stack="7lmT1"), "stacks.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual(context.technology.metal_stack, "7lmT1")
        self.assertTrue(str(context.technology.technology_lefs[0]).endswith("9t_lvt_7lmT1.lef"))
        self.assertTrue(str(context.technology.gds_files[0]).endswith("9t_lvt_7lmT1.gds"))
        self.assertTrue(str(context.technology.qrc_techfiles[0]).endswith("9t_lvt_7lmT1.captable"))

    def test_missing_metal_stack_with_several_declared_is_rejected(self):
        self._stacked_package()
        with self.assertRaisesRegex(ValueError, "technology.metal_stack is required"):
            resolve_declarative_environment(
                load_environment(self._write(self._yaml_with_stack(), "stacks.yaml")),
                state_root=self.state, environment_directory=self.environment,
            )

    def test_default_metal_stack_is_used_when_not_overridden(self):
        self._stacked_package(default_metal_stack="9lmT2")
        context = resolve_declarative_environment(
            load_environment(self._write(self._yaml_with_stack(), "stacks.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual(context.technology.metal_stack, "9lmT2")

    def test_explicit_metal_stack_overrides_the_default(self):
        self._stacked_package(default_metal_stack="9lmT2")
        context = resolve_declarative_environment(
            load_environment(self._write(self._yaml_with_stack(metal_stack="7lmT1"), "stacks.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual(context.technology.metal_stack, "7lmT1")

    def test_unknown_metal_stack_is_rejected(self):
        self._stacked_package()
        with self.assertRaisesRegex(ValueError, "is not declared"):
            resolve_declarative_environment(
                load_environment(self._write(self._yaml_with_stack(metal_stack="12lmT9"), "stacks.yaml")),
                state_root=self.state, environment_directory=self.environment,
            )

    def test_mismatched_stack_keys_across_fields_resolve_whichever_has_the_selected_stack(self):
        """lef and qrc_techfiles are allowed to declare different stack
        sets -- confirmed real PDK data: a vth's qrc_techfiles having
        captables for stacks that vth's own lef doesn't declare (yet, or
        at all) is a normal, valid state, not an authoring mistake to
        reject. Picking a stack that only one of the two fields has just
        resolves that field and leaves the other empty."""
        self._package("pdk", "tsmc65-mismatch", "pdk-rev", {"technology": {
            "name": "tsmc65-mismatch", "tracks": {"9T": {"vths": {"lvt": {
                "lef": {"9lmT2": ["lef/x.lef"]},
                "qrc_techfiles": {"7lmT1": ["qrc/x.captable"]},
                "timing": {"corners": {"typical": {"libraries": ["lib/x.lib"]}}},
            }}}},
        }})
        for relative in ("lef/x.lef", "qrc/x.captable", "lib/x.lib"):
            self._write_file(relative, package="tsmc65-mismatch")

        text_9lm = self._complete_yaml().replace(
            "package: pdk/asap7", "package: pdk/tsmc65-mismatch\n  metal_stack: 9lmT2",
        )
        context = resolve_declarative_environment(
            load_environment(self._write(text_9lm, "mismatch-9lm.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual([p.name for p in context.technology.technology_lefs], ["x.lef"])
        self.assertEqual(context.technology.qrc_techfiles, ())

        text_7lm = self._complete_yaml().replace(
            "package: pdk/asap7", "package: pdk/tsmc65-mismatch\n  metal_stack: 7lmT1",
        )
        context = resolve_declarative_environment(
            load_environment(self._write(text_7lm, "mismatch-7lm.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual(context.technology.technology_lefs, ())
        self.assertEqual([p.name for p in context.technology.qrc_techfiles], ["x.captable"])

    def test_qrc_techfiles_are_keyed_by_stack_and_named_rc_corner(self):
        """Unlike gds, a real captable is named per metal stack AND per
        rc-corner (confirmed filename: ..._Vp9m+alrdl_top2_rcworst.captable)
        -- qrc_techfiles keeps its full nesting, one level deeper than lef,
        resolved per named rc-corner (ResolvedQrcCorner) for the selected
        stack, plus the flat union across every rc-corner."""
        self._package("pdk", "tsmc65-rccorners", "pdk-rev", {"technology": {
            "name": "tsmc65-rccorners", "tracks": {"9T": {"vths": {"lvt": {
                "lef": {"9lmT2": ["lef/x.lef"], "7lmT1": ["lef/y.lef"]},
                "qrc_techfiles": {
                    "9lmT2": {
                        "rcbest": ["qrc/9lmT2_rcbest.captable"],
                        "rcworst": ["qrc/9lmT2_rcworst.captable"],
                        "typical": ["qrc/9lmT2_typical.captable"],
                    },
                    "7lmT1": {
                        "rcbest": ["qrc/7lmT1_rcbest.captable"],
                        "rcworst": ["qrc/7lmT1_rcworst.captable"],
                    },
                },
                "timing": {"corners": {"typical": {"libraries": ["lib/x.lib"]}}},
            }}}},
        }})
        for relative in (
            "lef/x.lef", "lef/y.lef", "lib/x.lib",
            "qrc/9lmT2_rcbest.captable", "qrc/9lmT2_rcworst.captable", "qrc/9lmT2_typical.captable",
            "qrc/7lmT1_rcbest.captable", "qrc/7lmT1_rcworst.captable",
        ):
            self._write_file(relative, package="tsmc65-rccorners")
        text = self._complete_yaml().replace(
            "package: pdk/asap7", "package: pdk/tsmc65-rccorners\n  metal_stack: 9lmT2",
        )
        context = resolve_declarative_environment(
            load_environment(self._write(text, "rccorners.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        qrc_by_name = {corner.name: corner for corner in context.technology.qrc_corners}
        self.assertEqual(set(qrc_by_name), {"rcbest", "rcworst", "typical"})
        self.assertEqual(
            [p.name for p in qrc_by_name["rcworst"].qrc_techfiles], ["9lmT2_rcworst.captable"],
        )
        # The flat union covers every rc-corner's files for the selected stack.
        self.assertEqual(
            {p.name for p in context.technology.qrc_techfiles},
            {"9lmT2_rcbest.captable", "9lmT2_rcworst.captable", "9lmT2_typical.captable"},
        )

    def test_legacy_flat_qrc_techfiles_per_stack_still_resolves_with_no_named_corners(self):
        """A vth that declared qrc_techfiles per stack before rc-corners
        were broken out by name (just {stack: [files]}) still resolves --
        no ResolvedQrcCorner entries, but the flat file list is there."""
        self._package("pdk", "tsmc65-flatqrc", "pdk-rev", {"technology": {
            "name": "tsmc65-flatqrc", "tracks": {"9T": {"vths": {"lvt": {
                "lef": {"9lmT2": ["lef/x.lef"]},
                "qrc_techfiles": {"9lmT2": ["qrc/x.captable"]},
                "timing": {"corners": {"typical": {"libraries": ["lib/x.lib"]}}},
            }}}},
        }})
        for relative in ("lef/x.lef", "lib/x.lib", "qrc/x.captable"):
            self._write_file(relative, package="tsmc65-flatqrc")
        text = self._complete_yaml().replace("package: pdk/asap7", "package: pdk/tsmc65-flatqrc")
        context = resolve_declarative_environment(
            load_environment(self._write(text, "flatqrc.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual(context.technology.qrc_corners, ())
        self.assertEqual([p.name for p in context.technology.qrc_techfiles], ["x.captable"])

    def test_gds_is_flat_and_independent_of_the_stack_axis(self):
        """A cell's own GDS geometry lives on metal layers shared by every
        stack option, unlike lef/qrc_techfiles -- gds is just a flat list,
        and lef/qrc_techfiles disagreeing about stack names (gds isn't
        even declared per-stack here) is never gds's problem."""
        self._package("pdk", "tsmc65-flatgds", "pdk-rev", {"technology": {
            "name": "tsmc65-flatgds", "tracks": {"9T": {"vths": {"lvt": {
                "lef": {"9lmT2": ["lef/x.lef"], "7lmT1": ["lef/y.lef"]},
                "gds": ["gds/x.gds"],
                "timing": {"corners": {"typical": {"libraries": ["lib/x.lib"]}}},
            }}}},
        }})
        for relative in ("lef/x.lef", "lef/y.lef", "gds/x.gds", "lib/x.lib"):
            self._write_file(relative, package="tsmc65-flatgds")
        text = self._complete_yaml().replace(
            "package: pdk/asap7", "package: pdk/tsmc65-flatgds\n  metal_stack: 7lmT1",
        )
        context = resolve_declarative_environment(
            load_environment(self._write(text, "flatgds.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual(context.technology.metal_stack, "7lmT1")
        self.assertEqual([p.name for p in context.technology.gds_files], ["x.gds"])

    def test_legacy_per_stack_gds_still_resolves(self):
        """A package that declared gds per metal stack before that stopped
        being a real axis for gds still resolves -- the selected
        metal_stack's own entry is used, rather than erroring out on
        every PDK manifest written before this changed."""
        self._package("pdk", "tsmc65-legacygds", "pdk-rev", {"technology": {
            "name": "tsmc65-legacygds", "tracks": {"9T": {"vths": {"lvt": {
                "lef": {"9lmT2": ["lef/x.lef"], "7lmT1": ["lef/y.lef"]},
                "gds": {"9lmT2": ["gds/a.gds"], "7lmT1": ["gds/b.gds"]},
                "timing": {"corners": {"typical": {"libraries": ["lib/x.lib"]}}},
            }}}},
        }})
        for relative in ("lef/x.lef", "lef/y.lef", "gds/a.gds", "gds/b.gds", "lib/x.lib"):
            self._write_file(relative, package="tsmc65-legacygds")
        text = self._complete_yaml().replace(
            "package: pdk/asap7", "package: pdk/tsmc65-legacygds\n  metal_stack: 7lmT1",
        )
        context = resolve_declarative_environment(
            load_environment(self._write(text, "legacygds.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual([p.name for p in context.technology.gds_files], ["b.gds"])

    def test_single_stack_still_requires_no_selection(self):
        self._package("pdk", "tsmc65-onestack", "pdk-rev", {"technology": {
            "name": "tsmc65-onestack", "tracks": {"9T": {"vths": {"lvt": {
                "lef": {"9lmT2": ["lef/x.lef"]},
                "timing": {"corners": {"typical": {"libraries": ["lib/x.lib"]}}},
            }}}},
        }})
        self._write_file("lef/x.lef", package="tsmc65-onestack")
        self._write_file("lib/x.lib", package="tsmc65-onestack")
        text = self._complete_yaml().replace("package: pdk/asap7", "package: pdk/tsmc65-onestack")
        context = resolve_declarative_environment(
            load_environment(self._write(text, "onestack.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual(context.technology.metal_stack, "9lmT2")

    def test_metal_stack_without_declared_stacks_is_rejected(self):
        self._package("pdk", "tsmc65-flatlef", "pdk-rev", {"technology": {
            "name": "tsmc65-flatlef", "tracks": {"9T": {"vths": {"lvt": {
                "lef": ["lef/x.lef"],
                "timing": {"corners": {"typical": {"libraries": ["lib/x.lib"]}}},
            }}}},
        }})
        self._write_file("lef/x.lef", package="tsmc65-flatlef")
        self._write_file("lib/x.lib", package="tsmc65-flatlef")
        text = self._complete_yaml().replace(
            "package: pdk/asap7", "package: pdk/tsmc65-flatlef\n  metal_stack: 9lmT2",
        )
        with self.assertRaisesRegex(ValueError, "declares no named metal stacks"):
            resolve_declarative_environment(
                load_environment(self._write(text, "flatlef.yaml")),
                state_root=self.state, environment_directory=self.environment,
            )


class SignoffCatalogTests(DeclarativeEnvironmentTests):
    """opconds -> delay_corners -> analysis_views: a static catalog
    mirroring the real MMMC object chain, each referencing the declared
    ones before it by name only -- the dynamic part (which actually
    drives a given run) is an environment-level concern this doesn't
    cover."""

    def _write_file(self, name, package="tsmc65-signoff"):
        path = self.state / "packages" / "pdk" / package / "pdk-rev" / "source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"-- {name} --\n", encoding="utf-8")
        return path

    def _signoff_package(self, *, delay_corners=None, analysis_views=None, opconds=None):
        technology = {
            "name": "tsmc65-signoff",
            "tracks": {"9T": {"vths": {"lvt": {
                "qrc_techfiles": {"9lmT2": {
                    "rcbest": ["qrc/rcbest.captable"], "rcworst": ["qrc/rcworst.captable"],
                }},
                "timing": {"corners": {
                    "bc": {"libraries": ["lib/bc.lib"]}, "wc": {"libraries": ["lib/wc.lib"]},
                }},
            }}}},
        }
        if opconds is not None:
            technology["opconds"] = opconds
        if delay_corners is not None:
            technology["delay_corners"] = delay_corners
        if analysis_views is not None:
            technology["analysis_views"] = analysis_views
        self._package("pdk", "tsmc65-signoff", "pdk-rev", {"technology": technology})
        for relative in ("qrc/rcbest.captable", "qrc/rcworst.captable", "lib/bc.lib", "lib/wc.lib"):
            self._write_file(relative)

    def _resolve(self):
        text = self._complete_yaml().replace(
            "package: pdk/asap7", "package: pdk/tsmc65-signoff\n  metal_stack: 9lmT2",
        )
        return resolve_declarative_environment(
            load_environment(self._write(text, "signoff.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )

    def test_full_catalog_resolves_and_links_by_name(self):
        self._signoff_package(
            opconds={"typ_25c": {"process": "1.0", "voltage": "1.2", "temperature": "25"}},
            delay_corners={
                "wc_rcworst": {"timing_corner": "wc", "rc_corner": "rcworst"},
                "bc_rcbest": {"timing_corner": "bc", "rc_corner": "rcbest"},
            },
            analysis_views={
                "func_setup_wc": {"delay_corner": "wc_rcworst", "is_setup": True},
                "func_hold_bc": {"delay_corner": "bc_rcbest", "is_hold": True},
            },
        )
        context = self._resolve()
        opconds = {o.name: o for o in context.technology.catalog_opconds}
        self.assertEqual(opconds["typ_25c"].voltage, "1.2")
        delay_corners = {d.name: d for d in context.technology.catalog_delay_corners}
        self.assertEqual(delay_corners["wc_rcworst"].rc_corner, "rcworst")
        views = {v.name: v for v in context.technology.catalog_analysis_views}
        self.assertTrue(views["func_setup_wc"].is_setup)
        self.assertEqual(views["func_setup_wc"].delay_corner, "wc_rcworst")
        self.assertFalse(views["func_hold_bc"].is_setup)
        self.assertTrue(views["func_hold_bc"].is_hold)

    def test_no_signoff_declared_resolves_to_empty_catalog(self):
        self._signoff_package()
        context = self._resolve()
        self.assertEqual(context.technology.catalog_opconds, ())
        self.assertEqual(context.technology.catalog_delay_corners, ())
        self.assertEqual(context.technology.catalog_analysis_views, ())

    def test_delay_corner_referencing_undeclared_timing_corner_is_rejected(self):
        self._signoff_package(delay_corners={
            "bogus": {"timing_corner": "nope", "rc_corner": "rcworst"},
        })
        with self.assertRaisesRegex(ValueError, "is not a declared timing corner"):
            self._resolve()

    def test_delay_corner_referencing_undeclared_rc_corner_is_rejected(self):
        self._signoff_package(delay_corners={
            "bogus": {"timing_corner": "wc", "rc_corner": "nope"},
        })
        with self.assertRaisesRegex(ValueError, "is not a declared RC-extraction corner"):
            self._resolve()

    def test_analysis_view_referencing_undeclared_delay_corner_is_rejected(self):
        self._signoff_package(analysis_views={
            "bogus": {"delay_corner": "nope", "is_setup": True},
        })
        with self.assertRaisesRegex(ValueError, "is not a declared delay corner"):
            self._resolve()


class MultiVthSelectionTests(DeclarativeEnvironmentTests):
    """technology.track/technology.vth accept a list, not just one name
    -- confirmed real usage: mixing lvt/rvt library sets in one synthesis
    run (`vths: ${VTHS}`, a bash array, in a real legacy setup.yaml
    template, consumed by synthesis.tcl's own `foreach trk [get_flow_config
    tracks] { foreach vth [get_flow_config vths] { ... } }`). A single
    string stays exactly the one-element-list case -- zero behavior
    change for every existing single-vth environment."""

    def _write_file(self, name, package="tsmc65-multivth"):
        path = self.state / "packages" / "pdk" / package / "pdk-rev" / "source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"-- {name} --\n", encoding="utf-8")
        return path

    def _multivth_package(self):
        self._package("pdk", "tsmc65-multivth", "pdk-rev", {"technology": {
            "name": "tsmc65-multivth", "tracks": {"9T": {"vths": {
                "lvt": {
                    "lef": ["lef/lvt.lef"],
                    "timing": {"corners": {"typical": {"libraries": ["lib/lvt_typical.lib"]}}},
                },
                "rvt": {
                    "lef": ["lef/rvt.lef"],
                    "timing": {"corners": {"typical": {"libraries": ["lib/rvt_typical.lib"]}}},
                },
            }}}},
        })
        for relative in ("lef/lvt.lef", "lef/rvt.lef", "lib/lvt_typical.lib", "lib/rvt_typical.lib"):
            self._write_file(relative)

    def _resolve(self, *, vth):
        text = self._complete_yaml().replace(
            "package: pdk/asap7", f"package: pdk/tsmc65-multivth\n  track: 9T\n  vth: {vth}",
        )
        return resolve_declarative_environment(
            load_environment(self._write(text, "multivth.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )

    def test_single_vth_string_resolves_to_a_one_element_selection(self):
        self._multivth_package()
        context = self._resolve(vth="lvt")
        self.assertEqual(context.technology.vth, "lvt")
        self.assertEqual(context.technology.selected_vths, ("lvt",))
        self.assertEqual(context.technology.selected_tracks, ("9T",))

    def test_vth_list_resolves_primary_plus_full_selection(self):
        self._multivth_package()
        context = self._resolve(vth="[lvt, rvt]")
        # Primary (used to resolve lef/gds/qrc/timing_corners) is the
        # first-listed name -- the same single flattened variant every
        # other field on ResolvedTechnology already assumes.
        self.assertEqual(context.technology.vth, "lvt")
        self.assertTrue(str(context.technology.technology_lefs[0]).endswith("lvt.lef"))
        # The full selection carries every name, for setup.yaml's own
        # plural vths: token.
        self.assertEqual(context.technology.selected_vths, ("lvt", "rvt"))

    def test_vth_list_with_a_non_string_entry_is_rejected(self):
        self._multivth_package()
        text = self._complete_yaml().replace(
            "package: pdk/asap7", "package: pdk/tsmc65-multivth\n  track: 9T\n  vth: [lvt, 7]",
        )
        with self.assertRaisesRegex(ValueError, "technology.vth must be a nonempty string or a list"):
            resolve_declarative_environment(
                load_environment(self._write(text, "badvth.yaml")),
                state_root=self.state, environment_directory=self.environment,
            )

    def test_empty_vth_list_is_rejected(self):
        self._multivth_package()
        text = self._complete_yaml().replace(
            "package: pdk/asap7", "package: pdk/tsmc65-multivth\n  track: 9T\n  vth: []",
        )
        with self.assertRaisesRegex(ValueError, "technology.vth must be a nonempty string or a list"):
            resolve_declarative_environment(
                load_environment(self._write(text, "emptyvth.yaml")),
                state_root=self.state, environment_directory=self.environment,
            )


class FlowBackendPersistenceTests(DeclarativeEnvironmentTests):
    """flow.backend persists a bundled-default flow's backend choice in
    wolf.yaml itself -- previously only ever a `wolf run --backend`
    override, meaning it had to be typed on every single invocation even
    though the environment otherwise fully resolved."""

    def test_flow_backend_is_honored_without_a_cli_override(self):
        text = self._complete_yaml().replace(
            "flow:\n  package: flow/orfs", "flow:\n  name: default\n  backend: cadence-flowtool",
        )
        context = resolve_declarative_environment(
            load_environment(self._write(text, "backend.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual(context.backend, "cadence-flowtool")

    def test_cli_backend_override_still_wins_over_flow_backend(self):
        text = self._complete_yaml().replace(
            "flow:\n  package: flow/orfs", "flow:\n  name: default\n  backend: cadence-flowtool",
        )
        context = resolve_declarative_environment(
            load_environment(self._write(text, "backend2.yaml")),
            state_root=self.state, environment_directory=self.environment,
            backend_override="orfs",
        )
        self.assertEqual(context.backend, "orfs")

    def test_a_bundled_flow_with_no_name_at_all_still_resolves_as_complete(self):
        """wolf env menu no longer writes flow.name: "default" at all --
        backend alone must still satisfy the "flow" completeness
        requirement (flow_name or backend), not just flow.name."""
        text = self._complete_yaml().replace(
            "flow:\n  package: flow/orfs", "flow:\n  backend: cadence-flowtool",
        )
        context = resolve_declarative_environment(
            load_environment(self._write(text, "backend3.yaml")),
            state_root=self.state, environment_directory=self.environment,
        )
        self.assertEqual(context.backend, "cadence-flowtool")
        self.assertIsNone(context.flow_name)


if __name__ == "__main__":
    unittest.main()

import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml
from textual.app import App
from textual.widgets import Input, OptionList, Static

from wolf.backend.cadence_genus_setup import design_setup_path
from wolf.env_menu import EnvWizardApp, _BrowseScreen, _scan_modules


class EnvWizardEndToEndTests(unittest.TestCase):
    """Drives the real TUI (Textual's own headless Pilot), the same bar
    `wolf pdk menu` is held to -- exercising the real screens, not just
    the underlying schema, is what catches wiring bugs between a picker
    and what actually ends up in wolf.yaml."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-env-menu-")
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.registry = self.root / "registry"
        self.state.mkdir(parents=True)
        self.variables = patch.dict(
            os.environ,
            {"WOLF_HOME": str(self.state), "WOLF_REGISTRY": str(self.registry)},
        )
        self.variables.start()

        self.hdl_dir = self.root / "hdl"
        self.hdl_dir.mkdir()
        (self.hdl_dir / "top.v").write_text("module top(input clk);\nendmodule\n", encoding="utf-8")

        self.constraints_dir = self.root / "constraints"
        self.constraints_dir.mkdir()
        self.sdc_path = self.constraints_dir / "top.sdc"
        self.sdc_path.write_text("set_max_delay 1.0\n", encoding="utf-8")

        self._register_pdk()

    def tearDown(self):
        self.variables.stop()
        self.temporary.cleanup()

    def _register_pdk(self):
        manifest = {
            "schema_version": 1, "kind": "pdk", "name": "testpdk", "description": "testpdk",
            "source": {"type": "local-path", "root": str(self.root / "pdksrc"), "revision": "V1"},
            "validation": {"required_paths": []},
            "metadata": {"technology": {
                "name": "testpdk",
                "tracks": {"9T": {"vths": {
                    "lvt": {
                        "lef": {"6lmT1": ["lef/x.lef"], "7lmT1": ["lef/y.lef"]},
                        "timing": {"corners": {"typical": {"libraries": ["lib/x.lib"]}}},
                    },
                    "rvt": {
                        "lef": ["lef/flat.lef"],
                        "timing": {"corners": {"typical": {"libraries": ["lib/x.lib"]}}},
                    },
                    "hvt": {
                        "lef": {"7lmT1": ["lef/z.lef"], "8lmT1": ["lef/w.lef"]},
                        "timing": {"corners": {"typical": {"libraries": ["lib/x.lib"]}}},
                    },
                }}},
            }},
        }
        pdk_dir = self.registry / "pdk"
        pdk_dir.mkdir(parents=True, exist_ok=True)
        (pdk_dir / "testpdk.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        installation = self.state / "packages" / "pdk" / "testpdk" / "V1"
        (installation / "source").mkdir(parents=True)
        (installation / "installed.yaml").write_text(
            yaml.safe_dump({
                "package": "pdk/testpdk", "revision": "V1", "source_revision": "V1",
                "content_path": "source", "installed_at": "2026-10-05T00:00:00Z",
            }),
            encoding="utf-8",
        )

    def _select(self, option_list, label):
        options = [o.prompt for o in option_list.options]
        option_list.highlighted = options.index(label)

    def test_full_wizard_builds_tracked_technology_constraints_and_workspace(self):
        project_root = self.root / "project"

        async def drive():
            app = EnvWizardApp("smoketest")
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)

                # Project root first -- everything else is gated on it.
                # This path doesn't exist yet, so no scan screen appears.
                self._select(main_list, "Project root: not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Type a path manually")
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = str(project_root)
                await pilot.press("enter")
                await pilot.pause()

                # RTL sources: type a path manually.
                self._select(main_list, "RTL sources: none yet")
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Type a path manually")
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = str(self.hdl_dir / "top.v")
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("escape")  # done with sources
                await pilot.pause()

                # Design name/top: pick the detected module.
                self._select(app.screen.query_one(OptionList), "Design name / top: not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "top")
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("enter")  # accept default design name (blank = same as top)
                await pilot.pause()

                # Technology: package, then track/vth, then metal stack --
                # all inside one visit to the Technology submenu, which
                # stays open (and shows live state) after each pick.
                self._select(app.screen.query_one(OptionList), "Technology (PDK): not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "PDK package: not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "pdk/testpdk (installed)")
                await pilot.press("enter")
                await pilot.pause()

                self._select(app.screen.query_one(OptionList), "Track: not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T")
                await pilot.press("enter")
                await pilot.pause()

                # VTH(s) is a checklist -- toggle lvt on, then finish the
                # checklist with esc (not enter, which only toggles here).
                self._select(app.screen.query_one(OptionList), "VTH(s): not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "[ ] lvt")
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()

                self._select(app.screen.query_one(OptionList), "Metal stack: not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "7lmT1")
                await pilot.press("enter")
                await pilot.pause()

                # Still on the Technology submenu -- esc applies it to the
                # main menu, rather than bouncing there after every pick.
                self.assertEqual(
                    [o.prompt for o in app.screen.query_one(OptionList).options],
                    ["PDK package: pdk/testpdk", "Track: 9T", "VTH(s): lvt", "Metal stack: 7lmT1"],
                )
                await pilot.press("escape")
                await pilot.pause()

                # Constraints: add the real SDC by manual path.
                self._select(app.screen.query_one(OptionList), "Constraints (SDC): none yet")
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Type a path manually")
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = str(self.sdc_path)
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("escape")  # done with constraints
                await pilot.pause()

                # Power/ground nets: add one of each.
                self._select(app.screen.query_one(OptionList), "Power/ground nets: none set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Power nets (0)")
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                app.screen.query_one(Input).value = "VDD"
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("escape")  # done with power nets, back to main menu
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Power/ground nets: 1 power / 0 ground")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Ground nets (0)")
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                app.screen.query_one(Input).value = "VSS"
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("escape")  # done with ground nets
                await pilot.pause()

                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive())

        document = yaml.safe_load((self.state / "envs" / "smoketest" / "wolf.yaml").read_text(encoding="utf-8"))
        self.assertEqual(document["design"]["top"], "top")
        # Saving copies the source into <project_root>/inputs/hdl/<design>/
        # and rewrites the stored path to the copy, rather than keeping a
        # path that points outside the project.
        copied = project_root / "inputs" / "hdl" / "top" / "top.v"
        self.assertEqual(document["design"]["sources"], [{"path": str(copied)}])
        self.assertTrue(copied.is_file())
        self.assertEqual(copied.read_text(encoding="utf-8"), (self.hdl_dir / "top.v").read_text(encoding="utf-8"))
        self.assertEqual(
            document["technology"],
            {"package": "pdk/testpdk", "track": "9T", "vth": "lvt", "metal_stack": "7lmT1"},
        )
        self.assertEqual(
            document["constraints"],
            {"files": [str(self.sdc_path)], "power_nets": ["VDD"], "ground_nets": ["VSS"]},
        )
        self.assertEqual(document["project"], {"root": str(project_root)})

    def test_track_vth_and_metal_stack_require_their_prerequisites(self):
        project_root = self.root / "project2"

        async def drive():
            app = EnvWizardApp("smoketest2")
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)

                # Project root first -- Technology is gated until it's set.
                self._select(main_list, "Project root: not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Type a path manually")
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = str(project_root)
                await pilot.press("enter")
                await pilot.pause()

                self._select(main_list, "Technology (PDK): not set")
                await pilot.press("enter")
                await pilot.pause()
                depth_before = len(app.screen_stack)

                def tech_options() -> list[str]:
                    return [o.prompt for o in app.screen.query_one(OptionList).options]

                self._select(app.screen.query_one(OptionList), "Track: not set")
                await pilot.press("enter")
                await pilot.pause()
                # No PDK package picked yet -- warns, stays on the (still
                # open) Technology submenu rather than opening a picker.
                self.assertEqual(len(app.screen_stack), depth_before)
                self.assertIn("Track: not set", tech_options())

                self._select(app.screen.query_one(OptionList), "VTH(s): not set")
                await pilot.press("enter")
                await pilot.pause()
                # No track picked yet either -- same guard.
                self.assertEqual(len(app.screen_stack), depth_before)

                self._select(app.screen.query_one(OptionList), "Metal stack: not set")
                await pilot.press("enter")
                await pilot.pause()
                # No vth picked yet either -- same guard.
                self.assertEqual(len(app.screen_stack), depth_before)

                # Pick the package, the track, then a vth with no named
                # stacks (flat lef).
                self._select(app.screen.query_one(OptionList), "PDK package: not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "pdk/testpdk (installed)")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Track: not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "VTH(s): not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "[ ] rvt")
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()

                self._select(app.screen.query_one(OptionList), "Metal stack: not set")
                await pilot.press("enter")
                await pilot.pause()
                # rvt has a flat lef list -- no named stacks to pick, so
                # this also stays on the Technology submenu, not a picker.
                self.assertEqual(len(app.screen_stack), depth_before)
                self.assertIn("Metal stack: not set", tech_options())

        asyncio.run(drive())

    def test_project_root_browser_creates_a_new_folder_with_a_real_mkdir(self):
        async def drive():
            with patch("wolf.env_menu.Path.home", return_value=self.root):
                app = EnvWizardApp("smoketest3")
                async with app.run_test() as pilot:
                    main_list = app.query_one(OptionList)
                    self._select(main_list, "Project root: not set")
                    await pilot.press("enter")
                    await pilot.pause()
                    self._select(app.screen.query_one(OptionList), "Browse filesystem")
                    await pilot.press("enter")
                    await pilot.pause()
                    await pilot.press("n")
                    await pilot.pause()
                    app.screen.query_one(Input).value = "new-project"
                    await pilot.press("enter")
                    await pilot.pause()
                    await pilot.press("a")  # use the (now real, on-disk) new directory
                    await pilot.pause()
                    # The new, empty directory is still scanned (never
                    # skipped) -- nothing found, so esc continues manually.
                    await pilot.press("escape")
                    await pilot.pause()
                    await pilot.press("s")
                    await pilot.pause()

        asyncio.run(drive())

        document = yaml.safe_load((self.state / "envs" / "smoketest3" / "wolf.yaml").read_text(encoding="utf-8"))
        created = Path(document["project"]["root"])
        self.assertEqual(created.name, "new-project")
        self.assertTrue(created.is_dir())

    def test_multiple_vths_write_a_list_and_metal_stack_is_their_intersection(self):
        """Confirmed real usage: a run mixes more than one vth's library
        set in one synthesis (Genus picks cells from whichever fits a
        given path). lvt declares stacks {6lmT1, 7lmT1}, hvt declares
        {7lmT1, 8lmT1} -- picking both must only offer 7lmT1 for metal
        stack, the one declared for both, not the union."""
        project_root = self.root / "project6"

        async def drive():
            app = EnvWizardApp("smoketest6")
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                self._select(main_list, "Project root: not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Type a path manually")
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = str(project_root)
                await pilot.press("enter")
                await pilot.pause()

                self._select(main_list, "Technology (PDK): not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "PDK package: not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "pdk/testpdk (installed)")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Track: not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T")
                await pilot.press("enter")
                await pilot.pause()

                self._select(app.screen.query_one(OptionList), "VTH(s): not set")
                await pilot.press("enter")
                await pilot.pause()
                checklist = [o.prompt for o in app.screen.query_one(OptionList).options]
                self.assertEqual(checklist, ["[ ] hvt", "[ ] lvt", "[ ] rvt"])
                self._select(app.screen.query_one(OptionList), "[ ] lvt")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "[ ] hvt")
                await pilot.press("enter")
                await pilot.pause()
                # Both now checked.
                checked = [o.prompt for o in app.screen.query_one(OptionList).options]
                self.assertEqual(checked, ["[x] hvt", "[x] lvt", "[ ] rvt"])
                await pilot.press("escape")  # finish the checklist
                await pilot.pause()

                self._select(app.screen.query_one(OptionList), "Metal stack: not set")
                await pilot.press("enter")
                await pilot.pause()
                stack_choices = [o.prompt for o in app.screen.query_one(OptionList).options]
                self.assertEqual(stack_choices, ["7lmT1"])
                self._select(app.screen.query_one(OptionList), "7lmT1")
                await pilot.press("enter")
                await pilot.pause()

                await pilot.press("escape")  # done with Technology
                await pilot.pause()
                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive())

        document = yaml.safe_load((self.state / "envs" / "smoketest6" / "wolf.yaml").read_text(encoding="utf-8"))
        self.assertEqual(
            document["technology"],
            {"package": "pdk/testpdk", "track": "9T", "vth": ["hvt", "lvt"], "metal_stack": "7lmT1"},
        )

    def test_quit_with_unsaved_changes_requires_confirming_yes(self):
        """escape is also the "go back one level" key everywhere else in
        this wizard, so an accidental press at the top level must not
        silently discard an in-progress edit -- confirm, defaulting to
        No, and only an explicit move to Yes actually quits."""
        project_root = self.root / "project5"

        async def drive():
            app = EnvWizardApp("smoketest5")
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                self._select(main_list, "Project root: not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Type a path manually")
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = str(project_root)
                await pilot.press("enter")
                await pilot.pause()
                self.assertIn("unsaved changes", app.sub_title)

                # First escape: confirm dialog, default highlighted is "No".
                await pilot.press("escape")
                await pilot.pause()
                confirm_opts = [o.prompt for o in app.screen.query_one(OptionList).options]
                self.assertEqual(confirm_opts, ["No", "Yes"])
                self.assertEqual(app.screen.query_one(OptionList).highlighted, 0)

                # Plain enter accepts the default (No) -- back on the main
                # menu, still running, nothing lost.
                await pilot.press("enter")
                await pilot.pause()
                self.assertTrue(app.is_running)
                self.assertIn("Project root", app.screen.query_one(OptionList).options[0].prompt)

                # Escape again, this time move to Yes and confirm.
                await pilot.press("escape")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Yes")
                await pilot.press("enter")
                await pilot.pause()
                self.assertFalse(app.is_running)

        asyncio.run(drive())
        self.assertFalse((self.state / "envs" / "smoketest5" / "wolf.yaml").exists())

    def test_setting_an_existing_project_root_scans_and_prefills_a_picked_design(self):
        """The shallow scan always runs the moment project root is set to
        a directory that already exists (never skipped -- see
        _ProjectScanScreen's own docstring); picking a design out of it
        prefills RTL sources, design name/top, and constraints in one
        shot, matching the real tree shape found in
        sandboxes/manuelbv/wolf_tutorials/ALU (per-design subdirectories
        for hdl, but a flat <design>.constraints.sdc file)."""
        existing_root = self.root / "existing"
        hdl_dir = existing_root / "inputs" / "hdl" / "top"
        hdl_dir.mkdir(parents=True)
        (hdl_dir / "top.v").write_text("module top(input clk);\nendmodule\n", encoding="utf-8")
        constraints_dir = existing_root / "inputs" / "constraints"
        constraints_dir.mkdir(parents=True)
        (constraints_dir / "top.constraints.sdc").write_text("set_max_delay 1.0\n", encoding="utf-8")

        async def drive():
            app = EnvWizardApp("smoketest4")
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                self._select(main_list, "Project root: not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Type a path manually")
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = str(existing_root)
                await pilot.press("enter")
                await pilot.pause()

                # The scan screen appears unprompted, listing the one
                # design its shallow scan found.
                scan_opts = [o.prompt for o in app.screen.query_one(OptionList).options]
                self.assertEqual(scan_opts, ["top (missing: calibre, env, floorplans, flows, scripts, tb)"])
                self._select(app.screen.query_one(OptionList), scan_opts[0])
                await pilot.press("enter")
                await pilot.pause()

                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive())

        document = yaml.safe_load((self.state / "envs" / "smoketest4" / "wolf.yaml").read_text(encoding="utf-8"))
        self.assertEqual(document["design"]["name"], "top")
        self.assertEqual(document["design"]["top"], "top")
        # Already inside the project's own inputs/hdl/top/ -- save's
        # copy-into-project step has nothing to do, so the path is
        # untouched.
        self.assertEqual(document["design"]["sources"], [{"path": str((hdl_dir / "top.v").resolve())}])
        self.assertEqual(
            document["constraints"], {"files": [str((constraints_dir / "top.constraints.sdc").resolve())]},
        )
        # Saving must have scaffolded every missing standard directory --
        # not just left the scan's "missing: ..." list as a diagnosis.
        for category in ("calibre", "env", "floorplans", "flows", "scripts", "tb"):
            self.assertTrue((existing_root / "inputs" / category / "top").is_dir(), category)
        self.assertTrue((existing_root / "outputs" / "top").is_dir())
        self.assertTrue((existing_root / "workspace").is_dir())
        for lib_subdir in ("gds", "lef", "spice", "timing", "verilog"):
            self.assertTrue((existing_root / "inputs" / "lib" / lib_subdir).is_dir(), lib_subdir)

    def test_saving_scaffolds_missing_directories_for_a_brand_new_design(self):
        """Pointing at an existing project root with no tree at all yet
        (a new design, not found by the scan) must still get its
        standard directories on save -- "if proj_dir exists, create
        those folders the moment the user commits to saving" is the
        contract, not something that only applies to designs the scan
        already recognized."""
        existing_root = self.root / "brand-new"
        existing_root.mkdir()

        async def drive():
            app = EnvWizardApp("smoketest7")
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                self._select(main_list, "Project root: not set")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Type a path manually")
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = str(existing_root)
                await pilot.press("enter")
                await pilot.pause()
                # Nothing found -- esc continues manually.
                await pilot.press("escape")
                await pilot.pause()

                self._select(app.screen.query_one(OptionList), "Design name / top: not set")
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = "newdesign"
                await pilot.press("enter")  # top module name
                await pilot.pause()
                await pilot.press("enter")  # design name: blank = same as top
                await pilot.pause()

                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive())

        for category in ("calibre", "constraints", "env", "floorplans", "flows", "hdl", "scripts", "tb"):
            self.assertTrue((existing_root / "inputs" / category / "newdesign").is_dir(), category)
        self.assertTrue((existing_root / "outputs" / "newdesign").is_dir())
        self.assertTrue((existing_root / "workspace").is_dir())

        # No constraints.files were ever set -- a starter SDC template
        # gets generated and wired in automatically.
        sdc_path = existing_root / "inputs" / "constraints" / "newdesign" / "newdesign.sdc"
        self.assertTrue(sdc_path.is_file())
        self.assertIn("create_clock", sdc_path.read_text(encoding="utf-8"))
        document = yaml.safe_load((self.state / "envs" / "smoketest7" / "wolf.yaml").read_text(encoding="utf-8"))
        self.assertEqual(document["constraints"], {"files": [str(sdc_path.resolve())]})

        # A symlink to the saved wolf.yaml itself lands inside the
        # project tree, readable without ~/.wolf/envs/ at all.
        record_path = existing_root / "inputs" / "env" / "newdesign" / "wolf.smoketest7.yaml"
        self.assertTrue(record_path.is_file())
        self.assertTrue(record_path.is_symlink())
        self.assertEqual(
            record_path.resolve(), (self.state / "envs" / "smoketest7" / "wolf.yaml").resolve(),
        )
        self.assertEqual(
            yaml.safe_load(record_path.read_text(encoding="utf-8")),
            document,
        )


_FAKE_LEF = """\
VERSION 5.8 ;
MACRO FAKEBUFX2
  CLASS CORE ;
  SIZE 1.5 BY 2.0 ;
END FAKEBUFX2
MACRO FAKEBUFX4
  CLASS CORE ;
  SIZE 3.0 BY 2.0 ;
END FAKEBUFX4
MACRO FAKEINVX1
  CLASS CORE ;
  SIZE 0.8 BY 2.0 ;
END FAKEINVX1
MACRO FAKETIEHIX1
  CLASS CORE ;
  SIZE 0.5 BY 2.0 ;
END FAKETIEHIX1
MACRO FAKETIELOX1
  CLASS CORE ;
  SIZE 0.5 BY 2.0 ;
END FAKETIELOX1
LAYER FAKEM1
  TYPE ROUTING ;
END FAKEM1
LAYER FAKEM2
  TYPE ROUTING ;
END FAKEM2
"""


class CadenceCellBrowserTests(unittest.TestCase):
    """`wolf env menu`'s CTS/tie-off/routing cell browser -- picks real
    cell/layer names out of a resolved technology's own (synthetic, for
    this test) LEF files instead of hand-editing YAML. Only made-up
    names are used anywhere in this fixture (FAKEBUFX2, FAKEM1, ...),
    never real PDK data."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-cell-browser-menu-")
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.registry = self.root / "registry"
        self.state.mkdir(parents=True)
        self.variables = patch.dict(
            os.environ,
            {"WOLF_HOME": str(self.state), "WOLF_REGISTRY": str(self.registry)},
        )
        self.variables.start()
        self._register_pdk()
        self.env_dir = self.state / "envs" / "cellbrowser-demo"
        self.env_dir.mkdir(parents=True)
        (self.env_dir / "wolf.yaml").write_text(
            "schema: wolf.environment/v1\nname: cellbrowser-demo\n"
            "design:\n  name: demo\n  top: demo\n  sources:\n    - path: /dev/null\n"
            "technology:\n  package: pdk/fakecells\n"
            "flow:\n  backend: cadence-flowtool\n"
            f"project:\n  root: {self.root / 'project'}\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.variables.stop()
        self.temporary.cleanup()

    def _design_setup(self) -> dict:
        path = design_setup_path(self.root / "project", "demo")
        return yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def _register_pdk(self):
        manifest = {
            "schema_version": 1, "kind": "pdk", "name": "fakecells", "description": "fakecells",
            "source": {"type": "local-path", "root": str(self.root / "pdksrc"), "revision": "V1"},
            "validation": {"required_paths": []},
            "metadata": {"technology": {
                "name": "fakecells",
                "physical": {"technology_lefs": ["fake_tech.lef"]},
            }},
        }
        pdk_dir = self.registry / "pdk"
        pdk_dir.mkdir(parents=True, exist_ok=True)
        (pdk_dir / "fakecells.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
        installation = self.state / "packages" / "pdk" / "fakecells" / "V1"
        (installation / "source").mkdir(parents=True)
        (installation / "source" / "fake_tech.lef").write_text(_FAKE_LEF, encoding="utf-8")
        (installation / "installed.yaml").write_text(
            yaml.safe_dump({
                "package": "pdk/fakecells", "revision": "V1", "source_revision": "V1",
                "content_path": "source", "installed_at": "2026-10-05T00:00:00Z",
            }),
            encoding="utf-8",
        )

    def _select(self, option_list, label):
        options = [o.prompt for o in option_list.options]
        option_list.highlighted = options.index(label)

    async def _open_field(self, pilot, app, submenu_label):
        self._select(app.query_one(OptionList), "CTS / tie-off / routing cells...")
        await pilot.press("enter")
        await pilot.pause()
        self._select(app.screen.query_one(OptionList), submenu_label)
        await pilot.press("enter")
        await pilot.pause()
        # The checklist loads in a background worker (real files would
        # take real time to scan; the synthetic fixture here is instant,
        # but still crosses a thread/call_from_thread round trip).
        for _ in range(5):
            await pilot.pause()

    def test_filter_narrows_the_list_live_and_select_all_stores_the_visible_matches(self):
        async def drive():
            app = EnvWizardApp("cellbrowser-demo")
            async with app.run_test() as pilot:
                app.technology_package = "pdk/fakecells"
                await self._open_field(pilot, app, "CTS buffer cells (default) [0]")
                results = app.screen.query_one("#results", OptionList)
                self.assertEqual(len(list(results.options)), 5)  # every fake cell, unfiltered
                app.screen.query_one(Input).value = "FAKEBUF*"
                await pilot.pause()
                self.assertEqual(
                    sorted(o.id for o in results.options),
                    ["FAKEBUFX2", "FAKEBUFX4"],
                )
                await pilot.press("tab")  # filter -> list
                await pilot.pause()
                self.assertTrue(results.has_focus)
                await pilot.press("a")  # select all visible (the 2 filtered matches)
                await pilot.pause()
                await pilot.press("escape")  # done with the checklist, back to the submenu
                await pilot.pause()
                await pilot.press("escape")  # done with the submenu, back to the main menu
                await pilot.pause()
                await pilot.press("s")
                await pilot.pause()
        asyncio.run(drive())
        setup = self._design_setup()
        self.assertEqual(sorted(setup["cts_buffer_cells"]), ["FAKEBUFX2", "FAKEBUFX4"])

    def test_toggling_one_entry_by_hand_stores_just_that_one(self):
        async def drive():
            app = EnvWizardApp("cellbrowser-demo")
            async with app.run_test() as pilot:
                app.technology_package = "pdk/fakecells"
                await self._open_field(pilot, app, "CTS inverter cells (default) [0]")
                await pilot.press("tab")
                await pilot.pause()
                results = app.screen.query_one("#results", OptionList)
                index = [o.id for o in results.options].index("FAKEINVX1")
                results.highlighted = index
                await pilot.press("enter")  # toggle just this one
                await pilot.pause()
                await pilot.press("escape")  # done with the checklist, back to the submenu
                await pilot.pause()
                await pilot.press("escape")  # done with the submenu, back to the main menu
                await pilot.pause()
                await pilot.press("s")
                await pilot.pause()
        asyncio.run(drive())
        self.assertEqual(self._design_setup()["cts_inverter_cells"], ["FAKEINVX1"])

    def test_deselect_all_clears_the_visible_selection(self):
        async def drive():
            app = EnvWizardApp("cellbrowser-demo")
            async with app.run_test() as pilot:
                app.technology_package = "pdk/fakecells"
                await self._open_field(pilot, app, "CTS clock-gating cells [0]")
                await pilot.press("tab")
                await pilot.pause()
                await pilot.press("a")  # select every cell
                await pilot.pause()
                await pilot.press("d")  # then deselect every (visible) cell
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("s")
                await pilot.pause()
        asyncio.run(drive())
        self.assertNotIn("cts_clock_gating_cells", self._design_setup())

    def test_a_filter_matching_nothing_shows_no_matches_and_nothing_is_selectable(self):
        async def drive():
            app = EnvWizardApp("cellbrowser-demo")
            async with app.run_test() as pilot:
                app.technology_package = "pdk/fakecells"
                await self._open_field(pilot, app, "CTS buffer cells (default) [0]")
                app.screen.query_one(Input).value = "NOTHING_MATCHES_THIS*"
                await pilot.pause()
                results = app.screen.query_one("#results", OptionList)
                self.assertEqual([o.prompt for o in results.options], ["(no matches)"])
                await pilot.press("escape")
                await pilot.pause()
        asyncio.run(drive())
        # Nothing was selected (no matches to select) -- cts never appears.
        self.assertNotIn("cts_buffer_cells", self._design_setup())

    def test_tieoff_cells_are_capped_at_two(self):
        async def drive():
            app = EnvWizardApp("cellbrowser-demo")
            async with app.run_test() as pilot:
                app.technology_package = "pdk/fakecells"
                await self._open_field(pilot, app, "Tie-off cells [0]")
                await pilot.press("tab")
                await pilot.pause()
                results = app.screen.query_one("#results", OptionList)
                for name in ("FAKETIEHIX1", "FAKETIELOX1", "FAKEBUFX2"):
                    index = [o.id for o in results.options].index(name)
                    results.highlighted = index
                    await pilot.press("enter")
                    await pilot.pause()
                # The third toggle (FAKEBUFX2) must be rejected -- only
                # the first two stay checked.
                checked = sorted(
                    o.id for o in results.options if o.prompt.startswith("[x]")
                )
                self.assertEqual(checked, ["FAKETIEHIX1", "FAKETIELOX1"])
                await pilot.press("escape")  # done with the checklist, back to the submenu
                await pilot.pause()
                await pilot.press("escape")  # done with the submenu, back to the main menu
                await pilot.pause()
                await pilot.press("s")
                await pilot.pause()
        asyncio.run(drive())
        self.assertEqual(
            sorted(self._design_setup()["add_tieoffs_cells"]), ["FAKETIEHIX1", "FAKETIELOX1"],
        )

    def test_clock_routing_preferred_layer_is_picked_from_resolved_layers(self):
        async def drive():
            app = EnvWizardApp("cellbrowser-demo")
            async with app.run_test() as pilot:
                app.technology_package = "pdk/fakecells"
                self._select(app.query_one(OptionList), "CTS / tie-off / routing cells...")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Clock routing trunk top layer [-]")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "FAKEM2")
                await pilot.press("enter")
                await pilot.pause()
                # Picking an option on _PickScreen dismisses it immediately,
                # back at the (freshly reopened) cts/tieoffs submenu --
                # escape once more to reach the main menu.
                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("s")
                await pilot.pause()
        asyncio.run(drive())
        self.assertEqual(
            self._design_setup()["clock_routing_types"]["trunk"]["top_preferred_layer"], "FAKEM2",
        )


class BundledFlowNameTests(unittest.TestCase):
    """The bundled-default flow must never be written as flow.name:
    "default" -- "default" is not a real flow identity, it collided with
    flow.name's own genus-syn-generic/-map/-opt shorthand lookup, and a
    bare `wolf run`/`wolf run --plan` (no -from/-to) crashed outright on
    every environment this wizard had ever saved with a bundled flow."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-bundled-flow-name-")
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.state.mkdir(parents=True)
        self.variables = patch.dict(os.environ, {"WOLF_HOME": str(self.state)})
        self.variables.start()
        self.env_dir = self.state / "envs" / "bundled-demo"
        self.env_dir.mkdir(parents=True)
        (self.env_dir / "wolf.yaml").write_text(
            "schema: wolf.environment/v1\nname: bundled-demo\n"
            "design:\n  name: demo\n  top: demo\n  sources:\n    - path: /dev/null\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.variables.stop()
        self.temporary.cleanup()

    def test_saving_a_bundled_flow_backend_writes_no_name_field(self):
        async def drive():
            app = EnvWizardApp("bundled-demo")
            async with app.run_test() as pilot:
                app.backend = "cadence-flowtool"
                await pilot.press("s")
                await pilot.pause()
        asyncio.run(drive())
        saved = yaml.safe_load((self.env_dir / "wolf.yaml").read_text(encoding="utf-8"))
        self.assertEqual(saved["flow"], {"backend": "cadence-flowtool"})


class RoundTripUntrackedFieldsTests(unittest.TestCase):
    """Fields the wizard has no UI for (resources.threads, backend.*
    overrides, env.*, constraints.clocks/lines/floorplan_def) must survive
    a save unrelated to them, exactly as an editor round-trips a field it
    renders no widget for. Regression: reopening ibex-fabulous-small-synth
    and saving after only adding a second SDC file silently dropped
    resources.threads: 64 -- every one of these fields was simply never
    captured into wizard state on load, so _save rebuilt the document
    without them."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-roundtrip-")
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.state.mkdir(parents=True)
        self.variables = patch.dict(os.environ, {"WOLF_HOME": str(self.state)})
        self.variables.start()
        self.env_dir = self.state / "envs" / "roundtrip-demo"
        self.env_dir.mkdir(parents=True)
        (self.env_dir / "wolf.yaml").write_text(
            "schema: wolf.environment/v1\nname: roundtrip-demo\n"
            "design:\n  name: demo\n  top: demo\n  sources:\n    - path: /dev/null\n"
            "flow:\n  backend: cadence-flowtool\n"
            "resources:\n  threads: 64\n"
            "env:\n  GENUS_NUM_CPUS: \"64\"\n"
            "backend:\n  cadence-flowtool:\n    genus:\n      set_db:\n        x: 1\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.variables.stop()
        self.temporary.cleanup()

    def test_resources_threads_and_other_untracked_fields_survive_an_unrelated_save(self):
        async def drive():
            app = EnvWizardApp("roundtrip-demo")
            async with app.run_test() as pilot:
                self.assertEqual(app.threads, 64)
                await pilot.press("s")
                await pilot.pause()
        asyncio.run(drive())
        saved = yaml.safe_load((self.env_dir / "wolf.yaml").read_text(encoding="utf-8"))
        self.assertEqual(saved["resources"], {"threads": 64})
        self.assertEqual(saved["env"], {"GENUS_NUM_CPUS": "64"})
        self.assertEqual(saved["backend"], {"cadence-flowtool": {"genus": {"set_db": {"x": 1}}}})


class ReopenManifestSourceTests(unittest.TestCase):
    """Reopening an existing environment whose design.sources already used
    a manifest entry, then re-saving without touching RTL at all, must not
    corrupt that entry. Regression: the wizard's own load path only knew
    about package/path when rebuilding self.sources from the loaded
    profile, silently dropping a manifest entry's real reference and
    turning it into {"path": None} -- which then failed to save with
    "design.sources[0] must set exactly one of package, path, or
    manifest", even though nothing about the RTL was being changed."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-reopen-manifest-")
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.state.mkdir(parents=True)
        self.variables = patch.dict(os.environ, {"WOLF_HOME": str(self.state)})
        self.variables.start()

        design_dir = self.root / "rtl"
        design_dir.mkdir()
        (design_dir / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
        (design_dir / "manifest.toml").write_text(
            'schema_version = 1\nname = "demo"\ntop = "top"\n'
            'verilog_sources = "manifests/verilog-sources.flist"\n',
            encoding="utf-8",
        )
        (design_dir / "manifests").mkdir()
        (design_dir / "manifests" / "verilog-sources.flist").write_text("../top.v\n", encoding="utf-8")

        self.env_dir = self.state / "envs" / "reopen-demo"
        self.env_dir.mkdir(parents=True)
        (self.env_dir / "wolf.yaml").write_text(
            "schema: wolf.environment/v1\n"
            "name: reopen-demo\n"
            "design:\n"
            "  name: demo\n"
            "  top: top\n"
            "  sources:\n"
            f"    - manifest: {design_dir / 'manifest.toml'}\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.variables.stop()
        self.temporary.cleanup()

    def test_resaving_an_unchanged_manifest_source_does_not_error(self):
        notifications: list = []

        async def drive():
            app = EnvWizardApp("reopen-demo")
            async with app.run_test() as pilot:
                # The real root cause: the wizard's own load path must
                # recover the manifest entry, not silently turn it into
                # {"path": None}.
                self.assertEqual(app.sources, [{"manifest": str((self.root / "rtl" / "manifest.toml"))}])
                original_notify = app.notify
                app.notify = lambda message, **kwargs: (
                    notifications.append((message, kwargs.get("severity", "information"))),
                    original_notify(message, **kwargs),
                )[0]
                await pilot.press("s")
                await pilot.pause()
        asyncio.run(drive())
        self.assertTrue(notifications, "expected a save notification")
        self.assertFalse(
            [n for n in notifications if n[1] == "error"],
            f"save reported an error: {notifications}",
        )
        saved = yaml.safe_load((self.env_dir / "wolf.yaml").read_text(encoding="utf-8"))
        self.assertEqual(
            saved["design"]["sources"], [{"manifest": str(self.root / "rtl" / "manifest.toml")}],
        )


class BrowseManifestDetectionTests(unittest.TestCase):
    """The regular browse-filesystem add flow (not a separate menu entry)
    must recognize a real manifest.toml and use it as-is -- a directory
    scan can never recover its compile order or FABULOUS_EFPGA/work
    library split, so once one is found there is nothing a per-file scan
    would add on top of it."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-browse-manifest-")
        self.root = Path(self.temporary.name)
        self.design_dir = self.root / "rtl"
        self.design_dir.mkdir()
        (self.design_dir / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
        (self.design_dir / "manifest.toml").write_text(
            'schema_version = 1\nname = "demo"\ntop = "top"\n', encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _run_browse(self, start: Path) -> list:
        result: list = []

        class _Harness(App):
            def on_mount(self) -> None:
                def handle(value) -> None:
                    result.extend(value or [])
                self.push_screen(_BrowseScreen(str(start), detect_manifest=True), handle)

        async def drive():
            async with _Harness().run_test() as pilot:
                await pilot.press("a")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
        asyncio.run(drive())
        return result

    def test_adding_a_directory_with_a_manifest_toml_yields_one_manifest_marker(self):
        result = self._run_browse(self.design_dir)
        self.assertEqual(result, [{"manifest": str((self.design_dir / "manifest.toml").resolve())}])

    def test_without_detect_manifest_the_old_per_file_scan_still_runs(self):
        result: list = []
        design_dir = self.design_dir

        class _Harness(App):
            def on_mount(self) -> None:
                def handle(value) -> None:
                    result.extend(value or [])
                self.push_screen(
                    _BrowseScreen(str(design_dir), detect_manifest=False), handle,
                )

        async def drive():
            async with _Harness().run_test() as pilot:
                await pilot.press("a")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
        asyncio.run(drive())
        self.assertEqual(result, [str((self.design_dir / "top.v").resolve())])

    def test_manifest_top_is_suggested_without_regex_scanning_hdl_text(self):
        """A manifest declares its own top directly -- no reason to make
        the user go look it up, and no reason to regex-scan the HDL text
        for it either, unlike a loose path entry."""
        entry = {"manifest": str((self.design_dir / "manifest.toml").resolve())}
        self.assertEqual(_scan_modules([entry]), ["top"])

    def test_a_broken_manifest_is_rejected_immediately_not_deferred_to_wolf_run(self):
        """Pointing at a manifest.toml that references a .flist that
        doesn't exist is caught the moment it's added, not silently
        accepted and only discovered later at `wolf run`."""
        broken_dir = self.root / "broken"
        broken_dir.mkdir()
        (broken_dir / "manifest.toml").write_text(
            'schema_version = 1\nname = "broken"\ntop = "top"\n'
            'verilog_sources = "manifests/verilog-sources.flist"\n',
            encoding="utf-8",
        )
        result = self._run_browse(broken_dir)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()

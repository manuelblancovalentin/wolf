import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml
from textual.widgets import Input, OptionList, Static

from wolf.env_menu import EnvWizardApp


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
        self.assertEqual(document["constraints"], {"files": [str(self.sdc_path)]})
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
                self.assertEqual(scan_opts, ["top (missing: calibre, env, floorplans, scripts, tb)"])
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


if __name__ == "__main__":
    unittest.main()

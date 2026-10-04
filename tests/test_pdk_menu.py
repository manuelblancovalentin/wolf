import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from wolf.environment import _technology_inputs
from wolf.package.registry import PackageRegistry, load_manifest
from wolf.pdk_menu import PdkMenuApp, _default_document, open_pdk_menu
from textual.widgets import Input, OptionList, Static


class PdkMenuEndToEndTests(unittest.TestCase):
    """Drives the real TUI (Textual's own headless Pilot), not just the
    underlying schema -- this is what actually caught the flow.template.yaml
    path-resolution bug in the cadence-genus work, so the same bar applies
    here: exercise the real screens, not just the data they produce."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-pdk-menu-")
        self.root = Path(self.temporary.name)
        self.lib_root = self.root / "libroot" / "lib"
        self.lib_root.mkdir(parents=True)
        (self.lib_root / "typical.lib").write_text("-- typical --\n", encoding="utf-8")
        (self.lib_root / "worst.lib").write_text("-- worst --\n", encoding="utf-8")
        self.manifest_path = self.root / "registry" / "pdk" / "smoketest.yaml"

    def tearDown(self):
        self.temporary.cleanup()

    def test_building_a_track_vth_corner_through_the_real_screens(self):
        data = _default_document("smoketest", str(self.root / "libroot"))

        async def drive():
            app = PdkMenuApp("smoketest", self.manifest_path, data, is_new=True)
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                main_list.highlighted = 3  # "Tracks"
                await pilot.press("enter")
                await pilot.pause()

                await pilot.press("a")
                await pilot.pause()
                app.screen.query_one(Input).value = "9T"
                await pilot.press("enter")
                await pilot.pause()

                await pilot.press("a")
                await pilot.pause()
                app.screen.query_one(Input).value = "lvt"
                await pilot.press("enter")
                await pilot.pause()

                vth_list = app.screen.query_one(OptionList)
                vth_list.highlighted = 0  # "Liberty corners"
                await pilot.press("enter")
                await pilot.pause()

                await pilot.press("a")
                await pilot.pause()
                app.screen.query_one(Input).value = "typical"
                await pilot.press("enter")
                await pilot.pause()

                corner_list = app.screen.query_one(OptionList)
                corner_list.highlighted = 0  # "Libraries"
                await pilot.press("enter")
                await pilot.pause()

                await pilot.press("a")  # browse
                await pilot.pause()
                await pilot.press("down")  # into lib/
                await pilot.pause()
                await pilot.press("enter")  # expand lib/
                await pilot.pause()
                await pilot.press("down")  # first file
                await pilot.pause()
                await pilot.press("a")  # add it
                await pilot.pause()
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("a")  # add second file
                await pilot.pause()
                await pilot.press("escape")  # done browsing -- this is what records last_browsed_dir
                await pilot.pause()
                self.assertEqual(app.last_browsed_dir, str(self.lib_root))
                await pilot.press("escape")  # back to CornerEditScreen (FileListScreen done)
                await pilot.pause()

                corner_edit_list = app.screen.query_one(OptionList)
                corner_edit_list.highlighted = 1  # "Format"
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = "ecsm"
                await pilot.press("enter")
                await pilot.pause()

                for _ in range(5):  # unwind every remaining nested screen back to the main menu
                    await pilot.pause()
                    await pilot.press("escape")
                await pilot.pause()

                await pilot.press("s")  # save
                await pilot.pause()

        asyncio.run(drive())

        self.assertTrue(self.manifest_path.is_file())
        document = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        typical = document["metadata"]["technology"]["tracks"]["9T"]["vths"]["lvt"] \
            ["timing"]["corners"]["typical"]
        self.assertEqual(sorted(typical["libraries"]), ["lib/typical.lib", "lib/worst.lib"])
        self.assertEqual(typical["format"], "ecsm")

        manifest = load_manifest(self.manifest_path)

        class FakeInstalled:
            content_path = self.root / "libroot"
        resolved = _technology_inputs(manifest, FakeInstalled())
        self.assertEqual((resolved.track, resolved.vth), ("9T", "lvt"))
        self.assertEqual(len(resolved.timing_corners), 1)
        self.assertEqual(resolved.timing_corners[0].name, "typical")
        self.assertEqual(resolved.timing_corners[0].format, "ecsm")

    def _select(self, option_list, label):
        options = [o.prompt for o in option_list.options]
        option_list.highlighted = options.index(label)

    def test_front_end_timing_power_navigation_creates_track_vth_corner(self):
        """Front-End -> Timing/Power -> ECSM should land you on the same
        real corner editor as the Tracks path, having lazily created the
        track/vth/corner along the way -- the library-shaped entry point
        this message's whole redesign is about."""
        data = _default_document("smoketest", str(self.root / "libroot"))

        async def drive():
            app = PdkMenuApp("smoketest", self.manifest_path, data, is_new=True)
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                self._select(main_list, "Front-End (timing/power, verilog)")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Timing / Power (lib: ECSM/NLDM/CCS)")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "ECSM")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "+ Create new...")  # track
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = "9T"
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "+ Create new...")  # vth
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = "lvt"
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "+ Create new...")  # corner
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = "typical"
                await pilot.press("enter")
                await pilot.pause()
                # Now on _CornerEditScreen, with format pre-set to ecsm.
                self._select(app.screen.query_one(OptionList), "Libraries (0 file(s))")
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                await pilot.press("down")  # into lib/
                await pilot.pause()
                await pilot.press("enter")  # expand
                await pilot.pause()
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("a")  # add first file
                await pilot.pause()
                await pilot.press("escape")  # done browsing -> back to FileListScreen
                await pilot.pause()
                await pilot.press("escape")  # FileListScreen done -> back to CornerEditScreen
                await pilot.pause()
                await pilot.press("escape")  # CornerEditScreen done -> back to the corner picker,
                await pilot.pause()          # not the main menu -- one level at a time, not a jump
                title = app.screen.query_one("#dialog-title", Static).content
                self.assertIn("smoketest / Front-End / Timing-Power / ECSM / 9T / lvt", title)
                self._select(app.screen.query_one(OptionList), "typical")
                await pilot.press("escape")  # corner picker cancelled -> up to the vth picker
                await pilot.pause()
                self.assertIn("9T\n", app.screen.query_one("#dialog-title", Static).content)
                self._select(app.screen.query_one(OptionList), "lvt")
                await pilot.press("escape")  # vth picker cancelled -> up to the track picker
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T")
                await pilot.press("escape")  # track picker cancelled -> up to the format picker
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "ECSM")
                await pilot.press("escape")  # format picker cancelled -> up to the category picker
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Timing / Power (lib: ECSM/NLDM/CCS)")
                await pilot.press("escape")  # category picker cancelled -> up to the main menu
                await pilot.pause()
                self.assertEqual(len(app.screen_stack), 1)
                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive())

        document = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        corner = document["metadata"]["technology"]["tracks"]["9T"]["vths"]["lvt"] \
            ["timing"]["corners"]["typical"]
        self.assertEqual(corner["format"], "ecsm")
        self.assertEqual(len(corner["libraries"]), 1)

        manifest = load_manifest(self.manifest_path)

        class FakeInstalled:
            content_path = self.root / "libroot"
        resolved = _technology_inputs(manifest, FakeInstalled())
        self.assertEqual((resolved.track, resolved.vth), ("9T", "lvt"))
        self.assertEqual(resolved.timing_corners[0].format, "ecsm")

    def test_back_end_lef_navigation_creates_a_named_metal_stack(self):
        """Back-End -> LEF -> LEF files should land you picking/creating a
        metal stack for an existing track/vth, writing lef as a
        {stack: [...]} mapping -- the multi-stack shape plain flat lists
        can't express."""
        lef_dir = self.root / "libroot" / "lef"
        lef_dir.mkdir()
        (lef_dir / "9lmT2.lef").write_text("-- lef --\n", encoding="utf-8")
        data = _default_document("smoketest", str(self.root / "libroot"))
        data["metadata"]["technology"]["tracks"] = {"9T": {"vths": {"lvt": {
            "timing": {"corners": {"typical": {"libraries": ["lib/typical.lib"]}}},
        }}}}

        async def drive():
            app = PdkMenuApp("smoketest", self.manifest_path, data, is_new=True)
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                self._select(main_list, "Back-End (LEF, GDS, techfiles, SPICE)")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "LEF")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "LEF files")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T")  # existing track
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "lvt")  # existing vth
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "+ Create new...")  # stack
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = "9lmT2"
                await pilot.press("enter")
                await pilot.pause()
                # Now directly on the LEF-files _FileListScreen for that stack.
                await pilot.press("a")
                await pilot.pause()
                await pilot.press("down")  # into lef/ (the only child)
                await pilot.pause()
                await pilot.press("enter")  # expand
                await pilot.pause()
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("a")  # add 9lmT2.lef
                await pilot.pause()
                await pilot.press("escape")  # done browsing -> back to FileListScreen
                await pilot.pause()
                await pilot.press("escape")  # FileListScreen done -> back to the stack picker,
                await pilot.pause()          # not the main menu -- one level at a time
                title = app.screen.query_one("#dialog-title", Static).content
                self.assertIn("smoketest / Back-End / LEF files / 9T / lvt", title)
                self._select(app.screen.query_one(OptionList), "9lmT2")
                await pilot.press("escape")  # stack picker cancelled -> up to the vth picker
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "lvt")
                await pilot.press("escape")  # vth picker cancelled -> up to the track picker
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T")
                await pilot.press("escape")  # track picker cancelled -> up to LEF files/Techfiles
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "LEF files")
                await pilot.press("escape")  # that picker cancelled -> up to the Back-End category
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "LEF")
                await pilot.press("escape")  # category picker cancelled -> up to the main menu
                await pilot.pause()
                self.assertEqual(len(app.screen_stack), 1)
                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive())

        document = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        lef = document["metadata"]["technology"]["tracks"]["9T"]["vths"]["lvt"]["lef"]
        self.assertEqual(lef, {"9lmT2": ["lef/9lmT2.lef"]})

        manifest = load_manifest(self.manifest_path)
        from wolf.environment import ComponentReference

        class FakeInstalled:
            content_path = self.root / "libroot"
        resolved = _technology_inputs(
            manifest, FakeInstalled(), ComponentReference(track="9T", vth="lvt", metal_stack="9lmT2"),
        )
        self.assertEqual(resolved.metal_stack, "9lmT2")
        self.assertEqual([p.name for p in resolved.technology_lefs], ["9lmT2.lef"])

    def test_back_end_gds_navigation_is_flat_not_metal_stack_keyed(self):
        """Unlike LEF, GDS -> track -> vth lands directly on a flat file
        list -- no metal-stack picker in between -- since a cell's own
        GDS geometry doesn't vary by metal stack."""
        gds_dir = self.root / "libroot" / "gds"
        gds_dir.mkdir()
        (gds_dir / "x.gds").write_text("-- gds --\n", encoding="utf-8")
        data = _default_document("smoketest", str(self.root / "libroot"))
        data["metadata"]["technology"]["tracks"] = {"9T": {"vths": {"lvt": {
            "timing": {"corners": {"typical": {"libraries": ["lib/typical.lib"]}}},
        }}}}

        async def drive():
            app = PdkMenuApp("smoketest", self.manifest_path, data, is_new=True)
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                self._select(main_list, "Back-End (LEF, GDS, techfiles, SPICE)")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "GDS")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "lvt")
                await pilot.press("enter")
                await pilot.pause()
                # Straight onto the flat GDS-files _FileListScreen -- no
                # "pick/create a metal stack" screen in between.
                await pilot.press("a")
                await pilot.pause()
                await pilot.press("down")  # into gds/ (the only child)
                await pilot.pause()
                await pilot.press("enter")  # expand
                await pilot.pause()
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("a")  # add x.gds
                await pilot.pause()
                await pilot.press("escape")  # done browsing
                await pilot.pause()
                while len(app.screen_stack) > 1:
                    await pilot.press("escape")
                    await pilot.pause()
                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive())

        document = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        gds = document["metadata"]["technology"]["tracks"]["9T"]["vths"]["lvt"]["gds"]
        self.assertEqual(gds, ["gds/x.gds"])

    def test_opening_a_vth_migrates_legacy_per_stack_gds_to_a_flat_list(self):
        """A vth saved before gds stopped being stack-keyed still has its
        old {stack: [...]} shape on disk -- opening it (either path)
        flattens it automatically instead of leaving stale, now-unreadable
        data sitting there untouched."""
        data = _default_document("smoketest", str(self.root / "libroot"))
        data["metadata"]["technology"]["tracks"] = {"9T": {"vths": {"lvt": {
            "timing": {"corners": {"typical": {"libraries": ["lib/typical.lib"]}}},
            "gds": {"9lmT2": ["gds/a.gds"], "7lmT1": ["gds/b.gds"]},
            "default_metal_stack": "7lmT1",
        }}}}

        async def drive():
            app = PdkMenuApp("smoketest", self.manifest_path, data, is_new=True)
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                self._select(main_list, "Tracks (1 track/vth group(s))")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T (1 vth(s))")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "lvt (1 corner(s))")
                await pilot.press("enter")  # opening the vth triggers migration
                await pilot.pause()
                while len(app.screen_stack) > 1:
                    await pilot.press("escape")
                    await pilot.pause()
                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive())

        document = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        gds = document["metadata"]["technology"]["tracks"]["9T"]["vths"]["lvt"]["gds"]
        # default_metal_stack ("7lmT1") wins the migration pick.
        self.assertEqual(gds, ["gds/b.gds"])

    def test_back_end_metal_stack_picker_supports_clone_too(self):
        """The metal-stack picker reached via Back-End -> LEF -> LEF
        files -> track -> vth is a different screen class
        (_PickCreateDeleteScreen) than the Tracks path's own
        metal-stacks screen -- clone has to be wired into both, not just
        one, or it silently only works from Tracks."""
        lef_dir = self.root / "libroot" / "lef"
        lef_dir.mkdir()
        (lef_dir / "9t_hvt_9lmT2.lef").write_text("x", encoding="utf-8")
        (lef_dir / "9t_hvt_7lmT1.lef").write_text("x", encoding="utf-8")
        data = _default_document("smoketest", str(self.root / "libroot"))
        data["metadata"]["technology"]["tracks"] = {"9T": {"vths": {"hvt": {
            "timing": {"corners": {"typical": {"libraries": ["lib/typical.lib"]}}},
            "lef": {"9lmT2": ["lef/9t_hvt_9lmT2.lef"]},
        }}}}

        async def drive():
            app = PdkMenuApp("smoketest", self.manifest_path, data, is_new=True)
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                self._select(main_list, "Back-End (LEF, GDS, techfiles, SPICE)")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "LEF")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "LEF files")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "hvt")
                await pilot.press("enter")
                await pilot.pause()
                # On the metal-stack picker: "c" should be offered, same as
                # the Tracks path's own metal-stacks screen.
                hint = app.screen.query_one("#dialog-hint", Static).content
                self.assertIn("c: clone highlighted", hint)
                self._select(app.screen.query_one(OptionList), "9lmT2")
                await pilot.press("c")  # clone stack
                await pilot.pause()
                app.screen.query_one(Input).value = "7lmT1"
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                app.screen.query_one(Input).value = "9lmT2"
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = "7lmT1"
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("escape")  # done adding pairs -> preview
                await pilot.pause()
                preview_hint = app.screen.query_one("#dialog-hint", Static).content
                self.assertIn("1 path(s), 0 missing", preview_hint)
                await pilot.press("c")  # confirm
                await pilot.pause()
                # Back on the stack picker with both stacks now listed.
                stacks = app.screen.query_one(OptionList)
                self.assertEqual(
                    sorted(o.prompt for o in stacks.options if o.prompt != "+ Create new..."),
                    ["7lmT1", "9lmT2"],
                )
                while len(app.screen_stack) > 1:
                    await pilot.press("escape")
                    await pilot.pause()
                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive())

        document = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        lef = document["metadata"]["technology"]["tracks"]["9T"]["vths"]["hvt"]["lef"]
        self.assertEqual(lef["7lmT1"], ["lef/9t_hvt_7lmT1.lef"])
        # The source stack is untouched by cloning it.
        self.assertEqual(lef["9lmT2"], ["lef/9t_hvt_9lmT2.lef"])

    def test_front_end_corner_picker_deletes_an_entry_in_place(self):
        """A legacy corner (renamed away from, e.g. PVT_1P08V_25C once its
        real PVT code is known) has no other way to be removed from the
        library-shaped Front-End navigation -- 'd' on the corner picker
        must delete it without closing the picker, matching the delete
        convention everywhere else in this menu."""
        data = _default_document("smoketest", str(self.root / "libroot"))
        data["metadata"]["technology"]["tracks"] = {"9T": {"vths": {"lvt": {
            "timing": {"corners": {
                "PVT_1P08V_25C": {"libraries": ["lib/typical.lib"], "format": "liberty"},
            }},
        }}}}

        async def drive():
            app = PdkMenuApp("smoketest", self.manifest_path, data, is_new=True)
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                self._select(main_list, "Front-End (timing/power, verilog)")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Timing / Power (lib: ECSM/NLDM/CCS)")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Other / custom format...")
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = "liberty"
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T")  # existing track
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "lvt")  # existing vth
                await pilot.press("enter")
                await pilot.pause()
                # At the corner picker: the legacy corner plus "+ Create new...".
                corner_list = app.screen.query_one(OptionList)
                self.assertEqual(
                    [o.prompt for o in corner_list.options], ["PVT_1P08V_25C", "+ Create new..."],
                )
                corner_list.highlighted = 0
                await pilot.press("d")  # delete it in place
                await pilot.pause()
                self.assertEqual([o.prompt for o in corner_list.options], ["+ Create new..."])
                await pilot.press("escape")  # corner picker cancelled -> up to the vth picker
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "lvt")
                await pilot.press("escape")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T")
                await pilot.press("escape")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Other / custom format...")
                await pilot.press("escape")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Timing / Power (lib: ECSM/NLDM/CCS)")
                await pilot.press("escape")
                await pilot.pause()
                self.assertEqual(len(app.screen_stack), 1)
                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive())

        document = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        corners = document["metadata"]["technology"]["tracks"]["9T"]["vths"]["lvt"]["timing"]["corners"]
        self.assertEqual(corners, {})

    def test_front_end_corner_picker_shows_every_corner_regardless_of_format(self):
        """Corners created via the Tracks path default to format: liberty
        unless hand-edited -- Front-End -> Timing/Power -> ECSM must still
        show them all, the same list Tracks shows for the same vth, not
        just the ones that happen to already be tagged format: ecsm. An
        earlier version filtered by format here, hiding real corners."""
        data = _default_document("smoketest", str(self.root / "libroot"))
        data["metadata"]["technology"]["tracks"] = {"9T": {"vths": {"rvt": {
            "timing": {"corners": {
                "bc": {"libraries": ["lib/typical.lib"], "format": "ecsm"},
                "tc": {"libraries": ["lib/typical.lib"]},  # format defaults to liberty
                "wc": {"libraries": ["lib/typical.lib"]},  # format defaults to liberty
            }},
        }}}}

        async def drive():
            app = PdkMenuApp("smoketest", self.manifest_path, data, is_new=True)
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                self._select(main_list, "Front-End (timing/power, verilog)")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Timing / Power (lib: ECSM/NLDM/CCS)")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "ECSM")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "rvt")
                await pilot.press("enter")
                await pilot.pause()
                corner_list = app.screen.query_one(OptionList)
                self.assertEqual(
                    sorted(o.prompt for o in corner_list.options if o.prompt != "+ Create new..."),
                    ["bc", "tc", "wc"],
                )
                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()

        asyncio.run(drive())

    def test_clone_vth_regex_substitutes_paths_and_drops_missing_ones(self):
        """Populating a second vth (lvt) by cloning an already-populated one
        (rvt) and regex-substituting its paths is the fast way to fill in a
        new vth's corners -- a path that doesn't exist after substitution is
        dropped rather than left pointing at nothing."""
        lib_dir = self.root / "libroot" / "lib"
        (lib_dir / "9t_rvt_typical.lib").write_text("-- typical rvt --\n", encoding="utf-8")
        (lib_dir / "9t_rvt_worst.lib").write_text("-- worst rvt --\n", encoding="utf-8")
        # Only the "typical" lvt file actually exists on disk -- "worst"
        # should be dropped from the clone, not written pointing at nothing.
        (lib_dir / "9t_lvt_typical.lib").write_text("-- typical lvt --\n", encoding="utf-8")
        data = _default_document("smoketest", str(self.root / "libroot"))
        data["metadata"]["technology"]["tracks"] = {"9T": {"vths": {"rvt": {
            "timing": {"corners": {
                "typical": {"libraries": ["lib/9t_rvt_typical.lib"], "format": "liberty"},
                "worst": {"libraries": ["lib/9t_rvt_worst.lib"], "format": "liberty"},
            }},
        }}}}

        async def drive():
            app = PdkMenuApp("smoketest", self.manifest_path, data, is_new=True)
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                self._select(main_list, "Tracks (1 track/vth group(s))")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T (1 vth(s))")
                await pilot.press("enter")
                await pilot.pause()
                # On the track screen, "rvt" is the only (and highlighted) vth.
                await pilot.press("c")  # clone
                await pilot.pause()
                app.screen.query_one(Input).value = "lvt"
                await pilot.press("enter")
                await pilot.pause()
                # On the regex-pairs screen: add one (find, replace) pair.
                await pilot.press("a")
                await pilot.pause()
                app.screen.query_one(Input).value = "rvt"
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = "lvt"
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("escape")  # done adding pairs -> on to the preview
                await pilot.pause()
                hint = app.screen.query_one("#dialog-hint", Static).content
                self.assertIn("2 path(s), 1 missing", hint)
                await pilot.press("c")  # confirm the clone
                await pilot.pause()
                # Lands on the new lvt's own screen -- back out and save.
                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                self.assertEqual(len(app.screen_stack), 1)
                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive())

        document = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        vths = document["metadata"]["technology"]["tracks"]["9T"]["vths"]
        self.assertEqual(set(vths), {"rvt", "lvt"})
        lvt_corners = vths["lvt"]["timing"]["corners"]
        self.assertEqual(lvt_corners["typical"]["libraries"], ["lib/9t_lvt_typical.lib"])
        self.assertEqual(lvt_corners["worst"]["libraries"], [])

    def test_clone_track_regex_substitutes_paths_across_every_vth(self):
        """Promoting clone to tracks: cloning 9T -> 7T applies the same
        regex substitution across every one of 9T's vths, not just one."""
        lib_dir = self.root / "libroot" / "lib"
        (lib_dir / "9t_rvt_typical.lib").write_text("x", encoding="utf-8")
        (lib_dir / "7t_rvt_typical.lib").write_text("x", encoding="utf-8")
        data = _default_document("smoketest", str(self.root / "libroot"))
        data["metadata"]["technology"]["tracks"] = {"9T": {"vths": {"rvt": {
            "timing": {"corners": {"typical": {"libraries": ["lib/9t_rvt_typical.lib"]}}},
        }}}}

        async def drive():
            app = PdkMenuApp("smoketest", self.manifest_path, data, is_new=True)
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                self._select(main_list, "Tracks (1 track/vth group(s))")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T (1 vth(s))")
                await pilot.press("c")  # clone track
                await pilot.pause()
                app.screen.query_one(Input).value = "7T"
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("a")  # add one (find, replace) pair
                await pilot.pause()
                app.screen.query_one(Input).value = "9t_"
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = "7t_"
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("escape")  # done adding pairs -> on to the preview
                await pilot.pause()
                hint = app.screen.query_one("#dialog-hint", Static).content
                self.assertIn("1 path(s), 0 missing", hint)
                await pilot.press("c")  # confirm
                await pilot.pause()
                await pilot.press("escape")  # 7T's own TrackScreen done
                await pilot.pause()
                await pilot.press("escape")  # TracksScreen done
                await pilot.pause()
                self.assertEqual(len(app.screen_stack), 1)
                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive())

        document = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        tracks = document["metadata"]["technology"]["tracks"]
        self.assertEqual(set(tracks), {"9T", "7T"})
        self.assertEqual(
            tracks["7T"]["vths"]["rvt"]["timing"]["corners"]["typical"]["libraries"],
            ["lib/7t_rvt_typical.lib"],
        )

    def test_clone_metal_stack_regex_substitutes_paths(self):
        """Promoting clone to metal stacks: cloning 9lmT2 -> 7lmT1 applies
        a regex substitution across that stack's lef/qrc_techfiles."""
        lib_dir = self.root / "libroot" / "lef"
        lib_dir.mkdir(parents=True)
        (lib_dir / "9t_lvt_9lmT2.lef").write_text("x", encoding="utf-8")
        (lib_dir / "9t_lvt_7lmT1.lef").write_text("x", encoding="utf-8")
        data = _default_document("smoketest", str(self.root / "libroot"))
        data["metadata"]["technology"]["tracks"] = {"9T": {"vths": {"lvt": {
            "timing": {"corners": {"typical": {"libraries": ["lib/typical.lib"]}}},
            "lef": {"9lmT2": ["lef/9t_lvt_9lmT2.lef"]},
        }}}}

        async def drive():
            app = PdkMenuApp("smoketest", self.manifest_path, data, is_new=True)
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                self._select(main_list, "Tracks (1 track/vth group(s))")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T (1 vth(s))")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "lvt (1 corner(s))")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "Metal stacks (1): LEF/QRC techfiles")
                await pilot.press("enter")
                await pilot.pause()
                # "9lmT2" is the only (and highlighted) stack.
                await pilot.press("c")  # clone stack
                await pilot.pause()
                app.screen.query_one(Input).value = "7lmT1"
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("a")  # one substitution pair
                await pilot.pause()
                app.screen.query_one(Input).value = "9lmT2"
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = "7lmT1"
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("escape")  # done adding pairs -> preview
                await pilot.pause()
                hint = app.screen.query_one("#dialog-hint", Static).content
                self.assertIn("1 path(s), 0 missing", hint)
                await pilot.press("c")  # confirm
                await pilot.pause()
                await pilot.press("escape")  # 7lmT1's own StackEditScreen done
                await pilot.pause()
                await pilot.press("escape")  # MetalStacksScreen done
                await pilot.pause()
                await pilot.press("escape")  # VthScreen done
                await pilot.pause()
                await pilot.press("escape")  # TrackScreen done
                await pilot.pause()
                await pilot.press("escape")  # TracksScreen done
                await pilot.pause()
                self.assertEqual(len(app.screen_stack), 1)
                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive())

        document = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        lef = document["metadata"]["technology"]["tracks"]["9T"]["vths"]["lvt"]["lef"]
        self.assertEqual(set(lef), {"9lmT2", "7lmT1"})
        self.assertEqual(lef["7lmT1"], ["lef/9t_lvt_7lmT1.lef"])

    def test_clone_with_multiple_regex_pairs_applies_them_in_order(self):
        """Some paths need more than one rewrite -- both pairs apply, in
        the order they were added."""
        lib_dir = self.root / "libroot" / "lib"
        (lib_dir / "9t_rvt_typical.lib").write_text("x", encoding="utf-8")
        (lib_dir / "7t_lvt_typical.lib").write_text("x", encoding="utf-8")
        data = _default_document("smoketest", str(self.root / "libroot"))
        data["metadata"]["technology"]["tracks"] = {"9T": {"vths": {"rvt": {
            "timing": {"corners": {"typical": {"libraries": ["lib/9t_rvt_typical.lib"]}}},
        }}}}

        async def drive():
            app = PdkMenuApp("smoketest", self.manifest_path, data, is_new=True)
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                self._select(main_list, "Tracks (1 track/vth group(s))")
                await pilot.press("enter")
                await pilot.pause()
                self._select(app.screen.query_one(OptionList), "9T (1 vth(s))")
                await pilot.press("enter")
                await pilot.pause()
                # On the track screen, "rvt" is the only (and highlighted) vth.
                await pilot.press("c")  # clone vth
                await pilot.pause()
                app.screen.query_one(Input).value = "lvt"
                await pilot.press("enter")
                await pilot.pause()
                # First pair: swap the track token.
                await pilot.press("a")
                await pilot.pause()
                app.screen.query_one(Input).value = "9t_"
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = "7t_"
                await pilot.press("enter")
                await pilot.pause()
                # Second pair: swap the vth token.
                await pilot.press("a")
                await pilot.pause()
                app.screen.query_one(Input).value = "rvt"
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = "lvt"
                await pilot.press("enter")
                await pilot.pause()
                pairs_list = app.screen.query_one(OptionList)
                self.assertEqual(
                    [o.prompt for o in pairs_list.options], ["/9t_/ -> '7t_'", "/rvt/ -> 'lvt'"],
                )
                await pilot.press("escape")  # done adding pairs -> preview
                await pilot.pause()
                hint = app.screen.query_one("#dialog-hint", Static).content
                self.assertIn("1 path(s), 0 missing", hint)
                await pilot.press("c")  # confirm
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                self.assertEqual(len(app.screen_stack), 1)
                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive())

        document = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        lvt_corners = document["metadata"]["technology"]["tracks"]["9T"]["vths"]["lvt"] \
            ["timing"]["corners"]
        self.assertEqual(lvt_corners["typical"]["libraries"], ["lib/7t_lvt_typical.lib"])

    def test_editing_an_existing_manifest_preserves_its_structure(self):
        data = _default_document("smoketest", str(self.root / "libroot"))
        data["source"]["revision"] = "V1"
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(yaml.safe_dump(data), encoding="utf-8")

        async def drive():
            loaded = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
            app = PdkMenuApp("smoketest", self.manifest_path, loaded, is_new=False)
            async with app.run_test() as pilot:
                main_list = app.query_one(OptionList)
                main_list.highlighted = 0  # "Revision"
                await pilot.press("enter")
                await pilot.pause()
                app.screen.query_one(Input).value = "V2"
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive())
        document = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(document["source"]["revision"], "V2")
        self.assertEqual(document["name"], "smoketest")

    def test_save_stamps_author_creation_date_once_and_last_modified_every_time(self):
        data = _default_document("smoketest", str(self.root / "libroot"))

        async def drive():
            app = PdkMenuApp("smoketest", self.manifest_path, data, is_new=True)
            async with app.run_test() as pilot:
                with patch.dict(os.environ, {"USER": "manuelbv"}):
                    await pilot.press("s")
                    await pilot.pause()

        asyncio.run(drive())
        first = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(first["author"], "manuelbv")
        self.assertIn("creation-date", first)
        self.assertIn("last-modified-date", first)
        created = first["creation-date"]

        async def drive_again():
            loaded = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
            app = PdkMenuApp("smoketest", self.manifest_path, loaded, is_new=False)
            async with app.run_test() as pilot:
                await pilot.press("s")
                await pilot.pause()

        asyncio.run(drive_again())
        second = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        # Re-saving an existing manifest never re-stamps author/creation-date.
        self.assertEqual(second["author"], "manuelbv")
        self.assertEqual(second["creation-date"], created)
        self.assertIn("last-modified-date", second)


class BrowseFilesScreenNavigationTests(unittest.TestCase):
    """The actual bug report: a browser rooted at the last directory used
    (for convenience) must still be able to reach a sibling directory --
    a corner's QRC techfile routinely lives next to, not inside, the
    directory its libraries came from."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-browse-files-")
        self.root = Path(self.temporary.name)
        (self.root / "lib").mkdir()
        (self.root / "lib" / "typical.lib").write_text("-- typical --\n", encoding="utf-8")
        (self.root / "qrc").mkdir()
        (self.root / "qrc" / "rc_25C.captable").write_text("-- captable --\n", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_up_escapes_a_directory_rooted_away_from_a_sibling_file(self):
        from textual.app import App, ComposeResult
        from textual.widgets import DirectoryTree
        from wolf.pdk_menu import _BrowseFilesScreen

        lib_dir = self.root / "lib"
        qrc_file = self.root / "qrc" / "rc_25C.captable"
        result: list = []

        class HostApp(App):
            def compose(self) -> ComposeResult:
                return []

        async def drive():
            app = HostApp()
            async with app.run_test() as pilot:
                def handle(picked):
                    result.extend(picked or [])
                app.push_screen(_BrowseFilesScreen(str(lib_dir), title="t"), handle)
                await pilot.pause()

                tree = app.screen.query_one(DirectoryTree)
                self.assertEqual(Path(tree.path).resolve(), lib_dir.resolve())

                await pilot.press("u")  # climb out of lib/ ...
                await pilot.pause()
                self.assertEqual(Path(tree.path).resolve(), self.root.resolve())

                # ... down into the sibling qrc/ directory ...
                for _ in range(2):  # skip past "lib" to "qrc" (alphabetical)
                    await pilot.press("down")
                    await pilot.pause()
                await pilot.press("enter")  # expand qrc/
                await pilot.pause()
                await pilot.press("down")  # the captable file
                await pilot.pause()
                await pilot.press("a")  # add it
                await pilot.pause()
                await pilot.press("escape")  # done
                await pilot.pause()

        asyncio.run(drive())
        self.assertEqual(result, [str(qrc_file.resolve())])

    def test_regex_filter_narrows_bulk_add_and_clears_with_empty_pattern(self):
        from textual.app import App, ComposeResult
        from textual.widgets import DirectoryTree, Input
        from wolf.pdk_menu import _BrowseFilesScreen

        corners = self.root / "corners"
        corners.mkdir()
        bc_file = corners / "bc1d11.lib"
        wc_file = corners / "wc1d08.lib"
        tc_file = corners / "tc1d20.lib"
        for path in (bc_file, wc_file, tc_file):
            path.write_text("-- lib --\n", encoding="utf-8")
        result: list = []

        class HostApp(App):
            def compose(self) -> ComposeResult:
                return []

        async def drive():
            app = HostApp()
            async with app.run_test() as pilot:
                def handle(picked):
                    result.extend(picked or [])
                app.push_screen(_BrowseFilesScreen(str(corners), title="t"), handle)
                await pilot.pause()

                # Narrow to the "bc" corner only, then bulk-add the (still
                # highlighted, unmoved) root directory -- only the matching
                # file should come through.
                await pilot.press("r")
                await pilot.pause()
                app.screen.query_one(Input).value = "^bc"
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()

                # Clear the filter (submit empty) and bulk-add again -- the
                # remaining two files should come through now, the already
                # -picked bc file skipped as a duplicate.
                await pilot.press("r")
                await pilot.pause()
                app.screen.query_one(Input).value = ""
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()

                await pilot.press("escape")  # done
                await pilot.pause()

        asyncio.run(drive())
        self.assertEqual(
            sorted(result),
            sorted(str(path.resolve()) for path in (bc_file, wc_file, tc_file)),
        )


class OpenPdkMenuRoutingTests(unittest.TestCase):
    """The plain-Python routing in open_pdk_menu (existing vs. new package),
    kept separate from the TUI itself."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-pdk-menu-routing-")
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.registry = self.root / "registry"
        (self.registry / "pdk").mkdir(parents=True)
        # RegistryManager reads ConfigStore, which keys off XDG_CONFIG_HOME/
        # HOME (not WOLF_HOME/WOLF_REGISTRY) -- clear=True so no real
        # ~/.wolf registries configured on this host leak into the test.
        self.variables = patch.dict(os.environ, {
            "HOME": str(self.root / "home"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "WOLF_HOME": str(self.state), "WOLF_REGISTRY": str(self.registry),
        }, clear=True)
        self.variables.start()

    def tearDown(self):
        self.variables.stop()
        self.temporary.cleanup()

    def _write_manifest(self, name: str, root: Path) -> Path:
        path = self.registry / "pdk" / f"{name}.yaml"
        path.write_text(yaml.safe_dump({
            "schema_version": 1, "kind": "pdk", "name": name, "description": name,
            "source": {"type": "local-path", "root": str(root), "revision": "V1"},
            "validation": {"required_paths": []},
            "metadata": {"technology": {"name": name}},
        }), encoding="utf-8")
        return path

    def test_existing_package_opens_the_app_with_its_real_manifest_path(self):
        root = self.root / "libroot"
        root.mkdir()
        manifest_path = self._write_manifest("tsmc65", root)
        with patch("wolf.pdk_menu.PdkMenuApp") as app_cls:
            open_pdk_menu("tsmc65")
        app_cls.assert_called_once()
        name, path, data, = app_cls.call_args.args
        self.assertEqual((name, path), ("tsmc65", manifest_path.resolve()))
        self.assertEqual(data["source"]["revision"], "V1")
        self.assertEqual(
            app_cls.call_args.kwargs,
            {"is_new": False, "initial_track": None, "initial_vth": None},
        )

    def test_new_package_without_any_local_registry_is_rejected(self):
        # WOLF_REGISTRY aggregation is disabled by the env override (see
        # PackageRegistry.__init__), so no RegistryManager-configured local
        # registries exist here either -- the real "nothing to create in" case.
        with self.assertRaisesRegex(ValueError, "no local package registry"):
            open_pdk_menu("brand-new")

    def test_dotted_name_resolves_to_initial_track_and_vth(self):
        root = self.root / "libroot"
        root.mkdir()
        self._write_manifest("tsmc65", root)
        with patch("wolf.pdk_menu.PdkMenuApp") as app_cls:
            open_pdk_menu("tsmc65.9T.lvt")
        self.assertEqual(
            app_cls.call_args.kwargs,
            {"is_new": False, "initial_track": "9T", "initial_vth": "lvt"},
        )

    def test_dotted_name_with_too_many_parts_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid pdk menu target"):
            open_pdk_menu("tsmc65.9T.lvt.extra")

    def test_deep_link_into_a_nonexistent_package_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not exist yet"):
            open_pdk_menu("brand-new.9T")

    def test_no_name_picks_from_existing_packages(self):
        root = self.root / "libroot"
        root.mkdir()
        self._write_manifest("tsmc65", root)
        with patch("wolf.pdk_menu._PdkPickerApp") as picker_cls, \
             patch("wolf.pdk_menu.PdkMenuApp") as app_cls:
            picker_cls.return_value.run.return_value = "tsmc65"
            open_pdk_menu()
        picker_cls.assert_called_once_with(["tsmc65"])
        self.assertEqual(app_cls.call_args.args[0], "tsmc65")

    def test_no_name_cancelled_picker_does_nothing(self):
        with patch("wolf.pdk_menu._PdkPickerApp") as picker_cls, \
             patch("wolf.pdk_menu.PdkMenuApp") as app_cls:
            picker_cls.return_value.run.return_value = None
            open_pdk_menu()
        app_cls.assert_not_called()

    def test_no_name_create_new_prompts_for_a_name(self):
        with patch("wolf.pdk_menu._PdkPickerApp") as picker_cls, \
             patch("builtins.input", return_value="freshpdk") as mock_input, \
             patch("wolf.pdk_menu._writable_local_registries", return_value=[]):
            picker_cls.return_value.run.return_value = "__create__"
            with self.assertRaisesRegex(ValueError, "no local package registry"):
                open_pdk_menu()
        mock_input.assert_called_once()


class MenuCandidatesTests(unittest.TestCase):
    """wolf.commands.pdk._menu_candidates feeds `wolf pdk menu` completion."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-pdk-candidates-")
        self.root = Path(self.temporary.name)
        self.registry = self.root / "registry"
        (self.registry / "pdk").mkdir(parents=True)
        self.variables = patch.dict(os.environ, {
            "HOME": str(self.root / "home"), "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"), "WOLF_HOME": str(self.root / "state"),
            "WOLF_REGISTRY": str(self.registry),
        }, clear=True)
        self.variables.start()

    def tearDown(self):
        self.variables.stop()
        self.temporary.cleanup()

    def test_candidates_include_package_track_and_vth_forms(self):
        from wolf.commands.pdk import _menu_candidates
        (self.registry / "pdk" / "tsmc65.yaml").write_text(yaml.safe_dump({
            "schema_version": 1, "kind": "pdk", "name": "tsmc65", "description": "tsmc65",
            "source": {"type": "local-path", "root": str(self.root), "revision": "V1"},
            "validation": {"required_paths": []},
            "metadata": {"technology": {
                "name": "tsmc65",
                "tracks": {"9T": {"vths": {"lvt": {}, "rvt": {}}}, "7T": {"vths": {"rvt": {}}}},
            }},
        }), encoding="utf-8")
        candidates = set(_menu_candidates())
        self.assertEqual(candidates, {
            "tsmc65", "tsmc65.9T", "tsmc65.9T.lvt", "tsmc65.9T.rvt",
            "tsmc65.7T", "tsmc65.7T.rvt",
        })

    def test_flat_package_contributes_only_its_bare_name(self):
        from wolf.commands.pdk import _menu_candidates
        (self.registry / "pdk" / "asap7.yaml").write_text(yaml.safe_dump({
            "schema_version": 1, "kind": "pdk", "name": "asap7", "description": "asap7",
            "source": {"type": "local-path", "root": str(self.root), "revision": "V1"},
            "validation": {"required_paths": []},
            "metadata": {"technology": {"name": "asap7"}},
        }), encoding="utf-8")
        self.assertEqual(_menu_candidates(), ("asap7",))


if __name__ == "__main__":
    unittest.main()

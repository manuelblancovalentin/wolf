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
from textual.widgets import Input, OptionList


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
                await pilot.press("escape")  # CornerEditScreen done -> back to the main menu
                await pilot.pause()
                self.assertEqual(len(app.screen_stack), 1)  # every _PickScreen already popped itself
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
                await pilot.press("escape")  # FileListScreen done -> back to the main menu
                await pilot.pause()
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

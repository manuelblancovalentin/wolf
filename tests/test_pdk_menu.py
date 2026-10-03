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

                for _ in range(6):  # unwind every nested screen back to the main menu
                    await pilot.pause()
                    await pilot.press("escape")
                await pilot.pause()

                await pilot.press("s")  # save
                await pilot.pause()

        asyncio.run(drive())

        self.assertTrue(self.manifest_path.is_file())
        document = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        libraries = document["metadata"]["technology"]["tracks"]["9T"]["vths"]["lvt"] \
            ["timing"]["corners"]["typical"]["libraries"]
        self.assertEqual(sorted(libraries), ["lib/typical.lib", "lib/worst.lib"])

        manifest = load_manifest(self.manifest_path)

        class FakeInstalled:
            content_path = self.root / "libroot"
        resolved = _technology_inputs(manifest, FakeInstalled())
        self.assertEqual((resolved.track, resolved.vth), ("9T", "lvt"))
        self.assertEqual(len(resolved.timing_corners), 1)
        self.assertEqual(resolved.timing_corners[0].name, "typical")

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
        self.assertEqual(app_cls.call_args.kwargs, {"is_new": False})

    def test_new_package_without_any_local_registry_is_rejected(self):
        # WOLF_REGISTRY aggregation is disabled by the env override (see
        # PackageRegistry.__init__), so no RegistryManager-configured local
        # registries exist here either -- the real "nothing to create in" case.
        with self.assertRaisesRegex(ValueError, "no local package registry"):
            open_pdk_menu("brand-new")


if __name__ == "__main__":
    unittest.main()

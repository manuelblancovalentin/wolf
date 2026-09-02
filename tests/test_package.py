import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from wolf.package import PackageId, PackageRegistry, PackageStore
from wolf.package.registry import UnknownPackageError
from wolf.package.store import CorruptPackageError


class PackageFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-package-")
        self.root = Path(self.temporary.name)
        self.environment = mock.patch.dict(
            os.environ,
            {"WOLF_HOME": str(self.root / "wolf-home")},
            clear=False,
        )
        self.environment.start()
        self.registry = PackageRegistry()
        self.store = PackageStore()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def test_package_identifiers_parse_and_reject_ambiguous_values(self):
        self.assertEqual(PackageId.parse("rtl/ibex"), PackageId("rtl", "ibex"))
        for value in ("ibex", "rtl/ibex/extra", "library/foo", "rtl/../ibex"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "KIND/NAME"):
                PackageId.parse(value)

    def test_builtin_registry_contains_phase_one_packages(self):
        self.assertEqual(
            self.registry.identifiers(),
            ("flow/orfs", "pdk/asap7", "rtl/ibex"),
        )
        self.assertEqual(
            self.registry.get("rtl/ibex").revision,
            "77d801001554cce8fe69e742e96539eecbe74425",
        )
        self.assertEqual(
            self.registry.get("flow/orfs").revision,
            "8c0616910615e843780ba527526f2b83a564ba70",
        )
        asap7 = self.registry.get("pdk/asap7")
        self.assertEqual(asap7.source.type, "package-path")
        self.assertEqual(str(asap7.source.package), "flow/orfs")
        self.assertEqual(asap7.revision, "b9b4c9266113c67978f75b987f1d5a0841c2f15f")

    def test_unknown_package_error_lists_registry_contents(self):
        with self.assertRaisesRegex(UnknownPackageError, "available packages:.*rtl/ibex"):
            self.registry.get("rtl/missing")

    def test_store_path_is_versioned_under_isolated_wolf_home(self):
        manifest = self.registry.get("rtl/ibex")
        expected = (
            self.root / "wolf-home" / "packages" / "rtl" / "ibex" / manifest.revision
        )
        self.assertEqual(self.store.installation_path(manifest), expected)
        self.assertEqual(self.store.status(manifest), "not installed")
        self.assertFalse((self.root / ".wolf").exists())

    def test_partial_installation_is_reported_as_corrupt(self):
        manifest = self.registry.get("rtl/ibex")
        self.store.installation_path(manifest).mkdir(parents=True)
        self.assertEqual(self.store.status(manifest), "corrupt")
        with self.assertRaisesRegex(CorruptPackageError, "refusing to overwrite"):
            self.store.read(manifest)


if __name__ == "__main__":
    unittest.main()

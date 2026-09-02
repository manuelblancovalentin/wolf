import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import yaml

from wolf.config import ConfigStore, config_path
from wolf.paths import environments_dir, packages_dir, state_root


class ConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-config-")
        self.root = Path(self.temporary.name)
        self.environment = mock.patch.dict(
            os.environ,
            {
                "HOME": str(self.root / "home"),
                "XDG_CONFIG_HOME": str(self.root / "config"),
                "XDG_DATA_HOME": str(self.root / "data"),
                "XDG_CACHE_HOME": str(self.root / "cache"),
            },
            clear=True,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def test_xdg_defaults_are_cwd_independent(self):
        expected = self.root / "config" / "wolf" / "config.yaml"
        previous = Path.cwd()
        try:
            os.chdir("/")
            first = (config_path(), state_root(), packages_dir(), environments_dir())
            os.chdir("/tmp")
            second = (config_path(), state_root(), packages_dir(), environments_dir())
        finally:
            os.chdir(previous)
        self.assertEqual(first, second)
        self.assertEqual(first[0], expected)
        self.assertEqual(first[1], self.root / "data" / "wolf")

    def test_set_get_unset_and_atomic_rewrite(self):
        store = ConfigStore()
        value = store.set("paths.packages", "relative", invocation_cwd=self.root)
        self.assertEqual(value, str(self.root / "relative"))
        self.assertEqual(store.get("paths.packages"), value)
        parsed = yaml.safe_load(store.path.read_text())
        self.assertEqual(parsed["schema"], "wolf.config/v1")
        self.assertFalse(any(store.path.parent.glob(".config-*.yaml")))
        store.unset("paths.packages")
        self.assertEqual(store.get("paths.packages"), str(self.root / "data" / "wolf" / "packages"))

    def test_invalid_value_does_not_corrupt_existing_config(self):
        store = ConfigStore()
        store.set("container.preferred_runtime", "podman")
        before = store.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "podman, docker"):
            store.set("container.preferred_runtime", "singularity")
        self.assertEqual(store.path.read_bytes(), before)

    def test_wolf_home_only_overrides_wolf_owned_data(self):
        isolated = self.root / "legacy-state"
        with mock.patch.dict(os.environ, {"WOLF_HOME": str(isolated)}):
            self.assertEqual(config_path(), self.root / "config" / "wolf" / "config.yaml")
            self.assertEqual(state_root(), isolated)
            self.assertEqual(packages_dir(), isolated / "packages")
            self.assertEqual(environments_dir(), isolated / "envs")

    def test_rejects_unknown_keys_and_schema(self):
        store = ConfigStore()
        store.path.parent.mkdir(parents=True)
        store.path.write_text("schema: wolf.config/v2\n")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            store.load()

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import yaml

from wolf.config import ConfigStore, config_path
from wolf.paths import environments_dir, packages_dir, state_root
from wolf.commands.init import command_init
from wolf.shell import BEGIN, install_bash_integration


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

    def test_init_accepts_defaults_and_prefers_usable_podman(self):
        diagnostic = lambda name: mock.Mock(
            usable=name == "podman", detail="usable" if name == "podman" else "unavailable"
        )
        answers = iter(["", "", "", "", "n", "n"])
        with mock.patch("wolf.commands.init.input", side_effect=lambda _prompt: next(answers)), \
             mock.patch("wolf.commands.init._runtime_diagnostic", side_effect=diagnostic):
            self.assertEqual(command_init(mock.Mock()), 0)
        config = ConfigStore().load()
        self.assertEqual(config["container"]["preferred_runtime"], "podman")
        self.assertEqual(config["paths"]["packages"], str(self.root / "data" / "wolf" / "packages"))

    def test_init_preserves_existing_config_when_reconfigure_is_declined(self):
        store = ConfigStore()
        store.set("workspace.default", str(self.root / "existing"))
        before = store.path.read_bytes()
        with mock.patch("wolf.commands.init.input", return_value="n"):
            self.assertEqual(command_init(mock.Mock()), 0)
        self.assertEqual(store.path.read_bytes(), before)

    def test_shell_integration_installation_is_idempotent(self):
        rc = self.root / "home" / ".bashrc"
        rc.parent.mkdir(parents=True)
        rc.write_text("export CUSTOM=value\n")
        self.assertTrue(install_bash_integration(rc))
        self.assertFalse(install_bash_integration(rc))
        text = rc.read_text()
        self.assertEqual(text.count(BEGIN), 1)
        self.assertIn("export CUSTOM=value", text)

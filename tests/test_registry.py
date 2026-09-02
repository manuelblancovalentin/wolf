import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import yaml

from wolf.config import ConfigStore
from wolf.package.installer import PackageInstaller
from wolf.package.registry import AmbiguousPackageError, PackageRegistry
from wolf.package.store import PackageStore
from wolf.registry import RegistryManager


def manifest_text(name="demo", source="https://example.invalid/demo.git", revision="0" * 40):
    return f'''schema_version: 1
kind: rtl
name: {name}
description: external test package
source:
  type: git
  url: {source}
  revision: "{revision}"
validation:
  required_paths: [required.txt]
'''


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-registry-")
        self.root = Path(self.temporary.name)
        self.environment = mock.patch.dict(os.environ, {
            "HOME": str(self.root / "home"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "WOLF_HOME": str(self.root / "state"),
            "GIT_ALLOW_PROTOCOL": "file",
        }, clear=True)
        self.environment.start()
        self.manager = RegistryManager()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def git(self, *arguments, cwd=None):
        return subprocess.run(["git", *arguments], cwd=cwd, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              check=True).stdout.strip()

    def make_registry(self, name="registry", package="demo"):
        root = self.root / name
        (root / "rtl").mkdir(parents=True)
        (root / "rtl" / f"{package}.yaml").write_text(manifest_text(package))
        return root

    def init_git(self, root):
        self.git("init", "--quiet", cwd=root)
        self.git("config", "user.email", "wolf-tests@example.invalid", cwd=root)
        self.git("config", "user.name", "WOLF Tests", cwd=root)
        self.git("add", ".", cwd=root)
        self.git("commit", "--quiet", "-m", "registry", cwd=root)
        return self.git("rev-parse", "HEAD", cwd=root)

    def test_builtin_registry_remains_available(self):
        self.assertEqual(PackageRegistry().get("rtl/ibex").registry_name, "builtin")

    def test_local_registry_discovery_and_package_lookup(self):
        local = self.make_registry()
        self.manager.add("lab", str(local), "local")
        package = PackageRegistry().get("rtl/demo")
        self.assertEqual(package.registry_name, "lab")
        self.assertEqual(package.registry_type, "local")
        self.assertEqual(self.manager.status(self.manager.get("lab")), "ready")

    def test_git_registry_clone_sync_and_revision(self):
        remote = self.make_registry("remote")
        first = self.init_git(remote)
        spec = self.manager.add("shared", str(remote), "git")
        self.assertEqual(self.manager.revision(spec), first)
        (remote / "rtl" / "second.yaml").write_text(manifest_text("second"))
        self.git("add", ".", cwd=remote)
        self.git("commit", "--quiet", "-m", "second", cwd=remote)
        second = self.git("rev-parse", "HEAD", cwd=remote)
        self.assertNotIn("rtl/second", PackageRegistry().identifiers())
        self.manager.sync("shared")
        self.assertEqual(self.manager.revision(spec), second)
        self.assertIn("rtl/second", PackageRegistry().identifiers())

    def test_duplicate_identifiers_require_registry_qualification(self):
        one = self.make_registry("one", "same")
        two = self.make_registry("two", "same")
        self.manager.add("one", str(one), "local")
        self.manager.add("two", str(two), "local")
        with self.assertRaisesRegex(AmbiguousPackageError, "multiple registries"):
            PackageRegistry().get("rtl/same")
        self.assertEqual(PackageRegistry().get("one::rtl/same").registry_name, "one")

    def test_private_ssh_source_is_stored_without_credentials(self):
        with mock.patch("wolf.registry._git") as git:
            def fake_git(arguments, cwd=None):
                if arguments[0] == "clone":
                    destination = Path(arguments[-1])
                    (destination / "rtl").mkdir(parents=True)
                    (destination / "rtl" / "demo.yaml").write_text(manifest_text())
                return "a" * 40
            git.side_effect = fake_git
            self.manager.add("private", "git@host:org/registry.git", "git")
        raw = ConfigStore().load()["registries"]["private"]
        self.assertEqual(raw["source"], "git@host:org/registry.git")
        self.assertNotIn("credential", raw)

    def test_embedded_https_credentials_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "must not embed credentials"):
            self.manager.add("bad", "https://user:token@host/registry.git", "git")

    def test_install_record_freezes_registry_provenance(self):
        source = self.root / "source"
        source.mkdir()
        (source / "required.txt").write_text("ok\n")
        revision = self.init_git(source)
        local = self.root / "external"
        (local / "rtl").mkdir(parents=True)
        (local / "rtl" / "demo.yaml").write_text(manifest_text("demo", str(source), revision))
        self.manager.add("lab", str(local), "local")
        installed, _ = PackageInstaller(PackageRegistry(), PackageStore()).install("rtl/demo")
        self.assertEqual(installed.registry_name, "lab")
        record = yaml.safe_load((installed.installation_path / "installed.yaml").read_text())
        self.assertEqual(record["registry"]["name"], "lab")

    def test_remove_does_not_modify_local_registry(self):
        local = self.make_registry()
        self.manager.add("lab", str(local), "local")
        self.manager.remove("lab")
        self.assertTrue(local.is_dir())

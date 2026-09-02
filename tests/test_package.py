import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from wolf.package import PackageId, PackageManifest, PackageRegistry, PackageStore
from wolf.package.installer import PackageInstallError, PackageInstaller
from wolf.package.model import PackageSource
from wolf.package.registry import UnknownPackageError, load_manifest
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

    def test_manifest_paths_cannot_escape_package_content(self):
        manifest = self.root / "escape.yaml"
        manifest.write_text(
            '''schema_version: 1
kind: pdk
name: escape
description: invalid path fixture
source:
  type: package-path
  package: flow/orfs
  path: ../outside
  url: https://example.invalid/source.git
  revision: "0000000000000000000000000000000000000000"
validation:
  required_paths: [../outside]
''', encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "must not escape"):
            load_manifest(manifest)


class StaticRegistry:
    def __init__(self, *manifests):
        self._manifests = {manifest.identifier: manifest for manifest in manifests}

    def get(self, value):
        identifier = PackageId.parse(value) if isinstance(value, str) else value
        return self._manifests[identifier]


class PackageInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-installer-")
        self.root = Path(self.temporary.name)
        self.store = PackageStore(self.root / "packages")
        self.git_environment = mock.patch.dict(
            os.environ,
            {"GIT_ALLOW_PROTOCOL": "file"},
            clear=False,
        )
        self.git_environment.start()

    def tearDown(self):
        self.git_environment.stop()
        self.temporary.cleanup()

    def git(self, *arguments, cwd=None):
        return subprocess.run(
            ["git", *arguments], cwd=cwd, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        ).stdout.strip()

    def repository(self, name, files):
        root = self.root / name
        root.mkdir()
        self.git("init", "--quiet", cwd=root)
        self.git("config", "user.email", "wolf-tests@example.invalid", cwd=root)
        self.git("config", "user.name", "WOLF Tests", cwd=root)
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.git("add", ".", cwd=root)
        self.git("commit", "--quiet", "-m", "fixture", cwd=root)
        return root, self.git("rev-parse", "HEAD", cwd=root)

    @staticmethod
    def manifest(identifier, url, revision, required_paths, *, submodules=False):
        return PackageManifest(
            schema_version=1,
            identifier=PackageId.parse(identifier),
            description="test package",
            source=PackageSource(
                type="git", url=str(url), revision=revision, submodules=submodules
            ),
            required_paths=tuple(required_paths),
        )

    def test_git_install_is_pinned_idempotent_and_cwd_independent(self):
        repository, revision = self.repository("source", {"required.txt": "content\n"})
        manifest = self.manifest("rtl/demo", repository, revision, ("required.txt",))
        installer = PackageInstaller(StaticRegistry(manifest), self.store)
        previous = Path.cwd()
        try:
            os.chdir("/")
            installed, created = installer.install("rtl/demo")
            os.chdir("/tmp")
            repeated, repeated_created = installer.install("rtl/demo")
        finally:
            os.chdir(previous)
        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(installed.installation_path, repeated.installation_path)
        self.assertEqual(installed.source_revision, revision)
        self.assertEqual(installed.content_path.joinpath("required.txt").read_text(), "content\n")

    def test_recursive_submodules_are_initialized_when_declared(self):
        child, _ = self.repository("child", {"child.txt": "submodule\n"})
        parent, _ = self.repository("parent", {"root.txt": "parent\n"})
        self.git("-c", "protocol.file.allow=always", "submodule", "add", "--quiet",
                 str(child), "deps/child", cwd=parent)
        self.git("commit", "--quiet", "-am", "add submodule", cwd=parent)
        revision = self.git("rev-parse", "HEAD", cwd=parent)
        manifest = self.manifest(
            "flow/demo", parent, revision, ("deps/child/child.txt",), submodules=True
        )
        installed, _ = PackageInstaller(StaticRegistry(manifest), self.store).install("flow/demo")
        self.assertEqual(
            installed.content_path.joinpath("deps/child/child.txt").read_text(),
            "submodule\n",
        )

    def test_package_path_creates_validated_view_without_copying_content(self):
        repository, revision = self.repository(
            "flow-source",
            {"flow/platforms/demo/config.mk": "PLATFORM=demo\n"},
        )
        parent = self.manifest(
            "flow/demo", repository, revision, ("flow/platforms/demo/config.mk",)
        )
        tree_revision = self.git(
            "rev-parse", f"{revision}:flow/platforms/demo", cwd=repository
        )
        child = PackageManifest(
            schema_version=1,
            identifier=PackageId.parse("pdk/demo"),
            description="test package view",
            source=PackageSource(
                type="package-path",
                url=str(repository),
                revision=tree_revision,
                package=parent.identifier,
                path="flow/platforms/demo",
                parent_revision=revision,
            ),
            required_paths=("config.mk",),
        )
        installer = PackageInstaller(StaticRegistry(parent, child), self.store)
        installer.install("flow/demo")
        installed, created = installer.install("pdk/demo")
        self.assertTrue(created)
        self.assertTrue(installed.installation_path.joinpath("content").is_symlink())
        self.assertEqual(installed.content_path.joinpath("config.mk").read_text(), "PLATFORM=demo\n")

    def test_package_path_requires_parent_installation(self):
        repository, revision = self.repository("unused", {"platform/config.mk": "x\n"})
        parent = self.manifest("flow/demo", repository, revision, ("platform/config.mk",))
        child = PackageManifest(
            schema_version=1,
            identifier=PackageId.parse("pdk/demo"),
            description="test package view",
            source=PackageSource(
                type="package-path", url=str(repository), revision="deadbeef",
                package=parent.identifier, path="platform", parent_revision=revision,
            ),
            required_paths=("config.mk",),
        )
        with self.assertRaisesRegex(PackageInstallError, "install flow/demo first"):
            PackageInstaller(StaticRegistry(parent, child), self.store).install("pdk/demo")

    def test_invalid_or_partial_installations_are_never_overwritten(self):
        repository, revision = self.repository("bad-source", {"other.txt": "wrong\n"})
        manifest = self.manifest("rtl/demo", repository, revision, ("required.txt",))
        installer = PackageInstaller(StaticRegistry(manifest), self.store)
        with self.assertRaisesRegex(PackageInstallError, "missing required content"):
            installer.install("rtl/demo")
        destination = self.store.installation_path(manifest)
        self.assertFalse(destination.exists())
        destination.mkdir(parents=True)
        destination.joinpath("unrelated.txt").write_text("preserve\n")
        with self.assertRaisesRegex(CorruptPackageError, "refusing to overwrite"):
            installer.install("rtl/demo")
        self.assertEqual(destination.joinpath("unrelated.txt").read_text(), "preserve\n")


class PackageCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-package-cli-")
        self.root = Path(self.temporary.name)
        self.wolf_home = self.root / "wolf-home"
        self.registry = self.root / "registry"
        self.source = self.root / "source"
        self.source.mkdir()
        subprocess.run(["git", "init", "--quiet"], cwd=self.source, check=True)
        subprocess.run(["git", "config", "user.email", "wolf-tests@example.invalid"], cwd=self.source, check=True)
        subprocess.run(["git", "config", "user.name", "WOLF Tests"], cwd=self.source, check=True)
        self.source.joinpath("required.txt").write_text("fixture\n")
        subprocess.run(["git", "add", "."], cwd=self.source, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "fixture"], cwd=self.source, check=True)
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.source, text=True,
            stdout=subprocess.PIPE, check=True,
        ).stdout.strip()
        manifest = self.registry / "rtl" / "demo.yaml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            f'''schema_version: 1
kind: rtl
name: demo
description: CLI package fixture
source:
  type: git
  url: {self.source}
  revision: {revision}
validation:
  required_paths: [required.txt]
metadata:
  design:
    name: demo
    top: demo_top
''', encoding="utf-8"
        )
        self.environment = os.environ.copy()
        self.environment.update({
            "WOLF_HOME": str(self.wolf_home),
            "WOLF_REGISTRY": str(self.registry),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        })

    def tearDown(self):
        self.temporary.cleanup()

    def wolf(self, *arguments, cwd="/"):
        return subprocess.run(
            [sys.executable, "-m", "wolf.cli", *arguments], cwd=cwd,
            env=self.environment, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )

    def test_package_info_install_list_and_idempotency(self):
        empty = self.wolf("package", "list")
        self.assertEqual(empty.returncode, 0, msg=empty.stderr)
        self.assertIn("No WOLF packages installed", empty.stdout)
        info = self.wolf("package", "info", "rtl/demo")
        self.assertEqual(info.returncode, 0, msg=info.stderr)
        self.assertIn("Status: not installed", info.stdout)
        installed = self.wolf("install", "rtl/demo", cwd="/tmp")
        self.assertEqual(installed.returncode, 0, msg=installed.stderr)
        self.assertIn("Installed rtl/demo", installed.stdout)
        repeated = self.wolf("install", "rtl/demo")
        self.assertEqual(repeated.returncode, 0, msg=repeated.stderr)
        self.assertIn("already installed", repeated.stdout)
        listed = self.wolf("package", "list")
        self.assertIn("rtl/demo", listed.stdout)
        self.assertIn(str(self.wolf_home / "packages"), listed.stdout)
        self.assertFalse((self.root / ".wolf").exists())

    def test_unknown_package_fails_clearly_without_creating_store(self):
        result = self.wolf("package", "info", "rtl/missing")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown WOLF package 'rtl/missing'", result.stderr)
        self.assertFalse((self.wolf_home / "packages").exists())


if __name__ == "__main__":
    unittest.main()

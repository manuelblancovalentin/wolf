"""Deterministic installers for Phase 1 WOLF package sources."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Optional

import yaml

from wolf.package.model import PackageManifest
from wolf.package.registry import PackageRegistry
from wolf.package.store import InstalledPackage, PackageStore, validate_content


class PackageInstallError(ValueError):
    pass


def _git(arguments: list[str], *, cwd: Optional[Path] = None, progress: bool = False) -> str:
    command = ["git", *arguments]
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=None if progress else subprocess.PIPE,
            stderr=None if progress else subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        raise PackageInstallError(f"cannot execute git: {error}") from error
    if result.returncode != 0:
        detail = (result.stderr.strip() if result.stderr else "") or (result.stdout.strip() if result.stdout else "") or f"exit status {result.returncode}"
        raise PackageInstallError(f"git {' '.join(arguments)} failed: {detail}")
    return (result.stdout or "").strip()


def _write_record(
    path: Path,
    manifest: PackageManifest,
    *,
    content_path: str,
    source_revision: str,
) -> None:
    record = {
        "schema_version": 1,
        "manifest_schema_version": manifest.schema_version,
        "package": str(manifest.identifier),
        "source_type": manifest.source.type,
        "source_url": manifest.source.url,
        "revision": manifest.revision,
        "source_revision": source_revision,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "content_path": content_path,
        "registry": {
            "name": manifest.registry_name,
            "type": manifest.registry_type,
            "revision": manifest.registry_revision,
            "manifest_path": manifest.manifest_path,
        },
    }
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")


class PackageInstaller:
    def __init__(
        self,
        registry: Optional[PackageRegistry] = None,
        store: Optional[PackageStore] = None,
    ):
        self.registry = registry or PackageRegistry()
        self.store = store or PackageStore()

    def install(self, value: str) -> tuple[InstalledPackage, bool]:
        manifest = self.registry.get(value)
        installed = self.store.read(manifest)
        if installed is not None:
            return installed, False
        if shutil.which("git") is None:
            raise PackageInstallError("git is required to install WOLF packages")
        destination = self.store.installation_path(manifest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".wolf-install-", dir=destination.parent))
        try:
            if manifest.source.type == "git":
                self._install_git(manifest, staging)
            elif manifest.source.type == "package-path":
                self._install_package_path(manifest, staging, destination)
            else:
                raise PackageInstallError(
                    f"unsupported package source type {manifest.source.type!r}"
                )
            if destination.exists():
                installed = self.store.read(manifest)
                if installed is not None:
                    return installed, False
            staging.rename(destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        installed = self.store.read(manifest)
        if installed is None:
            raise PackageInstallError(f"package installation did not create {destination}")
        return installed, True

    def _install_git(self, manifest: PackageManifest, staging: Path) -> None:
        source = staging / "source"
        _git(["init", "--quiet", str(source)])
        _git(["remote", "add", "origin", manifest.source.url], cwd=source)
        _git(["fetch", "--progress", "--depth", "1", "origin", manifest.revision], cwd=source, progress=True)
        _git(["checkout", "--quiet", "--detach", "FETCH_HEAD"], cwd=source)
        revision = _git(["rev-parse", "HEAD"], cwd=source)
        if revision != manifest.revision:
            raise PackageInstallError(
                f"package {manifest.identifier} resolved {revision}, expected {manifest.revision}"
            )
        if manifest.source.submodules:
            _git(["submodule", "update", "--init", "--recursive", "--progress"], cwd=source, progress=True)
        self._validate(manifest, source)
        _write_record(
            staging / "installed.yaml",
            manifest,
            content_path="source",
            source_revision=revision,
        )

    def _install_package_path(
        self,
        manifest: PackageManifest,
        staging: Path,
        destination: Path,
    ) -> None:
        source = manifest.source
        assert source.package is not None and source.path is not None
        parent_manifest = self.registry.get(source.package)
        if source.parent_revision and parent_manifest.revision != source.parent_revision:
            raise PackageInstallError(
                f"package {manifest.identifier} requires {source.package} at "
                f"{source.parent_revision}, registry provides {parent_manifest.revision}"
            )
        parent = self.store.read(parent_manifest)
        if parent is None:
            raise PackageInstallError(
                f"package {manifest.identifier} uses content from {source.package}; "
                f"install {source.package} first"
            )
        parent_content = parent.content_path.resolve()
        content = (parent_content / source.path).resolve()
        try:
            content.relative_to(parent_content)
        except ValueError as error:
            raise PackageInstallError(
                f"package {manifest.identifier} source path escapes {source.package}"
            ) from error
        tree_revision = _git(
            ["rev-parse", f"{parent_manifest.revision}:{source.path}"],
            cwd=parent.content_path,
        )
        if tree_revision != manifest.revision:
            raise PackageInstallError(
                f"package {manifest.identifier} content resolved {tree_revision}, "
                f"expected {manifest.revision}"
            )
        self._validate(manifest, content)
        relative_target = os.path.relpath(content, start=destination)
        (staging / "content").symlink_to(relative_target, target_is_directory=True)
        _write_record(
            staging / "installed.yaml",
            manifest,
            content_path="content",
            source_revision=tree_revision,
        )

    @staticmethod
    def _validate(manifest: PackageManifest, content: Path) -> None:
        missing = validate_content(manifest, content)
        if missing:
            raise PackageInstallError(
                f"package {manifest.identifier} is missing required content: {', '.join(missing)}"
            )

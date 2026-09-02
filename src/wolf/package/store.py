"""Deterministic on-disk package locations and human-readable records."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

from wolf.package.model import PackageManifest
from wolf.paths import packages_dir


@dataclass(frozen=True)
class InstalledPackage:
    manifest: PackageManifest
    installation_path: Path
    content_path: Path
    installed_at: str
    source_revision: str


class CorruptPackageError(ValueError):
    pass


def validate_content(manifest: PackageManifest, content_path: Path) -> tuple[str, ...]:
    return tuple(
        relative
        for relative in manifest.required_paths
        if not (content_path / relative).exists()
    )


class PackageStore:
    def __init__(self, root: Optional[Path] = None):
        self.root = (root or packages_dir()).resolve()

    def installation_path(self, manifest: PackageManifest) -> Path:
        return self.root / manifest.identifier.kind / manifest.identifier.name / manifest.revision

    def read(self, manifest: PackageManifest) -> Optional[InstalledPackage]:
        installation = self.installation_path(manifest)
        if not installation.exists():
            return None
        record = installation / "installed.yaml"
        if not installation.is_dir() or not record.is_file():
            raise CorruptPackageError(
                f"partial or corrupt package installation at {installation}; refusing to overwrite"
            )
        try:
            data = yaml.safe_load(record.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise CorruptPackageError(f"cannot read installed package record {record}: {error}") from error
        if not isinstance(data, dict):
            raise CorruptPackageError(f"invalid installed package record {record}")
        expected = str(manifest.identifier)
        if data.get("package") != expected or data.get("revision") != manifest.revision:
            raise CorruptPackageError(f"installed package record does not match {expected}")
        raw_content = data.get("content_path")
        if not isinstance(raw_content, str):
            raise CorruptPackageError(f"installed package record lacks content_path: {record}")
        content = Path(raw_content)
        if not content.is_absolute():
            content = (installation / content).resolve()
        missing = validate_content(manifest, content)
        if missing:
            raise CorruptPackageError(
                f"package {expected} is missing required content: {', '.join(missing)}"
            )
        return InstalledPackage(
            manifest=manifest,
            installation_path=installation,
            content_path=content,
            installed_at=str(data.get("installed_at", "unknown")),
            source_revision=str(data.get("source_revision", "")),
        )

    def status(self, manifest: PackageManifest) -> str:
        try:
            return "installed" if self.read(manifest) else "not installed"
        except CorruptPackageError:
            return "corrupt"

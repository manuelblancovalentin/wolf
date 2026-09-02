"""File-backed built-in package registry."""

from __future__ import annotations

import os
from pathlib import Path
import sysconfig
from typing import Any, Mapping, Optional

import yaml

from wolf import __version__
from wolf.package.model import PACKAGE_KINDS, PackageId, PackageManifest, PackageSource


class UnknownPackageError(ValueError):
    pass


class AmbiguousPackageError(ValueError):
    pass


def registry_root() -> Path:
    configured = os.environ.get("WOLF_REGISTRY")
    if configured:
        return Path(configured).expanduser().resolve()
    source_tree = Path(__file__).resolve().parents[3] / "registry"
    if source_tree.is_dir():
        return source_tree
    return Path(sysconfig.get_path("data")) / "share" / "wolf" / "registry"


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"package manifest field {field!r} must be a mapping")
    return value


def _required_string(mapping: Mapping[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"package manifest field {field!r} must be a nonempty string")
    return value


def _relative_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"package manifest field {field!r} must be a relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"package manifest field {field!r} must not escape its package root")
    return value


def load_manifest(
    path: Path, *, registry_name: str = "builtin", registry_type: str = "builtin",
    registry_revision: str | None = None,
) -> PackageManifest:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"cannot load package manifest {path}: {error}") from error
    data = _mapping(raw, "document")
    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported package manifest schema in {path}")
    identifier = PackageId(_required_string(data, "kind"), _required_string(data, "name"))
    PackageId.parse(str(identifier))
    source_data = _mapping(data.get("source"), "source")
    source_type = _required_string(source_data, "type")
    if source_type not in {"git", "package-path"}:
        raise ValueError(f"unsupported package source type {source_type!r} in {path}")
    package = source_data.get("package")
    source = PackageSource(
        type=source_type,
        url=_required_string(source_data, "url"),
        revision=_required_string(source_data, "revision"),
        submodules=source_data.get("submodules") == "recursive",
        package=PackageId.parse(package) if package else None,
        path=_relative_path(source_data.get("path"), "source.path")
        if source_type == "package-path" else None,
        parent_revision=source_data.get("parent_revision"),
    )
    if source.type == "package-path" and (source.package is None or not source.path):
        raise ValueError(f"package-path source in {path} requires package and path")
    validation = _mapping(data.get("validation", {}), "validation")
    required_paths = validation.get("required_paths", [])
    if not isinstance(required_paths, list) or not all(
        isinstance(item, str)
        and item
        and not Path(item).is_absolute()
        and ".." not in Path(item).parts
        for item in required_paths
    ):
        raise ValueError(f"validation.required_paths in {path} must contain relative paths")
    return PackageManifest(
        schema_version=1,
        identifier=identifier,
        description=_required_string(data, "description"),
        source=source,
        required_paths=tuple(required_paths),
        license=_mapping(data.get("license", {}), "license"),
        metadata=_mapping(data.get("metadata", {}), "metadata"),
        registry_name=registry_name,
        registry_type=registry_type,
        registry_revision=registry_revision,
        manifest_path=str(path.resolve()),
    )


class PackageRegistry:
    def __init__(
        self, root: Optional[Path] = None, *, registry_name: str = "builtin",
        registry_type: str = "builtin",
    ):
        override = os.environ.get("WOLF_REGISTRY") if root is None else None
        self.root = (root or (Path(override) if override else registry_root())).resolve()
        self.registry_name = registry_name
        self.registry_type = registry_type
        self.aggregate = root is None and override is None

    def _sources(self):
        yield self.registry_name, self.registry_type, self.root, __version__
        if self.aggregate:
            from wolf.registry import RegistryManager
            manager = RegistryManager()
            for spec in manager.specs():
                yield spec.name, spec.type, manager.content_root(spec), manager.revision(spec)

    def manifests(self) -> tuple[PackageManifest, ...]:
        found = []
        for name, kind_type, root, revision in self._sources():
            if not root.is_dir():
                continue
            local = []
            for kind in PACKAGE_KINDS:
                directory = root / kind
                if directory.is_dir():
                    local.extend(
                        load_manifest(path, registry_name=name, registry_type=kind_type,
                                      registry_revision=revision)
                        for path in sorted(directory.glob("*.yaml"))
                    )
            identifiers = [manifest.identifier for manifest in local]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"package registry {name!r} contains duplicate identifiers")
            found.extend(local)
        return tuple(sorted(found, key=lambda manifest: (manifest.identifier, manifest.registry_name)))

    def identifiers(self) -> tuple[str, ...]:
        return tuple(sorted(set(str(manifest.identifier) for manifest in self.manifests())))

    def completion_identifiers(self) -> tuple[str, ...]:
        grouped: dict[PackageId, list[PackageManifest]] = {}
        for manifest in self.manifests():
            grouped.setdefault(manifest.identifier, []).append(manifest)
        values = []
        for identifier, manifests in grouped.items():
            if len(manifests) == 1:
                values.append(str(identifier))
            else:
                values.extend(f"{manifest.registry_name}::{identifier}" for manifest in manifests)
        return tuple(sorted(values))

    def get(self, value: str | PackageId) -> PackageManifest:
        qualifier = None
        raw = value
        if isinstance(value, str) and "::" in value:
            qualifier, raw = value.split("::", 1)
        identifier = PackageId.parse(raw) if isinstance(raw, str) else raw
        matches = [manifest for manifest in self.manifests()
                   if manifest.identifier == identifier
                   and (qualifier is None or manifest.registry_name == qualifier)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(manifest.registry_name for manifest in matches)
            raise AmbiguousPackageError(
                f"package {identifier} is provided by multiple registries: {names}; "
                f"use REGISTRY::{identifier}"
            )
        available = ", ".join(self.identifiers())
        raise UnknownPackageError(
            f"unknown WOLF package {str(identifier)!r}; available packages: {available}"
        )

"""Stable data objects for declarative WOLF package manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Optional


PACKAGE_KINDS = ("rtl", "pdk", "flow")
_NAME = re.compile(r"^[a-z0-9]+(?:[-_.][a-z0-9]+)*$")


@dataclass(frozen=True, order=True)
class PackageId:
    kind: str
    name: str

    @classmethod
    def parse(cls, value: str) -> "PackageId":
        parts = value.split("/")
        if len(parts) != 2 or parts[0] not in PACKAGE_KINDS or not _NAME.fullmatch(parts[1]):
            kinds = ", ".join(PACKAGE_KINDS)
            raise ValueError(
                f"invalid package identifier {value!r}; expected KIND/NAME "
                f"with kind one of: {kinds}"
            )
        return cls(*parts)

    def __str__(self) -> str:
        return f"{self.kind}/{self.name}"


@dataclass(frozen=True)
class PackageSource:
    type: str
    url: str
    revision: str
    submodules: bool = False
    package: Optional[PackageId] = None
    path: Optional[str] = None
    parent_revision: Optional[str] = None


@dataclass(frozen=True)
class PackageManifest:
    schema_version: int
    identifier: PackageId
    description: str
    source: PackageSource
    required_paths: tuple[str, ...]
    license: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    registry_name: str = "builtin"
    registry_type: str = "builtin"
    registry_revision: Optional[str] = None
    manifest_path: Optional[str] = None

    @property
    def revision(self) -> str:
        return self.source.revision

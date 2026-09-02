"""Persistent external package-registry configuration and synchronization."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Optional

from wolf.config import ConfigStore
from wolf.paths import registries_dir


_NAME = re.compile(r"^[a-z0-9]+(?:[-_.][a-z0-9]+)*$")


@dataclass(frozen=True)
class RegistrySpec:
    name: str
    type: str
    source: str
    priority: int = 100


def _git(arguments: list[str], *, cwd: Optional[Path] = None) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments], cwd=cwd, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
    except OSError as error:
        raise ValueError(f"cannot execute git: {error}") from error
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit status {result.returncode}"
        raise ValueError(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout.strip()


class RegistryManager:
    def __init__(self, config: ConfigStore | None = None, root: Path | None = None):
        self.config = config or ConfigStore()
        self.root = (root or registries_dir()).resolve()

    def specs(self) -> tuple[RegistrySpec, ...]:
        entries = self.config.load()["registries"]
        found = []
        for name, raw in entries.items():
            kind = raw.get("type")
            source = raw.get("source")
            priority = raw.get("priority", 100)
            if kind not in {"git", "local"} or not isinstance(source, str) or not source:
                raise ValueError(f"invalid registry configuration for {name!r}")
            if not isinstance(priority, int):
                raise ValueError(f"registry {name!r} priority must be an integer")
            found.append(RegistrySpec(name, kind, source, priority))
        return tuple(sorted(found, key=lambda item: (item.priority, item.name)))

    def get(self, name: str) -> RegistrySpec:
        for spec in self.specs():
            if spec.name == name:
                return spec
        raise ValueError(f"unknown WOLF registry {name!r}")

    def checkout(self, spec: RegistrySpec) -> Path:
        return self.root / spec.name / "repository"

    def content_root(self, spec: RegistrySpec) -> Path:
        return Path(spec.source).expanduser().resolve() if spec.type == "local" else self.checkout(spec)

    def revision(self, spec: RegistrySpec) -> Optional[str]:
        root = self.content_root(spec)
        if spec.type != "git" or not (root / ".git").exists():
            return None
        try:
            return _git(["rev-parse", "HEAD"], cwd=root)
        except ValueError:
            return None

    def status(self, spec: RegistrySpec) -> str:
        root = self.content_root(spec)
        if not root.is_dir():
            return "unavailable"
        try:
            from wolf.package.registry import PackageRegistry
            PackageRegistry(root, registry_name=spec.name, registry_type=spec.type).manifests()
        except ValueError:
            return "invalid"
        return "ready"

    def add(self, name: str, source: str, kind: str | None = None, priority: int = 100) -> RegistrySpec:
        if not _NAME.fullmatch(name) or name == "builtin":
            raise ValueError("registry name must use lowercase letters, digits, '.', '_' or '-'")
        if any(spec.name == name for spec in self.specs()):
            raise ValueError(f"WOLF registry {name!r} already exists")
        source_path = Path(source).expanduser()
        inferred = "local" if source_path.exists() else "git"
        kind = kind or inferred
        if kind not in {"git", "local"}:
            raise ValueError("registry type must be git or local")
        if kind == "local":
            if not source_path.is_dir():
                raise ValueError(f"local registry is not a directory: {source_path}")
            source = str(source_path.resolve())
            spec = RegistrySpec(name, kind, source, priority)
            from wolf.package.registry import PackageRegistry
            PackageRegistry(Path(source), registry_name=name, registry_type=kind).manifests()
        else:
            if "://" in source and "@" in source.split("://", 1)[1].split("/", 1)[0]:
                raise ValueError(
                    "registry URLs must not embed credentials; use Git credential management"
                )
            if shutil.which("git") is None:
                raise ValueError("git is required to add a Git registry")
            spec = RegistrySpec(name, kind, source, priority)
            destination = self.checkout(spec)
            if destination.exists():
                raise ValueError(f"registry checkout already exists: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                _git(["clone", "--", source, str(destination)])
                from wolf.package.registry import PackageRegistry
                PackageRegistry(destination, registry_name=name, registry_type=kind).manifests()
            except Exception:
                if destination.exists():
                    shutil.rmtree(destination)
                raise
        document = self.config.load()
        document["registries"][name] = {
            "type": kind, "source": source, "priority": priority,
        }
        self.config.write(document)
        return spec

    def sync(self, name: str | None = None) -> tuple[RegistrySpec, ...]:
        selected = (self.get(name),) if name else self.specs()
        for spec in selected:
            if spec.type == "git":
                checkout = self.checkout(spec)
                if not checkout.is_dir():
                    raise ValueError(f"Git registry {spec.name!r} has no checkout; add it again")
                _git(["pull", "--ff-only"], cwd=checkout)
        return selected

    def remove(self, name: str) -> RegistrySpec:
        spec = self.get(name)
        document = self.config.load()
        del document["registries"][name]
        self.config.write(document)
        if spec.type == "git":
            checkout_parent = self.checkout(spec).parent
            if checkout_parent.is_dir() and checkout_parent.parent == self.root:
                shutil.rmtree(checkout_parent)
        return spec

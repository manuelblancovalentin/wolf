"""OpenROAD Flow Scripts backend identity and local validation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
from typing import Mapping, Optional, Sequence

from wolf.backend.base import Backend, ValidationItem


ORFS_STAGES = ("synth", "floorplan", "place", "cts", "route", "finish")


@dataclass(frozen=True)
class OrfsMetadata:
    root: Optional[Path]
    runtime: Optional[str]
    container_image: Optional[str]
    revision: Optional[str]


@dataclass(frozen=True)
class RuntimeDiagnostic:
    name: str
    usable: bool
    detail: str


def _value(context: Optional[Mapping[str, str]], name: str) -> Optional[str]:
    if context is not None and name in context:
        return context[name]
    return os.environ.get(name)


def _configured_runtime(context: Optional[Mapping[str, str]]) -> Optional[str]:
    return _value(context, "ORFS_CONTAINER_RUNTIME") or _value(
        context, "WOLF_CONTAINER_RUNTIME"
    )


def _runtime_diagnostic(name: str) -> RuntimeDiagnostic:
    location = shutil.which(name)
    if location is None:
        return RuntimeDiagnostic(name, False, "binary absent")
    try:
        result = subprocess.run(
            [name, "info"],
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        return RuntimeDiagnostic(name, False, f"installed but unavailable: {error}")
    if result.returncode == 0:
        return RuntimeDiagnostic(name, True, f"usable ({location})")
    error = result.stderr.strip().splitlines()
    detail = error[0] if error else f"exit status {result.returncode}"
    if "permission denied" in detail.lower():
        return RuntimeDiagnostic(name, False, f"installed but permission denied: {detail}")
    return RuntimeDiagnostic(name, False, f"installed but daemon/socket unavailable: {detail}")


def _detect_runtime(context: Optional[Mapping[str, str]]) -> Optional[str]:
    configured = _configured_runtime(context)
    if configured:
        return configured
    for name in ("podman", "docker"):
        if _runtime_diagnostic(name).usable:
            return name
    return None


def _git_revision(root: Optional[Path]) -> Optional[str]:
    if root is None or not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


class OrfsBackend(Backend):
    name = "orfs"
    description = "OpenROAD Flow Scripts container compatibility backend"
    adapter_filename = "orfs.sh"
    execution_style = "container (Docker or Podman)"

    def stages(self) -> Sequence[str]:
        return ORFS_STAGES

    def metadata(self, context: Optional[Mapping[str, str]] = None) -> OrfsMetadata:
        configured_root = _value(context, "ORFS_ROOT")
        root = Path(configured_root).expanduser().resolve() if configured_root else None
        return OrfsMetadata(
            root=root,
            runtime=_detect_runtime(context),
            container_image=_value(context, "ORFS_CONTAINER_IMAGE"),
            revision=_git_revision(root),
        )

    def validate(
        self, context: Optional[Mapping[str, str]] = None
    ) -> Sequence[ValidationItem]:
        configured_root = _value(context, "ORFS_ROOT")
        root = Path(configured_root).expanduser() if configured_root else None
        root_available = root is not None and root.is_dir()
        root_detail = str(root) if root_available else "not configured"
        if configured_root and not root_available:
            root_detail = f"not a directory: {root}"

        runtime = _detect_runtime(context)
        configured_runtime = _configured_runtime(context)
        diagnostics = {name: _runtime_diagnostic(name) for name in ("podman", "docker")}
        runtime_available = runtime in {"docker", "podman"} and diagnostics[runtime].usable
        if configured_runtime and configured_runtime not in {"docker", "podman"}:
            runtime_available = False
        runtime_detail = diagnostics[runtime].detail if runtime in diagnostics else "unsupported runtime"

        checks = [
            ValidationItem("ORFS_ROOT", root_available, root_detail),
            ValidationItem(
                "Makefile",
                bool(root_available and (root / "Makefile").is_file()),
                str(root / "Makefile") if root else "ORFS_ROOT not configured",
            ),
            ValidationItem(
                "util/docker_shell",
                bool(root_available and (root / "util" / "docker_shell").is_file()),
                str(root / "util" / "docker_shell") if root else "ORFS_ROOT not configured",
            ),
            ValidationItem(
                "selected container runtime",
                runtime_available,
                f"{runtime or 'none'} ({runtime_detail})",
            ),
            *(
                ValidationItem(f"{name} runtime", diagnostic.usable, diagnostic.detail)
                for name, diagnostic in diagnostics.items()
            ),
        ]

        image = _value(context, "ORFS_CONTAINER_IMAGE") or "openroad/orfs:latest"
        checks.append(
            ValidationItem(
                "container image",
                True,
                image + (" (floating tag)" if "@sha256:" not in image else " (pinned)"),
            )
        )
        return tuple(checks)


ORFS = OrfsBackend()

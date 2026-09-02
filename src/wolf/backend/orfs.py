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


def _value(context: Optional[Mapping[str, str]], name: str) -> Optional[str]:
    if context is not None and name in context:
        return context[name]
    return os.environ.get(name)


def _configured_runtime(context: Optional[Mapping[str, str]]) -> Optional[str]:
    return _value(context, "ORFS_CONTAINER_RUNTIME") or _value(
        context, "WOLF_CONTAINER_RUNTIME"
    )


def _detect_runtime(context: Optional[Mapping[str, str]]) -> Optional[str]:
    configured = _configured_runtime(context)
    if configured:
        return configured
    for name in ("docker", "podman"):
        if shutil.which(name):
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
        runtime_available = runtime in {"docker", "podman"} and shutil.which(runtime) is not None
        if configured_runtime and configured_runtime not in {"docker", "podman"}:
            runtime_available = False
        runtime_detail = (
            shutil.which(runtime) or "unavailable"
            if runtime_available and runtime
            else "unavailable"
        )

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
                "container runtime",
                runtime_available,
                f"{runtime or 'none'} ({runtime_detail})",
            ),
        ]

        image = _value(context, "ORFS_CONTAINER_IMAGE")
        if runtime == "podman":
            checks.append(
                ValidationItem(
                    "ORFS_CONTAINER_IMAGE",
                    bool(image),
                    image or "required for Podman execution",
                )
            )
        else:
            checks.append(
                ValidationItem(
                    "container image",
                    True,
                    image or "selected by ORFS util/docker_shell",
                )
            )
        return tuple(checks)


ORFS = OrfsBackend()

"""OpenROAD Flow Scripts backend identity and local validation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import json
import re
from typing import Mapping, Optional, Sequence

from wolf.backend.base import Backend, ValidationItem
from wolf.package.registry import PackageRegistry
from wolf.package.store import PackageStore
from wolf.backend.orfs_native import prepare_native_orfs
from wolf.context import ResolvedContext
from wolf.config import ConfigStore


ORFS_STAGES = ("synth", "floorplan", "place", "cts", "route", "finish")


@dataclass(frozen=True)
class OrfsMetadata:
    root: Optional[Path]
    root_source: Optional[str]
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
    ) or ConfigStore().get("container.preferred_runtime")


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
    if root is None:
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


def _installed_orfs_root() -> Optional[Path]:
    manifest = PackageRegistry().get("flow/orfs")
    installed = PackageStore().read(manifest)
    if installed is None:
        return None
    relative = manifest.metadata.get("flow_root")
    if not isinstance(relative, str) or not relative:
        raise ValueError("flow/orfs package manifest does not define metadata.flow_root")
    return (installed.content_path / relative).resolve()


class OrfsBackend(Backend):
    name = "orfs"
    description = "OpenROAD Flow Scripts container compatibility backend"
    adapter_filename = "orfs.sh"
    execution_style = "container (Docker or Podman)"

    def stages(self) -> Sequence[str]:
        return ORFS_STAGES

    def extract_metrics(self, run_directory):
        """Extract the small stable metric set used by the golden regression."""
        root = Path(run_directory)
        result = {}
        report = next(iter(sorted(root.rglob("6_finish.rpt"))), None)
        if report and report.is_file():
            text = report.read_text(encoding="utf-8", errors="replace")
            patterns = {
                "timing.worst_slack_ps": r"^\s*worst\s+slack\s+max\s+([-+]?\d+(?:\.\d+)?)\s*$",
                "electrical.max_slew_violations": r"^\s*max\s+slew\s+violation\s+count\s+(\d+)\s*$",
                "electrical.max_fanout_violations": r"^\s*max\s+fanout\s+violation\s+count\s+(\d+)\s*$",
                "electrical.max_cap_violations": r"^\s*max\s+cap\s+violation\s+count\s+(\d+)\s*$",
                "timing.setup_violations": r"^\s*setup\s+violation\s+count\s+(\d+)\s*$",
                "timing.hold_violations": r"^\s*hold\s+violation\s+count\s+(\d+)\s*$",
            }
            for key, pattern in patterns.items():
                match = re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE)
                if not match and key in {"timing.setup_violations", "timing.hold_violations"}:
                    kind = "setup" if "setup" in key else "hold"
                    match = re.search(
                        rf"finish\s+{kind}_violation_count(?:\s+|\s*$).*?{kind}\s+violation\s+count\s+(\d+)",
                        text, flags=re.MULTILINE | re.IGNORECASE | re.DOTALL,
                    )
                if match:
                    result[key] = float(match.group(1)) if "slack" in key else int(match.group(1))

        drc = next(iter(sorted(root.rglob("5_route_drc.rpt"))), None)
        if drc and drc.is_file():
            text = drc.read_text(encoding="utf-8", errors="replace")
            if not text.strip():
                result["physical.drc_violations"] = 0
            else:
                for pattern in (
                    r"^\s*(?:total\s+)?(?:drc\s+)?violations?\s*[:=]\s*(\d+)\s*$",
                    r"^\s*total\s+number\s+of\s+violations\s*[:=]\s*(\d+)\s*$",
                ):
                    match = re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE)
                    if match:
                        result["physical.drc_violations"] = int(match.group(1))
                        break

        metadata = next(iter(sorted(root.rglob("metadata.json"))), None)
        if metadata and metadata.is_file():
            try:
                raw = json.loads(metadata.read_text(encoding="utf-8"))
                flat = {}
                def flatten(value, prefix=""):
                    if isinstance(value, dict):
                        for key, child in value.items():
                            flatten(child, f"{prefix}.{key}" if prefix else str(key))
                    else:
                        flat[prefix.lower()] = value
                flatten(raw)
                for target, needles in {
                    "timing.worst_slack_ps": ("finish", "setup", "ws"),
                    "physical.drc_violations": ("detailedroute", "drc", "error"),
                    "electrical.max_slew_violations": ("finish", "slew", "violation"),
                    "electrical.max_fanout_violations": ("finish", "fanout", "violation"),
                    "electrical.max_cap_violations": ("finish", "cap", "violation"),
                }.items():
                    for key, value in flat.items():
                        if all(needle in key for needle in needles):
                            if isinstance(value, (int, float)) and not isinstance(value, bool) and target not in result:
                                result[target] = value
                            break
            except (OSError, ValueError, TypeError):
                pass
        return result

    def infer_stage_results(self, run_directory):
        root = Path(run_directory)
        names = {
            "synth": "1_synth.odb",
            "floorplan": "2_floorplan.odb",
            "place": "3_place.odb",
            "cts": "4_cts.odb",
            "route": "5_route.odb",
        }
        inferred = {stage: "complete" for stage, filename in names.items()
                    if any(path.is_file() for path in root.rglob(filename))}
        finish = (any(path.is_file() for path in root.rglob("6_final.odb")) and
                  any(path.is_file() for path in root.rglob("6_final.gds")))
        if finish:
            inferred["finish"] = "complete"
            # ORFS executes these stages sequentially; a final database is
            # sufficient evidence that each preceding stage completed.
            inferred.update({stage: "complete" for stage in ORFS_STAGES[:-1]})
        return inferred

    def metadata(self, context: Optional[Mapping[str, str]] = None) -> OrfsMetadata:
        configured_root = _value(context, "ORFS_ROOT")
        root = Path(configured_root).expanduser().resolve() if configured_root else _installed_orfs_root()
        return OrfsMetadata(
            root=root,
            root_source="explicit/environment ORFS_ROOT" if configured_root else (
                "installed flow/orfs package" if root else None
            ),
            runtime=_detect_runtime(context),
            container_image=_value(context, "ORFS_CONTAINER_IMAGE"),
            revision=_git_revision(root),
        )

    def validate(
        self, context: Optional[Mapping[str, str]] = None
    ) -> Sequence[ValidationItem]:
        configured_root = _value(context, "ORFS_ROOT")
        installed_root = None if configured_root else _installed_orfs_root()
        root = Path(configured_root).expanduser() if configured_root else installed_root
        root_available = root is not None and root.is_dir()
        root_detail = str(root) if root_available else "not configured or installed"
        if root_available and installed_root is not None:
            root_detail += " (installed flow/orfs package)"
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

        image = _value(context, "ORFS_CONTAINER_IMAGE") or "docker.io/openroad/orfs:latest"
        checks.append(
            ValidationItem(
                "container image",
                True,
                image + (" (floating tag)" if "@sha256:" not in image else " (pinned)"),
            )
        )
        return tuple(checks)

    def execution_environment(
        self, context: Optional[Mapping[str, str]] = None
    ) -> Mapping[str, str]:
        metadata = self.metadata(context)
        return {"ORFS_ROOT": str(metadata.root)} if metadata.root is not None else {}

    def prepare_execution(self, context: ResolvedContext) -> Mapping[str, str]:
        metadata = self.metadata(context.values)
        execution = {"ORFS_ROOT": str(metadata.root)} if metadata.root is not None else {}
        if context.format != "declarative-v1":
            return execution
        root = Path(execution["ORFS_ROOT"]) if execution.get("ORFS_ROOT") else None
        if root is None:
            raise ValueError("ORFS_ROOT is not configured and flow/orfs is not installed")
        execution.update(
            prepare_native_orfs(
                context,
                root,
                runtime=metadata.runtime,
                container_image=metadata.container_image or "docker.io/openroad/orfs:latest",
            )
        )
        return execution


ORFS = OrfsBackend()

"""Versioned, human-inspectable snapshots of a backend's flow scripts.

Cut only on explicit user action (`wolf flow snapshot`), living under
<project_root>/inputs/flows/<design_name>/flow.<N>/ -- a project-scoped
sibling of the per-run `scripts.<N>` snapshot `wolf.backend.cadence_genus`
already writes inside each numbered run directory. Both use the exact same
per-file sha256-of-sha256 content digest (`content_digest`, below); only the
storage location and cut-trigger differ (every run vs. only on explicit
`wolf flow snapshot`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Mapping

_FLOW_DIR_RE = re.compile(r"^flow\.(\d+)$")

_CHANGELOG_HEADER = (
    "# Flow snapshot changelog\n\n"
    "Each row is one `wolf flow snapshot` that actually changed the flow\n"
    "scripts' content; an unchanged snapshot is a no-op and adds no row.\n\n"
    "| Version | Date | Digest | Changed steps |\n"
    "|---|---|---|---|\n"
)


def content_digest(files: Mapping[str, str]) -> str:
    """A single sha256 over a {filename: text} mapping, computed as a
    hash-of-hashes keyed by filename (not a plain concatenation) so the
    result is independent of dict/glob ordering. Shared with
    `cadence_genus._snapshot_scripts`'s own run-local snapshot -- same
    algorithm, two call sites, so a run's `scripts.<N>` and a project's
    `flow.<N>` are comparable by digest if ever useful."""
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(files[name].encode("utf-8")).hexdigest().encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


@dataclass(frozen=True)
class FlowSnapshotResult:
    directory: Path
    version: int
    created: bool
    changed_steps: tuple[str, ...]


def flows_directory(project_root: Path, design_name: str) -> Path:
    return project_root / "inputs" / "flows" / design_name


def _existing_versions(base: Path) -> list[tuple[int, Path]]:
    if not base.is_dir():
        return []
    return sorted(
        (int(match.group(1)), path)
        for path in base.glob("flow.*")
        if path.is_dir() and (match := _FLOW_DIR_RE.match(path.name))
    )


def _read_step_digests(directory: Path) -> dict[str, str]:
    path = directory / "flow.step-digests"
    if not path.is_file():
        return {}
    digests: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        name, _, value = line.partition(" ")
        digests[name] = value
    return digests


def _write_step_digests(directory: Path, step_digests: Mapping[str, str]) -> None:
    lines = [f"{name} {digest}" for name, digest in sorted(step_digests.items())]
    text = "\n".join(lines) + ("\n" if lines else "")
    (directory / "flow.step-digests").write_text(text, encoding="utf-8")


def _append_changelog(
    base: Path, version: int, digest: str, changed_steps: tuple[str, ...],
) -> None:
    path = base / "CHANGELOG.md"
    if not path.is_file():
        path.write_text(_CHANGELOG_HEADER, encoding="utf-8")
    if version == 1:
        changed = "(initial snapshot)"
    elif changed_steps:
        changed = ", ".join(changed_steps)
    else:
        changed = "(no step body changed -- non-step content differs)"
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"| {version} | {date} | {digest[:12]} | {changed} |\n")


def _relink_latest(base: Path, target: Path) -> None:
    link = base / "flow.latest"
    link.unlink(missing_ok=True)
    link.symlink_to(target.name)


def snapshot_flow(
    project_root: Path,
    design_name: str,
    files: Mapping[str, str],
    step_digests: Mapping[str, str],
) -> FlowSnapshotResult:
    """Cut a new inputs/flows/<design>/flow.<N> snapshot of `files` (name ->
    text) if its content digest differs from the latest existing snapshot;
    otherwise report that latest snapshot unchanged. `step_digests` (e.g.
    `cadence_genus.flow_step_digests()`) is stored alongside the new
    snapshot so a later snapshot can report which steps changed without
    re-parsing old Tcl."""
    base = flows_directory(project_root, design_name)
    existing = _existing_versions(base)
    digest = content_digest(files)

    if existing:
        latest_version, latest_directory = existing[-1]
        checksum_file = latest_directory / "flow.sha256checksum"
        if checksum_file.is_file() and checksum_file.read_text(encoding="utf-8").strip() == digest:
            return FlowSnapshotResult(latest_directory, latest_version, created=False, changed_steps=())
        previous_steps = _read_step_digests(latest_directory)
        changed_steps = tuple(sorted(
            name for name in set(previous_steps) | set(step_digests)
            if previous_steps.get(name) != step_digests.get(name)
        ))
        next_version = latest_version + 1
    else:
        changed_steps = ()
        next_version = 1

    directory = base / f"flow.{next_version}"
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        destination = directory / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    (directory / "flow.sha256checksum").write_text(digest, encoding="utf-8")
    _write_step_digests(directory, step_digests)
    _append_changelog(base, next_version, digest, changed_steps)
    _relink_latest(base, directory)
    return FlowSnapshotResult(directory, next_version, created=True, changed_steps=changed_steps)

"""Small, deterministic resolution bridge for legacy WOLF executions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional


_PATH_VARIABLES = frozenset(
    {
        "WORKSPACE_DIR",
        "DATA_DIR",
        "HDL_SEARCH_PATH",
        "RTL_YAML_FILE",
        "FLOORPLAN_FILE",
        "FLOORPLAN_IO_FILE",
        "CONSTRAINTS_FILE",
        "PROCESS_SCRIPTS",
        "PROCESS_SETUP_COMMON_TEMPLATE",
        "PROCESS_SETUP_HOST_TEMPLATE",
        "PROCESS_FLOW_TEMPLATE",
        "YAML_TEMPLATE_FILE",
        "ORFS_ROOT",
        "ORFS_DESIGN_CONFIG",
        "ORFS_SDC_FILE",
    }
)


def resolve_stored_path(value: str, base_directory: Path) -> Path:
    """Resolve a stored path relative to its environment/manifest directory."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_directory / path
    return path.resolve()


def resolve_cli_path(value: str, invocation_directory: Path) -> Path:
    """Resolve a path explicitly typed on the command line."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = invocation_directory / path
    return path.resolve()


@dataclass(frozen=True)
class ResolvedContext:
    """Complete location-independent execution inputs used by the compatibility bridge."""

    state_root: Path
    environment_name: Optional[str]
    environment_directory: Optional[Path]
    workspace_root: Path
    design_name: str
    process: str
    backend: str
    run_tag: str
    run_directory: Path
    values: Mapping[str, str]
    format: str = "legacy"
    design_top: Optional[str] = None
    flow_name: Optional[str] = None
    design_package: Optional[str] = None
    technology_package: Optional[str] = None
    flow_package: Optional[str] = None
    package_revisions: Mapping[str, str] = field(default_factory=dict)
    package_paths: Mapping[str, Path] = field(default_factory=dict)
    clocks: tuple[Any, ...] = ()
    threads: Optional[int] = None
    backend_overrides: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


def resolve_context(
    values: Mapping[str, str],
    *,
    state_root: Path,
    environment_name: Optional[str] = None,
    environment_directory: Optional[Path] = None,
    invocation_directory: Optional[Path] = None,
    cli_paths: Optional[Mapping[str, str]] = None,
    overrides: Optional[Mapping[str, str]] = None,
) -> ResolvedContext:
    """Resolve compatibility inputs without allowing caller cwd to become state."""
    invocation_directory = (invocation_directory or Path.cwd()).resolve()
    stored_base = (environment_directory or state_root).resolve()
    resolved = dict(values)
    for name in _PATH_VARIABLES:
        value = resolved.get(name)
        if value:
            resolved[name] = str(resolve_stored_path(value, stored_base))
    for name, value in (cli_paths or {}).items():
        if value:
            resolved[name] = str(resolve_cli_path(value, invocation_directory))
    resolved.update({name: value for name, value in (overrides or {}).items() if value})

    design_name = resolved.get("DESIGN_NAME", "")
    process = resolved.get("PROCESS", "")
    backend = resolved.get("BACKEND", "cadence-flowtool")
    workspace = resolved.get("WORKSPACE_DIR", "")
    run_tag = resolved.get("RUNTAG") or design_name
    missing = [
        label
        for label, value in (
            ("design", design_name),
            ("process", process),
            ("workspace root", workspace),
            ("backend", backend),
        )
        if not value
    ]
    if missing:
        raise ValueError("incomplete WOLF run context; missing " + ", ".join(missing))

    workspace_root = resolve_stored_path(workspace, stored_base)
    resolved["WORKSPACE_DIR"] = str(workspace_root)
    run_directory = workspace_root / design_name / f"{design_name}.{process}" / run_tag
    return ResolvedContext(
        state_root=state_root.resolve(),
        environment_name=environment_name,
        environment_directory=environment_directory.resolve() if environment_directory else None,
        workspace_root=workspace_root,
        design_name=design_name,
        process=process,
        backend=backend,
        run_tag=run_tag,
        run_directory=run_directory,
        values=resolved,
    )

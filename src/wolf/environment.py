"""Versioned declarative environment profiles and semantic resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

from wolf.context import ResolvedContext, resolve_stored_path
from wolf.package.model import PackageId
from wolf.package.registry import PackageRegistry
from wolf.package.store import PackageStore


ENVIRONMENT_SCHEMA = "wolf.environment/v1"
ENVIRONMENT_FILENAME = "wolf.yaml"
_TOP_LEVEL_FIELDS = {
    "schema", "name", "design", "technology", "flow", "workspace",
    "constraints", "resources", "backend",
}


@dataclass(frozen=True)
class ClockConstraint:
    name: str
    port: str
    period_ps: float


@dataclass(frozen=True)
class ComponentReference:
    package: Optional[str] = None
    name: Optional[str] = None
    top: Optional[str] = None


@dataclass(frozen=True)
class EnvironmentProfile:
    name: str
    path: Path
    design: Optional[ComponentReference] = None
    technology: Optional[ComponentReference] = None
    flow: Optional[ComponentReference] = None
    workspace_root: Optional[str] = None
    clocks: tuple[ClockConstraint, ...] = ()
    threads: Optional[int] = None
    backend_overrides: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


def _mapping(value: Any, field: str, *, optional: bool = False) -> Mapping[str, Any]:
    if value is None and optional:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def _known_fields(data: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        prefix = f"{field}." if field else ""
        raise ValueError(f"unknown environment field: {prefix}{unknown[0]}")


def _optional_string(value: Any, field: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _component(data: Any, field: str, expected_kind: str) -> Optional[ComponentReference]:
    if data is None:
        return None
    mapping = _mapping(data, field)
    allowed = {"package", "name"} | ({"top"} if field == "design" else set())
    _known_fields(mapping, allowed, field)
    package = _optional_string(mapping.get("package"), f"{field}.package")
    if package and PackageId.parse(package).kind != expected_kind:
        raise ValueError(f"{field}.package must identify a {expected_kind} package")
    name = _optional_string(mapping.get("name"), f"{field}.name")
    top = _optional_string(mapping.get("top"), f"{field}.top") if field == "design" else None
    if not any((package, name, top)):
        raise ValueError(f"{field} must define at least one value")
    return ComponentReference(package=package, name=name, top=top)


def load_environment(path: Path, *, expected_name: Optional[str] = None) -> EnvironmentProfile:
    """Load and strictly validate one declarative-v1 environment."""
    path = path.expanduser().resolve()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"cannot load WOLF environment {path}: {error}") from error
    data = _mapping(raw, "environment document")
    schema = data.get("schema")
    if schema != ENVIRONMENT_SCHEMA:
        raise ValueError(f"unsupported WOLF environment schema {schema!r}; expected {ENVIRONMENT_SCHEMA}")
    _known_fields(data, _TOP_LEVEL_FIELDS, "")
    name = _optional_string(data.get("name"), "name")
    if expected_name and name and name != expected_name:
        raise ValueError(
            f"environment name {name!r} does not match requested name {expected_name!r}"
        )
    name = expected_name or name
    if not name:
        raise ValueError("environment name is required")

    workspace = _mapping(data.get("workspace"), "workspace", optional=True)
    _known_fields(workspace, {"root"}, "workspace")
    workspace_root = _optional_string(workspace.get("root"), "workspace.root")

    constraints = _mapping(data.get("constraints"), "constraints", optional=True)
    _known_fields(constraints, {"clocks"}, "constraints")
    raw_clocks = constraints.get("clocks", [])
    if not isinstance(raw_clocks, list):
        raise ValueError("constraints.clocks must be a sequence")
    clocks = []
    for index, raw_clock in enumerate(raw_clocks):
        field = f"constraints.clocks[{index}]"
        clock = _mapping(raw_clock, field)
        _known_fields(clock, {"name", "port", "period_ps"}, field)
        clock_name = _optional_string(clock.get("name"), f"{field}.name")
        port = _optional_string(clock.get("port"), f"{field}.port")
        period = clock.get("period_ps")
        if not isinstance(period, (int, float)) or isinstance(period, bool) or period <= 0:
            raise ValueError(f"{field}.period_ps must be a positive number")
        if not clock_name or not port:
            raise ValueError(f"{field} requires name and port")
        clocks.append(ClockConstraint(clock_name, port, float(period)))

    resources = _mapping(data.get("resources"), "resources", optional=True)
    _known_fields(resources, {"threads"}, "resources")
    threads = resources.get("threads")
    if threads is not None and (not isinstance(threads, int) or isinstance(threads, bool) or threads <= 0):
        raise ValueError("resources.threads must be a positive integer")

    backend = _mapping(data.get("backend"), "backend", optional=True)
    for backend_name, overrides in backend.items():
        if not isinstance(backend_name, str) or not backend_name:
            raise ValueError("backend names must be nonempty strings")
        _mapping(overrides, f"backend.{backend_name}")

    return EnvironmentProfile(
        name=name,
        path=path,
        design=_component(data.get("design"), "design", "rtl"),
        technology=_component(data.get("technology"), "technology", "pdk"),
        flow=_component(data.get("flow"), "flow", "flow"),
        workspace_root=workspace_root,
        clocks=tuple(clocks),
        threads=threads,
        backend_overrides=backend,
    )


def normalize_environment(source: Path, destination: Path, *, name: str) -> EnvironmentProfile:
    """Validate an imported profile and persist stable manifest-relative paths."""
    profile = load_environment(source, expected_name=name)
    data = yaml.safe_load(profile.path.read_text(encoding="utf-8"))
    data["name"] = name
    if profile.workspace_root:
        data.setdefault("workspace", {})["root"] = str(
            resolve_stored_path(profile.workspace_root, profile.path.parent)
        )
    destination.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return load_environment(destination, expected_name=name)


def environment_manifest(environment_directory: Path) -> Optional[Path]:
    path = environment_directory / ENVIRONMENT_FILENAME
    return path if path.is_file() else None


def _semantic(manifest: Any, section: str, field: str) -> Optional[str]:
    section_data = manifest.metadata.get(section, {})
    value = section_data.get(field) if isinstance(section_data, dict) else None
    return value if isinstance(value, str) and value else None


def resolve_declarative_environment(
    profile: EnvironmentProfile,
    *,
    state_root: Path,
    environment_directory: Path,
    design_override: Optional[str] = None,
    backend_override: Optional[str] = None,
    workspace_override: Optional[Path] = None,
    run_tag: Optional[str] = None,
    require_installed: bool = True,
) -> ResolvedContext:
    """Resolve package defaults and profile overrides into one complete context."""
    registry = PackageRegistry()
    store = PackageStore()
    references = {
        "design": profile.design,
        "technology": profile.technology,
        "flow": profile.flow,
    }
    if design_override:
        references["design"] = ComponentReference(package=design_override)

    manifests: dict[str, Any] = {}
    installed: dict[str, Any] = {}
    expected_kinds = {"design": "rtl", "technology": "pdk", "flow": "flow"}
    for role, reference in references.items():
        if reference and reference.package:
            identifier = PackageId.parse(reference.package)
            if identifier.kind != expected_kinds[role]:
                raise ValueError(f"{role} package must have kind {expected_kinds[role]}")
            manifest = registry.get(reference.package)
            manifests[role] = manifest
            package = store.read(manifest)
            if package is not None:
                installed[role] = package
            elif require_installed:
                raise ValueError(f"required package {reference.package} is not installed")

    design = references["design"]
    technology = references["technology"]
    flow = references["flow"]
    design_name = (design.name if design else None) or (
        _semantic(manifests["design"], "design", "name") if "design" in manifests else None
    )
    design_top = (design.top if design else None) or (
        _semantic(manifests["design"], "design", "top") if "design" in manifests else None
    )
    technology_name = (technology.name if technology else None) or (
        _semantic(manifests["technology"], "technology", "name")
        if "technology" in manifests else None
    )
    flow_name = (flow.name if flow else None) or (
        _semantic(manifests["flow"], "flow", "name") if "flow" in manifests else None
    )
    flow_backend = (
        _semantic(manifests["flow"], "flow", "backend") if "flow" in manifests else None
    )
    backend = backend_override or flow_backend
    workspace_root = workspace_override or (
        resolve_stored_path(profile.workspace_root, profile.path.parent)
        if profile.workspace_root else None
    )
    missing = [
        field for field, value in (
            ("design", design_name), ("technology", technology_name), ("flow", flow_name),
            ("backend", backend), ("workspace.root", workspace_root),
        ) if not value
    ]
    if missing:
        raise ValueError("incomplete WOLF run context; unresolved required field: " + ", ".join(missing))

    run_identity = run_tag or design_name
    run_directory = Path(workspace_root) / design_name / f"{design_name}.{technology_name}" / run_identity
    values = {
        "DESIGN_NAME": design_name,
        "PROCESS": technology_name,
        "BACKEND": backend,
        "WORKSPACE_DIR": str(workspace_root),
        "RUNTAG": run_identity,
    }
    package_revisions = {
        str(manifest.identifier): manifest.revision for manifest in manifests.values()
    }
    package_paths = {
        role: package.content_path for role, package in installed.items()
    }
    return ResolvedContext(
        state_root=state_root.resolve(),
        environment_name=profile.name,
        environment_directory=environment_directory.resolve(),
        workspace_root=Path(workspace_root).resolve(),
        design_name=design_name,
        process=technology_name,
        backend=backend,
        run_tag=run_identity,
        run_directory=run_directory.resolve(),
        values=values,
        format="declarative-v1",
        design_top=design_top,
        flow_name=flow_name,
        design_package=design.package if design else None,
        technology_package=technology.package if technology else None,
        flow_package=flow.package if flow else None,
        package_revisions=package_revisions,
        package_paths=package_paths,
        clocks=profile.clocks,
        threads=profile.threads,
        backend_overrides=profile.backend_overrides,
    )

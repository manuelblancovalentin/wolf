"""Versioned declarative environment profiles and semantic resolution."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
import re
try:  # Python 3.9/3.10 compatibility
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on older runtimes
    import tomli as tomllib
from typing import Any, Mapping, Optional

import yaml

from wolf.context import (
    CatalogFileList, CatalogLibrarySet, ResolvedAnalysisView, ResolvedContext, ResolvedDelayCorner,
    ResolvedOpcond, ResolvedQrcCorner, ResolvedSource, ResolvedTechnology, ResolvedTimingCorner,
    resolve_stored_path,
)
from wolf.package.model import PackageId
from wolf.package.registry import PackageRegistry
from wolf.package.store import PackageStore
from wolf.paths import cache_dir


_ENV_VAR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

ENVIRONMENT_SCHEMA = "wolf.environment/v1"
ENVIRONMENT_FILENAME = "wolf.yaml"
_TOP_LEVEL_FIELDS = {
    "schema", "name", "design", "technology", "flow", "project", "workspace",
    "constraints", "resources", "backend", "env",
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
    # track/vth: the primary (first-listed) selection, used to resolve the
    # one flattened variant (lef/gds/qrc_techfiles/timing_corners, ...)
    # most of the rest of this module still works with. tracks/vths: every
    # name actually selected -- a real flow mixes multiple vth libraries
    # in one synthesis run (confirmed against real Tcl: synthesis.tcl's
    # `foreach trk [get_flow_config tracks] { foreach vth [get_flow_config
    # vths] { ... } }`, unioning library/lef files across the full
    # cross product), so technology.track/technology.vth accept a list as
    # well as a single string -- see _track_or_vth_selection. A single
    # string is exactly the one-element case: track/vth equal tracks[0]/
    # vths[0].
    track: Optional[str] = None
    vth: Optional[str] = None
    tracks: tuple[str, ...] = ()
    vths: tuple[str, ...] = ()
    metal_stack: Optional[str] = None
    # technology only: the process technology value Innovus's own
    # design_process_node attribute expects (nm, man 20.15, default 90
    # -- confirmed real, a run never setting this explicitly logged
    # "Design Mode: 90nm" and IMPEXT-3530 at every implementation
    # stage regardless of the actual resolved PDK). Not derived from
    # the package name (fragile: not every PDK package name encodes
    # the node size the same way) -- a project declares it explicitly.
    process_node_nm: Optional[int] = None
    # flow.backend only: persists a bundled-default flow's backend choice
    # (cadence-flowtool, orfs, ...) in wolf.yaml itself, rather than it
    # only ever existing as a `wolf run --backend` override that has to
    # be typed on every single invocation. A flow.package's own
    # manifest.flow.backend still takes priority when both are present.
    backend: Optional[str] = None


@dataclass(frozen=True)
class SourceEntry:
    """One design.sources entry: a portable package reference, a local
    single file, or a local manifest.toml bundle.

    A package entry (e.g. rtl/ibex) is reproducible anywhere `wolf install`
    can resolve it. A path entry is not portable -- cloning or sharing the
    environment elsewhere does not carry that file along. A manifest entry
    points at a local manifest.toml (the same schema a published rtl
    package's own metadata.design.manifests.package already uses --
    vhdl_packages/vhdl_sources/verilog_sources/fabulous_library_sources/
    work_library_sources/include_dirs/defines/vhdl_standard) sitting
    directly in the project tree, not wrapped in an installed package --
    also not portable the way a package entry is, but preserves the
    manifest's own compile order and named-library split, which neither a
    bare path entry nor a directory scan can recover.
    """

    package: Optional[str] = None
    path: Optional[str] = None
    manifest: Optional[str] = None


@dataclass(frozen=True)
class EnvironmentProfile:
    name: str
    path: Path
    design: Optional[ComponentReference] = None
    design_sources: tuple[SourceEntry, ...] = ()
    technology: Optional[ComponentReference] = None
    flow: Optional[ComponentReference] = None
    project_root: Optional[str] = None
    workspace_root: Optional[str] = None
    clocks: tuple[ClockConstraint, ...] = ()
    constraint_files: tuple[str, ...] = ()
    constraint_lines: tuple[str, ...] = ()
    floorplan_def: Optional[str] = None
    power_nets: tuple[str, ...] = ()
    ground_nets: tuple[str, ...] = ()
    threads: Optional[int] = None
    backend_overrides: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    env_vars: Mapping[str, str] = field(default_factory=dict)


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


def _track_or_vth_selection(value: Any, field: str) -> tuple[Optional[str], tuple[str, ...]]:
    """technology.track/technology.vth accept either one name (the
    original, still the common shape) or a list of names (multi-vth
    mixing -- confirmed real usage: `vths: ${VTHS}` in a real setup.yaml
    template, with VTHS a bash array, consumed by synthesis.tcl's
    `foreach trk [get_flow_config tracks] { foreach vth [get_flow_config
    vths] { ... } }`, unioning every (track, vth) pair's library/lef
    files into one library_set). A single string is exactly the
    one-element-list case: primary is that name, the full selection is
    (name,)."""
    if value is None:
        return None, ()
    if isinstance(value, str):
        if not value:
            raise ValueError(f"{field} must be a nonempty string")
        return value, (value,)
    if isinstance(value, list) and value and all(isinstance(item, str) and item for item in value):
        return value[0], tuple(value)
    raise ValueError(f"{field} must be a nonempty string or a list of nonempty strings")


def _parse_source_entries(value: Any, field: str) -> tuple[SourceEntry, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a sequence")
    entries = []
    for index, item in enumerate(value):
        item_field = f"{field}[{index}]"
        mapping = _mapping(item, item_field)
        _known_fields(mapping, {"package", "path", "manifest"}, item_field)
        package = _optional_string(mapping.get("package"), f"{item_field}.package")
        path = _optional_string(mapping.get("path"), f"{item_field}.path")
        manifest_entry = _optional_string(mapping.get("manifest"), f"{item_field}.manifest")
        if sum(bool(value) for value in (package, path, manifest_entry)) != 1:
            raise ValueError(f"{item_field} must set exactly one of package, path, or manifest")
        if package and PackageId.parse(package).kind != "rtl":
            raise ValueError(f"{item_field}.package must identify an rtl package")
        entries.append(SourceEntry(package=package, path=path, manifest=manifest_entry))
    return tuple(entries)


def _component(
    data: Any, field: str, expected_kind: str, *, extra_satisfied: bool = False
) -> Optional[ComponentReference]:
    if data is None:
        return None
    mapping = _mapping(data, field)
    allowed = (
        {"package", "name"}
        | ({"top", "sources"} if field == "design" else set())
        | ({"track", "vth", "metal_stack", "process_node_nm"} if field == "technology" else set())
        | ({"backend"} if field == "flow" else set())
    )
    _known_fields(mapping, allowed, field)
    package = _optional_string(mapping.get("package"), f"{field}.package")
    if package and PackageId.parse(package).kind != expected_kind:
        raise ValueError(f"{field}.package must identify a {expected_kind} package")
    name = _optional_string(mapping.get("name"), f"{field}.name")
    top = _optional_string(mapping.get("top"), f"{field}.top") if field == "design" else None
    is_technology = field == "technology"
    track, tracks = _track_or_vth_selection(mapping.get("track"), f"{field}.track") if is_technology else (None, ())
    vth, vths = _track_or_vth_selection(mapping.get("vth"), f"{field}.vth") if is_technology else (None, ())
    metal_stack = (
        _optional_string(mapping.get("metal_stack"), f"{field}.metal_stack") if is_technology else None
    )
    process_node_nm = None
    if is_technology and mapping.get("process_node_nm") is not None:
        process_node_nm = mapping.get("process_node_nm")
        if (
            not isinstance(process_node_nm, int) or isinstance(process_node_nm, bool)
            or process_node_nm <= 0
        ):
            raise ValueError(f"{field}.process_node_nm must be a positive integer")
    backend = _optional_string(mapping.get("backend"), f"{field}.backend") if field == "flow" else None
    if not any((package, name, top, backend)) and not extra_satisfied:
        raise ValueError(f"{field} must define at least one value")
    return ComponentReference(
        package=package, name=name, top=top, track=track, vth=vth, tracks=tracks, vths=vths,
        metal_stack=metal_stack, process_node_nm=process_node_nm, backend=backend,
    )


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

    project = _mapping(data.get("project"), "project", optional=True)
    _known_fields(project, {"root"}, "project")
    project_root = _optional_string(project.get("root"), "project.root")

    workspace = _mapping(data.get("workspace"), "workspace", optional=True)
    _known_fields(workspace, {"root"}, "workspace")
    workspace_root = _optional_string(workspace.get("root"), "workspace.root")

    constraints = _mapping(data.get("constraints"), "constraints", optional=True)
    _known_fields(
        constraints,
        {"clocks", "floorplan_def", "files", "lines", "power_nets", "ground_nets"}, "constraints",
    )
    floorplan_def = _optional_string(constraints.get("floorplan_def"), "constraints.floorplan_def")
    raw_power_nets = constraints.get("power_nets", [])
    if not isinstance(raw_power_nets, list) or not all(
        isinstance(item, str) and item for item in raw_power_nets
    ):
        raise ValueError("constraints.power_nets must be a list of nonempty strings")
    raw_ground_nets = constraints.get("ground_nets", [])
    if not isinstance(raw_ground_nets, list) or not all(
        isinstance(item, str) and item for item in raw_ground_nets
    ):
        raise ValueError("constraints.ground_nets must be a list of nonempty strings")
    raw_constraint_files = constraints.get("files", [])
    if not isinstance(raw_constraint_files, list) or not all(
        isinstance(item, str) and item for item in raw_constraint_files
    ):
        raise ValueError("constraints.files must be a list of nonempty paths")
    raw_constraint_lines = constraints.get("lines", [])
    if not isinstance(raw_constraint_lines, list) or not all(
        isinstance(item, str) for item in raw_constraint_lines
    ):
        raise ValueError("constraints.lines must be a list of strings")
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

    env_vars = _mapping(data.get("env"), "env", optional=True)
    for env_key, env_value in env_vars.items():
        if not isinstance(env_key, str) or not _ENV_VAR_NAME.fullmatch(env_key):
            raise ValueError(f"env keys must be valid environment variable names, got {env_key!r}")
        if not isinstance(env_value, str):
            raise ValueError(f"env.{env_key} must be a string")

    design_mapping = _mapping(data.get("design"), "design", optional=True)
    design_sources = _parse_source_entries(design_mapping.get("sources"), "design.sources")

    return EnvironmentProfile(
        name=name,
        path=path,
        design=_component(
            data.get("design"), "design", "rtl", extra_satisfied=bool(design_sources)
        ),
        design_sources=design_sources,
        technology=_component(data.get("technology"), "technology", "pdk"),
        flow=_component(data.get("flow"), "flow", "flow"),
        project_root=project_root,
        workspace_root=workspace_root,
        clocks=tuple(clocks),
        constraint_files=tuple(raw_constraint_files),
        constraint_lines=tuple(raw_constraint_lines),
        floorplan_def=floorplan_def,
        power_nets=tuple(raw_power_nets),
        ground_nets=tuple(raw_ground_nets),
        threads=threads,
        backend_overrides=backend,
        env_vars=env_vars,
    )


def normalize_environment(source: Path, destination: Path, *, name: str) -> EnvironmentProfile:
    """Validate an imported profile and persist stable manifest-relative paths."""
    profile = load_environment(source, expected_name=name)
    data = yaml.safe_load(profile.path.read_text(encoding="utf-8"))
    data["name"] = name
    if profile.project_root:
        data.setdefault("project", {})["root"] = str(
            resolve_stored_path(profile.project_root, profile.path.parent)
        )
    if profile.workspace_root:
        data.setdefault("workspace", {})["root"] = str(
            resolve_stored_path(profile.workspace_root, profile.path.parent)
        )
    constraint_files = data.get("constraints", {}).get("files") \
        if isinstance(data.get("constraints"), dict) else None
    if isinstance(constraint_files, list):
        data["constraints"]["files"] = [
            str(resolve_stored_path(item, profile.path.parent)) if isinstance(item, str) else item
            for item in constraint_files
        ]
    design_sources = data.get("design", {}).get("sources") if isinstance(data.get("design"), dict) else None
    if isinstance(design_sources, list):
        for entry in design_sources:
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                entry["path"] = str(resolve_stored_path(entry["path"], profile.path.parent))
    for overrides in data.get("backend", {}).values():
        if isinstance(overrides, dict) and isinstance(overrides.get("design_config"), str):
            overrides["design_config"] = str(
                resolve_stored_path(overrides["design_config"], profile.path.parent)
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


def _paths_under(root: Path, value: Any, field: str) -> tuple[Path, ...]:
    """Resolve a list of package-relative paths, rejecting escapes or misses."""
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"technology.{field} must be a list of relative paths")
    resolved = []
    for item in value:
        path = (root / item).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"technology.{field} escapes installed package: {item}")
        if not path.is_file():
            raise ValueError(f"technology.{field} file does not exist: {path}")
        resolved.append(path)
    return tuple(resolved)


def _parse_timing_corners(
    root: Path, timing: Mapping[str, Any], *, field: str,
) -> tuple[tuple[ResolvedTimingCorner, ...], tuple[Path, ...]]:
    """Parse one timing.corners mapping (flat, or nested under one track/vth).

    Returns (corners, the union of every corner's libraries) -- the union is
    only for existence/checksum bookkeeping, not a value a backend should
    treat as one combined library set (that would reintroduce the exact
    cross-corner cell-name collision this whole mechanism exists to avoid).
    """
    raw_corners = timing.get("corners")
    if raw_corners is None:
        return (), ()
    if timing.get("libraries"):
        raise ValueError(
            f"{field}.corners and {field}.libraries are mutually exclusive -- declare "
            "either one named corner's libraries there, or several named corners under "
            "corners, not both"
        )
    if not isinstance(raw_corners, dict) or not raw_corners:
        raise ValueError(f"{field}.corners must be a nonempty mapping")
    corners = []
    qrc_files = []
    for corner_name, corner_data in raw_corners.items():
        if not isinstance(corner_name, str) or not corner_name:
            raise ValueError(f"{field}.corners keys must be nonempty corner names")
        if not isinstance(corner_data, dict):
            raise ValueError(f"{field}.corners.{corner_name} must be a mapping")
        corner_libraries = _paths_under(
            root, corner_data.get("libraries", []), f"{field}.corners.{corner_name}.libraries"
        )
        if not corner_libraries:
            raise ValueError(f"{field}.corners.{corner_name}.libraries must be nonempty")
        qrc_value = corner_data.get("qrc_tech_file")
        qrc_path: Optional[Path] = None
        if qrc_value is not None:
            if not isinstance(qrc_value, str) or not qrc_value:
                raise ValueError(f"{field}.corners.{corner_name}.qrc_tech_file must be a nonempty string")
            qrc_path = _paths_under(root, [qrc_value], f"{field}.corners.{corner_name}.qrc_tech_file")[0]
            qrc_files.append(qrc_path)
        library_format = corner_data.get("format", "liberty")
        if not isinstance(library_format, str) or not library_format:
            raise ValueError(f"{field}.corners.{corner_name}.format must be a nonempty string")
        corners.append(ResolvedTimingCorner(
            name=corner_name, libraries=corner_libraries, qrc_tech_file=qrc_path,
            format=library_format,
        ))
    return tuple(corners), tuple(qrc_files)


# A flat (no tracks) technology's timing/physical keys, kept exactly as before.
_FLAT_TECHNOLOGY_FIELDS = {
    "name", "timing", "physical", "synthesis", "setup_yaml_fragment",
    "opconds", "delay_corners", "analysis_views",
}
# A multi-track technology's own top-level keys.
_TRACKED_TECHNOLOGY_FIELDS = {
    "name", "tracks", "generic", "synthesis", "setup_yaml_fragment",
    "opconds", "delay_corners", "analysis_views",
}


# gds is deliberately not here: a cell's own GDS geometry lives on the
# metal layers shared by every stack option, so (unlike lef/cell_lef and
# qrc_techfiles, all genuinely tied to the chosen stack) it doesn't vary
# by metal_stack -- see _resolve_gds_field for the one remaining place
# a legacy per-stack gds mapping is still tolerated, for packages that
# declared it that way before this stopped being a real axis for gds.
_STACK_KEYED_FIELDS = ("lef", "cell_lef", "qrc_techfiles")


def _vth_metal_stacks(data: Mapping[str, Any], field: str) -> Optional[tuple[str, ...]]:
    """If this vth declares lef/qrc_techfiles per named metal stack (a
    mapping) rather than one flat list, return every stack name any of
    them declares. lef and qrc_techfiles are allowed to disagree about
    which stacks they each have files for -- real PDK data routinely
    does (a qrc captable existing for a stack with no LEF declared yet,
    say) -- the same "a field with nothing for this stack just resolves
    empty, not an error" tolerance _catalog_stack_files already extends
    to the full-package catalog; _technology_variant's own stack_paths
    and _resolve_qrc_techfiles apply that same tolerance per field once
    a stack is actually selected. Returns None when none of them use the
    mapping form at all (a single-stack vth, unchanged from before this
    existed).
    """
    stack_names: set = set()
    seen_mapping = False
    for key in _STACK_KEYED_FIELDS:
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, dict):
            names = tuple(sorted(value))
            if not names:
                raise ValueError(f"technology.{field}.{key} must be a nonempty mapping")
            stack_names.update(names)
            seen_mapping = True
        elif not isinstance(value, list):
            raise ValueError(f"technology.{field}.{key} must be a list or a mapping of metal stacks")
    return tuple(sorted(stack_names)) if seen_mapping else None


def _select_metal_stack(
    stack_names: tuple[str, ...], data: Mapping[str, Any],
    reference: Optional[ComponentReference], field: str,
) -> str:
    requested = reference.metal_stack if reference else None
    default = data.get("default_metal_stack")
    if default is not None and not isinstance(default, str):
        raise ValueError(f"technology.{field}.default_metal_stack must be a string")
    stack = requested or default
    if stack is None:
        if len(stack_names) == 1:
            return stack_names[0]
        raise ValueError(
            f"technology.metal_stack is required for {field} (several declared, no "
            f"default_metal_stack set): " + ", ".join(stack_names)
        )
    if stack not in stack_names:
        raise ValueError(
            f"technology.metal_stack {stack!r} is not declared for {field}; available: "
            + ", ".join(stack_names)
        )
    return stack


def _catalog_stack_files(
    root: Path, vth_data: Mapping[str, Any], key: str, metal_stack: Optional[str],
) -> Optional[tuple[Path, ...]]:
    """One track/vth's file list for a stack-keyed field (lef or gds),
    building the technology's single resolved metal_stack -- or this
    vth's own default, or its one declared stack if there's only one.
    Returns None (not an error) when this vth doesn't declare the
    relevant stack at all, or declares none unambiguously -- a catalog
    entry simply isn't produced for it, the same "normal mid-edit state"
    tolerance the rest of this module already extends to a package still
    being populated.
    """
    value = vth_data.get(key)
    if value is None:
        return None
    try:
        if isinstance(value, list):
            return _paths_under(root, value, f"catalog.{key}")
        if isinstance(value, dict):
            stack = metal_stack or vth_data.get("default_metal_stack")
            if stack is None and len(value) == 1:
                stack = next(iter(value))
            if stack is None or stack not in value:
                return None
            return _paths_under(root, value[stack], f"catalog.{key}.{stack}")
    except ValueError:
        return None
    return None


_CHECKSUM_CACHE_FILENAME = "technology-file-checksums.json"


def _checksum_cache_path() -> Path:
    return cache_dir() / _CHECKSUM_CACHE_FILENAME


def _load_checksum_cache() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(_checksum_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_checksum_cache(cache: Mapping[str, Mapping[str, Any]]) -> None:
    path = _checksum_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(cache), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass  # The cache is a pure speed optimization; losing it is never fatal.


def _cached_checksums(paths: tuple[Path, ...]) -> dict[str, str]:
    """sha256 every resolved technology file, reusing a prior result keyed
    on (mtime, size) instead of re-reading full file content when nothing
    has changed. These are often large PDK lef/gds/timing-library files,
    so re-hashing all of them on every `wolf run` -- even when the
    environment config itself hasn't changed -- is the real cost behind a
    slow resolve; a stat-based fingerprint lets an unchanged file skip the
    read entirely while still detecting a real edit."""
    cache = _load_checksum_cache()
    dirty = False
    checksums: dict[str, str] = {}
    for path in paths:
        key = str(path)
        info = path.stat()
        fingerprint = {"mtime_ns": info.st_mtime_ns, "size": info.st_size}
        entry = cache.get(key)
        if entry and entry.get("mtime_ns") == fingerprint["mtime_ns"] and entry.get("size") == fingerprint["size"]:
            checksums[key] = entry["sha256"]
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksums[key] = digest
        cache[key] = {**fingerprint, "sha256": digest}
        dirty = True
    if dirty:
        _save_checksum_cache(cache)
    return checksums


def _build_catalog(
    root: Path, tracks: Mapping[str, Any], metal_stack: Optional[str],
) -> tuple[tuple[CatalogLibrarySet, ...], tuple[CatalogFileList, ...], tuple[CatalogFileList, ...]]:
    """Walk every declared track/vth (not just the one variant an
    environment selected) to build the full get_flow_config-style catalog
    a real Flowtool-driven flow indexes itself at Tcl run time:
    library_sets keyed by corner (confirmed against a real legacy
    synthesis.tcl: `get_flow_config library_sets $name library_files $trk
    $vth`), lef/gds keyed by track/vth only -- no corner level (lef/gds
    aren't PVT-corner-dependent) and no metal-stack level either (also
    confirmed against real Tcl: `get_flow_config init_physical_files
    lef_files $trk $vth`, `get_flow_config std_cell_GDS_files $trk $vth`
    -- neither indexes by stack, so WOLF resolves metal_stack to one
    value across the whole catalog instead of exposing every stack).

    A track/vth with a missing file, or without the resolved metal_stack,
    is simply absent from the catalog rather than failing the whole
    resolution -- the same tolerance _technology_variant already extends
    to the one selected variant while a package is still being populated.
    """
    library_sets: list[CatalogLibrarySet] = []
    lef_files: list[CatalogFileList] = []
    gds_files: list[CatalogFileList] = []
    for track_name, track_data in tracks.items():
        if not isinstance(track_data, dict):
            continue
        vths = track_data.get("vths")
        if not isinstance(vths, dict):
            continue
        for vth_name, vth_data in vths.items():
            if not isinstance(vth_data, dict):
                continue
            corners = vth_data.get("timing", {})
            corners = corners.get("corners", {}) if isinstance(corners, dict) else {}
            if isinstance(corners, dict):
                for corner_name, corner_data in corners.items():
                    if not isinstance(corner_data, dict):
                        continue
                    libraries = corner_data.get("libraries", [])
                    if not isinstance(libraries, list):
                        continue
                    try:
                        paths = _paths_under(
                            root, libraries,
                            f"catalog.library_sets.{corner_name}.{track_name}.{vth_name}",
                        )
                    except ValueError:
                        continue
                    library_sets.append(CatalogLibrarySet(
                        corner=corner_name, track=track_name, vth=vth_name, libraries=paths,
                    ))
            lef = _catalog_stack_files(root, vth_data, "lef", metal_stack)
            if lef is not None:
                lef_files.append(CatalogFileList(track=track_name, vth=vth_name, files=lef))
            gds = _catalog_stack_files(root, vth_data, "gds", metal_stack)
            if gds is not None:
                gds_files.append(CatalogFileList(track=track_name, vth=vth_name, files=gds))
    return tuple(library_sets), tuple(lef_files), tuple(gds_files)


def _resolve_gds_field(
    root: Path, data: Mapping[str, Any], reference: Optional[ComponentReference], field: str,
    metal_stack: Optional[str],
) -> tuple[Path, ...]:
    """gds is always a flat list going forward -- a cell's own GDS
    geometry lives on metal layers shared by every stack option, unlike
    lef/qrc_techfiles. A legacy per-stack mapping (from before this
    stopped being a real axis for gds) still resolves rather than
    erroring: `metal_stack` (the one lef/qrc_techfiles already resolved
    to, if any) is tried first, falling back to this field's own
    default_metal_stack or its one declared stack if there's only one --
    the same tolerance the rest of this module extends to a package
    that's mid-migration, not fully consistent yet.
    """
    value = data.get("gds", [])
    if isinstance(value, list):
        return _paths_under(root, value, f"{field}.gds")
    if not isinstance(value, dict):
        raise ValueError(f"technology.{field}.gds must be a list of paths")
    stack = metal_stack or (reference.metal_stack if reference else None) or data.get("default_metal_stack")
    if stack is None and len(value) == 1:
        stack = next(iter(value))
    if stack is None or stack not in value:
        raise ValueError(
            f"technology.{field}.gds is declared per metal stack (a legacy shape gds no longer "
            "needs), but no stack could be selected for it -- set technology.metal_stack, add "
            f"{field}.default_metal_stack, or flatten gds to a single list"
        )
    return _paths_under(root, value[stack], f"{field}.gds.{stack}")


def _resolve_qrc_techfiles(
    root: Path, data: Mapping[str, Any], field: str, metal_stack: Optional[str],
) -> tuple[tuple[ResolvedQrcCorner, ...], tuple[Path, ...]]:
    """qrc_techfiles for the selected metal_stack, broken down by named
    rc-corner (see ResolvedQrcCorner) -- plus the flat union of every
    rc-corner's own files, for simple existence/checksum tracking (the
    same relationship timing_libraries already has to timing_corners).

    Real captables are named per metal stack AND per rc-corner (confirmed
    filenames like `..._Vp9m+alrdl_top2_rcworst.captable`), so unlike
    gds, qrc_techfiles keeps its full per-stack nesting, just one level
    deeper. Either level still being a flat list (no stack axis at all,
    or one stack's own entry not yet broken out by rc-corner) is
    tolerated as "no named rc-corners declared yet" -- the same
    leave-it-mid-edit tolerance the rest of this module already extends
    to an axis nothing has been declared for yet.
    """
    value = data.get("qrc_techfiles")
    if value is None:
        return (), ()
    if isinstance(value, list):
        return (), _paths_under(root, value, f"{field}.qrc_techfiles")
    if not isinstance(value, dict):
        raise ValueError(f"technology.{field}.qrc_techfiles must be a list or a mapping")
    if metal_stack is None or metal_stack not in value:
        return (), ()
    stack_value = value[metal_stack]
    if isinstance(stack_value, list):
        return (), _paths_under(root, stack_value, f"{field}.qrc_techfiles.{metal_stack}")
    if not isinstance(stack_value, dict):
        raise ValueError(
            f"technology.{field}.qrc_techfiles.{metal_stack} must be a list of paths or a "
            "mapping of rc-corner name to files"
        )
    qrc_corners = tuple(
        ResolvedQrcCorner(
            name=corner_name,
            qrc_techfiles=_paths_under(
                root, files_value, f"{field}.qrc_techfiles.{metal_stack}.{corner_name}",
            ),
        )
        for corner_name, files_value in stack_value.items()
    )
    flat = tuple(dict.fromkeys(path for corner in qrc_corners for path in corner.qrc_techfiles))
    return qrc_corners, flat


def _technology_variant(
    root: Path, track: str, vth: str, data: Any, reference: Optional[ComponentReference],
) -> tuple[
    tuple[ResolvedTimingCorner, ...], tuple[Path, ...], tuple[Path, ...], tuple[Path, ...],
    tuple[Path, ...], tuple[Path, ...], tuple[Path, ...], tuple[Path, ...],
    tuple[ResolvedQrcCorner, ...], Optional[str],
]:
    """Parse one tracks.<track>.vths.<vth> entry: corners, lef, cell_lef,
    gds, verilog, spice, qrc.

    lef/cell_lef/qrc_techfiles are physically tied to a metal stack
    (routing layer count plus top-metal option, e.g. 9lmT2) -- a real
    design axis, not a detail to just pick one file for and forget: the
    same track/vth can legitimately be built against several stacks
    (cloning an environment and only changing technology.metal_stack is
    meant to just work). See _vth_metal_stacks/_select_metal_stack for
    how the stack actually gets picked. gds does not share that axis --
    a cell's own GDS geometry lives on metal layers shared by every
    stack option -- so it's always a flat list (see _resolve_gds_field
    for the one remaining tolerance: a legacy per-stack mapping, from
    before this stopped being a real axis for gds, still resolves
    rather than erroring). qrc_techfiles goes one level deeper than lef
    instead: per metal stack *and* per named rc-corner (see
    _resolve_qrc_techfiles) -- a real, independent axis from the PVT
    timing corners above (BEOL process variation, not FEOL transistor
    skew).

    cell_lef is a *separate* declared key, not implied by lef -- some
    institutions genuinely ship a technology LEF (routing-layer/site
    definitions) and a standard-cell LEF (cell abstracts) as two
    distinct files. A package that ships one real merged LEF covering
    both (TSMC's own standard-cell LEF deliverable, confirmed real)
    simply never declares cell_lef at all; the caller then reuses lef
    for both roles rather than requiring every package to redundantly
    repeat the same path under two different keys.
    """
    field = f"tracks.{track}.vths.{vth}"
    if not isinstance(data, dict):
        raise ValueError(f"technology.{field} must be a mapping")
    timing = data.get("timing", {})
    timing = timing if isinstance(timing, dict) else {}
    corners, corner_qrc_files = _parse_timing_corners(root, timing, field=f"{field}.timing")
    if not corners:
        raise ValueError(f"technology.{field}.timing.corners must declare at least one corner")

    stack_names = _vth_metal_stacks(data, field)
    if stack_names is None:
        if reference is not None and reference.metal_stack:
            raise ValueError(
                f"technology.metal_stack was given but {field} declares no named metal stacks"
            )
        metal_stack = None
        lef = _paths_under(root, data.get("lef", []), f"{field}.lef")
        cell_lef = _paths_under(root, data.get("cell_lef", []), f"{field}.cell_lef")
    else:
        metal_stack = _select_metal_stack(stack_names, data, reference, field)

        def stack_paths(key: str) -> tuple[Path, ...]:
            value = data.get(key)
            if value is None:
                return ()
            if isinstance(value, list):
                # Not stack-keyed at all for this field (lef/cell_lef/
                # qrc_techfiles are allowed to disagree about which
                # ones use the mapping form -- see _vth_metal_stacks).
                return _paths_under(root, value, f"{field}.{key}")
            if metal_stack not in value:
                return ()
            return _paths_under(root, value[metal_stack], f"{field}.{key}.{metal_stack}")
        lef = stack_paths("lef")
        cell_lef = stack_paths("cell_lef")

    qrc_corners, qrc_techfiles = _resolve_qrc_techfiles(root, data, field, metal_stack)
    gds = _resolve_gds_field(root, data, reference, field, metal_stack)
    verilog_models = _paths_under(root, data.get("verilog_models", []), f"{field}.verilog_models")
    spice_models = _paths_under(root, data.get("spice_models", []), f"{field}.spice_models")
    return (
        corners, corner_qrc_files, lef, cell_lef, gds, verilog_models, spice_models,
        qrc_techfiles, qrc_corners, metal_stack,
    )


def _select_track_vth(
    tracks: Mapping[str, Any], reference: Optional[ComponentReference],
) -> tuple[str, str, Any]:
    """Pick the (track, vth) variant a run actually uses.

    Required once more than one combination exists; a single declared track
    with a single declared vth is selected automatically so a simple
    one-track package needs no selection at all.
    """
    if not isinstance(tracks, dict) or not tracks:
        raise ValueError("technology.tracks must be a nonempty mapping")
    available = []
    for track_name, track_data in tracks.items():
        if not isinstance(track_data, dict):
            raise ValueError(f"technology.tracks.{track_name} must be a mapping")
        vths = track_data.get("vths")
        if not isinstance(vths, dict) or not vths:
            raise ValueError(f"technology.tracks.{track_name}.vths must be a nonempty mapping")
        for vth_name in vths:
            available.append((track_name, vth_name))
    requested_track = reference.track if reference else None
    requested_vth = reference.vth if reference else None
    if requested_track is None and requested_vth is None:
        if len(available) == 1:
            track_name, vth_name = available[0]
            return track_name, vth_name, tracks[track_name]["vths"][vth_name]
        raise ValueError(
            "technology.track and technology.vth are required when the package declares "
            "more than one track/vth combination; available: "
            + ", ".join(f"{track}/{vth}" for track, vth in available)
        )
    if requested_track is None or requested_vth is None:
        raise ValueError("technology.track and technology.vth must both be set, or neither")
    track_data = tracks.get(requested_track)
    if not isinstance(track_data, dict) or requested_vth not in track_data.get("vths", {}):
        raise ValueError(
            f"technology {requested_track}/{requested_vth} is not declared; available: "
            + ", ".join(f"{track}/{vth}" for track, vth in available)
        )
    return requested_track, requested_vth, track_data["vths"][requested_vth]


def _collect_timing_corner_names(tracks: Mapping[str, Any]) -> frozenset:
    """Every PVT timing-corner name declared anywhere across a tracked
    package's tracks/vths -- corner names are universal vocabulary (the
    same name means the same PVT skew everywhere it's used), which is
    what lets a delay_corner reference one by name alone, not by
    track/vth."""
    names: set = set()
    for track_data in tracks.values():
        if not isinstance(track_data, dict):
            continue
        for vth_data in track_data.get("vths", {}).values():
            if not isinstance(vth_data, dict):
                continue
            corners = vth_data.get("timing", {})
            corners = corners.get("corners", {}) if isinstance(corners, dict) else {}
            if isinstance(corners, dict):
                names.update(corners)
    return frozenset(names)


def _collect_rc_corner_names(tracks: Mapping[str, Any]) -> frozenset:
    """Every named RC-extraction corner declared anywhere across a
    tracked package's tracks/vths/metal-stacks -- same universal-
    vocabulary assumption as _collect_timing_corner_names."""
    names: set = set()
    for track_data in tracks.values():
        if not isinstance(track_data, dict):
            continue
        for vth_data in track_data.get("vths", {}).values():
            if not isinstance(vth_data, dict):
                continue
            qrc = vth_data.get("qrc_techfiles")
            if isinstance(qrc, dict):
                for stack_corners in qrc.values():
                    if isinstance(stack_corners, dict):
                        names.update(stack_corners)
    return frozenset(names)


def _build_signoff_catalog(
    metadata: Mapping[str, Any], timing_corner_names: frozenset, rc_corner_names: frozenset,
) -> tuple[tuple[ResolvedOpcond, ...], tuple[ResolvedDelayCorner, ...], tuple[ResolvedAnalysisView, ...]]:
    """Resolve the static opconds -> delay_corners -> analysis_views
    catalog (see wolf.context's own docstrings for what each represents),
    each referencing the declared ones before it by name only -- mirrors
    the real MMMC object hierarchy (library_set/timing_condition ->
    delay_corner -> analysis_view) as a fully-declared, run-independent
    catalog. The dynamic part -- which analysis_views actually drive a
    given run -- is an environment-level concern, not resolved here.

    Validated eagerly: a delay_corner referencing a timing_corner/
    rc_corner name that isn't actually declared anywhere in this
    package, or an analysis_view referencing an undeclared delay_corner,
    is a real authoring mistake (the same severity wolf_pdk_menu's own
    "empty list, must create one first" guard exists to prevent while
    editing), not something to silently resolve around.
    """
    opconds_data = metadata.get("opconds", {})
    if not isinstance(opconds_data, dict):
        raise ValueError("technology.opconds must be a mapping")
    opconds: list[ResolvedOpcond] = []
    for name, data in opconds_data.items():
        if not isinstance(data, dict):
            raise ValueError(f"technology.opconds.{name} must be a mapping")
        opconds.append(ResolvedOpcond(
            name=name, process=data.get("process"), voltage=data.get("voltage"),
            temperature=data.get("temperature"),
        ))

    delay_corners_data = metadata.get("delay_corners", {})
    if not isinstance(delay_corners_data, dict):
        raise ValueError("technology.delay_corners must be a mapping")
    delay_corners: list[ResolvedDelayCorner] = []
    for name, data in delay_corners_data.items():
        if not isinstance(data, dict):
            raise ValueError(f"technology.delay_corners.{name} must be a mapping")
        timing_corner = data.get("timing_corner")
        rc_corner = data.get("rc_corner")
        if not timing_corner or timing_corner not in timing_corner_names:
            raise ValueError(
                f"technology.delay_corners.{name}.timing_corner {timing_corner!r} is not a "
                f"declared timing corner (available: {sorted(timing_corner_names)})"
            )
        if not rc_corner or rc_corner not in rc_corner_names:
            raise ValueError(
                f"technology.delay_corners.{name}.rc_corner {rc_corner!r} is not a declared "
                f"RC-extraction corner (available: {sorted(rc_corner_names)})"
            )
        delay_corners.append(ResolvedDelayCorner(name=name, timing_corner=timing_corner, rc_corner=rc_corner))
    delay_corner_names = frozenset(dc.name for dc in delay_corners)

    analysis_views_data = metadata.get("analysis_views", {})
    if not isinstance(analysis_views_data, dict):
        raise ValueError("technology.analysis_views must be a mapping")
    analysis_views: list[ResolvedAnalysisView] = []
    for name, data in analysis_views_data.items():
        if not isinstance(data, dict):
            raise ValueError(f"technology.analysis_views.{name} must be a mapping")
        delay_corner = data.get("delay_corner")
        if not delay_corner or delay_corner not in delay_corner_names:
            raise ValueError(
                f"technology.analysis_views.{name}.delay_corner {delay_corner!r} is not a "
                f"declared delay corner (available: {sorted(delay_corner_names)})"
            )
        analysis_views.append(ResolvedAnalysisView(
            name=name, delay_corner=delay_corner,
            is_setup=bool(data.get("is_setup", False)), is_hold=bool(data.get("is_hold", False)),
            is_dynamic=bool(data.get("is_dynamic", False)), is_leakage=bool(data.get("is_leakage", False)),
        ))
    return tuple(opconds), tuple(delay_corners), tuple(analysis_views)


def resolve_technology_reference(
    package: Optional[str], track: Optional[str] = None, vths: tuple = (),
    metal_stack: Optional[str] = None,
) -> Optional[ResolvedTechnology]:
    """Resolve one technology package's real LEF/library views from just
    its selection (no design/flow/workspace needed) -- for callers that
    want a technology's own resolved files (e.g. `wolf env menu`'s cell
    browser) without requiring a complete, installable environment.
    Returns None whenever the package isn't selected or isn't actually
    installed yet; callers should treat that as "not resolvable right
    now" (fall back to free-text entry), not an error.
    """
    if not package:
        return None
    try:
        manifest = PackageRegistry().get(package)
    except (ValueError, KeyError):
        return None
    installed = PackageStore().read(manifest)
    if installed is None:
        return None
    reference = ComponentReference(
        package=package, track=track, vth=vths[0] if vths else None,
        vths=tuple(vths), metal_stack=metal_stack,
    )
    return _technology_inputs(manifest, installed, reference)


def _technology_inputs(
    manifest: Any, installed: Any, reference: Optional[ComponentReference] = None,
) -> Optional[ResolvedTechnology]:
    """Resolve portable technology views declared by an installed PDK package."""
    metadata = manifest.metadata.get("technology", {})
    if not isinstance(metadata, dict) or not installed:
        return None
    root = installed.content_path.resolve()
    name = metadata.get("name")
    if not isinstance(name, str) or not name:
        return None
    synthesis = metadata.get("synthesis", {})
    synthesis = synthesis if isinstance(synthesis, dict) else {}

    track: Optional[str] = None
    vth: Optional[str] = None
    process_node_nm = reference.process_node_nm if reference else None
    generic: Mapping[str, Any] = {}
    verilog_models: tuple[Path, ...] = ()
    spice_models: tuple[Path, ...] = ()
    qrc_techfiles: tuple[Path, ...] = ()
    qrc_corners: tuple[ResolvedQrcCorner, ...] = ()

    if "tracks" in metadata:
        unknown = set(metadata) - _TRACKED_TECHNOLOGY_FIELDS
        if unknown:
            raise ValueError(f"unsupported technology field alongside tracks: {sorted(unknown)[0]}")
        generic = metadata.get("generic", {})
        if not isinstance(generic, dict):
            raise ValueError("technology.generic must be a mapping")
        track, vth, variant = _select_track_vth(metadata["tracks"], reference)
        selected_tracks = reference.tracks if (reference and reference.tracks) else (track,)
        selected_vths = reference.vths if (reference and reference.vths) else (vth,)
        timing_corners, corner_qrc_files, technology_lefs, declared_cell_lefs, gds_files, \
            verilog_models, spice_models, qrc_techfiles, qrc_corners, metal_stack = \
            _technology_variant(root, track, vth, variant, reference)
        # A package that ships one real merged LEF (technology geometry
        # and cell abstracts together -- TSMC's own standard-cell LEF
        # deliverable, confirmed real) never declares a separate
        # cell_lef key at all; reuse the same technology LEF files for
        # both roles rather than requiring every package to repeat the
        # same path under two different keys. qrc_techfiles is already
        # the flattened cross-corner captable list _resolve_qrc_techfiles
        # itself produces, exactly what rc_files means for a flat
        # (non-tracked) package -- the per-corner-named detail stays
        # available separately via qrc_corners for anything that needs
        # a specific corner's own captable, not just "is RC collateral
        # present at all".
        cell_lefs: tuple[Path, ...] = declared_cell_lefs or technology_lefs
        rc_files: tuple[Path, ...] = qrc_techfiles
        libraries = tuple(dict.fromkeys(
            library for corner in timing_corners for library in corner.libraries
        ))
        corner = f"{track}/{vth}"
        all_files = (
            *libraries, *technology_lefs, *declared_cell_lefs, *gds_files, *verilog_models,
            *spice_models, *qrc_techfiles, *corner_qrc_files,
        )
        catalog_library_sets, catalog_lef_files, catalog_gds_files = _build_catalog(
            root, metadata["tracks"], metal_stack,
        )
        catalog_opconds, catalog_delay_corners, catalog_analysis_views = _build_signoff_catalog(
            metadata, _collect_timing_corner_names(metadata["tracks"]),
            _collect_rc_corner_names(metadata["tracks"]),
        )
    else:
        catalog_library_sets, catalog_lef_files, catalog_gds_files = (), (), ()
        selected_tracks, selected_vths = (), ()
        metal_stack = None
        if reference is not None and (reference.track or reference.vth or reference.metal_stack):
            raise ValueError(
                "technology.track/technology.vth/technology.metal_stack require the package "
                "to declare technology.tracks; this package declares a flat timing/physical section"
            )
        unknown = set(metadata) - _FLAT_TECHNOLOGY_FIELDS
        if unknown:
            raise ValueError(f"unsupported technology field: {sorted(unknown)[0]}")
        timing = metadata.get("timing", {})
        timing = timing if isinstance(timing, dict) else {}
        physical = metadata.get("physical", {})
        physical = physical if isinstance(physical, dict) else {}
        timing_corners, corner_qrc_files = _parse_timing_corners(root, timing, field="timing")
        if timing_corners:
            libraries = tuple(dict.fromkeys(
                library for corner in timing_corners for library in corner.libraries
            ))
        else:
            libraries = _paths_under(root, timing.get("libraries", []), "timing.libraries")
        technology_lefs = _paths_under(root, physical.get("technology_lefs", []), "physical.technology_lefs")
        cell_lefs = _paths_under(root, physical.get("cell_lefs", []), "physical.cell_lefs")
        rc_files = _paths_under(root, physical.get("rc", []), "physical.rc")
        gds_files = _paths_under(root, physical.get("gds", []), "physical.gds")
        corner = timing.get("corner") or ("multi-corner" if timing_corners else "typical")
        if not isinstance(corner, str) or not corner:
            raise ValueError("technology.timing.corner must be a nonempty string")
        all_files = (*libraries, *technology_lefs, *cell_lefs, *rc_files, *gds_files, *corner_qrc_files)
        catalog_opconds, catalog_delay_corners, catalog_analysis_views = _build_signoff_catalog(
            metadata, frozenset(c.name for c in timing_corners), frozenset(),
        )

    setup_yaml_fragment_value = metadata.get("setup_yaml_fragment")
    setup_yaml_fragment: Optional[Path] = None
    if setup_yaml_fragment_value is not None:
        if not isinstance(setup_yaml_fragment_value, str) or not setup_yaml_fragment_value:
            raise ValueError("technology.setup_yaml_fragment must be a nonempty string")
        setup_yaml_fragment = _paths_under(root, [setup_yaml_fragment_value], "setup_yaml_fragment")[0]
        all_files = (*all_files, setup_yaml_fragment)

    checksums = _cached_checksums(all_files)
    dont_use = synthesis.get("dont_use", [])
    if not isinstance(dont_use, list) or not all(isinstance(item, str) and item for item in dont_use):
        raise ValueError("technology.synthesis.dont_use must be a list of nonempty cell name patterns")
    return ResolvedTechnology(
        package=str(manifest.identifier), revision=manifest.revision, name=name,
        root=root, track=track, vth=vth,
        selected_tracks=selected_tracks, selected_vths=selected_vths, metal_stack=metal_stack,
        timing_corner=corner, timing_libraries=libraries,
        timing_corners=timing_corners,
        technology_lefs=technology_lefs, cell_lefs=cell_lefs, rc_files=rc_files,
        gds_files=gds_files, verilog_models=verilog_models, spice_models=spice_models,
        qrc_techfiles=qrc_techfiles, qrc_corners=qrc_corners, generic=generic,
        checksums=checksums, dont_use_cells=tuple(dont_use),
        setup_yaml_fragment=setup_yaml_fragment,
        catalog_library_sets=catalog_library_sets, catalog_lef_files=catalog_lef_files,
        catalog_gds_files=catalog_gds_files,
        catalog_opconds=catalog_opconds, catalog_delay_corners=catalog_delay_corners,
        catalog_analysis_views=catalog_analysis_views,
        process_node_nm=process_node_nm,
    )


def _manifest_lines(path: Path) -> list[str]:
    """Read an ordered package file list, ignoring comments and blanks."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"design source manifest .flist does not exist or cannot be read: {path}") from error
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _checksum_inventory(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 64:
            result[parts[1].removeprefix("./")] = parts[0]
    return result


def _design_inputs(manifest: Any, installed: Any) -> tuple[
    tuple[ResolvedSource, ...], tuple[Path, ...], tuple[str, ...], Optional[str], dict[str, str]
]:
    """Resolve an installed rtl package's generic ordered source metadata,
    including a published TOML bundle (see _resolve_manifest_bundle)."""
    metadata = manifest.metadata.get("design", {})
    if not isinstance(metadata, dict):
        metadata = {}
    root = installed.content_path.resolve()
    return _resolve_manifest_bundle(metadata, root)


def _local_manifest_sources(manifest_path: Path) -> tuple[
    tuple[ResolvedSource, ...], tuple[Path, ...], tuple[str, ...], Optional[str], dict[str, str]
]:
    """Resolve a local design.sources[].manifest entry -- a manifest.toml
    sitting directly in the project tree (e.g.
    inputs/hdl/<design>/manifest.toml), not wrapped in an installed rtl
    package. Reuses _resolve_manifest_bundle exactly as an installed
    package's own metadata.design.manifests.package would, by
    constructing the same {"manifests": {"package": ...}} shape, rooted
    at the manifest file's own directory -- same schema, same
    ordering/library-split rules, no separate checksum inventory (a local
    manifest declares none of its own)."""
    if not manifest_path.is_file():
        raise ValueError(f"design.sources manifest does not exist: {manifest_path}")
    root = manifest_path.parent.resolve()
    metadata = {"manifests": {"package": manifest_path.name}}
    return _resolve_manifest_bundle(metadata, root)


@dataclass(frozen=True)
class ManifestInspection:
    """A manifest.toml's own declared identity plus a source count --
    what `wolf env menu` needs to validate a manifest the moment it's
    added (not only once `wolf run` eventually resolves it) and to
    suggest design.name/design.top from the manifest's own fields,
    rather than regex-scanning HDL text the way a loose path entry
    needs to."""

    name: Optional[str]
    top: Optional[str]
    vhdl_standard: Optional[str]
    source_count: int


def inspect_manifest_toml(manifest_path: Path) -> ManifestInspection:
    """Parse and fully resolve a manifest.toml (the same resolution a
    design.sources[].manifest entry gets at every `wolf run`, via
    _local_manifest_sources) far enough to answer "what does this
    declare, and does it even parse" right away. Raises ValueError on
    anything _resolve_manifest_bundle itself would reject (missing
    .flist, mismatched Verilog manifests, a referenced file that
    doesn't exist, ...) -- nothing here is cached; calling this again
    always reflects the manifest's current state on disk, so there is
    no separate "is it stale" question to answer."""
    if not manifest_path.is_file():
        raise ValueError(f"manifest does not exist: {manifest_path}")
    try:
        toml_data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"cannot parse {manifest_path}: {error}") from error
    sources, _, _, standard, _ = _local_manifest_sources(manifest_path)
    return ManifestInspection(
        name=toml_data.get("name"), top=toml_data.get("top"),
        vhdl_standard=standard, source_count=len(sources),
    )


def _resolve_manifest_bundle(metadata: Mapping[str, Any], root: Path) -> tuple[
    tuple[ResolvedSource, ...], tuple[Path, ...], tuple[str, ...], Optional[str], dict[str, str]
]:
    """Resolve generic ordered source metadata, including published TOML
    bundles -- shared by an installed rtl package (_design_inputs) and a
    local design.sources[].manifest entry (_local_manifest_sources)."""
    checksum_path = root / str(metadata.get("checksums", ""))
    checksums = _checksum_inventory(checksum_path)
    checksum_root = checksum_path.parent.resolve()
    manifest_paths = metadata.get("manifests", {})
    toml_data: Mapping[str, Any] = {}
    package_manifest = manifest_paths.get("package") if isinstance(manifest_paths, dict) else None
    bundle_root = root
    if package_manifest:
        package_path = root / str(package_manifest)
        if not package_path.is_file():
            raise ValueError(f"design package metadata manifest does not exist: {package_path}")
        try:
            toml_data = tomllib.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f"cannot parse design package metadata {package_path}: {error}") from error
        bundle_root = package_path.parent.resolve()

    def list_path(key: str, fallback: Any = None) -> Optional[Path]:
        value = toml_data.get(key, fallback)
        if not isinstance(value, str) or not value:
            return None
        return bundle_root / str(value)

    groups: list[tuple[str, str, str, Any]] = []
    ordered_verilog_libraries: dict[str, str] = {}
    if toml_data:
        groups.extend([
            ("vhdl", "work", "vhdl_package", list_path("vhdl_packages")),
            ("vhdl", "work", "vhdl_implementation", list_path("vhdl_sources")),
        ])
        combined = list_path("verilog_sources")
        fabulous = list_path("fabulous_library_sources")
        work = list_path("work_library_sources")
        if fabulous or work:
            split_lists = {
                "FABULOUS_EFPGA": _manifest_lines(fabulous) if fabulous else [],
                "work": _manifest_lines(work) if work else [],
            }
            split_paths = [path for values in split_lists.values() for path in values]
            if len(split_paths) != len(set(split_paths)):
                raise ValueError("design package split Verilog manifests contain duplicate paths")
            combined_values = _manifest_lines(combined) if combined else split_paths
            if len(combined_values) != len(set(combined_values)):
                raise ValueError("design package combined Verilog manifest contains duplicate paths")
            if set(combined_values) != set(split_paths):
                raise ValueError("design package combined and split Verilog manifests disagree")
            ordered_verilog_libraries = {
                path: library for library, values in split_lists.items() for path in values
            }
            # The combined manifest is an inventory and compilation order. The
            # split manifests provide only the named-library assignment.
            groups.append(("verilog", "work", "verilog", combined_values))
        else:
            groups.append(("verilog", "work", "verilog",
                           _manifest_lines(combined) if combined else []))
    else:
        patterns = metadata.get("sources", [])
        expanded: list[str] = []
        if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns):
            raise ValueError("design package metadata.design.sources must be a sequence of paths")
        for pattern in patterns:
            expanded.extend(path.relative_to(root).as_posix() for path in sorted(root.glob(pattern)))
        groups.append(("verilog", "work", "source", expanded))
    sources: list[ResolvedSource] = []
    for language, library, role, manifest_or_patterns in groups:
        if manifest_or_patterns is None:
            continue
        values = (_manifest_lines(manifest_or_patterns) if isinstance(manifest_or_patterns, Path)
                  else list(manifest_or_patterns) if isinstance(manifest_or_patterns, list) else [])
        if not all(isinstance(value, str) for value in values):
            raise ValueError("design source manifests must contain ordered relative paths")
        for value in values:
            path = (bundle_root / value).resolve()
            if not path.is_file():
                raise ValueError(f"design source manifest references missing file: {path}")
            suffix_language = language
            if language == "verilog" and path.suffix.lower() == ".sv":
                suffix_language = "systemverilog"
            relative = path.relative_to(checksum_root).as_posix()
            resolved_library = ordered_verilog_libraries.get(value, library)
            sources.append(ResolvedSource(
                path=path, language=suffix_language, library=resolved_library,
                order=len(sources), role=role, checksum=checksums.get(relative),
            ))
    include_path = list_path("include_dirs", metadata.get("include_dirs", []))
    includes = _manifest_lines(include_path) if isinstance(include_path, Path) else list(include_path or [])
    include_directories = tuple((bundle_root / str(value)).resolve() for value in includes)
    for path in include_directories:
        if not path.is_dir():
            raise ValueError(f"design include directory does not exist: {path}")
    define_path = list_path("defines", metadata.get("defines", []))
    defines = tuple(_manifest_lines(define_path) if isinstance(define_path, Path) else list(define_path or []))
    standard = toml_data.get("vhdl_standard")
    source_checksums = {
        str((checksum_root / relative).resolve()): checksum for relative, checksum in checksums.items()
    }
    return tuple(sources), include_directories, defines, standard, source_checksums


def _source_language(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".sv":
        return "systemverilog"
    if suffix in (".vhd", ".vhdl"):
        return "vhdl"
    return "verilog"


def _resolve_source_entries(
    entries: tuple[SourceEntry, ...],
    profile: EnvironmentProfile,
    registry: PackageRegistry,
    store: PackageStore,
    *,
    require_installed: bool,
) -> tuple[
    tuple[ResolvedSource, ...], tuple[Path, ...], tuple[str, ...], Optional[str],
    dict[str, str], list[tuple[Any, Any]],
]:
    """Resolve a design.sources list, mixing portable packages and local paths."""
    sources: list[ResolvedSource] = []
    include_directories: list[Path] = []
    defines: list[str] = []
    vhdl_standard: Optional[str] = None
    checksums: dict[str, str] = {}
    used: list[tuple[Any, Any]] = []
    for entry in entries:
        if entry.package:
            manifest = registry.get(entry.package)
            package = store.read(manifest)
            if package is None:
                if require_installed:
                    raise ValueError(f"required package {entry.package} is not installed")
                continue
            used.append((manifest, package))
            pkg_sources, pkg_includes, pkg_defines, pkg_standard, pkg_checksums = _design_inputs(
                manifest, package
            )
            for source in pkg_sources:
                sources.append(replace(source, order=len(sources)))
            include_directories.extend(pkg_includes)
            defines.extend(pkg_defines)
            vhdl_standard = vhdl_standard or pkg_standard
            checksums.update(pkg_checksums)
        elif entry.manifest:
            manifest_path = resolve_stored_path(entry.manifest, profile.path.parent)
            bundle_sources, bundle_includes, bundle_defines, bundle_standard, bundle_checksums = (
                _local_manifest_sources(manifest_path)
            )
            for source in bundle_sources:
                sources.append(replace(source, order=len(sources)))
            include_directories.extend(bundle_includes)
            defines.extend(bundle_defines)
            vhdl_standard = vhdl_standard or bundle_standard
            checksums.update(bundle_checksums)
        else:
            path = resolve_stored_path(entry.path, profile.path.parent)
            if not path.is_file():
                raise ValueError(f"design.sources path does not exist: {path}")
            sources.append(ResolvedSource(
                path=path, language=_source_language(path), library="work",
                order=len(sources), role="source",
            ))
    return (
        tuple(sources), tuple(dict.fromkeys(include_directories)), tuple(dict.fromkeys(defines)),
        vhdl_standard, checksums, used,
    )


def profile_semantics(profile: EnvironmentProfile) -> Mapping[str, Optional[str]]:
    """Return semantic package defaults without requiring package installation."""
    registry = PackageRegistry()
    result: dict[str, Optional[str]] = {
        "design": profile.design.name if profile.design else None,
        "top": profile.design.top if profile.design else None,
        "technology": profile.technology.name if profile.technology else None,
        "flow": profile.flow.name if profile.flow else None,
        # flow.backend (no flow package at all -- WOLF's own bundled flow,
        # the common case) is a direct, complete backend selection on its
        # own; an installed flow package's own declared backend below only
        # fills this in when the environment didn't already say so itself.
        "backend": profile.flow.backend if profile.flow else None,
    }
    for role, reference, section in (
        ("design", profile.design, "design"),
        ("technology", profile.technology, "technology"),
        ("flow", profile.flow, "flow"),
    ):
        if not reference or not reference.package:
            continue
        manifest = registry.get(reference.package)
        result[role] = result[role] or _semantic(manifest, section, "name")
        if role == "design":
            result["top"] = result["top"] or _semantic(manifest, "design", "top")
        if role == "flow":
            result["backend"] = result["backend"] or _semantic(manifest, "flow", "backend")
    return result


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
    # flow.backend (see ComponentReference's own comment) persists a
    # bundled-default flow's backend choice in wolf.yaml -- lower
    # priority than a real flow package's own declared backend, but
    # above it is only the explicit --backend CLI override.
    backend = backend_override or flow_backend or (flow.backend if flow else None)
    project_root = (
        resolve_stored_path(profile.project_root, profile.path.parent)
        if profile.project_root else None
    )
    workspace_root = workspace_override or (
        resolve_stored_path(profile.workspace_root, profile.path.parent)
        if profile.workspace_root else (project_root / "workspace" if project_root else None)
    )
    missing = [
        field for field, value in (
            ("design", design_name), ("technology", technology_name),
            # flow has no name of its own when using WOLF's bundled
            # default flow (backend alone is its real identity there --
            # "default" is not a real name, see env_menu.py), so backend
            # also satisfies this, same as _component's own "at least
            # one of package/name/top/backend" check already allows.
            ("flow", flow_name or backend),
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
    package_source_revisions = {
        str(package.manifest.identifier): package.source_revision
        for package in installed.values()
    }
    package_installation_paths = {
        str(package.manifest.identifier): package.installation_path
        for package in installed.values()
    }
    sources: tuple[ResolvedSource, ...] = ()
    source_files: tuple[Path, ...] = ()
    include_directories: tuple[Path, ...] = ()
    defines: tuple[str, ...] = ()
    vhdl_standard: Optional[str] = None
    package_checksums: dict[str, str] = {}
    resolved_technology = (
        _technology_inputs(manifests.get("technology"), installed.get("technology"), technology)
        if "technology" in manifests else None
    )
    if profile.design_sources:
        sources, include_directories, defines, vhdl_standard, package_checksums, used = (
            _resolve_source_entries(
                profile.design_sources, profile, registry, store,
                require_installed=require_installed,
            )
        )
        source_files = tuple(source.path for source in sources)
        package_revisions = {**package_revisions, **{str(m.identifier): m.revision for m, _ in used}}
        package_source_revisions = {
            **package_source_revisions,
            **{str(m.identifier): p.source_revision for m, p in used},
        }
        package_installation_paths = {
            **package_installation_paths,
            **{str(m.identifier): p.installation_path for m, p in used},
        }
    elif "design" in installed:
        sources, include_directories, defines, vhdl_standard, package_checksums = _design_inputs(
            manifests["design"], installed["design"]
        )
        source_files = tuple(source.path for source in sources)
    return ResolvedContext(
        state_root=state_root.resolve(),
        environment_name=profile.name,
        environment_directory=environment_directory.resolve(),
        project_root=project_root.resolve() if project_root else None,
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
        technology=resolved_technology,
        flow_package=flow.package if flow else None,
        package_revisions=package_revisions,
        package_paths=package_paths,
        package_source_revisions=package_source_revisions,
        package_installation_paths=package_installation_paths,
        source_files=tuple(dict.fromkeys(path.resolve() for path in source_files if path.is_file())),
        sources=sources,
        include_directories=tuple(dict.fromkeys(path for path in include_directories if path.is_dir())),
        defines=defines,
        vhdl_standard=vhdl_standard,
        package_checksums=package_checksums,
        clocks=profile.clocks,
        constraint_files=tuple(
            resolve_stored_path(item, profile.path.parent) for item in profile.constraint_files
        ),
        constraint_lines=profile.constraint_lines,
        floorplan_def=(
            resolve_stored_path(profile.floorplan_def, profile.path.parent)
            if profile.floorplan_def else None
        ),
        power_nets=profile.power_nets,
        ground_nets=profile.ground_nets,
        threads=profile.threads,
        backend_overrides=profile.backend_overrides,
        env_vars=profile.env_vars,
    )

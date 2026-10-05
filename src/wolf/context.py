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
class ResolvedSource:
    """One ordered source input preserved from a package manifest."""

    path: Path
    language: str
    library: str = "work"
    order: int = 0
    role: str = "source"
    checksum: Optional[str] = None


@dataclass(frozen=True)
class ResolvedTimingCorner:
    """One named MMMC corner: its own library set and, optionally, QRC tech file.

    `format` is declared metadata, not yet interpreted by any backend --
    Genus/Innovus auto-detect Liberty-family content regardless. It exists
    so a PDK package can record what it actually has (plain Liberty, ECSM,
    a variation/AOCV-SOCV library, ...) for whatever future consumer cares,
    the same declared-but-not-yet-consumed boundary as technology.generic.
    """

    name: str
    libraries: tuple[Path, ...]
    qrc_tech_file: Optional[Path] = None
    format: str = "liberty"


@dataclass(frozen=True)
class ResolvedQrcCorner:
    """One named RC extraction corner's own QRC techfiles, for the
    selected metal stack -- a real, independent axis from the PVT timing
    corners above: a captable characterizes BEOL (metal) process
    variation (e.g. rcbest/rcworst/typical), not FEOL transistor skew.
    Real captables are named per metal stack AND per rc-corner (confirmed
    filenames like `..._Vp9m+alrdl_top2_rcworst.captable`), unlike GDS,
    which doesn't vary by stack at all.
    """

    name: str
    qrc_techfiles: tuple[Path, ...]


@dataclass(frozen=True)
class ResolvedOpcond:
    """One named operating condition (create_opcond's own process/
    voltage/temperature) a timing corner may optionally reference --
    metadata for library sets that don't already embed it. Real .lib
    files almost always embed this already, so most packages declare
    none at all; this exists for the PDKs/corners that do need it."""

    name: str
    process: Optional[str] = None
    voltage: Optional[str] = None
    temperature: Optional[str] = None


@dataclass(frozen=True)
class ResolvedDelayCorner:
    """One named MMMC delay corner: a declared PVT timing-corner name
    paired with a declared RC-extraction-corner name -- the exact pairing
    a real delay_corner is (one rc_corner, one timing_condition), kept as
    a static, fully-declared catalog entry rather than computed per run."""

    name: str
    timing_corner: str
    rc_corner: str


@dataclass(frozen=True)
class ResolvedAnalysisView:
    """One named MMMC analysis view: a declared delay corner plus which
    kind(s) of analysis it drives (create_analysis_view's own -setup/
    -hold/-dynamic/-leakage flags). constraint_mode is deliberately not
    part of this -- it's a design-level pairing (which SDC a view uses),
    resolved at run time from the environment, not a PDK fact."""

    name: str
    delay_corner: str
    is_setup: bool = False
    is_hold: bool = False
    is_dynamic: bool = False
    is_leakage: bool = False


@dataclass(frozen=True)
class CatalogLibrarySet:
    """One (corner, track, vth)'s own library files -- the full cross
    product a tracked technology package declares, not just the one
    variant an environment selected. Exists so a get_flow_config-driven
    real flow can index `library_sets.<corner>.library_files.<track>.<vth>`
    itself at Tcl run time (its own code picks $trk/$vth; WOLF just hands
    over every combination that exists)."""

    corner: str
    track: str
    vth: str
    libraries: tuple[Path, ...]


@dataclass(frozen=True)
class CatalogFileList:
    """One (track, vth)'s own file list for a track/vth-keyed (not
    corner-keyed) physical/behavioral field -- lef or gds, say. Built
    against the technology's single resolved metal_stack (if the package
    declares named stacks at all): a track/vth that doesn't declare that
    stack is simply absent from the catalog, not an error -- not every
    track/vth combination necessarily supports every stack."""

    track: str
    vth: str
    files: tuple[Path, ...]


@dataclass(frozen=True)
class ResolvedTechnology:
    """Package-resolved technology views available to a backend.

    A technology package may declare its views flat (one implicit track/vth,
    today's shape) or nested under several named tracks/vths (e.g. 9T/lvt,
    9T/hvt, 7T/rvt) when it needs more than one. Either way, resolution
    always flattens down to exactly one selected variant's data here --
    `track`/`vth` record which one (None for a flat-declared package), and
    every other field below is that variant's data, in the same shape
    backends already consume regardless of how it was declared.
    """

    package: str
    revision: str
    name: str
    root: Path
    track: Optional[str] = None
    vth: Optional[str] = None
    metal_stack: Optional[str] = None
    timing_corner: str = "typical"
    timing_libraries: tuple[Path, ...] = ()
    timing_corners: tuple[ResolvedTimingCorner, ...] = ()
    technology_lefs: tuple[Path, ...] = ()
    cell_lefs: tuple[Path, ...] = ()
    rc_files: tuple[Path, ...] = ()
    gds_files: tuple[Path, ...] = ()
    verilog_models: tuple[Path, ...] = ()
    spice_models: tuple[Path, ...] = ()
    qrc_techfiles: tuple[Path, ...] = ()
    qrc_corners: tuple[ResolvedQrcCorner, ...] = ()
    generic: Mapping[str, Any] = field(default_factory=dict)
    checksums: Mapping[str, str] = field(default_factory=dict)
    dont_use_cells: tuple[str, ...] = ()
    setup_yaml_fragment: Optional[Path] = None
    catalog_library_sets: tuple[CatalogLibrarySet, ...] = ()
    catalog_lef_files: tuple[CatalogFileList, ...] = ()
    catalog_gds_files: tuple[CatalogFileList, ...] = ()
    catalog_opconds: tuple[ResolvedOpcond, ...] = ()
    catalog_delay_corners: tuple[ResolvedDelayCorner, ...] = ()
    catalog_analysis_views: tuple[ResolvedAnalysisView, ...] = ()


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
    technology: Optional[ResolvedTechnology] = None
    flow_package: Optional[str] = None
    package_revisions: Mapping[str, str] = field(default_factory=dict)
    package_paths: Mapping[str, Path] = field(default_factory=dict)
    package_source_revisions: Mapping[str, str] = field(default_factory=dict)
    package_installation_paths: Mapping[str, Path] = field(default_factory=dict)
    source_files: tuple[Path, ...] = ()
    sources: tuple[ResolvedSource, ...] = ()
    include_directories: tuple[Path, ...] = ()
    defines: tuple[str, ...] = ()
    vhdl_standard: Optional[str] = None
    package_checksums: Mapping[str, str] = field(default_factory=dict)
    clocks: tuple[Any, ...] = ()
    constraint_files: tuple[Path, ...] = ()
    constraint_lines: tuple[str, ...] = ()
    floorplan_def: Optional[Path] = None
    project_root: Optional[Path] = None
    threads: Optional[int] = None
    backend_overrides: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    env_vars: Mapping[str, str] = field(default_factory=dict)


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

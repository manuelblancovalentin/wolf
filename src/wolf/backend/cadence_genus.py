"""Generic mixed-language Cadence Genus input preparation.

This module consumes resolved WOLF source metadata only.  It deliberately has
no knowledge of ESP, FABulous, or any generator-specific conventions.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Mapping, Optional

import yaml

from wolf.context import ResolvedContext
from wolf.paths import builtin_flow_root


@dataclass(frozen=True)
class GenusValidation:
    name: str
    available: bool
    detail: str


@dataclass(frozen=True)
class GenusInputs:
    directory: Path
    scripts_directory: Path
    technology_script: Path | None
    overrides_script: Path | None
    source_script: Path
    flow_config_script: Path
    flow_root: Path
    setup_yaml: Path
    flow_yaml: Path
    manifest: Path


# Genus must parse RTL in synthesis mode.  These are backend policy, not
# package metadata, and are therefore added only to emitted Genus inputs.
GENUS_REQUIRED_DEFINES = ("SYNTHESIS",)

# Backend-native Genus attributes a run may need to override (e.g. raising
# hdl_max_memory_address_range past a generic-inference default). These are
# tool policy, not canonical WOLF semantics, so they arrive only through the
# explicit backend.cadence-flowtool escape hatch.
_ALLOWED_CADENCE_FLOWTOOL_OVERRIDES = frozenset({"genus", "flowtool"})
_ALLOWED_GENUS_OVERRIDES = frozenset({"set_db"})

# The institution-supplied Flowtool project descriptors this backend renders
# WOLF's resolved values into (see _flowtool_templates/_render_template).
# WOLF does not know or ship Cadence's YAML flow-descriptor schema -- these
# are the institution's own files, referenced only by path.
_ALLOWED_FLOWTOOL_OVERRIDES = frozenset({"setup_template", "flow_template"})

_SCRIPTS_DIR_RE = re.compile(r"^scripts\.(\d+)$")

# Canonical stage order -- must match the create_flow_step names in
# flows/cadence-genus/flow.tcl exactly, since these are passed verbatim as
# Flowtool's own -from/-to step-range arguments (see `_resolve_stage_range`).
STAGE_ORDER = ("elaborate", "syn_generic", "syn_map", "syn_opt")

# `flow.name` values remain supported as shorthand for the common "run
# everything from elaborate through X" range -- not a separate mechanism.
FLOW_GENUS_ELABORATION = "genus-elaboration"
FLOW_GENUS_SYN_GENERIC = "genus-syn-generic"
FLOW_GENUS_SYN_MAP = "genus-syn-map"
FLOW_GENUS_SYN_OPT = "genus-syn-opt"

_FLOW_NAME_STAGE_RANGE: Mapping[str, str] = {
    FLOW_GENUS_ELABORATION: "elaborate",
    FLOW_GENUS_SYN_GENERIC: "syn_generic",
    FLOW_GENUS_SYN_MAP: "syn_map",
    FLOW_GENUS_SYN_OPT: "syn_opt",
}

_SYNTHESIS_STAGE_NETLIST_SUFFIX = {
    "syn_generic": "generic",
    "syn_map": "mapped",
    "syn_opt": "opt",
}


def _resolve_stage_range(
    context: ResolvedContext, from_stage: Optional[str], to_stage: Optional[str]
) -> tuple[str, str]:
    """Return the (from, to) stage names this run should execute.

    An explicit -from/-to pair (checkpoint reuse's real primitive) always
    wins. Without one, `flow.name` is shorthand for "elaborate through X".
    """
    if from_stage is None and to_stage is None:
        flow_name = context.flow_name or FLOW_GENUS_ELABORATION
        try:
            return "elaborate", _FLOW_NAME_STAGE_RANGE[flow_name]
        except KeyError:
            raise ValueError(
                f"unsupported cadence-flowtool flow {flow_name!r}; expected one of "
                + ", ".join(sorted(_FLOW_NAME_STAGE_RANGE))
            ) from None
    from_stage = from_stage or "elaborate"
    to_stage = to_stage or STAGE_ORDER[-1]
    for stage in (from_stage, to_stage):
        if stage not in STAGE_ORDER:
            raise ValueError(f"unsupported stage {stage!r}; expected one of {STAGE_ORDER}")
    if STAGE_ORDER.index(from_stage) > STAGE_ORDER.index(to_stage):
        raise ValueError(f"-from {from_stage!r} comes after -to {to_stage!r}")
    return from_stage, to_stage


def _tcl_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _tcl_quote(value)
    raise ValueError(f"Genus set_db override values must be scalar, got {type(value).__name__}")


def _effective_genus_threads(context: ResolvedContext) -> Optional[int]:
    """Resolve the CPU/thread count Genus should use, if any.

    WOLF's own canonical ``resources.threads`` wins when set. Otherwise, the
    backend honors GENUS_NUM_CPUS if the environment declared it -- a
    long-standing Cadence-flow convention, recognized here as backend-native
    policy rather than promoted into canonical WOLF semantics. Reading it
    from context.env_vars (not the ambient process environment) keeps the
    resolved value reproducible and recorded in provenance.
    """
    if context.threads:
        return context.threads
    raw = context.env_vars.get("GENUS_NUM_CPUS")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"env.GENUS_NUM_CPUS must be an integer, got {raw!r}") from None


def _flow_root(context: ResolvedContext) -> Path:
    """Locate the real, editable Tcl scripts that define this run's flow.

    An installed flow package (a project's own `wolf flow init` clone) wins
    when the environment references one *and* it actually contains a Genus
    flow.tcl -- an environment's flow package may belong to a different
    backend entirely (e.g. flow/orfs), which is not this flow's root.
    Otherwise WOLF's own bundled default flow scripts are used. Either way,
    these are ordinary files on disk -- readable, browsable, and never
    regenerated by WOLF.
    """
    package_path = context.package_paths.get("flow")
    if package_path is not None and (package_path / "flow.tcl").is_file():
        return package_path
    return builtin_flow_root("cadence-genus")


def _tcl_list(values: tuple[str, ...]) -> str:
    return "{" + " ".join(_tcl_quote(value) for value in values) + "}"


def _cadence_flowtool_overrides(context: ResolvedContext) -> Mapping[str, Any]:
    overrides = context.backend_overrides.get("cadence-flowtool", {})
    if not isinstance(overrides, Mapping):
        raise ValueError("backend.cadence-flowtool must be a mapping")
    unknown = set(overrides) - _ALLOWED_CADENCE_FLOWTOOL_OVERRIDES
    if unknown:
        raise ValueError(f"unsupported backend.cadence-flowtool override: {sorted(unknown)[0]}")
    return overrides


def _genus_set_db_overrides(context: ResolvedContext) -> tuple[tuple[str, Any], ...]:
    """Return ordered, validated set_db overrides from backend.cadence-flowtool.genus."""
    genus = _cadence_flowtool_overrides(context).get("genus", {})
    if not isinstance(genus, Mapping):
        raise ValueError("backend.cadence-flowtool.genus must be a mapping")
    unknown = set(genus) - _ALLOWED_GENUS_OVERRIDES
    if unknown:
        raise ValueError(f"unsupported backend.cadence-flowtool.genus override: {sorted(unknown)[0]}")
    set_db = genus.get("set_db", {})
    if not isinstance(set_db, Mapping):
        raise ValueError("backend.cadence-flowtool.genus.set_db must be a mapping")
    return tuple(sorted(set_db.items()))


def _flowtool_templates(context: ResolvedContext) -> tuple[Path, Path]:
    """Return the institution-supplied (setup_template, flow_template) paths.

    WOLF ships no Cadence Flowtool YAML schema of its own -- these are the
    institution's own real Flowtool project descriptors (the same role
    PROCESS_SETUP_COMMON_TEMPLATE/PROCESS_FLOW_TEMPLATE play for the legacy
    Bash runner), referenced only by path via the same
    backend.cadence-flowtool escape hatch used for set_db overrides.
    """
    flowtool = _cadence_flowtool_overrides(context).get("flowtool", {})
    if not isinstance(flowtool, Mapping):
        raise ValueError("backend.cadence-flowtool.flowtool must be a mapping")
    unknown = set(flowtool) - _ALLOWED_FLOWTOOL_OVERRIDES
    if unknown:
        raise ValueError(f"unsupported backend.cadence-flowtool.flowtool override: {sorted(unknown)[0]}")
    missing = sorted(_ALLOWED_FLOWTOOL_OVERRIDES - set(flowtool))
    if missing:
        raise ValueError(
            "backend.cadence-flowtool.flowtool requires " + " and ".join(missing)
            + " (institution-supplied Flowtool project descriptors; WOLF does not ship one)"
        )
    paths = []
    for key in ("setup_template", "flow_template"):
        value = flowtool[key]
        if not isinstance(value, str) or not value:
            raise ValueError(f"backend.cadence-flowtool.flowtool.{key} must be a nonempty string")
        path = Path(value).expanduser()
        if not path.is_file():
            raise ValueError(f"backend.cadence-flowtool.flowtool.{key} does not exist: {path}")
        paths.append(path.resolve())
    return paths[0], paths[1]


def _render_template(template: Path, placeholders: Mapping[str, str]) -> str:
    """Substitute ``${KEY}`` placeholders into a copy of an institution template.

    WOLF never inspects or requires anything about the surrounding Flowtool
    YAML structure -- it only replaces tokens the institution's own template
    chooses to reference, the same plain substitution the legacy Bash runner
    already does with ``sed``.
    """
    text = template.read_text(encoding="utf-8")
    for key, value in placeholders.items():
        text = text.replace("${" + key + "}", value)
    return text


def _snapshot_scripts(base_directory: Path, files: Mapping[str, str]) -> Path:
    """Materialize flow scripts into a deduplicated, numbered scripts.<N> dir.

    Mirrors the legacy Bash runner's own scripts.<N>/scripts.latest
    mechanism (bin/wolf.run): reuse the most recent scripts.<N> whose
    recorded digest matches this run's content instead of writing a
    duplicate snapshot, and always repoint scripts.latest at whichever
    directory is current.
    """
    existing = sorted(
        (int(match.group(1)), path)
        for path in base_directory.glob("scripts.*")
        if path.is_dir() and (match := _SCRIPTS_DIR_RE.match(path.name))
    )
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(files[name].encode("utf-8")).hexdigest().encode("utf-8"))
        digest.update(b"\n")
    content_digest = digest.hexdigest()

    if existing:
        latest_index, latest_directory = existing[-1]
        checksum_file = latest_directory / "scripts.sha256checksum"
        if checksum_file.is_file() and checksum_file.read_text(encoding="utf-8").strip() == content_digest:
            _relink_scripts_latest(base_directory, latest_directory)
            return latest_directory
        next_index = latest_index + 1
    else:
        next_index = 1

    scripts_directory = base_directory / f"scripts.{next_index}"
    scripts_directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = scripts_directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (scripts_directory / "scripts.sha256checksum").write_text(content_digest, encoding="utf-8")
    _relink_scripts_latest(base_directory, scripts_directory)
    return scripts_directory


def _relink_scripts_latest(base_directory: Path, target: Path) -> None:
    link = base_directory / "scripts.latest"
    link.unlink(missing_ok=True)
    link.symlink_to(target.name)


def _normalize_vhdl_standard(value: Any) -> str:
    canonical = str(value or "93")
    normalized = {"87": "1987", "1987": "1987", "93": "1993", "1993": "1993",
                  "08": "2008", "2008": "2008"}.get(canonical)
    if normalized is None:
        raise ValueError(
            f"unsupported VHDL standard {canonical!r}; supported values are 1987, 1993, and 2008"
        )
    return normalized


def allocate_genus_run(context: ResolvedContext, *, clean: bool = False) -> Path:
    """Allocate a new numbered run without modifying earlier runs."""
    base = context.workspace_root / context.design_name / f"{context.design_name}.{context.process}"
    if not clean and not context.run_directory.exists():
        return context.run_directory
    index = 1
    while (base / f"{context.design_name}.{index}").exists():
        index += 1
    return base / f"{context.design_name}.{index}"


def _period_ns(period_ps: Any) -> str:
    value = Decimal(str(period_ps)) / Decimal("1000")
    return format(value.normalize(), "f").rstrip("0").rstrip(".") or "0"


def validate_genus(
    context: ResolvedContext,
    *,
    executable_lookup=shutil.which,
    physical: bool = False,
) -> tuple[GenusValidation, ...]:
    """Validate Genus and any explicitly configured technology inputs.

    Technology-independent elaboration may omit physical views.  When a view
    is configured, however, it must exist before a run is allocated.
    """
    checks = []
    flowtool = executable_lookup("flowtool")
    checks.append(GenusValidation("flowtool", flowtool is not None, flowtool or "unavailable"))
    try:
        setup_template, flow_template = _flowtool_templates(context)
        checks.append(GenusValidation(
            "flowtool templates", True, f"{setup_template}, {flow_template}",
        ))
    except ValueError as error:
        checks.append(GenusValidation("flowtool templates", False, str(error)))
    technology = context.technology
    if technology is not None:
        checks.append(GenusValidation(
            "technology timing libraries", bool(technology.timing_libraries),
            ", ".join(str(path) for path in technology.timing_libraries) or "none configured",
        ))
        if physical:
            checks.append(GenusValidation(
                "technology LEF", bool(technology.technology_lefs and technology.cell_lefs),
                "technology and cell LEF required for physical implementation",
            ))
            checks.append(GenusValidation(
                "technology RC", bool(technology.rc_files),
                "RC setup/extraction collateral required for physical implementation",
            ))
    for key in ("LIBRARY_FILES", "LEF_FILES", "QRC_TECH_FILE", "TECHNOLOGY_SETUP"):
        value = context.values.get(key)
        if value:
            paths = [Path(item) for item in value.split()]
            missing = [str(path) for path in paths if not path.is_file()]
            checks.append(GenusValidation(key, not missing, ", ".join(missing) or value))
    return tuple(checks)


def _tcl_quote(value: str) -> str:
    return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""


def _digest(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _effective_genus_defines(context: ResolvedContext) -> tuple[str, ...]:
    """Return stable, de-duplicated package plus Genus policy defines."""
    effective: list[str] = []
    seen: set[str] = set()
    for define in (*context.defines, *GENUS_REQUIRED_DEFINES):
        value = str(define)
        if value not in seen:
            effective.append(value)
            seen.add(value)
    return tuple(effective)


def prepare_genus_inputs(
    context: ResolvedContext, destination: Path, *,
    interactive: bool = False, from_stage: Optional[str] = None, to_stage: Optional[str] = None,
) -> GenusInputs:
    """Write deterministic Flowtool/Genus inputs and a provenance manifest.

    Two distinct kinds of file live under `destination`:

    - the flow *scripts* (flow.tcl, presentation.tcl) -- the real,
      version-controlled step definitions that decide what each stage does.
      These land in a deduplicated, numbered scripts.<N> snapshot (with a
      scripts.latest symlink), mirroring the legacy Bash runner's own
      PROCESS_SCRIPTS snapshot mechanism, so history of exactly which flow
      logic a run used is preserved and unchanged runs don't re-snapshot;
    - the resolved *values* this run supplies to them (sources.tcl,
      technology.tcl, overrides.tcl, constraints.sdc, flow-config.tcl, and
      the institution's own setup.yaml/flow.yaml Flowtool project
      descriptors rendered with those values) -- written directly, fresh
      every call, same as before.
    """
    if not context.sources:
        raise ValueError("Cadence Genus preparation requires ordered resolved sources")
    if not context.design_top:
        raise ValueError("Cadence Genus preparation requires design.top")
    resolved_from_stage, resolved_to_stage = _resolve_stage_range(context, from_stage, to_stage)
    synthesis_stages = tuple(
        stage for stage in STAGE_ORDER[STAGE_ORDER.index(resolved_from_stage):
                                        STAGE_ORDER.index(resolved_to_stage) + 1]
        if stage != "elaborate"
    )
    genus_vhdl_standard = _normalize_vhdl_standard(context.vhdl_standard)
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    reports_directory = destination / "reports"
    outputs_directory = destination / "outputs"
    reports_directory.mkdir(exist_ok=True)
    outputs_directory.mkdir(exist_ok=True)
    source_script = destination / "sources.tcl"
    technology_script = destination / "technology.tcl" if context.technology else None
    genus_overrides = _genus_set_db_overrides(context)
    overrides_script = destination / "overrides.tcl" if genus_overrides else None
    flow_config_script = destination / "flow-config.tcl"
    manifest = destination / "genus-inputs.yaml"
    constraints = destination / "constraints.sdc"
    package_defines = tuple(str(value) for value in context.defines)
    backend_defines = tuple(GENUS_REQUIRED_DEFINES)
    effective_defines = _effective_genus_defines(context)
    setup_template, flow_template = _flowtool_templates(context)

    if technology_script is not None:
        libraries = " ".join(_tcl_quote(str(path)) for path in context.technology.timing_libraries)
        technology_script.write_text(
            "# Generated by WOLF; package-resolved Genus technology inputs.\n"
            f"set_db library [list {libraries}]\n",
            encoding="utf-8",
        )

    if overrides_script is not None:
        overrides_script.write_text(
            "# Generated by WOLF; explicit backend.cadence-flowtool.genus.set_db overrides.\n"
            + "".join(f"set_db {key} {_tcl_scalar(value)}\n" for key, value in genus_overrides),
            encoding="utf-8",
        )

    if context.floorplan_def and not (context.technology and (
        context.technology.technology_lefs or context.technology.cell_lefs
    )):
        raise ValueError(
            "constraints.floorplan_def requires the technology package to declare "
            "physical.technology_lefs or physical.cell_lefs"
        )

    lines = [
        "# Generated by WOLF; source order is part of the resolved context.",
        f"set_db hdl_vhdl_read_version {genus_vhdl_standard}",
    ]
    if context.include_directories:
        include_values = " ".join(_tcl_quote(str(path)) for path in context.include_directories)
        lines.append(f"set_db hdl_search_path {{{include_values}}}")
    if effective_defines:
        defines = " ".join(_tcl_quote(value) for value in effective_defines)
        lines.append(f"set_db hdl_verilog_define {{{defines}}}")
    for source in context.sources:
        language = "-vhdl" if source.language == "vhdl" else "-sv"
        lines.append(f"read_hdl {language} -library {source.library} {_tcl_quote(str(source.path))}")
    source_script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    constraints.write_text("\n".join(
        f"create_clock -name {clock.name} -period {_period_ns(clock.period_ps)} [get_ports {clock.port}]"
        for clock in context.clocks
    ) + ("\n" if context.clocks else ""), encoding="utf-8")

    effective_threads = _effective_genus_threads(context)
    dont_use_cells = context.technology.dont_use_cells if context.technology else ()
    technology_lefs = context.technology.technology_lefs if context.technology else ()
    cell_lefs = context.technology.cell_lefs if context.technology else ()
    flow_root = _flow_root(context)

    # The flow *scripts* -- the real step definitions -- get a deduplicated,
    # numbered snapshot. Their dedup digest covers only these two files, so
    # unrelated per-run values never force a new snapshot.
    scripts_directory = _snapshot_scripts(destination, {
        "flow.tcl": (flow_root / "flow.tcl").read_text(encoding="utf-8"),
        "presentation.tcl": (flow_root / "presentation.tcl").read_text(encoding="utf-8"),
    })

    # Resolved, run-specific *values* only -- every step this run performs
    # is defined in scripts_directory/flow.tcl (see that file's header for
    # what each name below configures), never here. A project can point
    # flow.package at its own `wolf flow init` clone of flow_root instead of
    # the bundled default.
    flow_config_script.write_text(
        "# Generated by WOLF; resolved values consumed by flow.tcl.\n"
        f"set wolf_design_name {_tcl_quote(context.design_name)}\n"
        f"set wolf_design_top {_tcl_quote(context.design_top)}\n"
        f"set wolf_reports_dir {_tcl_quote(str(reports_directory))}\n"
        f"set wolf_outputs_dir {_tcl_quote(str(outputs_directory))}\n"
        f"set wolf_max_cpus_per_server "
        f"{effective_threads if effective_threads is not None else '\"\"'}\n"
        f"set wolf_technology_script "
        f"{_tcl_quote(str(technology_script)) if technology_script else '\"\"'}\n"
        f"set wolf_overrides_script "
        f"{_tcl_quote(str(overrides_script)) if overrides_script else '\"\"'}\n"
        f"set wolf_sources_script {_tcl_quote(str(source_script))}\n"
        f"set wolf_constraints_file {_tcl_quote(str(constraints))}\n"
        f"set wolf_dont_use_cells {_tcl_list(dont_use_cells)}\n"
        f"set wolf_technology_lefs {_tcl_list(tuple(str(path) for path in technology_lefs))}\n"
        f"set wolf_cell_lefs {_tcl_list(tuple(str(path) for path in cell_lefs))}\n"
        f"set wolf_floorplan_def "
        f"{_tcl_quote(str(context.floorplan_def)) if context.floorplan_def else '\"\"'}\n",
        encoding="utf-8",
    )

    # Render the institution's own Flowtool project descriptors. WOLF knows
    # nothing about their internal structure beyond the placeholder tokens
    # below; the institution's template decides how (or whether) to use
    # each one, exactly as it already does for the legacy Bash runner.
    placeholders = {
        "WOLF_DESIGN_NAME": context.design_name,
        "WOLF_DESIGN_TOP": context.design_top,
        "WOLF_SCRIPTS_DIR": str(scripts_directory),
        "WOLF_WORKSPACE_DIR": str(context.workspace_root),
        "WOLF_RUN_DIRECTORY": str(destination),
        "WOLF_RUN_TAG": context.run_tag,
        "WOLF_REPORTS_DIR": str(reports_directory),
        "WOLF_OUTPUTS_DIR": str(outputs_directory),
    }
    setup_yaml = destination / f"setup.{context.design_name}.yaml"
    flow_yaml = destination / f"flow.{context.design_name}.yaml"
    setup_yaml.write_text(_render_template(setup_template, placeholders), encoding="utf-8")
    flow_yaml.write_text(
        _render_template(flow_template, {**placeholders, "WOLF_SETUP_YAML": str(setup_yaml)}),
        encoding="utf-8",
    )

    netlist_relative: str | None = None
    if synthesis_stages:
        suffix = _SYNTHESIS_STAGE_NETLIST_SUFFIX[synthesis_stages[-1]]
        netlist_relative = f"outputs/{context.design_name}.{suffix}.v"

    records = [
        {
            "path": str(source.path), "order": source.order, "language": source.language,
            "library": source.library, "role": source.role,
            **({"sha256": source.checksum} if source.checksum else {}),
        }
        for source in context.sources
    ]
    data: Mapping[str, Any] = {
        "schema": "wolf.cadence-genus-inputs/v1",
        "design": {"name": context.design_name, "top": context.design_top},
        "vhdl_standard": context.vhdl_standard or "93",
        "sources": records,
        "include_directories": [str(path) for path in context.include_directories],
        # ``defines`` is the exact emitted set for compatibility and quick
        # inspection.  The detailed sets preserve package/backend provenance.
        "defines": list(effective_defines),
        "define_sets": {
            "package_requested": list(package_defines),
            "backend_required": list(backend_defines),
            "effective": list(effective_defines),
        },
        "constraints": {"clocks": [
            {"name": clock.name, "port": clock.port, "period_ps": clock.period_ps}
            for clock in context.clocks
        ]},
        "outputs": {
            "reports": str(reports_directory),
            "netlist": str(destination / netlist_relative) if netlist_relative else None,
            "constraints": str(constraints),
        },
        "flow": context.flow_name or FLOW_GENUS_ELABORATION,
        "flow_root": str(flow_root),
        "scripts_directory": str(scripts_directory),
        "setup_yaml": str(setup_yaml),
        "flow_yaml": str(flow_yaml),
        "from_stage": resolved_from_stage,
        "to_stage": resolved_to_stage,
        "synthesis_stages": list(synthesis_stages),
        "dont_use_cells": list(dont_use_cells),
        "floorplan_def": str(context.floorplan_def) if context.floorplan_def else None,
        "technology": ({
            "package": context.technology.package,
            "revision": context.technology.revision,
            "name": context.technology.name,
            "timing_corner": context.technology.timing_corner,
            "timing_libraries": [str(path) for path in context.technology.timing_libraries],
            "technology_lefs": [str(path) for path in context.technology.technology_lefs],
            "cell_lefs": [str(path) for path in context.technology.cell_lefs],
            "rc_files": [str(path) for path in context.technology.rc_files],
            "gds_files": [str(path) for path in context.technology.gds_files],
            "checksums": dict(context.technology.checksums),
        } if context.technology else None),
        "packages": [
            {"id": identifier, "revision": revision}
            for identifier, revision in sorted(context.package_revisions.items())
        ],
        "genus_overrides": {key: value for key, value in genus_overrides},
        "max_cpus_per_server": effective_threads,
        "source_checksum": _digest([source.path for source in context.sources]),
    }
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return GenusInputs(
        destination, scripts_directory, technology_script, overrides_script, source_script,
        flow_config_script, flow_root, setup_yaml, flow_yaml, manifest,
    )


def validate_genus_or_raise(context: ResolvedContext) -> str:
    checks = validate_genus(context)
    failures = [f"{item.name}: {item.detail}" for item in checks if not item.available]
    if failures:
        raise ValueError("Cadence Genus validation failed: " + "; ".join(failures))
    return next(item.detail for item in checks if item.name == "flowtool")


def run_genus(
    context: ResolvedContext, *, clean: bool = False, interactive: bool = False,
    from_stage: Optional[str] = None, to_stage: Optional[str] = None,
) -> tuple[int, Path]:
    """Allocate, prepare, freeze provenance, and execute one Flowtool run.

    Execution goes through the real `flowtool` binary, not `genus` directly,
    so the create_flow_step/-write_db checkpointing in
    flows/cadence-genus/flow.tcl is meaningful: Flowtool's own engine saves
    each step's checkpoint and, on a later -from, loads the nearest
    preceding one automatically -- WOLF does not reimplement that itself.
    A run without -c/--clean reuses the same numbered run directory, so an
    earlier invocation's checkpoints are still there for a later -from.
    """
    flowtool = validate_genus_or_raise(context)
    run_directory = allocate_genus_run(context, clean=clean)
    inputs = prepare_genus_inputs(
        context, run_directory / "backend" / "cadence-genus", interactive=interactive,
        from_stage=from_stage, to_stage=to_stage,
    )
    resolved = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
    resolved["schema"] = "wolf.resolved-run/v1"
    log_file = inputs.directory / "flowtool.log"
    command = [
        flowtool, "-files", str(inputs.flow_yaml), "-run_tag", context.run_tag,
        "-from", resolved["from_stage"], "-to", resolved["to_stage"],
        "-directory", str(context.workspace_root / context.design_name
                           / f"{context.design_name}.{context.process}"),
        "-log", str(log_file),
    ]
    if interactive:
        command.append("-interactive")
    resolved["execution"] = {
        "executor": "native", "tool": "flowtool", "executable": flowtool,
        "working_directory": str(inputs.directory),
        "command": command,
    }
    resolved["environment"] = context.environment_name
    resolved["workspace"] = {
        "root": str(context.workspace_root), "run_directory": str(run_directory),
    }
    resolved_source = inputs.directory / "resolved.yaml"
    resolved_source.write_text(yaml.safe_dump(resolved, sort_keys=False), encoding="utf-8")
    from wolf.provenance import freeze_run_manifest
    freeze_run_manifest(
        resolved_source, run_directory,
        generated_directory=inputs.directory,
        generated_files={
            **({"genus_technology": str(inputs.technology_script)} if inputs.technology_script else {}),
            **({"genus_overrides": str(inputs.overrides_script)} if inputs.overrides_script else {}),
            "genus_sources": str(inputs.source_script),
            "genus_constraints": str(inputs.directory / "constraints.sdc"),
            "genus_flow_config": str(inputs.flow_config_script),
            "flowtool_setup_yaml": str(inputs.setup_yaml),
            "flowtool_flow_yaml": str(inputs.flow_yaml),
            "flowtool_scripts_directory": str(inputs.scripts_directory),
        },
    )
    result = subprocess.run(command, cwd=inputs.directory, check=False)
    return result.returncode, run_directory

"""Generic mixed-language Cadence Genus input preparation.

This module consumes resolved WOLF source metadata only.  It deliberately has
no knowledge of ESP, FABulous, or any generator-specific conventions.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping, Optional

import yaml

from wolf.context import ResolvedContext


@dataclass(frozen=True)
class GenusValidation:
    name: str
    available: bool
    detail: str


@dataclass(frozen=True)
class GenusInputs:
    directory: Path
    technology_script: Path | None
    overrides_script: Path | None
    source_script: Path
    run_script: Path
    manifest: Path


# Genus must parse RTL in synthesis mode.  These are backend policy, not
# package metadata, and are therefore added only to emitted Genus inputs.
GENUS_REQUIRED_DEFINES = ("SYNTHESIS",)

# Backend-native Genus attributes a run may need to override (e.g. raising
# hdl_max_memory_address_range past a generic-inference default). These are
# tool policy, not canonical WOLF semantics, so they arrive only through the
# explicit backend.cadence-flowtool escape hatch.
_ALLOWED_CADENCE_FLOWTOOL_OVERRIDES = frozenset({"genus"})
_ALLOWED_GENUS_OVERRIDES = frozenset({"set_db"})

# Selectable Genus flows. Each name is a `flow.name` an environment can
# choose; the value is the ordered synthesis stages it runs on top of the
# elaboration pipeline every flow shares. Elaboration-only remains the
# default so existing environments are unaffected.
FLOW_GENUS_ELABORATION = "genus-elaboration"
FLOW_GENUS_SYN_GENERIC = "genus-syn-generic"
FLOW_GENUS_SYN_MAP = "genus-syn-map"
FLOW_GENUS_SYN_OPT = "genus-syn-opt"

_SYNTHESIS_STAGES: Mapping[str, tuple[str, ...]] = {
    FLOW_GENUS_ELABORATION: (),
    FLOW_GENUS_SYN_GENERIC: ("syn_generic",),
    FLOW_GENUS_SYN_MAP: ("syn_generic", "syn_map"),
    FLOW_GENUS_SYN_OPT: ("syn_generic", "syn_map", "syn_opt"),
}

_SYNTHESIS_STAGE_TITLES = {
    "syn_generic": "Synthesizing to generic gates",
    "syn_map": "Mapping to technology library",
    "syn_opt": "Optimizing mapped netlist",
}

_SYNTHESIS_STAGE_NETLIST_SUFFIX = {
    "syn_generic": "generic",
    "syn_map": "mapped",
    "syn_opt": "opt",
}


def _resolve_synthesis_stages(context: ResolvedContext) -> tuple[str, ...]:
    """Return the ordered synthesis stages the selected flow runs, if any."""
    flow_name = context.flow_name or FLOW_GENUS_ELABORATION
    try:
        return _SYNTHESIS_STAGES[flow_name]
    except KeyError:
        raise ValueError(
            f"unsupported cadence-flowtool flow {flow_name!r}; expected one of "
            + ", ".join(sorted(_SYNTHESIS_STAGES))
        ) from None


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


# Minimal, freshly written ANSI step presentation for the Genus log itself
# (Genus's own subprocess stdout, never touched by wolf.ui/Rich). Inspired by
# the concept of bracketing each operation with a colored title/separator,
# not derived from any specific flow's script content.
_WOLF_TCL_PRESENTATION = (
    "proc wolf_sep {} { return \"\\033\\[34m[string repeat - 100]\\033\\[0m\" }\n"
    "proc wolf_step {title} {\n"
    "    puts [wolf_sep]\n"
    "    puts \"\\033\\[1;34m| $title\\033\\[0m\"\n"
    "    puts [wolf_sep]\n"
    "}\n"
)


def _dont_use_tcl(patterns: tuple[str, ...]) -> str:
    """Mark PDK-configured cells unusable before generic synthesis.

    Each pattern is a plain cell-name glob from the technology package's own
    `synthesis.dont_use` metadata (never an arbitrary Tcl expression), kept
    to Genus's ordinary ``get_db`` name-glob matching.
    """
    quoted = " ".join(_tcl_quote(pattern) for pattern in patterns)
    return (
        f"foreach dont_use_cell {{{quoted}}} {{\n"
        "        set_db [get_db base_cells $dont_use_cell] .dont_use true\n"
        "    }"
    )


# Standard Cadence Genus path-grouping idiom (in2out/in2reg/reg2out/reg2reg),
# generic Cadence practice rather than any specific flow's methodology.
# WOLF resolves one flat SDC per run rather than multiple constraint-mode
# views, so grouping happens once rather than per analysis view.
_COST_GROUP_TCL = (
    "group_path -name in2out -from [all_inputs] -to [all_outputs]\n"
    "    if {[sizeof_collection [all_registers]] > 0} {\n"
    "        group_path -name in2reg -from [all_inputs] -to [all_registers]\n"
    "        group_path -name reg2out -from [all_registers] -to [all_outputs]\n"
    "        group_path -name reg2reg -from [all_registers] -to [all_registers]\n"
    "    }"
)


def _genus_set_db_overrides(context: ResolvedContext) -> tuple[tuple[str, Any], ...]:
    """Return ordered, validated set_db overrides from backend.cadence-flowtool.genus."""
    overrides = context.backend_overrides.get("cadence-flowtool", {})
    if not isinstance(overrides, Mapping):
        raise ValueError("backend.cadence-flowtool must be a mapping")
    unknown = set(overrides) - _ALLOWED_CADENCE_FLOWTOOL_OVERRIDES
    if unknown:
        raise ValueError(f"unsupported backend.cadence-flowtool override: {sorted(unknown)[0]}")
    genus = overrides.get("genus", {})
    if not isinstance(genus, Mapping):
        raise ValueError("backend.cadence-flowtool.genus must be a mapping")
    unknown = set(genus) - _ALLOWED_GENUS_OVERRIDES
    if unknown:
        raise ValueError(f"unsupported backend.cadence-flowtool.genus override: {sorted(unknown)[0]}")
    set_db = genus.get("set_db", {})
    if not isinstance(set_db, Mapping):
        raise ValueError("backend.cadence-flowtool.genus.set_db must be a mapping")
    return tuple(sorted(set_db.items()))


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
    genus = executable_lookup("genus")
    checks.append(GenusValidation("genus", genus is not None, genus or "unavailable"))
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
    context: ResolvedContext, destination: Path, *, interactive: bool = False
) -> GenusInputs:
    """Write deterministic Genus scripts and a provenance manifest."""
    if not context.sources:
        raise ValueError("Cadence Genus preparation requires ordered resolved sources")
    if not context.design_top:
        raise ValueError("Cadence Genus preparation requires design.top")
    synthesis_stages = _resolve_synthesis_stages(context)
    genus_vhdl_standard = _normalize_vhdl_standard(context.vhdl_standard)
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "reports").mkdir(exist_ok=True)
    (destination / "outputs").mkdir(exist_ok=True)
    source_script = destination / "sources.tcl"
    technology_script = destination / "technology.tcl" if context.technology else None
    genus_overrides = _genus_set_db_overrides(context)
    overrides_script = destination / "overrides.tcl" if genus_overrides else None
    run_script = destination / "run.tcl"
    manifest = destination / "genus-inputs.yaml"
    constraints = destination / "constraints.sdc"
    package_defines = tuple(str(value) for value in context.defines)
    backend_defines = tuple(GENUS_REQUIRED_DEFINES)
    effective_defines = _effective_genus_defines(context)

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
    steps: list[tuple[str, str]] = []
    if effective_threads is not None:
        steps.append(("Configuring resources", f"set_db max_cpus_per_server {effective_threads}"))
    if technology_script is not None:
        steps.append(("Loading technology", f"source {_tcl_quote(str(technology_script))}"))
    if overrides_script is not None:
        steps.append(("Applying overrides", f"source {_tcl_quote(str(overrides_script))}"))
    steps.append(("Reading sources", f"source {_tcl_quote(str(source_script))}"))
    steps.append(("Elaborating design", f"elaborate {context.design_top}"))
    steps.append(("Reading constraints", f"read_sdc {_tcl_quote(str(constraints))}"))

    dont_use_cells = context.technology.dont_use_cells if context.technology else ()
    if synthesis_stages:
        if dont_use_cells:
            steps.append(("Applying dont-use cells", _dont_use_tcl(dont_use_cells)))
        steps.append(("Grouping synthesis cost paths", _COST_GROUP_TCL))
        for stage in synthesis_stages:
            steps.append((_SYNTHESIS_STAGE_TITLES[stage], stage))

    steps.append(("Checking design", "check_design -unresolved"))
    report_lines = ["report_hierarchy > reports/hierarchy.rpt", "report_messages > reports/messages.rpt"]
    netlist_relative: str | None = None
    if synthesis_stages:
        report_lines.append("report_area > reports/area.rpt")
        suffix = _SYNTHESIS_STAGE_NETLIST_SUFFIX[synthesis_stages[-1]]
        netlist_relative = f"outputs/{context.design_name}.{suffix}.v"
        report_lines.append(f"write_hdl > {netlist_relative}")
    steps.append(("Writing reports", "\n    ".join(report_lines)))

    # Interactive runs stay at Genus's own prompt instead of exiting, so a
    # failure -- or simply the end of the script -- hands the tool's CLI
    # back for inspection; the caller types `exit` when done. Batch runs
    # (the default) always exit so automation gets a clean process status.
    run_operations = "".join(
        f"    wolf_step {_tcl_quote(title)}\n    {operation}\n" for title, operation in steps
    )
    failure_exit = "" if interactive else "    exit 1\n"
    success_exit = "" if interactive else "exit 0\n"
    run_script.write_text(
        "# Generated by WOLF; execution is intentionally separate from preparation.\n"
        + _WOLF_TCL_PRESENTATION
        + "# Every operation is inside one catch so Genus cannot mask a Tcl error.\n"
        "if {[catch {\n"
        + run_operations
        + "} error options]} {\n"
        "    puts stderr \"WOLF Genus failure: $error\"\n"
        "    if {[dict exists $options -errorinfo]} { puts stderr [dict get $options -errorinfo] }\n"
        "    if {[dict exists $options -errorcode]} { puts stderr \"ErrorCode: [dict get $options -errorcode]\" }\n"
        + failure_exit
        + "}\n"
        + success_exit,
        encoding="utf-8",
    )
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
            "reports": str(destination / "reports"),
            "netlist": str(destination / netlist_relative) if netlist_relative else None,
            "constraints": str(constraints),
        },
        "flow": context.flow_name or FLOW_GENUS_ELABORATION,
        "synthesis_stages": list(synthesis_stages),
        "dont_use_cells": list(dont_use_cells),
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
        destination, technology_script, overrides_script, source_script, run_script, manifest
    )


def validate_genus_or_raise(context: ResolvedContext) -> str:
    checks = validate_genus(context)
    failures = [f"{item.name}: {item.detail}" for item in checks if not item.available]
    if failures:
        raise ValueError("Cadence Genus validation failed: " + "; ".join(failures))
    return next(item.detail for item in checks if item.name == "genus")


def run_genus(
    context: ResolvedContext, *, clean: bool = False, interactive: bool = False
) -> tuple[int, Path]:
    """Allocate, prepare, freeze provenance, and execute one Genus run.

    In interactive mode Genus is never told to exit, so a run that finishes
    -- or fails -- hands its own CLI back at a prompt instead of tearing the
    process down; the caller regains control by typing ``exit`` there. Batch
    mode (the default) always exits so the process status is a reliable
    success/failure signal for automation.
    """
    genus = validate_genus_or_raise(context)
    run_directory = allocate_genus_run(context, clean=clean)
    inputs = prepare_genus_inputs(
        context, run_directory / "backend" / "cadence-genus", interactive=interactive
    )
    resolved = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
    resolved["schema"] = "wolf.resolved-run/v1"
    resolved["execution"] = {
        "executor": "native", "tool": "genus", "executable": genus,
        "working_directory": str(inputs.directory),
        "command": [genus, "-files", "run.tcl", "-log", "genus.log"],
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
            "genus_script": str(inputs.run_script),
        },
    )
    result = subprocess.run(
        [genus, "-files", "run.tcl", "-log", "genus.log"],
        cwd=inputs.directory, check=False,
    )
    return result.returncode, run_directory

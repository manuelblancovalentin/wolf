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

from wolf.context import ResolvedContext, ResolvedTechnology
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
    mmmc_script: Path | None
    overrides_script: Path | None
    source_script: Path
    flow_config_script: Path
    flow_root: Path
    setup_yaml: Path | None
    flow_yaml: Path
    manifest: Path


# Genus must parse RTL in synthesis mode.  These are backend policy, not
# package metadata, and are therefore added only to emitted Genus inputs.
GENUS_REQUIRED_DEFINES = ("SYNTHESIS",)

# Backend-native Genus attributes a run may need to override (e.g. raising
# hdl_max_memory_address_range past a generic-inference default). These are
# tool policy, not canonical WOLF semantics, so they arrive only through the
# explicit backend.cadence-flowtool escape hatch.
_ALLOWED_CADENCE_FLOWTOOL_OVERRIDES = frozenset({"genus", "flowtool", "postsyn_netlists", "inject"})
_ALLOWED_INJECT_PHASES = frozenset({"pre", "post"})
_ALLOWED_GENUS_OVERRIDES = frozenset({"set_db"})

# The institution-supplied Flowtool project descriptors this backend renders
# WOLF's resolved values into (see _flowtool_templates/_render_template).
# WOLF does not know or ship Cadence's YAML flow-descriptor schema -- these
# are the institution's own files, referenced only by path.
_ALLOWED_FLOWTOOL_OVERRIDES = frozenset({"setup_template", "flow_template"})

_SCRIPTS_DIR_RE = re.compile(r"^scripts\.(\d+)$")

# Canonical stage order -- must match the real create_flow names in
# flows/cadence-genus/common_flows.tcl exactly, since these are passed
# verbatim as Flowtool's own -from/-to flow-range arguments (see
# `_resolve_stage_range`). elaborate is no longer independently selectable:
# it is a step *inside* the syn_generic flow now (real Flowtool -from/-to
# selects by flow name, not by step name within one), matching how the
# real Stylus flow this was adapted from also only exposes
# syn_generic/syn_map/syn_opt as resumable flows.
STAGE_ORDER = ("syn_generic", "syn_map", "syn_opt")

# `flow.name` values remain supported as shorthand for the common "run
# everything through X" range -- not a separate mechanism.
FLOW_GENUS_SYN_GENERIC = "genus-syn-generic"
FLOW_GENUS_SYN_MAP = "genus-syn-map"
FLOW_GENUS_SYN_OPT = "genus-syn-opt"

_FLOW_NAME_STAGE_RANGE: Mapping[str, str] = {
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
    wins. Without one, `flow.name` is shorthand for "all stages through X";
    with neither given at all, the default is the complete synthesis flow.
    """
    if from_stage is None and to_stage is None:
        flow_name = context.flow_name or FLOW_GENUS_SYN_OPT
        try:
            return STAGE_ORDER[0], _FLOW_NAME_STAGE_RANGE[flow_name]
        except KeyError:
            raise ValueError(
                f"unsupported cadence-flowtool flow {flow_name!r}; expected one of "
                + ", ".join(sorted(_FLOW_NAME_STAGE_RANGE))
            ) from None
    from_stage = from_stage or STAGE_ORDER[0]
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
    when the environment references one *and* it actually contains Genus's
    real create_flow sequencing (common_flows.tcl) -- an environment's flow
    package may belong to a different backend entirely (e.g. flow/orfs),
    which is not this flow's root. Otherwise WOLF's own bundled default flow
    scripts are used. Either way, these are ordinary files on disk --
    readable, browsable, and never regenerated by WOLF.
    """
    package_path = context.package_paths.get("flow")
    if package_path is not None and (package_path / "common_flows.tcl").is_file():
        return package_path
    return builtin_flow_root("cadence-genus")


def _tcl_list(values: tuple[str, ...]) -> str:
    return "{" + " ".join(_tcl_quote(value) for value in values) + "}"


def _tcl_brace_list(values: tuple[str, ...]) -> str:
    """Brace-quote each element instead of double-quoting it.

    Used only for injected Tcl snippets, which may themselves be arbitrary
    Tcl (not just plain strings like paths) -- brace quoting suppresses all
    substitution, so an inline snippet containing $vars or [commands] is
    preserved literally until wolf_inject's own `uplevel` evaluates it.
    Unlike _tcl_list, this does NOT backslash-escape internal braces: Tcl's
    list parser only strips the outermost brace pair of a `{...}` element,
    so a snippet's own balanced braces (an `if {...} {...}`, a `puts
    {...}`) survive as real Tcl grouping syntax when later evaluated --
    backslash-escaping them would instead leave literal backslash-brace
    characters in the evaluated text, breaking that grouping. This requires
    each snippet's own braces to already be balanced, true for realistic
    injected Tcl and for plain file paths (no braces at all).
    """
    return "{" + " ".join("{" + value + "}" for value in values) + "}"


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


def _postsyn_netlists(context: ResolvedContext) -> tuple[str, ...]:
    """Pre-synthesized sub-block netlists genus_to_innovus reads by reference.

    For hierarchical synthesis of a repeated block (e.g. one eFPGA tile
    synthesized once and instantiated many times in the fabric): point this
    at that block's own synthesized netlist so the handoff includes it
    directly instead of every instance being re-elaborated and re-optimized.
    """
    values = _cadence_flowtool_overrides(context).get("postsyn_netlists", [])
    if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
        raise ValueError("backend.cadence-flowtool.postsyn_netlists must be a list of paths")
    return tuple(values)


def _inject_snippets(context: ResolvedContext) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Validate backend.cadence-flowtool.inject.<step>.<pre|post> -> [snippets].

    Each snippet is either a file path (sourced) or inline Tcl (eval'd) --
    see presentation.tcl's wolf_inject. Returns a flat, ordered sequence of
    (step, phase, snippets) ready to become `wolf_inject(step,phase)` array
    entries in flow-config.tcl.
    """
    inject = _cadence_flowtool_overrides(context).get("inject", {})
    if not isinstance(inject, Mapping):
        raise ValueError("backend.cadence-flowtool.inject must be a mapping")
    result = []
    for step, phases in sorted(inject.items()):
        if not isinstance(step, str) or not step:
            raise ValueError("backend.cadence-flowtool.inject keys must be step names")
        if not isinstance(phases, Mapping):
            raise ValueError(f"backend.cadence-flowtool.inject.{step} must be a mapping")
        unknown = set(phases) - _ALLOWED_INJECT_PHASES
        if unknown:
            raise ValueError(f"backend.cadence-flowtool.inject.{step} must only set pre/post")
        for phase, snippets in sorted(phases.items()):
            if not isinstance(snippets, list) or not all(
                isinstance(snippet, str) and snippet for snippet in snippets
            ):
                raise ValueError(
                    f"backend.cadence-flowtool.inject.{step}.{phase} must be a list of strings"
                )
            if snippets:
                result.append((step, phase, tuple(snippets)))
    return tuple(result)


def _flowtool_templates(context: ResolvedContext, flow_root: Path) -> tuple[Optional[Path], Path]:
    """Return the (setup_template, flow_template) paths Flowtool should render.

    WOLF ships its own generic flow_template (flow_root/flow.template.yaml)
    that only lists this flow's real Tcl scripts -- no setup_template is
    needed alongside it, since this flow reads its resolved values directly
    out of flow-config.tcl rather than via get_flow_config/design_yaml (see
    flow.template.yaml's header). A project can still override either or
    both via backend.cadence-flowtool.flowtool.{setup_template,flow_template}
    -- e.g. to supply a get_flow_config-style setup_template its own
    extension Tcl relies on, or an institution's existing Flowtool project
    descriptors -- the same escape hatch used for set_db overrides.
    """
    flowtool = _cadence_flowtool_overrides(context).get("flowtool", {})
    if not isinstance(flowtool, Mapping):
        raise ValueError("backend.cadence-flowtool.flowtool must be a mapping")
    if not flowtool:
        return None, flow_root / "flow.template.yaml"
    unknown = set(flowtool) - _ALLOWED_FLOWTOOL_OVERRIDES
    if unknown:
        raise ValueError(f"unsupported backend.cadence-flowtool.flowtool override: {sorted(unknown)[0]}")
    missing = sorted(_ALLOWED_FLOWTOOL_OVERRIDES - set(flowtool))
    if missing:
        raise ValueError(
            "backend.cadence-flowtool.flowtool requires " + " and ".join(missing)
            + " when overriding either -- omit both to use WOLF's bundled flow_template"
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


_SETUP_YAML_TOKEN_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _concatenate_setup_fragments(primary: Path, *fragments: Path) -> str:
    """Concatenate a Flowtool setup.yaml's primary (institution-supplied)
    template with any number of additional fragments -- a PDK's own
    technology.setup_yaml_fragment, say -- mirroring the legacy
    `cp primary; tail -n +3 fragment >> ...` mechanism in
    bin/backends/cadence-flowtool.sh: a fragment's own first two lines
    (the `%TAG !.../---` document header every one of these templates
    starts with) are dropped, so concatenating several never produces
    more than the one document-start marker the result actually needs.
    """
    text = primary.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    for fragment in fragments:
        lines = fragment.read_text(encoding="utf-8").splitlines(keepends=True)
        text += "".join(lines[2:])
    return text


def _setup_yaml_tokens(
    context: ResolvedContext, destination: Path, scripts_directory: Path, constraints: Path,
) -> dict[str, str]:
    """The flat ${TOKEN} values WOLF itself can resolve for a Flowtool
    setup.yaml, matching bin/backends/cadence-flowtool.sh's own sed
    substitution map exactly (DESIGN_NAME, CONSTRAINTS_FILES, ...) so an
    institution template authored against that legacy mechanism needs no
    changes to work here instead. A token with no WOLF equivalent (an
    institution-specific directory convention, say) is deliberately not
    included here -- see _render_setup_yaml's technology.generic fallback
    and its error for anything still unresolved after that.

    TRACKS/VTHS render as yaml lists (even for a single value), not bare
    scalars -- confirmed real usage: a real legacy setup.yaml's own
    `vths: ${VTHS}` (VTHS a bash array) is consumed by synthesis.tcl's
    `foreach trk [get_flow_config tracks] { foreach vth [get_flow_config
    vths] { ... } }`, unioning every (track, vth) pair's library/lef
    files -- so a run mixing lvt+rvt library sets needs the real list,
    not a single name.
    """
    technology = context.technology
    tokens = {
        "DESIGN_NAME": context.design_name,
        "CONSTRAINTS_FILES": yaml.safe_dump([str(constraints)], default_flow_style=True).strip(),
        "WORKSPACE_DIR": str(context.workspace_root),
        "SCRIPTS_DIR": str(scripts_directory),
        "RUNDIR": str(destination),
    }
    if context.floorplan_def:
        tokens["FLOORPLAN_FILE"] = str(context.floorplan_def)
    if technology is not None:
        tokens["PDK_DIR"] = str(technology.root)
        if technology.metal_stack:
            tokens["METAL_STACK"] = technology.metal_stack
        selected_tracks = technology.selected_tracks or (
            (technology.track,) if technology.track else ()
        )
        selected_vths = technology.selected_vths or ((technology.vth,) if technology.vth else ())
        if selected_tracks:
            tokens["TRACKS"] = yaml.safe_dump(list(selected_tracks), default_flow_style=True).strip()
        if selected_vths:
            tokens["VTHS"] = yaml.safe_dump(list(selected_vths), default_flow_style=True).strip()
    return tokens


def _catalog_document(technology: Optional[ResolvedTechnology]) -> dict:
    """The get_flow_config-indexed catalog keys injected into every run's
    setup.yaml, built from the PDK's full track/vth/corner catalog (see
    wolf.environment's technology.catalog_library_sets/catalog_lef_files/
    catalog_gds_files). Key names and nesting are fixed, confirmed
    against a real legacy synthesis.tcl's own get_flow_config calls --
    not WOLF's invention:
      get_flow_config library_sets $corner library_files $track $vth
      get_flow_config init_physical_files lef_files $track $vth
      get_flow_config std_cell_GDS_files $track $vth
    Neither lef nor gds indexes by metal_stack -- WOLF already resolved
    that to one value while building the catalog (see
    wolf.environment._build_catalog), the same way DESIGN_NAME is one
    resolved scalar rather than every design WOLF has ever heard of.
    verilog/spice/qrc_techfiles have no confirmed get_flow_config access
    pattern yet, so they're deliberately not injected here.
    """
    if technology is None:
        return {}
    library_sets: dict[str, Any] = {}
    for entry in technology.catalog_library_sets:
        corner = library_sets.setdefault(entry.corner, {"library_files": {}})
        corner["library_files"].setdefault(entry.track, {})[entry.vth] = [
            str(path) for path in entry.libraries
        ]
    lef_files: dict[str, Any] = {}
    for entry in technology.catalog_lef_files:
        lef_files.setdefault(entry.track, {})[entry.vth] = [str(path) for path in entry.files]
    gds_files: dict[str, Any] = {}
    for entry in technology.catalog_gds_files:
        gds_files.setdefault(entry.track, {})[entry.vth] = [str(path) for path in entry.files]
    document: dict[str, Any] = {}
    if library_sets:
        document["library_sets"] = library_sets
    if lef_files:
        document["init_physical_files"] = {"lef_files": lef_files}
    if gds_files:
        document["std_cell_GDS_files"] = gds_files
    return document


def _render_setup_yaml(
    setup_template: Path, technology: Optional[ResolvedTechnology], tokens: Mapping[str, str],
) -> str:
    """Render one run's Flowtool setup.yaml: concatenate the institution's
    primary template with the PDK's own setup_yaml_fragment (if declared --
    see wolf.environment's technology.setup_yaml_fragment), substitute
    every ${TOKEN} WOLF can resolve (see _setup_yaml_tokens), falling back
    to technology.generic for anything else a fragment references -- an
    institution-specific directory root with no general WOLF model, say
    -- then inject the PDK's full track/vth/corner catalog (see
    _catalog_document) as a few fixed top-level keys. Any ${TOKEN} still
    unresolved after both substitution passes is a real error: a run's
    actual setup.yaml should never be written with a literal placeholder
    still sitting in it.
    """
    fragments = (technology.setup_yaml_fragment,) if technology and technology.setup_yaml_fragment else ()
    text = _concatenate_setup_fragments(setup_template, *fragments)
    for key, value in tokens.items():
        text = text.replace("${" + key + "}", value)
    generic = technology.generic if technology else {}

    def substitute_from_generic(match: "re.Match[str]") -> str:
        key = match.group(1)
        return str(generic[key]) if key in generic else match.group(0)
    text = _SETUP_YAML_TOKEN_RE.sub(substitute_from_generic, text)
    leftover = sorted(set(_SETUP_YAML_TOKEN_RE.findall(text)))
    if leftover:
        raise ValueError(
            "setup.yaml references undefined token(s): " + ", ".join(leftover)
            + " -- define them under technology.generic in the pdk manifest, or add support "
            "for them in wolf.backend.cadence_genus._setup_yaml_tokens"
        )
    catalog = _catalog_document(technology)
    if catalog:
        document = yaml.safe_load(text)
        if not isinstance(document, dict):
            raise ValueError(f"rendered setup.yaml is not a yaml mapping: {setup_template}")
        document.update(catalog)
        text = yaml.safe_dump(document, sort_keys=False)
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
    """Allocate a numbered run (<design>.<N>) -- confirmed real legacy
    convention: every run is numbered starting at .1, there is never an
    unnumbered run alongside them. Without --clean, continues the latest
    already-allocated numbered run (so an earlier invocation's Flowtool
    checkpoints are still there for a later -from); --clean, or no
    existing numbered run at all, allocates a fresh one. Read-only: only
    computes a path, by globbing what's already on disk -- never creates
    anything itself, safe to call from `wolf run --plan` too.
    """
    base = context.workspace_root / context.design_name / f"{context.design_name}.{context.process}"
    existing = sorted(
        int(p.name.rsplit(".", 1)[-1])
        for p in base.glob(f"{context.design_name}.*")
        if p.is_dir() and p.name.rsplit(".", 1)[-1].isdigit()
    )
    if not clean and existing:
        return base / f"{context.design_name}.{existing[-1]}"
    index = existing[-1] + 1 if existing else 1
    return base / f"{context.design_name}.{index}"


def _period_ns(period_ps: Any) -> str:
    value = Decimal(str(period_ps)) / Decimal("1000")
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


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
        setup_template, flow_template = _flowtool_templates(context, _flow_root(context))
        detail = f"{setup_template}, {flow_template}" if setup_template else str(flow_template)
        checks.append(GenusValidation("flowtool templates", True, detail))
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


# Must match prepare_genus_inputs' own _snapshot_scripts call -- the real
# step-definition files a run actually executes.
_FLOW_SCRIPT_NAMES = (
    "presentation.tcl", "common_flows.tcl", "common_steps.tcl", "synthesis.tcl",
    "floorplanning.tcl", "cts.tcl", "route.tcl", "postroute.tcl",
)


def bundled_flow_digest() -> str:
    """A short content hash identifying exactly which revision of WOLF's
    own bundled flow Tcl (flows/cadence-genus/*.tcl) a run actually
    executes -- "default" alone doesn't say which one. Hashing the real
    file content, not a git commit, means it's accurate even for an
    editable/dev install with uncommitted local changes, which is
    exactly the case this was built under."""
    flow_root = builtin_flow_root("cadence-genus")
    return _digest([flow_root / name for name in _FLOW_SCRIPT_NAMES])[:12]


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

    - the flow *scripts* (presentation.tcl, common_flows.tcl,
      common_steps.tcl, synthesis.tcl, floorplanning.tcl, cts.tcl, route.tcl,
      postroute.tcl) -- the real, version-controlled step definitions that
      decide what each stage does. These land in a deduplicated, numbered
      scripts.<N> snapshot (with a scripts.latest symlink), mirroring the
      legacy Bash runner's own PROCESS_SCRIPTS snapshot mechanism, so
      history of exactly which flow logic a run used is preserved and
      unchanged runs don't re-snapshot;
    - the resolved *values* this run supplies to them (sources.tcl,
      technology.tcl, overrides.tcl, constraints.sdc, flow-config.tcl, and
      the flow.yaml Flowtool project descriptor -- WOLF's own bundled
      flow.template.yaml by default, or an institution-/project-supplied
      override, rendered with those values) -- written directly, fresh
      every call, same as before.
    """
    if not context.sources:
        raise ValueError("Cadence Genus preparation requires ordered resolved sources")
    if not context.design_top:
        raise ValueError("Cadence Genus preparation requires design.top")
    resolved_from_stage, resolved_to_stage = _resolve_stage_range(context, from_stage, to_stage)
    synthesis_stages = STAGE_ORDER[
        STAGE_ORDER.index(resolved_from_stage):STAGE_ORDER.index(resolved_to_stage) + 1
    ]
    genus_vhdl_standard = _normalize_vhdl_standard(context.vhdl_standard)
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    reports_directory = destination / "reports"
    outputs_directory = destination / "outputs"
    reports_directory.mkdir(exist_ok=True)
    outputs_directory.mkdir(exist_ok=True)
    source_script = destination / "sources.tcl"
    flow_root = _flow_root(context)
    setup_template, flow_template = _flowtool_templates(context, flow_root)
    # A Flowtool-native setup_template is the point where a project's real
    # flow reads library/corner data back via get_flow_config out of
    # setup.yaml (see _render_setup_yaml) -- WOLF's own mmmc.tcl/
    # technology.tcl generation (plain Tcl variables in flow-config.tcl) is
    # for the bundled default flow only, never alongside a real one.
    generate_wolf_technology_scripts = setup_template is None
    has_corners = bool(context.technology and context.technology.timing_corners)
    technology_script = (
        destination / "technology.tcl"
        if (generate_wolf_technology_scripts and context.technology and not has_corners) else None
    )
    mmmc_script = (
        destination / "mmmc.tcl" if (generate_wolf_technology_scripts and has_corners) else None
    )
    genus_overrides = _genus_set_db_overrides(context)
    overrides_script = destination / "overrides.tcl" if genus_overrides else None
    flow_config_script = destination / "flow-config.tcl"
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

    if mmmc_script is not None:
        mmmc_lines = []
        for corner in context.technology.timing_corners:
            name = _tcl_quote(corner.name)
            libraries = _tcl_list(tuple(str(path) for path in corner.libraries))
            mmmc_lines.append(f"create_library_set -name {name} -timing {libraries}")
            mmmc_lines.append(f"create_timing_condition -name {name} -library_sets {{{name}}}")
            if corner.qrc_tech_file is not None:
                qrc = _tcl_quote(str(corner.qrc_tech_file))
                mmmc_lines.append(f"create_rc_corner -name {name} -qrc_tech_file {qrc}")
                mmmc_lines.append(
                    f"create_delay_corner -name {name} -timing_condition {name} -rc_corner {name}"
                )
            else:
                mmmc_lines.append(f"create_delay_corner -name {name} -timing_condition {name}")
            mmmc_lines.append(
                f"create_constraint_mode -name {name} -sdc_files {_tcl_list((str(constraints),))}"
            )
            mmmc_lines.append(
                f"create_analysis_view -name {name} -constraint_mode {name} -delay_corner {name}"
            )
        all_names = _tcl_list(tuple(corner.name for corner in context.technology.timing_corners))
        mmmc_lines.append(f"set_analysis_view -setup {all_names} -hold {all_names}")
        mmmc_script.write_text(
            "# Generated by WOLF; package-resolved multi-corner Genus MMMC inputs.\n"
            "#\n"
            "# Every declared corner is active for both setup and hold checks --\n"
            "# WOLF does not infer which corner is electrically slow/fast from its\n"
            "# name or voltage, so this is the conservative default: timing is\n"
            "# evaluated against every declared corner for both checks.\n"
            + "\n".join(mmmc_lines) + "\n",
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
    constraint_lines = [
        f"create_clock -name {clock.name} -period {_period_ns(clock.period_ps)} [get_ports {clock.port}]"
        for clock in context.clocks
    ]
    # Extra SDC content is appended after the generated clocks, verbatim and
    # unparsed -- WOLF stays ignorant of what timing exceptions mean, the
    # same boundary as the env/inject passthroughs.
    for extra_file in context.constraint_files:
        if not extra_file.is_file():
            raise ValueError(f"constraints.files entry does not exist: {extra_file}")
        constraint_lines.append(f"# From {extra_file}")
        constraint_lines.append(extra_file.read_text(encoding="utf-8").rstrip("\n"))
    if context.constraint_lines:
        constraint_lines.append("# Inline constraints.lines")
        constraint_lines.extend(context.constraint_lines)
    constraints.write_text(
        "\n".join(constraint_lines) + ("\n" if constraint_lines else ""), encoding="utf-8"
    )

    effective_threads = _effective_genus_threads(context)
    dont_use_cells = context.technology.dont_use_cells if context.technology else ()
    technology_lefs = context.technology.technology_lefs if context.technology else ()
    cell_lefs = context.technology.cell_lefs if context.technology else ()
    handoff_directory = destination / "handoff"
    postsyn_netlists = _postsyn_netlists(context)
    inject_snippets = _inject_snippets(context)

    # The flow *scripts* -- the real step definitions -- get a deduplicated,
    # numbered snapshot. Their dedup digest covers only these files, so
    # unrelated per-run values never force a new snapshot.
    scripts_directory = _snapshot_scripts(destination, {
        name: (flow_root / name).read_text(encoding="utf-8")
        for name in (
            "presentation.tcl", "common_flows.tcl", "common_steps.tcl", "synthesis.tcl",
            "floorplanning.tcl", "cts.tcl", "route.tcl", "postroute.tcl",
        )
    })

    # Resolved, run-specific *values* only -- every step this run performs
    # is defined in scripts_directory/{common_flows,common_steps,synthesis}.tcl
    # (see synthesis.tcl's header for what each name below configures),
    # never here. A project can point flow.package at its own `wolf flow
    # init` clone of flow_root instead of the bundled default.
    inject_lines = "".join(
        f"set wolf_inject({step},{phase}) {_tcl_brace_list(snippets)}\n"
        for step, phase, snippets in inject_snippets
    )
    flow_config_script.write_text(
        "# Generated by WOLF; resolved values consumed by synthesis.tcl/common_steps.tcl.\n"
        f"set wolf_design_name {_tcl_quote(context.design_name)}\n"
        f"set wolf_design_top {_tcl_quote(context.design_top)}\n"
        f"set wolf_reports_dir {_tcl_quote(str(reports_directory))}\n"
        f"set wolf_outputs_dir {_tcl_quote(str(outputs_directory))}\n"
        f"set wolf_handoff_dir {_tcl_quote(str(handoff_directory))}\n"
        f"set wolf_postsyn_netlists {_tcl_list(postsyn_netlists)}\n"
        f"set wolf_max_cpus_per_server "
        f"{effective_threads if effective_threads is not None else '\"\"'}\n"
        f"set wolf_technology_script "
        f"{_tcl_quote(str(technology_script)) if technology_script else '\"\"'}\n"
        f"set wolf_mmmc_script "
        f"{_tcl_quote(str(mmmc_script)) if mmmc_script else '\"\"'}\n"
        f"set wolf_overrides_script "
        f"{_tcl_quote(str(overrides_script)) if overrides_script else '\"\"'}\n"
        f"set wolf_sources_script {_tcl_quote(str(source_script))}\n"
        f"set wolf_constraints_file {_tcl_quote(str(constraints))}\n"
        f"set wolf_dont_use_cells {_tcl_list(dont_use_cells)}\n"
        f"set wolf_technology_lefs {_tcl_list(tuple(str(path) for path in technology_lefs))}\n"
        f"set wolf_cell_lefs {_tcl_list(tuple(str(path) for path in cell_lefs))}\n"
        f"set wolf_floorplan_def "
        f"{_tcl_quote(str(context.floorplan_def)) if context.floorplan_def else '\"\"'}\n"
        f"array set wolf_inject {{}}\n"
        f"{inject_lines}",
        encoding="utf-8",
    )

    # Render the Flowtool project descriptor(s). WOLF's own bundled
    # flow_template only ever uses WOLF_SCRIPTS_DIR/WOLF_FLOW_CONFIG_SCRIPT
    # below; an institution- or project-supplied override may reference any
    # of the others, exactly as it already does for the legacy Bash runner.
    placeholders = {
        "WOLF_DESIGN_NAME": context.design_name,
        "WOLF_DESIGN_TOP": context.design_top,
        "WOLF_SCRIPTS_DIR": str(scripts_directory),
        "WOLF_FLOW_CONFIG_SCRIPT": str(flow_config_script),
        "WOLF_WORKSPACE_DIR": str(context.workspace_root),
        "WOLF_RUN_DIRECTORY": str(destination),
        # destination's own name, not context.run_tag -- the run
        # directory is always named after the real allocated run tag
        # (<design>.<N> for a Genus run; see allocate_genus_run),
        # matching the -run_tag flag run_genus itself passes to Flowtool.
        "WOLF_RUN_TAG": destination.name,
        "WOLF_REPORTS_DIR": str(reports_directory),
        "WOLF_OUTPUTS_DIR": str(outputs_directory),
    }
    flow_yaml = destination / f"flow.{context.design_name}.yaml"
    if setup_template is not None:
        setup_yaml = destination / f"setup.{context.design_name}.yaml"
        tokens = _setup_yaml_tokens(context, destination, scripts_directory, constraints)
        setup_yaml.write_text(
            _render_setup_yaml(setup_template, context.technology, tokens), encoding="utf-8",
        )
        placeholders = {**placeholders, "WOLF_SETUP_YAML": str(setup_yaml)}
    else:
        setup_yaml = None
    flow_yaml.write_text(_render_template(flow_template, placeholders), encoding="utf-8")

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
        "constraints": {
            "clocks": [
                {"name": clock.name, "port": clock.port, "period_ps": clock.period_ps}
                for clock in context.clocks
            ],
            "files": [str(path) for path in context.constraint_files],
            "lines": list(context.constraint_lines),
        },
        "outputs": {
            "reports": str(reports_directory),
            "netlist": str(destination / netlist_relative) if netlist_relative else None,
            "constraints": str(constraints),
        },
        "flow": context.flow_name or FLOW_GENUS_SYN_OPT,
        "flow_root": str(flow_root),
        "scripts_directory": str(scripts_directory),
        "setup_yaml": str(setup_yaml) if setup_yaml else None,
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
            "track": context.technology.track,
            "vth": context.technology.vth,
            "selected_tracks": list(context.technology.selected_tracks),
            "selected_vths": list(context.technology.selected_vths),
            "metal_stack": context.technology.metal_stack,
            "timing_corner": context.technology.timing_corner,
            "timing_libraries": [str(path) for path in context.technology.timing_libraries],
            "timing_corners": [
                {
                    "name": corner.name,
                    "libraries": [str(path) for path in corner.libraries],
                    "qrc_tech_file": str(corner.qrc_tech_file) if corner.qrc_tech_file else None,
                    "format": corner.format,
                }
                for corner in context.technology.timing_corners
            ],
            "technology_lefs": [str(path) for path in context.technology.technology_lefs],
            "cell_lefs": [str(path) for path in context.technology.cell_lefs],
            "rc_files": [str(path) for path in context.technology.rc_files],
            "gds_files": [str(path) for path in context.technology.gds_files],
            "verilog_models": [str(path) for path in context.technology.verilog_models],
            "spice_models": [str(path) for path in context.technology.spice_models],
            "qrc_techfiles": [str(path) for path in context.technology.qrc_techfiles],
            "generic": dict(context.technology.generic),
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
        destination, scripts_directory, technology_script, mmmc_script, overrides_script,
        source_script, flow_config_script, flow_root, setup_yaml, flow_yaml, manifest,
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
    flows/cadence-genus/common_steps.tcl is meaningful: Flowtool's own engine saves
    each step's checkpoint and, on a later -from, loads the nearest
    preceding one automatically -- WOLF does not reimplement that itself.
    A run without -c/--clean reuses the same numbered run directory, so an
    earlier invocation's checkpoints are still there for a later -from.
    """
    flowtool = validate_genus_or_raise(context)
    run_directory = allocate_genus_run(context, clean=clean)
    inputs = prepare_genus_inputs(
        context, run_directory, interactive=interactive,
        from_stage=from_stage, to_stage=to_stage,
    )
    resolved = yaml.safe_load(inputs.manifest.read_text(encoding="utf-8"))
    resolved["schema"] = "wolf.resolved-run/v1"
    # The real, numbered run tag (<design>.<N>, from allocate_genus_run) --
    # not context.run_tag, which only ever defaults to the bare design
    # name and would otherwise collide every run doesn't explicitly pass
    # --runtag.
    run_tag = run_directory.name
    process_directory = str(
        context.workspace_root / context.design_name / f"{context.design_name}.{context.process}"
    )
    # One flowtool invocation per stage, not one spanning the whole
    # range: Flowtool loses -interactive (and would lose any other
    # per-invocation flag) past the first stage of a multi-stage single
    # call. The real legacy runner (bin/backends/cadence-flowtool.sh's
    # _wolf_backend_run_stage, looped by bin/backend.sh) always ran one
    # flowtool process per stage with -from stage -to stage, passing the
    # full original argument set to every one of them; mirror that here
    # rather than the single wide-range call this used to make.
    stages: list[str] = list(resolved["synthesis_stages"]) or [resolved["from_stage"]]
    commands: list[list[str]] = []
    for stage in stages:
        command = [
            flowtool, "-files", str(inputs.flow_yaml), "-run_tag", run_tag,
            "-from", stage, "-to", stage,
            "-directory", process_directory,
            "-log", str(inputs.directory / f"flowtool.{stage}.log"),
        ]
        if interactive:
            command.append("-interactive")
        commands.append(command)
    resolved["execution"] = {
        "executor": "native", "tool": "flowtool", "executable": flowtool,
        "working_directory": str(inputs.directory),
        "commands": commands,
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
        # Continuing the same run with a later -from/-to is the whole
        # point of not passing --clean (see this function's own
        # docstring) -- these are exactly the fields that trivially
        # differ just from picking a different stage range or
        # re-invoking, not from the run actually being a different one.
        volatile_keys=("from_stage", "to_stage", "synthesis_stages", "outputs", "execution"),
        generated_directory=inputs.directory,
        generated_files={
            **({"genus_technology": str(inputs.technology_script)} if inputs.technology_script else {}),
            **({"genus_mmmc": str(inputs.mmmc_script)} if inputs.mmmc_script else {}),
            **({"genus_overrides": str(inputs.overrides_script)} if inputs.overrides_script else {}),
            "genus_sources": str(inputs.source_script),
            "genus_constraints": str(inputs.directory / "constraints.sdc"),
            "genus_flow_config": str(inputs.flow_config_script),
            **({"flowtool_setup_yaml": str(inputs.setup_yaml)} if inputs.setup_yaml else {}),
            "flowtool_flow_yaml": str(inputs.flow_yaml),
            "flowtool_scripts_directory": str(inputs.scripts_directory),
        },
    )
    returncode = 0
    for command in commands:
        result = subprocess.run(command, cwd=inputs.directory, check=False)
        returncode = result.returncode
        if returncode != 0:
            break  # Matches the legacy runner: stop the sequence at the first failing stage.
    return returncode, run_directory

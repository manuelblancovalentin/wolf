"""Generic mixed-language Cadence Genus input preparation.

This module consumes resolved WOLF source metadata only.  It deliberately has
no knowledge of ESP, FABulous, or any generator-specific conventions.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
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
# syn_generic/syn_map/syn_opt/floorplan/prects/cts/postcts/route/postroute
# as resumable flows -- the exact same split the reference flow's own
# `synthesis`/`implementation` top-level flows draw.
#
# Both sections run through the exact same mechanism (run_genus allocates
# one numbered run and invokes the real `flowtool` binary once per stage,
# never `genus`/`innovus` directly) -- there is no separate "Innovus
# path"; a stage name here is just which named Flowtool flow this
# invocation selects.
SYNTHESIS_STAGES = ("syn_generic", "syn_map", "syn_opt")
IMPLEMENTATION_STAGES = ("floorplan", "prects", "cts", "postcts", "route", "postroute")
STAGE_ORDER = SYNTHESIS_STAGES + IMPLEMENTATION_STAGES

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
    wins. Without one, `flow.name` is recognized as shorthand for "all
    stages through X" only when it's one of the three known
    genus-syn-*/FLOW_GENUS_SYN_* values -- `flow.name` is also just a
    plain label in every other case (the bundled default flow's own
    literal "default", or a real installed flow package's own manifest
    name, e.g. "orfs" or an institution's own flow name), and must never
    block the sensible default range just because it doesn't happen to
    match one of the three shorthands. With neither given and no
    recognized shorthand, the default is the complete synthesis flow
    (unchanged: adding IMPLEMENTATION_STAGES to STAGE_ORDER must not make
    an existing bare `wolf run`/`-from syn_map` suddenly run all the way
    through postroute).

    A single explicit endpoint fills the other end with the *same
    section's* boundary, not the global STAGE_ORDER edge -- `-from
    syn_map` alone still means "through syn_opt", and `-from floorplan`
    alone means "through postroute", not one default blindly spanning
    both. Giving both endpoints explicitly may still cross sections (e.g.
    `-from syn_generic -to postroute` for the whole `block`), matching the
    reference flow's own `block` flow spanning `synthesis`+`implementation`.
    """
    if from_stage is None and to_stage is None:
        flow_name = context.flow_name or FLOW_GENUS_SYN_OPT
        return STAGE_ORDER[0], _FLOW_NAME_STAGE_RANGE.get(flow_name, SYNTHESIS_STAGES[-1])
    if from_stage is None:
        from_stage = (
            SYNTHESIS_STAGES[0] if to_stage in SYNTHESIS_STAGES else IMPLEMENTATION_STAGES[0]
        )
    if to_stage is None:
        to_stage = (
            SYNTHESIS_STAGES[-1] if from_stage in SYNTHESIS_STAGES else IMPLEMENTATION_STAGES[-1]
        )
    for stage in (from_stage, to_stage):
        if stage not in STAGE_ORDER:
            raise ValueError(f"unsupported stage {stage!r}; expected one of {STAGE_ORDER}")
    if STAGE_ORDER.index(from_stage) > STAGE_ORDER.index(to_stage):
        raise ValueError(f"-from {from_stage!r} comes after -to {to_stage!r}")
    return from_stage, to_stage


def _requires_physical_views(from_stage: str, to_stage: str) -> bool:
    """Any stage from floorplan onward needs LEF/RC before Flowtool is
    even invoked -- Innovus cannot do anything physical without them,
    unlike Genus's synthesis stages where physical views are optional."""
    start = STAGE_ORDER.index(from_stage)
    end = STAGE_ORDER.index(to_stage)
    return any(stage in IMPLEMENTATION_STAGES for stage in STAGE_ORDER[start:end + 1])


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


def _update_latest_run_link(context: ResolvedContext, run_directory: Path) -> None:
    """Maintain <environment_directory>/run.latest.d -- the same symlink
    convention the legacy shell runner already writes and `wolf status`
    already reads (_latest_for_environment), so `wolf status --environment
    NAME` finds a declarative-v1 Genus run without any new resolution
    path. Only in run_genus (real execution), never allocate_genus_run
    itself, which stays read-only/safe for `wolf run --plan`. Best-effort:
    an environment with no environment_directory (CLI-only context) or a
    filesystem that rejects symlinks simply doesn't get one.
    """
    if context.environment_directory is None:
        return
    link = context.environment_directory / "run.latest.d"
    try:
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(run_directory, target_is_directory=True)
    except OSError:
        pass


def _tcl_list_elements(text: str) -> list[str]:
    """Split one line of real Tcl list/dict syntax into its top-level
    elements, respecting {...} brace-grouping (an element containing
    whitespace, or itself a nested list/dict, is wrapped in one brace
    pair -- standard Tcl list syntax, not guessed: this is exactly the
    format flow.status, flow.metrics, and report_flow all actually use)."""
    elements: list[str] = []
    depth = 0
    start = 0
    current: list[str] = []
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = index + 1
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                elements.append(text[start:index])
        elif depth == 0:
            if char.isspace():
                if current:
                    elements.append("".join(current))
                    current = []
            else:
                current.append(char)
    if current:
        elements.append("".join(current))
    return elements


def _tcl_dict(text: str) -> dict[str, str]:
    """One line/element of Tcl dict syntax (alternating key value key
    value ...) as a Python dict. A later duplicate key overwrites an
    earlier one, same as Tcl's own `dict` semantics."""
    elements = _tcl_list_elements(text.strip())
    return dict(zip(elements[0::2], elements[1::2]))


_FLOW_STATUS_SUCCESS_STATES = frozenset({"success", "complete", "completed", "done"})
_FLOW_STATUS_RUNNING_STATES = frozenset({"starting", "running", "in_progress"})
_FLOW_STATUS_FAILED_STATES = frozenset({"failed", "failure", "error"})


def genus_run_status(run_directory: Path) -> tuple[str, dict[str, str]]:
    """Read Flowtool's own real per-run execution record directly --
    `<run_directory>/flow.status`, confirmed real and already present on
    disk for any run that has actually invoked Flowtool (written by
    Flowtool itself, one real Tcl dict per line: a `{script flowtool
    status invoked ...}` line marks the start of one flowtool invocation
    and is skipped; every other line is one step's status transition,
    carrying a `status` (`starting`/`success`/...), a `time` (unix
    seconds), and a nested `steps_run` dict whose own `str` field is the
    step's real canonical dotted path, e.g.
    "block.synthesis.syn_generic.report_synth.report_finish" --
    disambiguating a step name several stages share, like `block_start`,
    by which stage actually ran it). A plain file read, no flowtool
    subprocess invocation needed at all.

    Returns (raw_text, {canonical_path: state}) -- state is one of
    "complete"/"running"/"failed", keyed by the exact dotted path
    flow.status itself uses (see stage_canonical_paths to map a
    STAGE_ORDER name to the set of paths it owns). A later record for
    the same path always overwrites an earlier one (file order is
    chronological), so the result reflects the latest known state per
    step. An unparseable or missing status word degrades to leaving that
    record out rather than raising. Returns ("", {}) when no flow.status
    exists yet (e.g. `wolf run --plan` was the only thing that's
    happened).

    One real wrinkle, hit continuing an actual run after fixing a bug
    that had made it fail mid-stage: Flowtool's own `{script flowtool
    status invoked arguments {... -from X -to Y ...}}` marker lines are
    real too, and the most recent one names the stage range a brand new
    invocation is about to (re)run -- but that fresh attempt may not
    have logged anything for those canonical paths yet (e.g. it's an
    interactive session still sitting at a prompt before running its
    first step). Left alone, a path's stale "failed" from the *previous*
    attempt would keep showing "failed" even though a new attempt is
    actively under way and hasn't reported anything of its own yet. The
    most recent invocation marker, if any, is used to demote a stale
    "failed" within its own `-from`/`-to` range to "running" when
    nothing has been logged for that path since -- a new invocation
    starting is itself real, observed evidence that supersedes the old
    outcome, not a guess at Flowtool's internals.

    A second, related wrinkle, hit for real continuing past that same
    fix into the next stage: a stage flow.status has logged *nothing at
    all* for yet (not even a stale failure to demote) still needs to
    show as "running" the moment WOLF's own `wolf.step-status` (see
    genus_run_step_events' own docstring -- written independently of
    Flowtool's buffering) has a live record for it. That overlay is
    deliberately scoped to the same invocation's own `-from`/`-to`
    range as the demotion above, not applied blindly across every
    STAGE_ORDER name -- wolf.step-status is keyed by bare step name,
    and a name several stages share (like block_start) would otherwise
    falsely promote an unrelated, not-yet-reached stage too."""
    status_file = run_directory / "flow.status"
    if not status_file.is_file():
        return "", {}
    raw = status_file.read_text(encoding="utf-8", errors="replace")
    states: dict[str, str] = {}
    last_update_index: dict[str, int] = {}
    last_invocation: Optional[tuple[int, Optional[str], Optional[str]]] = None
    for index, line in enumerate(raw.splitlines()):
        line = line.strip()
        if not line:
            continue
        # Each real line is itself one outer {...}-wrapped Tcl list (the
        # whole record), not a bare key/value sequence -- strip that one
        # enclosing layer before parsing its own key/value pairs.
        if line.startswith("{") and line.endswith("}"):
            line = line[1:-1]
        record = _tcl_dict(line)
        if record.get("script") == "flowtool":
            arguments = _tcl_list_elements(record.get("arguments", ""))
            from_stage = (
                arguments[arguments.index("-from") + 1] if "-from" in arguments else None
            )
            to_stage = arguments[arguments.index("-to") + 1] if "-to" in arguments else None
            if from_stage or to_stage:
                last_invocation = (index, from_stage, to_stage)
            continue  # An invocation-boundary marker, not a step event.
        steps_run = record.get("steps_run")
        path = _tcl_dict(steps_run).get("str") if steps_run else None
        status = record.get("status", "").lower()
        if not path or not status:
            continue
        # A non-empty "errors" list on the record overrides the literal
        # status word -- the exact failure status string isn't confirmed
        # from a real failure yet, but a populated errors list is a
        # reliable signal regardless of what that word turns out to be.
        errors = record.get("errors", "")
        if errors and errors not in ("{}", ""):
            states[path] = "failed"
        elif status in _FLOW_STATUS_FAILED_STATES:
            states[path] = "failed"
        elif status in _FLOW_STATUS_SUCCESS_STATES:
            states[path] = "complete"
        elif status in _FLOW_STATUS_RUNNING_STATES:
            states[path] = "running"
        last_update_index[path] = index
    if last_invocation is not None:
        invocation_index, from_stage, to_stage = last_invocation
        if from_stage in STAGE_ORDER:
            start = STAGE_ORDER.index(from_stage)
            end = STAGE_ORDER.index(to_stage) if to_stage in STAGE_ORDER else start
            membership = flow_membership()
            live_events = genus_run_step_events(run_directory)
            for stage in STAGE_ORDER[start:end + 1]:
                for path in stage_canonical_paths(stage, membership):
                    bare_name = path.rsplit(".", 1)[-1]
                    # Exact canonical-path match first (unambiguous,
                    # the real fix for a bare name reused more than
                    # once within the same stage), bare name only as a
                    # fallback for an older-format wolf.step-status
                    # line with no path recorded.
                    live_event = live_events.get(path) or live_events.get(bare_name)
                    if live_event is not None:
                        # Live evidence always wins within this
                        # invocation's own stage range, whether
                        # promoting a path flow.status never mentioned
                        # at all or correcting a stale one.
                        states[path] = live_event[0]
                    elif (
                        states.get(path) == "failed"
                        and last_update_index.get(path, -1) < invocation_index
                    ):
                        states[path] = "running"
    return raw, states


def genus_run_step_events(run_directory: Path) -> dict[str, tuple[str, float]]:
    """Read WOLF's own live per-step status record directly --
    `<run_directory>/wolf.step-status`, written by presentation.tcl's
    own create_flow_step wrapper (one real step's own bookkeeping, not
    Flowtool's) as `<step_name>|<status>|<unix_time>|<canonical_path>`
    lines, truncated fresh by `prepare_genus_inputs` at the start of
    every flowtool invocation.

    This exists specifically because Flowtool's own `flow.status`/
    `flow.metrics` are confirmed NOT promptly updated per step when a
    step runs as part of a manually-typed `run_flow` at an interactive
    Genus/Innovus prompt -- real, observed on an actual run: `flow.status`
    sat unchanged for well over an hour while the console clearly showed
    steps completing one after another. wolf.step-status instead reflects
    each step directly, independent of Flowtool's own buffering.

    Returns {key: (state, unix_time)}, state one of "running"/
    "complete"/"failed" via the same vocabulary genus_run_status itself
    uses, and unix_time the real timestamp of that latest record (used
    by stage_step_detail to compute how long a still-running step has
    actually been running). `key` is the real canonical dotted path
    (flow.status's own form, via presentation.tcl's own
    `wolf_step_canonical_path`) when the Tcl side could compute one,
    which fully disambiguates a step name reused more than once within
    the *same* stage (e.g. init_genus, both syn_opt's own direct member
    and one of report_synth's own nested leaf steps -- confirmed hit
    for real: report_synth falsely showed "running" because syn_opt's
    own already-complete direct init_genus cross-matched, by bare name
    alone, into report_synth's own unrelated, not-yet-started nested
    init_genus). Falls back to the bare step name as `key` for an
    older-format line with no canonical path recorded (a session still
    running the previous presentation.tcl -- the same "won't affect an
    already-running session" limit every Tcl change this session has
    had). A caller matching a specific canonical path should check that
    key first and the bare step name second (`stage_step_detail` and
    genus_run_status's own live overlay both do), which correctly
    handles either format without needing to know which is in effect.
    A later record for the same key always overwrites an earlier one,
    same as genus_run_status. Degrades to {} rather than raising on a
    missing file -- e.g. before any step has executed yet this
    invocation."""
    events_file = run_directory / "wolf.step-status"
    if not events_file.is_file():
        return {}
    events: dict[str, tuple[str, float]] = {}
    for line in events_file.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        name, status = parts[0], parts[1].lower()
        try:
            event_time = float(parts[2])
        except ValueError:
            continue
        key = parts[3] if len(parts) > 3 and parts[3] else name
        if status in _FLOW_STATUS_FAILED_STATES:
            events[key] = ("failed", event_time)
        elif status in _FLOW_STATUS_SUCCESS_STATES:
            events[key] = ("complete", event_time)
        elif status in _FLOW_STATUS_RUNNING_STATES:
            events[key] = ("running", event_time)
    return events


def genus_run_active_elapsed(run_directory: Path) -> Optional[float]:
    """How long the current flowtool invocation has actually been
    running, in seconds -- wolf.step-status is truncated fresh per
    invocation (see genus_run_step_events' own docstring), so its own
    earliest logged timestamp marks when this invocation's first real
    step started. Independent of flow.metrics' own total_real_seconds,
    which (like flow.status) is confirmed not promptly updated during a
    manually-typed run_flow either. Returns None when nothing has
    started yet this invocation (a missing or empty wolf.step-status)."""
    events_file = run_directory / "wolf.step-status"
    if not events_file.is_file():
        return None
    timestamps: list[float] = []
    for line in events_file.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        try:
            timestamps.append(float(parts[2]))
        except ValueError:
            continue
    return time.time() - min(timestamps) if timestamps else None


def genus_run_step_elapsed(run_directory: Path) -> dict[str, float]:
    """Real per-step duration -- how long a step that has finished
    actually took, or how long a still-running one has been running so
    far -- derived from wolf.step-status's own `starting` and later
    terminal (`success`/`failed`) records for the same key.
    genus_run_step_events only ever keeps the *latest* record per key
    (by design, for current status), which discards the earlier
    `starting` timestamp a completed step would need to compute its own
    duration from; this re-reads the same file to keep both.

    Returns {key: elapsed_seconds} -- keyed the same way
    genus_run_step_events is (the real canonical dotted path when
    presentation.tcl recorded one, the bare step name as a fallback for
    an older-format line). A key with no `starting` record seen (a run
    continuing from a checkpoint older than this file, say) is simply
    left out rather than guessed."""
    events_file = run_directory / "wolf.step-status"
    if not events_file.is_file():
        return {}
    start_times: dict[str, float] = {}
    latest: dict[str, tuple[str, float]] = {}
    for line in events_file.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        name, status = parts[0], parts[1].lower()
        try:
            event_time = float(parts[2])
        except ValueError:
            continue
        key = parts[3] if len(parts) > 3 and parts[3] else name
        if status in _FLOW_STATUS_RUNNING_STATES:
            start_times[key] = event_time
            latest[key] = ("running", event_time)
        elif status in _FLOW_STATUS_SUCCESS_STATES:
            latest[key] = ("complete", event_time)
        elif status in _FLOW_STATUS_FAILED_STATES:
            latest[key] = ("failed", event_time)
    now = time.time()
    elapsed: dict[str, float] = {}
    for key, (state, event_time) in latest.items():
        start = start_times.get(key)
        if start is None:
            continue
        elapsed[key] = (now - start) if state == "running" else (event_time - start)
    return elapsed


def genus_run_status_elapsed(run_directory: Path) -> dict[str, float]:
    """The same real per-step duration as genus_run_step_elapsed, from
    flow.status instead of wolf.step-status -- Flowtool's own
    `starting`/terminal record pairs per canonical path, confirmed real
    (each one carries its own real unix `time`). This covers a
    completed step that finished before wolf.step-status existed for
    this run (an older stage, run under a previous presentation.tcl),
    or any step genuinely driven by Flowtool's own prompt invocation
    rather than a manually-typed `run_flow` (where flow.status itself
    is confirmed to stay prompt). `stage_step_detail` tries
    genus_run_step_elapsed first and falls back to this.

    Returns {canonical_path: elapsed_seconds}, left out for a path
    whose own `starting` record this run hasn't seen."""
    status_file = run_directory / "flow.status"
    if not status_file.is_file():
        return {}
    start_times: dict[str, float] = {}
    latest: dict[str, tuple[str, float]] = {}
    for line in status_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("{") and line.endswith("}"):
            line = line[1:-1]
        record = _tcl_dict(line)
        if record.get("script") == "flowtool":
            continue
        steps_run = record.get("steps_run")
        path = _tcl_dict(steps_run).get("str") if steps_run else None
        status = record.get("status", "").lower()
        time_field = record.get("time")
        if not path or not status or time_field is None:
            continue
        try:
            event_time = float(time_field)
        except ValueError:
            continue
        if status in _FLOW_STATUS_RUNNING_STATES:
            start_times[path] = event_time
            latest[path] = ("running", event_time)
        elif status in _FLOW_STATUS_SUCCESS_STATES:
            latest[path] = ("complete", event_time)
        elif status in _FLOW_STATUS_FAILED_STATES:
            latest[path] = ("failed", event_time)
    now = time.time()
    elapsed: dict[str, float] = {}
    for path, (state, event_time) in latest.items():
        start = start_times.get(path)
        if start is None:
            continue
        elapsed[path] = (now - start) if state == "running" else (event_time - start)
    return elapsed


def _memory_mb(value: Optional[str]) -> Optional[float]:
    """Flowtool reports memory as a free-text string like "39197 MB" --
    pull out just the leading number, degrading to None (left out of the
    result) for anything that doesn't look like that."""
    if not value:
        return None
    match = re.match(r"\s*([-+]?\d+(?:\.\d+)?)\s*MB\b", value, flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


def genus_run_metrics(run_directory: Path) -> dict[str, Any]:
    """Read Flowtool's own real per-run metrics record directly --
    `<run_directory>/flow.metrics`, a single JSON object (confirmed real
    against an actual run, written alongside flow.status): a top-level
    `metrics` list holds the *current* in-progress snapshot's own
    key/value pairs (including `flowtool.status`, Flowtool's own
    free-text one-line summary of what's running right now -- e.g.
    "Running flows... (1 running)\\n* flow_current @ genus:
    block.synthesis.syn_map.block_start -> ..."), `total_real`/
    `total_cpu` are the whole flow's own cumulative wall/CPU seconds so
    far, and `snapshots` holds one entry per *completed* child stage at
    the current nesting level, each with its own `key` (a Tcl list
    ending in "flow:<stage name>", not the step-level canonical path
    genus_run_status uses) and `metrics` (that stage's own
    `flow.realtime`/`flow.cputime`/memory totals).

    Returns a flat dict of display-ready metrics, plus one internal
    convention key, "stage_elapsed_seconds" (a {stage: seconds} dict
    pulled out of `snapshots`) -- `load_status` pops that back out
    before showing the metrics table or JSON, using it only to fill in
    `StageResult.elapsed_seconds` for a Cadence run's completed stages
    (which, unlike a generically-tracked `wolf.stage-results` run, have
    no other source of real timing). Degrades to {} rather than raising
    on a missing or malformed file."""
    metrics_file = run_directory / "flow.metrics"
    if not metrics_file.is_file():
        return {}
    try:
        data = json.loads(metrics_file.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    current = {
        entry.get("name"): entry.get("value")
        for entry in data.get("metrics", []) if isinstance(entry, dict)
    }
    result: dict[str, Any] = {}
    if "flowtool.status" in current:
        result["cadence.current_activity"] = current["flowtool.status"]
    for key, source in (
        ("cadence.total_real_seconds", "total_real"), ("cadence.total_cpu_seconds", "total_cpu"),
    ):
        value = data.get(source)
        if isinstance(value, (int, float)):
            result[key] = float(value)
    memory_mb = _memory_mb(current.get("flow.memory.resident"))
    if memory_mb is not None:
        result["cadence.memory_resident_mb"] = memory_mb
    peak_mb = _memory_mb(current.get("flow.memory.resident.peak"))
    if peak_mb is not None:
        result["cadence.memory_resident_peak_mb"] = peak_mb
    stage_elapsed: dict[str, float] = {}
    for snapshot in data.get("snapshots", []):
        if not isinstance(snapshot, dict):
            continue
        key = snapshot.get("key", "")
        stage = key.split()[-1].removeprefix("flow:") if key else ""
        if stage not in STAGE_ORDER:
            continue
        snapshot_metrics = {
            entry.get("name"): entry.get("value")
            for entry in snapshot.get("metrics", []) if isinstance(entry, dict)
        }
        realtime = snapshot_metrics.get("flow.realtime")
        try:
            stage_elapsed[stage] = float(realtime)
        except (TypeError, ValueError):
            continue
    if stage_elapsed:
        result["stage_elapsed_seconds"] = stage_elapsed
    return result


# area/timing/power.<stage>.rpt -- Genus's own real, already-written report
# files (named via flow_report_name, see common_flows.tcl's own header on
# report_synth), confirmed real and already present on disk for any
# completed synthesis stage. Deliberately not scanning for DRC/LVS/signoff
# reports yet -- those only exist once a run has reached floorplan/route,
# a later extension, not guessed ahead of real evidence.
_QOR_REPORT_KINDS = ("area", "timing", "power")

# {report path: (mtime, parsed)} -- a report file is Genus's own static
# snapshot from whichever step wrote it, never rewritten again once that
# step finishes, so re-parsing it every `wolf status --watch` tick (the
# whole point of this cache) would be pure waste; the mtime check itself
# is one cheap stat() call either way.
_qor_report_cache: dict[Path, tuple[float, dict[str, float]]] = {}


def _cached_qor_parse(path: Path, parser) -> Optional[dict[str, float]]:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    cached = _qor_report_cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    result = parser(path)
    if result is not None:
        _qor_report_cache[path] = (mtime, result)
    return result


def _parse_area_report(path: Path) -> Optional[dict[str, float]]:
    """The design's own top-level row from a real Genus area report --
    confirmed real shape: a `---`-only separator line, then one row per
    hierarchy level, each indented except the top (design) row, whose
    own last four whitespace-separated fields are Cell Count/Cell Area/
    Net Area/Total Area regardless of how many name columns precede
    them (the design's own instance name has no separate Module
    column, unlike every child row)."""
    in_table = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not in_table:
            if line.strip().startswith("---"):
                in_table = True
            continue
        if not line.strip() or line[0].isspace():
            continue  # blank, or an indented (non-top-level) row.
        tokens = line.split()
        if len(tokens) < 4:
            return None
        try:
            cell_count = float(tokens[-4])
            cell_area, net_area, total_area = (float(token) for token in tokens[-3:])
        except ValueError:
            return None
        return {
            "cell_count": cell_count, "cell_area_um2": cell_area,
            "net_area_um2": net_area, "total_area_um2": total_area,
        }
    return None


def _parse_timing_report(path: Path) -> Optional[dict[str, float]]:
    """The real SETUP `View: ALL` summary row from a Genus timing
    report -- confirmed real shape: `View: ALL  <wns>  <tns>  <fep>`.
    A second, DRV-section `View: ALL` line (no trailing numbers, "N/A"
    checks) is skipped automatically since it has too few fields."""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("View:"):
            continue
        tokens = stripped.split()
        if len(tokens) < 5:
            continue
        try:
            wns, tns, fep = (float(token) for token in tokens[2:5])
        except ValueError:
            continue
        return {"worst_slack_ps": wns, "total_negative_slack_ps": tns, "failing_endpoints": fep}
    return None


def _parse_power_report(path: Path) -> Optional[dict[str, float]]:
    """The real `Subtotal` row from a Genus power report -- confirmed
    real shape: `Subtotal  <leakage>  <internal>  <switching>  <total>
    <row%>`, watts, scientific notation."""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("Subtotal"):
            continue
        tokens = stripped.split()
        if len(tokens) < 5:
            return None
        try:
            leakage, internal, switching, total = (float(token) for token in tokens[1:5])
        except ValueError:
            return None
        return {
            "leakage_w": leakage, "internal_w": internal,
            "switching_w": switching, "total_w": total,
        }
    return None


_QOR_PARSERS = {
    "area": _parse_area_report, "timing": _parse_timing_report, "power": _parse_power_report,
}


def genus_run_qor(run_directory: Path) -> dict[str, dict[str, dict[str, float]]]:
    """Real QoR figures straight from Genus's own already-written
    area/timing/power reports for every synthesis stage that has
    produced one so far -- `wolf status --watch`'s QoR table. Each
    report is Genus's own static snapshot (never rewritten once its
    own step finishes), so this is mtime-cached per file rather than
    re-parsed every call.

    Returns {stage: {kind: {field: value}}}, only for (stage, kind)
    pairs whose report file actually exists and parsed successfully --
    a stage with no reports directory yet, or with some but not all
    three report kinds (report_synth hasn't finished, say), simply has
    whatever is real and present, not a guess at the rest."""
    reports_directory = run_directory / "reports"
    if not reports_directory.is_dir():
        return {}
    result: dict[str, dict[str, dict[str, float]]] = {}
    for stage in SYNTHESIS_STAGES:
        for kind in _QOR_REPORT_KINDS:
            report_path = reports_directory / f"{kind}.{stage}.rpt"
            if not report_path.is_file():
                continue
            parsed = _cached_qor_parse(report_path, _QOR_PARSERS[kind])
            if parsed is not None:
                result.setdefault(stage, {})[kind] = parsed
    return result


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
            # Split so a real gap says exactly which piece is missing --
            # a combined "technology and cell LEF" message left someone
            # with only one of the two guessing which one Innovus
            # actually lacks. A tracked package that ships one real
            # merged LEF (technology + cell geometry together) has both
            # non-empty from the same file (see environment.py's own
            # _technology_inputs), so this isn't asking for two separate
            # files -- only that Innovus's own real minimum (routing-
            # layer/site geometry, and standard-cell abstracts) is
            # actually present, however it got there.
            checks.append(GenusValidation(
                "technology LEF", bool(technology.technology_lefs),
                "technology LEF (routing layers/sites) required for physical implementation"
                if not technology.technology_lefs else
                ", ".join(str(path) for path in technology.technology_lefs),
            ))
            checks.append(GenusValidation(
                "cell LEF", bool(technology.cell_lefs),
                "cell LEF (standard-cell abstracts) required for physical implementation"
                if not technology.cell_lefs else
                ", ".join(str(path) for path in technology.cell_lefs),
            ))
            checks.append(GenusValidation(
                "technology RC", bool(technology.rc_files),
                "RC setup/extraction collateral (qrc techfiles/captables) required for "
                "physical implementation" if not technology.rc_files else
                ", ".join(str(path) for path in technology.rc_files),
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


_CREATE_FLOW_STEP_RE = re.compile(r"create_flow_step\s+-name\s+(\S+)[^{]*\{")
_CREATE_FLOW_RE = re.compile(r"create_flow\s+-name\s+(\S+)[^{]*\{")


def _braced_block(text: str, open_brace_index: int) -> str:
    """The real `{...}` block starting at `text[open_brace_index]`, by
    brace-depth matching rather than a non-greedy regex -- both a step
    body (an `if`, a `foreach`, ...) and a flow's own member list can
    legitimately contain nested braces that a regex would truncate at
    the first inner `}`."""
    depth = 0
    end = open_brace_index
    for index in range(open_brace_index, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
    return text[open_brace_index:end + 1]


def _extract_step_bodies(text: str) -> dict[str, str]:
    """Pull out each create_flow_step's raw Tcl body by brace-matching."""
    bodies: dict[str, str] = {}
    for match in _CREATE_FLOW_STEP_RE.finditer(text):
        bodies[match.group(1)] = _braced_block(text, match.end() - 1)
    return bodies


def _extract_flow_members(text: str) -> dict[str, tuple[str, ...]]:
    """Pull out each create_flow's own member list (step names and/or
    other flow names, in execution order) by the same brace-matching."""
    members: dict[str, tuple[str, ...]] = {}
    for match in _CREATE_FLOW_RE.finditer(text):
        block = _braced_block(text, match.end() - 1)
        # Tcl line-continuation: a backslash immediately before a newline
        # joins the next line into this one, the backslash itself is not
        # a member -- without this, a wrapped member list (every real one
        # here) leaves a literal "\" token behind.
        block = re.sub(r"\\\s*\n", " ", block)
        members[match.group(1)] = tuple(block.strip("{}").split())
    return members


def flow_membership() -> dict[str, tuple[str, ...]]:
    """Every real create_flow's own member list across the bundled flow
    (currently all in common_flows.tcl, but scans every flow file in
    case a project's fork adds more) -- e.g. "syn_generic" -> ("block_start",
    "avoid_module_renaming", ..., "report_synth"). A member is either a
    real create_flow_step name (a leaf -- see flow_step_digests) or
    another flow name (nested, like report_synth inside syn_generic, or
    synthesis/implementation inside block); the caller expands those
    recursively with flow_descendant_steps."""
    flow_root = builtin_flow_root("cadence-genus")
    members: dict[str, tuple[str, ...]] = {}
    for name in _FLOW_SCRIPT_NAMES:
        text = (flow_root / name).read_text(encoding="utf-8")
        members.update(_extract_flow_members(text))
    return members


def flow_descendant_steps(
    name: str, membership: Optional[dict[str, tuple[str, ...]]] = None,
) -> tuple[str, ...]:
    """Every real create_flow_step reachable under a flow name, expanded
    recursively and flattened in execution order -- e.g.
    flow_descendant_steps("syn_generic") includes every leaf step
    syn_generic itself lists plus every leaf step its nested
    report_synth reference expands to. `name` that is itself already a
    real step (not a flow) returns just (name,) -- the recursion's own
    base case, so a caller doesn't need to know in advance which kind of
    name it has."""
    membership = membership if membership is not None else flow_membership()
    if name not in membership:
        return (name,)
    steps: list[str] = []
    seen: set[str] = set()
    for member in membership[name]:
        for step in flow_descendant_steps(member, membership):
            if step not in seen:
                steps.append(step)
                seen.add(step)
    return tuple(steps)


_STAGE_TOPLEVEL_FLOW = {
    **{stage: "synthesis" for stage in SYNTHESIS_STAGES},
    **{stage: "implementation" for stage in IMPLEMENTATION_STAGES},
}


def _expand_canonical_paths(
    prefix: str, name: str, membership: dict[str, tuple[str, ...]], out: list[str],
) -> None:
    if name not in membership:
        out.append(f"{prefix}.{name}")
        return
    nested_prefix = f"{prefix}.{name}"
    for member in membership[name]:
        _expand_canonical_paths(nested_prefix, member, membership, out)


def stage_canonical_paths(
    stage: str, membership: Optional[dict[str, tuple[str, ...]]] = None,
) -> tuple[str, ...]:
    """Every real canonical dotted path (flow.status's own step key, e.g.
    "block.synthesis.syn_generic.report_synth.report_finish") that
    `stage` (a STAGE_ORDER name) owns -- unlike flow_descendant_steps,
    which flattens nested sub-flows away to their bare leaf step names,
    this keeps every intermediate flow name (block, synthesis/
    implementation, the stage itself, and any further nested flow like
    report_synth) as its own path segment, exactly matching how
    flow.status disambiguates a step name several stages share (like
    block_start) by which stage actually ran it.

    The "block.synthesis"/"block.implementation" prefix reflects the
    real, fixed create_flow topology in common_flows.tcl (block owns
    synthesis and implementation; each owns its own STAGE_ORDER
    sub-flows) -- not derived generically, since nothing else in the
    bundled flow needs that generality."""
    membership = membership if membership is not None else flow_membership()
    prefix = f"block.{_STAGE_TOPLEVEL_FLOW[stage]}"
    paths: list[str] = []
    _expand_canonical_paths(prefix, stage, membership, paths)
    return tuple(paths)


def flow_step_digests() -> dict[str, str]:
    """A short content hash per real create_flow_step in the bundled
    flow -- lets a run (or a human reading two runs' logs) tell exactly
    which steps changed between them, not just that *something* in the
    bundled flow did (bundled_flow_digest alone can't distinguish "the
    report step changed" from "the synthesis step changed"). Keyed by
    step name, sorted by the caller as needed."""
    flow_root = builtin_flow_root("cadence-genus")
    digests: dict[str, str] = {}
    for name in _FLOW_SCRIPT_NAMES:
        text = (flow_root / name).read_text(encoding="utf-8")
        for step_name, body in _extract_step_bodies(text).items():
            digests[step_name] = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    return digests


def _rollup_one_state(known: dict[str, str], descendant_count: int) -> str:
    values = list(known.values())
    if "failed" in values:
        return "failed"
    if "running" in values:
        return "running"
    # "complete" only counts for the *stage* once every one of its real
    # descendant steps is accounted for -- a partial sample (e.g. only
    # block_start, a name several stages share) all happening to read
    # "complete" says nothing about the steps genus_run_status had no
    # line for at all, and must not be mistaken for the whole stage
    # being done.
    if len(known) == descendant_count and all(value == "complete" for value in values):
        return "complete"
    if "complete" in values:
        # Some real work has happened (seen directly, or implied by full
        # coverage not yet reached) and more remains -- the stage itself
        # is in progress, not simply "not started yet".
        return "running"
    return "pending"


def rollup_stage_states(
    states: dict[str, str], stages: tuple[str, ...] = STAGE_ORDER,
) -> dict[str, str]:
    """Fill in a state for every name in `stages` from the real,
    canonical-path-keyed detail `genus_run_status` reads out of
    flow.status.

    flow.status disambiguates a step name several stages share (like
    block_start or init_genus) by which stage actually ran it --
    `stage_canonical_paths` computes exactly that stage's own set of
    real dotted paths (block.synthesis.syn_generic.block_start, not the
    bare "block_start" every other synthesis stage also happens to
    list), so a stage's rollup only ever counts its *own* steps, never
    an unrelated stage's run of a same-named one. A stage with no state
    at all for any of its canonical paths (nothing recognized yet) is
    simply left absent -- `wolf status`'s own existing fallback
    ("unknown"/"pending") already handles that.

    Returns a new dict with every original canonical-path-keyed entry
    preserved alongside the stage-level rollup, for a future renderer
    that wants the full detail, not just the one load_status reads
    today.
    """
    rolled = dict(states)
    membership = flow_membership()
    for stage in stages:
        if stage in rolled:
            continue
        canonical_paths = stage_canonical_paths(stage, membership)
        known = {path: states[path] for path in canonical_paths if path in states}
        if not known:
            continue
        rolled[stage] = _rollup_one_state(known, len(canonical_paths))
    return rolled


def stage_step_detail(
    run_directory: Path, stage: str, membership: Optional[dict[str, tuple[str, ...]]] = None,
) -> tuple[tuple[str, str, Optional[float]], ...]:
    """One level of real detail under `stage` -- its own direct
    create_flow members, in execution order, each paired with its
    current state and (when known) how long it's been running -- for
    `wolf status --watch`'s expanded live view of whichever stage is
    currently running.

    A member that's itself a leaf create_flow_step reports its own
    canonical path's state directly; a member that's a nested sub-flow
    (e.g. report_synth inside syn_generic) reports the same rollup
    `rollup_stage_states` itself uses -- "complete" only once every one
    of *its* own real leaf descendants is accounted for, "failed" if
    any is, otherwise "running" once anything has started. Returns ()
    for an unrecognized stage name or a run with no flow.status yet.

    genus_run_step_events' own live data (see its own docstring for why
    it exists -- Flowtool's own flow.status isn't promptly updated per
    step during an interactive `run_flow`) always wins over
    flow.status's own canonical-path state for a leaf it has an entry
    for, matched by exact canonical path first (unambiguous even for a
    step name reused more than once within the same stage, like
    init_genus as both a direct member and one of report_synth's own
    nested leaf steps) and the bare step name only as a fallback for an
    older-format wolf.step-status line with no path recorded.
    genus_run_status's own states already carry this same overlay for
    paths within the active invocation's own stage range.

    The elapsed seconds (third tuple element) is a direct leaf
    member's own real duration -- how long it actually took once it
    finished, or how long it's been running so far -- from
    genus_run_step_elapsed, falling back to genus_run_status_elapsed
    (the same real `starting`/terminal timestamp pairs, from
    flow.status instead, for a step that finished before this run's
    wolf.step-status existed). None when neither source has a
    `starting` record for it; a nested sub-flow's own aggregate row
    never gets one either, since there is no single real "start" for
    an aggregate."""
    if stage not in STAGE_ORDER:
        return ()
    membership = membership if membership is not None else flow_membership()
    _, states = genus_run_status(run_directory)
    events = genus_run_step_events(run_directory)
    live_elapsed = genus_run_step_elapsed(run_directory)
    flow_status_elapsed = genus_run_status_elapsed(run_directory)
    prefix = f"block.{_STAGE_TOPLEVEL_FLOW[stage]}.{stage}"
    detail: list[tuple[str, str, Optional[float]]] = []
    for member in membership.get(stage, ()):
        leaf_paths: list[str] = []
        _expand_canonical_paths(prefix, member, membership, leaf_paths)
        known = {path: states[path] for path in leaf_paths if path in states}
        member_elapsed: Optional[float] = None
        for path in leaf_paths:
            bare_name = path.rsplit(".", 1)[-1]
            live_event = events.get(path) or events.get(bare_name)
            if live_event is not None:
                known[path] = live_event[0]
            if bare_name == member:
                # Not `a or b or c` -- a real 0.0-second duration is
                # falsy and would otherwise be mistaken for "missing"
                # and silently overridden by a less specific fallback.
                member_elapsed = live_elapsed.get(path)
                if member_elapsed is None:
                    member_elapsed = live_elapsed.get(bare_name)
                if member_elapsed is None:
                    member_elapsed = flow_status_elapsed.get(path)
        detail.append((member, _rollup_one_state(known, len(leaf_paths)), member_elapsed))
    return tuple(detail)


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
    # Kept named synthesis_stages for provenance/manifest compatibility --
    # a frozen wolf.resolved.yaml key -- even though a range reaching into
    # IMPLEMENTATION_STAGES now legitimately lands non-synthesis stage
    # names in here too.
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
    # flow-config.tcl is the *last* file Flowtool sources during setup
    # (flow.template.yaml's user_flow_steps, after every create_flow/
    # create_flow_step above has already registered) -- the natural place
    # for something to run automatically once setup finishes and before
    # control passes to the user (interactive or not), with no need for
    # a separate -inject_tcl flag. The identity banner means a log (or a
    # user's own eyes, comparing two runs) can tell not just "the bundled
    # flow ran" but exactly which content each step actually had.
    #
    # Deliberately NOT also calling the real report_flow command here:
    # confirmed against a real run that invoking it this early, while
    # Flowtool is still sourcing user_flow_steps, throws its own internal
    # Tcl error ("expected boolean value but got \"\"") -- some Flowtool
    # db attribute report_flow depends on apparently isn't initialized
    # yet at this point in setup. report_flow itself is a native
    # Flowtool command outside WOLF's control (see AGENTS.md: don't
    # reimplement or guess at backend internals), so the fix is to not
    # call it automatically from here at all; the identity banner alone
    # (no report_flow dependency) is safe, and a user who wants
    # report_flow's own output can still type it by hand once control
    # reaches the prompt.
    step_digests = flow_step_digests()
    setup_report_tail = (
        "\nputs [wolf_sep]\n"
        f'wolf_step "Bundled flow identity -- sha256:{bundled_flow_digest()}"\n'
        + "".join(
            f'wolf_info "  {name}: sha256:{digest}"\n'
            for name, digest in sorted(step_digests.items())
        )
        + "puts [wolf_sep]\n"
    )
    # Truncated fresh on every invocation (not just the first) -- a
    # step name several stages share (like block_start) is otherwise
    # ambiguous in wolf.step-status across invocations the way a
    # canonical dotted path in Flowtool's own flow.status is not; a
    # fresh, empty file per invocation means the only entries present
    # ever belong to whichever stage *this* invocation is actually
    # running. See presentation.tcl's own create_flow_step wrapper for
    # why this file exists at all: Flowtool's own flow.status/
    # flow.metrics are confirmed NOT promptly updated per step when a
    # step runs as part of a manually-typed `run_flow` at an
    # interactive prompt.
    (destination / "wolf.step-status").write_text("", encoding="utf-8")
    flow_config_script.write_text(
        "# Generated by WOLF; resolved values consumed by synthesis.tcl/common_steps.tcl.\n"
        f"set wolf_run_directory {_tcl_quote(str(destination))}\n"
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
        # Not resolved from any PDK/environment field yet -- always empty,
        # so the guarded steps in synthesis.tcl that read these quietly
        # skip rather than running on a fabricated value. See
        # synthesis.tcl's own header for what each one would feed.
        f"set wolf_clock_derate_early \"\"\n"
        f"set wolf_clock_derate_late \"\"\n"
        f"set wolf_preserve_blocks {{}}\n"
        f"set wolf_preserve_instances {{}}\n"
        f"set wolf_power_intent_file \"\"\n"
        f"set wolf_max_routing_layers \"\"\n"
        f"array set wolf_inject {{}}\n"
        f"{inject_lines}"
        f"{setup_report_tail}",
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

    # None for an implementation-only range -- floorplan/prects/cts/
    # postcts/route/postroute don't write_hdl a netlist the way the three
    # Genus synthesis stages do.
    netlist_relative: str | None = None
    if synthesis_stages and synthesis_stages[-1] in _SYNTHESIS_STAGE_NETLIST_SUFFIX:
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


def validate_genus_or_raise(context: ResolvedContext, *, physical: bool = False) -> str:
    checks = validate_genus(context, physical=physical)
    failures = [f"{item.name}: {item.detail}" for item in checks if not item.available]
    if failures:
        raise ValueError("Cadence Genus validation failed: " + "; ".join(failures))
    return next(item.detail for item in checks if item.name == "flowtool")


def run_genus(
    context: ResolvedContext, *, clean: bool = False, interactive: bool = False,
    from_stage: Optional[str] = None, to_stage: Optional[str] = None,
) -> tuple[int, Path]:
    """Allocate, prepare, freeze provenance, and execute one Flowtool run --
    for any stage in STAGE_ORDER, Genus (syn_generic/syn_map/syn_opt) or
    Innovus (floorplan/prects/cts/postcts/route/postroute) alike.

    Execution always goes through the real `flowtool` binary, never
    `genus`/`innovus` directly, so the create_flow_step/-write_db
    checkpointing in flows/cadence-genus/common_steps.tcl is meaningful:
    Flowtool's own engine saves each step's checkpoint and, on a later
    -from, loads the nearest preceding one automatically -- WOLF does not
    reimplement that itself, and does not care which tool a given stage
    happens to run under; that distinction lives entirely in the Tcl flow
    definitions, not here.
    A run without -c/--clean reuses the same numbered run directory, so an
    earlier invocation's checkpoints are still there for a later -from --
    this is exactly how `-from syn_opt` (Genus) and a later `-from
    floorplan` (Innovus) share one run directory and one provenance
    record.
    """
    resolved_from_stage, resolved_to_stage = _resolve_stage_range(context, from_stage, to_stage)
    flowtool = validate_genus_or_raise(
        context, physical=_requires_physical_views(resolved_from_stage, resolved_to_stage),
    )
    run_directory = allocate_genus_run(context, clean=clean)
    _update_latest_run_link(context, run_directory)
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
    # wolf status's own backend lookup (wolf/status.py's _manifest) reads
    # this exact shape (backend.name) to decide which Backend.
    # infer_stage_results/extract_metrics/stages to call -- without it,
    # it falls back to "unknown" and silently skips all three.
    resolved["backend"] = {"name": context.backend}
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
        #
        # scripts_directory is volatile too, deliberately: it names a
        # deduplicated scripts.<N> snapshot of the bundled flow Tcl
        # (_snapshot_scripts), and really does get a new number the
        # moment that Tcl's own content changes -- which legitimately
        # happens mid-run during active flow development (fixing a real
        # bug in synthesis.tcl/common_flows.tcl and continuing the same
        # physical-design run with the fix, not starting over). Flowtool
        # checkpoint resume is Genus/Innovus session state, independent
        # of which exact snapshot loaded it, so this was never really
        # part of a run's *physical* identity the way design/technology
        # are. The real safety net already exists and stays
        # non-negotiable: flow_step_digests/bundled_flow_digest print
        # automatically (flow-config.tcl's own tail, and again on every
        # `wolf run` exit) specifically so a content difference between
        # two invocations of the same run is always visible, even though
        # it no longer blocks continuing.
        # "generated" (directory + every generated_files path) is
        # volatile for the same reason as scripts_directory above --
        # flowtool_scripts_directory inside it references that same
        # snapshot number, and the rest (genus_sources, genus_constraints,
        # ...) are freshly (re)written every single invocation by design
        # (see prepare_genus_inputs's own docstring: "written directly,
        # fresh every call"), never part of what makes this run this run.
        volatile_keys=(
            "from_stage", "to_stage", "synthesis_stages", "outputs", "execution",
            "scripts_directory", "generated",
        ),
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

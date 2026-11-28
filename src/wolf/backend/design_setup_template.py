"""Generate and refresh a design's setup.<design_name>.yaml as a fully
commented template, and append a flow package's own extra per-design
keys from its own declared template.

WOLF's own section documents every key in
cadence_genus_setup.DESIGN_SETUP_ALLOWED_KEYS, commented out, each
with a one-line description, its value shape, WOLF's own (unset)
default, and a commented example -- never a real cell name (see
cells_for_technology/CatalogLibrarySet; this file lives in the project
tree, which is tracked in git). A non-cell, PDK-derived choice (an
analysis-view/corner name, a routing layer name) is cited by its real
resolved name when a technology is resolvable, since those are safe to
write (see the handoff this was built for:
workspace/handoff/wolf-agent-design-setup-template.md).

A flow package's own section (see cadence_genus_setup.flow_design_setup_keys)
is appended verbatim -- its template is already in this same commented
format, so no re-rendering is needed, the same plain-text-append
approach cadence_genus._concatenate_setup_fragments already uses for a
PDK's own setup.yaml fragment.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable, Optional

from wolf.backend.cadence_genus_setup import DESIGN_SETUP_ALLOWED_KEYS
from wolf.context import ResolvedTechnology


@dataclass(frozen=True)
class _KeySpec:
    key: str
    section: str
    description: str
    shape: str
    default: str
    example: Callable[[Optional[ResolvedTechnology]], tuple[str, ...]]


def _scalar_example(value: str) -> Callable[[Optional[ResolvedTechnology]], tuple[str, ...]]:
    return lambda technology: (value,)


def _cell_list_example(placeholder: str = "<cell_name>") -> Callable[[Optional[ResolvedTechnology]], tuple[str, ...]]:
    return lambda technology: ("", f"  - {placeholder}")


def _view_example(technology: Optional[ResolvedTechnology]) -> tuple[str, ...]:
    from wolf.cell_browser import analysis_view_names_for_technology

    names = analysis_view_names_for_technology(technology) if technology else None
    name = names[0] if names else "<view_name>"
    return ("", f"  setup: [{name}]")


def _layer_example(technology: Optional[ResolvedTechnology]) -> tuple[str, ...]:
    from wolf.cell_browser import routing_layers_for_technology

    try:
        names = routing_layers_for_technology(technology) if technology else None
    except OSError:
        names = None
    name = names[-1] if names else "<layer_name>"
    return (name,)


_KEY_SPECS: tuple[_KeySpec, ...] = (
    _KeySpec(
        "cts_buffer_cells", "Clock tree synthesis (CTS)",
        "CCOpt buffer cell names/patterns for clock tree synthesis.",
        "list of cell names or patterns (e.g. \"<prefix>*\")",
        "[] (CCOpt uses every library cell reporting is_buffer)",
        _cell_list_example(),
    ),
    _KeySpec(
        "cts_buffer_cells_top", "Clock tree synthesis (CTS)",
        "Buffer cells CCOpt may use near the clock tree's top (trunk) level.",
        "list of cell names or patterns", "[] (same as cts_buffer_cells)",
        _cell_list_example(),
    ),
    _KeySpec(
        "cts_buffer_cells_leaf", "Clock tree synthesis (CTS)",
        "Buffer cells CCOpt may use at the clock tree's leaf level.",
        "list of cell names or patterns", "[] (same as cts_buffer_cells)",
        _cell_list_example(),
    ),
    _KeySpec(
        "cts_inverter_cells", "Clock tree synthesis (CTS)",
        "CCOpt inverter cell names/patterns for clock tree synthesis.",
        "list of cell names or patterns",
        "[] (CCOpt uses every library cell reporting is_inverter)",
        _cell_list_example(),
    ),
    _KeySpec(
        "cts_inverter_cells_top", "Clock tree synthesis (CTS)",
        "Inverter cells CCOpt may use near the clock tree's top level.",
        "list of cell names or patterns", "[] (same as cts_inverter_cells)",
        _cell_list_example(),
    ),
    _KeySpec(
        "cts_inverter_cells_leaf", "Clock tree synthesis (CTS)",
        "Inverter cells CCOpt may use at the clock tree's leaf level.",
        "list of cell names or patterns", "[] (same as cts_inverter_cells)",
        _cell_list_example(),
    ),
    _KeySpec(
        "cts_clock_gating_cells", "Clock tree synthesis (CTS)",
        "Clock-gating cell names/patterns CCOpt may use.",
        "list of cell names or patterns",
        "[] (CCOpt uses every library cell reporting is_integrated_clock_gating)",
        _cell_list_example(),
    ),
    _KeySpec(
        "cts_target_skew", "Clock tree synthesis (CTS)",
        "CCOpt's clock skew target.",
        "number (ps), or one of: default | auto | ignore | double",
        "unset (Innovus's own CCOpt default)",
        _scalar_example("auto"),
    ),
    _KeySpec(
        "cts_target_max_transition_time", "Clock tree synthesis (CTS)",
        "CCOpt's clock-network max transition-time target.",
        "number (ps), or one of: default | auto | ignore | double",
        "unset (Innovus's own CCOpt default)",
        _scalar_example("auto"),
    ),
    _KeySpec(
        "cts_max_fanout", "Clock tree synthesis (CTS)",
        "CCOpt's max fanout per clock buffer/inverter.",
        "integer", "unset (Innovus's own CCOpt default)",
        _scalar_example("16"),
    ),
    _KeySpec(
        "add_tieoffs_cells", "Tie-off cells",
        "Tie-high/tie-low driver cell names for add_tieoffs (at most two: one of each).",
        "list of at most two cell names", "[] (add_tieoffs stays a no-op)",
        _cell_list_example(),
    ),
    _KeySpec(
        "add_tieoffs_honor_dont_use", "Tie-off cells",
        "Whether add_tieoffs honors the loaded library's dont_use flags.",
        "boolean", "unset (Innovus's own default)",
        _scalar_example("true"),
    ),
    _KeySpec(
        "add_tieoffs_max_fanout", "Tie-off cells",
        "Max fanout per tie-off driver instance add_tieoffs inserts.",
        "integer", "unset (Innovus's own default)",
        _scalar_example("100"),
    ),
    _KeySpec(
        "add_tieoffs_max_distance", "Tie-off cells",
        "Max distance (microns) a tied-off pin may be from its driver.",
        "number (microns)", "unset (Innovus's own default)",
        _scalar_example("50"),
    ),
    _KeySpec(
        "add_fillers_cells", "Filler cells",
        "Exact filler cell names for add_fillers (no pattern expansion).",
        "list of exact cell names", "[] (add_fillers stays a no-op)",
        _cell_list_example(),
    ),
    _KeySpec(
        "design_top_routing_layer", "Routing", "The highest metal layer route_design may use.",
        "scalar, a declared routing layer name", "unset (no top-layer constraint)",
        _layer_example,
    ),
    _KeySpec(
        "design_bottom_routing_layer", "Routing", "The lowest metal layer route_design may use.",
        "scalar, a declared routing layer name", "unset (no bottom-layer constraint)",
        _layer_example,
    ),
    _KeySpec(
        "route_design_antenna_cell_name", "Routing",
        "Antenna diode cell names/patterns for route_design's antenna fixing.",
        "list of cell names or patterns", "[] (no antenna fixing)",
        _cell_list_example(),
    ),
    _KeySpec(
        "gds_layermap", "Export",
        "GDS layer-map file path for write_stream's -map_file.",
        "scalar, a file path", "unset (Innovus generates its own generic layer map)",
        _scalar_example("'[get_flow_config flow_root]/project-scripts/layermap.map'"),
    ),
    _KeySpec(
        "export_spef", "Export",
        "Whether export also runs extract_rc + write_parasitics (-spef_file).",
        "boolean", "false (SPEF is not extracted or written)",
        _scalar_example("true"),
    ),
    _KeySpec(
        "clock_routing_width_multiplier", "Clock routing",
        "create_route_rule -width_multiplier per declared layer range.",
        "mapping of layer-range name to number", "{} (no custom route rule)",
        lambda technology: ("", f"  {_layer_example(technology)[0]}: 2.0"),
    ),
    _KeySpec(
        "clock_routing_spacing_multiplier", "Clock routing",
        "create_route_rule -spacing_multiplier per declared layer range.",
        "mapping of layer-range name to number", "{} (no custom route rule)",
        lambda technology: ("", f"  {_layer_example(technology)[0]}: 2.0"),
    ),
    _KeySpec(
        "clock_routing_types", "Clock routing",
        "add_clock_route_types' top/trunk/leaf route types.",
        "mapping of top|trunk|leaf to "
        "{route_rule: bool, top_preferred_layer: str, bottom_preferred_layer: str}",
        "{} (add_clock_route_types stays a no-op)",
        lambda technology: (
            "", "  top:", "    route_rule: true",
            f"    top_preferred_layer: {_layer_example(technology)[0]}",
        ),
    ),
    _KeySpec(
        "active_views", "Active analysis views",
        "Which declared analysis views (timing corners) stay active for setup/hold checks.",
        "mapping of setup|hold to a list of declared view names",
        "{} (every declared view active for both)",
        _view_example,
    ),
    _KeySpec(
        "genus_set_db", "Genus set_db overrides",
        "Arbitrary Genus set_db attribute overrides, applied before synthesis.",
        "mapping of attribute name to a scalar value", "{} (no overrides)",
        lambda technology: ("", "  some_genus_attribute: value"),
    ),
    _KeySpec(
        "postsyn_netlists", "Post-synthesis netlists",
        "Pre-synthesized sub-block netlists genus_to_innovus reads by reference "
        "(e.g. a repeated tile synthesized once).",
        "list of file paths", "[] (none)",
        lambda technology: ("", "  - /path/to/block/netlist.v"),
    ),
    _KeySpec(
        "inject", "Injected Tcl",
        "Extra Tcl (a file path, sourced, or inline text, eval'd) run before/after a named step.",
        "mapping of step name to {pre: [...], post: [...]}", "{} (none)",
        lambda technology: (
            "", "  some_step:", "    pre:", "      - /path/to/snippet.tcl",
        ),
    ),
)

assert {spec.key for spec in _KEY_SPECS} == DESIGN_SETUP_ALLOWED_KEYS, (
    "every DESIGN_SETUP_ALLOWED_KEYS key needs its own _KeySpec, and vice versa"
)


def _render_key_stanza(spec: _KeySpec, technology: Optional[ResolvedTechnology]) -> str:
    lines = [
        f"# {spec.description}",
        f"# {spec.shape}. Default: {spec.default}.",
    ]
    example_lines = spec.example(technology)
    first, rest = example_lines[0], example_lines[1:]
    lines.append(f"# {spec.key}:{(' ' + first) if first else ''}")
    for line in rest:
        lines.append(f"#{line}")
    return "\n".join(lines) + "\n"


def render_wolf_section(technology: Optional[ResolvedTechnology] = None) -> str:
    """WOLF's own fully commented section -- every DESIGN_SETUP_ALLOWED_KEYS
    key, grouped under the same kind of banner headers the real flow
    example file this was built against uses."""
    sections: list[str] = []
    seen_sections: list[str] = []
    by_section: dict[str, list[_KeySpec]] = {}
    for spec in _KEY_SPECS:
        by_section.setdefault(spec.section, []).append(spec)
        if spec.section not in seen_sections:
            seen_sections.append(spec.section)
    header = (
        "#" + "=" * 88 + "\n"
        "# Design setup: see skills/wolf-new-environment and skills/wolf-environments.\n"
        "# Uncomment a key below to override WOLF's own default for this design only.\n"
        "#" + "=" * 88 + "\n"
    )
    sections.append(header)
    for section in seen_sections:
        sections.append(
            "#" + "-" * 88 + "\n" f"# {section}\n" "#" + "-" * 88 + "\n"
        )
        for spec in by_section[section]:
            sections.append(_render_key_stanza(spec, technology))
    return "\n".join(sections)


def flow_section_header(flow_name: Optional[str]) -> str:
    name = flow_name or "the project flow"
    return (
        "\n" + "#" + "=" * 88 + "\n"
        f"# {name}'s own design keys.\n"
        "#" + "=" * 88 + "\n"
    )


def generate_or_refresh(
    path: Path, *,
    technology: Optional[ResolvedTechnology] = None,
    flow_template_path: Optional[Path] = None,
    flow_name: Optional[str] = None,
) -> None:
    """Write a brand-new, fully commented setup.<design>.yaml, or
    refresh an existing one by appending only the commented stanzas for
    keys that aren't a real, present entry yet -- every existing line
    (including a user's own added comments) is left exactly as-is,
    never reordered, never rewritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        text = render_wolf_section(technology)
        if flow_template_path is not None and flow_template_path.is_file():
            text += flow_section_header(flow_name)
            text += flow_template_path.read_text(encoding="utf-8")
        path.write_text(text, encoding="utf-8")
        return

    existing_text = path.read_text(encoding="utf-8")
    existing_keys = {
        match.group(1)
        for match in re.finditer(r"^#?\s*([A-Za-z_][A-Za-z0-9_]*):", existing_text, re.MULTILINE)
    }
    missing_wolf = [spec for spec in _KEY_SPECS if spec.key not in existing_keys]
    missing_flow_text = ""
    if flow_template_path is not None and flow_template_path.is_file():
        from wolf.backend.cadence_genus_setup import flow_design_setup_keys

        extra_keys = flow_design_setup_keys(flow_template_path)
        if extra_keys and not (extra_keys & existing_keys):
            # None of this flow's own keys appear anywhere in the file
            # yet (commented or not) -- its whole section was never
            # appended at all (an older file, or the template variable
            # just changed); append it once, not key-by-key, since its
            # stanzas aren't individually addressable the way WOLF's
            # own keys (each with its own _KeySpec) are.
            missing_flow_text = flow_section_header(flow_name) + flow_template_path.read_text(
                encoding="utf-8",
            )
    if not missing_wolf and not missing_flow_text:
        return
    addition = ""
    if missing_wolf:
        addition += (
            "\n" + "#" + "-" * 88 + "\n"
            "# Newly available keys\n"
            "#" + "-" * 88 + "\n"
        )
        for spec in missing_wolf:
            addition += _render_key_stanza(spec, technology)
    addition += missing_flow_text
    with path.open("a", encoding="utf-8") as handle:
        handle.write(addition)

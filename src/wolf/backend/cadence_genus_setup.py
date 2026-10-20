"""The design-level setup.<design_name>.yaml -- the authoritative,
hand-editable store for the cadence-flowtool knobs a user tunes per design
(CTS cell selection, tie-off cells, clock routing, active analysis views,
Genus set_db policy overrides, post-synthesis netlists, injected Tcl
snippets).

Lives at <project_root>/inputs/env/<design_name>/setup.<design_name>.yaml --
inside the project tree itself, not WOLF's own ~/.wolf/envs/ state
directory, so it is inspectable, shippable, and zippable alongside the
project, right next to the existing wolf.<env>.yaml reproducibility copy in
the same inputs/env/<design_name>/ directory.

Native-ish Flowtool key names (no wolf_ prefix), modeled on the real
institution setup.yaml this was adapted from. See cadence_genus.py's
_catalog_document/_render_setup_yaml for how this file's parsed content is
merged into a run's own rendered setup.yaml, and its _cts_overrides/
_tieoff_overrides/_clock_routing_overrides/_active_views_overrides/
_genus_set_db_overrides/_postsyn_netlists/_inject_snippets for the
per-key *value* shape this module does not itself validate -- only the
top-level key set, the one thing every caller (CLI set/unset, the menu,
the backend) needs to agree on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

DESIGN_SETUP_ALLOWED_KEYS = frozenset({
    "cts_buffer_cells", "cts_buffer_cells_top", "cts_buffer_cells_leaf",
    "cts_inverter_cells", "cts_inverter_cells_top", "cts_inverter_cells_leaf",
    "cts_clock_gating_cells",
    "cts_target_skew", "cts_target_max_transition_time", "cts_max_fanout",
    "add_tieoffs_cells", "add_tieoffs_honor_dont_use",
    "add_tieoffs_max_fanout", "add_tieoffs_max_distance",
    "add_fillers_cells",
    "clock_routing_width_multiplier", "clock_routing_spacing_multiplier",
    "clock_routing_types",
    "active_views",
    "genus_set_db",
    "postsyn_netlists",
    "inject",
})


def design_setup_path(project_root: Path, design_name: str) -> Path:
    return Path(project_root) / "inputs" / "env" / design_name / f"setup.{design_name}.yaml"


def load_design_setup(path: Path) -> dict[str, Any]:
    """The raw, validated top-level mapping -- {} if the file doesn't exist
    yet, so every design-level knob falls back to its documented default,
    same as an absent backend.cadence-flowtool key did before this file
    existed."""
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, Mapping):
        raise ValueError(f"{path}: must be a YAML mapping")
    unknown = set(data) - DESIGN_SETUP_ALLOWED_KEYS
    if unknown:
        raise ValueError(f"{path}: unsupported setup.yaml key: {sorted(unknown)[0]}")
    return dict(data)


def write_design_setup(path: Path, data: Mapping[str, Any]) -> None:
    unknown = set(data) - DESIGN_SETUP_ALLOWED_KEYS
    if unknown:
        raise ValueError(f"unsupported setup.yaml key: {sorted(unknown)[0]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(dict(data), sort_keys=False), encoding="utf-8")
    temporary.replace(path)


def _prune(data: dict, parts: list[str]) -> None:
    chain = [data]
    node: Any = data
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return
        node = node[part]
        chain.append(node)
    if isinstance(node, dict):
        node.pop(parts[-1], None)
    for index in range(len(chain) - 1, 0, -1):
        if isinstance(chain[index], dict) and not chain[index]:
            parent = chain[index - 1]
            if isinstance(parent, dict):
                parent.pop(parts[index - 1], None)


def set_design_setup_value(path: Path, dotted_key: str, value: Any) -> None:
    """Set (or, when value is None, remove and prune now-empty parents of)
    one dotted key in the design setup file -- the one real mutator both
    `wolf env set`/`wolf env unset` and `wolf env menu` call. Mirrors
    env_menu.py's own _override_set pruning, generalized to an arbitrary
    dotted path instead of the fixed backend.cadence-flowtool.* one it
    replaces."""
    parts = dotted_key.split(".")
    if not parts or not all(parts):
        raise ValueError(f"invalid setup key: {dotted_key!r}")
    if parts[0] not in DESIGN_SETUP_ALLOWED_KEYS:
        raise ValueError(f"unsupported setup.yaml key: {parts[0]!r}")
    data = load_design_setup(path)
    if value is None:
        _prune(data, parts)
    else:
        node = data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise ValueError(f"setup key parent is not a mapping: {dotted_key}")
        node[parts[-1]] = value
    write_design_setup(path, data)

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
import re
from typing import Any, Mapping, Optional

import yaml

DESIGN_SETUP_ALLOWED_KEYS = frozenset({
    "cts_buffer_cells", "cts_buffer_cells_top", "cts_buffer_cells_leaf",
    "cts_inverter_cells", "cts_inverter_cells_top", "cts_inverter_cells_leaf",
    "cts_clock_gating_cells",
    "cts_target_skew", "cts_target_max_transition_time", "cts_max_fanout",
    "add_tieoffs_cells", "add_tieoffs_honor_dont_use",
    "add_tieoffs_max_fanout", "add_tieoffs_max_distance",
    "add_fillers_cells",
    "design_top_routing_layer", "design_bottom_routing_layer",
    "route_design_antenna_cell_name",
    "gds_layermap",
    "export_spef",
    "clock_routing_width_multiplier", "clock_routing_spacing_multiplier",
    "clock_routing_types",
    "active_views",
    "genus_set_db",
    "postsyn_netlists",
    "inject",
})


def design_setup_path(project_root: Path, design_name: str) -> Path:
    return Path(project_root) / "inputs" / "env" / design_name / f"setup.{design_name}.yaml"


_TOP_LEVEL_KEY_RE = re.compile(r"^#?( )?([A-Za-z_][A-Za-z0-9_]*):(\s|$)")
_SECTION_HEADER_RE = re.compile(r"^#[-=]{3,}\s*$")


def flow_design_setup_keys(template_path: Optional[Path]) -> frozenset[str]:
    """Every top-level key name a flow's own design-setup template
    declares -- a narrow regex over commented `# key: ...` lines at
    column 0, not a YAML parse (the template also has plain prose
    description lines that aren't valid YAML once merely uncommented,
    so parsing the whole file is the wrong tool here; only the key
    *names* are needed, not their example values). Matches a top-level
    key line only -- at most one space between a leading `#` (if any)
    and the key name; two or more spaces (or any indentation with no
    `#` at all) is a nested/continuation line, not another top-level
    key, the same distinction `_stanza_bounds` relies on. Returns an
    empty set for no template at all."""
    if template_path is None or not template_path.is_file():
        return frozenset()
    keys: set[str] = set()
    for line in template_path.read_text(encoding="utf-8").splitlines():
        match = _TOP_LEVEL_KEY_RE.match(line)
        if match:
            keys.add(match.group(2))
    return frozenset(keys)


def load_design_setup(path: Path, *, extra_keys: frozenset[str] = frozenset()) -> dict[str, Any]:
    """The raw, validated top-level mapping -- {} if the file doesn't exist
    yet, so every design-level knob falls back to its documented default,
    same as an absent backend.cadence-flowtool key did before this file
    existed. `extra_keys` -- a flow package's own declared design-setup
    keys for this environment (see flow_design_setup_keys) -- are allowed
    alongside WOLF's own `DESIGN_SETUP_ALLOWED_KEYS`, never written back
    into that shared, process-global set itself."""
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, Mapping):
        raise ValueError(f"{path}: must be a YAML mapping")
    unknown = set(data) - DESIGN_SETUP_ALLOWED_KEYS - extra_keys
    if unknown:
        raise ValueError(f"{path}: unsupported setup.yaml key: {sorted(unknown)[0]}")
    return dict(data)


def write_design_setup(
    path: Path, data: Mapping[str, Any], *, extra_keys: frozenset[str] = frozenset(),
) -> None:
    unknown = set(data) - DESIGN_SETUP_ALLOWED_KEYS - extra_keys
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


def _split_and_check(dotted_key: str, extra_keys: frozenset[str]) -> list[str]:
    parts = dotted_key.split(".")
    if not parts or not all(parts):
        raise ValueError(f"invalid setup key: {dotted_key!r}")
    if parts[0] not in DESIGN_SETUP_ALLOWED_KEYS and parts[0] not in extra_keys:
        raise ValueError(f"unsupported setup.yaml key: {parts[0]!r}")
    return parts


def _apply_dotted_value(data: dict, dotted_key: str, parts: list[str], value: Any) -> None:
    if value is None:
        _prune(data, parts)
        return
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
        if not isinstance(node, dict):
            raise ValueError(f"setup key parent is not a mapping: {dotted_key}")
    node[parts[-1]] = value


def set_design_setup_value(
    path: Path, dotted_key: str, value: Any, *, extra_keys: frozenset[str] = frozenset(),
) -> None:
    """Set (or, when value is None, remove and prune now-empty parents of)
    one dotted key in the design setup file -- rewrites the whole file
    via `write_design_setup` (plain `yaml.safe_dump`), dropping any
    comments the file had. `wolf env menu` still uses this for its own
    whole-dict save; `wolf env set`/`unset` use
    `set_design_setup_value_preserving_comments` instead."""
    parts = _split_and_check(dotted_key, extra_keys)
    data = load_design_setup(path, extra_keys=extra_keys)
    _apply_dotted_value(data, dotted_key, parts, value)
    write_design_setup(path, data, extra_keys=extra_keys)


def _comment_out_line(line: str) -> str:
    """Prefix one live line with `# `, preserving whatever indentation
    it already had -- a top-level line (no leading whitespace) becomes
    `# key: ...`; an indented continuation line (e.g. a dumped list's
    `- item`) becomes `#  - item`, matching the one-space-after-#-for-
    top-level, two-or-more-for-continuation convention
    `_TOP_LEVEL_KEY_RE` itself relies on."""
    if line.lstrip().startswith("#"):
        return line
    if line.startswith(" "):
        return "#" + line
    return "# " + line


def _stanza_bounds(lines: list[str], key: str) -> Optional[tuple[int, int]]:
    """The [start, end) line range -- the key's own declaration line
    (commented or not) through every immediately-following line that
    isn't blank, a `#---`/`#===` section header, or another top-level
    key's own declaration -- i.e. exactly its value and any YAML
    continuation lines, never the description/shape/default comment
    lines a WOLF-documented key has above it (those stay untouched
    regardless of the key's current value). A continuation line must
    also share the key line's own commented-ness (both commented, or
    both live) -- confirmed real need: a freestanding comment (a
    user's own note, or the next key's own description) sitting right
    after a *live* key with no blank line between them must stop the
    scan, not be swallowed as if it were part of that key's value."""
    for index, line in enumerate(lines):
        match = _TOP_LEVEL_KEY_RE.match(line)
        if match and match.group(2) == key:
            commented = line.lstrip().startswith("#")
            end = index + 1
            while end < len(lines):
                candidate = lines[end]
                if not candidate.strip() or _SECTION_HEADER_RE.match(candidate):
                    break
                if _TOP_LEVEL_KEY_RE.match(candidate):
                    break
                if candidate.lstrip().startswith("#") != commented:
                    break
                end += 1
            return index, end
    return None


def set_design_setup_value_preserving_comments(
    path: Path, dotted_key: str, value: Any, *, extra_keys: frozenset[str] = frozenset(),
) -> None:
    """Same set/unset semantics as `set_design_setup_value` (value=None
    removes and prunes now-empty parents), but edits the file's own
    text in place -- only the one top-level key's own stanza (its
    `key: value` line and any continuation lines, found by
    `_stanza_bounds`) is replaced; every other line, including a
    user's own added comments, is left byte-for-byte untouched, never
    reordered.

    A key still present after the update is written live (uncommented,
    a fresh `yaml.safe_dump` of just that one key); a key pruned away
    entirely has its existing stanza re-commented in place (prefixed
    with `# `) rather than deleted -- "comment it back out", not erase.
    A key with no existing stanza at all (an older file, or a key the
    template never got to generate yet) gets one appended at the end.

    No file yet at all: falls back to `write_design_setup` (nothing to
    preserve)."""
    parts = _split_and_check(dotted_key, extra_keys)
    key_root = parts[0]
    data = load_design_setup(path, extra_keys=extra_keys)
    _apply_dotted_value(data, dotted_key, parts, value)
    unknown = set(data) - DESIGN_SETUP_ALLOWED_KEYS - extra_keys
    if unknown:
        raise ValueError(f"unsupported setup.yaml key: {sorted(unknown)[0]}")

    if not path.is_file():
        write_design_setup(path, data, extra_keys=extra_keys)
        return

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    bounds = _stanza_bounds(lines, key_root)
    if key_root in data:
        replacement = yaml.safe_dump(
            {key_root: data[key_root]}, sort_keys=False,
        ).rstrip("\n").splitlines()
    elif bounds is not None:
        replacement = [_comment_out_line(line) for line in lines[bounds[0]:bounds[1]]]
    else:
        replacement = [f"# {key_root}:"]

    if bounds is None:
        new_lines = list(lines)
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.extend(replacement)
    else:
        start, end = bounds
        new_lines = lines[:start] + replacement + lines[end:]
    new_text = "\n".join(new_lines)
    if text.endswith("\n"):
        new_text += "\n"
    path.write_text(new_text, encoding="utf-8")

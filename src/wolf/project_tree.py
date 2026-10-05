"""Read-only inspection of a WOLF project root's inputs/outputs/workspace
tree, against the same convention `wolf env auto-setup` scaffolds.

Pure filesystem inspection, no caching, no Textual dependency -- safe to
import from both the `wolf env menu` wizard and any future `wolf`
subcommand. A later `.wolf` project metadata file (not built yet) is meant
to make repeat scans cheap by recording what was already found instead of
re-walking the tree every time; nothing here depends on that existing.

Never writes anything. Every function here only reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Per-design input categories, scaffolded as <project_root>/inputs/<category>/<design_name>
# (the "constraints" category is the one historical exception -- see
# _design_candidates_in_category's own handling). Mirrors the legacy
# `wolf env auto-setup` directory spec (bin/wolf.env), backend-agnostic: no
# files are created, only the directories every design's inputs are
# expected to live under. Must match wolf.commands.env's own copy.
PER_DESIGN_INPUT_CATEGORIES = ("calibre", "constraints", "env", "floorplans", "hdl", "scripts", "tb")
# Shared across all designs in a project, not nested under a design name.
SHARED_LIB_SUBDIRS = ("gds", "lef", "spice", "timing", "verilog")

_HDL_SUFFIXES = (".v", ".sv", ".vhd", ".vhdl")


def _design_candidates_in_category(category_dir: Path, category: str) -> dict[str, Path]:
    """Every design name this one category directory suggests, mapped to
    the matched path. A subdirectory named after the design is the usual
    shape (inputs/hdl/<design>/, inputs/tb/<design>/, ...); "constraints"
    is the one real exception found in practice -- a flat file named
    <design>.<anything> (e.g. <design>.constraints.sdc), not a
    subdirectory, in the legacy tree this was modeled against. Both
    shapes are accepted for every category, since a project started under
    one convention and continued under the other is a real, unremarkable
    case, not an error.
    """
    candidates: dict[str, Path] = {}
    if not category_dir.is_dir():
        return candidates
    for entry in sorted(category_dir.iterdir()):
        if entry.is_dir():
            candidates[entry.name] = entry
        elif entry.is_file():
            name = entry.name.split(".", 1)[0]
            if name:
                candidates.setdefault(name, entry)
    return candidates


@dataclass(frozen=True)
class CategoryScan:
    """One inputs/<category> directory's own scan result."""

    category: str
    exists: bool
    designs: dict[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectTreeScan:
    """The shallow, always-run structural scan of a project root: which of
    inputs/outputs/workspace exist, which categories inputs/ has, and
    which design names each category suggests -- cheap enough (a handful
    of listdir calls) to run unconditionally every time a project root is
    set, never skipped, matching how `wolf env auto-setup` itself treats
    this as the one true directory convention."""

    root: Path
    inputs_exists: bool
    outputs_exists: bool
    workspace_exists: bool
    categories: dict[str, CategoryScan]
    lib_subdirs: dict[str, bool]
    design_names: tuple[str, ...]

    def designs_missing_categories(self, design: str) -> tuple[str, ...]:
        """Which declared categories this design has nothing under --
        shown so an incomplete project (hdl present, constraints not
        written yet) is visibly incomplete, not silently treated as done."""
        return tuple(
            category for category in PER_DESIGN_INPUT_CATEGORIES
            if design not in self.categories[category].designs
        )


def scan_project_tree(root: Path) -> ProjectTreeScan:
    """The shallow structural scan: never returns None, even for a
    directory with nothing WOLF-shaped in it yet -- an all-missing,
    all-empty result is itself the answer ("nothing here"), not a reason
    to skip scanning."""
    inputs_dir = root / "inputs"
    categories: dict[str, CategoryScan] = {}
    all_names: set[str] = set()
    for category in PER_DESIGN_INPUT_CATEGORIES:
        category_dir = inputs_dir / category
        designs = _design_candidates_in_category(category_dir, category)
        categories[category] = CategoryScan(category=category, exists=category_dir.is_dir(), designs=designs)
        all_names.update(designs)
    lib_dir = inputs_dir / "lib"
    lib_subdirs = {name: (lib_dir / name).is_dir() for name in SHARED_LIB_SUBDIRS}
    return ProjectTreeScan(
        root=root,
        inputs_exists=inputs_dir.is_dir(),
        outputs_exists=(root / "outputs").is_dir(),
        workspace_exists=(root / "workspace").is_dir(),
        categories=categories,
        lib_subdirs=lib_subdirs,
        design_names=tuple(sorted(all_names)),
    )


@dataclass(frozen=True)
class DesignScan:
    """The deep, per-design scan triggered once a user actually picks a
    design name out of ProjectTreeScan.design_names: real HDL file lists,
    the real constraints path(s), and a cheap count of existing runs under
    outputs/ and workspace/ -- not their content (pass/fail, timing,
    ...), which is the planned per-run status metadata's job, not this
    read-only tree scan's."""

    design: str
    hdl_files: tuple[Path, ...]
    constraint_files: tuple[Path, ...]
    category_file_counts: dict[str, int]
    missing_categories: tuple[str, ...]
    output_run_count: int
    workspace_run_count: int


def _files_under(directory: Path, *, suffixes: Optional[tuple] = None) -> tuple[Path, ...]:
    if not directory.is_dir():
        return ()
    files = [
        entry for entry in sorted(directory.iterdir())
        if entry.is_file() and (not suffixes or entry.suffix.lower() in suffixes)
    ]
    return tuple(entry.resolve() for entry in files)


def _count_output_runs(outputs_dir: Path, design: str) -> int:
    design_dir = outputs_dir / design
    if not design_dir.is_dir():
        return 0
    return sum(1 for entry in design_dir.iterdir() if entry.is_dir())


def _count_workspace_runs(workspace_dir: Path, design: str) -> int:
    """Real run directories look like
    workspace/<design>/<design>.<process>/<design>.<N> (N an integer) --
    ".latest" symlinks and anything else alongside the numbered runs
    don't count as a run of their own."""
    design_dir = workspace_dir / design
    if not design_dir.is_dir():
        return 0
    count = 0
    for process_dir in design_dir.iterdir():
        if not process_dir.is_dir():
            continue
        for run_dir in process_dir.iterdir():
            if not run_dir.is_dir():
                continue
            suffix = run_dir.name.rsplit(".", 1)[-1]
            if suffix.isdigit():
                count += 1
    return count


def scan_design(root: Path, design: str) -> DesignScan:
    """The deep scan for one design name, called once it's actually
    picked (not for every candidate the shallow scan found -- that would
    mean walking every design's full file tree just to populate a
    picker)."""
    inputs_dir = root / "inputs"
    tree = scan_project_tree(root)

    hdl_dir = tree.categories["hdl"].designs.get(design)
    hdl_files = _files_under(hdl_dir, suffixes=_HDL_SUFFIXES) if hdl_dir else ()

    constraints_match = tree.categories["constraints"].designs.get(design)
    if constraints_match is None:
        constraint_files: tuple[Path, ...] = ()
    elif constraints_match.is_dir():
        constraint_files = _files_under(constraints_match)
    else:
        constraint_files = (constraints_match.resolve(),)

    category_file_counts = {
        category: len(_files_under(match)) if match and match.is_dir() else (1 if match else 0)
        for category, match in (
            (category, tree.categories[category].designs.get(design))
            for category in PER_DESIGN_INPUT_CATEGORIES
        )
    }

    return DesignScan(
        design=design,
        hdl_files=hdl_files,
        constraint_files=constraint_files,
        category_file_counts=category_file_counts,
        missing_categories=tree.designs_missing_categories(design),
        output_run_count=_count_output_runs(root / "outputs", design),
        workspace_run_count=_count_workspace_runs(root / "workspace", design),
    )

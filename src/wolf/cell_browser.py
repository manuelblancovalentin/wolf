"""Lazy, cached extraction of cell and routing-layer *names* (never file
paths or file contents) from a resolved technology's own LEF files, for
interactive picking in `wolf env menu`.

Nothing here ever prints or stores a library file path, a liberty/LEF
line, or any other vendor content -- only names (and area, from a LEF
MACRO's own SIZE line, when cheaply available). The extracted list is
cached once per resolved technology under WOLF's own state directory
(`wolf.paths.cache_dir()`, never the repo or a project's own tree) so
repeated menu interactions filter an already-parsed list instead of
re-scanning the real files every time.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Optional

from wolf.context import ResolvedTechnology
from wolf.paths import cache_dir


@dataclass(frozen=True)
class CellInfo:
    name: str
    area: Optional[float] = None  # um^2, from a LEF MACRO's own SIZE line


def _technology_cache_key(technology: ResolvedTechnology, files: tuple[Path, ...]) -> str:
    """A stable key for this exact resolved file set -- the technology's
    own package/revision/track/vth/metal_stack identity plus each file's
    own mtime, so a LEF changing on disk (a PDK package update) or a
    different track/vth/stack selection both naturally invalidate the
    cache without needing to re-hash file content."""
    identity = [technology.package, technology.revision, technology.track or "",
                technology.vth or "", technology.metal_stack or ""]
    for path in sorted(files, key=str):
        try:
            identity.append(f"{path}:{path.stat().st_mtime_ns}")
        except OSError:
            identity.append(f"{path}:missing")
    digest = hashlib.sha256("\n".join(identity).encode("utf-8")).hexdigest()[:24]
    return digest


def _cache_path(category: str, key: str) -> Path:
    return cache_dir() / "cells" / category / f"{key}.json"


def _read_cache(path: Path) -> Optional[list]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_cache(path: Path, payload: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _iter_lef_lines(path: Path):
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                yield line.strip()
    except OSError:
        return


def _extract_lef_macros(path: Path) -> list[CellInfo]:
    """Cheap line scan for `MACRO <name>` ... `SIZE <w> BY <h>` ...
    `END <name>` blocks -- never loads the whole file, never returns
    anything but the macro name and its bounding-box area."""
    cells: list[CellInfo] = []
    name: Optional[str] = None
    width = height = None
    for line in _iter_lef_lines(path):
        if line.startswith("MACRO "):
            parts = line.split()
            name = parts[1] if len(parts) > 1 else None
            width = height = None
        elif name and line.startswith("SIZE "):
            parts = line.split()
            try:
                width, height = float(parts[1]), float(parts[3])
            except (IndexError, ValueError):
                width = height = None
        elif name and line.startswith("END ") and line.split()[1:2] == [name]:
            area = width * height if width is not None and height is not None else None
            cells.append(CellInfo(name, area))
            name = None
    return cells


def _extract_lef_routing_layers(path: Path) -> list[str]:
    """Cheap line scan for `LAYER <name>` ... `TYPE ROUTING` ...
    `END <name>` blocks -- routing layers only (cut/implant/etc. layers
    are also declared this way in a tech LEF but are not routable)."""
    layers: list[str] = []
    name: Optional[str] = None
    is_routing = False
    for line in _iter_lef_lines(path):
        if line.startswith("LAYER "):
            parts = line.split()
            name = parts[1] if len(parts) > 1 else None
            is_routing = False
        elif name and line.startswith("TYPE "):
            is_routing = "ROUTING" in line.upper()
        elif name and line.startswith("END ") and line.split()[1:2] == [name]:
            if is_routing:
                layers.append(name)
            name = None
    return layers


def cells_for_technology(
    technology: Optional[ResolvedTechnology], on_file=None,
) -> Optional[list[CellInfo]]:
    """Every cell name (standard cell or macro) declared by the resolved
    technology's own LEF files, cached per resolved file set. Returns
    None -- "not resolvable, fall back to free text" -- when there is no
    technology selected or it declares no LEF at all; callers must not
    treat None the same as "no cells" (an empty list).

    `on_file`, if given, is called with each file's own Path right before
    it is actually scanned -- never called at all on a cache hit, so a
    caller driving a "Parsing <file>" progress indicator only sees it
    when a real (slow, first-time) scan is about to happen.
    """
    if technology is None:
        return None
    files = tuple(dict.fromkeys((*technology.cell_lefs, *technology.technology_lefs)))
    if not files:
        return None
    key = _technology_cache_key(technology, files)
    path = _cache_path("macros", key)
    cached = _read_cache(path)
    if cached is not None:
        return [CellInfo(item["name"], item.get("area")) for item in cached]
    merged: dict[str, CellInfo] = {}
    for file in files:
        if on_file:
            on_file(file)
        for cell in _extract_lef_macros(file):
            merged.setdefault(cell.name, cell)
    result = sorted(merged.values(), key=lambda cell: cell.name)
    _write_cache(path, [{"name": cell.name, "area": cell.area} for cell in result])
    return result


def routing_layers_for_technology(
    technology: Optional[ResolvedTechnology], on_file=None,
) -> Optional[list[str]]:
    """Every routing layer name declared by the resolved technology's own
    LEF files (technology_lefs normally carries the tech LEF; cell_lefs
    rarely declares layers itself but is scanned too, harmlessly, for a
    package that merges both into one file). None when not resolvable.
    `on_file`: see cells_for_technology -- same cache-hit-skips-it rule."""
    if technology is None:
        return None
    files = tuple(dict.fromkeys((*technology.technology_lefs, *technology.cell_lefs)))
    if not files:
        return None
    key = _technology_cache_key(technology, files)
    path = _cache_path("layers", key)
    cached = _read_cache(path)
    if cached is not None:
        return list(cached)
    merged: dict[str, None] = {}
    for file in files:
        if on_file:
            on_file(file)
        for layer in _extract_lef_routing_layers(file):
            merged.setdefault(layer, None)
    result = sorted(merged)
    _write_cache(path, result)
    return result


def analysis_view_names_for_technology(technology: Optional[ResolvedTechnology]) -> Optional[list[str]]:
    """Declared analysis-view (timing corner) names -- already fully
    resolved on `technology.timing_corners`, the exact same name set
    `_active_views_overrides` validates `active_views.{setup,hold}`
    against, so no file scanning (or caching) is needed at all here.
    None when the technology has no named corners (a flat package)."""
    if technology is None or not technology.timing_corners:
        return None
    return sorted({corner.name for corner in technology.timing_corners})

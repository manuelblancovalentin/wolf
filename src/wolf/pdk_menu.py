"""A real full-screen `wolf pdk menu NAME`, a PDK registry manifest editor.

Kept separate from `wolf.commands.pdk` so Textual is only imported when this
specific subcommand actually runs (same reason `wolf.env_menu` is its own
module).

Creates a new `pdk/<name>` registry manifest, or edits an existing one in
place. Works entirely off the manifest's own raw YAML document in memory
(loaded once, written back atomically on save) -- the deep
`metadata.technology` structure this edits (tracks/vths/corners/physical
and behavioral file lists, plus a free-form `generic` bucket for whatever
doesn't depend on track/vth at all) is deliberately left lenient while
editing: a track with no vths yet, or a vth with no corners yet, is normal
mid-edit state, not an error -- the strict shape `_technology_inputs`
requires is only enforced later, when an environment actually resolves
this package (see wolf.environment).

Every file/directory picker remembers the last directory it was used in
(App.last_browsed_dir) and starts there next time, rather than restarting
from the package root every time -- real PDK trees keep lib/lef/gds/qrc
for the same corner near each other, so jumping back to the same
neighborhood across several consecutive picks (libraries, then that
corner's qrc file, then the next corner) is the common case. That starting
directory is never a hard boundary, though: 'u' climbs one level at a
time from wherever the tree is currently rooted, since a corner's QRC
techfile just as often lives in a sibling directory as the libraries
picked moments earlier, not the same one. The file browser also takes
'r' to narrow file names to those matching a regex -- real libraries
pack dozens of track/vth/corner variants into one directory, and this is
for picking the one `.lib` you actually want out of that.

NAME is optional: `wolf pdk menu` with none picks from existing pdk/*
packages (or offers to create one). A given NAME may also be a dotted
path into one package's own tracks/vths -- `tsmc65`, `tsmc65.9T`, or
`tsmc65.9T.lvt` -- to jump straight to that level instead of starting at
the top of the package's own menu; shell completion offers all three
forms (see wolf.commands.pdk._candidates).
"""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Optional

import yaml
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Footer, Header, Input, OptionList, Static
from textual.widgets.option_list import Option

from wolf.package.model import PackageId
from wolf.package.registry import PackageRegistry, load_manifest
from wolf.registry import RegistryManager


def _open_in_editor(app: App, path: Path) -> None:
    """Suspend the TUI and open a file in $EDITOR (vim by default)."""
    editor = os.environ.get("EDITOR", "vim")
    try:
        with app.suspend():
            subprocess.run([editor, str(path)])
    except Exception as error:  # SuspendNotSupported, or the editor itself failing
        app.notify(f"could not open {path} in {editor!r}: {error}", severity="error")


class _TextScreen(ModalScreen[Optional[str]]):
    def __init__(self, title: str, initial: str = "", hint: str = "enter to submit — esc to cancel"):
        super().__init__()
        self._title = title
        self._initial = initial
        self._hint = hint

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield Input(value=self._initial, id="value")
            yield Static(self._hint, id="dialog-hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


class _PickScreen(ModalScreen[Optional[str]]):
    """Pick one id out of a list of (label, id) choices. See wolf.env_menu's
    own copy of this screen for the rationale (kept separate -- see module
    docstring)."""

    def __init__(
        self, title: str, choices: list[tuple[str, str]], details: Optional[dict] = None,
    ):
        super().__init__()
        self._title = title
        self._choices = choices
        self._details = details or {}

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*(Option(label, id=key) for label, key in self._choices))
            initial = self._choices[0][1] if self._choices else None
            yield Static(self._hint(initial), id="dialog-hint")

    def _hint(self, option_id: Optional[str]) -> str:
        base = "enter to choose — esc to cancel"
        detail = self._details.get(option_id) if option_id is not None else None
        return f"{detail}\n{base}" if detail else base

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self.query_one("#dialog-hint", Static).update(self._hint(event.option_id))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option_id)

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


class _FilterableDirectoryTree(DirectoryTree):
    """A DirectoryTree that can hide dotfiles/dotdirs, and narrow file names
    by regex, both toggled at runtime. Directories are never hidden by the
    regex filter (only by the dotfile toggle) -- it narrows what files you
    see while picking, not where you can navigate; applying the same regex
    at every level means it stays in effect as you move around, not just
    in the directory it was set in."""

    show_hidden = False
    name_filter: Optional[re.Pattern] = None

    def filter_paths(self, paths):
        if not self.show_hidden:
            paths = [path for path in paths if not path.name.startswith(".")]
        if self.name_filter is not None:
            paths = [
                path for path in paths
                if self._safe_is_dir(path) or self.name_filter.search(path.name)
            ]
        return paths


def _parent_or_none(path: str) -> Optional[str]:
    """The directory above `path`, or None if `path` is already a
    filesystem root (so "go up" can stop offering to climb further)."""
    resolved = Path(path).expanduser().resolve()
    parent = resolved.parent
    return None if parent == resolved else str(parent)


class _BrowseFilesScreen(ModalScreen[Optional[list]]):
    """Browse the filesystem and collect one or more file paths, of any
    suffix -- a PDK tree mixes .lib/.lef/.gds/.v/.spi/.captable files, so
    unlike wolf.env_menu's RTL-only browser this never filters by suffix.

    'a' adds the highlighted file, or every file directly inside the
    highlighted directory; 'u' climbs one directory level, so the tree
    being rooted at the last directory used (for convenience -- see
    App.last_browsed_dir) never traps you there, since a corner's QRC
    techfile just as often lives in a sibling directory as the libraries
    you picked moments earlier, not the same one; 'r' narrows the file
    names shown to those matching a regex (directories stay visible so
    you can still navigate through them; submit an empty pattern to
    clear it) -- real libraries keep dozens of track/vth/corner variants
    in one directory, and picking the one `.lib` you actually want out of
    that is the common case this is for; 'h' toggles hidden (dot) entries,
    off by default; enter on a file opens it in $EDITOR to inspect it
    rather than adding it (adding is always an explicit 'a'); escape
    finishes, returning whatever was added (possibly empty).
    """

    BINDINGS = [
        ("a", "add", "Add"),
        ("u", "up", "Up a level"),
        ("r", "filter", "Filter (regex)"),
        ("h", "toggle_hidden", "Hidden files"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, start: str, *, title: str = "Browse for files"):
        super().__init__()
        self._start = start
        self._title = title
        self._selected: list[str] = []
        self._show_hidden = False
        self._name_filter: Optional[re.Pattern] = None

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            tree = _FilterableDirectoryTree(self._start, id="browse-tree")
            tree.show_hidden = self._show_hidden
            yield tree
            yield Static(self._hint(), id="dialog-hint")

    def _hint(self) -> str:
        picked = f"{len(self._selected)} file(s) picked" if self._selected else "none picked yet"
        hidden = "shown" if self._show_hidden else "hidden"
        filtered = f"/{self._name_filter.pattern}/" if self._name_filter else "none"
        return (
            f"{picked} — enter: expand folder / edit file in $EDITOR — a: add — "
            f"u: up a level — r: filter (currently {filtered}) — "
            f"h: toggle dotfiles (currently {hidden}) — esc: done"
        )

    def _refresh_hint(self) -> None:
        self.query_one("#dialog-hint", Static).update(self._hint())

    def action_toggle_hidden(self) -> None:
        self._show_hidden = not self._show_hidden
        tree = self.query_one(DirectoryTree)
        tree.show_hidden = self._show_hidden
        tree.reload()
        self._refresh_hint()

    def action_up(self) -> None:
        tree = self.query_one(DirectoryTree)
        parent = _parent_or_none(str(tree.path))
        if parent is None:
            self.app.notify("Already at the top of the filesystem.", severity="warning")
            return
        tree.path = parent

    def action_filter(self) -> None:
        current = self._name_filter.pattern if self._name_filter else ""

        def handle(value: Optional[str]) -> None:
            if value is None:
                return  # cancelled -- keep whatever filter was already set
            value = value.strip()
            if not value:
                self._name_filter = None
                self.app.notify("Filter cleared.")
            else:
                try:
                    self._name_filter = re.compile(value)
                except re.error as error:
                    self.app.notify(f"Invalid regex: {error}", severity="error")
                    return
                self.app.notify(f"Filtering file names by /{value}/")
            tree = self.query_one(DirectoryTree)
            tree.name_filter = self._name_filter
            tree.reload()
            self._refresh_hint()

        self.app.push_screen(
            _TextScreen(
                "Filter file names by regex (submit empty to clear)",
                current,
            ),
            handle,
        )

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()
        _open_in_editor(self.app, event.path)

    def action_add(self) -> None:
        tree = self.query_one(DirectoryTree)
        node = tree.cursor_node
        if node is None:
            return
        path = node.data.path
        if path.is_dir():
            added = 0
            for entry in sorted(path.iterdir()):
                if entry.is_file() and (self._name_filter is None or self._name_filter.search(entry.name)):
                    resolved = str(entry.resolve())
                    if resolved not in self._selected:
                        self._selected.append(resolved)
                        added += 1
            if added:
                self.app.notify(f"Added {added} file(s) from {path}")
            else:
                self.app.notify("No new files in that directory.", severity="warning")
        else:
            resolved = str(path.resolve())
            if resolved in self._selected:
                self.app.notify(f"{path.name} is already picked.", severity="warning")
            else:
                self._selected.append(resolved)
                self.app.notify(f"Added {path.name}")
        self._refresh_hint()

    def action_done(self) -> None:
        self.dismiss(self._selected)


class _BrowseDirectoryScreen(ModalScreen[Optional[str]]):
    """Browse the filesystem and pick one directory (e.g. a package's
    local-path source root). See wolf.env_menu's own copy for the
    rationale (kept separate -- see module docstring)."""

    BINDINGS = [
        ("a", "select", "Use this directory"),
        ("u", "up", "Up a level"),
        ("h", "toggle_hidden", "Hidden files"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, start: str, *, title: str = "Browse for a directory"):
        super().__init__()
        self._start = start
        self._title = title
        self._show_hidden = False

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            tree = _FilterableDirectoryTree(self._start, id="browse-tree")
            tree.show_hidden = self._show_hidden
            yield tree
            yield Static(self._hint(), id="dialog-hint")

    def _hint(self) -> str:
        hidden = "shown" if self._show_hidden else "hidden"
        return (
            f"enter: expand folder — a: use this directory — u: up a level — "
            f"h: toggle dotfiles (currently {hidden}) — esc: cancel"
        )

    def _refresh_hint(self) -> None:
        self.query_one("#dialog-hint", Static).update(self._hint())

    def action_toggle_hidden(self) -> None:
        self._show_hidden = not self._show_hidden
        tree = self.query_one(DirectoryTree)
        tree.show_hidden = self._show_hidden
        tree.reload()
        self._refresh_hint()

    def action_up(self) -> None:
        tree = self.query_one(DirectoryTree)
        parent = _parent_or_none(str(tree.path))
        if parent is None:
            self.app.notify("Already at the top of the filesystem.", severity="warning")
            return
        tree.path = parent

    def _highlighted_directory(self) -> Optional[Path]:
        node = self.query_one(DirectoryTree).cursor_node
        if node is None:
            return None
        path = node.data.path
        return path if path.is_dir() else path.parent

    def action_select(self) -> None:
        directory = self._highlighted_directory()
        if directory is not None:
            self.dismiss(str(directory.resolve()))

    def action_cancel(self) -> None:
        self.dismiss(None)


def _relative_or_absolute(root: Path, path: Path) -> str:
    """Store a path relative to the package root when possible, matching
    how technology.* fields are declared (see wolf.environment's
    _paths_under) -- absolute only if it genuinely falls outside root."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)


class _FileListScreen(ModalScreen[Optional[list]]):
    """Edit one named list of files (LEF, GDS, verilog models, a corner's
    libraries, ...): 'a' browses to add one or more, 'd' deletes the
    highlighted entry, esc finishes and returns the (possibly reordered by
    add-order) list."""

    BINDINGS = [
        ("a", "add", "Add"),
        ("d", "delete", "Delete"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, title: str, root: Path, values: list[str]):
        super().__init__()
        self._title = title
        self._root = root
        self._values = list(values)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*self._options())
            yield Static(self._hint(), id="dialog-hint")

    def _options(self) -> list[Option]:
        if not self._values:
            return [Option("(none yet -- press a to add)", id="__empty__", disabled=True)]
        return [Option(value, id=str(index)) for index, value in enumerate(self._values)]

    def _hint(self) -> str:
        return f"{len(self._values)} file(s) — a: add — d: delete highlighted — esc: done"

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)
        self.query_one("#dialog-hint", Static).update(self._hint())

    def action_add(self) -> None:
        start = self.app.last_browsed_dir or str(self._root)

        def handle(paths: Optional[list]) -> None:
            if not paths:
                return
            added = 0
            for raw in paths:
                relative = _relative_or_absolute(self._root, Path(raw))
                if relative not in self._values:
                    self._values.append(relative)
                    added += 1
            self.app.last_browsed_dir = str(Path(paths[-1]).parent)
            if added:
                self.app.notify(f"Added {added} entr{'y' if added == 1 else 'ies'}")
            self._refresh()
        self.app.push_screen(_BrowseFilesScreen(start, title=self._title), handle)

    def action_delete(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or not self._values:
            return
        del self._values[option_list.highlighted]
        self._refresh()

    def action_done(self) -> None:
        self.dismiss(self._values)


class _SingleFileScreen(ModalScreen[Optional[str]]):
    """Pick (or clear) one optional file, e.g. a corner's qrc_tech_file."""

    def __init__(self, title: str, root: Path, value: Optional[str]):
        super().__init__()
        self._title = title
        self._root = root
        self._value = value

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(
                Option(f"Current: {self._value}" if self._value else "(not set)", id="current"),
                Option("Browse to pick a file", id="browse"),
                Option("Clear", id="clear"),
            )
            yield Static("enter to choose — esc to cancel", id="dialog-hint")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id == "browse":
            start = self.app.last_browsed_dir or str(self._root)

            def handle(paths: Optional[list]) -> None:
                if paths:
                    self.app.last_browsed_dir = str(Path(paths[-1]).parent)
                    self.dismiss(_relative_or_absolute(self._root, Path(paths[-1])))
                else:
                    self.dismiss(None)
            self.app.push_screen(_BrowseFilesScreen(start, title=self._title), handle)
        elif event.option_id == "clear":
            self.dismiss("")
        else:
            self.dismiss(None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


class _StringListScreen(ModalScreen[Optional[list]]):
    """Edit one list of plain strings (e.g. dont_use cell globs) -- typed
    in, not browsed."""

    BINDINGS = [
        ("a", "add", "Add"),
        ("d", "delete", "Delete"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, title: str, values: list[str]):
        super().__init__()
        self._title = title
        self._values = list(values)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*self._options())
            yield Static(self._hint(), id="dialog-hint")

    def _options(self) -> list[Option]:
        if not self._values:
            return [Option("(none yet -- press a to add)", id="__empty__", disabled=True)]
        return [Option(value, id=str(index)) for index, value in enumerate(self._values)]

    def _hint(self) -> str:
        return f"{len(self._values)} entr{'y' if len(self._values) == 1 else 'ies'} — a: add — d: delete highlighted — esc: done"

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)
        self.query_one("#dialog-hint", Static).update(self._hint())

    def action_add(self) -> None:
        def handle(value: Optional[str]) -> None:
            if value:
                self._values.append(value)
                self._refresh()
        self.app.push_screen(_TextScreen(self._title), handle)

    def action_delete(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or not self._values:
            return
        del self._values[option_list.highlighted]
        self._refresh()

    def action_done(self) -> None:
        self.dismiss(self._values)


class _CornerEditScreen(ModalScreen[Optional[dict]]):
    """Edit one corner: its libraries and optional qrc_tech_file."""

    BINDINGS = [("escape", "done", "Done")]

    def __init__(self, name: str, root: Path, data: dict):
        super().__init__()
        self._name = name
        self._root = root
        self._data = dict(data)
        self._data.setdefault("libraries", [])

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(f"Corner: {self._name}", id="dialog-title")
            yield OptionList(*self._options())
            yield Static("enter: edit — esc: done", id="dialog-hint")

    def _options(self) -> list[Option]:
        libraries = self._data.get("libraries", [])
        qrc = self._data.get("qrc_tech_file")
        library_format = self._data.get("format", "liberty")
        return [
            Option(f"Libraries ({len(libraries)} file(s))", id="libraries"),
            Option(f"Format: {library_format}", id="format"),
            Option(f"QRC tech file: {qrc or 'not set'}", id="qrc_tech_file"),
        ]

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id == "libraries":
            def handle(values: Optional[list]) -> None:
                if values is not None:
                    self._data["libraries"] = values
                    self._refresh()
            self.app.push_screen(
                _FileListScreen(
                    f"Libraries for corner {self._name}", self._root, self._data.get("libraries", []),
                ),
                handle,
            )
        elif event.option_id == "format":
            def handle(value: Optional[str]) -> None:
                if value:
                    self._data["format"] = value
                    self._refresh()
            self.app.push_screen(
                _TextScreen(
                    "Library format (e.g. liberty, ecsm, variation/aocv-socv)",
                    self._data.get("format", "liberty"),
                ),
                handle,
            )
        elif event.option_id == "qrc_tech_file":
            def handle(value: Optional[str]) -> None:
                if value is not None:
                    if value:
                        self._data["qrc_tech_file"] = value
                    else:
                        self._data.pop("qrc_tech_file", None)
                    self._refresh()
            self.app.push_screen(
                _SingleFileScreen(
                    f"QRC tech file for corner {self._name}", self._root,
                    self._data.get("qrc_tech_file"),
                ),
                handle,
            )

    def action_done(self) -> None:
        self.dismiss(self._data)


class _CornersScreen(ModalScreen[Optional[dict]]):
    """Edit the named corners for one track/vth."""

    BINDINGS = [
        ("a", "add", "Add corner"),
        ("d", "delete", "Delete corner"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, title: str, root: Path, corners: dict):
        super().__init__()
        self._title = title
        self._root = root
        self._corners = dict(corners)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*self._options())
            yield Static(self._hint(), id="dialog-hint")

    def _options(self) -> list[Option]:
        if not self._corners:
            return [Option("(none yet -- press a to add)", id="__empty__", disabled=True)]
        return [
            Option(f"{name} ({len(data.get('libraries', []))} lib file(s))", id=name)
            for name, data in self._corners.items()
        ]

    def _hint(self) -> str:
        return f"{len(self._corners)} corner(s) — enter: edit — a: add — d: delete highlighted — esc: done"

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)
        self.query_one("#dialog-hint", Static).update(self._hint())

    def _edit(self, name: str) -> None:
        def handle(data: Optional[dict]) -> None:
            if data is not None:
                self._corners[name] = data
                self._refresh()
        self.app.push_screen(_CornerEditScreen(name, self._root, self._corners.get(name, {})), handle)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id and event.option_id != "__empty__":
            self._edit(event.option_id)

    def action_add(self) -> None:
        def handle(name: Optional[str]) -> None:
            if not name:
                return
            if name in self._corners:
                self.app.notify(f"Corner {name!r} already exists.", severity="warning")
                return
            self._corners[name] = {"libraries": []}
            self._refresh()
            self._edit(name)
        self.app.push_screen(_TextScreen("Corner name (e.g. typical, worst_case)"), handle)

    def action_delete(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or not self._corners:
            return
        name = list(self._corners)[option_list.highlighted]
        del self._corners[name]
        self._refresh()

    def action_done(self) -> None:
        self.dismiss(self._corners)


def _all_timing_corner_names(technology: dict) -> list[str]:
    """Every PVT timing-corner name declared anywhere in this package,
    across every track/vth -- corner names are universal vocabulary (the
    same name means the same PVT skew everywhere it's used), so a
    delay_corner only needs to reference one by name, not by track/vth.
    Must match wolf.environment's own _collect_timing_corner_names."""
    names: set = set()
    for track_data in technology.get("tracks", {}).values():
        if not isinstance(track_data, dict):
            continue
        for vth_data in track_data.get("vths", {}).values():
            if not isinstance(vth_data, dict):
                continue
            corners = vth_data.get("timing", {})
            corners = corners.get("corners", {}) if isinstance(corners, dict) else {}
            if isinstance(corners, dict):
                names.update(corners)
    return sorted(names)


def _all_rc_corner_names(technology: dict) -> list[str]:
    """Every named RC-extraction corner declared anywhere in this
    package, across every track/vth/metal-stack -- same universal-
    vocabulary assumption as _all_timing_corner_names. Must match
    wolf.environment's own _collect_rc_corner_names."""
    names: set = set()
    for track_data in technology.get("tracks", {}).values():
        if not isinstance(track_data, dict):
            continue
        for vth_data in track_data.get("vths", {}).values():
            if not isinstance(vth_data, dict):
                continue
            qrc = vth_data.get("qrc_techfiles")
            if isinstance(qrc, dict):
                for stack_corners in qrc.values():
                    if isinstance(stack_corners, dict):
                        names.update(stack_corners)
    return sorted(names)


def _all_delay_corner_names(technology: dict) -> list[str]:
    delay_corners = technology.get("delay_corners", {})
    return sorted(delay_corners) if isinstance(delay_corners, dict) else []


class _OpcondsScreen(ModalScreen[Optional[dict]]):
    """Edit the named operating conditions (create_opcond's own process/
    voltage/temperature) a timing corner may optionally reference. Real
    .lib files almost always embed this already (confirmed unused in a
    real legacy flow this schema is modeled on), so this exists for
    completeness -- declared once, optionally linked from elsewhere --
    not because every corner needs one."""

    BINDINGS = [
        ("a", "add", "Add opcond"),
        ("d", "delete", "Delete opcond"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, title: str, opconds: dict):
        super().__init__()
        self._title = title
        self._opconds = dict(opconds)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*self._options())
            yield Static(self._hint(), id="dialog-hint")

    def _options(self) -> list[Option]:
        if not self._opconds:
            return [Option("(none yet -- press a to add)", id="__empty__", disabled=True)]
        return [
            Option(
                f"{name} (process={data.get('process', '?')}, voltage={data.get('voltage', '?')}, "
                f"temperature={data.get('temperature', '?')})",
                id=name,
            )
            for name, data in self._opconds.items()
        ]

    def _hint(self) -> str:
        return f"{len(self._opconds)} opcond(s) — enter: edit — a: add — d: delete highlighted — esc: done"

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)
        self.query_one("#dialog-hint", Static).update(self._hint())

    def _edit(self, name: str) -> None:
        def handle(data: Optional[dict]) -> None:
            if data is not None:
                self._opconds[name] = data
                self._refresh()
        self.app.push_screen(_OpcondEditScreen(name, self._opconds.get(name, {})), handle)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id and event.option_id != "__empty__":
            self._edit(event.option_id)

    def action_add(self) -> None:
        def handle(name: Optional[str]) -> None:
            if not name:
                return
            if name in self._opconds:
                self.app.notify(f"Opcond {name!r} already exists.", severity="warning")
                return
            self._opconds[name] = {}
            self._refresh()
            self._edit(name)
        self.app.push_screen(_TextScreen("Opcond name (e.g. typ_1p2_25c)"), handle)

    def action_delete(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or not self._opconds:
            return
        name = list(self._opconds)[option_list.highlighted]
        del self._opconds[name]
        self._refresh()

    def action_done(self) -> None:
        self.dismiss(self._opconds)


class _OpcondEditScreen(ModalScreen[Optional[dict]]):
    """Edit one opcond's process/voltage/temperature -- free-text fields,
    since create_opcond's own values and units vary (e.g. 1.0 vs 1, 25
    vs "25C")."""

    BINDINGS = [("escape", "done", "Done")]

    def __init__(self, name: str, data: dict):
        super().__init__()
        self._name = name
        self._data = dict(data)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._name, id="dialog-title")
            yield OptionList(*self._options())
            yield Static("enter: edit field — esc: done", id="dialog-hint")

    def _options(self) -> list[Option]:
        return [
            Option(f"Process: {self._data.get('process', 'unset')}", id="process"),
            Option(f"Voltage: {self._data.get('voltage', 'unset')}", id="voltage"),
            Option(f"Temperature: {self._data.get('temperature', 'unset')}", id="temperature"),
        ]

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        field = event.option_id

        def handle(value: Optional[str]) -> None:
            if value is not None:
                self._data[field] = value
                self._refresh()
        self.app.push_screen(_TextScreen(f"{field.title()} value", str(self._data.get(field, ""))), handle)

    def action_done(self) -> None:
        self.dismiss(self._data)


class _DelayCornersScreen(ModalScreen[Optional[dict]]):
    """Edit the named delay corners a package declares -- each one a
    pairing of a declared PVT timing-corner name and a declared RC-
    extraction-corner name, the exact pairing a real delay_corner is
    (one rc_corner, one timing_condition). Creating one requires at
    least one of each to already exist -- an empty picker warns and
    aborts rather than letting you reference a name that doesn't exist
    yet, the same linked-dependency guard _AnalysisViewsScreen applies
    one level up."""

    BINDINGS = [
        ("a", "add", "Add delay corner"),
        ("d", "delete", "Delete delay corner"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, title: str, technology: dict, delay_corners: dict):
        super().__init__()
        self._title = title
        self._technology = technology
        self._delay_corners = dict(delay_corners)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*self._options())
            yield Static(self._hint(), id="dialog-hint")

    def _options(self) -> list[Option]:
        if not self._delay_corners:
            return [Option("(none yet -- press a to add)", id="__empty__", disabled=True)]
        return [
            Option(
                f"{name} (timing_corner={data.get('timing_corner', '?')}, "
                f"rc_corner={data.get('rc_corner', '?')})",
                id=name,
            )
            for name, data in self._delay_corners.items()
        ]

    def _hint(self) -> str:
        return (
            f"{len(self._delay_corners)} delay corner(s) — enter: edit — a: add — "
            f"d: delete highlighted — esc: done"
        )

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)
        self.query_one("#dialog-hint", Static).update(self._hint())

    def _pick_pairing(self, on_done) -> None:
        timing_names = _all_timing_corner_names(self._technology)
        if not timing_names:
            self.app.notify(
                "No timing corners declared yet -- add one under Tracks or Front-End "
                "before creating a delay corner.", severity="warning",
            )
            return
        rc_names = _all_rc_corner_names(self._technology)
        if not rc_names:
            self.app.notify(
                "No RC-extraction corners declared yet -- add one under Back-End / LEF "
                "/ Techfiles before creating a delay corner.", severity="warning",
            )
            return

        def handle_timing(timing_corner: Optional[str]) -> None:
            if timing_corner is None:
                return

            def handle_rc(rc_corner: Optional[str]) -> None:
                if rc_corner is None:
                    return
                on_done({"timing_corner": timing_corner, "rc_corner": rc_corner})
            self.app.push_screen(
                _PickScreen("RC-extraction corner", [(n, n) for n in rc_names]), handle_rc,
            )
        self.app.push_screen(
            _PickScreen("PVT timing corner", [(n, n) for n in timing_names]), handle_timing,
        )

    def _edit(self, name: str) -> None:
        def handle(data: dict) -> None:
            self._delay_corners[name] = data
            self._refresh()
        self._pick_pairing(handle)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id and event.option_id != "__empty__":
            self._edit(event.option_id)

    def action_add(self) -> None:
        def handle(name: Optional[str]) -> None:
            if not name:
                return
            if name in self._delay_corners:
                self.app.notify(f"Delay corner {name!r} already exists.", severity="warning")
                return
            self._edit(name)
        self.app.push_screen(_TextScreen("Delay corner name (e.g. wc_rcworst)"), handle)

    def action_delete(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or not self._delay_corners:
            return
        name = list(self._delay_corners)[option_list.highlighted]
        del self._delay_corners[name]
        self._refresh()

    def action_done(self) -> None:
        self.dismiss(self._delay_corners)


_ANALYSIS_VIEW_FLAGS = (
    ("is_setup", "Setup"), ("is_hold", "Hold"), ("is_dynamic", "Dynamic"), ("is_leakage", "Leakage"),
)


class _AnalysisViewFlagsScreen(ModalScreen[dict]):
    """Toggle which kind(s) of analysis one analysis_view drives --
    setup/hold/dynamic/leakage, matching create_analysis_view's own
    flags. enter toggles the highlighted flag; escape finishes with
    whatever's currently set (even all-off, though that's unusual)."""

    BINDINGS = [("escape", "done", "Done")]

    def __init__(self, title: str, data: dict):
        super().__init__()
        self._title = title
        self._flags = {key: bool(data.get(key, False)) for key, _ in _ANALYSIS_VIEW_FLAGS}

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*self._options())
            yield Static("enter: toggle highlighted — esc: done", id="dialog-hint")

    def _options(self) -> list[Option]:
        return [
            Option(f"[{'x' if self._flags[key] else ' '}] {label}", id=key)
            for key, label in _ANALYSIS_VIEW_FLAGS
        ]

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        highlighted = option_list.highlighted
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)
        option_list.highlighted = highlighted

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        key = event.option_id
        self._flags[key] = not self._flags[key]
        self._refresh()

    def action_done(self) -> None:
        self.dismiss(self._flags)


class _AnalysisViewsScreen(ModalScreen[Optional[dict]]):
    """Edit the named analysis views a package declares -- each one a
    declared delay_corner plus which kind(s) of analysis it drives,
    matching create_analysis_view's own flags. constraint_mode is
    deliberately not here: it's a design-level pairing (which SDC a view
    uses), resolved at run time from the environment, not declared
    statically per PDK."""

    BINDINGS = [
        ("a", "add", "Add analysis view"),
        ("d", "delete", "Delete analysis view"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, title: str, technology: dict, analysis_views: dict):
        super().__init__()
        self._title = title
        self._technology = technology
        self._analysis_views = dict(analysis_views)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*self._options())
            yield Static(self._hint(), id="dialog-hint")

    def _flag_summary(self, data: dict) -> str:
        active = [label for key, label in _ANALYSIS_VIEW_FLAGS if data.get(key)]
        return "+".join(active) if active else "none"

    def _options(self) -> list[Option]:
        if not self._analysis_views:
            return [Option("(none yet -- press a to add)", id="__empty__", disabled=True)]
        return [
            Option(f"{name} (delay_corner={data.get('delay_corner', '?')}, {self._flag_summary(data)})", id=name)
            for name, data in self._analysis_views.items()
        ]

    def _hint(self) -> str:
        return (
            f"{len(self._analysis_views)} analysis view(s) — enter: edit — a: add — "
            f"d: delete highlighted — esc: done"
        )

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)
        self.query_one("#dialog-hint", Static).update(self._hint())

    def _edit(self, name: str) -> None:
        delay_corner_names = _all_delay_corner_names(self._technology)
        if not delay_corner_names:
            self.app.notify(
                "No delay corners declared yet -- add one under Signoff / Delay corners "
                "before creating an analysis view.", severity="warning",
            )
            return

        def handle_delay_corner(delay_corner: Optional[str]) -> None:
            if delay_corner is None:
                return
            existing = self._analysis_views.get(name, {})

            def handle_flags(flags: dict) -> None:
                self._analysis_views[name] = {"delay_corner": delay_corner, **flags}
                self._refresh()
            self.app.push_screen(_AnalysisViewFlagsScreen(f"{name} flags", existing), handle_flags)
        self.app.push_screen(
            _PickScreen("Delay corner", [(n, n) for n in delay_corner_names]), handle_delay_corner,
        )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id and event.option_id != "__empty__":
            self._edit(event.option_id)

    def action_add(self) -> None:
        def handle(name: Optional[str]) -> None:
            if not name:
                return
            if name in self._analysis_views:
                self.app.notify(f"Analysis view {name!r} already exists.", severity="warning")
                return
            self._edit(name)
        self.app.push_screen(_TextScreen("Analysis view name (e.g. func_setup_wc)"), handle)

    def action_delete(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or not self._analysis_views:
            return
        name = list(self._analysis_views)[option_list.highlighted]
        del self._analysis_views[name]
        self._refresh()

    def action_done(self) -> None:
        self.dismiss(self._analysis_views)


_VTH_FILE_FIELDS = (
    ("gds", "GDS files"),
    ("verilog_models", "Verilog models"),
    ("spice_models", "SPICE models"),
)


# Must match wolf.environment's own _STACK_KEYED_FIELDS -- these are the
# fields a vth may declare per named metal stack instead of as a flat
# list. gds is deliberately not here -- see wolf.environment's own
# comment by the same name: a cell's own GDS geometry lives on metal
# layers shared by every stack option, unlike lef and qrc_techfiles.
_STACK_KEYED_FIELDS = ("lef", "qrc_techfiles")


def _flatten_legacy_gds(vth_data: dict) -> Optional[tuple[Optional[str], int]]:
    """GDS used to be declared per metal stack, the same as lef and
    qrc_techfiles -- but a cell's own GDS geometry lives on metal layers
    shared by every stack option, so it no longer needs that axis.
    Mutates an old per-stack gds dict into the new flat list in place:
    the vth's own default_metal_stack if set, else its only declared
    stack if there's just one, else the first one sorted. Returns
    (stack_name_or_None, file_count) if gds actually was a legacy dict
    (so a caller can notify what happened -- this picks one stack's
    files and drops the others, usually the same files anyway), or None
    if there was nothing to migrate. Pure data mutation, no App reference
    needed, so it's safe to call from __init__, before a screen is
    actually mounted."""
    value = vth_data.get("gds")
    if not isinstance(value, dict):
        return None
    stack = vth_data.get("default_metal_stack")
    if stack not in value:
        stack = next(iter(sorted(value)), None)
    files = list(value.get(stack, [])) if stack else []
    vth_data["gds"] = files
    return (stack, len(files))


def _copy_stack_entry(value: Any) -> Any:
    """Copy one stack's value for one _STACK_KEYED_FIELDS field -- lef's
    is always a flat file list, but qrc_techfiles' may be a flat list
    (legacy) or a {rc_corner: [files]} mapping, so this has to stay
    shape-aware rather than assuming list() is always the right copy."""
    return dict(value) if isinstance(value, dict) else list(value)


def _normalize_stacks(vth_data: dict) -> dict:
    """Read a vth's lef/qrc_techfiles into {stack_name: {field: [...]}}
    regardless of which shape they're currently declared in.

    A flat list (or no stack-keyed field at all) is one implicit stack --
    named after the vth's own default_metal_stack if it has one, else
    "default" -- so a single-stack vth still opens into this same editor
    with nothing to migrate by hand.
    """
    stacks: dict = {}
    has_dict_form = any(isinstance(vth_data.get(key), dict) for key in _STACK_KEYED_FIELDS)
    if has_dict_form:
        for key in _STACK_KEYED_FIELDS:
            value = vth_data.get(key)
            if isinstance(value, dict):
                for stack, entry in value.items():
                    stacks.setdefault(stack, {field: [] for field in _STACK_KEYED_FIELDS})[key] = (
                        _copy_stack_entry(entry)
                    )
    else:
        name = vth_data.get("default_metal_stack") or "default"
        entry = {field: [] for field in _STACK_KEYED_FIELDS}
        any_present = False
        for key in _STACK_KEYED_FIELDS:
            value = vth_data.get(key)
            if isinstance(value, list) and value:
                entry[key] = list(value)
                any_present = True
        if any_present:
            stacks[name] = entry
    return stacks


def _write_stacks(vth_data: dict, stacks: dict) -> None:
    """Write {stack_name: {field: [...]}} back into a vth's lef/
    qrc_techfiles -- always as the mapping form (even a single stack),
    which resolves identically to a flat list (auto-selected). A field
    with no files in any stack is omitted entirely, matching what
    wolf.environment's _vth_metal_stacks requires."""
    for key in _STACK_KEYED_FIELDS:
        if not any(data.get(key) for data in stacks.values()):
            vth_data.pop(key, None)
            continue
        vth_data[key] = {name: data.get(key, []) for name, data in stacks.items()}


def _substitute_all(value: str, substitutions: list[tuple[re.Pattern, str]]) -> str:
    """Apply an ordered list of (find regex, replace) pairs in sequence --
    some paths need more than one rewrite (the track token and the vth
    token, say), applied left to right exactly as declared."""
    for pattern, replace in substitutions:
        value = pattern.sub(replace, value)
    return value


def _apply_clone(
    vth_data: dict, substitutions: list[tuple[re.Pattern, str]], root: Path,
) -> tuple[dict, list[dict]]:
    """Apply an ordered list of regex substitutions (see _substitute_all)
    across every file path a vth carries (corners' libraries and
    qrc_tech_file, flat gds/verilog/spice model lists, and every metal
    stack's lef/qrc_techfiles), producing both the resulting vth dict and a
    flat list of preview rows describing what changed and whether each
    new path actually exists on disk. Both the confirmation screen and
    the real write are driven off this same computation so they can
    never drift apart. A path that doesn't exist after substitution is
    simply dropped from the result -- cloning a vth that only has 5 of a
    track's 7 corners' worth of files on disk is normal, not an error to
    block on."""
    def exists(value: str) -> bool:
        candidate = Path(value)
        return (candidate if candidate.is_absolute() else root / candidate).exists()

    def substitute(value: str) -> str:
        return _substitute_all(value, substitutions)

    def clone_list(values: list) -> tuple[list, list[dict]]:
        kept: list = []
        rows: list[dict] = []
        for old in values:
            new = substitute(old)
            ok = exists(new)
            rows.append({"old": old, "new": new, "exists": ok})
            if ok:
                kept.append(new)
        return kept, rows

    new_data: dict = {}
    all_rows: list[dict] = []

    corners = vth_data.get("timing", {}).get("corners", {})
    new_corners: dict = {}
    for name, corner in corners.items():
        if not isinstance(corner, dict):
            continue
        new_corner = dict(corner)
        libraries, rows = clone_list(corner.get("libraries", []))
        for row in rows:
            row["location"] = f"corner {name}: libraries"
        all_rows.extend(rows)
        new_corner["libraries"] = libraries
        qrc = corner.get("qrc_tech_file")
        if qrc:
            new_qrc = substitute(qrc)
            ok = exists(new_qrc)
            all_rows.append({"location": f"corner {name}: qrc_tech_file", "old": qrc, "new": new_qrc, "exists": ok})
            if ok:
                new_corner["qrc_tech_file"] = new_qrc
            else:
                new_corner.pop("qrc_tech_file", None)
        new_corners[name] = new_corner
    if new_corners:
        new_data["timing"] = {"corners": new_corners}

    for field, label in _VTH_FILE_FIELDS:
        values, rows = clone_list(vth_data.get(field, []))
        for row in rows:
            row["location"] = label
        all_rows.extend(rows)
        if values:
            new_data[field] = values

    stacks = _normalize_stacks(vth_data)
    new_stacks: dict = {}
    for stack_name, entry in stacks.items():
        # Reuse _apply_clone_stack rather than duplicating its lef-vs-
        # qrc_techfiles-rc-corners handling here.
        new_entry, rows = _apply_clone_stack(entry, substitutions, root)
        for row in rows:
            row["location"] = f"stack {stack_name}: {row['location']}"
        all_rows.extend(rows)
        new_stacks[stack_name] = new_entry
    _write_stacks(new_data, new_stacks)

    default_stack = vth_data.get("default_metal_stack")
    if default_stack and default_stack in new_stacks:
        new_data["default_metal_stack"] = default_stack

    return new_data, all_rows


def _apply_clone_track(
    track_data: dict, substitutions: list[tuple[re.Pattern, str]], root: Path,
) -> tuple[dict, list[dict]]:
    """Clone a whole track: apply _apply_clone to every one of its vths,
    prefixing each vth's own preview rows with its name so a multi-vth
    preview still reads clearly. A vth that fails to clone to anything
    meaningful still ends up in the result as an empty vth, same as
    _apply_clone's own per-field tolerance -- only truly empty rows (a
    vth with no file paths to clone at all) are left out of the rows list,
    never silently dropped from the resulting track."""
    vths = track_data.get("vths", {})
    new_vths: dict = {}
    all_rows: list[dict] = []
    for vth_name, vth_data in vths.items():
        if not isinstance(vth_data, dict):
            continue
        new_vth_data, rows = _apply_clone(vth_data, substitutions, root)
        for row in rows:
            row["location"] = f"{vth_name} / {row['location']}"
        all_rows.extend(rows)
        new_vths[vth_name] = new_vth_data
    return {"vths": new_vths}, all_rows


def _apply_clone_stack(
    stack_data: dict, substitutions: list[tuple[re.Pattern, str]], root: Path,
) -> tuple[dict, list[dict]]:
    """Clone one metal stack: apply the same ordered regex substitutions
    (see _substitute_all) across its lef files and every one of its
    qrc_techfiles rc-corners' own file lists -- the simplest of the three
    clone shapes otherwise, since a stack has no further nesting beyond
    that (no PVT corners, no sub-vths)."""
    def exists(value: str) -> bool:
        candidate = Path(value)
        return (candidate if candidate.is_absolute() else root / candidate).exists()

    def clone_list(values: list, location: str) -> tuple[list, list[dict]]:
        kept: list = []
        rows: list[dict] = []
        for old in values:
            new = _substitute_all(old, substitutions)
            ok = exists(new)
            rows.append({"location": location, "old": old, "new": new, "exists": ok})
            if ok:
                kept.append(new)
        return kept, rows

    new_data: dict = {}
    all_rows: list[dict] = []
    lef, rows = clone_list(stack_data.get("lef", []), "lef")
    new_data["lef"] = lef
    all_rows.extend(rows)

    qrc_corners, rows = _apply_clone_qrc_corners(
        _normalize_qrc_corners(stack_data.get("qrc_techfiles")), substitutions, root,
    )
    new_data["qrc_techfiles"] = qrc_corners
    all_rows.extend(rows)
    return new_data, all_rows


def _apply_clone_file_list(
    files: list, substitutions: list[tuple[re.Pattern, str]], root: Path, location: str,
) -> tuple[list, list[dict]]:
    """Apply an ordered list of regex substitutions across one flat file
    list, dropping any resulting path that doesn't actually exist on
    disk -- the single-list building block every clone flavor (a whole
    stack's lef, one rc-corner's own files, ...) reduces to."""
    def exists(value: str) -> bool:
        candidate = Path(value)
        return (candidate if candidate.is_absolute() else root / candidate).exists()

    kept: list = []
    rows: list[dict] = []
    for old in files:
        new = _substitute_all(old, substitutions)
        ok = exists(new)
        rows.append({"location": location, "old": old, "new": new, "exists": ok})
        if ok:
            kept.append(new)
    return kept, rows


def _apply_clone_qrc_corners(
    corners: dict, substitutions: list[tuple[re.Pattern, str]], root: Path,
) -> tuple[dict, list[dict]]:
    """Clone a whole stack's named RC-extraction corners at once (the
    level reached via Back-End / QRC techfiles / <track> / <vth> /
    <stack>): apply the same ordered regex substitutions across every
    rc-corner's own file list, in place -- used when cloning the stack
    itself (_apply_clone_stack), not the per-corner clone on
    _QrcCornersScreen, which clones one highlighted corner to a new name
    instead (see _apply_clone_file_list)."""
    new_corners: dict = {}
    all_rows: list[dict] = []
    for corner_name, files in corners.items():
        kept, rows = _apply_clone_file_list(files, substitutions, root, f"qrc_techfiles: {corner_name}")
        new_corners[corner_name] = kept
        all_rows.extend(rows)
    return new_corners, all_rows


def _common_path_prefix(paths: list[str]) -> str:
    """The longest directory prefix shared by every path, or "" if there
    isn't one (mixed absolute/relative paths, or fewer than 2 distinct
    directories) -- stripped from a clone preview's rows so what's left
    is just the part that actually differs, not a repeated screenful of
    identical leading directories."""
    if len(paths) < 2:
        return ""
    try:
        common = os.path.commonpath(paths)
    except ValueError:
        return ""
    # commonpath may return a bare filename shared by every path with no
    # real directory in common -- only a genuine directory prefix is worth
    # stripping.
    return common if any(os.sep in path[len(common):] for path in paths) and common not in ("", ".") else ""


class _RegexPairsScreen(ModalScreen[Optional[list]]):
    """Build an ordered list of (find regex, replace) substitution pairs
    for a clone -- some paths need more than one rewrite (the track token
    and the vth token both changing, say), applied left to right exactly
    as declared (see _substitute_all). 'a' adds a pair, enter edits the
    highlighted one in place, 'd' deletes it, esc finishes -- dismisses
    with the list, empty meaning "nothing to clone with", which callers
    treat as a cancelled clone."""

    BINDINGS = [
        ("a", "add", "Add pair"),
        ("d", "delete", "Delete pair"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, title: str):
        super().__init__()
        self._title = title
        self._pairs: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*self._options())
            yield Static(self._hint(), id="dialog-hint")

    def _options(self) -> list[Option]:
        if not self._pairs:
            return [Option("(none yet -- press a to add)", id="__empty__", disabled=True)]
        return [
            Option(f"/{find}/ -> {replace!r}", id=str(index))
            for index, (find, replace) in enumerate(self._pairs)
        ]

    def _hint(self) -> str:
        return (
            f"{len(self._pairs)} substitution(s), applied in order — enter: edit highlighted — "
            f"a: add — d: delete highlighted — esc: done"
        )

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)
        self.query_one("#dialog-hint", Static).update(self._hint())

    def _prompt_pair(self, on_done, *, initial_find: str = "", initial_replace: str = "") -> None:
        def handle_find(find: Optional[str]) -> None:
            if not find:
                return
            try:
                re.compile(find)
            except re.error as error:
                self.app.notify(f"Invalid regex: {error}", severity="error")
                return

            def handle_replace(replace: Optional[str]) -> None:
                if replace is None:
                    return
                on_done(find, replace)
            self.app.push_screen(
                _TextScreen(f"Replace with (matches /{find}/)", initial_replace), handle_replace,
            )
        self.app.push_screen(_TextScreen("Regex to find", initial_find), handle_find)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if not event.option_id or event.option_id == "__empty__":
            return
        index = int(event.option_id)
        find, replace = self._pairs[index]

        def done(new_find: str, new_replace: str) -> None:
            self._pairs[index] = (new_find, new_replace)
            self._refresh()
        self._prompt_pair(done, initial_find=find, initial_replace=replace)

    def action_add(self) -> None:
        def done(find: str, replace: str) -> None:
            self._pairs.append((find, replace))
            self._refresh()
        self._prompt_pair(done)

    def action_delete(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or not self._pairs:
            return
        del self._pairs[option_list.highlighted]
        self._refresh()

    def action_done(self) -> None:
        self.dismiss(self._pairs)


class _ClonePreviewScreen(ModalScreen[bool]):
    """Shows every path a clone would produce (old -> new) before
    committing, with a green OK if the new path exists on disk and a red
    MISSING if it doesn't. Confirming drops every MISSING row from the
    cloned vth -- it's a preview of exactly what _apply_clone already
    computed, not a separate judgment call. A directory prefix shared by
    every old and new path is stripped and shown once up top instead of
    repeated on every row -- with a few corners and several file fields,
    that's almost the entire path on every line otherwise."""

    BINDINGS = [("c", "confirm", "Confirm"), ("escape", "cancel", "Cancel")]

    def __init__(self, title: str, rows: list[dict]):
        super().__init__()
        self._title = title
        self._rows = rows

    def compose(self) -> ComposeResult:
        missing = sum(1 for row in self._rows if not row["exists"])
        prefix = _common_path_prefix(
            [row["old"] for row in self._rows] + [row["new"] for row in self._rows],
        )

        def strip(path: str) -> str:
            return path[len(prefix):].lstrip(os.sep) if prefix else path

        with VerticalScroll(id="dialog"):
            yield Static(self._title, id="dialog-title")
            if prefix:
                yield Static(f"[dim]common path (stripped below): {prefix}{os.sep}[/dim]")
            for row in self._rows:
                mark = "[green]OK[/green]" if row["exists"] else "[red]MISSING[/red]"
                yield Static(
                    f"{mark}  {row['location']}\n"
                    f"  {strip(row['old'])}\n"
                    f"  -> {strip(row['new'])}"
                )
                yield Static("-" * 60, classes="clone-divider")
            yield Static(
                f"{len(self._rows)} path(s), {missing} missing (dropped on confirm) -- "
                f"c: confirm -- esc: cancel",
                id="dialog-hint",
            )

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


def _run_clone_flow(app: App, source_label: str, apply_fn, on_confirmed) -> None:
    """Shared clone flow behind tracks, vths, and metal stacks: prompt
    for one or more (find, replace) substitution pairs (_RegexPairsScreen),
    apply them via apply_fn(substitutions) -> (new_data, rows), preview
    the result (_ClonePreviewScreen), then confirm. on_confirmed(new_data)
    only fires once the user actually confirms a non-empty preview --
    cancelling at any step leaves the source completely untouched."""
    def handle_pairs(pairs: Optional[list]) -> None:
        if not pairs:
            return
        substitutions = [(re.compile(find), replace) for find, replace in pairs]
        new_data, rows = apply_fn(substitutions)
        if not rows:
            app.notify(f"{source_label} has no file paths to clone.", severity="warning")
            return

        def handle_confirm(confirmed: bool) -> None:
            if confirmed:
                on_confirmed(new_data)
        summary = "\n".join(f"/{find}/ -> {replace!r}" for find, replace in pairs)
        app.push_screen(_ClonePreviewScreen(f"Clone {source_label}\n{summary}", rows), handle_confirm)
    app.push_screen(_RegexPairsScreen(f"Substitutions for cloning {source_label}"), handle_pairs)


# Display labels for _STACK_KEYED_FIELDS -- a dict, not zip(), so a field
# being added or removed from that tuple can never silently mispair with
# the wrong label (zip() truncates/misaligns silently; a missing key
# here raises instead).
_STACK_FIELD_LABELS = {"lef": "LEF files", "qrc_techfiles": "QRC techfiles"}


def _normalize_qrc_corners(value: Any) -> dict:
    """A stack's qrc_techfiles value, normalized to {rc_corner: [files]}.
    A flat list -- the shape before rc-corners were broken out by name --
    becomes one bucket named "unnamed" so nothing already declared is
    silently dropped; rename or split it via the RC-corners editor
    itself. A real captable is named per metal stack AND per rc-corner
    (confirmed filename: ..._Vp9m+alrdl_top2_rcworst.captable), unlike
    gds, so qrc_techfiles keeps this one extra level lef doesn't need."""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list) and value:
        return {"unnamed": list(value)}
    return {}


class _QrcCornersScreen(ModalScreen[Optional[dict]]):
    """Edit the named RC-extraction corners declared for one metal
    stack's qrc_techfiles (e.g. rcbest/rcworst/typical) -- a real,
    independent axis from the PVT timing corners (BEOL metal/via process
    variation, not FEOL transistor skew): real captables are named per
    rc-corner, the same way PVT corners are named, and (like those) the
    same rc-corner names should be used everywhere once chosen for one
    stack -- WOLF doesn't enforce that consistency, the same way it
    doesn't for PVT corner names either."""

    BINDINGS = [
        ("a", "add", "Add rc-corner"),
        ("d", "delete", "Delete rc-corner"),
        ("c", "clone", "Clone (regex)"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, title: str, root: Path, corners: dict):
        super().__init__()
        self._title = title
        self._root = root
        self._corners = dict(corners)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*self._options())
            yield Static(self._hint(), id="dialog-hint")

    def _options(self) -> list[Option]:
        if not self._corners:
            return [Option("(none yet -- press a to add)", id="__empty__", disabled=True)]
        return [
            Option(f"{name} ({len(files)} file(s))", id=name)
            for name, files in self._corners.items()
        ]

    def _hint(self) -> str:
        return (
            f"{len(self._corners)} rc-corner(s) — enter: edit — a: add — "
            f"c: clone highlighted — d: delete highlighted — esc: done"
        )

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)
        self.query_one("#dialog-hint", Static).update(self._hint())

    def _edit(self, name: str) -> None:
        def handle(values: Optional[list]) -> None:
            if values is not None:
                self._corners[name] = values
                self._refresh()
        self.app.push_screen(
            _FileListScreen(f"{self._title} / {name}", self._root, self._corners.get(name, [])),
            handle,
        )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id and event.option_id != "__empty__":
            self._edit(event.option_id)

    def action_add(self) -> None:
        def handle(name: Optional[str]) -> None:
            if not name:
                return
            if name in self._corners:
                self.app.notify(f"RC-corner {name!r} already exists.", severity="warning")
                return
            self._corners[name] = []
            self._refresh()
            self._edit(name)
        self.app.push_screen(_TextScreen("RC-corner name (e.g. rcbest, rcworst, typical)"), handle)

    def action_delete(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or not self._corners:
            return
        name = list(self._corners)[option_list.highlighted]
        del self._corners[name]
        self._refresh()

    def action_clone(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or not self._corners:
            return
        source_name = list(self._corners)[option_list.highlighted]
        source_files = self._corners[source_name]

        def handle_name(new_name: Optional[str]) -> None:
            if not new_name:
                return
            if new_name in self._corners:
                self.app.notify(f"RC-corner {new_name!r} already exists.", severity="warning")
                return

            def on_confirmed(new_files: list) -> None:
                self._corners[new_name] = new_files
                self._refresh()
            _run_clone_flow(
                self.app, f"rc-corner {source_name} -> {new_name}",
                lambda substitutions: _apply_clone_file_list(
                    source_files, substitutions, self._root, f"qrc_techfiles: {new_name}",
                ),
                on_confirmed,
            )
        self.app.push_screen(_TextScreen(f"New rc-corner name (cloned from {source_name})"), handle_name)

    def action_done(self) -> None:
        self.dismiss(self._corners)


class _StackEditScreen(ModalScreen[Optional[dict]]):
    """Edit one named metal stack's LEF files and QRC-techfile rc-corners
    -- not GDS, which doesn't vary by metal stack (see
    _STACK_KEYED_FIELDS). qrc_techfiles opens one level deeper than lef
    (_QrcCornersScreen, not a flat file list) since a real captable is
    named per rc-corner too, not just per stack."""

    BINDINGS = [("escape", "done", "Done")]

    def __init__(self, name: str, root: Path, data: dict):
        super().__init__()
        self._name = name
        self._root = root
        self._data = dict(data)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(f"Metal stack: {self._name}", id="dialog-title")
            yield OptionList(*self._options())
            yield Static("enter: edit — esc: done", id="dialog-hint")

    def _options(self) -> list[Option]:
        options = [Option(
            f"{_STACK_FIELD_LABELS['lef']} ({len(self._data.get('lef', []))} file(s))", id="lef",
        )]
        corners = _normalize_qrc_corners(self._data.get("qrc_techfiles"))
        options.append(Option(
            f"{_STACK_FIELD_LABELS['qrc_techfiles']} ({len(corners)} rc-corner(s))",
            id="qrc_techfiles",
        ))
        return options

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        key = event.option_id
        if key == "qrc_techfiles":
            def handle_corners(corners: Optional[dict]) -> None:
                if corners is not None:
                    self._data["qrc_techfiles"] = corners
                    self._refresh()
            self.app.push_screen(
                _QrcCornersScreen(
                    f"RC corners for stack {self._name}", self._root,
                    _normalize_qrc_corners(self._data.get("qrc_techfiles")),
                ),
                handle_corners,
            )
        elif key == "lef":
            def handle_files(values: Optional[list]) -> None:
                if values is not None:
                    self._data["lef"] = values
                    self._refresh()
            self.app.push_screen(
                _FileListScreen(
                    f"{_STACK_FIELD_LABELS['lef']} for stack {self._name}", self._root,
                    self._data.get("lef", []),
                ),
                handle_files,
            )

    def action_done(self) -> None:
        self.dismiss(self._data)


class _MetalStacksScreen(ModalScreen[Optional[dict]]):
    """Edit the named metal stacks declared for one vth (each stack: its
    own LEF/QRC-techfile lists -- not GDS, which doesn't vary by metal
    stack) -- the multi-stack equivalent of _CornersScreen, since the
    same "named, then edited" shape applies."""

    BINDINGS = [
        ("a", "add", "Add stack"),
        ("c", "clone", "Clone stack"),
        ("d", "delete", "Delete stack"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, title: str, root: Path, vth_data: dict):
        super().__init__()
        self._title = title
        self._root = root
        self._stacks = _normalize_stacks(vth_data)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*self._options())
            yield Static(self._hint(), id="dialog-hint")

    def _options(self) -> list[Option]:
        if not self._stacks:
            return [Option("(none yet -- press a to add)", id="__empty__", disabled=True)]
        return [
            Option(
                f"{name} ({', '.join(f'{key}={len(data[key])}' for key in _STACK_KEYED_FIELDS)})",
                id=name,
            )
            for name, data in self._stacks.items()
        ]

    def _hint(self) -> str:
        return (
            f"{len(self._stacks)} stack(s) — enter: edit — a: add — "
            f"c: clone highlighted — d: delete highlighted — esc: done"
        )

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)
        self.query_one("#dialog-hint", Static).update(self._hint())

    def _edit(self, name: str) -> None:
        def handle(data: Optional[dict]) -> None:
            if data is not None:
                self._stacks[name] = data
                self._refresh()
        self.app.push_screen(_StackEditScreen(name, self._root, self._stacks.get(name, {})), handle)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id and event.option_id != "__empty__":
            self._edit(event.option_id)

    def action_add(self) -> None:
        def handle(name: Optional[str]) -> None:
            if not name:
                return
            if name in self._stacks:
                self.app.notify(f"Metal stack {name!r} already exists.", severity="warning")
                return
            self._stacks[name] = {field: [] for field in _STACK_KEYED_FIELDS}
            self._refresh()
            self._edit(name)
        self.app.push_screen(_TextScreen("Metal stack name (e.g. 9lmT2, 7lmT1)"), handle)

    def action_delete(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or not self._stacks:
            return
        name = list(self._stacks)[option_list.highlighted]
        del self._stacks[name]
        self._refresh()

    def action_done(self) -> None:
        self.dismiss(self._stacks)

    def action_clone(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or not self._stacks:
            return
        source_name = list(self._stacks)[option_list.highlighted]
        source_data = self._stacks[source_name]

        def handle_name(new_name: Optional[str]) -> None:
            if not new_name:
                return
            if new_name in self._stacks:
                self.app.notify(f"Metal stack {new_name!r} already exists.", severity="warning")
                return

            def on_confirmed(new_data: dict) -> None:
                self._stacks[new_name] = new_data
                self._refresh()
                self._edit(new_name)
            _run_clone_flow(
                self.app, f"metal stack {source_name} -> {new_name}",
                lambda substitutions: _apply_clone_stack(source_data, substitutions, self._root),
                on_confirmed,
            )
        self.app.push_screen(_TextScreen(f"New metal stack name (cloned from {source_name})"), handle_name)


class _PickCreateDeleteScreen(ModalScreen[Optional[str]]):
    """Pick an existing name, create a new one, or delete one in place --
    the shared shape behind navigating to a track, vth, corner, or metal
    stack from the library-mirroring (Front-End/Back-End) side of the PDK
    menu. 'd' deletes the highlighted name without closing this screen,
    so removing several in a row doesn't mean reopening the picker each
    time. Dismisses with the chosen (existing or newly created) name, or
    None if cancelled outright -- callers treat None as "done at this
    level", which is what makes escape go up exactly one level rather
    than collapsing the whole chain back to the top (see _loop_named_level
    below, which is what actually loops this screen)."""

    BINDINGS = [("c", "clone", "Clone"), ("d", "delete", "Delete")]

    def __init__(
        self, title: str, existing: list[str], create_prompt: str, on_delete: Optional[Any] = None,
        on_clone: Optional[Any] = None, on_clone_commit: Optional[Any] = None,
    ):
        super().__init__()
        self._title = title
        self._existing = list(existing)
        self._create_prompt = create_prompt
        self._on_delete = on_delete
        self._on_clone = on_clone
        self._on_clone_commit = on_clone_commit

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*self._options())
            yield Static(self._hint(), id="dialog-hint")

    def _options(self) -> list[Option]:
        return [Option(name, id=name) for name in self._existing] + [
            Option("+ Create new...", id="__new__"),
        ]

    def _hint(self) -> str:
        clone_hint = " — c: clone highlighted" if self._existing and self._on_clone else ""
        delete_hint = " — d: delete highlighted" if self._existing and self._on_delete else ""
        return f"enter: choose{clone_hint}{delete_hint} — esc: back"

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)
        self.query_one("#dialog-hint", Static).update(self._hint())

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id == "__new__":
            def handle_name(name: Optional[str]) -> None:
                if name:
                    self.dismiss(name)
            self.app.push_screen(_TextScreen(self._create_prompt), handle_name)
        else:
            self.dismiss(event.option_id)

    def action_delete(self) -> None:
        if self._on_delete is None or not self._existing:
            return
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or option_list.highlighted >= len(self._existing):
            return
        name = self._existing[option_list.highlighted]
        self._on_delete(name)
        self._existing.remove(name)
        self._refresh()

    def action_clone(self) -> None:
        if self._on_clone is None or not self._existing:
            return
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or option_list.highlighted >= len(self._existing):
            return
        source_name = self._existing[option_list.highlighted]

        def handle_name(new_name: Optional[str]) -> None:
            if not new_name:
                return
            if new_name in self._existing:
                self.app.notify(f"{new_name!r} already exists.", severity="warning")
                return

            def on_confirmed(new_data: dict) -> None:
                self._on_clone_commit(new_name, new_data)
                self._existing.append(new_name)
                self._refresh()
            _run_clone_flow(
                self.app, f"{source_name} -> {new_name}",
                lambda substitutions: self._on_clone(source_name, substitutions),
                on_confirmed,
            )
        self.app.push_screen(_TextScreen(f"New name (cloned from {source_name})"), handle_name)

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


def _loop_named_level(
    app: App, title: str, existing_fn, create_prompt: str, do_child, on_return, on_delete=None,
    on_clone=None, on_clone_commit=None,
) -> None:
    """Show a pick/create/delete screen for one level of the hierarchy,
    looping back to itself (re-fetching `existing_fn` fresh each time) once
    `do_child` is fully done with whatever it opened -- so finishing with
    one item lands you back on the picker for this same level, not back
    at the top. `on_return` fires only when this screen is cancelled
    outright with nothing chosen, which is the one and only point where
    control actually passes up to whoever called this level -- that's
    what makes escape move exactly one level at a time instead of
    collapsing however many pick/create steps led here. `on_clone`/
    `on_clone_commit` are optional (see _PickCreateDeleteScreen.action_clone)
    -- most levels don't support cloning."""
    def show() -> None:
        app.push_screen(
            _PickCreateDeleteScreen(
                title, sorted(existing_fn()), create_prompt, on_delete=on_delete,
                on_clone=on_clone, on_clone_commit=on_clone_commit,
            ),
            handle,
        )
    def handle(name: Optional[str]) -> None:
        if name is None:
            on_return()
        else:
            do_child(name, show)
    show()


def _loop_fixed_choice(app: App, title: str, choices: list[tuple[str, str]], do_child, on_return) -> None:
    """Same looping shape as _loop_named_level, for a fixed menu of
    choices (a delay-model format, a Front-End/Back-End category, ...)
    rather than a growable/deletable list of names."""
    def show() -> None:
        app.push_screen(_PickScreen(title, choices), handle)
    def handle(choice: Optional[str]) -> None:
        if choice is None:
            on_return()
        else:
            do_child(choice, show)
    show()


def _navigate_to_vth(app: App, technology: dict, root: Path, breadcrumb: str, on_vth, on_return) -> None:
    """Pick, create, delete, or clone a track, then a vth under it -- the
    common first step of every library-shaped (Front-End/Back-End)
    navigation entry point, since every one of them ends up at "some
    vth's data" before branching into a format, a flat category, or a
    metal stack. Looping at both levels (see _loop_named_level) means
    finishing with one vth -- or deleting it -- lands you back on the
    vth picker for the same track, and escaping that lands you back on
    the track picker, not at the top. Calls on_vth(track_name, vth_name,
    vth_data, vth_crumb, resume_vth) once a vth is chosen; on_return()
    only once the track picker itself is cancelled outright.
    """
    tracks = technology.setdefault("tracks", {})

    def do_track(track_name: str, resume_track) -> None:
        track_data = tracks.setdefault(track_name, {"vths": {}})
        vths = track_data.setdefault("vths", {})
        track_crumb = f"{breadcrumb} / {track_name}"

        def do_vth(vth_name: str, resume_vth) -> None:
            vth_data = vths.setdefault(vth_name, {})
            migration = _flatten_legacy_gds(vth_data)
            if migration is not None:
                stack, count = migration
                app.notify(
                    (
                        f"gds no longer varies by metal stack -- flattened to {stack!r}'s "
                        f"{count} file(s); review and re-save."
                    ) if stack else
                    "gds no longer varies by metal stack -- flattened to an empty list; "
                    "review and re-save.",
                    severity="warning",
                )
            on_vth(track_name, vth_name, vth_data, f"{track_crumb} / {vth_name}", resume_vth)

        def delete_vth(vth_name: str) -> None:
            vths.pop(vth_name, None)

        def clone_vth(vth_name: str, substitutions) -> tuple[dict, list[dict]]:
            return _apply_clone(vths[vth_name], substitutions, root)

        def commit_vth(new_name: str, new_data: dict) -> None:
            vths[new_name] = new_data

        _loop_named_level(
            app, f"{track_crumb}\nPick/create/delete a vth", lambda: vths,
            "vth name (e.g. lvt, rvt, hvt)", do_vth, resume_track, on_delete=delete_vth,
            on_clone=clone_vth, on_clone_commit=commit_vth,
        )

    def delete_track(track_name: str) -> None:
        tracks.pop(track_name, None)

    def clone_track(track_name: str, substitutions) -> tuple[dict, list[dict]]:
        return _apply_clone_track(tracks[track_name], substitutions, root)

    def commit_track(new_name: str, new_data: dict) -> None:
        tracks[new_name] = new_data

    _loop_named_level(
        app, f"{breadcrumb}\nPick/create/delete a track", lambda: tracks,
        "Track name (e.g. 9T, 7T, 12T)", do_track, on_return, on_delete=delete_track,
        on_clone=clone_track, on_clone_commit=commit_track,
    )


def _enter_timing_format(
    app: App, technology: dict, root: Path, breadcrumb: str, format_name: str, on_return,
    on_done=lambda: None,
) -> None:
    """Front-End -> Timing/Power -> <format>: pick/create/delete a
    track/vth, then a corner already using this format (or create one),
    then open its real corner editor -- mirrors browsing to
    Front_End/timing_power_noise/<FORMAT>/<family>/ in the real tree.
    Looping at every level means finishing one corner lands you back on
    the corner picker for the same vth, not back at the top. on_done()
    fires every time something is actually saved or deleted, so the
    caller can refresh its own menu -- repeatedly, since this keeps
    looping until the user backs all the way out on their own.
    """
    full_breadcrumb = f"{breadcrumb} / {format_name.upper()}"

    def on_vth(track_name, vth_name, vth_data, vth_crumb, resume_vth) -> None:
        corners = vth_data.setdefault("timing", {}).setdefault("corners", {})

        def existing() -> list[str]:
            # Every corner, regardless of its own declared format -- this
            # must show exactly what the Tracks path shows for the same
            # vth. Filtering by format here (as an earlier version did)
            # meant a corner created without ever touching this exact
            # format path (e.g. via Tracks, or cloned) stayed invisible
            # from Front-End even though it's the very same data.
            return sorted(corners)

        def do_corner(corner_name: str, resume_corner) -> None:
            data = corners.setdefault(corner_name, {"libraries": []})
            data.setdefault("format", format_name)

            def handle_result(result: Optional[dict]) -> None:
                if result is not None:
                    corners[corner_name] = result
                    on_done()
                resume_corner()
            app.push_screen(
                _CornerEditScreen(f"{vth_crumb} / {corner_name}", root, data), handle_result,
            )

        def delete_corner(corner_name: str) -> None:
            corners.pop(corner_name, None)
            on_done()

        _loop_named_level(
            app, f"{vth_crumb}\nPick/create/delete a corner (new ones default to {format_name})",
            existing, f"Corner name (format={format_name}, e.g. typical, worst_case)",
            do_corner, resume_vth, on_delete=delete_corner,
        )
    _navigate_to_vth(app, technology, root, full_breadcrumb, on_vth, on_return)


def _enter_flat_category(
    app: App, technology: dict, root: Path, breadcrumb: str, category: str, label: str, on_return,
    on_done=lambda: None,
) -> None:
    """Front-End -> Verilog, or Back-End -> SPICE: pick/create/delete a
    track/vth, then edit that one flat (not stack- or corner-keyed) file
    list. There's no name to pick at this level (it's a single list per
    vth, not a growable set), so closing the editor goes straight back to
    the vth picker, one level up."""
    full_breadcrumb = f"{breadcrumb} / {label}"

    def on_vth(track_name, vth_name, vth_data, vth_crumb, resume_vth) -> None:
        def handle_result(values: Optional[list]) -> None:
            if values is not None:
                vth_data[category] = values
                on_done()
            resume_vth()
        app.push_screen(
            _FileListScreen(f"{vth_crumb}\n{label}", root, vth_data.get(category, [])), handle_result,
        )
    _navigate_to_vth(app, technology, root, full_breadcrumb, on_vth, on_return)


def _enter_stack_field(
    app: App, technology: dict, root: Path, breadcrumb: str, field: str, label: str, on_return,
    on_done=lambda: None,
) -> None:
    """Back-End -> GDS / LEF / Techfiles: pick/create/delete a track/vth,
    then a metal stack, then edit just that one field for that stack --
    without needing to open the full per-stack editor for the other two
    fields. Looping at the stack level too means finishing (or deleting)
    one stack lands you back on the stack picker for the same vth."""
    full_breadcrumb = f"{breadcrumb} / {label}"

    def on_vth(track_name, vth_name, vth_data, vth_crumb, resume_vth) -> None:
        stacks = _normalize_stacks(vth_data)

        def do_stack(stack_name: str, resume_stack) -> None:
            entry = stacks.setdefault(stack_name, {key: [] for key in _STACK_KEYED_FIELDS})

            if field == "qrc_techfiles":
                def handle_corners(corners: Optional[dict]) -> None:
                    if corners is not None:
                        entry[field] = corners
                        _write_stacks(vth_data, stacks)
                        on_done()
                    resume_stack()
                app.push_screen(
                    _QrcCornersScreen(
                        f"{vth_crumb} / {stack_name}\n{label}", root,
                        _normalize_qrc_corners(entry.get(field)),
                    ),
                    handle_corners,
                )
                return

            def handle_result(values: Optional[list]) -> None:
                if values is not None:
                    entry[field] = values
                    _write_stacks(vth_data, stacks)
                    on_done()
                resume_stack()
            app.push_screen(
                _FileListScreen(f"{vth_crumb} / {stack_name}\n{label}", root, entry.get(field, [])),
                handle_result,
            )

        def delete_stack(stack_name: str) -> None:
            stacks.pop(stack_name, None)
            _write_stacks(vth_data, stacks)
            on_done()

        def clone_stack(stack_name: str, substitutions) -> tuple[dict, list[dict]]:
            # Clones the whole stack (lef+gds+qrc_techfiles), not just the
            # one field this particular screen happens to be editing --
            # matches what cloning the same stack via the Tracks path's
            # metal-stacks screen does.
            return _apply_clone_stack(stacks[stack_name], substitutions, root)

        def commit_stack(new_name: str, new_data: dict) -> None:
            stacks[new_name] = new_data
            _write_stacks(vth_data, stacks)
            on_done()

        _loop_named_level(
            app, f"{vth_crumb}\nPick/create/delete a metal stack", lambda: stacks,
            "Metal stack name (e.g. 9lmT2, 7lmT1)", do_stack, resume_vth, on_delete=delete_stack,
            on_clone=clone_stack, on_clone_commit=commit_stack,
        )
    _navigate_to_vth(app, technology, root, full_breadcrumb, on_vth, on_return)


class _VthScreen(ModalScreen[Optional[dict]]):
    """Edit one vth's corners, metal stacks (LEF/QRC techfiles), and flat
    per-vth file lists (gds, verilog models, spice models)."""

    BINDINGS = [("escape", "done", "Done")]

    def __init__(self, title: str, root: Path, data: dict):
        super().__init__()
        self._title = title
        self._root = root
        self._data = dict(data)
        # Pure mutation, safe before mount -- see _flatten_legacy_gds.
        # Flattening here (not at each place that used to call it ad hoc)
        # means opening a vth through *any* path -- Tracks, Front-End/
        # Back-End, or the dotted-name quick-jump straight to
        # tsmc65.<track>.<vth> -- always migrates it, not just some of
        # them.
        self._gds_migration = _flatten_legacy_gds(self._data)

    def on_mount(self) -> None:
        if self._gds_migration is None:
            return
        stack, count = self._gds_migration
        self.notify(
            (
                f"gds no longer varies by metal stack -- flattened to {stack!r}'s {count} "
                "file(s); review and re-save."
            ) if stack else
            "gds no longer varies by metal stack -- flattened to an empty list; review and re-save.",
            severity="warning",
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*self._options())
            yield Static("enter: edit — esc: done", id="dialog-hint")

    def _options(self) -> list[Option]:
        corners = self._data.get("timing", {}).get("corners", {})
        stacks = _normalize_stacks(self._data)
        default_stack = self._data.get("default_metal_stack") or "not set (auto-select if only one)"
        options = [
            Option(f"Liberty corners ({len(corners)})", id="corners"),
            Option(f"Metal stacks ({len(stacks)}): LEF/QRC techfiles", id="stacks"),
            Option(f"Default metal stack: {default_stack}", id="default_metal_stack"),
        ]
        for key, label in _VTH_FILE_FIELDS:
            count = len(self._data.get(key, []))
            options.append(Option(f"{label} ({count} file(s))", id=key))
        return options

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        key = event.option_id
        if key == "corners":
            def handle(corners: Optional[dict]) -> None:
                if corners is not None:
                    self._data.setdefault("timing", {})["corners"] = corners
                    self._refresh()
            corners = self._data.get("timing", {}).get("corners", {})
            self.app.push_screen(_CornersScreen(self._title, self._root, corners), handle)
        elif key == "stacks":
            def handle(stacks: Optional[dict]) -> None:
                if stacks is not None:
                    _write_stacks(self._data, stacks)
                    self._refresh()
            self.app.push_screen(
                _MetalStacksScreen(f"Metal stacks for {self._title}", self._root, self._data), handle,
            )
        elif key == "default_metal_stack":
            def handle(value: Optional[str]) -> None:
                if value is not None:
                    if value:
                        self._data["default_metal_stack"] = value
                    else:
                        self._data.pop("default_metal_stack", None)
                    self._refresh()
            self.app.push_screen(
                _TextScreen("Default metal stack", self._data.get("default_metal_stack", "")), handle,
            )
        elif key in dict(_VTH_FILE_FIELDS):
            label = dict(_VTH_FILE_FIELDS)[key]

            def handle(values: Optional[list]) -> None:
                if values is not None:
                    self._data[key] = values
                    self._refresh()
            self.app.push_screen(
                _FileListScreen(f"{label} for {self._title}", self._root, self._data.get(key, [])),
                handle,
            )

    def action_done(self) -> None:
        self.dismiss(self._data)


class _TrackScreen(ModalScreen[Optional[dict]]):
    """Edit the vths declared under one track."""

    BINDINGS = [
        ("a", "add", "Add vth"),
        ("c", "clone", "Clone vth"),
        ("d", "delete", "Delete vth"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, track: str, root: Path, data: dict):
        super().__init__()
        self._track = track
        self._root = root
        self._data = dict(data)
        self._data.setdefault("vths", {})

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(f"Track: {self._track}", id="dialog-title")
            yield OptionList(*self._options())
            yield Static(self._hint(), id="dialog-hint")

    def _vths(self) -> dict:
        return self._data["vths"]

    def _options(self) -> list[Option]:
        if not self._vths():
            return [Option("(none yet -- press a to add)", id="__empty__", disabled=True)]
        return [
            Option(f"{name} ({len(data.get('timing', {}).get('corners', {}))} corner(s))", id=name)
            for name, data in self._vths().items()
        ]

    def _hint(self) -> str:
        return (
            f"{len(self._vths())} vth(s) — enter: edit — a: add — "
            f"c: clone highlighted — d: delete highlighted — esc: done"
        )

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)
        self.query_one("#dialog-hint", Static).update(self._hint())

    def _edit(self, name: str) -> None:
        # _VthScreen itself handles the legacy-gds migration (see
        # _flatten_legacy_gds) now, regardless of how it's reached.
        vth_data = self._vths().get(name, {})

        def handle(data: Optional[dict]) -> None:
            if data is not None:
                self._vths()[name] = data
                self._refresh()
        self.app.push_screen(_VthScreen(f"{self._track}/{name}", self._root, vth_data), handle)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id and event.option_id != "__empty__":
            self._edit(event.option_id)

    def action_add(self) -> None:
        def handle(name: Optional[str]) -> None:
            if not name:
                return
            if name in self._vths():
                self.app.notify(f"vth {name!r} already exists on {self._track}.", severity="warning")
                return
            self._vths()[name] = {}
            self._refresh()
            self._edit(name)
        self.app.push_screen(_TextScreen("vth name (e.g. lvt, rvt, hvt)"), handle)

    def action_clone(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or not self._vths():
            return
        source_name = list(self._vths())[option_list.highlighted]
        source_data = self._vths()[source_name]

        def handle_name(new_name: Optional[str]) -> None:
            if not new_name:
                return
            if new_name in self._vths():
                self.app.notify(f"vth {new_name!r} already exists on {self._track}.", severity="warning")
                return

            def on_confirmed(new_data: dict) -> None:
                self._vths()[new_name] = new_data
                self._refresh()
                self._edit(new_name)
            _run_clone_flow(
                self.app, f"{self._track}/{source_name} -> {self._track}/{new_name}",
                lambda substitutions: _apply_clone(source_data, substitutions, self._root),
                on_confirmed,
            )
        self.app.push_screen(
            _TextScreen(f"New vth name (cloned from {source_name})"), handle_name,
        )

    def action_delete(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or not self._vths():
            return
        name = list(self._vths())[option_list.highlighted]
        del self._vths()[name]
        self._refresh()

    def action_done(self) -> None:
        self.dismiss(self._data)


class _TracksScreen(ModalScreen[Optional[dict]]):
    """Edit the tracks declared for this technology package."""

    BINDINGS = [
        ("a", "add", "Add track"),
        ("c", "clone", "Clone track"),
        ("d", "delete", "Delete track"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, root: Path, tracks: dict):
        super().__init__()
        self._root = root
        self._tracks = dict(tracks)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Tracks", id="dialog-title")
            yield OptionList(*self._options())
            yield Static(self._hint(), id="dialog-hint")

    def _options(self) -> list[Option]:
        if not self._tracks:
            return [Option("(none yet -- press a to add)", id="__empty__", disabled=True)]
        return [
            Option(f"{name} ({len(data.get('vths', {}))} vth(s))", id=name)
            for name, data in self._tracks.items()
        ]

    def _hint(self) -> str:
        return (
            f"{len(self._tracks)} track(s) — enter: edit — a: add — "
            f"c: clone highlighted — d: delete highlighted — esc: done"
        )

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)
        self.query_one("#dialog-hint", Static).update(self._hint())

    def _edit(self, name: str) -> None:
        def handle(data: Optional[dict]) -> None:
            if data is not None:
                self._tracks[name] = data
                self._refresh()
        self.app.push_screen(_TrackScreen(name, self._root, self._tracks.get(name, {})), handle)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id and event.option_id != "__empty__":
            self._edit(event.option_id)

    def action_add(self) -> None:
        def handle(name: Optional[str]) -> None:
            if not name:
                return
            if name in self._tracks:
                self.app.notify(f"Track {name!r} already exists.", severity="warning")
                return
            self._tracks[name] = {"vths": {}}
            self._refresh()
            self._edit(name)
        self.app.push_screen(_TextScreen("Track name (e.g. 9T, 7T, 12T)"), handle)

    def action_clone(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or not self._tracks:
            return
        source_name = list(self._tracks)[option_list.highlighted]
        source_data = self._tracks[source_name]

        def handle_name(new_name: Optional[str]) -> None:
            if not new_name:
                return
            if new_name in self._tracks:
                self.app.notify(f"Track {new_name!r} already exists.", severity="warning")
                return

            def on_confirmed(new_data: dict) -> None:
                self._tracks[new_name] = new_data
                self._refresh()
                self._edit(new_name)
            _run_clone_flow(
                self.app, f"track {source_name} -> {new_name}",
                lambda substitutions: _apply_clone_track(source_data, substitutions, self._root),
                on_confirmed,
            )
        self.app.push_screen(_TextScreen(f"New track name (cloned from {source_name})"), handle_name)

    def action_delete(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None or not self._tracks:
            return
        name = list(self._tracks)[option_list.highlighted]
        del self._tracks[name]
        self._refresh()

    def action_done(self) -> None:
        self.dismiss(self._tracks)


class _MainMenuOptionList(OptionList):
    """Arrow-down off the last row moves focus into the Save/Quit buttons
    below, instead of just stopping there -- same as wolf.env_menu's."""

    def action_cursor_down(self) -> None:
        if self.highlighted is not None and self.highlighted == self.option_count - 1:
            self.screen.query_one("#save", Button).focus()
            return
        super().action_cursor_down()


class PdkMenuApp(App[None]):
    """Creates or edits one pdk/NAME registry manifest.

    `initial_track`/`initial_vth`, when given (a dotted NAME like
    `tsmc65.9T.lvt`), jump straight to that track or vth's own screen on
    mount instead of starting at the top of this package's menu --
    closing it (esc) returns to the main menu, same as any other edit.
    """

    CSS = """
    #dialog {
        width: 100; height: auto; max-height: 34; border: round #ad4ce5; padding: 1 2;
        background: $surface;
    }
    #dialog-title { color: #ad4ce5; text-style: bold; margin-bottom: 1; }
    #dialog-hint { color: $text-muted; margin-top: 1; }
    .clone-divider { color: $text-muted; margin-bottom: 1; }
    Screen { align: center middle; }
    OptionList { border: round #ad4ce5; }
    #actions { height: auto; align: center middle; margin-top: 1; }
    #actions Button {
        margin: 0 2; min-width: 20; background: #3a3a3a; color: $text;
        border: tall #5a5a5a; text-style: bold;
    }
    #actions Button:focus {
        background: #ad4ce5 !important; color: white; border: tall #ad4ce5;
    }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "quit", "Quit"),
        ("s", "save_in_place", "Save"),
        # priority=True so this fires from anywhere in the TUI -- any
        # modal screen, any focused Input mid-edit -- the same way "s"
        # already does at the top level, without needing every screen to
        # declare its own copy of this binding.
        Binding("ctrl+s", "save_in_place", "Save", priority=True),
    ]
    TITLE = "WOLF PDK setup"

    def __init__(
        self, name: str, manifest_path: Path, data: dict, *, is_new: bool,
        initial_track: Optional[str] = None, initial_vth: Optional[str] = None,
    ):
        super().__init__()
        self._name = name
        self._manifest_path = manifest_path
        self._data = data
        self._is_new = is_new
        self._dirty = is_new
        self._initial_track = initial_track
        self._initial_vth = initial_vth
        self.last_browsed_dir: Optional[str] = None
        self.sub_title = self._name

    def on_mount(self) -> None:
        if self._initial_track is not None:
            self._open_track_directly(self._initial_track, self._initial_vth)

    def _open_track_directly(self, track_name: str, vth_name: Optional[str]) -> None:
        tracks = self._technology.setdefault("tracks", {})
        track_data = tracks.setdefault(track_name, {"vths": {}})
        if vth_name is None:
            def handle_track(data: Optional[dict]) -> None:
                if data is not None:
                    tracks[track_name] = data
                    self._refresh()
            self.push_screen(_TrackScreen(track_name, self._root, track_data), handle_track)
            return
        vths = track_data.setdefault("vths", {})
        vth_data = vths.setdefault(vth_name, {})

        def handle_vth(data: Optional[dict]) -> None:
            if data is not None:
                vths[vth_name] = data
                self._refresh()
        self.push_screen(
            _VthScreen(f"{track_name}/{vth_name}", self._root, vth_data), handle_vth,
        )

    @property
    def _technology(self) -> dict:
        return self._data.setdefault("metadata", {}).setdefault("technology", {})

    @property
    def _root(self) -> Path:
        source = self._data.get("source", {})
        if source.get("type") == "local-path" and source.get("root"):
            return Path(source["root"])
        return Path.home()

    def compose(self) -> ComposeResult:
        yield Header()
        yield _MainMenuOptionList(*self._options())
        with Horizontal(id="actions"):
            yield Button("Save", id="save")
            yield Button("Quit without saving", id="quit_")
        yield Footer()

    def on_key(self, event) -> None:
        focused = self.focused
        if not isinstance(focused, Button):
            return
        if event.key == "up":
            event.stop()
            self.query_one(OptionList).focus()
        elif event.key == "left":
            event.stop()
            self.query_one("#save", Button).focus()
        elif event.key == "right":
            event.stop()
            self.query_one("#quit_", Button).focus()

    def _options(self) -> list[Option]:
        source = self._data.get("source", {})
        technology = self._technology
        tracks = technology.get("tracks", {})
        generic = technology.get("generic", {})
        dont_use = technology.get("synthesis", {}).get("dont_use", [])
        opconds = technology.get("opconds", {})
        delay_corners = technology.get("delay_corners", {})
        analysis_views = technology.get("analysis_views", {})
        options = [
            Option(f"Revision: {source.get('revision', 'unset')}", id="revision"),
            Option(f"License name: {self._data.get('license', {}).get('name', 'not set')}", id="license"),
        ]
        if source.get("type") == "local-path":
            options.append(Option(f"Source root: {source.get('root', 'not set')}", id="source_root"))
        else:
            options.append(Option(f"Source: {source.get('type', 'unknown')} (not editable here)", id="source_info"))
        options.extend([
            Option(f"Tracks ({len(tracks)} track/vth group(s))", id="tracks"),
            Option("Front-End (timing/power, verilog)", id="front_end"),
            Option("Back-End (LEF, GDS, techfiles, SPICE)", id="back_end"),
            Option(
                f"Signoff ({len(opconds)} opcond(s), {len(delay_corners)} delay corner(s), "
                f"{len(analysis_views)} analysis view(s))",
                id="signoff",
            ),
            Option(f"Generic / other fields ({len(generic)} key(s), edit as YAML)", id="generic"),
            Option(f"Synthesis dont_use cells ({len(dont_use)})", id="dont_use"),
            Option(
                f"Setup.yaml fragment: {technology.get('setup_yaml_fragment') or 'not set'}",
                id="setup_yaml_fragment",
            ),
        ])
        return options

    def _refresh(self) -> None:
        self._dirty = True
        self._update_subtitle()
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)

    def _update_subtitle(self) -> None:
        self.sub_title = f"{self._name} — unsaved changes" if self._dirty else self._name

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        choice = event.option_id
        if choice == "revision":
            self._edit_text("Revision", ["source", "revision"], default="unset")
        elif choice == "license":
            self._edit_text("License name", ["license", "name"], default="")
        elif choice == "source_root":
            self._edit_source_root()
        elif choice == "tracks":
            self._edit_tracks()
        elif choice == "front_end":
            self._edit_front_end()
        elif choice == "back_end":
            self._edit_back_end()
        elif choice == "signoff":
            self._edit_signoff()
        elif choice == "generic":
            self._edit_generic()
        elif choice == "dont_use":
            self._edit_dont_use()
        elif choice == "setup_yaml_fragment":
            self._edit_setup_yaml_fragment()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save(close=True)
        elif event.button.id == "quit_":
            self.exit()

    def action_save_in_place(self) -> None:
        self._save(close=False)

    def _edit_text(self, title: str, path: list[str], *, default: str) -> None:
        node = self._data
        for key in path[:-1]:
            node = node.setdefault(key, {})
        current = node.get(path[-1], default)

        def handle(value: Optional[str]) -> None:
            if value is not None:
                node[path[-1]] = value
                self._refresh()
        self.push_screen(_TextScreen(title, current), handle)

    def _edit_source_root(self) -> None:
        source = self._data.setdefault("source", {})
        start = self.last_browsed_dir or source.get("root") or str(Path.home())

        def handle(path: Optional[str]) -> None:
            if path is not None:
                source["root"] = path
                self.last_browsed_dir = path
                self._refresh()
        self.push_screen(_BrowseDirectoryScreen(start, title="Source root directory"), handle)

    def _edit_tracks(self) -> None:
        def handle(tracks: Optional[dict]) -> None:
            if tracks is not None:
                self._technology["tracks"] = tracks
                self._refresh()
        self.push_screen(_TracksScreen(self._root, self._technology.get("tracks", {})), handle)

    def _edit_front_end(self) -> None:
        """Mirrors Front_End/{timing_power_noise,verilog} in the real tree:
        pick a category, then (lazily, creating track/vth/corner as
        needed) land on the real leaf editor -- the same data _edit_tracks
        edits, just entered from "what kind of file is this" instead of
        "which track/vth first". Loops (see _loop_fixed_choice) so
        finishing with one category lands you back on this same picker;
        cancelling it outright has nothing to return to but the main
        menu, which is correct -- it's genuinely the level above this."""
        def do_category(choice: str, resume_category) -> None:
            if choice == "timing":
                self._edit_timing_format(f"{self._name} / Front-End", resume_category)
            elif choice == "verilog":
                _enter_flat_category(
                    self, self._technology, self._root, f"{self._name} / Front-End",
                    "verilog_models", "Verilog models", resume_category, on_done=self._refresh,
                )
        _loop_fixed_choice(self, f"{self._name} / Front-End\nPick a category", [
            ("Timing / Power (lib: ECSM/NLDM/CCS)", "timing"),
            ("Verilog", "verilog"),
        ], do_category, lambda: None)

    def _edit_timing_format(self, breadcrumb: str, on_return) -> None:
        full_breadcrumb = f"{breadcrumb} / Timing-Power"

        def do_format(choice: str, resume_format) -> None:
            if choice == "__custom__":
                def handle_name(name: Optional[str]) -> None:
                    if name:
                        _enter_timing_format(
                            self, self._technology, self._root, full_breadcrumb, name, resume_format,
                            on_done=self._refresh,
                        )
                    else:
                        resume_format()
                self.push_screen(_TextScreen("Custom delay-model format name"), handle_name)
            else:
                _enter_timing_format(
                    self, self._technology, self._root, full_breadcrumb, choice, resume_format,
                    on_done=self._refresh,
                )
        _loop_fixed_choice(self, f"{full_breadcrumb}\nPick a delay-model format", [
            ("ECSM", "ecsm"), ("NLDM", "nldm"), ("CCS", "ccs"), ("Other / custom format...", "__custom__"),
        ], do_format, on_return)

    def _edit_back_end(self) -> None:
        """Mirrors Back_End/{gds,lef,spice}. lef/techfiles share one
        metal-stack axis (same as the real lef/<family>/techfiles/
        subdirectory living inside lef/<family>/, not beside it); gds
        doesn't -- a cell's own GDS geometry lives on metal layers shared
        by every stack option -- so it's a flat per-vth list like
        verilog/spice, not a per-stack one. Loops the same way
        _edit_front_end does."""
        def do_category(choice: str, resume_category) -> None:
            if choice == "gds":
                _enter_flat_category(
                    self, self._technology, self._root, f"{self._name} / Back-End", "gds",
                    "GDS files", resume_category, on_done=self._refresh,
                )
            elif choice == "lef":
                self._edit_lef_menu(f"{self._name} / Back-End", resume_category)
            elif choice == "spice":
                _enter_flat_category(
                    self, self._technology, self._root, f"{self._name} / Back-End",
                    "spice_models", "SPICE models", resume_category, on_done=self._refresh,
                )
        _loop_fixed_choice(self, f"{self._name} / Back-End\nPick a category", [
            ("GDS", "gds"), ("LEF", "lef"), ("SPICE", "spice"),
        ], do_category, lambda: None)

    def _edit_lef_menu(self, breadcrumb: str, on_return) -> None:
        def do_choice(choice: str, resume_choice) -> None:
            if choice == "lef":
                _enter_stack_field(
                    self, self._technology, self._root, breadcrumb, "lef", "LEF files",
                    resume_choice, on_done=self._refresh,
                )
            elif choice == "techfiles":
                _enter_stack_field(
                    self, self._technology, self._root, breadcrumb, "qrc_techfiles",
                    "QRC techfiles", resume_choice, on_done=self._refresh,
                )
        _loop_fixed_choice(self, f"{breadcrumb} / LEF\nPick LEF files or techfiles", [
            ("LEF files", "lef"), ("Techfiles (QRC captables)", "techfiles"),
        ], do_choice, on_return)

    def _edit_signoff(self) -> None:
        """Mirrors the real MMMC object chain (opconds -> delay corners ->
        analysis views, each referencing declared timing/rc corner names
        by name) as a static, fully-declared catalog -- the dynamic part
        (which of these actually drive a given run) is an environment-
        level concern, not edited here. Loops the same way Front-End/
        Back-End do."""
        def do_category(choice: str, resume_category) -> None:
            if choice == "opconds":
                self._edit_opconds(resume_category)
            elif choice == "delay_corners":
                self._edit_delay_corners(resume_category)
            elif choice == "analysis_views":
                self._edit_analysis_views(resume_category)
        _loop_fixed_choice(self, f"{self._name} / Signoff\nPick a category", [
            ("Opconds (optional, process/voltage/temperature)", "opconds"),
            ("Delay corners (PVT corner + RC corner pairing)", "delay_corners"),
            ("Analysis views (delay corner + setup/hold/dynamic/leakage)", "analysis_views"),
        ], do_category, lambda: None)

    def _edit_opconds(self, on_return) -> None:
        def handle(opconds: Optional[dict]) -> None:
            if opconds is not None:
                if opconds:
                    self._technology["opconds"] = opconds
                else:
                    self._technology.pop("opconds", None)
                self._refresh()
            on_return()
        self.push_screen(
            _OpcondsScreen(f"{self._name} / Signoff / Opconds", self._technology.get("opconds", {})), handle,
        )

    def _edit_delay_corners(self, on_return) -> None:
        def handle(delay_corners: Optional[dict]) -> None:
            if delay_corners is not None:
                if delay_corners:
                    self._technology["delay_corners"] = delay_corners
                else:
                    self._technology.pop("delay_corners", None)
                self._refresh()
            on_return()
        self.push_screen(
            _DelayCornersScreen(
                f"{self._name} / Signoff / Delay corners", self._technology,
                self._technology.get("delay_corners", {}),
            ),
            handle,
        )

    def _edit_analysis_views(self, on_return) -> None:
        def handle(analysis_views: Optional[dict]) -> None:
            if analysis_views is not None:
                if analysis_views:
                    self._technology["analysis_views"] = analysis_views
                else:
                    self._technology.pop("analysis_views", None)
                self._refresh()
            on_return()
        self.push_screen(
            _AnalysisViewsScreen(
                f"{self._name} / Signoff / Analysis views", self._technology,
                self._technology.get("analysis_views", {}),
            ),
            handle,
        )

    def _edit_dont_use(self) -> None:
        synthesis = self._technology.setdefault("synthesis", {})

        def handle(values: Optional[list]) -> None:
            if values is not None:
                synthesis["dont_use"] = values
                self._refresh()
        self.push_screen(
            _StringListScreen("Dont_use cell name globs", synthesis.get("dont_use", [])), handle,
        )

    def _edit_setup_yaml_fragment(self) -> None:
        def handle(value: Optional[str]) -> None:
            if value is not None:
                if value:
                    self._technology["setup_yaml_fragment"] = value
                else:
                    self._technology.pop("setup_yaml_fragment", None)
                self._refresh()
        self.push_screen(
            _SingleFileScreen(
                "Setup.yaml fragment (flow knobs for this PDK)", self._root,
                self._technology.get("setup_yaml_fragment"),
            ),
            handle,
        )

    def _edit_generic(self) -> None:
        """Edit technology.generic as raw YAML in $EDITOR.

        Deliberately not a structured form: this bucket exists precisely
        for fields WOLF doesn't (yet) have dedicated handling for
        (tech_layermap, rc_corners, ...) -- see the module docstring and
        wolf.environment's own _technology_inputs. A text round-trip
        through $EDITOR shows and lets you edit literally anything here,
        with no schema WOLF would need to keep in lockstep.
        """
        import tempfile
        generic = self._technology.get("generic", {})
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", prefix="wolf-pdk-generic-", delete=False,
        ) as handle:
            handle.write(yaml.safe_dump(generic, sort_keys=False))
            temp_path = Path(handle.name)
        try:
            _open_in_editor(self, temp_path)
            text = temp_path.read_text(encoding="utf-8")
            try:
                parsed = yaml.safe_load(text) or {}
            except yaml.YAMLError as error:
                self.notify(f"Generic fields not saved -- invalid YAML: {error}", severity="error")
                return
            if not isinstance(parsed, dict):
                self.notify("Generic fields not saved -- must be a YAML mapping.", severity="error")
                return
            self._technology["generic"] = parsed
            self._refresh()
        finally:
            temp_path.unlink(missing_ok=True)

    def _save(self, *, close: bool) -> None:
        temporary = self._manifest_path.with_suffix(".yaml.tmp")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self._is_new:
            self._data.setdefault("author", os.environ.get("USER", "unknown"))
            self._data.setdefault("creation-date", now)
        self._data["last-modified-date"] = now
        try:
            self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(yaml.safe_dump(self._data, sort_keys=False), encoding="utf-8")
            load_manifest(temporary)
            temporary.replace(self._manifest_path)
        except Exception as error:
            self.notify(f"Could not save {self._manifest_path}: {error}", severity="error")
            return
        finally:
            temporary.unlink(missing_ok=True)

        self.notify(f"Saved {self._manifest_path}")
        self._is_new = False
        self._dirty = False
        self._update_subtitle()
        if close:
            self.exit()


def _default_document(name: str, root: str) -> dict:
    return {
        "schema_version": 1,
        "kind": "pdk",
        "name": name,
        "description": f"{name} PDK package",
        "source": {"type": "local-path", "root": root, "revision": "unset"},
        "license": {},
        "validation": {"required_paths": []},
        "metadata": {"technology": {"name": name}},
    }


def _writable_local_registries() -> list:
    return [spec for spec in RegistryManager().specs() if spec.type == "local"]


def _existing_pdk_names() -> list[str]:
    return sorted(
        manifest.identifier.name
        for manifest in PackageRegistry().manifests()
        if manifest.identifier.kind == "pdk"
    )


class _PdkPickerApp(App[Optional[str]]):
    """A one-shot picker: existing pdk/* packages, plus "create new"."""

    CSS = """
    #dialog {
        width: 80; height: auto; max-height: 30; border: round #ad4ce5; padding: 1 2;
        background: $surface;
    }
    #dialog-title { color: #ad4ce5; text-style: bold; margin-bottom: 1; }
    #dialog-hint { color: $text-muted; margin-top: 1; }
    Screen { align: center middle; }
    OptionList { border: round #ad4ce5; }
    """

    def __init__(self, names: list[str]):
        super().__init__()
        self._names = names

    def on_mount(self) -> None:
        choices = [(f"pdk/{name}", name) for name in self._names]
        choices.append(("Create a new PDK package...", "__create__"))

        def handle(value: Optional[str]) -> None:
            self.exit(value)
        self.push_screen(_PickScreen("Pick a PDK package to edit", choices), handle)


def _pick_or_create_package_name() -> Optional[str]:
    """No NAME given: pick an existing pdk/* package, or name a new one."""
    chosen = _PdkPickerApp(_existing_pdk_names()).run()
    if chosen is None:
        return None
    if chosen != "__create__":
        return chosen
    new_name = input("New PDK package name (e.g. tsmc65): ").strip()
    return new_name or None


def open_pdk_menu(name: Optional[str] = None) -> None:
    """Resolve NAME to a manifest path (existing or new) and run the menu.

    NAME may be a dotted path (`tsmc65`, `tsmc65.9T`, or `tsmc65.9T.lvt`)
    to jump straight into a track or vth; with no NAME at all, pick from
    existing pdk/* packages or name a new one first.

    Kept out of PdkMenuApp.__init__ so picking a package (or a destination
    registry for a brand new one) stays separate from the editor itself.
    """
    if name is None:
        name = _pick_or_create_package_name()
        if name is None:
            return

    parts = name.split(".")
    package_name = parts[0]
    initial_track = parts[1] if len(parts) > 1 else None
    initial_vth = parts[2] if len(parts) > 2 else None
    if len(parts) > 3 or not package_name:
        raise ValueError(f"invalid pdk menu target {name!r}; expected NAME[.TRACK[.VTH]]")

    identifier = str(PackageId.parse(f"pdk/{package_name}"))
    registry = PackageRegistry()
    try:
        manifest = registry.get(identifier)
    except ValueError:
        manifest = None

    if manifest is not None:
        manifest_path = Path(manifest.manifest_path)
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        PdkMenuApp(
            package_name, manifest_path, data, is_new=False,
            initial_track=initial_track, initial_vth=initial_vth,
        ).run()
        return

    if initial_track is not None:
        raise ValueError(f"pdk/{package_name} does not exist yet; create it first without .{initial_track}")

    local_registries = _writable_local_registries()
    if not local_registries:
        raise ValueError(
            "no local package registry is configured to create pdk/"
            f"{package_name} in; add one with: wolf registry add <name> <path> --type local"
        )
    if len(local_registries) == 1:
        destination_root = RegistryManager().content_root(local_registries[0])
    else:
        print(f"pdk/{package_name} does not exist yet. Pick a registry to create it in:")
        for index, spec in enumerate(local_registries):
            print(f"  [{index}] {spec.name} ({spec.source})")
        choice = input("Registry index: ").strip()
        try:
            destination_root = RegistryManager().content_root(local_registries[int(choice)])
        except (ValueError, IndexError):
            raise ValueError(f"invalid registry choice: {choice!r}") from None

    source_root = input(
        f"Local filesystem root for pdk/{package_name}'s real files (e.g. /asic/Library/...): "
    ).strip()
    if not source_root or not Path(source_root).is_absolute():
        raise ValueError("pdk source root must be a nonempty absolute path")
    manifest_path = destination_root / "pdk" / f"{package_name}.yaml"
    if manifest_path.exists():
        raise ValueError(
            f"{manifest_path} already exists but is not a registered pdk/{package_name} manifest"
        )
    PdkMenuApp(
        package_name, manifest_path, _default_document(package_name, source_root), is_new=True,
    ).run()

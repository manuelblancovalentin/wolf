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
corner's qrc file, then the next corner) is the common case.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any, Optional

import yaml
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
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
            self.dismiss(None)


class _FilterableDirectoryTree(DirectoryTree):
    """A DirectoryTree that can hide dotfiles/dotdirs, toggled at runtime."""

    show_hidden = False

    def filter_paths(self, paths):
        if self.show_hidden:
            return paths
        return [path for path in paths if not path.name.startswith(".")]


class _BrowseFilesScreen(ModalScreen[Optional[list]]):
    """Browse the filesystem and collect one or more file paths, of any
    suffix -- a PDK tree mixes .lib/.lef/.gds/.v/.spi/.captable files, so
    unlike wolf.env_menu's RTL-only browser this never filters by suffix.

    'a' adds the highlighted file, or every file directly inside the
    highlighted directory; 'h' toggles hidden (dot) entries, off by
    default; enter on a file opens it in $EDITOR to inspect it rather than
    adding it (adding is always an explicit 'a'); escape finishes,
    returning whatever was added (possibly empty).
    """

    BINDINGS = [
        ("a", "add", "Add"),
        ("h", "toggle_hidden", "Hidden files"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, start: str, *, title: str = "Browse for files"):
        super().__init__()
        self._start = start
        self._title = title
        self._selected: list[str] = []
        self._show_hidden = False

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
        return (
            f"{picked} — enter: expand folder / edit file in $EDITOR — a: add — "
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
                if entry.is_file():
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
            f"enter: expand folder — a: use this directory — "
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
        return [
            Option(f"Libraries ({len(libraries)} file(s))", id="libraries"),
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


_VTH_FILE_FIELDS = (
    ("lef", "LEF files"),
    ("gds", "GDS files"),
    ("verilog_models", "Verilog models"),
    ("spice_models", "SPICE models"),
    ("qrc_techfiles", "QRC techfiles"),
)


class _VthScreen(ModalScreen[Optional[dict]]):
    """Edit one vth's corners plus its physical/behavioral file lists."""

    BINDINGS = [("escape", "done", "Done")]

    def __init__(self, title: str, root: Path, data: dict):
        super().__init__()
        self._title = title
        self._root = root
        self._data = dict(data)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*self._options())
            yield Static("enter: edit — esc: done", id="dialog-hint")

    def _options(self) -> list[Option]:
        corners = self._data.get("timing", {}).get("corners", {})
        options = [Option(f"Liberty corners ({len(corners)})", id="corners")]
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
        return f"{len(self._vths())} vth(s) — enter: edit — a: add — d: delete highlighted — esc: done"

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)
        self.query_one("#dialog-hint", Static).update(self._hint())

    def _edit(self, name: str) -> None:
        def handle(data: Optional[dict]) -> None:
            if data is not None:
                self._vths()[name] = data
                self._refresh()
        self.app.push_screen(
            _VthScreen(f"{self._track}/{name}", self._root, self._vths().get(name, {})), handle,
        )

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
        return f"{len(self._tracks)} track(s) — enter: edit — a: add — d: delete highlighted — esc: done"

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
    """`wolf pdk menu NAME` -- creates or edits a pdk/NAME registry manifest.

    Unlike environments, PDK packages have no "active" one to default to,
    so NAME is required: `wolf pdk menu tsmc65` either opens the existing
    pdk/tsmc65 manifest (wherever it's registered) or offers to create it
    in a chosen local registry.
    """

    CSS = """
    #dialog {
        width: 100; height: auto; max-height: 34; border: round #ad4ce5; padding: 1 2;
        background: $surface;
    }
    #dialog-title { color: #ad4ce5; text-style: bold; margin-bottom: 1; }
    #dialog-hint { color: $text-muted; margin-top: 1; }
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
    ]
    TITLE = "WOLF PDK setup"

    def __init__(self, name: str, manifest_path: Path, data: dict, *, is_new: bool):
        super().__init__()
        self._name = name
        self._manifest_path = manifest_path
        self._data = data
        self._is_new = is_new
        self._dirty = is_new
        self.last_browsed_dir: Optional[str] = None
        self.sub_title = self._name

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
            Option(f"Generic / other fields ({len(generic)} key(s), edit as YAML)", id="generic"),
            Option(f"Synthesis dont_use cells ({len(dont_use)})", id="dont_use"),
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
        elif choice == "generic":
            self._edit_generic()
        elif choice == "dont_use":
            self._edit_dont_use()

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

    def _edit_dont_use(self) -> None:
        synthesis = self._technology.setdefault("synthesis", {})

        def handle(values: Optional[list]) -> None:
            if values is not None:
                synthesis["dont_use"] = values
                self._refresh()
        self.push_screen(
            _StringListScreen("Dont_use cell name globs", synthesis.get("dont_use", [])), handle,
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


def open_pdk_menu(name: str) -> None:
    """Resolve pdk/NAME to a manifest path (existing or new) and run the menu.

    Kept out of PdkMenuApp.__init__ so picking a destination registry for a
    brand new package (a plain prompt, no need for the full app yet) stays
    separate from the editor itself.
    """
    identifier = str(PackageId.parse(f"pdk/{name}"))
    registry = PackageRegistry()
    try:
        manifest = registry.get(identifier)
    except ValueError:
        manifest = None

    if manifest is not None:
        manifest_path = Path(manifest.manifest_path)
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        PdkMenuApp(name, manifest_path, data, is_new=False).run()
        return

    local_registries = _writable_local_registries()
    if not local_registries:
        raise ValueError(
            "no local package registry is configured to create pdk/"
            f"{name} in; add one with: wolf registry add <name> <path> --type local"
        )
    if len(local_registries) == 1:
        destination_root = RegistryManager().content_root(local_registries[0])
    else:
        print(f"pdk/{name} does not exist yet. Pick a registry to create it in:")
        for index, spec in enumerate(local_registries):
            print(f"  [{index}] {spec.name} ({spec.source})")
        choice = input("Registry index: ").strip()
        try:
            destination_root = RegistryManager().content_root(local_registries[int(choice)])
        except (ValueError, IndexError):
            raise ValueError(f"invalid registry choice: {choice!r}") from None

    source_root = input(
        f"Local filesystem root for pdk/{name}'s real files (e.g. /asic/Library/...): "
    ).strip()
    if not source_root or not Path(source_root).is_absolute():
        raise ValueError("pdk source root must be a nonempty absolute path")
    manifest_path = destination_root / "pdk" / f"{name}.yaml"
    if manifest_path.exists():
        raise ValueError(f"{manifest_path} already exists but is not a registered pdk/{name} manifest")
    PdkMenuApp(name, manifest_path, _default_document(name, source_root), is_new=True).run()

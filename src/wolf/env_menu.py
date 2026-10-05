"""A real full-screen `wolf env menu`, a step-by-step environment builder.

Kept separate from `wolf.commands.env` so Textual is only imported when this
specific subcommand actually runs, not on every WOLF invocation (same reason
`wolf.config_menu` is its own module).

Creates a new declarative-v1 environment, or edits an existing one in
place (reloading its current wolf.yaml to prefill the wizard, if it has
one -- an existing legacy environment with no wolf.yaml yet starts empty
and gets one written into its same directory on save). The order of
steps mirrors the dependency order discussed for environment setup: RTL
sources first (nothing else can be meaningfully picked before there is
RTL), then design name/top (offered from module names found in those
sources), then the technology (PDK) and flow/backend, then the project
root.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Optional

import yaml
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button, DirectoryTree, Footer, Header, Input, OptionList, Static, TextArea, Tree,
)
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode

_RTL_SUFFIXES = (".v", ".sv", ".vhd", ".vhdl")

from wolf.backend import backend_names
from wolf.environment import ENVIRONMENT_FILENAME, ENVIRONMENT_SCHEMA, load_environment
from wolf.flow_inspect import FlowStructure, parse_flow_directory
from wolf.package.installer import PackageInstaller
from wolf.package.registry import PackageRegistry
from wolf.package.store import PackageStore
from wolf.paths import builtin_flow_root, environments_dir
from wolf.project_tree import PER_DESIGN_INPUT_CATEGORIES, ProjectTreeScan, scan_design, scan_project_tree


_MODULE_RE = re.compile(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_$]*)", re.MULTILINE)


def _absolute(raw: str) -> str:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return str(path.resolve())


def _scan_modules(sources: list[dict]) -> list[str]:
    """Verilog/SystemVerilog module names found in local-path sources.

    VHDL entities and package-backed sources aren't scanned -- a package's
    own metadata already names the design (see design.package/top), and
    VHDL detection isn't implemented yet.
    """
    names: list[str] = []
    for entry in sources:
        raw = entry.get("path")
        if not raw:
            continue
        path = Path(raw)
        if path.suffix.lower() not in (".v", ".sv"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in _MODULE_RE.finditer(text):
            name = match.group(1)
            if name not in names:
                names.append(name)
    return names


def _source_label(entry: dict) -> str:
    if entry.get("package"):
        return f"rtl package: {entry['package']}"
    return f"local path: {entry.get('path', '')}"


def _open_in_editor(app: App, path: Path) -> None:
    """Suspend the TUI and open a file in $EDITOR (vim by default)."""
    editor = os.environ.get("EDITOR", "vim")
    try:
        with app.suspend():
            subprocess.run([editor, str(path)])
    except Exception as error:  # SuspendNotSupported, or the editor itself failing
        app.notify(f"could not open {path} in {editor!r}: {error}", severity="error")


def _package_location_hint(manifest) -> str:
    """Say what "not installed" actually costs for this package's source type.

    `wolf install` always means "validate and record a revision", but what
    that takes differs a lot: a local-path or package-path package's real
    files are already sitting on disk (most PDKs here), so installing it
    is instant and copies nothing; a git package is actually cloned. "not
    installed" alone reads like "not available, go find it in a catalog"
    -- WOLF has no such catalog to browse or auto-provision from, so the
    picker and the confirm prompt both spell out which case this is.
    """
    source = manifest.source
    if source.type in ("local-path", "package-path"):
        return "already on disk, installing just records this revision"
    return f"not fetched yet, installing clones it from {source.url}"


def _package_choice(manifest) -> tuple[str, str, str]:
    """Return (label, id, detail) for one package picker entry.

    The label alone is always one short line -- "kind/name (installed)"
    or "kind/name (not installed)" -- so entries never wrap into each
    other; the longer explanation of what "not installed" costs here is
    the detail, shown only for whichever entry is currently highlighted
    (see _PickScreen).
    """
    identifier = str(manifest.identifier)
    if PackageStore().read(manifest) is not None:
        return f"{identifier} (installed)", identifier, ""
    return f"{identifier} (not installed)", identifier, _package_location_hint(manifest)


def _maybe_install(app: App, package_id: str, on_done) -> None:
    """Offer to `wolf install` a picked-but-uninstalled package, then continue.

    A local-path package (most PDKs on this host) installs instantly --
    it only records a validated revision, nothing is copied. A git
    package is actually cloned. Either way this never blocks picking the
    package: declining, or a failed install, still calls on_done so the
    reference can be set now and installed later with a plain
    `wolf install`.
    """
    manifest = PackageRegistry().get(package_id)
    if PackageStore().read(manifest) is not None:
        on_done()
        return

    def handle_confirm(choice: Optional[str]) -> None:
        if choice == "yes":
            try:
                PackageInstaller().install(package_id)
                app.notify(f"Installed {package_id}")
            except Exception as error:
                app.notify(f"Could not install {package_id}: {error}", severity="error")
        on_done()
    app.push_screen(
        _PickScreen(
            f"{package_id} is not installed ({_package_location_hint(manifest)}). Install it now?",
            [("Yes", "yes"), ("No", "no")],
        ),
        handle_confirm,
    )


def _technology_tracks(package: str) -> dict:
    """A tracked PDK package's own technology.tracks, read straight from
    its manifest -- empty for a flat (single implicit corner) package,
    which has nothing to pick here."""
    manifest = PackageRegistry().get(package)
    technology = manifest.metadata.get("technology", {})
    tracks = technology.get("tracks", {}) if isinstance(technology, dict) else {}
    return tracks if isinstance(tracks, dict) else {}


def _technology_metal_stacks(package: str, track: str, vth: str) -> list[str]:
    """Every named metal stack declared for one track/vth's lef/
    qrc_techfiles -- must match wolf.environment's own
    _STACK_KEYED_FIELDS. Empty means this vth has no named stacks at
    all (a flat lef list, or none declared yet) -- nothing to pick,
    WOLF resolves it without technology.metal_stack."""
    tracks = _technology_tracks(package)
    track_data = tracks.get(track, {})
    vth_data = track_data.get("vths", {}).get(vth, {}) if isinstance(track_data, dict) else {}
    if not isinstance(vth_data, dict):
        return []
    stacks: set = set()
    for key in ("lef", "qrc_techfiles"):
        value = vth_data.get(key)
        if isinstance(value, dict):
            stacks.update(value)
    return sorted(stacks)


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


class _FilterableDirectoryTree(DirectoryTree):
    """A DirectoryTree that can hide dotfiles/dotdirs, toggled at runtime."""

    show_hidden = False

    def filter_paths(self, paths):
        if self.show_hidden:
            return paths
        return [path for path in paths if not path.name.startswith(".")]


class _BrowseScreen(ModalScreen[Optional[list]]):
    """Browse the filesystem and collect one or more file paths.

    Consistent with every other list screen here: 'a' adds (the
    highlighted file, or every matching-suffix file directly inside the
    highlighted directory), 'h' toggles hidden (dot) files and
    directories, off by default. Enter on a directory expands/collapses
    it -- the tree's own default, left untouched. Enter on a file opens
    it in $EDITOR to view it, rather than adding it -- adding is always
    an explicit 'a'. Escape finishes, returning whatever was added.

    `suffixes` narrows which files 'a' picks up from a directory (RTL by
    default); pass `None` to accept any file. `title`/`label` adapt the
    dialog's wording for whatever this particular browse is collecting
    (RTL sources, an SDC file, ...) without needing a separate screen
    class per file kind.
    """

    BINDINGS = [
        ("a", "add", "Add"),
        ("h", "toggle_hidden", "Hidden files"),
        ("escape", "done", "Done"),
    ]

    def __init__(
        self, start: str, *, suffixes: Optional[tuple] = _RTL_SUFFIXES,
        title: str = "Browse for RTL files", label: str = "file(s)",
    ):
        super().__init__()
        self._start = start
        self._suffixes = suffixes
        self._title = title
        self._label = label
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
        picked = f"{len(self._selected)} {self._label} picked" if self._selected else "none picked yet"
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
                if entry.is_file() and (not self._suffixes or entry.suffix.lower() in self._suffixes):
                    resolved = str(entry.resolve())
                    if resolved not in self._selected:
                        self._selected.append(resolved)
                        added += 1
            if added:
                self.app.notify(f"Added {added} {self._label} from {path}")
            else:
                self.app.notify("No new matching files in that directory.", severity="warning")
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
    """Browse the filesystem and pick one directory, e.g. a project root.

    'a' uses the highlighted directory (or its parent, if a file is
    highlighted); 'n' creates a new folder inside the highlighted
    directory and expands into it; 'h' toggles hidden (dot) files and
    directories, off by default, same as the RTL browser. Enter still
    just expands/collapses a folder. Escape cancels.
    """

    BINDINGS = [
        ("a", "select", "Use this directory"),
        ("n", "new_folder", "New folder"),
        ("h", "toggle_hidden", "Hidden files"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, start: str):
        super().__init__()
        self._start = start
        self._show_hidden = False

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Browse for a directory", id="dialog-title")
            tree = _FilterableDirectoryTree(self._start, id="browse-tree")
            tree.show_hidden = self._show_hidden
            yield tree
            yield Static(self._hint(), id="dialog-hint")

    def _hint(self) -> str:
        hidden = "shown" if self._show_hidden else "hidden"
        return (
            f"enter: expand folder — a: use this directory — n: new folder here — "
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

    def _highlighted_node(self) -> Optional[TreeNode]:
        node = self.query_one(DirectoryTree).cursor_node
        if node is None:
            return None
        return node if node.data.path.is_dir() else node.parent

    def _highlighted_directory(self) -> Optional[Path]:
        node = self._highlighted_node()
        return node.data.path if node is not None else None

    def action_select(self) -> None:
        directory = self._highlighted_directory()
        if directory is not None:
            self.dismiss(str(directory.resolve()))

    def action_new_folder(self) -> None:
        parent_node = self._highlighted_node()
        if parent_node is None:
            return
        directory = parent_node.data.path

        async def handle_name(name: Optional[str]) -> None:
            if not name:
                return
            new_directory = directory / name
            try:
                new_directory.mkdir()
            except OSError as error:
                self.app.notify(f"Could not create folder: {error}", severity="error")
                return
            self.app.notify(f"Created {new_directory}")
            tree = self.query_one(DirectoryTree)
            await tree.reload_node(parent_node)
            resolved = new_directory.resolve()
            child = next(
                (node for node in parent_node.children if node.data.path.resolve() == resolved), None,
            )
            if child is not None:
                tree.move_cursor(child)
        self.app.push_screen(_TextScreen(f"New folder name (inside {directory})"), handle_name)

    def action_cancel(self) -> None:
        self.dismiss(None)


class _StepDetailScreen(ModalScreen[None]):
    """Read-only view of one flow step's real Tcl body, plus provenance."""

    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close")]

    CSS = """
    #step-dialog {
        width: 110; height: 36; border: round #ad4ce5; padding: 1 2;
        background: $surface;
    }
    #step-title { color: #ad4ce5; text-style: bold; }
    #step-meta { color: $text-muted; margin-bottom: 1; }
    #step-body { height: 1fr; border: round #ad4ce5; }
    #step-location { color: $text-muted; margin-top: 1; }
    """

    def __init__(self, name: str, step):
        super().__init__()
        self._name = name
        self._step = step

    def compose(self) -> ComposeResult:
        with Vertical(id="step-dialog"):
            yield Static(self._name, id="step-title")
            if self._step is None:
                yield Static(
                    "Not defined in this flow's local Tcl files -- provided elsewhere "
                    "(e.g. Cadence's own template generator, as init_dft/add_dft would be).",
                    id="step-meta",
                )
            else:
                meta = f"owner={self._step.owner or '-'}  write_db={'yes' if self._step.write_db else 'no'}"
                yield Static(meta, id="step-meta")
                yield TextArea(
                    self._step.body, read_only=True, show_line_numbers=True, id="step-body",
                )
                yield Static(f"{self._step.file} : line {self._step.line}", id="step-location")
            yield Static("esc: close", id="dialog-hint")

    def action_close(self) -> None:
        self.dismiss(None)


class _FlowInspectScreen(ModalScreen[None]):
    """Tree view of a flow's real create_flow/create_flow_step structure.

    Shows the actual nesting, not a flat list of every `create_flow`: a
    flow that's itself a member of another flow (syn_generic inside
    synthesis, synthesis inside block) appears as that parent's child, the
    same containment the real Tcl defines. Top-level nodes are whichever
    flows aren't a member of any other flow (flow_top, usually just one --
    "block" here). Selecting a leaf step opens _StepDetailScreen with that
    step's actual Tcl body. A step a sequence references but that isn't
    defined anywhere in this flow's own files (e.g. init_dft, left to a
    Cadence-template generator) still shows up and is selectable -- it
    just says so instead of showing a body.
    """

    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close")]

    def __init__(self, root: Path, structure: FlowStructure):
        super().__init__()
        self._root = root
        self._structure = structure

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(f"Flow structure: {self._root}", id="dialog-title")
            tree: Tree = Tree(self._root.name)
            tree.root.expand()

            sequences_by_name = {sequence.name: sequence for sequence in self._structure.sequences}
            members = {name for sequence in self._structure.sequences for name in sequence.steps}
            roots = [sequence.name for sequence in self._structure.sequences if sequence.name not in members]
            if not roots:
                # No single top-level flow found (e.g. no create_flow at all,
                # or a reference cycle) -- fall back to listing every
                # sequence at the top level rather than showing nothing.
                roots = [sequence.name for sequence in self._structure.sequences]

            reached: set[str] = set()
            for root_name in roots:
                self._add_node(tree.root, root_name, sequences_by_name, reached, set())

            orphans = sorted(set(self._structure.steps) - reached)
            if orphans:
                other_node = tree.root.add("(steps not reachable from any top-level flow)", expand=False)
                for name in orphans:
                    other_node.add_leaf(name, data=name)
            if not self._structure.sequences:
                for name in sorted(self._structure.steps):
                    tree.root.add_leaf(name, data=name)

            yield tree
            yield Static("enter: view step — esc: close", id="dialog-hint")

    def _add_node(
        self, parent: TreeNode, name: str, sequences_by_name: dict, reached: set[str], ancestors: set[str],
    ) -> None:
        reached.add(name)
        sequence = sequences_by_name.get(name)
        if sequence is None:
            defined = name in self._structure.steps
            parent.add_leaf(name if defined else f"{name} (not defined locally)", data=name)
            return
        node = parent.add(f"{name} (flow)", expand=True)
        if name in ancestors:
            node.add_leaf("(already shown above — recursive reference)")
            return
        for member in sequence.steps:
            self._add_node(node, member, sequences_by_name, reached, ancestors | {name})

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        event.stop()
        name = event.node.data
        if not name:
            return
        self.app.push_screen(_StepDetailScreen(name, self._structure.steps.get(name)))

    def action_close(self) -> None:
        self.dismiss(None)


class _PickScreen(ModalScreen[Optional[str]]):
    """Pick one id out of a list of (label, id) choices.

    Labels stay short so entries never wrap into each other -- the usual
    cause of a list being hard to read. An optional `details` map (id ->
    longer text) is shown for whichever entry is currently highlighted,
    one line at a time, instead of being crammed into every option.
    """

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


class _SourcesScreen(ModalScreen[Optional[list]]):
    """Add/remove design.sources entries: installed rtl packages or local paths.

    'a' adds (choosing browse / manual path / installed package), 'd'
    deletes the highlighted entry, enter opens a local-path entry in
    $EDITOR to view it (a package entry has no single file to open).
    Escape finishes, keeping whatever was added or removed so far.
    """

    BINDINGS = [
        ("a", "add", "Add"),
        ("d", "delete", "Delete"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, sources: list[dict]):
        super().__init__()
        self._sources = list(sources)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("RTL sources", id="dialog-title")
            yield OptionList(*self._options())
            yield Static(
                "enter: open path in $EDITOR — a: add — d: delete highlighted — esc: done",
                id="dialog-hint",
            )

    def _options(self) -> list[Option]:
        if not self._sources:
            return [Option("(none yet — press 'a' to add)", id="__empty__", disabled=True)]
        return [Option(_source_label(entry), id=str(index)) for index, entry in enumerate(self._sources)]

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id in (None, "__empty__"):
            return
        entry = self._sources[int(event.option_id)]
        if entry.get("path"):
            _open_in_editor(self.app, Path(entry["path"]))
        else:
            self.app.notify(f"{entry.get('package')} is an installed package, not a single file.")

    def action_add(self) -> None:
        def handle_method(method: Optional[str]) -> None:
            if method == "browse":
                existing = next((Path(e["path"]).parent for e in reversed(self._sources) if e.get("path")), None)
                start = str(existing or Path.home())

                def handle_browse(paths: Optional[list]) -> None:
                    if paths:
                        for path in paths:
                            if not any(e.get("path") == path for e in self._sources):
                                self._sources.append({"path": path})
                        self._refresh()
                self.app.push_screen(_BrowseScreen(start), handle_browse)
            elif method == "manual":
                def handle_path(value: Optional[str]) -> None:
                    if value:
                        self._sources.append({"path": _absolute(value)})
                        self._refresh()
                self.app.push_screen(_TextScreen("Path to an RTL file"), handle_path)
            elif method == "package":
                entries = [
                    _package_choice(manifest) for manifest in PackageRegistry().manifests()
                    if manifest.identifier.kind == "rtl"
                ]
                if not entries:
                    self.app.notify("No rtl/* packages found in any configured registry.", severity="warning")
                    return
                choices = [(label, identifier) for label, identifier, _ in entries]
                details = {identifier: detail for _, identifier, detail in entries if detail}

                def handle_package(value: Optional[str]) -> None:
                    if not value:
                        return

                    def finish() -> None:
                        self._sources.append({"package": value})
                        self._refresh()
                    _maybe_install(self.app, value, finish)
                self.app.push_screen(_PickScreen("Pick an rtl package", choices, details), handle_package)
        self.app.push_screen(
            _PickScreen("Add a source", [
                ("Browse filesystem", "browse"),
                ("Type a path manually", "manual"),
                ("Installed rtl package", "package"),
            ]),
            handle_method,
        )

    def action_delete(self) -> None:
        option_list = self.query_one(OptionList)
        index = option_list.highlighted
        if index is None or index >= len(self._sources):
            return
        del self._sources[index]
        self._refresh()

    def action_done(self) -> None:
        self.dismiss(self._sources)


class _ConstraintFilesScreen(ModalScreen[Optional[list]]):
    """Add/remove constraints.files entries -- SDC files applied to
    every run, the same local-path shape design.sources' own path
    entries use. 'a' adds (browse, filtered to .sdc, or type a path
    manually), 'd' deletes the highlighted entry, enter opens one in
    $EDITOR to view it, escape finishes."""

    BINDINGS = [
        ("a", "add", "Add"),
        ("d", "delete", "Delete"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, files: list[str]):
        super().__init__()
        self._files = list(files)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Constraints (SDC) files", id="dialog-title")
            yield OptionList(*self._options())
            yield Static(
                "enter: open in $EDITOR — a: add — d: delete highlighted — esc: done",
                id="dialog-hint",
            )

    def _options(self) -> list[Option]:
        if not self._files:
            return [Option("(none yet — press 'a' to add)", id="__empty__", disabled=True)]
        return [Option(path, id=str(index)) for index, path in enumerate(self._files)]

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id in (None, "__empty__"):
            return
        _open_in_editor(self.app, Path(self._files[int(event.option_id)]))

    def action_add(self) -> None:
        def handle_method(method: Optional[str]) -> None:
            if method == "browse":
                existing = next((Path(path).parent for path in reversed(self._files)), None)
                start = str(existing or Path.home())

                def handle_browse(paths: Optional[list]) -> None:
                    if paths:
                        for path in paths:
                            if path not in self._files:
                                self._files.append(path)
                        self._refresh()
                self.app.push_screen(
                    _BrowseScreen(start, suffixes=(".sdc",), title="Browse for SDC files", label="SDC file(s)"),
                    handle_browse,
                )
            elif method == "manual":
                def handle_path(value: Optional[str]) -> None:
                    if value:
                        self._files.append(_absolute(value))
                        self._refresh()
                self.app.push_screen(_TextScreen("Path to an SDC file"), handle_path)
        self.app.push_screen(
            _PickScreen("Add a constraints file", [
                ("Browse filesystem", "browse"),
                ("Type a path manually", "manual"),
            ]),
            handle_method,
        )

    def action_delete(self) -> None:
        option_list = self.query_one(OptionList)
        index = option_list.highlighted
        if index is None or index >= len(self._files):
            return
        del self._files[index]
        self._refresh()

    def action_done(self) -> None:
        self.dismiss(self._files)


class _ProjectScanScreen(ModalScreen[Optional[str]]):
    """Shows the shallow structural scan of a project root (see
    wolf.project_tree.scan_project_tree) -- which of inputs/outputs/
    workspace exist, which inputs/ categories are present, and which
    design names they suggest. This scan always runs the moment a
    project root is set to an existing directory, never skipped --
    an all-missing result (a genuinely new, empty directory) is shown
    the same way a populated one is, not silently passed over.

    Picking a design name triggers the deeper per-design scan
    (wolf.project_tree.scan_design), prefilling RTL sources, design
    name/top, and constraints in the wizard's own in-memory state --
    still nothing written to wolf.yaml until Save. Escape (or no design
    names found at all) leaves the project root set with nothing else
    prefilled; the manual, pick-everything-by-hand flow underneath is
    completely unaffected either way.
    """

    BINDINGS = [("escape", "done", "Done")]

    def __init__(self, root: Path, scan: ProjectTreeScan):
        super().__init__()
        self._root = root
        self._scan = scan

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(f"Project tree scan: {self._root}", id="dialog-title")
            yield Static(self._structure_summary(), id="scan-summary")
            yield OptionList(*self._options())
            yield Static(self._hint(), id="dialog-hint")

    def _structure_summary(self) -> str:
        def mark(value: bool) -> str:
            return "present" if value else "missing"
        lines = [
            f"inputs/: {mark(self._scan.inputs_exists)}  "
            f"outputs/: {mark(self._scan.outputs_exists)}  "
            f"workspace/: {mark(self._scan.workspace_exists)}",
        ]
        for category in PER_DESIGN_INPUT_CATEGORIES:
            cat_scan = self._scan.categories[category]
            lines.append(f"  inputs/{category}: {mark(cat_scan.exists)} ({len(cat_scan.designs)} design(s))")
        present_libs = sorted(name for name, exists in self._scan.lib_subdirs.items() if exists)
        lines.append(f"  inputs/lib: {', '.join(present_libs) or 'none found'}")
        return "\n".join(lines)

    def _design_label(self, name: str) -> str:
        missing = self._scan.designs_missing_categories(name)
        return f"{name} (missing: {', '.join(missing)})" if missing else f"{name} (complete)"

    def _options(self) -> list[Option]:
        if not self._scan.design_names:
            return [Option(
                "(no existing design found here -- esc to continue manually)",
                id="__empty__", disabled=True,
            )]
        return [Option(self._design_label(name), id=name) for name in self._scan.design_names]

    def _hint(self) -> str:
        return "enter: load this design's inputs — esc: continue without picking one"

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id and event.option_id != "__empty__":
            self.dismiss(event.option_id)

    def action_done(self) -> None:
        self.dismiss(None)


class _MainMenuOptionList(OptionList):
    """The main menu's own list: arrow-down off the last row moves focus
    into the Save/Quit buttons below, instead of just stopping there."""

    def action_cursor_down(self) -> None:
        if self.highlighted is not None and self.highlighted == self.option_count - 1:
            self.screen.query_one("#save", Button).focus()
            return
        super().action_cursor_down()


class EnvWizardApp(App[None]):
    """`wolf env menu [NAME]` -- creates or edits a declarative-v1 environment.

    NAME defaults to the active environment (same fallback `wolf env
    remove`/`set` use), so the normal flow is `wolf env create` (empty),
    `wolf activate`, `wolf env menu` with no argument, `wolf deactivate` --
    never naming the environment a second time while it's already active.
    """

    CSS = """
    #dialog {
        width: 90; height: auto; max-height: 30; border: round #ad4ce5; padding: 1 2;
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
    TITLE = "WOLF environment setup"

    def __init__(self, name: str):
        super().__init__()
        self._name = name
        self._path = environments_dir() / name
        self._dirty = False
        self.sources: list[dict] = []
        self.design_name: Optional[str] = None
        self.design_top: Optional[str] = None
        self.technology_package: Optional[str] = None
        self.technology_track: Optional[str] = None
        self.technology_vth: Optional[str] = None
        self.technology_metal_stack: Optional[str] = None
        self.flow_package: Optional[str] = None
        self.backend: Optional[str] = None
        self.project_root: Optional[str] = None
        self.workspace_root: Optional[str] = None
        self.constraint_files: list[str] = []

        manifest = self._path / ENVIRONMENT_FILENAME
        if manifest.is_file():
            profile = load_environment(manifest, expected_name=name)
            if profile.design:
                self.design_name = profile.design.name
                self.design_top = profile.design.top
            self.sources = [
                {"package": entry.package} if entry.package else {"path": entry.path}
                for entry in profile.design_sources
            ]
            if profile.technology:
                self.technology_package = profile.technology.package
                self.technology_track = profile.technology.track
                self.technology_vth = profile.technology.vth
                self.technology_metal_stack = profile.technology.metal_stack
            if profile.flow and profile.flow.package:
                self.flow_package = profile.flow.package
            # A flow with no package (bundled default) also has no recorded
            # backend -- that choice is only ever used as a `wolf run
            # --backend` override, never persisted. Re-editing such an
            # environment starts flow/backend unset; pick it again if needed.
            self.project_root = profile.project_root
            self.workspace_root = profile.workspace_root
            self.constraint_files = list(profile.constraint_files)
        self.sub_title = self._name

    def compose(self) -> ComposeResult:
        yield Header()
        yield _MainMenuOptionList(*self._options())
        with Horizontal(id="actions"):
            yield Button("Save", id="save")
            yield Button("Quit without saving", id="quit_")
        yield Footer()

    def on_key(self, event) -> None:
        """Arrow-key navigation between the option list and the buttons
        below it (Tab/Shift+Tab still work too, Textual's own default)."""
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
        sources_label = f"{len(self.sources)} entr{'y' if len(self.sources) == 1 else 'ies'}" \
            if self.sources else "none yet"
        design_label = " / ".join(filter(None, (self.design_name, self.design_top))) or "not set"
        technology_label = self.technology_package or "not set"
        if self.technology_package and self.technology_track:
            technology_label += f" ({self.technology_track}/{self.technology_vth}"
            technology_label += f", {self.technology_metal_stack})" if self.technology_metal_stack else ")"
        flow_label = self.flow_package or (f"bundled default, backend={self.backend}" if self.backend else "not set")
        workspace_label = self.workspace_root or (
            f"{self.project_root}/workspace (default)" if self.project_root else "not set"
        )
        constraints_label = (
            f"{len(self.constraint_files)} file(s)" if self.constraint_files else "none yet"
        )
        # Everything but "Project root" needs a project root to mean
        # anything -- RTL added before one is set has nowhere to be copied
        # into at save time (see _save's own copy-into-inputs/hdl step),
        # and a scan can't run without a directory to scan. Visible but
        # unselectable (not hidden) so it's clear what's gating the rest,
        # not just missing.
        gated = not self.project_root
        return [
            Option(f"Project root: {self.project_root or 'not set'}", id="project"),
            Option(f"RTL sources: {sources_label}", id="sources", disabled=gated),
            Option(f"Design name / top: {design_label}", id="design", disabled=gated),
            Option(f"Technology (PDK): {technology_label}", id="technology", disabled=gated),
            Option(f"Flow / backend: {flow_label}", id="flow", disabled=gated),
            Option(f"Constraints (SDC): {constraints_label}", id="constraints", disabled=gated),
            Option(f"Workspace root: {workspace_label}", id="workspace", disabled=gated),
        ]

    def _refresh(self) -> None:
        """Rebuild the main menu's option list after an edit, which always
        means there is something unsaved -- see _save()'s own reset."""
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
        if choice == "sources":
            def handle(value: Optional[list]) -> None:
                if value is not None:
                    self.sources = value
                    self._refresh()
            self.push_screen(_SourcesScreen(self.sources), handle)
        elif choice == "design":
            self._edit_design()
        elif choice == "technology":
            self._edit_technology()
        elif choice == "flow":
            self._edit_flow()
        elif choice == "constraints":
            def handle(value: Optional[list]) -> None:
                if value is not None:
                    self.constraint_files = value
                    self._refresh()
            self.push_screen(_ConstraintFilesScreen(self.constraint_files), handle)
        elif choice == "project":
            self._edit_project_root()
        elif choice == "workspace":
            self._edit_workspace_root()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save(close=True)
        elif event.button.id == "quit_":
            self.exit()

    def action_save_in_place(self) -> None:
        self._save(close=False)

    def _edit_design(self) -> None:
        detected = _scan_modules(self.sources)

        def pick_name(value: Optional[str]) -> None:
            if value is None:
                return

            def set_design_name(design_name: Optional[str]) -> None:
                if design_name is not None:
                    self.design_top = value
                    self.design_name = design_name or value
                    self._refresh()
            self.push_screen(
                _TextScreen("Design name (blank = same as top)", self.design_name or value),
                set_design_name,
            )

        if detected:
            choices = [(name, name) for name in detected] + [("(enter manually)", "")]

            def handle_pick(value: Optional[str]) -> None:
                if value is None:
                    return
                if value:
                    pick_name(value)
                else:
                    self.push_screen(_TextScreen("Top module name", self.design_top or ""), pick_name)
            self.push_screen(_PickScreen("Pick the top module", choices), handle_pick)
        else:
            self.push_screen(_TextScreen("Top module name", self.design_top or ""), pick_name)

    def _edit_directory_field(self, label: str, current: Optional[str], on_set) -> None:
        """Shared browse/manual flow behind project root and workspace
        root: 'Browse filesystem' lands on _BrowseDirectoryScreen, whose
        own 'n' binding creates a real new folder (a plain mkdir, right
        away -- not deferred to Save) and expands into it, so pointing
        either field at a directory that doesn't exist yet is a single
        screen, not a trip out to a terminal first."""
        def handle_method(method: Optional[str]) -> None:
            if method == "browse":
                def handle_browse(path: Optional[str]) -> None:
                    if path is not None:
                        on_set(path)
                        self._refresh()
                self.push_screen(_BrowseDirectoryScreen(current or str(Path.home())), handle_browse)
            elif method == "manual":
                def handle_path(value: Optional[str]) -> None:
                    if value is not None:
                        on_set(_absolute(value) if value else None)
                        self._refresh()
                self.push_screen(_TextScreen(label, current or ""), handle_path)
        self.push_screen(
            _PickScreen(f"Set {label.lower()}", [
                ("Browse filesystem", "browse"),
                ("Type a path manually", "manual"),
            ]),
            handle_method,
        )

    def _edit_project_root(self) -> None:
        def on_set(value: Optional[str]) -> None:
            self.project_root = value
            if value and Path(value).is_dir():
                self._scan_project_root(Path(value))
        self._edit_directory_field("Project root", self.project_root, on_set)

    def _scan_project_root(self, root: Path) -> None:
        """Always runs once a project root is set to a directory that
        already exists -- see _ProjectScanScreen's own docstring for why
        this is never skipped, even for a directory with nothing in it
        yet."""
        scan = scan_project_tree(root)

        def handle(design: Optional[str]) -> None:
            if design:
                self._apply_design_scan(root, design)
        self.push_screen(_ProjectScanScreen(root, scan), handle)

    def _apply_design_scan(self, root: Path, design: str) -> None:
        deep = scan_design(root, design)
        self.design_name = design
        self.sources = [{"path": str(path)} for path in deep.hdl_files]
        detected = _scan_modules(self.sources)
        if detected:
            self.design_top = detected[0]
        if deep.constraint_files:
            self.constraint_files = [str(path) for path in deep.constraint_files]
        self._refresh()
        summary = (
            f"Loaded {design}: {len(deep.hdl_files)} HDL file(s), "
            f"{len(deep.constraint_files)} constraints file(s), "
            f"{deep.output_run_count} output run(s), {deep.workspace_run_count} workspace run(s) found."
        )
        if deep.missing_categories:
            summary += f" Missing inputs categories: {', '.join(deep.missing_categories)}."
        self.notify(summary)

    def _edit_workspace_root(self) -> None:
        def on_set(value: Optional[str]) -> None:
            self.workspace_root = value
        self._edit_directory_field(
            "Workspace root (optional -- defaults to project root / workspace)",
            self.workspace_root or self.project_root, on_set,
        )

    def _edit_technology(self) -> None:
        def handle_action(action: Optional[str]) -> None:
            if action == "package":
                self._pick_technology_package()
            elif action == "track_vth":
                self._pick_technology_track_vth()
            elif action == "metal_stack":
                self._pick_technology_metal_stack()
        self.push_screen(
            _PickScreen("Technology (PDK)", [
                ("Pick PDK package", "package"),
                ("Pick track / vth", "track_vth"),
                ("Pick metal stack", "metal_stack"),
            ]),
            handle_action,
        )

    def _pick_technology_package(self) -> None:
        entries = [
            _package_choice(manifest) for manifest in PackageRegistry().manifests()
            if manifest.identifier.kind == "pdk"
        ]
        if not entries:
            self.notify("No pdk/* packages found in any configured registry.", severity="warning")
            return
        choices = [(label, identifier) for label, identifier, _ in entries]
        details = {identifier: detail for _, identifier, detail in entries if detail}

        def handle(value: Optional[str]) -> None:
            if value is None:
                return

            def finish() -> None:
                if value != self.technology_package:
                    # A different package's track/vth/stack names don't
                    # carry over -- keeping a stale selection around would
                    # silently resolve against the wrong package's vocabulary.
                    self.technology_track = None
                    self.technology_vth = None
                    self.technology_metal_stack = None
                self.technology_package = value
                self._refresh()
            _maybe_install(self, value, finish)
        self.push_screen(_PickScreen("Pick a technology (PDK) package", choices, details), handle)

    def _pick_technology_track_vth(self) -> None:
        if not self.technology_package:
            self.notify("Pick a PDK package first.", severity="warning")
            return
        tracks = _technology_tracks(self.technology_package)
        if not tracks:
            self.notify(
                f"{self.technology_package} declares a flat technology (no named tracks/vths) "
                "-- nothing to pick.", severity="warning",
            )
            return
        choices = [
            (f"{track} / {vth}", f"{track}/{vth}")
            for track, track_data in sorted(tracks.items())
            for vth in sorted(track_data.get("vths", {})) if isinstance(track_data, dict)
        ]

        def handle(value: Optional[str]) -> None:
            if value is None:
                return
            track, vth = value.split("/", 1)
            if (track, vth) != (self.technology_track, self.technology_vth):
                self.technology_metal_stack = None
            self.technology_track = track
            self.technology_vth = vth
            self._refresh()
        self.push_screen(_PickScreen("Pick a track / vth", choices), handle)

    def _pick_technology_metal_stack(self) -> None:
        if not self.technology_track or not self.technology_vth:
            self.notify("Pick a track/vth first.", severity="warning")
            return
        stacks = _technology_metal_stacks(self.technology_package, self.technology_track, self.technology_vth)
        if not stacks:
            self.notify(
                f"{self.technology_track}/{self.technology_vth} declares no named metal stacks "
                "-- nothing to pick, WOLF resolves it without technology.metal_stack.",
                severity="warning",
            )
            return

        def handle(value: Optional[str]) -> None:
            if value is None:
                return
            self.technology_metal_stack = value
            self._refresh()
        self.push_screen(_PickScreen("Pick a metal stack", [(name, name) for name in stacks]), handle)

    def _edit_flow(self) -> None:
        def handle_action(action: Optional[str]) -> None:
            if action == "inspect":
                self._inspect_flow()
            elif action == "change":
                self._change_flow()
        self.push_screen(
            _PickScreen("Flow", [
                ("Inspect flow structure", "inspect"),
                ("Change flow package / backend", "change"),
            ]),
            handle_action,
        )

    def _flow_root_path(self) -> Path:
        if self.flow_package:
            manifest = PackageRegistry().get(self.flow_package)
            package = PackageStore().read(manifest)
            if package is None:
                raise ValueError(
                    f"{self.flow_package} is not installed yet "
                    "-- install it to inspect its flow structure."
                )
            return package.content_path
        return builtin_flow_root("cadence-genus")

    def _inspect_flow(self) -> None:
        try:
            root = self._flow_root_path()
        except ValueError as error:
            self.notify(str(error), severity="error")
            return
        structure = parse_flow_directory(root)
        if not structure.sequences and not structure.steps:
            self.notify(f"No create_flow/create_flow_step definitions found under {root}.", severity="warning")
            return
        self.push_screen(_FlowInspectScreen(root, structure))

    def _change_flow(self) -> None:
        entries = [
            _package_choice(manifest) for manifest in PackageRegistry().manifests()
            if manifest.identifier.kind == "flow"
        ]
        choices = [(label, identifier) for label, identifier, _ in entries]
        details = {identifier: detail for _, identifier, detail in entries if detail}
        choices.append(("(none — WOLF's own built-in flow)", ""))
        details[""] = (
            "Not your institutional Stylus flow -- runs WOLF's bundled "
            "elaborate -> syn_generic -> syn_map -> syn_opt Genus script instead."
        )

        def handle(value: Optional[str]) -> None:
            if value is None:
                return
            if value:
                def finish() -> None:
                    self.flow_package = value
                    self.backend = None
                    self._refresh()
                _maybe_install(self, value, finish)
                return
            self.flow_package = None

            def handle_backend(backend: Optional[str]) -> None:
                if backend is not None:
                    self.backend = backend
                    self._refresh()
            backend_details = {
                "cadence-flowtool": (
                    "Local Genus/Innovus execution, using WOLF's own bundled flow "
                    "above -- not your institutional Stylus flow."
                ),
                "orfs": "OpenROAD Flow Scripts, run in a container.",
            }
            self.push_screen(
                _PickScreen(
                    "Pick a backend", [(name, name) for name in backend_names()], backend_details,
                ),
                handle_backend,
            )
        self.push_screen(_PickScreen("Pick a flow package", choices, details), handle)

    def _copy_sources_into_project(self) -> None:
        """Any local-path RTL source that isn't already living under
        <project_root>/inputs/hdl/<design_name>/ gets copied there, and
        its stored path rewritten to the copy. Done at Save, not at Add
        time: project_root/design_name aren't guaranteed to exist yet
        when a source is first picked (that's the whole reason Add just
        records whatever path was picked), but both are real,
        already-resolved fields by the time Save runs. "Quit without
        saving" means no copy ever happens, same as every other change
        this wizard makes."""
        if not self.project_root or not self.design_name:
            return
        hdl_dir = Path(self.project_root) / "inputs" / "hdl" / self.design_name
        for entry in self.sources:
            path = entry.get("path")
            if not path:
                continue
            source_path = Path(path)
            try:
                source_path.resolve().relative_to(hdl_dir.resolve())
                continue  # already inside the project's own hdl dir
            except (ValueError, OSError):
                pass
            hdl_dir.mkdir(parents=True, exist_ok=True)
            destination = hdl_dir / source_path.name
            if destination.resolve() != source_path.resolve():
                shutil.copy2(source_path, destination)
            entry["path"] = str(destination.resolve())

    def _save(self, *, close: bool) -> None:
        self._copy_sources_into_project()
        document: dict = {"schema": ENVIRONMENT_SCHEMA, "name": self._name}
        design: dict = {}
        if self.design_name:
            design["name"] = self.design_name
        if self.design_top:
            design["top"] = self.design_top
        if self.sources:
            design["sources"] = self.sources
        if design:
            document["design"] = design
        if self.technology_package:
            technology: dict = {"package": self.technology_package}
            if self.technology_track:
                technology["track"] = self.technology_track
            if self.technology_vth:
                technology["vth"] = self.technology_vth
            if self.technology_metal_stack:
                technology["metal_stack"] = self.technology_metal_stack
            document["technology"] = technology
        if self.flow_package:
            document["flow"] = {"package": self.flow_package}
        elif self.backend:
            document["flow"] = {"name": "default"}
        if self.constraint_files:
            document["constraints"] = {"files": self.constraint_files}
        if self.project_root:
            document["project"] = {"root": self.project_root}
        if self.workspace_root:
            document["workspace"] = {"root": self.workspace_root}

        # Every path this wizard collects was already made absolute at pick
        # time (see _absolute()), so there is nothing left for
        # normalize_environment's relative-to-source-file resolution to do --
        # this writes the validated document directly, the same atomic
        # sibling-temp-file-then-replace pattern `wolf env set` uses, so it
        # works whether self._path is new or an existing environment (legacy
        # or declarative) being edited in place.
        self._path.mkdir(parents=True, exist_ok=True)
        target = self._path / ENVIRONMENT_FILENAME
        temporary = target.with_suffix(".yaml.tmp")
        try:
            temporary.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            load_environment(temporary, expected_name=self._name)
            temporary.replace(target)
        except Exception as error:
            self.notify(f"Could not save environment: {error}", severity="error")
            return
        finally:
            temporary.unlink(missing_ok=True)

        self.notify(f"Saved WOLF environment {self._name!r} at {self._path}")
        self._dirty = False
        self._update_subtitle()
        if close:
            self.exit()

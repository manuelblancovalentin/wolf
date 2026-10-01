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
import subprocess
from typing import Optional

import yaml
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Footer, Header, Input, OptionList, Static
from textual.widgets.option_list import Option

_RTL_SUFFIXES = (".v", ".sv", ".vhd", ".vhdl")

from wolf.backend import backend_names
from wolf.environment import ENVIRONMENT_FILENAME, ENVIRONMENT_SCHEMA, load_environment
from wolf.package.installer import PackageInstaller
from wolf.package.registry import PackageRegistry
from wolf.package.store import PackageStore
from wolf.paths import environments_dir


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


def _package_choice_label(manifest) -> str:
    if PackageStore().read(manifest) is not None:
        return f"{manifest.identifier} (installed)"
    return f"{manifest.identifier} (not installed — {_package_location_hint(manifest)})"


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
    """Browse the filesystem and collect one or more RTL file paths.

    Consistent with every other list screen here: 'a' adds (the
    highlighted file, or every RTL-looking file directly inside the
    highlighted directory), 'h' toggles hidden (dot) files and
    directories, off by default. Enter on a directory expands/collapses
    it -- the tree's own default, left untouched. Enter on a file opens
    it in $EDITOR to view it, rather than adding it -- adding is always
    an explicit 'a'. Escape finishes, returning whatever was added.
    """

    BINDINGS = [
        ("a", "add", "Add"),
        ("h", "toggle_hidden", "Hidden files"),
        ("escape", "done", "Done"),
    ]

    def __init__(self, start: str):
        super().__init__()
        self._start = start
        self._selected: list[str] = []
        self._show_hidden = False

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Browse for RTL files", id="dialog-title")
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
                if entry.is_file() and entry.suffix.lower() in _RTL_SUFFIXES:
                    resolved = str(entry.resolve())
                    if resolved not in self._selected:
                        self._selected.append(resolved)
                        added += 1
            if added:
                self.app.notify(f"Added {added} RTL file(s) from {path}")
            else:
                self.app.notify("No new RTL files in that directory.", severity="warning")
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


class _PickScreen(ModalScreen[Optional[str]]):
    """Pick one id out of a list of (label, id) choices."""

    def __init__(self, title: str, choices: list[tuple[str, str]]):
        super().__init__()
        self._title = title
        self._choices = choices

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*(Option(label, id=key) for label, key in self._choices))
            yield Static("enter to choose — esc to cancel", id="dialog-hint")

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
                registry = PackageRegistry()
                choices = [
                    (_package_choice_label(manifest), str(manifest.identifier))
                    for manifest in registry.manifests() if manifest.identifier.kind == "rtl"
                ]
                if not choices:
                    self.app.notify("No rtl/* packages found in any configured registry.", severity="warning")
                    return

                def handle_package(value: Optional[str]) -> None:
                    if not value:
                        return

                    def finish() -> None:
                        self._sources.append({"package": value})
                        self._refresh()
                    _maybe_install(self.app, value, finish)
                self.app.push_screen(_PickScreen("Pick an rtl package", choices), handle_package)
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
    """
    BINDINGS = [("q", "quit", "Quit"), ("escape", "quit", "Quit")]
    TITLE = "WOLF environment setup"

    def __init__(self, name: str):
        super().__init__()
        self._name = name
        self._path = environments_dir() / name
        self.sources: list[dict] = []
        self.design_name: Optional[str] = None
        self.design_top: Optional[str] = None
        self.technology_package: Optional[str] = None
        self.flow_package: Optional[str] = None
        self.backend: Optional[str] = None
        self.project_root: Optional[str] = None

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
            if profile.technology and profile.technology.package:
                self.technology_package = profile.technology.package
            if profile.flow and profile.flow.package:
                self.flow_package = profile.flow.package
            # A flow with no package (bundled default) also has no recorded
            # backend -- that choice is only ever used as a `wolf run
            # --backend` override, never persisted. Re-editing such an
            # environment starts flow/backend unset; pick it again if needed.
            self.project_root = profile.project_root

    def compose(self) -> ComposeResult:
        yield Header()
        yield OptionList(*self._options())
        yield Footer()

    def _options(self) -> list[Option]:
        sources_label = f"{len(self.sources)} entr{'y' if len(self.sources) == 1 else 'ies'}" \
            if self.sources else "none yet"
        design_label = " / ".join(filter(None, (self.design_name, self.design_top))) or "not set"
        technology_label = self.technology_package or "not set"
        flow_label = self.flow_package or (f"bundled default, backend={self.backend}" if self.backend else "not set")
        project_label = self.project_root or "not set"
        return [
            Option(f"RTL sources: {sources_label}", id="sources"),
            Option(f"Design name / top: {design_label}", id="design"),
            Option(f"Technology (PDK): {technology_label}", id="technology"),
            Option(f"Flow / backend: {flow_label}", id="flow"),
            Option(f"Project root: {project_label}", id="project"),
            Option("Save", id="save"),
            Option("Quit without saving", id="quit_"),
        ]

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)

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
        elif choice == "project":
            def handle(value: Optional[str]) -> None:
                if value is not None:
                    self.project_root = _absolute(value) if value else None
                    self._refresh()
            self.push_screen(_TextScreen("Project root", self.project_root or ""), handle)
        elif choice == "save":
            self._save()
        elif choice == "quit_":
            self.exit()

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

    def _edit_technology(self) -> None:
        registry = PackageRegistry()
        choices = [
            (_package_choice_label(manifest), str(manifest.identifier))
            for manifest in registry.manifests() if manifest.identifier.kind == "pdk"
        ]
        if not choices:
            self.notify("No pdk/* packages found in any configured registry.", severity="warning")
            return

        def handle(value: Optional[str]) -> None:
            if value is None:
                return

            def finish() -> None:
                self.technology_package = value
                self._refresh()
            _maybe_install(self, value, finish)
        self.push_screen(_PickScreen("Pick a technology (PDK) package", choices), handle)

    def _edit_flow(self) -> None:
        registry = PackageRegistry()
        choices = [
            (_package_choice_label(manifest), str(manifest.identifier))
            for manifest in registry.manifests() if manifest.identifier.kind == "flow"
        ]
        choices.append(("(none — use WOLF's bundled default flow)", ""))

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
            self.push_screen(
                _PickScreen("Pick a backend", [(name, name) for name in backend_names()]),
                handle_backend,
            )
        self.push_screen(_PickScreen("Pick a flow package", choices), handle)

    def _save(self) -> None:
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
            document["technology"] = {"package": self.technology_package}
        if self.flow_package:
            document["flow"] = {"package": self.flow_package}
        elif self.backend:
            document["flow"] = {"name": "default"}
        if self.project_root:
            document["project"] = {"root": self.project_root}

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
        self.exit()

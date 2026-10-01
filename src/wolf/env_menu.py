"""A real full-screen `wolf env menu`, a step-by-step environment builder.

Kept separate from `wolf.commands.env` so Textual is only imported when this
specific subcommand actually runs, not on every WOLF invocation (same reason
`wolf.config_menu` is its own module).

This first slice only creates a new declarative-v1 environment -- it does
not yet edit an existing one. The order of steps mirrors the dependency
order discussed for environment setup: RTL sources first (nothing else can
be meaningfully picked before there is RTL), then design name/top (offered
from module names found in those sources), then the technology (PDK) and
flow/backend, then the project root.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import tempfile
from typing import Optional

import yaml
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, OptionList, Static
from textual.widgets.option_list import Option

from wolf.backend import backend_names
from wolf.environment import ENVIRONMENT_FILENAME, ENVIRONMENT_SCHEMA, load_environment, normalize_environment
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
    """Add/remove design.sources entries: installed rtl packages or local paths."""

    def __init__(self, sources: list[dict]):
        super().__init__()
        self._sources = list(sources)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("RTL sources", id="dialog-title")
            yield OptionList(*self._options())
            yield Static(
                "select an entry to remove it — esc cancels, keeping earlier changes",
                id="dialog-hint",
            )

    def _options(self) -> list[Option]:
        options = [
            Option(f"− remove: {_source_label(entry)}", id=f"remove:{index}")
            for index, entry in enumerate(self._sources)
        ]
        options.append(Option("+ add local file path", id="add_path"))
        options.append(Option("+ add installed rtl package", id="add_package"))
        options.append(Option("Done", id="done"))
        return options

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        choice = event.option_id
        assert choice is not None
        if choice == "done":
            self.dismiss(self._sources)
        elif choice == "add_path":
            def handle_path(value: Optional[str]) -> None:
                if value:
                    self._sources.append({"path": _absolute(value)})
                    self._refresh()
            self.app.push_screen(_TextScreen("Path to an RTL file"), handle_path)
        elif choice == "add_package":
            registry = PackageRegistry()
            store = PackageStore()
            choices = []
            for manifest in registry.manifests():
                if manifest.identifier.kind != "rtl":
                    continue
                status = store.status(manifest)
                choices.append((f"{manifest.identifier} ({status})", str(manifest.identifier)))
            if not choices:
                self.app.notify("No rtl/* packages found in any configured registry.", severity="warning")
                return

            def handle_package(value: Optional[str]) -> None:
                if value:
                    self._sources.append({"package": value})
                    self._refresh()
            self.app.push_screen(_PickScreen("Pick an rtl package", choices), handle_package)
        elif choice.startswith("remove:"):
            index = int(choice.split(":", 1)[1])
            del self._sources[index]
            self._refresh()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(self._sources)


class EnvWizardApp(App[None]):
    """`wolf env menu NAME` -- builds a new declarative-v1 environment."""

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
        self.sources: list[dict] = []
        self.design_name: Optional[str] = None
        self.design_top: Optional[str] = None
        self.technology_package: Optional[str] = None
        self.flow_package: Optional[str] = None
        self.backend: Optional[str] = None
        self.project_root: Optional[str] = None

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
            Option("Save and create environment", id="save"),
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
        store = PackageStore()
        choices = []
        for manifest in registry.manifests():
            if manifest.identifier.kind != "pdk":
                continue
            status = store.status(manifest)
            choices.append((f"{manifest.identifier} ({status})", str(manifest.identifier)))
        if not choices:
            self.notify("No pdk/* packages found in any configured registry.", severity="warning")
            return

        def handle(value: Optional[str]) -> None:
            if value is not None:
                self.technology_package = value
                self._refresh()
        self.push_screen(_PickScreen("Pick a technology (PDK) package", choices), handle)

    def _edit_flow(self) -> None:
        registry = PackageRegistry()
        store = PackageStore()
        choices = []
        for manifest in registry.manifests():
            if manifest.identifier.kind != "flow":
                continue
            status = store.status(manifest)
            choices.append((f"{manifest.identifier} ({status})", str(manifest.identifier)))
        choices.append(("(none — use WOLF's bundled default flow)", ""))

        def handle(value: Optional[str]) -> None:
            if value is None:
                return
            if value:
                self.flow_package = value
                self.backend = None
                self._refresh()
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

        destination = environments_dir() / self._name
        if destination.exists() or destination.is_symlink():
            self.notify(f"WOLF environment {self._name!r} already exists.", severity="error")
            return

        temporary_file = Path(tempfile.mkstemp(prefix=f".{self._name}-", suffix=".yaml")[1])
        try:
            temporary_file.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            load_environment(temporary_file, expected_name=self._name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{self._name}-", dir=destination.parent))
            try:
                normalize_environment(temporary_file, staging / ENVIRONMENT_FILENAME, name=self._name)
                staging.replace(destination)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
        except Exception as error:
            self.notify(f"Could not create environment: {error}", severity="error")
            return
        finally:
            temporary_file.unlink(missing_ok=True)

        self.notify(f"Created WOLF environment {self._name!r} at {destination}")
        self.exit()

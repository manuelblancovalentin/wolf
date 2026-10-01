"""A real full-screen `wolf config menu`, built with Textual.

Kept separate from `wolf.commands.config` so Textual is only imported when
this specific subcommand actually runs, not on every WOLF invocation.
"""

from __future__ import annotations

from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, OptionList, RadioButton, RadioSet, Static
from textual.widgets.option_list import Option

from wolf.commands.config import _ENUM_CHOICES, _UNSET, _display, _parse_value
from wolf.config import CONFIG_KEYS, ConfigStore
from wolf.registry import RegistryManager

_REGISTRIES_OPTION = "__registries__"


class _EditEnumScreen(ModalScreen[Optional[str]]):
    """Pick one of a key's fixed valid values, or leave it unset."""

    def __init__(self, key: str, choices: tuple[str, ...], current: Optional[str]):
        super().__init__()
        self._key = key
        self._choices = (*choices, _UNSET)
        self._current = current if current is not None else _UNSET

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._key, id="dialog-title")
            yield RadioSet(
                *(RadioButton(choice, value=choice == self._current) for choice in self._choices),
            )
            yield Static("enter to choose - esc to cancel", id="dialog-hint")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        self.dismiss(str(event.pressed.label))

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class _EditTextScreen(ModalScreen[Optional[str]]):
    """Free-text edit for a path-like key; empty submits as unset."""

    def __init__(self, key: str, current: str):
        super().__init__()
        self._key = key
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._key, id="dialog-title")
            yield Input(value=self._current, id="value")
            yield Static("enter to submit (blank = unset) - esc to cancel", id="dialog-hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value or _UNSET)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class _PromptScreen(ModalScreen[Optional[str]]):
    """Free-text prompt, used for a registry's name or source path."""

    def __init__(self, title: str, initial: str = ""):
        super().__init__()
        self._title = title
        self._initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield Input(value=self._initial, id="value")
            yield Static("enter to submit - esc to cancel", id="dialog-hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class _ChoiceScreen(ModalScreen[Optional[str]]):
    """Pick one id out of a list of (label, id) choices."""

    def __init__(self, title: str, choices: list[tuple[str, str]]):
        super().__init__()
        self._title = title
        self._choices = choices

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield OptionList(*(Option(label, id=key) for label, key in self._choices))
            yield Static("enter to choose - esc to cancel", id="dialog-hint")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option_id)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class _RegistriesScreen(ModalScreen[None]):
    """List, add, and remove configured package registries.

    Consistent with every other list screen here: 'a' adds, 'd' deletes
    the highlighted registry, enter shows its details (a registry has no
    single file to open). Escape closes.
    """

    BINDINGS = [
        ("a", "add", "Add"),
        ("d", "delete", "Delete"),
        ("escape", "done", "Done"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Package registries", id="dialog-title")
            yield OptionList(*self._options())
            yield Static("enter: view details — a: add — d: delete highlighted — esc: done", id="dialog-hint")

    def _options(self) -> list[Option]:
        specs = RegistryManager().specs()
        if not specs:
            return [Option("(none yet — press 'a' to add)", id="__empty__", disabled=True)]
        return [Option(f"{spec.name} ({spec.type}, priority {spec.priority})", id=spec.name) for spec in specs]

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id in (None, "__empty__"):
            return
        manager = RegistryManager()
        spec = manager.get(event.option_id)
        status = manager.status(spec)
        self.app.notify(
            f"{spec.name}: type={spec.type} source={spec.source} "
            f"priority={spec.priority} status={status}",
            timeout=8,
        )

    def action_add(self) -> None:
        self._add_registry()

    def action_delete(self) -> None:
        option_list = self.query_one(OptionList)
        index = option_list.highlighted
        if index is None:
            return
        option = option_list.get_option_at_index(index)
        if option.id is None or option.id == "__empty__":
            return
        try:
            RegistryManager().remove(option.id)
        except ValueError as error:
            self.app.notify(str(error), severity="error")
        self._refresh()

    def action_done(self) -> None:
        self.dismiss(None)

    def _add_registry(self) -> None:
        def got_name(name: Optional[str]) -> None:
            if not name:
                return

            def got_source(source: Optional[str]) -> None:
                if not source:
                    return

                def got_type(kind: Optional[str]) -> None:
                    if kind is None:
                        return
                    try:
                        RegistryManager().add(name, source, kind or None)
                    except ValueError as error:
                        self.app.notify(str(error), severity="error")
                    self._refresh()
                self.app.push_screen(
                    _ChoiceScreen("Registry type", [
                        ("(auto-detect)", ""), ("git", "git"), ("local", "local"),
                    ]),
                    got_type,
                )
            self.app.push_screen(_PromptScreen("Registry source (path or git URL)"), got_source)
        self.app.push_screen(_PromptScreen("Registry name"), got_name)


class ConfigMenuApp(App[None]):
    """`wolf config menu` -- an arrow-key picker over every CONFIG_KEYS entry."""

    CSS = """
    #dialog {
        width: 70; height: auto; border: round #ad4ce5; padding: 1 2;
        background: $surface;
    }
    #dialog-title { color: #ad4ce5; text-style: bold; margin-bottom: 1; }
    #dialog-hint { color: $text-muted; margin-top: 1; }
    Screen { align: center middle; }
    OptionList { border: round #ad4ce5; }
    """
    BINDINGS = [("q", "quit", "Quit"), ("escape", "quit", "Quit")]
    TITLE = "WOLF configuration"

    def __init__(self):
        super().__init__()
        self._store = ConfigStore()

    def compose(self) -> ComposeResult:
        yield Header()
        yield OptionList(*self._options())
        yield Footer()

    def _options(self) -> list[Option]:
        document = self._store.load(effective=True)
        options = []
        for key in CONFIG_KEYS:
            section, field = key.split(".", 1)
            value = document[section].get(field)
            options.append(Option(f"{key} = {_display(value)}", id=key))
        registries = len(RegistryManager().specs())
        options.append(Option(f"Registries: {registries} configured", id=_REGISTRIES_OPTION))
        return options

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        key = event.option_id
        assert key is not None
        if key == _REGISTRIES_OPTION:
            self.push_screen(_RegistriesScreen(), lambda _: self._refresh())
            return
        document = self._store.load(effective=True)
        section, field = key.split(".", 1)
        current = document[section].get(field)

        def handle(answer: Optional[str]) -> None:
            if answer is None:
                return
            if answer == _UNSET:
                self._store.unset(key)
            else:
                self._store.set(key, _parse_value(key, answer))
            self._refresh()

        if key in _ENUM_CHOICES:
            self.push_screen(
                _EditEnumScreen(key, _ENUM_CHOICES[key], _display(current) if current is not None else None),
                handle,
            )
        else:
            self.push_screen(_EditTextScreen(key, str(current) if current is not None else ""), handle)

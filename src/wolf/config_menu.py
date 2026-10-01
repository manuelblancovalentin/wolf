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
        return options

    def _refresh(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.clear_options()
        for option in self._options():
            option_list.add_option(option)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        key = event.option_id
        assert key is not None
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

"""Machine-readable completion candidates for WOLF shell integrations."""

from __future__ import annotations

import argparse
from collections.abc import Iterable

from wolf.backend import backend_names
from wolf.commands.env import _environment_names


_DYNAMIC_POSITIONALS = {
    ("activate",): _environment_names,
    ("info",): _environment_names,
    ("env", "remove"): _environment_names,
    ("env", "set"): _environment_names,
    ("backend", "info"): backend_names,
}


def _subcommands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return {
                name: child
                for name, child in action.choices.items()
                if not name.startswith("_")
            }
    return {}


def _option_candidates(parser: argparse.ArgumentParser) -> list[str]:
    return sorted(
        option
        for action in parser._actions
        for option in action.option_strings
    )


def _selected_parser(
    parser: argparse.ArgumentParser, completed: list[str]
) -> tuple[argparse.ArgumentParser, tuple[str, ...], list[str]]:
    path: list[str] = []
    remaining = completed[:]
    current = parser
    while remaining:
        choices = _subcommands(current)
        token = remaining[0]
        if token not in choices:
            break
        path.append(token)
        current = choices[token]
        remaining.pop(0)
    return current, tuple(path), remaining


def _positional_count(parser: argparse.ArgumentParser, words: list[str]) -> int:
    option_actions = {
        option: action
        for action in parser._actions
        for option in action.option_strings
    }
    count = 0
    index = 0
    while index < len(words):
        word = words[index]
        option = word.split("=", 1)[0]
        action = option_actions.get(option)
        if action is not None:
            if "=" not in word and action.nargs not in (0, "?"):
                index += 1
        elif not word.startswith("-"):
            count += 1
        index += 1
    return count


def _value_candidates(path: tuple[str, ...], option: str) -> Iterable[str]:
    if path == ("run",) and option == "--environment":
        return _environment_names()
    if path == ("run",) and option == "--backend":
        return backend_names()
    return ()


def candidates(parser: argparse.ArgumentParser, words: list[str]) -> list[str]:
    """Return completion candidates for words following the public command name."""
    prefix = words[-1] if words else ""
    completed = words[:-1] if words else []
    current, path, remaining = _selected_parser(parser, completed)

    if completed:
        previous = completed[-1]
        values = _value_candidates(path, previous)
        if values:
            return sorted(value for value in values if value.startswith(prefix))

    for option in ("--environment", "--backend"):
        assignment = f"{option}="
        if prefix.startswith(assignment):
            value_prefix = prefix[len(assignment):]
            return [
                assignment + value
                for value in sorted(_value_candidates(path, option))
                if value.startswith(value_prefix)
            ]

    if prefix.startswith("-"):
        return [value for value in _option_candidates(current) if value.startswith(prefix)]

    subcommands = _subcommands(current)
    if subcommands and not remaining:
        choices = list(subcommands)
        if not path:
            choices.extend(_option_candidates(current))
        return sorted(name for name in choices if name.startswith(prefix))

    provider = _DYNAMIC_POSITIONALS.get(path)
    if provider is not None and _positional_count(current, remaining) == 0:
        return sorted(name for name in provider() if name.startswith(prefix))

    if not prefix and path == ("run",):
        return _option_candidates(current)
    return []


def command_complete(args: argparse.Namespace) -> int:
    words = args.words
    if words and words[0] == "--":
        words = words[1:]
    parser = args.parser_factory()
    for value in candidates(parser, words):
        if "\n" not in value and "\r" not in value:
            print(value)
    return 0


def register(
    subparsers: argparse._SubParsersAction,
    parser_factory,
) -> None:
    parser = subparsers.add_parser("_complete", help=argparse.SUPPRESS)
    parser.add_argument("words", nargs=argparse.REMAINDER)
    parser.set_defaults(
        handler=command_complete,
        parser_factory=parser_factory,
        suppress_ui=True,
    )

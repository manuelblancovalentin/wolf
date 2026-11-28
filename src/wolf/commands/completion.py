"""Machine-readable completion candidates for WOLF shell integrations."""

from __future__ import annotations

import argparse
from collections.abc import Iterable

from wolf.backend import backend_names
from wolf.commands.env import _environment_names
from wolf.commands.pdk import _menu_candidates as _pdk_menu_candidates
from wolf.commands.pdk import _pdk_names
from wolf.package.registry import PackageRegistry
from wolf.config import CONFIG_KEYS
from wolf.registry import RegistryManager


def _registry_names():
    return ("builtin",) + tuple(spec.name for spec in RegistryManager().specs())


_DYNAMIC_POSITIONALS = {
    ("activate",): _environment_names,
    ("info",): _environment_names,
    ("env", "remove"): _environment_names,
    ("env", "set"): _environment_names,
    ("env", "clone"): _environment_names,
    ("env", "menu"): _environment_names,
    ("pdk", "menu"): _pdk_menu_candidates,
    ("pdk", "info"): _pdk_names,
    ("backend", "info"): backend_names,
    ("package", "info"): lambda: PackageRegistry().completion_identifiers(),
    ("install",): lambda: PackageRegistry().completion_identifiers(),
    ("config", "get"): lambda: CONFIG_KEYS,
    ("config", "set"): lambda: CONFIG_KEYS,
    ("config", "unset"): lambda: CONFIG_KEYS,
    ("registry", "info"): _registry_names,
    ("registry", "sync"): _registry_names,
    ("registry", "remove"): lambda: tuple(
        spec.name for spec in RegistryManager().specs()
    ),
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


def _typed_environment_name(completed: list[str]) -> Optional[str]:
    """`--environment NAME` or `--environment=NAME`, if already typed
    among `completed` -- the same already-typed words `candidates()`
    has on hand, just scanned for this one option instead of the
    option currently being completed."""
    for index, word in enumerate(completed):
        if word == "--environment" and index + 1 < len(completed):
            return completed[index + 1]
        if word.startswith("--environment="):
            return word.split("=", 1)[1]
    return None


def _run_stage_names(completed: list[str] = ()) -> tuple[str, ...]:
    """The real stage names -from/-to accept. With a --environment
    already typed and resolvable to a cadence-flowtool environment,
    this is that environment's own derived flow vocabulary (see
    derive_stage_order) -- a project flow's own extra stages included.
    Falls back to WOLF's bundled STAGE_ORDER with no --environment yet,
    a non-cadence-flowtool one, or any failure resolving it at all --
    completion must never hang or crash on a half-typed command line."""
    from wolf.backend.cadence_genus import STAGE_ORDER

    environment_name = _typed_environment_name(list(completed))
    if not environment_name:
        return STAGE_ORDER
    try:
        from wolf.backend.cadence_genus import _context_stage_order
        from wolf.commands.env import _environment_path
        from wolf.environment import (
            environment_manifest, load_environment, resolve_declarative_environment,
        )
        from wolf.paths import state_root

        environment_directory = _environment_path(environment_name)
        manifest = environment_manifest(environment_directory)
        if not manifest:
            return STAGE_ORDER
        context = resolve_declarative_environment(
            load_environment(manifest, expected_name=environment_name),
            state_root=state_root(), environment_directory=environment_directory,
        )
        if context.backend != "cadence-flowtool":
            return STAGE_ORDER
        derived = _context_stage_order(context)
        return tuple(stage.selector() for stage in derived) or STAGE_ORDER
    except Exception:
        return STAGE_ORDER


def _value_candidates(path: tuple[str, ...], option: str, completed: list[str] = ()) -> Iterable[str]:
    if path == ("run",) and option == "--environment":
        return _environment_names()
    if path == ("run",) and option == "--backend":
        return backend_names()
    if path == ("run",) and option in ("-from", "-to"):
        return _run_stage_names(completed)
    if path == ("status",) and option == "--environment":
        return _environment_names()
    return ()


def candidates(parser: argparse.ArgumentParser, words: list[str]) -> list[str]:
    """Return completion candidates for words following the public command name."""
    prefix = words[-1] if words else ""
    completed = words[:-1] if words else []
    current, path, remaining = _selected_parser(parser, completed)

    if completed:
        previous = completed[-1]
        values = _value_candidates(path, previous, completed[:-1])
        if values:
            return sorted(value for value in values if value.startswith(prefix))

    for option in ("--environment", "--backend"):
        assignment = f"{option}="
        if prefix.startswith(assignment):
            value_prefix = prefix[len(assignment):]
            return [
                assignment + value
                for value in sorted(_value_candidates(path, option, completed))
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

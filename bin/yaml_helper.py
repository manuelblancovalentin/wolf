#!/usr/bin/env python3

"""Small YAML query helper for WOLF's legacy shell implementation."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path
import sys
from typing import Any, List, Optional

import yaml


def load_yaml(path: str) -> Any:
    with Path(path).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def resolve_path(document: Any, path: Optional[str]) -> Any:
    value = document
    if not path:
        return value

    for component in path.split("."):
        if not isinstance(value, Mapping) or component not in value:
            raise KeyError(path)
        value = value[component]
    return value


def scalar_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (Mapping, Sequence)) and not isinstance(value, str):
        return yaml.safe_dump(value, default_flow_style=True).strip()
    return str(value)


def command_keys(args: argparse.Namespace) -> None:
    value = resolve_path(load_yaml(args.file), args.path)
    if not isinstance(value, Mapping):
        raise TypeError(f"YAML path {args.path or '<root>'!r} is not a mapping")
    for key in value:
        print(key)


def command_get_value(args: argparse.Namespace) -> None:
    print(scalar_text(resolve_path(load_yaml(args.file), args.path)))


def command_get_values(args: argparse.Namespace) -> None:
    value = resolve_path(load_yaml(args.file), args.path)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            print(scalar_text(item))
        return
    print(scalar_text(value))


def recursive_stage_search(
    document: Any,
    prefix: str = "",
    selected_flows: Optional[List[str]] = None,
) -> List[str]:
    stages: List[str] = []
    if isinstance(document, Mapping):
        for child_key, value in document.items():
            if child_key == "steps":
                stages.extend(recursive_stage_search(value, prefix))
            elif prefix:
                child_path = f"{prefix}.{child_key}"
                stages.append(child_path)
                stages.extend(recursive_stage_search(value, child_path))
            elif not selected_flows or any(
                str(child_key).startswith(flow) for flow in selected_flows
            ):
                child_path = str(child_key)
                stages.append(child_path)
                stages.extend(recursive_stage_search(value, child_path))
    elif isinstance(document, Sequence) and not isinstance(document, (str, bytes)):
        for value in document:
            stages.extend(recursive_stage_search(value, prefix))
    return stages


def command_stages(args: argparse.Namespace) -> None:
    document = load_yaml(args.file)
    if not isinstance(document, Mapping) or "flows" not in document:
        raise KeyError("flows")
    for stage in recursive_stage_search(document["flows"], selected_flows=args.flow):
        print(stage)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    keys_parser = subparsers.add_parser("keys", help="print mapping keys")
    keys_parser.add_argument("file")
    keys_parser.add_argument("path", nargs="?")
    keys_parser.set_defaults(handler=command_keys)

    value_parser = subparsers.add_parser("get-value", help="print one value")
    value_parser.add_argument("file")
    value_parser.add_argument("path")
    value_parser.set_defaults(handler=command_get_value)

    values_parser = subparsers.add_parser("get-values", help="print sequence values")
    values_parser.add_argument("file")
    values_parser.add_argument("path")
    values_parser.set_defaults(handler=command_get_values)

    stages_parser = subparsers.add_parser("stages", help="print Flowtool stage names")
    stages_parser.add_argument("file")
    stages_parser.add_argument("flow", nargs="*")
    stages_parser.set_defaults(handler=command_stages)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except (KeyError, OSError, TypeError, yaml.YAMLError) as error:
        print(f"wolf YAML error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

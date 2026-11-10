"""Print WOLF's canonical-concepts catalog (wolf.catalog/v1)."""

from __future__ import annotations

import argparse
import json

from wolf.catalog import build_catalog


def command_catalog(args: argparse.Namespace) -> int:
    data = build_catalog()
    if args.json:
        print(json.dumps(data, sort_keys=True, indent=2))
        return 0
    from wolf import ui

    ui.key_value("Schema", data["schema"])
    ui.key_value("WOLF version", data["wolf_version"])
    ui.key_value("Variables", str(len(data["variables"])))
    ui.key_value("Processes", str(len(data["processes"])))
    ui.key_value("Flows", str(len(data["flows"])))
    ui.key_value("Commands", str(len(data["commands"])))
    ui.info("Use --json for the machine-readable catalog.")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "catalog", help="print WOLF's canonical-concepts catalog"
    )
    parser.add_argument("--json", action="store_true", help="emit wolf.catalog/v1 JSON")
    parser.set_defaults(
        handler=command_catalog,
        ui_kind="wolf",
        ui_section="Catalog",
    )

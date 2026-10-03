"""PDK registry manifest commands."""

from __future__ import annotations

import argparse


def command_menu(args: argparse.Namespace) -> int:
    from wolf.pdk_menu import open_pdk_menu

    open_pdk_menu(args.name)
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("pdk", help="manage PDK registry manifests")
    commands = parser.add_subparsers(dest="pdk_command", required=True)

    menu_parser = commands.add_parser(
        "menu", help="interactively create or edit a pdk/NAME registry manifest",
    )
    menu_parser.add_argument("name", help="the pdk package name, e.g. tsmc65 (pdk/tsmc65)")
    menu_parser.set_defaults(handler=command_menu, suppress_ui=True)

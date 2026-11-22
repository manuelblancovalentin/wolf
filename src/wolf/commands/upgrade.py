"""Check for, and optionally install, a newer `wolf` release."""

from __future__ import annotations

import argparse

from wolf import ui
from wolf.upgrade import UpgradeError, check_latest, download_and_install


def command_upgrade(args: argparse.Namespace) -> int:
    try:
        installed, latest, is_newer = check_latest()
    except UpgradeError as error:
        ui.error(str(error))
        return 1
    if not is_newer:
        ui.success(f"wolf {installed} is already the latest release ({latest}).")
        return 0
    ui.info(f"A newer release is available: {installed} -> {latest}.")
    if args.check:
        return 0
    if not ui.confirm(f"Install wolf {latest} now?", assume_yes=args.yes):
        ui.info("Upgrade cancelled.")
        return 0
    try:
        installed_version = download_and_install()
    except UpgradeError as error:
        ui.error(str(error))
        return 1
    ui.success(f"Installed wolf {installed_version}. Open a new shell (or re-activate) to pick it up.")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("upgrade", help="check for and install a newer wolf release")
    parser.add_argument("--check", action="store_true", help="only report whether a newer release exists")
    parser.add_argument("-y", "--yes", action="store_true", help="do not prompt")
    parser.set_defaults(handler=command_upgrade, ui_kind="wolf", ui_section="Upgrade")

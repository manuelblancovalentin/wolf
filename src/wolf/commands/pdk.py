"""PDK registry manifest commands."""

from __future__ import annotations

import argparse


def _menu_candidates() -> tuple[str, ...]:
    """Completion candidates for `wolf pdk menu`: every pdk/* package name,
    plus every track and track.vth declared in it (tsmc65, tsmc65.9T,
    tsmc65.9T.lvt, ...) -- see wolf.pdk_menu.open_pdk_menu's own dotted-name
    handling. Prefix-filtering (done by the completion protocol itself)
    narrows this full set down to whatever the user has typed so far.
    """
    from wolf.package.registry import PackageRegistry

    names: list[str] = []
    for manifest in PackageRegistry().manifests():
        if manifest.identifier.kind != "pdk":
            continue
        name = manifest.identifier.name
        names.append(name)
        technology = manifest.metadata.get("technology", {})
        tracks = technology.get("tracks", {}) if isinstance(technology, dict) else {}
        if not isinstance(tracks, dict):
            continue
        for track, track_data in tracks.items():
            names.append(f"{name}.{track}")
            vths = track_data.get("vths", {}) if isinstance(track_data, dict) else {}
            if isinstance(vths, dict):
                names.extend(f"{name}.{track}.{vth}" for vth in vths)
    return tuple(names)


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
    menu_parser.add_argument(
        "name", nargs="?",
        help="pdk package name, optionally dotted into a track/vth (tsmc65, tsmc65.9T, "
             "tsmc65.9T.lvt); omit to pick from existing packages or create one",
    )
    menu_parser.set_defaults(handler=command_menu, suppress_ui=True)

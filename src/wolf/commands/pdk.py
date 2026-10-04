"""PDK registry manifest commands."""

from __future__ import annotations

import argparse

from wolf import ui


def _pdk_manifests():
    from wolf.package.registry import PackageRegistry

    return [
        manifest for manifest in PackageRegistry().manifests()
        if manifest.identifier.kind == "pdk"
    ]


def _variant_summary(technology: dict) -> str:
    tracks = technology.get("tracks") if isinstance(technology, dict) else None
    if isinstance(tracks, dict) and tracks:
        combos = sum(
            len(data.get("vths", {})) if isinstance(data, dict) else 0
            for data in tracks.values()
        )
        return f"{len(tracks)} track(s), {combos} track/vth combo(s)"
    timing = technology.get("timing") if isinstance(technology, dict) else None
    corners = timing.get("corners") if isinstance(timing, dict) else None
    if isinstance(corners, dict) and corners:
        return f"flat, {len(corners)} corner(s)"
    return "flat, 1 corner"


def command_list(_args: argparse.Namespace) -> int:
    from wolf.package.store import PackageStore

    manifests = _pdk_manifests()
    if not manifests:
        ui.info("No pdk/* packages found in any configured registry.")
        return 0
    store = PackageStore()
    ui.key_value("NAME", "REVISION      STATUS       REGISTRY      VARIANTS")
    for manifest in manifests:
        technology = manifest.metadata.get("technology", {})
        variants = _variant_summary(technology if isinstance(technology, dict) else {})
        ui.key_value(
            manifest.identifier.name,
            f"{manifest.revision[:12]:<13} {store.status(manifest):<12} "
            f"{manifest.registry_name:<13} {variants}",
        )
    return 0


_STACK_FIELDS = ("lef", "gds", "qrc_techfiles")


def _vth_stacks(vth_data: dict) -> set:
    stacks: set = set()
    for key in _STACK_FIELDS:
        value = vth_data.get(key)
        if isinstance(value, dict):
            stacks.update(value)
    return stacks


def _vth_stack_fields(vth_data: dict) -> dict:
    """Which stack-keyed fields (lef/gds/qrc_techfiles) each named metal
    stack actually has files for, on one vth -- a stack can be declared
    with, say, lef but no gds yet, mid-edit."""
    fields: dict = {}
    for key in _STACK_FIELDS:
        value = vth_data.get(key)
        if isinstance(value, dict):
            for stack, files in value.items():
                if files:
                    fields.setdefault(stack, set()).add(key)
    return fields


def _tracked_summary(tracks: dict) -> dict:
    """Collect the same shape of facts your README's 'Table of features'
    reports, by walking the manifest -- tracks, vths per track, every
    corner name and library format seen, every metal stack declared, and
    which track/vth combos actually populate each stack and with what
    (lef/gds/qrc_techfiles) -- the same "where is this stack really used"
    view wolf pdk menu's own clone flow needs you to already know."""
    vths_by_track: dict = {}
    all_corners: dict = {}
    all_formats: set = set()
    all_stacks: set = set()
    stack_usage: dict = {}
    corner_counts = 0
    for track, track_data in tracks.items():
        vths = track_data.get("vths", {}) if isinstance(track_data, dict) else {}
        vths_by_track[track] = sorted(vths)
        for vth, vth_data in vths.items():
            if not isinstance(vth_data, dict):
                continue
            all_stacks.update(_vth_stacks(vth_data))
            for stack, fields in _vth_stack_fields(vth_data).items():
                stack_usage.setdefault(stack, []).append(f"{track}/{vth} ({'+'.join(sorted(fields))})")
            corners = vth_data.get("timing", {}).get("corners", {})
            if isinstance(corners, dict):
                corner_counts += len(corners)
                for name, data in corners.items():
                    all_corners[name] = True
                    if isinstance(data, dict):
                        all_formats.add(data.get("format", "liberty"))
    return {
        "vths_by_track": vths_by_track,
        "corner_names": sorted(all_corners),
        "corner_count": corner_counts,
        "formats": sorted(all_formats),
        "stacks": sorted(all_stacks),
        "stack_usage": stack_usage,
    }


def command_info(args: argparse.Namespace) -> int:
    from wolf.package.registry import PackageRegistry
    from wolf.package.store import PackageStore

    manifest = PackageRegistry().get(f"pdk/{args.name}")
    store = PackageStore()
    ui.key_value("Package", manifest.identifier)
    ui.key_value("Description", manifest.description)
    ui.key_value("Source type", manifest.source.type)
    if manifest.source.type == "local-path":
        ui.key_value("Host-local root", manifest.source.root)
    else:
        ui.key_value("Upstream", manifest.source.url)
    ui.key_value("Revision", manifest.revision)
    ui.key_value("Registry", f"{manifest.registry_name} ({manifest.registry_type})")
    ui.key_value("Status", store.status(manifest))
    if manifest.license:
        ui.key_value("License", manifest.license.get("spdx") or manifest.license.get("name", ""))
    if manifest.author:
        ui.key_value("Author", manifest.author)
    if manifest.created:
        ui.key_value("Created", manifest.created)
    if manifest.last_modified:
        ui.key_value("Last modified", manifest.last_modified)

    technology = manifest.metadata.get("technology", {})
    technology = technology if isinstance(technology, dict) else {}
    tracks = technology.get("tracks")
    if isinstance(tracks, dict) and tracks:
        summary = _tracked_summary(tracks)
        ui.key_value("Tracks", ", ".join(sorted(tracks)) or "none")
        for track in sorted(tracks):
            vths = summary["vths_by_track"].get(track, [])
            ui.key_value(f"  {track} vths", ", ".join(vths) or "none")
        ui.key_value(
            "Corners",
            f"{summary['corner_count']} declared across all track/vth combos "
            f"({', '.join(summary['corner_names']) or 'none'})",
        )
        ui.key_value("Library formats", ", ".join(summary["formats"]) or "liberty (default)")
        ui.key_value("Metal stacks", ", ".join(summary["stacks"]) or "none declared (flat lef/gds)")
        for stack in summary["stacks"]:
            ui.key_value(f"  {stack}", ", ".join(summary["stack_usage"].get(stack, [])) or "none")
    else:
        timing = technology.get("timing", {})
        corners = timing.get("corners", {}) if isinstance(timing, dict) else {}
        if corners:
            ui.key_value("Corners", ", ".join(corners))
        else:
            ui.key_value("Corner", timing.get("corner", "typical") if isinstance(timing, dict) else "typical")
    generic = technology.get("generic", {})
    if isinstance(generic, dict) and generic:
        ui.key_value("Generic fields", ", ".join(generic))
    dont_use = technology.get("synthesis", {}).get("dont_use", []) \
        if isinstance(technology.get("synthesis"), dict) else []
    if dont_use:
        ui.key_value("Dont_use cells", f"{len(dont_use)} pattern(s)")
    return 0


def _pdk_names() -> tuple[str, ...]:
    """Completion candidates for `wolf pdk info`: just the bare package names."""
    return tuple(manifest.identifier.name for manifest in _pdk_manifests())


def _menu_candidates() -> tuple[str, ...]:
    """Completion candidates for `wolf pdk menu`: every pdk/* package name,
    plus every track and track.vth declared in it (tsmc65, tsmc65.9T,
    tsmc65.9T.lvt, ...) -- see wolf.pdk_menu.open_pdk_menu's own dotted-name
    handling. Prefix-filtering (done by the completion protocol itself)
    narrows this full set down to whatever the user has typed so far.
    """
    names: list[str] = []
    for manifest in _pdk_manifests():
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

    list_parser = commands.add_parser("list", help="list pdk/* registry manifests")
    list_parser.set_defaults(handler=command_list, ui_kind="wolf", ui_section="PDK packages")

    info_parser = commands.add_parser("info", help="show one pdk/NAME manifest's details")
    info_parser.add_argument("name", help="the pdk package name, e.g. tsmc65 (pdk/tsmc65)")
    info_parser.set_defaults(handler=command_info, ui_kind="wolf", ui_section="PDK package information")

    menu_parser = commands.add_parser(
        "menu", help="interactively create or edit a pdk/NAME registry manifest",
    )
    menu_parser.add_argument(
        "name", nargs="?",
        help="pdk package name, optionally dotted into a track/vth (tsmc65, tsmc65.9T, "
             "tsmc65.9T.lvt); omit to pick from existing packages or create one",
    )
    menu_parser.set_defaults(handler=command_menu, suppress_ui=True)

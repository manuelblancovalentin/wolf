"""Inspect and install packages from configured and built-in registries."""

from __future__ import annotations

import argparse

from wolf import ui
from wolf.package.installer import PackageInstaller
from wolf.package.registry import PackageRegistry
from wolf.package.store import PackageStore


def command_list(_args: argparse.Namespace) -> int:
    registry = PackageRegistry()
    store = PackageStore()
    visible = []
    for manifest in registry.manifests():
        status = store.status(manifest)
        if status != "not installed":
            visible.append((manifest, status))
    if not visible:
        ui.info("No WOLF packages installed.")
        return 0
    ui.key_value("KIND/NAME", "REVISION      STATUS     LOCATION")
    for manifest, status in visible:
        location = store.installation_path(manifest)
        ui.key_value(
            str(manifest.identifier),
            f"{manifest.revision[:12]}  {status:<9}  {location}",
        )
    return 0


def command_info(args: argparse.Namespace) -> int:
    registry = PackageRegistry()
    store = PackageStore()
    manifest = registry.get(args.package)
    ui.key_value("Package", manifest.identifier)
    ui.key_value("Description", manifest.description)
    ui.key_value("Source type", manifest.source.type)
    ui.key_value("Upstream", manifest.source.url)
    ui.key_value("Pinned revision", manifest.revision)
    ui.key_value("Registry", manifest.registry_name)
    ui.key_value("Registry type", manifest.registry_type)
    if manifest.registry_revision:
        ui.key_value("Registry revision", manifest.registry_revision)
    ui.key_value("Recursive submodules", "yes" if manifest.source.submodules else "no")
    if manifest.source.package is not None:
        ui.key_value("Parent package", manifest.source.package)
        ui.key_value("Parent content path", manifest.source.path or "")
        ui.key_value("Parent revision", manifest.source.parent_revision or "")
    status = store.status(manifest)
    ui.key_value("Status", status)
    ui.key_value("Installation path", store.installation_path(manifest))
    if status == "installed":
        installed = store.read(manifest)
        assert installed is not None
        ui.key_value("Content path", installed.content_path)
        ui.key_value("Installed at", installed.installed_at)
        ui.key_value("Installed from registry", installed.registry_name)
    if manifest.license:
        ui.key_value("License", manifest.license.get("spdx") or manifest.license.get("name", ""))
    for category, values in manifest.metadata.items():
        if isinstance(values, dict):
            ui.key_value(category.replace("_", " ").title(), "")
            for key, value in values.items():
                ui.key_value(f"  {key.replace('_', ' ').title()}", value)
        else:
            ui.key_value(category.replace("_", " ").title(), values)
    return 0


def command_install(args: argparse.Namespace) -> int:
    ui.info(f"Resolving and installing pinned package {args.package}")
    installed, created = PackageInstaller().install(args.package)
    if created:
        ui.success(f"Installed {installed.manifest.identifier} at {installed.installation_path}")
    else:
        ui.info(
            f"Package {installed.manifest.identifier} is already installed at "
            f"{installed.installation_path}"
        )
    return 0


def register_package(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("package", help="inspect locally managed packages")
    commands = parser.add_subparsers(dest="package_command", required=True)
    list_parser = commands.add_parser("list", help="list installed packages")
    list_parser.set_defaults(handler=command_list, ui_kind="wolf", ui_section="Installed packages")
    info_parser = commands.add_parser("info", help="show registry and installation metadata")
    info_parser.add_argument("package")
    info_parser.set_defaults(handler=command_info, ui_kind="wolf", ui_section="Package information")


def register_install(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("install", help="install a pinned WOLF package")
    parser.add_argument("package")
    parser.set_defaults(handler=command_install, ui_kind="wolf", ui_section="Package installation")

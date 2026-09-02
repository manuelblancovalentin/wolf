"""Friendly first-time global configuration wizard."""

from __future__ import annotations

import argparse
from pathlib import Path

from wolf import ui
from wolf.backend.orfs import _runtime_diagnostic
from wolf.config import ConfigStore, default_document
from wolf.shell import detect_shell, install_shell_integration


def _ask(prompt: str, default: str | None) -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or (default or "")


def _yes(prompt: str, default: bool = False) -> bool:
    marker = "Y/n" if default else "y/N"
    answer = input(f"{prompt} [{marker}]: ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def command_init(_args: argparse.Namespace) -> int:
    store = ConfigStore()
    ui.key_value("Configuration file", store.path)
    if store.path.exists() and not _yes("Configuration already exists. Reconfigure it?"):
        ui.info("Existing configuration was left unchanged.")
        return 0
    document = store.load(effective=True) if store.path.exists() else default_document()
    packages = _ask("Package store", document["paths"]["packages"])
    environments = _ask("Environment store", document["paths"]["environments"])
    workspace_default = document["workspace"].get("default") or str(Path.home() / "wolf-work")
    workspace = _ask("Default workspace", workspace_default)
    runtime = None
    for name in ("podman", "docker"):
        diagnostic = _runtime_diagnostic(name)
        ui.key_value(name.title(), diagnostic.detail)
        if runtime is None and diagnostic.usable:
            runtime = name
    selected_runtime = _ask("Preferred container runtime", runtime)
    document["paths"]["packages"] = str(Path(packages).expanduser().resolve())
    document["paths"]["environments"] = str(Path(environments).expanduser().resolve())
    document["workspace"]["default"] = str(Path(workspace).expanduser().resolve())
    document["container"]["preferred_runtime"] = selected_runtime or None
    store.write(document)
    ui.success(f"Wrote {store.path}")
    shell = detect_shell()
    if shell:
        rc = "~/.bashrc" if shell == "bash" else "~/.zshrc"
        ui.key_value("Detected shell", shell)
        if _yes(f"Install WOLF {shell} integration in {rc}?"):
            changed = install_shell_integration(shell)
            ui.success(f"Installed {shell} shell integration.") if changed else ui.info(
                f"{shell} shell integration is already installed."
            )
    else:
        ui.info("Could not determine the current shell; use shell/wolf.bash or shell/wolf.zsh.")
    if _yes("Configure an additional package registry now?"):
        ui.info("Use: wolf registry add NAME SOURCE")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("init", help="configure WOLF for first use")
    parser.set_defaults(handler=command_init, ui_kind="wolf", ui_section="WOLF initialization")

"""Translate canonical WOLF run inputs into ORFS-native configuration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from wolf.context import ResolvedContext


def _make_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise ValueError(f"ORFS Make override values must be scalar, got {type(value).__name__}")


def _container_path(path: Path, host_root: Path, container_root: str) -> str:
    try:
        relative = path.resolve().relative_to(host_root.resolve())
    except ValueError as error:
        raise ValueError(f"path {path} is outside its declared package root {host_root}") from error
    return f"{container_root}/{relative.as_posix()}"


def _write_sdc(source: Path | None, destination: Path, context: ResolvedContext) -> None:
    if len(context.clocks) != 1:
        raise ValueError("ORFS native mode currently requires exactly one canonical clock")
    clock = context.clocks[0]
    if source and source.is_file():
        text = source.read_text(encoding="utf-8")
        substitutions = (
            (r"(?m)^set\s+clk_name\s+.*$", f"set clk_name {clock.name}"),
            (r"(?m)^set\s+clk_port_name\s+.*$", f"set clk_port_name {clock.port}"),
            (r"(?m)^set\s+clk_period\s+.*$", f"set clk_period {clock.period_ps:g}"),
        )
        for pattern, replacement in substitutions:
            text, count = re.subn(pattern, replacement, text, count=1)
            if count == 0:
                raise ValueError(f"ORFS base SDC {source} lacks expected canonical clock assignment")
    else:
        text = (
            f"set clk_name {clock.name}\n"
            f"set clk_port_name {clock.port}\n"
            f"set clk_period {clock.period_ps:g}\n"
            "create_clock -name $clk_name -period $clk_period [get_ports $clk_port_name]\n"
        )
    destination.write_text(text, encoding="utf-8")


def _resolved_manifest(context: ResolvedContext, generated: Path) -> Mapping[str, Any]:
    return {
        "schema": "wolf.resolved-run/v1",
        "environment": context.environment_name,
        "design": {
            "package": context.design_package,
            "name": context.design_name,
            "top": context.design_top,
        },
        "technology": {"package": context.technology_package, "name": context.process},
        "flow": {"package": context.flow_package, "name": context.flow_name},
        "backend": {"name": context.backend, "overrides": context.backend_overrides.get(context.backend, {})},
        "constraints": {"clocks": [
            {"name": clock.name, "port": clock.port, "period_ps": clock.period_ps}
            for clock in context.clocks
        ]},
        "resources": {"threads": context.threads} if context.threads else {},
        "workspace": {"root": str(context.workspace_root), "run_directory": str(context.run_directory)},
        "packages": [
            {"id": identifier, "revision": revision}
            for identifier, revision in sorted(context.package_revisions.items())
        ],
        "generated": {"directory": str(generated)},
    }


def prepare_native_orfs(context: ResolvedContext, orfs_root: Path) -> Mapping[str, str]:
    """Generate deterministic ORFS inputs for a declarative RunContext."""
    overrides = context.backend_overrides.get("orfs", {})
    if not isinstance(overrides, Mapping):
        raise ValueError("backend.orfs must be a mapping")
    allowed = {"make", "design_config", "container_runtime", "container_image", "flow_variant"}
    unknown = sorted(set(overrides) - allowed)
    if unknown:
        raise ValueError(f"unknown ORFS backend override: backend.orfs.{unknown[0]}")
    make = overrides.get("make", {})
    if not isinstance(make, Mapping):
        raise ValueError("backend.orfs.make must be a mapping")

    design_root = context.package_paths.get("design")
    if design_root is None:
        raise ValueError("ORFS native mode requires an installed design package")
    if not context.source_files:
        raise ValueError("design package does not resolve any canonical RTL source files")
    if not context.design_top:
        raise ValueError("ORFS native mode requires design.top")

    base_directory = orfs_root / "designs" / context.process / context.design_name
    base_config = base_directory / "config.mk"
    base_sdc = base_directory / "constraint.sdc"
    configured = overrides.get("design_config")
    if configured:
        base_config = Path(str(configured)).expanduser().resolve()
    if not base_config.is_file():
        raise ValueError(
            f"ORFS does not provide native collateral for {context.process}/{context.design_name}: {base_config}"
        )

    identity = json.dumps({
        "environment": context.environment_name,
        "packages": sorted(context.package_revisions.items()),
        "design": [context.design_name, context.design_top],
        "technology": context.process,
        "clocks": [(clock.name, clock.port, clock.period_ps) for clock in context.clocks],
        "threads": context.threads,
        "overrides": overrides,
    }, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    generated = context.state_root / "generated" / "environments" / (context.environment_name or "anonymous") / digest
    generated.mkdir(parents=True, exist_ok=True)
    config = generated / "config.mk"
    sdc = generated / "constraints.sdc"
    manifest = generated / "resolved.yaml"

    _write_sdc(base_sdc if base_sdc.is_file() else None, sdc, context)
    source_values = [
        _container_path(path, design_root, "/wolf/design") for path in context.source_files
    ]
    include_values = [
        _container_path(path, design_root, "/wolf/design") for path in context.include_directories
    ]
    base_container = (
        _container_path(base_config, orfs_root, "/work")
        if base_config.is_relative_to(orfs_root)
        else "/wolf/native-config/config.mk"
    )
    lines = [
        f"include {base_container}",
        f"override DESIGN_NICKNAME := {context.design_name}",
        f"override DESIGN_NAME := {context.design_top}",
        "override VERILOG_FILES := " + " ".join(source_values),
        "override VERILOG_INCLUDE_DIRS := " + " ".join(include_values),
        "override SDC_FILE := /wolf/generated/constraints.sdc",
    ]
    if context.threads:
        lines.append(f"override NUM_CORES := {context.threads}")
    lines.extend(f"export {name}" for name in (
        "DESIGN_NICKNAME", "DESIGN_NAME", "VERILOG_FILES", "VERILOG_INCLUDE_DIRS", "SDC_FILE", "NUM_CORES"
    ))
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest.write_text(yaml.safe_dump(_resolved_manifest(context, generated), sort_keys=False), encoding="utf-8")

    flow_variant = _make_value(overrides.get("flow_variant")) or (
        "wolf_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", context.environment_name or context.run_tag)
    )
    mounts = [
        f"{design_root}|/wolf/design",
        f"{generated}|/wolf/generated",
    ]
    if configured and not base_config.is_relative_to(orfs_root):
        mounts.append(f"{base_config.parent}|/wolf/native-config")
    result = {
        "ORFS_ROOT": str(orfs_root),
        "ORFS_DESIGN_CONFIG": str(config),
        "ORFS_SDC_FILE": str(sdc),
        "ORFS_DESIGN_NAME": context.design_name,
        "ORFS_PLATFORM": context.process,
        "ORFS_FLOW_VARIANT": flow_variant,
        "ORFS_MAKE_VARS": "\n".join(f"{key}={_make_value(value)}" for key, value in make.items()),
        "WOLF_CONTAINER_MOUNTS": "\n".join(mounts),
        "WOLF_RESOLVED_MANIFEST": str(manifest),
        "WOLF_WORKSPACE_DIR": str(context.workspace_root),
        "ORFS_NATIVE_WORKSPACE": "1",
    }
    if overrides.get("container_runtime"):
        result["ORFS_CONTAINER_RUNTIME"] = _make_value(overrides["container_runtime"])
    if overrides.get("container_image"):
        result["ORFS_CONTAINER_IMAGE"] = _make_value(overrides["container_image"])
    return result

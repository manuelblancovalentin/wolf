"""Freeze resolved human-readable provenance into an allocated WOLF run."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Optional, Sequence

import yaml


RUN_MANIFEST_FILENAME = "wolf.resolved.yaml"


def _generated_files(value: str) -> Mapping[str, str]:
    files: dict[str, str] = {}
    for line in value.splitlines():
        if not line:
            continue
        role, separator, path = line.partition("|")
        if not separator or not role or not path:
            raise ValueError(f"invalid generated configuration record: {line!r}")
        files[role] = str(Path(path).expanduser().resolve())
    return files


def materialize_run_manifest(
    source: Path,
    run_directory: Path,
    *,
    executor: Optional[str] = None,
    runtime: Optional[str] = None,
    container_image: Optional[str] = None,
    generated_directory: Optional[Path] = None,
    generated_files: Optional[Mapping[str, str]] = None,
) -> Mapping[str, Any]:
    """Resolve allocation-time values without consulting mutable environment state."""
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"cannot read resolved manifest {source}: {error}") from error
    if not isinstance(data, dict) or data.get("schema") != "wolf.resolved-run/v1":
        raise ValueError(f"invalid resolved-run manifest: {source}")
    run_directory = run_directory.expanduser().resolve()
    workspace = data.setdefault("workspace", {})
    if not isinstance(workspace, dict):
        raise ValueError("resolved manifest workspace must be a mapping")
    workspace["run_directory"] = str(run_directory)

    execution = data.setdefault("execution", {})
    if not isinstance(execution, dict):
        raise ValueError("resolved manifest execution must be a mapping")
    for key, value in (
        ("executor", executor), ("runtime", runtime), ("container_image", container_image)
    ):
        if value:
            execution[key] = value

    generated = data.setdefault("generated", {})
    if not isinstance(generated, dict):
        raise ValueError("resolved manifest generated field must be a mapping")
    if generated_directory:
        generated["directory"] = str(generated_directory.expanduser().resolve())
    if generated_files:
        generated["files"] = dict(sorted(generated_files.items()))
    return data


def _write_immutable(destination: Path, payload: bytes) -> None:
    """Atomically replace destination's content: write to a sibling temp
    file, chmod read-only, then hardlink it into place -- the same
    write-once mechanism a brand-new manifest already used, just also
    used here to update an existing one (first making the existing file
    writable long enough to remove it)."""
    run_directory = destination.parent
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=run_directory
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o444)
        if destination.exists():
            os.chmod(destination, 0o644)
            destination.unlink()
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def freeze_run_manifest(
    source: Path,
    run_directory: Path,
    *,
    destination: Optional[Path] = None,
    executor: Optional[str] = None,
    runtime: Optional[str] = None,
    container_image: Optional[str] = None,
    generated_directory: Optional[Path] = None,
    generated_files: Optional[Mapping[str, str]] = None,
    volatile_keys: Sequence[str] = (),
) -> Path:
    """Atomically create, or verify, a resolved run manifest.

    A run is a durable identity that may accumulate append-only
    executions and stage results (continuing to a later -from/-to is the
    common case, not a new run) -- `volatile_keys` names the top-level
    keys that are expected to legitimately differ between invocations of
    the *same* run (e.g. from_stage/to_stage/execution, which trivially
    change just from picking a different stage range) without that
    meaning the run's actual identity changed. When every key outside
    `volatile_keys` still matches the manifest already on disk, this
    updates it in place instead of rejecting the run; a real identity
    difference (different RTL, different technology, ...) still raises.
    Callers that pass nothing (the default) get the original fully
    strict, byte-for-byte comparison.
    """
    run_directory = run_directory.expanduser().resolve()
    destination = (destination or run_directory / RUN_MANIFEST_FILENAME).resolve()
    if destination.parent != run_directory:
        raise ValueError("resolved run manifest must be written directly inside its run directory")
    data = materialize_run_manifest(
        source,
        run_directory,
        executor=executor,
        runtime=runtime,
        container_image=container_image,
        generated_directory=generated_directory,
        generated_files=generated_files,
    )
    payload = yaml.safe_dump(data, sort_keys=False).encode("utf-8")
    if destination.exists():
        if destination.read_bytes() == payload:
            return destination
        if volatile_keys:
            existing = yaml.safe_load(destination.read_bytes())
            identity_matches = isinstance(existing, dict) and all(
                existing.get(key) == data.get(key)
                for key in data
                if key not in volatile_keys
            ) and set(existing) - set(volatile_keys) == set(data) - set(volatile_keys)
            if identity_matches:
                _write_immutable(destination, payload)
                return destination
        raise ValueError(
            f"allocated run already has different immutable provenance: {destination}; "
            "select a new run identity"
        )

    run_directory.mkdir(parents=True, exist_ok=True)
    try:
        _write_immutable(destination, payload)
    except FileExistsError:
        if destination.read_bytes() != payload:
            raise ValueError(
                f"allocated run already has different immutable provenance: {destination}; "
                "select a new run identity"
            )
    return destination


def _command_freeze(args: argparse.Namespace) -> int:
    freeze_run_manifest(
        Path(args.source),
        Path(args.run_directory),
        destination=Path(args.destination) if args.destination else None,
        executor=os.environ.get("WOLF_EXECUTOR"),
        runtime=os.environ.get("WOLF_EXECUTOR_RUNTIME"),
        container_image=os.environ.get("WOLF_EXECUTOR_CONTAINER_IMAGE"),
        generated_directory=Path(os.environ["WOLF_GENERATED_CONFIG_DIR"])
        if os.environ.get("WOLF_GENERATED_CONFIG_DIR") else None,
        generated_files=_generated_files(os.environ.get("WOLF_GENERATED_CONFIG_FILES", "")),
    )
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m wolf.provenance")
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--source", required=True)
    freeze.add_argument("--run-directory", required=True)
    freeze.add_argument("--destination")
    freeze.set_defaults(handler=_command_freeze)
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except ValueError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

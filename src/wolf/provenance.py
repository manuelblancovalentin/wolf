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


def _strip_volatile_paths(value: Any, prefix: str, volatile_paths: frozenset) -> Any:
    """Return a deep copy of `value` with any key at dotted path
    `prefix.key` appearing in `volatile_paths` removed, regardless of
    nesting depth -- comparing the result with `==` then ignores
    exactly those fields without needing to blanket-exclude their
    whole containing key (e.g. "technology.cell_lefs" without also
    exempting "technology.package"/"technology.revision" from
    comparison, which would silently tolerate a genuine PDK swap
    mid-run). Non-dict values pass through unchanged."""
    if not isinstance(value, dict):
        return value
    result = {}
    for key, sub_value in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if path in volatile_paths:
            continue
        result[key] = _strip_volatile_paths(sub_value, path, volatile_paths)
    return result


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
    volatile_paths: Sequence[str] = (),
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
    A key WOLF's own schema has started recording since the manifest was
    first frozen (present in the fresh resolution, absent from the one
    on disk) is tolerated the same way -- schema growth is not a new run
    identity -- but a key the schema used to record and no longer does
    is still a hard mismatch. Callers that pass nothing (the default)
    get the original fully strict, byte-for-byte comparison.

    `volatile_paths` is `volatile_keys`' own sibling for a field nested
    *inside* an otherwise-strict top-level key -- dotted paths (e.g.
    "technology.cell_lefs") stripped from both sides before comparison
    (see `_strip_volatile_paths`), so a real WOLF resolution-logic fix
    that makes a previously-empty nested field start getting populated
    (confirmed real: `cell_lefs`/`rc_files` were always hardcoded empty
    for a tracked technology package before a bug fix, regardless of
    what the package manifest actually declared) doesn't block
    continuing an already-allocated run, without blanket-exempting the
    whole containing key (marking all of "technology" volatile would
    also silently tolerate a genuine mid-run PDK package swap, which
    must still raise).
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
        if volatile_keys or volatile_paths:
            existing = yaml.safe_load(destination.read_bytes())
            volatile_path_set = frozenset(volatile_paths)
            comparable_existing = (
                _strip_volatile_paths(existing, "", volatile_path_set)
                if volatile_path_set else existing
            )
            comparable_data = (
                _strip_volatile_paths(data, "", volatile_path_set) if volatile_path_set else data
            )
            # A key present in `existing` but absent from today's `data`
            # (a field WOLF's own schema removed or renamed) is still a
            # hard mismatch -- but a key present in `data` and absent
            # from `existing` (WOLF started tracking something new, e.g.
            # recording which backend a run used) is tolerated: an
            # already-frozen run from before that field existed is not a
            # different run identity just because today's WOLF knows
            # more about it than the version that first allocated it.
            non_volatile_existing = (
                set(comparable_existing) - set(volatile_keys)
                if isinstance(comparable_existing, dict) else set()
            )
            non_volatile_data = set(comparable_data) - set(volatile_keys)
            identity_matches = (
                isinstance(comparable_existing, dict)
                and non_volatile_existing <= non_volatile_data
                and all(
                    comparable_existing.get(key) == comparable_data.get(key)
                    for key in non_volatile_existing
                )
            )
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

"""Narrow subprocess bridge to behavior still owned by legacy Bash."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Optional, Sequence

from wolf.paths import state_root


class LegacyCommandError(RuntimeError):
    pass


def _legacy_root() -> Path:
    configured = os.environ.get("WOLF_LEGACY_ROOT")
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())

    # Source and editable installs.
    candidates.append(Path(__file__).resolve().parents[2])
    # Conventional data-files location for a regular installation.
    candidates.append(Path(sys.prefix) / "share" / "wolf")

    for candidate in candidates:
        if (candidate / "bin" / "wolf.env").is_file():
            return candidate.resolve()
    raise LegacyCommandError(
        "WOLF's legacy compatibility files could not be located; reinstall WOLF"
    )


def run_env(arguments: Sequence[str], *, environment_name: Optional[str] = None) -> None:
    """Run the legacy environment handler in an isolated Bash process."""
    root = _legacy_root()
    environment = os.environ.copy()
    environment["WOLF_HOME"] = str(state_root())
    if environment_name is not None:
        environment["WOLF_ENV_NAME"] = environment_name
        environment["WOLF_ENV_DIR"] = str(state_root() / "envs" / environment_name)

    script = 'source "$1"; shift; _wolf_env "$@"'
    result = subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            script,
            "wolf-legacy-env",
            str(root / "bin" / "wolf.env"),
            *arguments,
        ],
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        details = result.stderr.strip() or result.stdout.strip()
        message = "legacy environment operation failed"
        if details:
            message = f"{message}: {details}"
        raise LegacyCommandError(message)


def run_legacy(arguments: Sequence[str], environment: dict[str, str]) -> int:
    """Invoke the legacy runner from a stable installation path, not caller cwd."""
    root = _legacy_root()
    result = subprocess.run(
        ["bash", str(root / "bin" / "wolf.run"), *arguments],
        cwd=str(root),
        env=environment,
        check=False,
    )
    return result.returncode

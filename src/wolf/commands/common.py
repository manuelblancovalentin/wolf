"""Shared helpers for commands that accept a WOLF environment name."""

from __future__ import annotations

import os
from typing import Optional


def resolve_environment_name(explicit: Optional[str], *, required: bool = True) -> Optional[str]:
    """Resolve an environment name, falling back to the active shell session.

    An explicitly given name always wins over any fallback. WOLF_ACTIVE_ENV
    (set by `wolf activate` through the Bash/zsh integration) is the primary
    fallback; WOLF_ENV_NAME (set by the legacy Bash activation path) is a
    secondary fallback so legacy-environment sessions behave the same way.
    """
    name = explicit or os.environ.get("WOLF_ACTIVE_ENV") or os.environ.get("WOLF_ENV_NAME")
    if not name and required:
        raise ValueError(
            "no WOLF environment is active; pass an environment explicitly or "
            "run `wolf activate <environment>` first"
        )
    return name or None

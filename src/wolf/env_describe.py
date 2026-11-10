"""A sanitized, website-safe description of one WOLF environment: each
variable's name and a *safe* value only, plus the exact lines a person
types to activate and work with the design. Schema ``wolf.describe/v1``.
See docs/DIGEST.md.

No raw value from a library or PDK tree is ever shown as-is: a value
that looks like it points into one becomes the literal marker
``<library>``; a value inside the project becomes project-relative;
anything else is shown only if it matches a strict, narrow pattern, and
is otherwise reported as ``"hidden"`` with no part of the real value.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Optional

DESCRIBE_SCHEMA = "wolf.describe/v1"

# A deliberately narrow allowance: short identifiers, simple numbers,
# version-looking tokens, a bare relative filename -- not quotes, not
# spaces, not shell metacharacters, not arbitrarily long text.
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.+-]{1,64}$")

# Case-insensitive hints that a path is pointing into a PDK/library tree
# this module must never show, even project-relative -- deliberately
# generic (name-shaped, not any one institution's real path) so it keys
# off what the path *looks like*, not a value this module had to be told
# about in advance.
_LIBRARY_HINTS = ("library", "/ip/", "/ip", "/pdk/")


def _looks_like_a_library_path(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in _LIBRARY_HINTS)


def safe_value(raw_value: Any, project_root: Optional[Path] = None) -> Optional[str]:
    """One value, made safe to show on a public-facing page. `None` stays
    `None` (an unset variable, not a hidden one)."""
    if raw_value is None:
        return None
    text = str(raw_value)
    path = Path(text)
    if path.is_absolute():
        if _looks_like_a_library_path(text):
            return "<library>"
        if project_root is not None:
            try:
                return str(path.resolve().relative_to(Path(project_root).resolve()))
            except (OSError, ValueError):
                pass
        return "hidden"
    if _SAFE_VALUE.fullmatch(text):
        return text
    return "hidden"


def build_description(
    name: str,
    variables: Mapping[str, Any],
    *,
    design_name: Optional[str] = None,
    process: Optional[str] = None,
    metal_stack: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> dict[str, Any]:
    safe_variables = {
        key: safe_value(value, project_root) for key, value in sorted(variables.items())
    }
    return {
        "schema": DESCRIBE_SCHEMA,
        "environment": name,
        "design": design_name,
        "process": process,
        "metal_stack": metal_stack,
        "variables": safe_variables,
        "activation_commands": [f"wolf activate {name}", "wolf run"],
    }


def description_path(project_root: Path, design_name: str, environment_name: str) -> Path:
    return (
        Path(project_root) / "inputs" / "env" / design_name
        / f"wolf.{environment_name}.description.json"
    )


def write_description(project_root: Path, design_name: str, environment_name: str, description: dict[str, Any]) -> Path:
    """Write the description as a real file next to the environment
    definition in the project -- never a link, so it can be read by a
    scan that never runs wolf and never dereferences anything outside
    the project tree."""
    import json
    import os
    import tempfile

    destination = description_path(project_root, design_name, environment_name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=str(destination.parent), prefix=f".{destination.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(description, handle, sort_keys=True, indent=2)
        os.replace(temp_name, destination)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return destination

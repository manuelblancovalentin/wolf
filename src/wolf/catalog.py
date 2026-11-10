"""WOLF's canonical-concepts catalog: variables, processes, choices, flow
stages, and commands, generated from WOLF's own code and documentation so
a website never hand-copies this. See ``wolf catalog --json`` and
docs/CATALOG.md.

Rules this module exists to honor (see the handoff that introduced it):
no value that could come from a PDK or library tree -- no paths, versions,
directory layouts, file names, layer maps, license hosts/ports, user names
or e-mail addresses -- ever appears here. A ``path``-typed variable is
described by its meaning only, never by an example value drawn from a real
installation.
"""

from __future__ import annotations

from typing import Any

from wolf import __version__
from wolf.backend import get_backend
from wolf.backend.cadence_genus import IMPLEMENTATION_STAGES, SYNTHESIS_STAGES
from wolf.backend.orfs import ORFS_STAGES

SCHEMA = "wolf.catalog/v1"

# Every item below defaults to the current installed version unless noted
# otherwise. WOLF does not yet mine git history per concept, so `since`
# is a simplification: it names the version this catalog last confirmed
# the item under, not necessarily the version that first introduced it.
_SINCE = __version__


def _variables() -> list[dict[str, Any]]:
    return [
        {
            "name": "DESIGN_NAME",
            "meaning": "The design this environment targets.",
            "type": "text",
            "source": "per-design bucket",
            "required": True,
            "scope": "per-design",
            "example": "my_design",
            "visibility": "public",
            "since": _SINCE,
        },
        {
            "name": "PROCESS",
            "meaning": "The process node this environment builds against.",
            "type": "choice",
            "source": "profile bucket",
            "required": True,
            "scope": "per-project",
            "example": "asap7",
            "visibility": "public",
            "since": _SINCE,
        },
        {
            "name": "METAL_STACK",
            "meaning": "The metal-stack option selected for the chosen process.",
            "type": "choice",
            "source": "profile bucket",
            "required": False,
            "scope": "per-project",
            "example": "<stack-name>",
            "visibility": "internal",
            "since": _SINCE,
        },
        {
            "name": "PROJ_DIR",
            "meaning": "The project directory holding this design's inputs, outputs, and workspace.",
            "type": "path",
            "source": "per-design bucket",
            "required": True,
            "scope": "per-design",
            "example": None,
            "visibility": "public",
            "since": _SINCE,
        },
        {
            "name": "VTHS",
            "meaning": (
                "The threshold-voltage flavor(s) synthesis may pick cells "
                "from; may name more than one so Genus can mix libraries "
                "on a path-by-path basis."
            ),
            "type": "list",
            "source": "profile bucket",
            "required": False,
            "scope": "per-project",
            "example": ["<vth-name>"],
            "visibility": "internal",
            "since": _SINCE,
        },
        {
            "name": "TRACKS",
            "meaning": "The cell-library track(s) selected alongside the chosen VTH(s).",
            "type": "list",
            "source": "profile bucket",
            "required": False,
            "scope": "per-project",
            "example": ["<track-name>"],
            "visibility": "internal",
            "since": _SINCE,
        },
        {
            "name": "CONSTRAINTS_FILE",
            "meaning": "The design's timing/constraints source file.",
            "type": "path",
            "source": "per-design bucket",
            "required": False,
            "scope": "per-design",
            "example": None,
            "visibility": "public",
            "since": _SINCE,
        },
        {
            "name": "WORKSPACE_DIR",
            "meaning": "The resolved workspace root a run executes under.",
            "type": "path",
            "source": "user",
            "required": False,
            "scope": "per-project",
            "example": None,
            "visibility": "public",
            "since": _SINCE,
        },
    ]


def _processes() -> list[dict[str, Any]]:
    # WOLF's own code/registry does not yet record a gating Unix group or a
    # proj bundle per process -- that mapping lives in proj, outside WOLF's
    # own domain. Both fields are reported as null rather than guessed.
    return [
        {
            "name": "asap7",
            "purpose": "Open, public 7nm-class academic PDK used by WOLF's ORFS backend example flow.",
            "gating_group": None,
            "proj_bundle": None,
            "visibility": "public",
            "since": _SINCE,
        },
        {
            "name": "tsmc65",
            "purpose": "Cadence Flowtool/Genus/Innovus process-specific setup bundled as a WOLF backend asset.",
            "gating_group": None,
            "proj_bundle": None,
            "visibility": "internal",
            "since": _SINCE,
        },
        {
            "name": "tsmc28",
            "purpose": "Cadence Flowtool/Genus/Innovus process-specific setup bundled as a WOLF backend asset.",
            "gating_group": None,
            "proj_bundle": None,
            "visibility": "internal",
            "since": _SINCE,
        },
        {
            "name": "gf22",
            "purpose": "Cadence Flowtool/Genus/Innovus process-specific setup bundled as a WOLF backend asset.",
            "gating_group": None,
            "proj_bundle": None,
            "visibility": "internal",
            "since": _SINCE,
        },
    ]


def _choices() -> dict[str, Any]:
    # No package in WOLF's own registry today declares more than one
    # metal-stack or vth option, so there is no real choice list to report
    # yet without reading bundled Cadence template content WOLF deliberately
    # avoids mining for this catalog. Left empty and explained rather than
    # guessed; see the accompanying report.
    return {
        "metal_stack": [],
        "vth": [],
    }


def _flows() -> list[dict[str, Any]]:
    cadence = get_backend("cadence-flowtool")
    orfs = get_backend("orfs")
    return [
        {
            "backend": cadence.name,
            "purpose": cadence.description,
            "stages": [
                {"name": stage, "tool_suite": "Cadence Genus"} for stage in SYNTHESIS_STAGES
            ]
            + [
                {"name": stage, "tool_suite": "Cadence Innovus"} for stage in IMPLEMENTATION_STAGES
            ],
            "since": _SINCE,
        },
        {
            "backend": orfs.name,
            "purpose": orfs.description,
            "stages": [
                {"name": stage, "tool_suite": "Yosys" if stage == "synth" else "OpenROAD"}
                for stage in ORFS_STAGES
            ],
            "since": _SINCE,
        },
    ]


def _commands(build_parser) -> list[dict[str, Any]]:
    """Walk the real argparse tree so this list can never drift from what
    `wolf` actually accepts."""
    parser = build_parser()
    entries: list[dict[str, Any]] = []

    def walk(action, prefix: str) -> None:
        for name, subparser in action.choices.items():
            if name.startswith("_"):
                continue
            full_name = f"{prefix} {name}".strip()
            help_text = None
            for sub_action in action._choices_actions:
                if sub_action.dest == name:
                    help_text = sub_action.help
                    break
            entries.append({"command": f"wolf {full_name}", "purpose": help_text or ""})
            for sub in subparser._subparsers._group_actions if subparser._subparsers else []:
                walk(sub, full_name)

    for action in parser._subparsers._group_actions:
        walk(action, "")
    return entries


def build_catalog(build_parser=None) -> dict[str, Any]:
    if build_parser is None:
        from wolf.cli import build_parser as _build_parser

        build_parser = _build_parser
    return {
        "schema": SCHEMA,
        "wolf_version": __version__,
        "variables": _variables(),
        "processes": _processes(),
        "choices": _choices(),
        "flows": _flows(),
        "commands": _commands(build_parser),
    }

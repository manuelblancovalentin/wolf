"""Best-effort structure parsing for `create_flow`/`create_flow_step` Tcl.

Not a general Tcl parser -- brace-matching only, no comment or string
awareness beyond that. Good enough for WOLF's own flow files (which it
writes/ships itself, in a controlled style), used to drive the `wolf env
menu` flow-structure inspector. Never used for anything that executes;
only for display.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class FlowStep:
    name: str
    owner: str | None
    write_db: bool
    body: str
    file: Path
    line: int


@dataclass(frozen=True)
class FlowSequence:
    name: str
    owner: str | None
    tool: str | None
    steps: tuple[str, ...]
    file: Path
    line: int


@dataclass(frozen=True)
class FlowStructure:
    sequences: tuple[FlowSequence, ...]
    steps: dict[str, FlowStep]


_NAME_RE = re.compile(r"-name\s+(\S+)")
_OWNER_RE = re.compile(r"-owner\s+(\S+)")
_TOOL_RE = re.compile(r"-tool\s+(\S+)")


def _find_matching_brace(text: str, open_index: int) -> int:
    """Return the index just past the `}` matching text[open_index] == '{'."""
    depth = 0
    index = open_index
    while index < len(text):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise ValueError(f"unbalanced braces starting at index {open_index}")


def _parse_calls(text: str, command: str):
    """Yield (header, body, line, end_index) for each `command ... { body }` call.

    `header` is everything between the command name and the opening brace
    (the -name/-owner/-tool flags); `end_index` is the index just past the
    call's closing brace, so a caller can check what immediately follows
    (e.g. a trailing -write_db).
    """
    for match in re.finditer(rf"\b{re.escape(command)}\s", text):
        start = match.start()
        brace = text.find("{", start)
        if brace == -1:
            continue
        header = text[start:brace]
        end = _find_matching_brace(text, brace)
        body = text[brace + 1:end - 1]
        line = text.count("\n", 0, start) + 1
        yield header, body, line, end


def parse_flow_directory(directory: Path) -> FlowStructure:
    """Parse every `*.tcl` file in `directory` for flow/step structure."""
    sequences: list[FlowSequence] = []
    steps: dict[str, FlowStep] = {}
    for path in sorted(directory.glob("*.tcl")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for header, body, line, end in _parse_calls(text, "create_flow_step"):
            name_match = _NAME_RE.search(header)
            if not name_match:
                continue
            owner_match = _OWNER_RE.search(header)
            tail = text[end:end + 40].lstrip()
            steps[name_match.group(1)] = FlowStep(
                name=name_match.group(1),
                owner=owner_match.group(1) if owner_match else None,
                write_db=tail.startswith("-write_db"),
                body=body.strip("\n"),
                file=path,
                line=line,
            )

        for header, body, line, _end in _parse_calls(text, "create_flow"):
            name_match = _NAME_RE.search(header)
            if not name_match:
                continue
            owner_match = _OWNER_RE.search(header)
            tool_match = _TOOL_RE.search(header)
            sequences.append(FlowSequence(
                name=name_match.group(1),
                owner=owner_match.group(1) if owner_match else None,
                tool=tool_match.group(1) if tool_match else None,
                steps=tuple(body.split()),
                file=path,
                line=line,
            ))

    return FlowStructure(sequences=tuple(sequences), steps=steps)

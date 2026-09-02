#!/usr/bin/env python3

"""Create or validate the namespaced 1050 ps SDC for the Ibex ORFS harness."""

from __future__ import annotations

from pathlib import Path
import re
import sys
from typing import Iterable, Optional


CLOCK_PATTERN = re.compile(r"^(\s*set\s+clk_period\s+)(\S+)(\s*(?:#.*)?)$", re.MULTILINE)


def has_1050_ps_clock(contents: str) -> bool:
    matches = CLOCK_PATTERN.findall(contents)
    return len(matches) == 1 and matches[0][1] == "1050"


def create_or_validate(source: Path, target: Path) -> None:
    if target.exists():
        if not has_1050_ps_clock(target.read_text(encoding="utf-8")):
            raise ValueError(f"existing target does not contain exactly 'set clk_period 1050': {target}")
        return

    source_contents = source.read_text(encoding="utf-8")
    updated_contents, replacements = CLOCK_PATTERN.subn(r"\g<1>1050\g<3>", source_contents)
    if replacements != 1:
        raise ValueError(f"expected one clk_period assignment in source: {source}")
    try:
        with target.open("x", encoding="utf-8") as stream:
            stream.write(updated_contents)
    except FileExistsError:
        if not has_1050_ps_clock(target.read_text(encoding="utf-8")):
            raise ValueError(f"concurrent target does not contain a 1050 ps clock: {target}")


def main(argv: Optional[Iterable[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 2:
        print("usage: prepare_orfs_ibex_sdc.py SOURCE_SDC TARGET_SDC", file=sys.stderr)
        return 2
    try:
        create_or_validate(Path(arguments[0]), Path(arguments[1]))
    except (OSError, ValueError) as error:
        print(f"cannot prepare ORFS Ibex SDC: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

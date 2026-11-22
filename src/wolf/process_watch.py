"""Whether a run's own backend process is still alive, read from `/proc`
only -- no tool name is hardcoded anywhere here, so this is the same check
for a Cadence run or an ORFS one: a process counts as this run's own worker
when its own working directory (its `/proc/<pid>/cwd` symlink) resolves at
or under the run directory. This is how `wolf status`/`wolf monitor` tell a
stage that is genuinely still running from one whose flow.status record
says "running" because the tool that was updating it died without ever
writing a clean "failed" (a kill -9, an OOM kill, a crashed license
daemon) -- the latter is reported as "stalled", not "running".
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import NamedTuple

_DELETED_SUFFIX = " (deleted)"


class RunProcess(NamedTuple):
    pid: int
    start: float
    rss_gib: float
    command: str
    cwd: str
    orphaned: bool


def _boot_time() -> float:
    try:
        with open("/proc/stat", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("btime"):
                    return float(line.split()[1])
    except OSError:
        pass
    return 0.0


def _under(cwd: str, run_directory: Path) -> bool:
    try:
        resolved = Path(cwd).resolve()
    except OSError:
        return False
    return resolved == run_directory or resolved.is_relative_to(run_directory)


def run_processes(run_directory: Path) -> tuple[RunProcess, ...]:
    """Every process of the current user whose own working directory is at
    or under `run_directory`, read straight from `/proc`. A process whose
    `cwd` symlink carries the kernel's own " (deleted)" suffix -- the run
    directory was removed while it kept working there -- is still
    returned, flagged `orphaned=True`, rather than silently dropped."""
    run_directory = run_directory.resolve()
    boot = _boot_time()
    try:
        tick = os.sysconf("SC_CLK_TCK")
        page = os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError):
        return ()
    me = os.getuid()
    found: list[RunProcess] = []
    try:
        pids = [name for name in os.listdir("/proc") if name.isdigit()]
    except OSError:
        return ()
    for pid in pids:
        try:
            if os.stat(f"/proc/{pid}").st_uid != me:
                continue
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            continue
        orphaned = cwd.endswith(_DELETED_SUFFIX)
        cwd_path = cwd[: -len(_DELETED_SUFFIX)] if orphaned else cwd
        if not _under(cwd_path, run_directory):
            continue
        try:
            with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as handle:
                stat_line = handle.read()
            fields = stat_line[stat_line.rindex(")") + 2:].split()
            start = boot + int(fields[19]) / tick
            rss_gib = int(fields[21]) * page / (1024 ** 3)
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                command = handle.read().replace(b"\0", b" ").decode(errors="replace").strip()
        except (OSError, ValueError, IndexError):
            continue
        found.append(RunProcess(
            pid=int(pid), start=start, rss_gib=rss_gib,
            command=command or f"pid {pid}", cwd=cwd_path, orphaned=orphaned,
        ))
    return tuple(found)


def run_is_alive(run_directory: Path) -> bool:
    """True when at least one of the current user's own processes is
    still working in `run_directory` -- see `run_processes`."""
    return bool(run_processes(run_directory))

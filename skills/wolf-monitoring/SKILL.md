---
name: wolf-monitoring
description: Use when you need to watch a WOLF run while it is going, or tell whether a stage that still says "running" is actually dead.
---

# Monitoring a WOLF run

Verified 2026-11-22 with WOLF 0.1.0. The `stalled` status and the
process line below were added to WOLF itself on this date -- use these
commands rather than writing your own process-liveness check against
`/proc`.

## How do I watch a run while it is going?
```bash
wolf status --environment <environment> --watch
```
redraws a stage table in place until the run finishes -- no need to pipe
it through the external `watch` command, which would strip the colors.
`wolf monitor --environment <environment>` is a fuller full-screen view
with an expandable step tree for whichever stage is currently running.
Both read the same run; use whichever fits your terminal.

## How do I check once, without watching?
```bash
wolf status --environment <environment>
wolf status --environment <environment> --json   # wolf.status/v1
```
`--json` gives the same facts a script can read: `run.status`,
`stages[].status`, and, when relevant, `run.failed_stage` or
`run.stalled_stage`.

## How do I tell a stage that is really still running from one that silently died?
A stage whose own status file says "running" is cross-checked against the
real process table (`/proc`, read-only, no tool name assumed -- works the
same for Cadence or ORFS). If nothing of yours is still working in that
run directory, the stage is reported **`stalled`**, not `running`:
```
 Stalled stage: syn_map (no process is working in the run directory anymore)
```
`wolf status --watch` and `wolf monitor` both stop on a stalled run the
same way they stop on a finished or failed one -- you do not have to
notice it by a frozen screen. A genuinely active run also prints a
`Processes` section with one line per real process working in the run
directory: PID, elapsed time, memory (GiB), and its command line. A
process still working in a run directory that was itself deleted out from
under it is flagged `ORPHAN: run directory deleted` right there, instead
of silently vanishing from the view.

## What are the stage names, and what does `skipped` mean?
A Cadence Flowtool environment's stage list comes from that environment's
own flow (`wolf run --plan` lists it) -- not just the bundled nine. A
project flow's own extra stages, and a branched section that schedules more
than one sub-flow at once (e.g. `signoff_checks` running
`physical_verification`/`extract`/`sta`), each show up as their own row.
A stage with no evidence it ever ran, while a later one in the same run
did, shows **`skipped`** instead of `pending` -- most likely a stage a
feature flag turned off. This is read from the absence of evidence, not
from the flag itself (WOLF has no visibility into which flag or how it was
set), so it cannot tell "turned off on purpose" from "something else kept
it from running" -- treat it as a hint to check, not a verdict.

## How do I rerun once I've confirmed a stage stalled?
Exactly like a clean failure -- see `skills/wolf-run-failures` and
`skills/wolf-run-flow`'s "How do I rerun from a failed step?": `wolf run
--environment <environment> -from <stalled stage>`.

## What does this skill not cover?
Reading a *failure* message (`skills/wolf-run-failures`); running the flow in
the first place (`skills/wolf-run-flow`); a dashboard across many unrelated
projects' own simulation/synthesis jobs -- that is project-specific
tooling outside WOLF, not something this skill, or WOLF's own monitor,
tries to be.

## Commands in this skill
* `wolf status [--environment <name> | --run <path>] [--json] [--watch]`
  -- read-only.
* `wolf monitor [--environment <name> | --run <path>]` -- read-only.
* `wolf run --environment <name> -from <stage>` -- not read-only; reruns
  from the named stage (see `skills/wolf-run-flow`).

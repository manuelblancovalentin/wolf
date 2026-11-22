---
name: wolf-preflight
description: Use before running a WOLF flow, to check which tools and versions it assumes are actually reachable -- so a run fails in seconds on a missing tool, not minutes in.
---

# Checking a WOLF flow's tool assumptions before you run it

Verified 2026-11-22 with WOLF 0.1.0.

## What does my environment assume?
```bash
wolf info <environment>
```
names the backend (`cadence-flowtool` or `orfs`) and the technology
package. Those two choices decide which real tools the next step checks.

## How do I check the backend's own tools are reachable?
```bash
wolf backend info <environment's backend>
```
For `cadence-flowtool` this reports whether `flowtool` and `python3` each
resolve, with the exact path when they do (`flowtool: available (/path/to/
flowtool)`) or `unavailable` when not -- the same check `wolf run` itself
does before resolving anything further, so running this first turns a
failure that would otherwise show up mid-plan into one you see immediately.
For `orfs` it reports `ORFS_ROOT`, the `Makefile` and `util/docker_shell`
under it, which container runtime it picked (`podman` or `docker`) and
whether the flow's container image is already available locally.

## How do I check WOLF itself and its configuration?
```bash
wolf doctor
```
reports the WOLF and Python versions, the operating system, which
`WOLF_HOME`/config file is in effect, Git availability, whether the
package store is writable, every configured registry's own readiness, and
whether Docker/Podman are present (optional -- only `orfs` needs either).
Nothing here checks a vendor EDA tool itself; that is backend-specific, see
above.

## How do I check the vendor tool's own version?
That is outside WOLF -- see the tool's own documentation (for example
`genus -version`). `wolf backend info` only confirms the
*executable* resolves, never which version it is or whether its licence
will actually check out.

## What does this skill not cover?
Licence checkout and display behaviour (the vendor tool's own skill); what
a specific run failure means once you are already mid-run
(`skills/wolf-run-failures`).

## Commands in this skill
* `wolf info [<environment>]` -- read-only.
* `wolf backend info <name>` -- read-only.
* `wolf doctor` -- read-only.

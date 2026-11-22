---
name: wolf-run-failures
description: Use when a `wolf run`, `wolf env create`, or `wolf status` command failed and you need to know what the message means and what to do about it.
---

# Common WOLF run failures

Verified 2026-11-22 with WOLF 0.1.0, by provoking each one against a
throwaway environment. The provenance-mismatch
row is read from WOLF's own source (`provenance.py`), not provoked live.

| Message | Cause | What to do |
|---|---|---|
| `unknown WOLF package 'pdk/<name>'; available packages: <list>` | the technology (or RTL/flow) package the environment names was never installed in this `WOLF_HOME` | `wolf install pdk/<name>`; if it is not in the list at all, the project has not added that library bundle yet -- `proj use <bundle-name>`, or ask the owner |
| `incomplete WOLF run context; unresolved required field: <field>` | the environment is missing a required piece (commonly `technology`, or `workspace.root` when `project.root` is also unset) | `wolf info <environment>` names the same missing field under "Environment is partial"; add it with `wolf env set` or finish the YAML and `wolf env create` again |
| `unsupported stage '<name>'; expected one of (...)` | a typo in `-from`/`-to` | use one of the nine real stage names the message lists (`syn_generic`, `syn_map`, `syn_opt`, `floorplan`, `prects`, `cts`, `postcts`, `route`, `postroute`) |
| `WOLF environment '<name>' does not exist` | a typo'd `--environment`, or no environment activated and none named | `wolf env list` to see the real names; `wolf activate <name>` or pass `--environment` |
| `Cadence Genus validation failed: flowtool: unavailable` | Cadence's own tools are not on `PATH` in this shell -- `wolf run`/`--plan` checks that `flowtool` resolves before anything else starts | however your site makes Cadence's tools available (a module, a shared install), load/activate that first; check with `command -v flowtool` |
| `ORFS_ROOT is not configured and flow/orfs is not installed` | the environment's backend is `orfs` but no ORFS checkout is configured on this machine | ask the owner to configure `ORFS_ROOT`, or switch the environment to `cadence-flowtool` if that is what is actually installed here |
| a stage stays `running` forever in `wolf status`, but you know the job died | the tool process was killed (OOM, a licence daemon that crashed, `kill -9`) without writing a clean failure -- WOLF now calls this **stalled**, not running, once it confirms no process of yours is still working in the run directory | `wolf status --environment <name>` shows `Stalled stage: <name>`, not a false "running"; once you've confirmed it is really dead, rerun from that stage (see `skills/wolf-run-flow`) |
| `allocated run already has different immutable provenance: <path>; select a new run identity` (read from source, not provoked live) | the environment changed (a different technology package revision, a different flow) since this numbered run directory was first allocated -- often after a tool/package upgrade | `wolf run -c` to allocate a fresh numbered run, or `--force` to continue the same one anyway (records exactly what changed in the run's own `wolf.resolved.drift.yaml` instead of silently overwriting it) |

## What does this skill not cover?
The vendor tool's own start-up, licence and display failures (that tool's
own documentation); how to read a passing/failing run's
status in the first place (`skills/wolf-run-flow`); checking tool versions
before you start (`skills/wolf-preflight`).

## Commands in this skill
* `wolf env list` -- read-only.
* `wolf info [<environment>]` -- read-only.
* `wolf status [--environment <name>]` -- read-only.
* `wolf install <package>` -- not read-only (writes under `~/.wolf/packages`).
* `wolf run --environment <name> -c` -- not read-only; allocates a new run.
* `wolf run --environment <name> --force` -- not read-only; continues an
  allocated run despite a provenance mismatch and records the drift.

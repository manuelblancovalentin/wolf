---
name: run-flow
description: Use when you need to run a WOLF flow -- the whole thing or a range of steps -- on a design, and want the exact command, where logs and results land, and how to tell whether it worked.
---

# Running a flow with WOLF

Verified 2026-11-22 with WOLF 0.1.0.dev1. Anything not listed here is not
verified. How your site makes the `wolf` command available (a module, a
shared install, a container) is its own configuration; check with `wolf
--version` and `command -v wolf`. This skill covers the `wolf run`/`wolf
status` commands themselves; actually launching a real vendor tool needs that
tool's own licence and skill (for example `skills/genus`) -- running one was
out of scope for verifying this skill, so the parts that start a real tool
are read from WOLF's own source, not watched live.

## How do I run the whole flow?
Activate the environment once, then run:

```bash
wolf activate demo
wolf run
```

or, without activating, name it explicitly for one invocation:

```bash
wolf run --environment demo
```

`wolf run` resolves the environment, then launches the backend's own tool
chain (Cadence Genus/Innovus through `flowtool`, or an OpenROAD Flow Scripts
container) for every stage in order. First check what it would do with
`--plan`, which only prints the resolved paths and never starts a tool or
needs a licence:

```bash
wolf run --environment demo --plan
```

## How do I run just part of it?
A flow is nine stages, in order: `syn_generic`, `syn_map`, `syn_opt`,
`floorplan`, `prects`, `cts`, `postcts`, `route`, `postroute`.
`-from`/`-to` take any of those names:

```bash
wolf run --environment demo -from syn_generic -to syn_opt
```

Naming a stage that is not one of the nine fails immediately with the exact
list, before anything runs:
`unsupported stage '<name>'; expected one of ('syn_generic', 'syn_map', ...)`.
`-c`/`--clean` allocates a brand-new numbered run instead of continuing the
latest one; without it, a run picks up the same numbered directory (so
`-from` continues real work, not a fresh one).

## Where do logs and results land?
Every run gets its own numbered directory:
`<project root>/workspace/<design>/<design>.<process>/<design>.<N>`
(`--plan` prints the exact path for your environment before anything runs).
`wolf info <environment>` shows the same project root and design name if you
need to find it without running `--plan` again. Nothing lands in your home
folder or the current directory -- the run directory is resolved from the
environment, never from where you happened to type the command.

## How do I tell whether it worked?
```bash
wolf status --environment demo
```
prints a stage table (`● running`, `● failed`, `○ unknown`, `✓` for a
finished stage) and, for a finished run, an overall `Status: succeeded` or
`Status: failed` line. A failed run also names the stage: `Failed stage:
syn_map`. Add `--watch` to the same command to auto-refresh while a run is
still going, or use `wolf monitor --environment demo` for a fuller live
view. `wolf status --environment demo --json` prints the same facts as
`wolf.status/v1` JSON (`run.status`, `stages[].status`, `metrics`) for a
script to read instead of parsing the table.

## How do I rerun from a failed step?
Once you know which stage failed (from `wolf status`), rerun from exactly
that stage, in the same run directory (no `-c`):

```bash
wolf run --environment demo -from syn_map
```

A stage that already finished is not redone unless you name it as the
`-from` stage yourself.

## What does this skill not cover?
The vendor tool's own start-up, licence and display behaviour (see that
tool's own skill, for example `skills/genus`); what each of the nine stages
actually does inside a design (that is flow methodology, not WOLF); the
common failure messages of a run (`skills/run-failures`); creating or editing
an environment in the first place (`skills/new-environment`).

## Commands in this skill
* `wolf activate <environment>` -- read-only (selects configuration for the
  current shell; starts nothing).
* `wolf run [--environment <name>] [--plan] [-from <stage>] [-to <stage>]
  [-c]` -- `--plan` is read-only; without `--plan` it launches the backend's
  own tool and writes a new or continued run directory.
* `wolf status [--environment <name> | --run <path>] [--json] [--watch]` --
  read-only.
* `wolf monitor [--environment <name> | --run <path>]` -- read-only.
* `wolf info [<environment>]` -- read-only.

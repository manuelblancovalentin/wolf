---
name: wolf-environments
description: Use when you need to see what WOLF environments and flows exist, read what one environment does without running it, or understand how an environment relates to a project's `proj` environment, if your site uses one.
---

# Browsing WOLF environments and flows

Verified 2026-11-22 with WOLF 0.1.0.

## How do I see what environments exist?
```bash
wolf env list
```
prints every environment WOLF knows about, one name per line, under
"Available environments". There are no columns to read -- for anything
beyond the name, describe one specific environment instead.

## How do I read what one environment does, without running it?
```bash
wolf info <environment>
```
prints its format (`declarative-v1` or `legacy`), design name, technology
package and process name, backend, flow source, and constraints -- the same
view whether the environment is active or not. If it is only partially set
up it says so plainly, for example `Environment is partial; unresolved:
technology`, naming exactly which piece is missing.

For a sanitized, shareable version of the same facts (safe to hand to
another tool or person: library-looking paths become the literal marker
`<library>`, an absolute in-project path becomes project-relative):
```bash
wolf env describe <environment>
wolf env describe <environment> --json   # machine-readable wolf.describe/v1
```

## How does an environment relate to a project's `proj` environment?
They are two different things that sit side by side, if your site uses
`proj` (or a similar tool) at all. `proj` manages a project's own modules
and tool access; WOLF manages one design's resolved build configuration
(sources, constraints, technology package, backend) inside that project.
If WOLF is one of the modules `proj` can add, check `proj module --help`
and `proj avail` for the exact name your site gave it, then something
like:
```bash
proj module add application <wolf's module name> --env <project>
proj reload   # if the project is already active
```
`wolf activate <environment>` is a separate step after that: it sets
`WOLF_ACTIVE_ENV` in the shell (nothing else), and while a `proj`
environment is also active, `proj`'s own prompt draws WOLF's marker for it
(the token `wolf` in `PROJ_PROMPT_TOKENS`) instead of WOLF drawing a second
one -- you will not see the `«name»` marker twice. The process library a
design needs is a `proj` concept too, added by bundle name only:
```bash
proj use <bundle-name>
```
never by a path -- see that bundle's own documentation for what it
contains.

## What flows and stages does WOLF know about?
```bash
wolf backend list
wolf backend info cadence-flowtool   # or: orfs
```
`wolf backend info` shows, for the backend an environment actually uses,
which local tools it found (`flowtool`, or the container runtime and image
for `orfs`) and whether each one validated. For Cadence Flowtool, the
stages themselves come from the active environment's own flow (the
bundled nine by default -- `syn_generic`, `syn_map`, `syn_opt`,
`floorplan`, `prects`, `cts`, `postcts`, `route`, `postroute` -- or more,
if a project flow package declares them); `wolf run --plan` lists the
exact names for an environment (see `skills/wolf-run-flow`).

To see the exact flow scripts one environment's run would use (not edit
them):
```bash
wolf flow snapshot <environment>
```
cuts a versioned, inspectable copy under
`<project root>/inputs/flows/<design>/`.

## Where do a design's own tunable keys live?
`<project root>/inputs/env/<design>/setup.<design>.yaml` -- a fully
commented file WOLF generates and keeps updated (see
`skills/wolf-new-environment` for how it's written, refreshed, and
extended by a project's own flow package). `wolf info`/`env describe`
don't show its contents; read the file itself, or `wolf env menu`.

## What does this skill not cover?
Creating or editing an environment (`skills/wolf-new-environment`); running a
flow (`skills/wolf-run-flow`); the vendor tool behind a backend (its own
documentation).

## Commands in this skill
* `wolf env list` -- read-only.
* `wolf info [<environment>]` -- read-only.
* `wolf env describe [<environment>] [--json]` -- read-only.
* `wolf backend list` -- read-only.
* `wolf backend info <name>` -- read-only.
* `wolf flow snapshot [<environment>]` -- read-only on the live environment;
  writes a new versioned copy under the project's own `inputs/flows/`
  (never outside the project).
* `proj module add application <name> --env <project>` -- adds a module
  to that project's own environment (an ordinary, unprivileged `proj`
  command; not read-only). Only applies if your site uses `proj`.
* `proj use <bundle-name>` -- adds a library/toolkit bundle to that
  project's own environment (ordinary, unprivileged; not read-only). Only
  applies if your site uses `proj`.

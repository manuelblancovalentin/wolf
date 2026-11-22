---
name: wolf-new-environment
description: Use when you need to create a new WOLF environment for a project, or adapt an existing one -- what commands to run and which files a person edits.
---

# Creating or adapting a WOLF environment

Verified 2026-11-22 with WOLF 0.1.0.

## How do I create a new environment?
Write a small YAML file and import it (invented names below; use your own
project, design, and the process bundle your project already has):

```yaml
# demo.yaml
schema: wolf.environment/v1
name: demo
design:
  name: demo
  sources: [{path: /path/to/project/inputs/hdl/demo/demo.sv}]
technology:
  package: pdk/<name>   # the process package your project added, see below
  track: 9T
  vth: rvt
flow:
  backend: cadence-flowtool   # or: orfs
project:
  root: /path/to/project
constraints:
  files: [/path/to/project/inputs/constraints/demo/demo.sdc]
```

```bash
wolf env create demo --from demo.yaml
wolf info demo   # confirm it resolves; "Environment is partial" names what's missing
```

## How do I get the process library added first?
The process library is never a path or a file name in this skill -- it is
a named bundle. If your site uses `proj` (or a similar tool) to manage
libraries per project, that is where you add it:
```bash
proj use <bundle-name>
```
The package it refers to (`pdk/<name>` above) is made once, by the project
owner, in `wolf pdk menu`; you reference it by name, you do not create it.

## How do I adapt an existing environment instead of starting from scratch?
```bash
wolf env clone <source> demo2
```
makes an independent copy. Then change one design-level knob at a time:
```bash
wolf env set demo2 active_views '{"setup": ["func_setup"], "hold": ["func_hold"]}'
wolf env unset demo2 active_views
```
`wolf env set`/`unset` write to that design's own `setup.<design>.yaml`
under the project's `inputs/env/<design>/`, never to your home folder. A
key that is environment-level instead (for example `constraints.clocks.0.
period_ps`) is written into the environment's own `wolf.yaml` -- `wolf env
set` decides which file by the key itself, you do not pick. `wolf env menu`
opens the same editing interactively if you would rather not hand-write a
key path.

## How do I scaffold the project's folders for it?
```bash
wolf env auto-setup demo
```
creates every missing standard directory under the project root once:
`inputs/{calibre,constraints,env,floorplans,flows,hdl,scripts,tb}/<design>/`,
`inputs/lib/{gds,lef,spice,timing,verilog}/`, `outputs/`, `workspace/`.
Anything already there is reported "already present", not overwritten.

## What does this skill not cover?
Making the `pdk/<name>` package manifest itself, or the library/kit content
behind it (the project owner's job, in `wolf pdk menu`); running the
environment once it exists (`skills/wolf-run-flow`); listing or describing
environments that already exist (`skills/wolf-environments`).

## Commands in this skill
* `wolf env create <name> --from <file>` -- not read-only (writes under
  `~/.wolf/envs/<name>`).
* `wolf env clone <source> <destination>` -- not read-only.
* `wolf env set [<name>] <key> <value>` / `wolf env unset [<name>] <key>` --
  not read-only (writes `wolf.yaml` or the design's own
  `setup.<design>.yaml`, never outside the environment/project).
* `wolf env auto-setup [<name>]` -- not read-only (creates directories
  under the project root; never overwrites an existing one).
* `wolf env menu [<name>]` -- not read-only; interactive.
* `proj use <bundle-name>` -- not read-only; adds a library/toolkit bundle
  to the project. Only applies if your site uses `proj`.

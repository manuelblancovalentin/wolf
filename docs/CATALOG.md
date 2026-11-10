# The catalog

`wolf catalog --json` prints one machine-readable document describing
WOLF's own canonical concepts: variables, supported processes, the
`choice`-typed variables' allowed values, flow stages per backend, and
every command WOLF accepts. It is generated from WOLF's own code
(the real argparse command tree, the real backend/stage definitions) and
documentation each time it runs, so it cannot drift from what the
installed WOLF actually does.

Run it without `--json` for a short human-readable summary (counts per
section); `--json` is the form meant for another tool to read.

## Schema: `wolf.catalog/v1`

```json
{
  "schema": "wolf.catalog/v1",
  "wolf_version": "0.1.0.dev1",
  "variables": [...],
  "processes": [...],
  "choices": {"metal_stack": [...], "vth": [...]},
  "flows": [...],
  "commands": [...]
}
```

### `variables`

One entry per canonical variable (`DESIGN_NAME`, `PROCESS`, `METAL_STACK`,
`PROJ_DIR`, `VTHS`, `TRACKS`, `CONSTRAINTS_FILE`, `WORKSPACE_DIR`):

| Key | Meaning |
|---|---|
| `name` | The variable's name. |
| `meaning` | One sentence describing what it is. |
| `type` | `text`, `choice`, `list`, or `path`. |
| `source` | Where the value is expected to come from: `user`, `profile bucket`, or `per-design bucket`. |
| `required` | Whether a run needs it. |
| `scope` | `per-design` or `per-project`. |
| `example` | A non-sensitive example value, or `null` for a `path` variable (paths are described by meaning only, never by example value). |
| `visibility` | `public` or `internal` (see below). |
| `since` | The WOLF version this entry was last confirmed under. |

### `processes`

One entry per process node WOLF has bundled backend assets for. `name` is
the identifier a user writes (e.g. in `PROCESS=`); `purpose` is one line.
`gating_group` and `proj_bundle` are present in the schema for a future
mapping to the Unix group and `proj` bundle that gate/provide a process --
WOLF's own code does not track that mapping yet (it lives in `proj`), so
both are `null` today rather than guessed.

### `choices`

Allowed value names for the `choice`-typed variables (`metal_stack`,
`vth`). Both lists are empty today: no package in WOLF's own registry
declares more than one metal stack or vth option yet, so there is no real
list to publish without reading content this catalog deliberately never
looks at (see the release report for why). A future catalog version fills
these in once a tracked PDK package declares them.

### `flows`

One entry per backend (`cadence-flowtool`, `orfs`): its one-line purpose
and its stages in execution order, each tagged with the tool suite that
runs it (Cadence Genus / Cadence Innovus / Yosys / OpenROAD).

### `commands`

Every command WOLF's real CLI accepts (`wolf <command>` or
`wolf <group> <command>`), each with its one-line help text, walked
directly from the installed `argparse` tree -- this list cannot list a
command WOLF doesn't actually have, or omit one it does.

## Visibility

Every item in `variables` and `processes` carries `visibility`:

- `public` -- safe for the public-facing site.
- `internal` -- shown only to signed-in lab members. Anything a foundry
  could consider confidential is marked `internal`; this currently covers
  `METAL_STACK`/`VTHS`/`TRACKS`'s own values and the three Cadence-backed
  process entries (`tsmc65`, `tsmc28`, `gf22`). The public bible tooling
  should filter on this field rather than hand-maintaining its own list.

## For the website agent

Read the catalog with `wolf catalog --json` (or import
`wolf.catalog.build_catalog()` directly from Python if you're running in
the same environment). Filter every `variables`/`processes` entry to
`visibility == "public"` before rendering the public site; render
everything for a signed-in lab member. Nothing in this document needs a
PDK or library tree to be read, and regenerating it never requires one
either -- if a future version needs real metal-stack/vth choice names, that
will land as a change to `wolf.catalog`, not something the website should
try to infer itself.

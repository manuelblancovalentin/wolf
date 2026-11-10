# The run digest and environment description

Two small files, both written by wolf, both safe for a website's scan to
read directly -- the scan should never run `wolf`, and never open a
report or log file itself.

## `wolf.digest.json` -- schema `wolf.digest/v1`

Written atomically into the run folder (`<run_directory>/wolf.digest.json`)
after every stage attempt and once more when the run ends, and, when the
environment's project root is known, a second real copy (never a link)
at `<project_root>/shared/wolf-digests/<design>.<run_number>.json`. At
most 64 KB.

```json
{
  "schema": "wolf.digest/v1",
  "wolf_version": "0.1.0.dev1",
  "design": "bin_to_therm_dec",
  "process": "gf22",
  "metal_stack": "M9",
  "run_number": "3",
  "started_at": "2026-11-09T12:00:00Z",
  "ended_at": null,
  "stages": [
    {"name": "syn_generic", "status": "succeeded", "attempts": 1, "elapsed_seconds": 120.0, "inferred": false},
    {"name": "postroute", "status": "failed", "attempts": 3, "elapsed_seconds": 900.0, "inferred": false}
  ],
  "metrics": [
    {"name": "total_area_um2", "value": 12345.6, "unit": "um2", "stage": "postroute"},
    {"name": "total_real_seconds", "value": 3600.0, "unit": "s", "stage": null}
  ],
  "checks": {
    "drc": {"status": "pass", "violations": 0},
    "lvs": {"status": "fail", "violations": 2}
  }
}
```

### Fields

| Field | Meaning |
|---|---|
| `design`, `process`, `metal_stack` | The run's resolved identity. `metal_stack` is `null` when the technology package has none. |
| `run_number` | The run's own numbered suffix (`<design>.<N>`'s `N`), as a string. |
| `started_at`/`ended_at` | ISO-8601 UTC. `started_at` is fixed at the run's first stage and never moves on a later continuation; `ended_at` is `null` until the run's own invocation finishes. |
| `stages[].status` | One of `pending`, `running`, `succeeded`, `failed`, `skipped`. |
| `stages[].attempts` | How many times Flowtool (re)ran this stage, counted from file names in `flow.status.d/` alone -- `0` for a stage never reached, `1` for one clean pass, more for each retry. A stage whose status is non-pending but whose backend never writes `flow.status.d` (an older Flowtool, or a non-Cadence backend) shows `1`, never a guessed higher number. |
| `stages[].inferred` | `true` when this stage's status came from the tolerant, older-flow-revision fallback (matching the stage name as a component of a `flow.status` step path, rather than an exact match against the currently bundled flow's own step tree) -- a run predating today's Python backend typically shows this. `false` for an exact match. |
| `metrics[]` | `{name, value, unit, stage}` -- `stage` is `null` for a run-level metric. `name` is always one of a closed, wolf-owned vocabulary (see below); nothing else is ever added without a name here first. |
| `checks.drc`/`checks.lvs` | `{status: "pass"|"fail", violations: <count>}`, present only when wolf actually found and parsed a check report; absent, not guessed, otherwise. Looked for only in the run directory's own `*.geom.rpt` (drc) / `*.conn.rpt` (lvs) -- Innovus's own verifyGeometry/verifyConnectivity reports, confirmed real names and locations. `reports/DRC/`/`reports/LVS/` are deliberately not scanned: confirmed real for this flow that `reports/DRC/` holds unrelated timing/netlist checks and `reports/LVS/` is empty. Calibre's own `calibre/<stage>/{drc,lvs,fill}` is a known second real source not covered yet -- its file names aren't known. The geom.rpt clean case ("No DRC violations ... found") and both conn.rpt shapes (a "N total violation(s)" summary, or counted "Net ..." lines when no summary is present) are confirmed real; a nonzero geom.rpt is still an unconfirmed best-effort guess at the shape. Run `tools/wolf_digest_selfcheck.py` against a real run to check this. |

### Closed metric vocabulary (today)

`total_real_seconds` (s), `total_cpu_seconds` (s), `memory_resident_mb`
(MB), `memory_resident_peak_mb` (MB), `setup_violations` (count),
`hold_violations` (count), `max_slew_violations` (count),
`max_cap_violations` (count), `max_fanout_violations` (count),
`cell_count` (count), `total_area_um2` (um2), `worst_slack_ps` (ps),
`total_negative_slack_ps` (ps), `failing_endpoints` (count),
`total_power_w` (W).

### Never in it

Absolute paths, library or cell names, instance or net names, log text,
user names, host names, license information. Confirmed by test: a
library-shaped string planted in a synthetic report never reaches the
digest, only the derived count.

## `wolf.<environment>.description.json` -- schema `wolf.describe/v1`

A real file (never a link) next to the environment's own definition:
`<project_root>/inputs/env/<design>/wolf.<environment>.description.json`.
Refreshed on `wolf env set`/`unset` and printed on demand by
`wolf env describe <name> [--json] [--file wolf.yaml]`.

```json
{
  "schema": "wolf.describe/v1",
  "environment": "demo",
  "design": "demo_design",
  "process": "demo_process",
  "metal_stack": "M9",
  "variables": {
    "DESIGN_NAME": "demo_design",
    "VTHS": "rvt",
    "CONSTRAINTS_FILE": "<library>",
    "SOME_OTHER_PATH": "hidden"
  },
  "activation_commands": ["wolf activate demo", "wolf run"]
}
```

Each variable's value is made safe by wolf itself, never by the reader:
a value that points into a library/PDK tree becomes the literal marker
`"<library>"`; an absolute path inside the project becomes
project-relative; anything else is shown only if it matches
`^[A-Za-z0-9_.+-]{1,64}$` (short identifiers, numbers, simple relative
tokens); everything else becomes the literal string `"hidden"`, with no
part of the real value. `activation_commands` is the exact, literal pair
of lines a person types to activate and work with the design.

## For the website agent

Read both files by their exact names, as plain JSON -- never run `wolf`,
never follow a path inside either file, never open a report or log
yourself. `wolf.digest.json` may be read mid-run (`ended_at: null`);
treat that as normal, not an error. The `shared/wolf-digests/` copy
exists specifically so a digest is readable without crossing into
another member's own run folder.

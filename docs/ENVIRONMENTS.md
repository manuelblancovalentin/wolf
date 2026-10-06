# WOLF environments

WOLF supports a versioned declarative environment alongside the existing
legacy `vars.env` format. An environment is a named, mutable, optionally
partial configuration profile. A resolved run context is complete and records
the explicit backend and package provenance used for execution.

## Declarative v1

Create a profile from YAML with:

```bash
wolf env create ibex-asap7 --from wolf.yaml
```

The CLI name is authoritative. If an input `name` is present and differs from
the CLI name, creation fails without leaving a partial environment. The stored
profile uses schema marker `wolf.environment/v1`:

```yaml
schema: wolf.environment/v1
name: ibex-asap7
design:
  package: rtl/ibex
technology:
  package: pdk/asap7
flow:
  package: flow/orfs
workspace:
  root: /projects/eda-work
constraints:
  clocks:
    - name: core_clock
      port: clk_i
      period_ps: 1050
resources:
  threads: 16
backend:
  orfs:
    make:
      SWAP_ARITH_OPERATORS: ""
      OPENROAD_HIERARCHICAL: 0
env:
  GENUS_NUM_CPUS: "64"
```

Phase 1 accepts `name`, `design`, `technology`, `flow`, `project`, `workspace`,
`constraints`, `resources`, `backend`, and `env`. Unknown fields and
unsupported schema versions are errors. Design, technology, and flow package
references must use the corresponding `rtl`, `pdk`, and `flow` package kinds.

### Composing design sources from more than one place

`design.package` names a single installed `rtl` package as the whole source
list, as above. A design can instead be assembled from several places with
`design.sources`, a list where each entry is either a portable package
reference or a local path:

```yaml
design:
  name: mixed
  top: foo
  sources:
    - package: rtl/ibex
    - path: extra/foo.sv
```

Each entry sets exactly one of `package` or `path`. A `package` entry is
fully portable: installing that same package anywhere reproduces it. A
`path` entry is not -- it names a file on this machine, outside any package,
and is not carried along when the environment is cloned or shared. `path` is
resolved the same way other stored paths are: relative to the profile's own
directory, made absolute on import. When `design.sources` is present it
replaces `design.package`'s source resolution entirely; `design.sources`
carries no implicit name or top, so set `design.name` (and `design.top` if
needed) explicitly alongside it.

## Project directory structure

`project.root` names a project directory holding this environment's
`inputs/`, `outputs/`, and `workspace/` -- the same three-directory shape
regardless of backend (Cadence Flowtool or ORFS), so a project doesn't
reorganize when it switches tools:

```yaml
project:
  root: /home/you/my-project
```

When set, `workspace.root` defaults to `<project.root>/workspace` and need
not be given explicitly; an explicit `workspace.root` always wins if both are
present. `wolf env auto-setup [NAME]` scaffolds the directories a design's
inputs are conventionally expected under:

```text
<project.root>/
  inputs/
    calibre/<design>/      constraints/<design>/   env/<design>/
    floorplans/<design>/   hdl/<design>/           scripts/<design>/
    tb/<design>/
    lib/{gds,lef,spice,timing,verilog}/   (shared across designs)
  outputs/<design>/
  workspace/
```

It only creates directories -- no PDK- or flow-specific files -- is safe to
run repeatedly (existing directories are left untouched and reported as
"already present"), and requires `project.root` plus a resolvable design name
(`design.name` or an installed `design.package`) but nothing else, so it can
run before any technology or flow package is chosen.

`constraints.clocks` and the optional `constraints.floorplan_def` (a
physical-aware Cadence Genus flow's placed floorplan DEF; see
[Physical views, floorplan DEF, and MMMC](CADENCE_GENUS.md#physical-views-floorplan-def-and-mmmc))
are the only recognized `constraints` fields.

`env` is a plain string-to-string map, unrelated to `resources` (which is
about allocation, e.g. thread count). WOLF core has no opinion on what any
key means: `wolf run` merges the map, untouched, into whatever subprocess the
selected backend execs, and `wolf activate`/`wolf deactivate` export and
restore the same map in the interactive shell (see
[CLI reference](CLI.md#active-environments)). Keys must be valid environment
variable names (`[A-Za-z_][A-Za-z0-9_]*`); values must be strings.

Package metadata supplies semantic defaults. For the built-in packages these
include Ibex's design name/top, ASAP7's technology name, and ORFS's flow/backend
identity. Explicit values in the environment override package defaults. CLI
run overrides have final precedence. The resolved context retains each
package's pinned revision.

## Partial profiles and paths

A profile may omit design, technology, flow, backend, or workspace. `wolf info`
loads it and reports unresolved fields. `wolf run` requires a complete context
and fails clearly otherwise. A package design can complete a partial profile:

```bash
wolf run --environment asap7-orfs --design rtl/ibex --plan
```

Execution location does not define experiment location. Relative paths in an
imported YAML file resolve from that file's directory and are stored in
canonical form. Explicit relative `--workspace` values resolve from the caller's
directory for that invocation. Package roots come from installed records.

## Native ORFS and compatibility mode

For a complete package-backed ORFS profile, WOLF generates a deterministic
`config.mk`, clock SDC, and `wolf.resolved-run/v1` planning manifest under
`WOLF_HOME/generated/environments`. The adapter uses package RTL, canonical
design/platform identity, canonical clock and thread values, and explicit
`backend.orfs.make` overrides. Generated files and RTL are mounted read-only;
ORFS `WORK_HOME` is mounted at the WOLF run directory so results do not modify
the installed flow package.

Native ORFS design collateral is used when
`flow/designs/<platform>/<design>/config.mk` exists. For an external RTL
package without that directory, WOLF instead creates a deterministic minimal
base Makefile containing the resolved platform and layers the same canonical
overrides on top. This lets arbitrary validated RTL packages use the
declarative backend without adding their sources to the ORFS checkout. The
generated base file and its source (`native`, `explicit`, or `generated`) are
recorded in the resolved manifest.

`backend.orfs.design_config` is an escape hatch for an existing native ORFS
config and takes precedence over native or generated base configuration. If an
explicit path is supplied but missing, preparation fails clearly. Legacy
`ORFS_DESIGN_CONFIG`, `ORFS_SDC_FILE`, and other variable inputs remain
supported. Backend-native Make knobs are not promoted into canonical WOLF
fields.

Planning uses a deterministic generated manifest without allocating a physical
run. During real execution, the exact allocated run receives an immutable
`wolf.resolved.yaml` before backend files are materialized or stages start.
Generated backend files are then associated with paths recorded in that frozen
snapshot. Failed runs retain both the directory and manifest. Reusing a run
with different resolved provenance is rejected rather than overwriting history.

## Editing, cloning, and legacy compatibility

`wolf env menu [name]` is the interactive, full-coverage way to build or edit
a profile -- RTL sources, design name/top, technology (PDK package, track/
vth, and metal stack for a tracked package), flow/backend, constraints (SDC
files), project root, and an optional workspace root override, each picked
from what's actually declared elsewhere (a tracked PDK's own track/vth
names, its metal stacks) rather than typed blind. Browsing for a project or
workspace root that doesn't exist yet can create it on the spot (`n`), a
real `mkdir` right away, not deferred to save.

Project root comes first in the wizard and gates everything else -- every
other field stays visible but unselectable until it's set, since RTL
sources, constraints, and workspace all ultimately resolve relative to it.
Setting it to a directory that already exists always triggers a scan (see
`wolf.project_tree`, never skipped, even for an empty directory) against the
same `inputs/{calibre,constraints,env,floorplans,hdl,lib,scripts,tb}`
convention `wolf env auto-setup` itself scaffolds -- each category's own
per-design subdirectory (or, for `constraints` specifically, a flat
`<design>.<anything>` file -- both shapes are accepted) suggests a design
name. Picking one out of the scan prefills RTL sources, design name/top,
and constraints in the wizard's own in-memory state; nothing is written to
`wolf.yaml` until Save, same as every other field here. Declining (`esc`,
or nothing found) leaves project root set with everything else still to
fill in by hand.

Saving also copies any RTL source that isn't already living under
`<project_root>/inputs/hdl/<design_name>/` into that directory, rewriting
the stored path to the copy -- a source added by browsing to some file
elsewhere ends up owned by the project, not left pointing outside it. And
whenever project root exists and a design name is known, saving scaffolds
every missing standard directory for it (`wolf.project_tree.
scaffold_project_tree`, the same convention `wolf env auto-setup` itself
creates) -- a project the scan found only partially populated (hdl there,
constraints not written yet, say) gets the rest filled in automatically,
not left as a diagnosis you have to act on by hand with a separate
`wolf env auto-setup` call. Two of those directories also get populated,
not just created: a design with no `constraints.files` set yet gets a
starter SDC at `inputs/constraints/<design>/<design>.sdc` (common
directives present but commented out -- `create_clock`, I/O delays, loads
-- to fill in and uncomment, matching the role a hand-maintained template
played in the legacy tree this was modeled on), wired into
`constraints.files` automatically; and saving always refreshes a copy of
this environment's own `wolf.yaml` at
`inputs/env/<design>/wolf.<environment_name>.yaml`, so the configuration
behind a given project tree (which RTL, which PDK/track/vth, which
constraints) is readable right there on disk, without `~/.wolf/envs/` at
all -- the same role the legacy tree's own `<design>.src.yaml` played,
except always in sync with the real source of truth instead of a second,
driftable copy.

The Technology entry opens a submenu (PDK package, then track, then vth(s),
then metal stack) that stays open across all four picks and shows each
one's current value -- escape applies whatever's set so far to the main
menu, rather than bouncing back there after every single pick. Track and
vth are picked separately, not as one combined choice: vth is a checklist
(`enter` toggles, `esc` finishes), since a real run commonly mixes more
than one vth's library set in the same synthesis so Genus can pick cells
from whichever fits a given path (confirmed real usage: a legacy
`vths: ${VTHS}` setup.yaml token, `VTHS` a bash array). `technology.vth` in
`wolf.yaml` accepts either one name or a list -- a single string is exactly
the one-element-list case, so every existing single-vth environment is
unaffected. Metal stack only offers stacks declared for *every* selected
vth (the intersection, not the union), so whatever's picked is guaranteed
valid for the whole selection.

`q`/escape at the top level asks for confirmation (defaulting to No)
whenever there are unsaved changes; a plain enter or a second escape on
that prompt cancels the quit and returns to the main menu, only an
explicit move to Yes exits.

Profiles also remain human-readable and may be edited directly. A narrow
structured setter updates existing paths:

```bash
wolf env set ibex-asap7 constraints.clocks.0.period_ps 1100
wolf env set ibex-asap7 env.GENUS_NUM_CPUS 64
wolf env clone ibex-asap7 ibex-asap7-1100
```

Clone creates an independent declarative profile and does not duplicate
installed packages. Phase 1 cloning supports declarative-v1 profiles only.
Legacy profiles are detected by the absence of `wolf.yaml`, resolve through the
compatibility adapter, display `Format: legacy`, and are never rewritten
destructively.

`env.KEY` follows the same convention as `constraints.clocks.0.period_ps` or
`backend.orfs.make.KEY`: it sets a leaf under an already-existing structured
path. If the environment has no `env:` block yet, set the whole block first
(`wolf env set ibex-asap7 env '{}'`), then set individual keys under it.

## Defaulting to the active environment

`wolf activate <environment>` (via the Bash/zsh integration) sets
`WOLF_ACTIVE_ENV` in the current shell. Every subcommand that accepts an
environment name — `run --environment`, `info`, `status --environment`,
`env set`, `env clone` (as the clone source), and `env remove` — falls back
to `WOLF_ACTIVE_ENV` when the argument is omitted; an explicitly given name
always wins. If nothing is active and no name is given, the command fails
clearly rather than guessing:

```bash
wolf activate ibex-asap7
wolf info                              # same as: wolf info ibex-asap7
wolf env set env.GENUS_NUM_CPUS 64     # same as: wolf env set ibex-asap7 env.GENUS_NUM_CPUS 64
wolf run --plan
```

`wolf env remove` still requires deactivating the environment first if it
happens to be the active one — the fallback composes with that existing
safety check rather than bypassing it.

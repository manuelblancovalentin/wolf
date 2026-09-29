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

Phase 1 accepts `name`, `design`, `technology`, `flow`, `workspace`,
`constraints`, `resources`, `backend`, and `env`. Unknown fields and
unsupported schema versions are errors. Design, technology, and flow package
references must use the corresponding `rtl`, `pdk`, and `flow` package kinds.

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

Profiles remain human-readable and may be edited directly. A narrow structured
setter updates existing paths:

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

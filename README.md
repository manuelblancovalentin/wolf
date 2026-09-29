# WOLF

WOLF is a reproducible, technology-agnostic environment manager and execution
layer for digital implementation flows. It describes an ASIC experiment once,
then resolves its design, technology, flow, packages, backend configuration,
execution environment, and provenance.

WOLF exists because an implementation run should not overwrite its history or
depend on the directory from which a command happened to be launched. It keeps
numbered runs, immutable resolved manifests, snapshots, logs, artifacts, and a
small semantic status view while delegating synthesis and physical design to
established flow ecosystems.

## Quick demo

Install WOLF from a clone:

```bash
python3 -m pip install -e .
wolf --version
wolf init
```

Install the built-in, pinned packages and create an environment from
[`examples/ibex-asap7-orfs/wolf.yaml`](examples/ibex-asap7-orfs/wolf.yaml):

```bash
wolf install flow/orfs
wolf install rtl/ibex
wolf install pdk/asap7
wolf env create ibex-asap7 --from examples/ibex-asap7-orfs/wolf.yaml
wolf activate ibex-asap7
wolf run --plan
wolf run -y
wolf status
```

The example uses a 1050 ps clock and the Ibex, ASAP7, and ORFS packages. A
WOLF environment is configuration, not a Python virtual environment. Activation
selects configuration and does not change directory. Execution location does
not define experiment location.

## Mental model

```text
Registries → Packages → Environment → Resolver → RunContext
                                                   ↓
                                              Backend → Executor
                                                   ↓
                                       numbered run / provenance / results
```

Canonical concepts such as design, top, technology, clocks, workspace, and
stage range are translated by the selected backend into native flow inputs.
ORFS-specific options remain explicit backend overrides.

WOLF does not replace ORFS or Flowtool. An ORFS run is:

```text
WOLF semantic configuration → ORFS backend → ORFS → Yosys/OpenROAD
```

Cadence Flowtool is supported through a compatibility backend. Current support
is intentionally evolving: ORFS is validated with the golden case below,
while Cadence remains an important compatibility target.

## Environments, runs, and reproducibility

An environment is a named, mutable configuration profile. A resolved RunContext
is complete and is frozen into `wolf.resolved.yaml` in the allocated numbered
run. `wolf status` records evolving execution state separately.

Typical output layout:

```text
<workspace>/ibex/ibex.asap7/ibex.1/
  wolf.resolved.yaml
  wolf.stage-results
  backend/orfs/config.mk
  backend/orfs/constraints.sdc
  logs/  reports/  results/
```

Numbered runs preserve historical implementations; `.latest` links provide
convenient access. The resolved manifest records package revisions, backend,
constraints, paths, runtime, and generated configuration so the run remains
understandable without WOLF's operational state.

`wolf info` describes the active environment and resolved configuration.
`wolf status` describes the latest run's execution and results. Use
`wolf status --json` for automation.

## Packages and registries

The built-in registry currently provides `rtl/ibex`, `rtl/aes`, `pdk/asap7`, and
`flow/orfs`. Package sources are pinned and installed under WOLF-managed data
paths, separate from workspaces.

```bash
wolf package list
wolf package info rtl/ibex
wolf registry list
wolf registry add lab /path/to/registry
wolf install rtl/ibex
```

Local and Git registries are supported for institutional or private manifests.
WOLF does not store Git credentials; authentication remains Git's
responsibility. See [Packages](docs/PACKAGES.md) and [Registries](docs/REGISTRIES.md).

## How to

Short, self-contained recipes for common tasks. Each assumes a working WOLF
install (`wolf --version` succeeds).

**Install an open-source PDK package.**

```bash
wolf install flow/orfs
wolf install pdk/asap7
wolf package info pdk/asap7
```

`pdk/asap7` is a `package-path` view into the pinned `flow/orfs` checkout —
open collateral, safe to fetch and commit a manifest for in `registry/`.

**Register a licensed or otherwise host-local PDK.**

Licensed PDKs live on institutional infrastructure and must never be fetched
by WOLF or committed to `registry/`. A `local-path` package source instead
references an already-resident absolute directory as-is:

```yaml
# /somewhere/not/in/git/local-registry/pdk/tsmc65.yaml
schema_version: 1
kind: pdk
name: tsmc65
description: Site-local TSMC 65LP digital timing libraries
source:
  type: local-path
  root: /path/to/institutional/pdk/root
  revision: site-label-or-version
metadata:
  technology:
    name: tsmc65
    timing:
      corner: typical
      libraries:
        - relative/path/to/typical.lib
```

```bash
wolf registry add site-pdk /somewhere/not/in/git/local-registry --type local
wolf install pdk/tsmc65
wolf env set my-environment technology "{package: pdk/tsmc65}"
```

See [Packages](PACKAGES.md) for the full `local-path` schema.

**Create and customize a flow without forking the shared base.**

```bash
wolf flow init my-flow \
  --from /path/to/shared/base/flow \
  --to /path/to/my-project-repo/wolf/flows/my-flow \
  --manifest /path/to/my-project-repo/wolf/registry/flow/my-flow.yaml \
  --backend cadence-flowtool \
  --revision "$(git -C /path/to/my-project-repo rev-parse HEAD)"
```

Edit anything under `--to` freely — cell lists, steps, whatever the project
needs — then commit it inside your own project repo. See [Flows](FLOWS.md).

**Add a flow or PDK registry and install from it.**

```bash
wolf registry add my-flows /path/to/my-project-repo/wolf/registry --type local
wolf registry list
wolf install flow/my-flow
```

**Pass an environment variable through to a run, and to your activated shell.**

```yaml
env:
  GENUS_NUM_CPUS: "64"
```

```bash
wolf env set my-environment env '{}'   # once, if the environment has no env: block yet
wolf env set my-environment env.GENUS_NUM_CPUS 64
wolf run --environment my-environment  # GENUS_NUM_CPUS reaches the backend's subprocess
wolf activate my-environment           # GENUS_NUM_CPUS is exported in this shell too
wolf deactivate                        # restored (or unset) automatically
```

WOLF core never interprets these keys; they pass through untouched to
whatever the backend execs.

**Omit the environment name once it's active.**

```bash
wolf activate my-environment
wolf info                 # same as: wolf info my-environment
wolf run --plan           # same as: wolf run --environment my-environment --plan
wolf env set env.FOO bar  # same as: wolf env set my-environment env.FOO bar
```

An explicitly given name always overrides the active one; if nothing is
active and no name is given, the command fails clearly rather than guessing.

**Override a single backend-native Genus attribute without forking a flow.**

```yaml
backend:
  cadence-flowtool:
    genus:
      set_db:
        hdl_max_memory_address_range: 65536
```

See [Genus attribute overrides](CADENCE_GENUS.md#genus-attribute-overrides).

## Configuration and setup

`wolf init` creates persistent XDG-style configuration and can explicitly
install an idempotent Bash or Zsh integration hook. `wolf config list` shows
the effective paths and runtime preference. Users normally do not need to set
`WOLF_HOME`; it remains available as a compatibility/testing override.

```bash
wolf config list
wolf env list
wolf backend list
wolf doctor
```

See [Configuration](docs/CONFIGURATION.md), [Environments](docs/ENVIRONMENTS.md),
and [CLI reference](docs/CLI.md).

## Validated golden case

The package-backed Ibex/ASAP7/ORFS reference flow completes synth through finish
under rootless Podman. The validated result is:

```text
worst setup slack     +13.31 ps
setup violations       0
hold violations        0
route DRC               0
max slew violations   64
max cap violations      0
max fanout violations   0
```

This is a reproducibility reference, not a universal performance claim. See
[the example](examples/ibex-asap7-orfs/README.md) and [ORFS documentation](docs/ORFS.md).

## Current support and limitations

| Capability | Status |
|---|---|
| Declarative environments | supported |
| Package registry and pinned installs | supported |
| ORFS backend | supported; golden validated |
| Cadence Flowtool backend | compatibility/legacy path |
| Ibex + ASAP7 | golden validated |
| AES + ASAP7 | validation run completed; timing not closed |
| Private/local registries | supported |
| Run provenance | supported |
| Run status and metrics | initial support |
| Dependency solving, remote registry service, full run database | not implemented |
| Multi-design/backend validation | AES second-design validation completed |

WOLF is an evolving development project. Interfaces, backend coverage, and
metric coverage may change as a second design and backend configuration are
validated.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Environments](docs/ENVIRONMENTS.md)
- [Packages](docs/PACKAGES.md)
- [Registries](docs/REGISTRIES.md)
- [Flows](docs/FLOWS.md)
- [Configuration](docs/CONFIGURATION.md)
- [ORFS backend](docs/ORFS.md)
- [Cadence Genus backend](docs/CADENCE_GENUS.md)
- [Testing](docs/TESTING.md)
- [Runnable example](examples/ibex-asap7-orfs/README.md)
- [Man page](docs/man/wolf.1)

Longer-term design topics are outlined in [the white-paper outline](docs/WHITEPAPER_OUTLINE.md).

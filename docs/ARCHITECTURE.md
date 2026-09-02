# WOLF Target Architecture

## Purpose and scope

WOLF is an EDA workflow and experiment environment manager. It composes independently defined design, technology, libraries, technology options, flow, backend, constraints, and user variables; resolves that composition for a run; preserves what was executed; and delegates tool-specific work to a backend.

A WOLF environment is an EDA experiment definition, not a Python virtual environment. WOLF is broader than either Cadence Flowtool or OpenROAD Flow Scripts (ORFS).

This document describes the target architecture. It is a direction for incremental migration, not a demand to replace the current Bash implementation at once.

## Architecture overview

```text
 Environment definition
          |
          v
      Resolver
          |
          v
      RunContext ----------------------+
          |                            |
          |                            +--> RunManager
          |                                 |-- run allocation and locking
          |                                 |-- snapshots and .latest links
          |                                 |-- manifests and provenance
          |                                 `-- SQLite operational state
          v
       Backend
       /     \
      v       v
 Cadence      ORFS
 Flowtool     Backend
 Backend      |
      |       |
      v       v
  Executor   Executor
      |       |
      v       v
 native /    container runtime
 local       (Docker or Podman compatible)
```

The resolved input model is:

```text
 Design + PDK/Technology + Libraries + Metal-stack/options
        + Flow + Backend + Constraints + Variables + Versions
                              |
                              v
                         RunContext
```

The execution and result model is:

```text
 Run
  `-- Execution(s)
       `-- Stage execution(s): pending | running | succeeded | failed | skipped
            |-- artifacts
            |-- metrics
            `-- logs
```

## Responsibility boundaries

### WOLF core

The core owns behavior that must be consistent across all EDA tools:

- environment definition, cloning, selection, and resolution;
- run identity, UUIDs, numbering, allocation, continuation, and locking;
- execution and stage-execution records;
- script/configuration snapshots and `.latest` links;
- human-readable provenance manifests;
- operational state and query indexes;
- artifact, metric, log, and status records;
- package discovery, installation, and local registration;
- portable subprocess and executor orchestration;
- user-facing CLI behavior and backend selection.

The core must not know how Flowtool constructs a Stylus flow or how ORFS performs synthesis, placement, routing, or finishing.

### Resolver

The resolver loads an environment definition and its referenced manifests, applies explicit user or host-local inputs, validates compatibility, and produces one fully resolved `RunContext`. Resolution must be deterministic from recorded inputs.

Backend identity is mandatory in the resolved context. A flow may advertise a default or a set of compatible backends, but it cannot leave the executed backend ambiguous.

The first implemented environment schema is `wolf.environment/v1`. It is a
deliberately small, versioned starting point; later schema growth must follow
real Cadence and ORFS needs rather than precede them.

### Run manager and state store

The run manager creates or continues a physical-design run, records executions, owns generic snapshots and links, and commits provenance/state transitions. It must support a run that accumulates stages without treating each invocation as a new physical-design identity.

The state store is an operational index, initially built with Python's `sqlite3` or a similarly thin layer. A heavy ORM is not justified unless later query and migration complexity demonstrates a need.

### Backend

A backend translates a resolved context into a tool-specific plan and executes its stages. The initial interface should remain close to:

```python
validate(context)
prepare(context, run)
stages(context)
run_stage(context, run, stage, passthrough_args)
```

The interface is deliberately small. It should evolve only when both `cadence-flowtool` and `orfs`, or another real backend, demonstrate a shared need.

Initial backends are:

- `cadence-flowtool`: compatibility backend for existing Flowtool/Genus/Innovus behavior;
- `orfs`: adapter to ORFS, which remains responsible for the Yosys/OpenROAD implementation flow.

WOLF must not copy ORFS algorithms or internal orchestration into its core.

### Executor

The executor controls where and how a backend command runs. It is independent of backend identity.

Examples:

- `ORFSBackend` with `ContainerExecutor`;
- `CadenceFlowtoolBackend` with `LocalExecutor` after sourcing an institutional setup;
- a future backend with `SlurmExecutor` or `LSFExecutor`.

Docker is not part of ORFS backend identity. A container executor should support an equivalent Podman runtime when possible. Proprietary environments are not required to be containerized.

## Domain model

Stable concepts should be represented by Python classes or dataclasses. Concrete assets should be represented by declarative data.

Likely data objects include:

- `Design`
- `PDK` or `Technology`
- `Library`
- `Flow` and `FlowStep`
- `Environment`
- `Run` and `RunContext`
- `Execution`
- `Artifact`
- `Constraints`
- source and version metadata

Likely services include:

- `Backend`
- `EnvironmentManager`
- `RunManager`
- `StateStore` or `RunStore`
- `PackageRegistry` and `PackageInstaller`
- `Executor`

Classes describe stable categories and behavior. Manifests describe instances. Ibex should be loaded as `Design(...)` and ASAP7 as `PDK(...)`; WOLF should not define `Ibex(Design)` or `ASAP7(PDK)` subclasses.

### RunContext

`RunContext` is the central resolved value object for execution. It contains the exact selected design and revision, PDK and revision, libraries, technology options, flow and revision, backend, constraints, resolved variables, and source/tool version information.

The context is immutable for a run once materialized. A changed resolved composition creates a new implementation run rather than silently changing the meaning of an existing run.

### Canonical and backend configuration

WOLF presents canonical semantic configuration for concepts that have shared
meaning: design identity and top module, RTL and include inputs, technology,
libraries, constraints, workspace, resources, stage range, flow, and backend.
Backends translate a resolved context into native Flowtool YAML/Tcl/SDC or ORFS
Make/config/SDC inputs. Native backend configurations may also be imported for
compatibility, and explicit backend overrides remain available for knobs such
as `OPENROAD_HIERARCHICAL` and `SWAP_ARITH_OPERATORS`. Backend-specific knobs
are not promoted into canonical WOLF state merely for symmetry.

## Environment model and shell integration

An **Environment** is a named, mutable, optionally partial configuration
profile. It may supply defaults for design, technology, libraries, flow,
backend, workspace, constraints, variables, and executor choices. It is not an
immutable `{design, technology, flow}` identity.

A **RunContext** is the complete, unambiguous resolved configuration for one
execution/run. Environments may be partial; RunContexts may not be. A changed
constraint or environment value may create a new resolved run without requiring
a new Environment; cloning remains an explicit user choice for a long-lived
named branch.

### Path resolution

**Execution location does not define experiment location. The
environment/resolved configuration does.** The caller's current directory must
not implicitly select a workspace, run directory, design source, technology,
flow, generated configuration, or output location.

WOLF distinguishes three roots:

- **WOLF state root** (`WOLF_HOME`, default `~/.wolf`) stores WOLF-owned state;
- **workspace root** is the user-selected destination for generated runs;
- **source/package roots** identify RTL, PDK, library, and flow assets.

Absolute paths remain absolute. Paths stored in a manifest resolve relative to
that manifest's directory; explicit relative CLI path overrides resolve from
the invocation directory and are canonicalized before execution. Imported
assets resolve from registered absolute roots. Backends derive generated and
output paths from the resolved context, never from `$PWD`.

The long-term source of truth is a declarative environment manifest. The current bucket mechanism remains a compatibility input during migration, but executable shell fragments should not remain the primary structured representation.

Declarative Phase 1 resolves package semantic defaults, environment values,
and explicit CLI overrides into the transitional `ResolvedContext`. Package
revisions and the explicit backend survive resolution. Native ORFS preparation
generates backend-owned Make/SDC inputs and a human-readable resolved planning
manifest; backend-native overrides remain a separate escape hatch. Legacy
`vars.env` profiles continue through an adapter without destructive conversion.

Institutional setup scripts may be referenced as native backend/executor inputs. They are not substitutes for recording the resolved WOLF environment.

The long-term primary CLI is a normal installed Python entry point:

```text
wolf run
wolf env create foo
wolf env clone foo bar
wolf info foo
wolf install rtl/ibex
wolf doctor
```

Activation is the exception that must affect the caller's shell. The public UX remains:

```text
wolf activate foo
wolf deactivate
```

A small automatically installed shell hook may cooperate with the Python CLI. Users should not normally need to type `eval "$(wolf ...)"`, initialize a shell manually, or understand the hook protocol.

The Bash integration changes the current shell minimally using explicit
`WOLF_ACTIVE_ENV` identity. Activation selects configuration only: it never
changes a working directory or opens a child shell. Deactivation restores the
original prompt and removes only WOLF-owned shell state.

## Run, execution, and stage semantics

A new or clean invocation creates a new run identity. Subsequent invocations may append stage work to that run:

```text
Run 42
 |-- Execution A: synth
 |-- Execution B: floorplan
 |-- Execution C: place, cts
 `-- Execution D: route, finish
```

An `Execution` records one invocation through a backend/executor. A stage execution records the lifecycle and result of one flow stage within that invocation. Execution history is append-only even when a run continues.

Known bugs are not compatibility behavior. Existing useful semantics—numbered runs, `.latest` links, UUID-addressable identity, stage ranges, snapshots, and continuation—are compatibility requirements.

## Provenance and persistence

### Human-readable manifests

Each run directory must eventually contain a portable resolved manifest sufficient to understand the run without WOLF or its database. It should record at least:

- run number and UUID;
- source environment identity;
- design, PDK, library, and flow identities and revisions;
- selected backend;
- tool and container versions or digests;
- constraints and resolved variables;
- planned and executed stages;
- executor, host, and relevant process/container identifiers;
- timestamps and source/version metadata.

Environment and package definitions are also human-readable manifests. These files are the authoritative reproducibility record and should be safe to archive with a run.

### SQLite operational state

SQLite provides efficient indexing and live operational state. Initial conceptual tables are:

- `environment`
- `run`
- `execution`
- `stage`
- `artifact`

Metrics, events, and packages may be added when real queries require them. The database may track status, timestamps, PIDs, container IDs, hosts, executors, and queryable metrics. It must be rebuildable or understandable from durable manifests and run contents; it is never the only provenance store.

State transitions and manifest writes should be atomic enough that interrupted runs remain diagnosable. Recovery must not rewrite successful historical execution records.

## Tracking and artifacts

PID files are a legacy transport, not the target model. Structured execution state should support local processes, containers, and later remote schedulers with fields such as backend, executor, stage, PID/container/job ID, hostname, start/end time, and status.

A future `wolf ps` may query this state. Its model must not assume that the executing process is local.

Artifacts, logs, reports, and metrics belong to a specific run, execution, and where applicable stage. Backend code identifies and interprets tool-specific outputs; the core records their generic identity and provenance.

## Packages and registry

The Phase 1 local package system supports RTL, PDK, and flow assets through a
trusted file-backed built-in registry. Generic `PackageManifest`, registry,
store, and installer behavior loads concrete assets from declarative YAML;
there are no per-Ibex, per-ASAP7, or per-ORFS classes. Installations use pinned,
versioned paths under `WOLF_HOME/packages`, retain human-readable installed
metadata, and remain distinct from implementation workspaces.

Git sources are staged, checked out at an exact revision, optionally initialized
with recursive submodules, validated, and atomically placed. Package views may
identify content owned by another pinned package without duplicating it. This
is how Phase 1 represents the ORFS-vendored ASAP7 platform while preserving an
independent `pdk/asap7` semantic identity.

Later categories may include libraries, backend/toolchains, and complete
examples or recipes. Registry entries should normally describe manifests,
recipes, checksums, licenses, and upstream sources rather than mirror every
artifact.

Public assets may be fetched automatically. Proprietary assets must be locally importable/registerable without upload or redistribution. No proprietary PDK or library content belongs in the WOLF repository or public registry.

Phase 1 intentionally omits dependency solving, version negotiation, updates,
uninstall, publishing, remote indexes, signing, and package discovery plugins.
See `docs/PACKAGES.md`.

## Architectural invariants

- The resolved run records one explicit backend.
- Backend and executor are independent choices.
- A run may contain multiple append-only executions and stage executions.
- A changed resolved composition cannot silently mutate an existing run's meaning.
- Human-readable manifests remain authoritative for reproducibility; SQLite is an operational index.
- Core run and environment behavior is tool-neutral.
- Execution location does not define experiment location.
- Environments may be partial; RunContexts may not be.
- Backend-specific dependencies, preparation, stages, commands, and result interpretation remain backend-local.
- ORFS remains the implementation-flow owner for Yosys/OpenROAD.
- Existing Cadence behavior is protected by characterization tests before extraction or migration.
- Host-specific configuration is an explicit local input or overlay, not an implicit hostname branch in core.
- Open-source toolchains prefer reproducible containers without requiring Docker specifically.
- Proprietary backends may use native institutional environments.
- The public activation UX does not expose shell implementation mechanics.
- Tool-native Tcl, SDC, and setup assets remain in their native languages.
- No proprietary PDK/library payload is committed or redistributed.
- New dependencies require demonstrated value.

## Portability boundary

WOLF core must not require Ubuntu/Debian, `apt`, a specific hostname or lab path, host-installed Yosys/OpenROAD, or Docker when Podman can provide an equivalent container interface. Fedora is a clean public-user development target. Northwestern/Fermilab Cadence systems remain compatibility and regression targets, not core defaults.

## Python and shell boundary

Python is the target for parsing, resolution, run allocation/locking, UUIDs, links, structured manifests, SQLite, provenance, package resolution, safe process/container orchestration, backend abstractions, and data-driven scaffolding.

Shell remains appropriate for changing the caller's environment, small institutional setup adapters, and concise wrappers whose interface is inherently shell-based. Tcl, SDC, and other tool-native files remain native. Migration is driven by correctness and testability, not by a goal of eliminating every shell file.

## Non-goals

- WOLF is not replacing ORFS.
- WOLF is not implementing synthesis, placement, routing, or signoff algorithms.
- WOLF is not a PDK redistribution service.
- WOLF is not requiring proprietary tool environments to be containerized.
- WOLF is not a Python virtual-environment manager.
- WOLF is not committing to cluster executors, a public registry, or a finalized manifest schema in the initial multibackend milestone.

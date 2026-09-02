# WOLF Incremental Roadmap

## Roadmap rules

This roadmap preserves working behavior while using two real backends to discover the correct abstraction. Phase labels express commitment and order, not dates.

- **NOW** is required before safely introducing a backend boundary.
- **NEAR TERM** delivers the multibackend milestone and the open-source golden case.
- **LATER** follows only after Cadence and ORFS have exercised the architecture.
- **POSSIBLE FUTURE** is explicitly speculative and is not a current product commitment.

Do not reorder this plan into a wholesale Python rewrite before ORFS exists.

## NOW

### Global configuration and registries

The installed CLI now has a small XDG-backed configuration store, a confirmed
first-use `wolf init` wizard, and explicit local/Git package registries. This
precedes the all-managed package smoke and any future configuration TUI.

UX hardening (shell detection, idempotent prompt markers, streamed package
progress, elapsed timing, semantic summaries, and backend-owned optional
metrics) is complete. A full `wolf status` view remains a later milestone.

### 1. Characterize behavior before changing it

Add tests around the behavior users and future backends depend on:

- numbered clean/new runs and continuation of existing runs;
- `.latest` links and UUID-addressable run identity;
- script/configuration snapshots and unchanged-snapshot reuse;
- environment creation, activation, deactivation, variables, and bucket ordering;
- design/process/library/flow composition;
- Cadence stage discovery, single-stage and range selection;
- command/argument forwarding, interactive stage sequencing, tracking, and failures;
- current history/provenance outputs.

Use temporary directories and fake tool commands where possible. Institutional Cadence integration tests may be separately gated, but core characterization must run without proprietary data.

Exit criterion: the important intended behavior in `docs/RECON.md` is executable as a regression suite, and tests distinguish intended behavior from known bugs.

### 2. Fix confirmed high-risk P0 defects

Fix narrowly, with regression tests, before structural extraction:

- cleanup operating outside the run directory;
- malformed/unsafe history serialization;
- ineffective `--design` handling;
- broken process creation inputs and validation flow;
- auto-setup error-path defects;
- ignored or unreliable Flowtool failure status;
- the unusable/truncated installer being presented as a release artifact.

Known bugs are not preserved for compatibility. Avoid unrelated cleanup in these changes.

Exit criterion: confirmed data-loss and run-record correctness risks are removed without changing intended Cadence workflows.

## NEAR TERM

### 3. Introduce the smallest backend seam

Add explicit backend identity and a compatibility backend named `cadence-flowtool`. Route existing Cadence preparation, stage discovery, and execution through an interface close to:

```python
validate(context)
prepare(context, run)
stages(context)
run_stage(context, run, stage, passthrough_args)
```

Keep core ownership of run identity, snapshots, links, history/provenance, and environment behavior. Do not redesign manifests, migrate all core logic, or generalize the interface speculatively during this phase.

Exit criterion: existing Cadence characterization tests pass through the adapter, and the resolved run identifies `cadence-flowtool` unambiguously.

### 4. Implement ORFS as the second backend

Integrate ORFS rather than reproducing its flow internals. Keep backend identity separate from execution: ORFS should initially prefer a reproducible container executor that can use Docker or Podman equivalently where practical.

Backend-local responsibilities include dependency validation, ORFS configuration preparation, stage exposure, command construction, and interpretation of ORFS reports/results. Core behavior remains unchanged.

Exit criterion: WOLF can prepare and launch an ORFS run through the same small backend seam without Cadence-specific branches entering generic run management.

### 5. Establish the golden Ibex + ASAP7 regression

Reproduce the known-good research baseline:

- Ibex RTL;
- ASAP7;
- ORFS/Yosys/OpenROAD;
- 1050 ps clock period;
- `SWAP_ARITH_OPERATORS` disabled;
- `OPENROAD_HIERARCHICAL=0`;
- complete RTL-to-GDS execution.

Required outcome:

- zero setup violations;
- zero hold violations;
- clean OpenROAD detailed-route DRC report;
- complete successful flow.

Approximately +14.7 ps worst final setup slack is a reference, not a bit-exact requirement. Small nondeterministic timing changes are acceptable if timing remains clean. Residual max-slew violations are recorded but are not blockers for this baseline.

The regression must pin or record tool/container, RTL, PDK, flow, configuration, and constraint versions so failures can be interpreted.

Exit criterion: a repeatable WOLF invocation produces a human-readable resolved run record and machine-checked timing/DRC acceptance results.

### 6. Reassess and migrate proven generic core

Only after both backends work, review which shared behavior is genuinely generic. Migrate selected pieces to Python where correctness and testing clearly improve:

- installed CLI parsing and validation;
- resolved domain objects and `RunContext`;
- run allocation, locking, UUIDs, and links;
- structured manifests and provenance capture;
- thin SQLite operational state;
- safe subprocess/container orchestration.

Retain compatibility shims and shell activation behavior. Do not migrate tool-native Tcl/SDC or shell code that exists specifically to mutate or source a shell environment.

Exit criterion: migrated components serve both backends, preserve characterized Cadence behavior, and do not encode ORFS or host-specific policy in core.

### 6a. Make resolved execution location-independent

Before package management, centralize deterministic resolution of state,
workspace, source, and run paths. An Environment remains a named mutable and
possibly partial profile; execution requires a complete RunContext. Add
regressions proving that equivalent invocations from `/`, `/tmp`, and project
directories resolve the same experiment and output paths.

## LATER

### 7. Introduce declarative environment and component manifests

Phase 1 implements the versioned `wolf.environment/v1` profile with package
references for design, technology, and flow; canonical workspace, clock, and
thread values; explicit backend overrides; partial-profile validation; cloning;
and legacy compatibility. Native ORFS planning translates the resolved context
into generated config/SDC inputs and records package provenance.

Continue gradually replacing bucket files as the primary source of truth with declarative environment definitions referencing design, PDK, libraries, technology options, flow, backend, constraints, and variables.

Build stable Python data classes for categories and load concrete instances from manifests. Do not create a subclass per design, PDK, library, or flow. Continue accepting institutional shell setup as an explicit native backend/executor input during migration.

Candidate environment UX includes:

```text
wolf env create
wolf env clone
wolf env set
wolf info
wolf activate
wolf deactivate
```

The v1 schema should grow only through real migrations rather than being
expanded speculatively. Exact allocated runs now freeze immutable resolved
manifests before backend execution. The next validation is the package-only
golden execution before expanding component kinds or inheritance.

### 8. Add package and registry behavior after abstraction stability

Phase 1 establishes pinned local discovery/install support for `rtl`, `pdk`,
and `flow` using a trusted built-in file registry and human-readable installed
records. It proves `rtl/ibex`, `pdk/asap7`, and `flow/orfs` without introducing
dependency solving or a service.

The registry should prefer recipes and upstream references. Public assets may be fetched; proprietary assets remain local and must never be uploaded or redistributed.

Implemented initial UX:

```text
wolf search rtl
wolf install rtl/ibex
wolf install pdk/asap7
wolf install flow/orfs
wolf package list
wolf package info rtl/ibex
```

Later phases may add libraries, toolchains/backends, complete examples,
search, updates, uninstall, and richer registry behavior after native
declarative environments exercise the package metadata.

## POSSIBLE FUTURE

The following ideas remain compatible with the architecture but are not committed requirements:

- `SlurmExecutor`, `LSFExecutor`, and other remote/cluster executors;
- structured `wolf ps` views across local PIDs, containers, and remote jobs;
- richer event and metric indexing;
- package signing, trust policy, mirrors, or multiple registries;
- artifact caching and content-addressed reuse;
- additional proprietary and open-source backends;
- portable example/recipe bundles beyond the initial golden case;
- remote artifact storage or team collaboration services.

Each should be justified by a concrete workflow before expanding core interfaces or dependencies.

## Major design decisions and rationale

| Decision | Rationale |
| --- | --- |
| Use an installed Python CLI as the long-term primary command. | Normal argument parsing, packaging, testing, structured state, and subprocess handling should not depend on sourcing the whole application into Bash. |
| Preserve `wolf activate <environment>` and `wolf deactivate`. | Shell mutation mechanics are an implementation detail; the existing direct UX is valuable and should remain stable. |
| Treat an environment as a resolved EDA experiment composition. | WOLF coordinates design, technology, libraries, flow, backend, constraints, and variables; it is not a language virtual environment. |
| Make backend identity explicit in every resolved run. | Reproducibility and result interpretation require knowing exactly which backend executed, even when a flow has a default. |
| Separate backend from executor. | Tool-flow behavior and execution location/runtime vary independently; ORFS is not synonymous with Docker, and Cadence need not be containerized. |
| Keep the backend interface small until Cadence and ORFS exercise it. | Premature abstraction would encode guesses and increase compatibility risk. |
| Delegate Yosys/OpenROAD flow internals to ORFS. | WOLF manages experiments and execution; duplicating ORFS would create an unnecessary, divergent flow implementation. |
| Model run, execution, and stage execution separately. | A physical-design run can continue across invocations while retaining append-only, queryable execution history. |
| Make human-readable manifests authoritative and SQLite operational. | Archived run directories must explain themselves without WOLF or a database, while SQLite supports live queries and tracking. |
| Use classes for stable categories and manifests for instances. | Data such as Ibex and ASAP7 varies declaratively; subclass-per-asset designs would be rigid and difficult to package. |
| Migrate incrementally, with tests first and ORFS before broad Python migration. | This protects existing Cadence behavior and lets two real backends reveal the correct generic core. |
| Prefer containers for open-source reproducibility, not as a universal requirement. | Public toolchains benefit from pinning; proprietary institutional environments may be legally or operationally native. |
| Keep proprietary assets local. | WOLF may register local PDK/library installations but must not redistribute restricted content. |
| Avoid freezing accidental legacy layouts as APIs. | User-visible behavior deserves compatibility; hostname- and lab-specific internal structures do not. |

## Non-goals for the roadmap

- Rewriting all Bash as Python before ORFS integration.
- Replacing ORFS or implementing EDA algorithms.
- Finalizing a broad plugin/backend/executor interface before real use requires it.
- Redistributing proprietary PDKs or libraries.
- Requiring proprietary environments to run in containers.
- Treating speculative registry, scheduler, or remote-service ideas as part of the initial multibackend release.

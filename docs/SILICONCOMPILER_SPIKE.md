# SiliconCompiler 0.38.5 Competitive Spike

This is a read-only implementation comparison against the official
[SiliconCompiler 0.38.5 manual](https://docs.siliconcompiler.com/en/v0.38.5/).
SiliconCompiler 0.38.5 was installed into `/tmp` only; no WOLF code or state
was changed and no EDA flow was run.

## Evidence gathered

- `Project`, `Design`, `ASIC`, `Flowgraph`, `Task`, `Project.run()`,
  `Project.history()`, `Project.summary()`, `Project.write_manifest()`, and
  `Project.from_manifest()` are public APIs.
- A disposable API experiment wrote a 100 kB `.pkg.json` manifest, reloaded it
  with `Project.from_manifest()`, and preserved build directory, job name,
  `jobincr`, `from`, `to`, and file-hash options.
- A disposable two-node custom flow ran twice. With `clean=True` and
  `jobincr=True`, it retained `build/demo/job/...` and created
  `build/demo/job1/...`, with separate per-node directories.
- `option.jobincr` auto-increments a colliding job name (adding a numeric
  suffix when needed). `option.clean` starts a fresh job; `option.from` and
  `option.to` select a flow range. A re-run reuses completed nodes by default.
- Job history is a full project copy, is queryable by job name, and is recorded
  even when a run fails. The official multi-job documentation describes this
  as the basis for sweeps and comparisons.
- `Project.summary()` reads recorded metrics; the optional dashboard can graph
  metrics across jobs. `Project.from_manifest()` reloads a project/configuration
  from disk.
- Dataroots anchor files to a module or external path rather than cwd. The
  external-library documentation supports environment-variable roots for
  large or restricted collateral.
- The documented scheduler options include local execution, Docker, and
  Slurm. Podman is not presented as a first-class scheduler in the 0.38.5
  documentation.
- Built-in/custom flows are directed graphs of task drivers. A custom tool
  requires a Python `Task` driver with setup, runtime options, and post-process
  behavior. This is the natural extension point for an external flow wrapper.

## Requirement matrix

| Requirement | SiliconCompiler 0.38.5 | Result | UX/architectural difference |
|---|---|---|---|
| Pinned Ibex RTL | Design filesets, dataroots, package/library modules; source revisions can be represented in manifests or external package code | partial | WOLF package identifiers/revisions are a direct user concept; SC expects a Python design/package definition or explicit files |
| ASAP7 technology | Built-in `asap7_demo` target through LambdaPDK, libraries, PDK and timing scenarios | partial/exact for SC target | SC’s PDK object is richer and more tool-schema-oriented; WOLF keeps technology as a reusable package semantic |
| 1050 ps clock | ASIC constraint API/SDC files support clocks and periods | exact | Different API vocabulary; no conceptual gap |
| RTL-to-GDS execution | Built-in ASIC flows are graph-based with Yosys/OpenROAD tasks | exact for native SC flow | SC owns the task graph and drivers; WOLF delegates intact ORFS instead |
| Preserved numbered jobs | `jobname`, build directory, history, and `jobincr` | partial | SC uses named jobs and numeric auto-increment, not WOLF’s design/technology/run identity and `.latest` links |
| Fresh run retaining old job | `clean=True` plus `jobincr=True` | exact | Straightforward SC option combination |
| Resume/re-run from stage | `option.from`/`option.to`; completed nodes are reused by default | exact | SC uses graph node names; WOLF uses backend-neutral stage ranges |
| Exact configuration manifest | `.pkg.json` manifest contains schema/configuration and history | exact | SC manifest is a large schema document; WOLF’s resolved YAML is deliberately semantic and human-oriented |
| Per-stage manifests/state | Per-node build directories with inputs/outputs/reports/logs and schema history | exact/partial | SC stores node state in build tree and manifest history; WOLF has explicit `wolf.stage-results` and `wolf.status.yaml` semantics |
| Metrics/status | Task `post_process()` records semantic metrics; `summary()` and dashboard expose them | exact | SC has broader built-in metric infrastructure; WOLF keeps a smaller backend-owned metric set |
| Job comparison | `history(job)` plus summary/dashboard graphs across jobs | exact | SC is stronger out of the box; WOLF currently has no comparison command |
| Git/local package resolution | Dataroots, Python packages, external libraries, and tool install mechanisms | partial | SC resolves data roots/modules; WOLF has user-facing package/registry/install identifiers |
| Private/local collateral | External dataroots via environment variables; private drivers can be pip-installed | partial/exact | SC’s model is natural for restricted data, but credentials/registry UX is not WOLF’s package registry model |
| cwd/build behavior | Build directory is explicit; dataroots anchor paths to definitions | exact | Similar invariant; SC’s default build path is conventional and configurable |
| Share/reload configuration | `write_manifest()` / `Project.from_manifest()` | exact | SC reloads a full project; WOLF separates mutable environment from frozen run provenance |
| Input/output hashing | `option.hash` and recorded schema/tool data | exact/partial | SC can hash files; WOLF records package revisions and resolved paths but does not yet offer equivalent universal input hashing |
| Commercial/private tools | Tool drivers, private pip modules, native executable/license environments, optional schedulers | exact/partial | Natural for SC when a driver exists; proprietary drivers cannot generally ship publicly |

## Answers to the architectural questions

### A. Straightforward duplicates

Run/job naming, clean-vs-resume execution, stage range selection, manifests,
per-node build artifacts, metric extraction, summaries, job history, and
configuration reload are all already substantial SiliconCompiler capabilities.

### B. Mostly CLI/UX differences

WOLF’s `wolf activate`, `wolf info`, `wolf status`, vibrant terminal UI,
package identifiers, `.latest` links, and semantic pre-run summary are mostly
presentation and workflow choices over capabilities SC already exposes through
Python APIs and its dashboard.

### C. Genuinely different abstractions

WOLF treats an environment as a named mutable, optionally partial experiment
profile and resolves packages, technology, flow, backend, executor, and paths
into a backend-independent RunContext. It also treats intact external flow
ecosystems as backends. SiliconCompiler instead centers a complete Project,
Design/PDK/library objects, a graph of Task drivers, and a schema manifest.

WOLF’s explicit separation of package registry, semantic environment, backend,
and native-flow compatibility mode is not a one-to-one duplicate.

### D. Thin frontend/plugin around SiliconCompiler?

Reasonable for a WOLF mode that uses SiliconCompiler-native flows. WOLF could
own activation, package/registry UX, semantic environment resolution, and
translate a resolved context into an SC Project. This would duplicate less run,
history, metrics, and comparison machinery.

### E. SiliconCompiler as a WOLF backend?

Also reasonable. A backend could construct/load an SC Project, set its flow,
apply canonical constraints, select build/job options, and delegate execution.
The adapter would need to translate WOLF stages and preserve WOLF’s frozen
manifest alongside SC’s `.pkg.json`.

### F. WOLF code potentially unnecessary

If SC became an internal engine, generic stage scheduling, job history,
per-stage artifact bookkeeping, broad metric storage, manifest serialization,
run comparison, and perhaps file hashing could be removed or reduced to
adapters. WOLF package/registry, activation, semantic resolution, and external
backend compatibility would remain.

### G. Capabilities WOLF could lose

WOLF would risk losing its intentionally small, human-readable semantic model;
the distinction between mutable environments and immutable run snapshots;
first-class intact ORFS/Flowtool compatibility; `.latest` and current legacy
run semantics; and a lightweight installation with few dependencies. SC’s
schema is powerful but substantially more prescriptive.

### H. Capabilities WOLF could gain

SC would provide mature flow DAG validation, scheduler/parallel execution,
tool drivers, per-node metrics, job history, hashing, summaries, dashboards,
remote execution options, and a broad ecosystem of PDK/library/tool modules.

### I. Intact ORFS or institutional Flowtool

Native SC flows are natural: each tool stage is already a Task and custom
flows are explicitly supported. Wrapping intact ORFS is possible but less
natural: WOLF would need an SC custom Task/flow that launches ORFS’s own Make
graph, maps files and stages, captures outputs, and avoids SC’s assumptions
about task-level inputs/outputs. This preserves ORFS but adds a second flow
model and duplicate scheduling/provenance layers. Institutional Cadence is
similar: natural if a private SC driver exists, awkward if WOLF must preserve a
lab’s existing Flowtool orchestration unchanged.

### J. Recommendation

**Continue independent WOLF for now, while keeping a SiliconCompiler adapter
as an explicit future experiment.**

Rebuilding WOLF on SC would immediately duplicate or surrender the parts that
motivate WOLF: semantic environments, package/registry composition, and intact
external-flow backends. Conversely, ignoring SC would leave valuable mature
execution/history/metrics capabilities unused. The lowest-risk path is to
validate a small optional SC backend or frontend adapter after WOLF’s second
design, without changing WOLF’s core contracts or ORFS backend.

## Decision summary

SiliconCompiler is not merely a competing CLI: it already solves much of the
execution engine. WOLF remains differentiated at the composition boundary and
at compatibility with existing flow ecosystems. The spike does not justify
deleting WOLF today, but it does justify avoiding parallel reinvention of job
history, generic metrics, comparison, and scheduler features.

## Sources

- [Quickstart and run results](https://docs.siliconcompiler.com/en/v0.38.5/user_guide/quickstart.html)
- [Clean, jobincr, from/to, and manifest reload](https://docs.siliconcompiler.com/en/latest/user_guide/howto.html)
- [Multi-job history and comparisons](https://docs.siliconcompiler.com/en/latest/user_guide/tutorials/multi_job_flows.html)
- [Custom flows and task drivers](https://docs.siliconcompiler.com/en/latest/user_guide/tutorials/custom_flow.html)
- [Dataroots and external/private collateral](https://docs.siliconcompiler.com/en/latest/development_guide/external_libraries.html)
- [Metrics and post-processing](https://docs.siliconcompiler.com/en/v0.38.5/development_guide/metrics.html)

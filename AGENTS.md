# WOLF project guidance

WOLF is an EDA workflow and environment manager. Its core purpose is to compose independently selectable design/RTL, process/PDK, library, metal-stack, and flow definitions while preserving reproducible, numbered implementation runs, snapshots, history, and convenient latest-run links.

Preserve existing Cadence Flowtool/Genus/Innovus behavior while developing WOLF as a multibackend system, including an ORFS backend using Yosys and OpenROAD. Keep generic WOLF concerns—environment composition, run lifecycle, provenance, history, and project structure—separate from backend-specific dependency checks, configuration generation, stage discovery, invocation, and result interpretation.

Backend identity must be explicit in every resolved run. Keep the backend separate from its execution mechanism: for example, ORFS may use a container executor while Cadence may use a native/local executor. Do not reimplement ORFS internals inside WOLF, and do not expand the backend interface beyond what the Cadence and ORFS implementations demonstrate they need.

Prefer incremental, compatibility-preserving changes over wholesale rewrites. Add characterization tests before behavior-changing refactors, especially around run numbering, snapshot retention, environment activation, history, command forwarding, stage selection, and `.latest` links.

Definitions and manifests should be portable across machines. Do not assume Ubuntu, `apt`, particular hostnames, or institutional filesystem paths. Never commit proprietary PDK or library content. Open-source backends should prefer reproducible containerized toolchains; proprietary backends may integrate with native institutional environments.

Human-readable environment and resolved-run manifests are the authoritative reproducibility record. SQLite may index operational state, executions, stages, artifacts, and metrics, but it must not be the sole provenance store. Treat a physical-design run as a durable identity that may accumulate append-only executions and stage results.

The long-term primary command is an installed Python CLI, but preserve `wolf activate <environment>` and `wolf deactivate` as the public UX. Any shell hook needed to mutate the caller's environment should remain a transparent implementation detail.

Avoid unnecessary dependencies. Keep shell where shell state or native environment setup is the actual problem, and use more structured tooling where parsing, validation, manifests, or orchestration require it.

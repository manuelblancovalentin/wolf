# WOLF backends

A backend adapts WOLF's generic run lifecycle to one implementation system.
Backend identity is explicit, uses lowercase letters, numbers, and hyphens, and
is resolved through a small built-in registry. The compatibility default is
`cadence-flowtool`; an unknown name fails before run state or tools are touched.

## Responsibility boundary

WOLF core owns run allocation and continuation, numbered script snapshots,
generic `.latest` links, UUID/history records, stage-range selection, user
confirmation, ordered stage orchestration, and stopping after a failed stage.

A backend owns its dependency/configuration validation, tool-specific input
derivation, configuration generation, ordered stage discovery, command
construction, execution, PID/tool integration, and interpretation of tool
status and logs.

The execution contract is deliberately small:

```text
validate
plan       # transitional, read-only legacy summary preparation
prepare
stages
run_stage
```

`plan` exists because the legacy runner displays resolved Cadence inputs and
planned configuration paths before the user authorizes filesystem changes. It
should disappear into normal context resolution when that lifecycle moves to
Python; it is not intended as a permanent expansion of the target interface.

## Transitional implementation

The real legacy execution boundary is currently shell-based to avoid rewriting
the stabilized Bash run lifecycle:

- `bin/backend.sh` loads a registered adapter, validates its contract, selects
  a backend-neutral stage range, and invokes stages in order;
- `bin/backends/cadence-flowtool.sh` contains the extracted Flowtool-specific
  preparation, discovery, invocation, Tcl PID injection, and log handling;
- `bin/wolf.run` selects the backend and retains generic run behavior.

The installed Python package exposes the same built-in identity through
`wolf.backend`. This registry powers `wolf backend list` and
`wolf backend info NAME`; it performs no Cadence checks during ordinary WOLF
imports or non-Cadence commands. Backend-local validation is mockable and is
reported only when that backend is inspected or selected.

This is a compatibility bridge, not the final Python `RunContext` or executor
model. Built-ins are registered centrally; there is no entry-point or dynamic
plugin discovery.

## Built-in backends

The built-in backends are:

- `cadence-flowtool` — the existing Cadence Flowtool/Genus/Innovus behavior.
- `orfs` — an adapter to an externally supplied OpenROAD Flow Scripts checkout.

The ORFS adapter uses the same shell contract and generic range orchestration as
Cadence. It provides the ordered public stages `synth`, `floorplan`, `place`,
`cts`, `route`, and `finish`; each is translated to the matching ORFS Make
target. WOLF does not recreate ORFS's internal flow.

`orfs` is container-oriented but is not synonymous with Docker. WOLF prefers a
usable rootless Podman runtime, then usable Docker, and uses a shared direct
container executor for both. This preserves ORFS's supported headless Qt mode
for SSH execution. The selected runtime, checkout revision when available,
image configuration, and constructed Make arguments are backend metadata for
future run-manifest persistence.

See `docs/ORFS.md` for configuration and the opt-in Ibex regression harness.

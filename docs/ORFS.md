# ORFS backend

The `orfs` backend drives an externally supplied OpenROAD Flow Scripts (ORFS)
checkout. WOLF manages the selected backend, generic WOLF run lifecycle, stage
ranges, snapshots, and failure stopping; ORFS remains responsible for the
Yosys/OpenROAD implementation flow.

This phase does not clone, install, or manage ORFS. It also does not require
host-installed Yosys, OpenROAD, or KLayout.

## Requirements

- An ORFS checkout whose root is its `flow` directory. It must contain
  `Makefile`, `designs`, and `util`.
- A usable Docker or Podman runtime. Rootless Podman is preferred when it is
  available and usable.
- Python 3 for the opt-in result checker.

Configure the checkout with:

```bash
export ORFS_ROOT=/path/to/OpenROAD-flow-scripts/flow
wolf backend info orfs
```

`wolf backend info orfs` is read-only: it reports configured checkout and
runtime status and does not attempt to pull images or invoke EDA tools. It
distinguishes a missing binary, a daemon/socket failure, and permission denial.
The shell runner checks that its selected runtime can answer `info` before
allocating a WOLF run.

## Backend inputs

The initial backend uses environment variables while WOLF's declarative
environment model is still being introduced.

| Variable | Required | Meaning |
| --- | --- | --- |
| `ORFS_ROOT` | yes | External ORFS `flow` checkout. |
| `ORFS_DESIGN_CONFIG` | yes | Design `config.mk`, absolute or relative to `ORFS_ROOT`. |
| `ORFS_FLOW_VARIANT` | yes | Dedicated ORFS `FLOW_VARIANT` result namespace. |
| `ORFS_SDC_FILE` | no | Explicit host-owned SDC override, absolute or relative to `ORFS_ROOT`. |
| `ORFS_MAKE_VARS` | no | Newline-separated `NAME=VALUE` Make overrides. |
| `ORFS_CONTAINER_RUNTIME` | no | `docker` or `podman`. WOLF chooses usable Podman, then usable Docker, when unset. |
| `ORFS_CONTAINER_IMAGE` | no | Image used by either runtime; defaults to `docker.io/openroad/orfs:latest`. Pin a digest for reproducibility. |
| `ORFS_CONTAINER_WORKDIR` | no | Defaults to `/OpenROAD-flow-scripts/flow`. |

WOLF runs both container runtimes directly, mounts `ORFS_ROOT` at `/work` with
the Fedora-compatible `:Z` label, and passes ORFS's supported headless Qt
settings (`DISPLAY=` and `QT_QPA_PLATFORM=offscreen`). This prevents ORFS final
report image generation from trying to initialize an X11 GUI during SSH runs.
It does not suppress a nonzero OpenROAD or Make exit status. WOLF does not
treat a floating tag as a reproducibility guarantee.

On Fedora, use rootless Podman when `podman info` succeeds. If Docker is
installed but reports permission denial, WOLF will not select it automatically.
If Podman is unavailable, Docker remains supported; Docker users normally need
the daemon running and access to its socket (often through the local `docker`
group and a new login session). Do not change Docker group membership merely
to use WOLF when rootless Podman is already usable.

Make assignments may also be passed through the legacy shell runner as separate
`NAME=VALUE` arguments. Non-assignment passthrough arguments are rejected by
the ORFS adapter rather than being interpreted by a shell.

## Host and container paths

ORFS's Docker helper mounts the host checkout at `/work` but runs in the image's
own `/OpenROAD-flow-scripts/flow`. A relative `DESIGN_CONFIG` or `SDC_FILE` can
therefore accidentally select collateral from the image instead of host-edited
files.

WOLF validates that `ORFS_DESIGN_CONFIG` and an optional `ORFS_SDC_FILE` are
inside `ORFS_ROOT`, then passes them to Make as container-visible absolute paths
under `/work`. For example:

```text
DESIGN_CONFIG=/work/designs/asap7/ibex/config.mk
SDC_FILE=/work/designs/asap7/ibex/constraint.sdc
```

Files outside the checkout are rejected because they are not guaranteed to be
visible in the container.

## Stages

The initial public stage mapping is deliberately modest:

| WOLF stage | ORFS target |
| --- | --- |
| `synth` | `make synth` |
| `floorplan` | `make floorplan` |
| `place` | `make place` |
| `cts` | `make cts` |
| `route` | `make route` |
| `finish` | `make finish` |

The existing backend-neutral range orchestration selects an inclusive range and
stops on the first nonzero Make/container exit status.

## Opt-in Ibex + ASAP7 regression

The harness is intentionally excluded from `tests/run`. It runs the Ibex ASAP7
1050 ps baseline with `SWAP_ARITH_OPERATORS` disabled and
`OPENROAD_HIERARCHICAL=0`.

The stock Ibex SDC may use a 1000 ps clock. Before starting ORFS, the harness
creates (or validates without overwriting) the dedicated host file
`designs/asap7/ibex/constraint.wolf_ibex_asap7_1050ps.sdc`. It changes only the
single `set clk_period` assignment to `1050`, leaves the stock SDC untouched,
and passes the derived file explicitly as
`SDC_FILE=/work/designs/asap7/ibex/constraint.wolf_ibex_asap7_1050ps.sdc`.

Before invoking it, choose an unused dedicated ORFS variant. The default is
`wolf_ibex_asap7_1050ps`; the harness refuses variants that do not begin with
that name and refuses to run if the corresponding ORFS `results` or `reports`
directory already exists. It never runs an ORFS clean target.

```bash
cd /projects/wolf
export ORFS_ROOT=/path/to/OpenROAD-flow-scripts/flow
tests/integration/run_orfs_ibex
```

To force a particular runtime or pinned image:

```bash
export ORFS_CONTAINER_RUNTIME=podman
export ORFS_CONTAINER_IMAGE=registry.example/orfs@sha256:...
tests/integration/run_orfs_ibex
```

On completion, the harness runs ORFS's report-only `metadata-generate` target,
then checks `reports/asap7/ibex/<variant>/metadata.json` for zero setup
violating paths, zero hold violating paths, and zero detailed-route DRC errors.
It prints the final worst setup slack in ps; roughly `+14.7 ps` is the
reference, but timing-clean completion is the criterion. Residual max-slew
violations are not checked by this baseline.

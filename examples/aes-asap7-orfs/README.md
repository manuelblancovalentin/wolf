# AES + ASAP7 + ORFS

This example validates a second, non-CPU RTL design through WOLF's existing
package, environment, resolver, and ORFS backend model.

## Prerequisites

- an installed WOLF checkout (`python -m pip install -e .`)
- rootless Podman (preferred) or Docker
- enough disk space for the pinned OpenROAD Flow Scripts package and results

The example uses the built-in pinned packages; it does not require a manual
`ORFS_ROOT` checkout.

## Run

```bash
wolf install flow/orfs
wolf install rtl/aes
wolf install pdk/asap7

wolf env create aes-asap7 --from wolf.yaml
wolf activate aes-asap7
wolf info
wolf run --plan
wolf run -y
wolf status
```

The stock ORFS AES configuration uses top `aes_cipher_top`, a Verilog source
set from `flow/designs/src/aes`, and a 380-period clock named `clk` on port
`clk`. WOLF generates the backend configuration and SDC from those semantic
values, while retaining the pinned package revisions in the frozen run
manifest.

Run planning is independent of the caller's directory: it is safe to plan or
run from `/`, `/tmp`, or another directory after activation. Activation does
not change the working directory.

## Results and provenance

Runs are allocated below the configured workspace using WOLF's numbered-run
layout:

```text
<workspace>/aes/aes.asap7/<run>/
  wolf.resolved.yaml
  backend/orfs/
    config.mk
    constraints.sdc
  logs/
  reports/
  results/
```

`wolf.resolved.yaml` is the immutable resolved experiment snapshot. `wolf
status` reports mutable execution state and backend-owned metrics. Existing
runs are preserved and `.latest` links provide convenient access to the most
recent run.

## Validation result

At the pinned ORFS revision, this WOLF-managed run completed through `finish`
under rootless Podman. The observed result was worst setup slack `-3.8 ps`,
8 setup violations, 0 hold violations, 0 route DRC violations, and 0 max
cap/fanout/slew violations. This is a configuration and multi-design
validation result, not a timing-closure claim; the Ibex 1050 ps run remains
WOLF's timing-clean golden case.

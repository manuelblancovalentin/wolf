# Ibex + ASAP7 + ORFS

This is the runnable WOLF reference example: Ibex RTL, the ASAP7 technology,
and the ORFS backend with a 1050 ps clock. It requires Python 3 with WOLF
installed, Git, and a usable rootless Podman or Docker runtime. The packages
are open-source and pinned by the built-in registry.

```bash
python3 -m pip install -e /path/to/wolf
wolf install flow/orfs
wolf install rtl/ibex
wolf install pdk/asap7
wolf env create ibex-asap7 --from /path/to/wolf/examples/ibex-asap7-orfs/wolf.yaml
wolf activate ibex-asap7
wolf run --plan
wolf run -y
wolf status
```

Planning is safe and does not allocate a numbered run. Execution may be
launched from `/`, `/tmp`, or any other directory: the resolved environment,
not the caller's cwd, determines the workspace and inputs.

Runs live below the configured workspace, for example:

```text
~/wolf-work/ibex/ibex.asap7/ibex.1/
  wolf.resolved.yaml
  backend/orfs/config.mk
  backend/orfs/constraints.sdc
  logs/  reports/  results/
```

Each numbered run preserves its own implementation identity. The frozen
`wolf.resolved.yaml` records package revisions, canonical constraints, backend,
runtime, paths, and generated inputs. `wolf status` reads execution state and
the small set of backend-owned timing/DRC metrics.

The validated reference result is timing-clean with zero setup violations,
zero hold violations, zero route DRC violations, and approximately +13.31 ps
worst setup slack. Max-slew violations may remain in this research baseline.

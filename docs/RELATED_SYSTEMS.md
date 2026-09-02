# Related systems

WOLF sits among several useful, partially overlapping EDA and reproducibility
tools. These are factual relationship notes, not novelty claims.

## SiliconCompiler

[SiliconCompiler](https://docs.siliconcompiler.com/en/v0.38.5/) is a Python
hardware compilation framework organized around Projects, Designs, PDKs,
libraries, flowgraphs, and tool Tasks. It already provides manifests, explicit
build directories, stage selection, job history, metrics, hashing, schedulers,
and optional dashboards. WOLF overlaps strongly in run lifecycle and
provenance, but emphasizes mutable semantic environments, package/registry
composition, and wrapping intact external ecosystems such as ORFS and
institutional Flowtool.

## Hammer

[Hammer](https://hammer-vlsi.readthedocs.io/en/stable/) is a modular physical
design flow infrastructure focused on generators and tool/technology
interfaces. It standardizes flow inputs and backend APIs across tools while
allowing technology and vendor plugins. WOLF operates at a broader experiment
and environment layer; a future integration could use Hammer-generated flow
inputs or treat Hammer as a backend ecosystem.

## FuseSoC / Edalize

[FuseSoC](https://fusesoc.readthedocs.io/en/stable/) manages reusable hardware
cores described by core files. [Edalize](https://edalize.readthedocs.io/) is
the tool/flow interfacing layer used to configure and invoke EDA tools. This
maps naturally to WOLF's reusable RTL/package concerns, but FuseSoC targets
core assembly and tool invocation rather than WOLF's technology-aware,
numbered implementation-run and provenance model.

## OpenROAD Flow Scripts

[ORFS](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts) is a
native Make/configuration flow for Yosys/OpenROAD RTL-to-GDS implementation.
WOLF's ORFS backend translates a resolved semantic environment into ORFS
configuration and preserves WOLF-owned runs, manifests, and status. WOLF does
not replace ORFS algorithms or its native flow graph.

## Nix

[Nix](https://nix.dev/) is a general-purpose functional package/build and
environment system. Nix expressions and lock files can pin toolchains and
inputs, while the Nix store isolates build outputs. WOLF may use or coexist
with Nix for reproducible tool environments, but WOLF's packages describe EDA
assets and its environments describe experiments, constraints, backends, and
runs. They solve related reproducibility problems at different layers.

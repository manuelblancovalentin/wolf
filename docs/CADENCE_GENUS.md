# Cadence Genus mixed-language preparation

WOLF's `cadence-flowtool` backend can prepare generic mixed-language Genus
inputs from a resolved `RunContext`. The preparation layer consumes only
package metadata: ordered sources, language, compilation role, named library,
include directories, defines, VHDL standard, constraints, revisions, and
checksums. It does not invoke ESP, SocketGen, or FABulous generators.

The generated collateral consists of:

- `sources.tcl`, with VHDL packages before VHDL implementations and each
  Verilog/SystemVerilog source in resolved order;
- `run.tcl`, which performs elaboration, unresolved-design checks, and basic
  hierarchy/message reports inside one Tcl error boundary. Any failure while
  sourcing HDL, elaborating, reading constraints, checking the design, or
  writing reports prints the original Tcl error and error information, then
  exits Genus nonzero. The script exits zero only after every operation
  succeeds. WOLF uses this process status as the execution result rather than
  treating log text as a success signal;
- `genus-inputs.yaml`, a human-readable input/provenance record.

For Genus Tcl, VHDL sources use `read_hdl -vhdl`. Both `verilog` and
`systemverilog` package classifications deliberately use Genus's `read_hdl
-sv` reader, because modern Verilog-family sources may contain SystemVerilog
syntax even when their filenames end in `.v`. The original language
classification remains unchanged in the resolved context and provenance.

Genus preparation also adds the backend-required `SYNTHESIS` define to the
effective emitted Verilog/SystemVerilog define set. Package-requested defines
such as `WT_DCACHE` are preserved, duplicates are removed deterministically,
and the package, backend-required, and effective sets are recorded in
`genus-inputs.yaml` and frozen run provenance. The canonical resolved package
metadata is not modified.

Technology is resolved from the selected installed PDK package. The initial
Genus gate uses one package-declared timing corner and its ordered NLDM Liberty
files, emitted in `technology.tcl` before `sources.tcl`. Technology and cell
LEFs, RC setup/extraction files, and GDS are retained as package-resolved
physical inputs and are validated when a physical stage requests them; they
are not required for technology-independent HDL elaboration. The generated
technology manifest records package revision, selected corner, paths, and
file hashes. A future private technology package can provide the same view
metadata without committing proprietary collateral or machine-local paths.

The historical `/home/manu/stylus` flow was consulted only as a reference for
the high-level technology-loading lifecycle. It is not copied, imported, or a
runtime dependency of WOLF.

## Thread configuration and step presentation

`prepare_genus_inputs` sets `max_cpus_per_server` when a thread count is
resolved. WOLF's own canonical `resources.threads` wins when set; otherwise
the backend honors `GENUS_NUM_CPUS` if the environment's `env:` map declares
it — a long-standing Cadence-flow convention, recognized here as
backend-native policy (read from the resolved, reproducible `env:` map, never
the ambient process environment). Neither present means no attribute is
emitted and Genus keeps its own default. The resolved value (or `null`) is
recorded in `genus-inputs.yaml` as `max_cpus_per_server`.

`run.tcl` also wraps each operation (technology load, overrides, source
read, elaborate, constraints, design check, reports) in a small
`wolf_step`/`wolf_sep` Tcl helper pair that prints an ANSI-colored title and
divider — freshly written, inspired by the concept of bracketing each step
with a colored banner rather than derived from any specific flow's script
content. This only affects Genus's own subprocess stdout; it has no relation
to `wolf.ui`/Rich, which governs the Python CLI's own terminal output.

## Genus attribute overrides

Some Genus attributes are tool policy rather than package metadata or
canonical WOLF semantics, and cannot be inferred from a resolved design
(for example `hdl_max_memory_address_range`, which caps generic memory
inference during elaboration). These are supplied explicitly through the
`backend.cadence-flowtool` escape hatch in `wolf.yaml`:

```yaml
backend:
  cadence-flowtool:
    genus:
      set_db:
        hdl_max_memory_address_range: 65536
```

When present, `prepare_genus_inputs` writes `overrides.tcl` and sources it
before `sources.tcl` and `elaborate`, so overrides take effect before Genus
touches the design. Override values must be scalars (string, number, or
boolean); the resolved key/value pairs are also recorded in
`genus-inputs.yaml` and frozen run provenance. Unknown keys under
`backend.cadence-flowtool` or `backend.cadence-flowtool.genus` are rejected
rather than silently ignored.

Preparation is exposed by `wolf.backend.cadence_genus.prepare_genus_inputs` and
is intentionally separate from the legacy Flowtool shell runner. For
declarative `cadence-flowtool` environments, the run bridge validates Genus
before allocation, writes directly under the exact numbered run, freezes
`wolf.resolved.yaml`, and invokes:

```text
cd <run>/backend/cadence-genus
genus -files run.tcl -log genus.log
```

Preparation-only plans validate and report prospective paths without
allocating a run or invoking Genus. A licensed Kona gate should first validate HDL read, `ESP_ASIC_TOP` elaboration, hierarchy,
and link checks. WOLF must validate `genus` and any explicitly configured
technology files before allocating a run. Physical views are not inferred or
bundled by WOLF; missing Liberty, LEF, QRC, or equivalent inputs must be
reported and the technology selected explicitly.

No licensed-tool execution is part of the local unit suite. The exact Kona
command should be assembled only after selecting the technology and confirming
the institution's Genus installation and technology views.

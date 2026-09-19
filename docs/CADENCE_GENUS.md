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
  hierarchy/message reports;
- `genus-inputs.yaml`, a human-readable input/provenance record.

Preparation is exposed by `wolf.backend.cadence_genus.prepare_genus_inputs` and
is intentionally separate from the legacy Flowtool shell runner. A licensed
Kona gate should first validate HDL read, `ESP_ASIC_TOP` elaboration, hierarchy,
and link checks. WOLF must validate `genus` and any explicitly configured
technology files before allocating a run. Physical views are not inferred or
bundled by WOLF; missing Liberty, LEF, QRC, or equivalent inputs must be
reported and the technology selected explicitly.

No licensed-tool execution is part of the local unit suite. The exact Kona
command should be assembled only after selecting the technology and confirming
the institution's Genus installation and technology views.

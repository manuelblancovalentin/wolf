# Cadence Genus mixed-language preparation

WOLF's `cadence-flowtool` backend can prepare generic mixed-language
Flowtool/Genus inputs from a resolved `RunContext`. The preparation layer
consumes only package metadata: ordered sources, language, compilation role,
named library, include directories, defines, VHDL standard, constraints,
revisions, and checksums. It does not invoke ESP, SocketGen, or FABulous
generators.

Execution goes through the real `flowtool` binary, not `genus` directly.
This matters: `create_flow_step`/`-write_db` checkpointing is Flowtool's own
Common-UI runtime mechanism, and Genus's internal synthesis-stage tracking
is live session state that only a genuine `write_db`, called immediately
after the real stage command completes in that same session, preserves --
exporting a netlist and re-elaborating it in a fresh session does not count,
however faithful the netlist is.

## The flow scripts are real files, not generated code

Every step this run performs -- and Flowtool, not WOLF, sequences and
checkpoints them -- is defined in real, version-controlled Tcl:
[`flows/cadence-genus/flow.tcl`](../flows/cadence-genus/flow.tcl) and
[`flows/cadence-genus/presentation.tcl`](../flows/cadence-genus/presentation.tcl).
Open them, read them, or clone them:

```bash
wolf flow init my-genus-flow \
  --from flows/cadence-genus \
  --to /path/to/my-project-repo/wolf/flows/my-genus-flow \
  --manifest /path/to/my-project-repo/wolf/registry/flow/my-genus-flow.yaml \
  --backend cadence-flowtool \
  --revision "$(git -C /path/to/my-project-repo rev-parse HEAD)"
```

Point `flow.package` at the resulting manifest and WOLF resolves the clone
instead of the bundled default (`wolf.backend.cadence_genus._flow_root`
falls back to the bundled scripts only when no installed flow package
provides its own `flow.tcl`).

### Steps

```text
create_flow_step -name elaborate   -owner design  { ... } -write_db
create_flow_step -name syn_generic -owner cadence { ... } -write_db
create_flow_step -name syn_map     -owner cadence { ... } -write_db
create_flow_step -name syn_opt     -owner cadence { ... } -write_db
```

`elaborate` is `-owner design` because what RTL is read and how it
elaborates is the one part of this flow every design customizes; the three
synthesis steps are `-owner cadence` because they need no per-design
customization. `-write_db` on all four means Flowtool checkpoints
immediately after each step's real work, in the same live session -- see
[Checkpointing and resuming a run](#checkpointing-and-resuming-a-run).

`elaborate`'s body: configure resources, load technology/overrides, read
physical views and elaborate (physical-aware automatically whenever LEF
views are configured -- see
[Physical views, floorplan DEF, and MMMC](#physical-views-floorplan-def-and-mmmc)),
read constraints, check the design. `syn_generic`'s body: mark PDK-declared
dont-use cells, group the standard Cadence Genus synthesis cost paths, run
`syn_generic`, report area, write the generic netlist. `syn_map`/`syn_opt`
run `syn_map`/`syn_opt`, report area, write their netlist; `syn_opt`
additionally does the final `check_design`/hierarchy/message reports.

### What was intentionally left out, and why

The reference production TSMC65 flow (read for structure only, never
copied) does considerably more than this. Dropped, with the specific
reason for each:

- **MMMC generation** (library sets per threshold-voltage/track, RC
  corners, delay corners, constraint modes, analysis views, all generated
  from a `setup.yaml` MMMC section): this is a genuine multi-corner
  technology-model feature. WOLF's technology model today is single
  corner/single flat SDC; adding real MMMC needs that model expanded first,
  not guessed at here. Tracked as a follow-up, not implemented.
- **`apply_clock_derate`**: depends on the same multi-corner analysis-view
  machinery as MMMC: no analysis views yet, nothing to derate per-view.
- **`uniquify_modules`/`preserve_blocks`/`preserve_instances`**: these
  implement a specific hierarchy-preservation *policy* (which modules/
  instances a project chooses to keep un-flattened) driven by
  project-specific config lists (`setup.yaml`'s `preserve_modules` etc.)
  that WOLF's environment schema has no equivalent of; nothing to hang this
  off without inventing that config surface first.
- **`read_power_intent`** (UPF/CPF): no power-intent input exists anywhere
  in WOLF's resolved context yet; would need its own new config field,
  analogous to how `constraints.floorplan_def` was added for DEF.
- **`genus_to_lec`/`genus_to_clp`** (LEC/CLP equivalence-checking
  integration): these schedule *separate* verification flows/tools
  (`write_do_lec`, `write_clp_script`) entirely outside synthesis itself,
  gated by feature flags this flow doesn't model.

Kept (added on top of what an earlier revision of this flow had), per
explicit instruction that these belong in WOLF's own default flow:
**`read_physical`/`init_design`** (physical-aware synthesis, gated
automatically on the technology package declaring LEF views) and
**`read_def`** (a floorplan DEF, via the new `constraints.floorplan_def`
field) -- see
[Physical views, floorplan DEF, and MMMC](#physical-views-floorplan-def-and-mmmc).

## The Flowtool project descriptor (flow.yaml)

WOLF ships its own generic `flow.yaml` Flowtool project descriptor
(`flows/cadence-genus/flow.template.yaml`) and uses it by default -- no
institution-supplied file is required. It only lists this flow's real Tcl
scripts (`default_flow_steps`) and points Flowtool at the per-run
`flow-config.tcl` (`user_flow_steps`); the actual flow sequencing is
Tcl's own `create_flow`/`create_flow_step` in `common_flows.tcl` and
friends, not a yaml step tree, so this file never needs anything
technology-, library-, or institution-specific. No companion `setup.yaml`
is written either: this flow reads its resolved values directly out of
`flow-config.tcl` as plain Tcl variables rather than via
`get_flow_config`/`design_yaml`.

A project with its own extension Tcl that does rely on `get_flow_config`
(or wants an institution's existing Flowtool project descriptors instead)
can still override the template pair via the same `backend.cadence-flowtool`
escape hatch used for `set_db` overrides:

```yaml
backend:
  cadence-flowtool:
    flowtool:
      setup_template: /asic/flows/wolf-registry/flowtool/tsmc65.setup.yaml.template
      flow_template: /asic/flows/wolf-registry/flowtool/tsmc65.flow.yaml.template
```

Both keys are required when overriding at all (omit the whole `flowtool`
key to use WOLF's bundled default); each path must exist.
`prepare_genus_inputs` rejects a missing or nonexistent template path, a
partial override (only one of the two keys given), or an unknown key under
`backend.cadence-flowtool.flowtool`, before writing anything.

### `flow_template`: WOLF's own `${WOLF_*}` tokens

`flow_template` is always rendered by plain `${TOKEN}` substitution (the
same mechanism the legacy Bash runner already uses via `sed`) -- WOLF
does not parse or otherwise understand its YAML structure. The template
decides which of these tokens to use and how:

| Token | Value |
|---|---|
| `${WOLF_DESIGN_NAME}` | resolved design name |
| `${WOLF_DESIGN_TOP}` | resolved top-level module/entity |
| `${WOLF_SCRIPTS_DIR}` | the scripts.\<N\> snapshot directory (see below) -- WOLF's own `flow_template` sets `init_flow_directory` here |
| `${WOLF_FLOW_CONFIG_SCRIPT}` | this run's `flow-config.tcl` path -- WOLF's own `flow_template` lists it under `user_flow_steps` |
| `${WOLF_SETUP_YAML}` | the rendered setup.yaml's own path (available inside the flow template only, and only when a `setup_template` override is given) |
| `${WOLF_WORKSPACE_DIR}` | resolved workspace root |
| `${WOLF_RUN_DIRECTORY}` | this run's own numbered directory (`<design>.<N>`) |
| `${WOLF_RUN_TAG}` | the real allocated run tag (`<design>.<N>`, matching `${WOLF_RUN_DIRECTORY}`'s own name) -- not the environment's `run_tag`, which only ever defaults to the bare design name |
| `${WOLF_REPORTS_DIR}` | absolute directory the flow writes reports under |
| `${WOLF_OUTPUTS_DIR}` | absolute directory the flow writes netlists under |

### `setup_template`: the flat legacy token set, a PDK fragment, and the catalog

`setup_template` is the point where a real flow's own Tcl reads values
back via `get_flow_config` rather than the `${WOLF_*}` mechanism above,
so it's rendered differently, in three steps:

1. **Concatenate.** If the selected technology package declares
   `technology.setup_yaml_fragment` (a PDK/process-specific yaml chunk
   `wolf pdk menu` owns -- see [PDK_PACKAGES.md](PDK_PACKAGES.md)), its
   content is appended to `setup_template`'s own, mirroring the legacy
   Bash backend's own `cp primary; tail -n +3 fragment >> ...`
   (`bin/backends/cadence-flowtool.sh`'s `_wolf_backend_prepare`): the
   fragment's own `%TAG !.../---` document header is dropped so the
   result is still one valid document.
2. **Substitute the flat token set**, matching that same legacy
   mechanism's own `sed` map exactly (no `WOLF_` prefix):

   | Token | Value |
   |---|---|
   | `${DESIGN_NAME}` | resolved design name |
   | `${CONSTRAINTS_FILES}` | this run's generated `constraints.sdc`, as an inline yaml list |
   | `${FLOORPLAN_FILE}` | `constraints.floorplan_def`, if set |
   | `${PDK_DIR}` | the selected technology package's installed root |
   | `${METAL_STACK}` | the technology's resolved `metal_stack`, if set |
   | `${TRACKS}` / `${VTHS}` | the selected track(s)/vth(s), as an inline yaml list -- confirmed real usage: a legacy `vths: ${VTHS}` setup.yaml token (`VTHS` a bash array) is consumed by `synthesis.tcl`'s own `foreach trk [get_flow_config tracks] { foreach vth [get_flow_config vths] { ... } }`, unioning every (track, vth) pair's library/lef files -- so even a single selected value renders as a one-element list, not a bare scalar |
   | `${WORKSPACE_DIR}` / `${SCRIPTS_DIR}` / `${RUNDIR}` | resolved workspace root / scripts.\<N\> directory / this run's own directory |

   Anything the fragment references outside that set falls back to
   `technology.generic` (an institution-specific directory convention
   with no general WOLF model, say); any `${TOKEN}` still unresolved
   after both passes is a hard error naming it, never left as a literal
   placeholder in a run's actual setup.yaml.
3. **Inject the PDK's full catalog**, if the technology package declares
   tracks: `library_sets.<corner>.library_files.<track>.<vth>`,
   `init_physical_files.lef_files.<track>.<vth>`, and
   `std_cell_GDS_files.<track>.<vth>` -- every track/vth/corner the
   package declares, not just the one this run selected, so the same
   `get_flow_config` call works regardless of which `$trk`/`$vth` a
   flow's own Tcl happens to be given. These three keys and their
   nesting are fixed, confirmed against a real legacy `synthesis.tcl`'s
   own `get_flow_config` calls -- not WOLF's invention. Metal stack is
   *not* an indexed level here (confirmed the same way): WOLF resolves
   it to one value across the whole catalog before injecting, the same
   way `${DESIGN_NAME}` is already a single resolved scalar rather than
   every design WOLF has ever heard of. `verilog_models`/`spice_models`/
   `qrc_techfiles` have no confirmed `get_flow_config` access pattern
   yet, so nothing is injected for them.

Whenever `setup_template` is overridden this way, WOLF's own
`mmmc.tcl`/`technology.tcl` generation (plain Tcl variables read out of
`flow-config.tcl`, not `get_flow_config`) is skipped entirely -- a
project whose real flow already reads library/corner data back via
`get_flow_config` out of `setup.yaml` never needs WOLF's separate
generation for that at all.

## scripts.\<N\>/scripts.latest

The flow *scripts* (`presentation.tcl`, `common_flows.tcl`,
`common_steps.tcl`, `synthesis.tcl`, `floorplanning.tcl`, `cts.tcl`,
`route.tcl`, `postroute.tcl` -- the real step definitions) are snapshotted
into a deduplicated, numbered `scripts.<N>` directory directly under the
run directory (`<workspace>/<design>/<design>.<process>/<design>.<N>`,
confirmed real legacy convention: every run is numbered starting at `.1`,
there is no unnumbered run alongside them, and nothing lives one level
deeper under a `backend/<name>` subdirectory the way an earlier revision
of this had it), with a `scripts.latest` symlink always pointing at the
current one -- mirroring the legacy Bash runner's own `PROCESS_SCRIPTS`
snapshot mechanism (`bin/wolf.run`). The dedup digest covers only these
files: unrelated per-run resolved values (thread count, design name, ...)
never force a new snapshot, and an unchanged flow reuses its existing
`scripts.<N>` across runs. Everything else this run needs (`sources.tcl`,
`technology.tcl`, `overrides.tcl`, `constraints.sdc`, `flow-config.tcl`,
and the rendered `flow.<design>.yaml`, plus `setup.<design>.yaml` when a
`setup_template` override is given) is written directly into the run
directory, fresh on every call.

`flow-config.tcl` holds the plain `set` statements the flow's step bodies
read (design name/top, thread count, dont-use cell list, physical view
paths, reports/outputs directories); see `synthesis.tcl`'s own header
comment for the exact list.

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
files, emitted in `technology.tcl`. Technology and cell LEFs, RC
setup/extraction files, and GDS are retained as package-resolved physical
inputs and are validated when a physical stage requests them; they are not
required for technology-independent HDL elaboration.

## Thread configuration and step presentation

`flow.tcl`'s `elaborate` step sets `max_cpus_per_server` when a thread count
is resolved. WOLF's own canonical `resources.threads` wins when set;
otherwise it honors `GENUS_NUM_CPUS` if the environment's `env:` map
declares it -- a long-standing Cadence-flow convention, recognized here as
backend-native policy (read from the resolved, reproducible `env:` map,
never the ambient process environment). Neither present means no attribute
is emitted and Genus keeps its own default. The resolved value (or `null`)
is recorded in `genus-inputs.yaml` as `max_cpus_per_server`.

`presentation.tcl`'s `wolf_step`/`wolf_sep` procs print an ANSI-colored title
and divider around each step -- freshly written, inspired by the concept of
bracketing each step with a colored banner rather than derived from any
specific flow's script content. This only affects Flowtool's own subprocess
stdout; it has no relation to `wolf.ui`/Rich, which governs the Python CLI's
own terminal output.

## Synthesis flows

By default, `flow.name` selects `genus-elaboration`: run only the
`elaborate` step. Three additional flow names run further stages:

| `flow.name`         | Stages run (in order)                    | Netlist written           |
|----------------------|-------------------------------------------|---------------------------|
| `genus-elaboration`  | `elaborate`                                | *(none)*                  |
| `genus-syn-generic`  | `elaborate`, `syn_generic`                 | `outputs/<design>.generic.v` |
| `genus-syn-map`      | `elaborate`, `syn_generic`, `syn_map`      | `outputs/<design>.mapped.v`  |
| `genus-syn-opt`      | `elaborate`, `syn_generic`, `syn_map`, `syn_opt` | `outputs/<design>.opt.v` |

An unrecognized `flow.name` is rejected before any input is written.
`flow.name` is shorthand for a common "elaborate through X" range over the
real primitive, `-from`/`-to` -- see
[Checkpointing and resuming a run](#checkpointing-and-resuming-a-run).

Point an environment at a synthesis flow the same way as any other flow
package:

```yaml
flow:
  package: flow/genus-syn-generic   # or an inline {name: genus-syn-generic, backend: cadence-flowtool}
```

To declare dont-use cells, add `synthesis.dont_use` to the technology
package's metadata alongside its existing `timing`/`physical` sections:

```yaml
metadata:
  technology:
    name: tsmc65
    synthesis:
      dont_use:
        - "*_lvt"
```

## Checkpointing and resuming a run

Flowtool itself -- not WOLF -- checkpoints each step (`-write_db` on every
`create_flow_step` above) and resumes from one (`-from <step>` loads the
nearest preceding checkpoint automatically). WOLF's own job is only to tell
Flowtool which range to run:

```bash
wolf run --environment my-environment -from syn_map -to syn_map
```

runs only `syn_map`, letting Flowtool load the `syn_generic` checkpoint
rather than WOLF re-running `elaborate`/`syn_generic` itself. Without
`-c`/`--clean`, a run reuses the same numbered run directory, so an earlier
invocation's checkpoints are still there for a later `-from`.

`flow.name` remains a shorthand for the common "elaborate through X" range
when `-from`/`-to` are not given (`genus-syn-map` == `-from elaborate -to
syn_map`) -- but `-from`/`-to` are the real primitive underneath it, and
take precedence whenever given explicitly. Combine with `--interactive` to
inspect a resumed run (e.g. `gui_show`) once it finishes.

### Validating this before a real, expensive run

Before trusting `-from`/`-to` resume on a design that takes hours, prove the
write_db/read_db bridge on a small, fast stub design first (this must be
run on Kona against real Flowtool/Genus -- nothing here can validate it):

```bash
wolf run --environment my-stub-environment -from elaborate -to syn_generic
wolf run --environment my-stub-environment -from syn_map -to syn_map
wolf run --environment my-stub-environment -from syn_opt -to syn_opt
```

Confirm: the second and third commands' logs show no `read_hdl`/`elaborate`
and no `SYNTH-27`-style state-loss errors; `syn_map`/`syn_opt` each complete
against the design state the prior stage actually left behind (check a
report or two, not just a clean exit); and `scripts.<N>` stays at the same
number across all three invocations (the flow scripts didn't change).
Report back the exact commands and their outcomes before relying on this
for the real design.

## Physical views, floorplan DEF, and MMMC

When the technology package declares `physical.technology_lefs` and/or
`physical.cell_lefs`, the `elaborate` step becomes physical-aware
automatically: it loads those LEFs before elaboration and runs `init_design`
right after. Declaring `constraints.floorplan_def` in `wolf.yaml`
additionally reads a placed floorplan DEF once the physical design is
initialized; it is rejected up front if no physical views are configured,
since there would be no physical database for the DEF to load into.

```yaml
constraints:
  floorplan_def: ./floorplans/demo.def
```

### Multi-corner (MMMC) technology packages

A technology package may declare several named timing corners instead of one
flat `timing.libraries` list:

```yaml
metadata:
  technology:
    name: tsmc65
    timing:
      corners:
        typical:
          libraries: [Front_End/.../tcbn65lplvttc1d0_ecsm.lib, ...]
        worst_case:
          libraries: [Front_End/.../tcbn65lplvtwc_ecsm.lib, ...]
          qrc_tech_file: PVS_QRC/.../qrcTechFile   # optional, per corner
```

`timing.corners` and `timing.libraries` are mutually exclusive -- declare
either a single flat list (unchanged, existing behavior) or several named
corners, not both. Each corner becomes its own real Genus MMMC library set,
timing condition, (optional) RC corner, delay corner, constraint mode, and
analysis view, written to a generated `mmmc.tcl` and loaded via `read_mmmc`
instead of `technology.tcl`'s plain `set_db library`. Every declared corner
is active for both setup and hold checks in the generated
`set_analysis_view` -- WOLF does not infer which corner is electrically
slow/fast from its name or voltage, so this is the conservative default
(check timing against all of them, for both checks).

This is the fix for the real failure mode a single flat list has: TSMC-style
split liberty files often reuse the same cell names across what are actually
different corners (e.g. a `*tc1d0*` "typical" file and a `*wc*` "worst case"
file both defining `AN4D2LVT`). Genus's library loader silently resolves a
same-named collision by keeping the first-loaded definition and discarding
the rest (`LBR-22`), so a flat multi-file list that mixes corners discards
an entire corner's cells without raising an error -- timing then reflects
only whichever corner's files loaded first, not every corner combined.
Splitting corners into separate named library sets (confirmed against a
real multi-corner `tsmc65` run through real `genus`/`flowtool`) keeps each
corner's cells intact; any remaining `LBR-22` warnings after that reflect a
narrower, same-corner library-curation question (TSMC's own multi-rail
level-shifter cells are sometimes re-declared across more than one of a
single corner's own split files) rather than cross-corner contamination.

Once MMMC is active, two Genus behaviors are not optional, and `synthesis.tcl`
accounts for both (each confirmed against the real failure before fixing it):
`init_elaborate` always calls `init_design` (Genus otherwise refuses
`syn_generic` with "Please use init_design command prior to syn_gen
command", regardless of whether physical/LEF views are configured), and
`create_cost_group` calls `set_interactive_constraint_modes [all_constraint_modes]`
before its `group_path` calls (Genus otherwise refuses with "SDC command
requires a constraint mode specification" once more than one constraint
mode exists). `init_elaborate` also skips its own plain `read_sdc` when MMMC
is active, since each corner's `create_constraint_mode -sdc_files` already
points at the same generated `constraints.sdc`.

`write_design -innovus` carries MMMC through to the handoff automatically
(it writes its own `<design>.mmmc.tcl` alongside the netlist/SDC/init
script, listing every corner) -- `genus_to_innovus` needed no changes for
this.

### Physical views, floorplan DEF, and MMMC

When the technology package declares `physical.technology_lefs` and/or
`physical.cell_lefs`, the `elaborate` step becomes physical-aware
automatically: it loads those LEFs before elaboration and runs `init_design`
right after. Declaring `constraints.floorplan_def` in `wolf.yaml`
additionally reads a placed floorplan DEF once the physical design is
initialized; it is rejected up front if no physical views are configured,
since there would be no physical database for the DEF to load into.

```yaml
constraints:
  floorplan_def: ./floorplans/demo.def
```

## Extra constraints (`constraints.files`/`constraints.lines`)

`constraints.clocks` is the only structured input WOLF resolves into SDC
itself. For anything else -- false paths, disabled timing, case analysis,
any other timing exception -- `wolf.yaml` can supply raw SDC content, which
is appended to `constraints.sdc` verbatim, after the generated clocks, and
never parsed or interpreted by WOLF (the same ignorance boundary as the
`env:`/`inject` passthroughs):

```yaml
constraints:
  clocks:
    - name: core_clock
      port: clk_i
      period_ps: 10000
  files:
    - ./constraints/efpga_exceptions.sdc
  lines:
    - 'set_case_analysis 0 [get_ports test_mode]'
```

`files` entries are resolved relative to the environment's own directory
(the same rule as `constraints.floorplan_def`); each file's content is
required to exist at run-preparation time and is recorded in both the
run manifest and provenance under `constraints.files`/`constraints.lines`.

## Interactive runs

Passing `--interactive` to `wolf run` (cadence-flowtool declarative runs
only) passes Flowtool's own `-interactive` flag through. Batch mode (the
default) omits it, so Flowtool's own process status stays a reliable
pass/fail signal for automation.

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

When present, `prepare_genus_inputs` writes `overrides.tcl`; the
`elaborate` step sources it before HDL is read or the design is elaborated,
so overrides take effect before Genus touches the design. Override values
must be scalars (string, number, or boolean); the resolved key/value pairs
are also recorded in `genus-inputs.yaml` and frozen run provenance. Unknown
keys under `backend.cadence-flowtool` or `backend.cadence-flowtool.genus`
are rejected rather than silently ignored.

Preparation is exposed by `wolf.backend.cadence_genus.prepare_genus_inputs`
and is intentionally separate from the legacy Flowtool shell runner. For
declarative `cadence-flowtool` environments, the run bridge validates
Flowtool before allocation, writes directly under the exact numbered run,
freezes `wolf.resolved.yaml`, and invokes Flowtool once *per stage* in the
requested `-from`/`-to` range (never one call spanning several stages),
mirroring the legacy Bash runner's own per-stage loop:

```text
cd <workspace>/<design>/<design>.<process>/<design>.<N>
flowtool -files scripts.<N>/flow.<design>.yaml -run_tag <design>.<N> \
  -from syn_generic -to syn_generic -directory <workspace>/<design>/<design>.<process> \
  -log flowtool.syn_generic.log
flowtool -files scripts.<N>/flow.<design>.yaml -run_tag <design>.<N> \
  -from syn_map -to syn_map -directory <workspace>/<design>/<design>.<process> \
  -log flowtool.syn_map.log
flowtool -files scripts.<N>/flow.<design>.yaml -run_tag <design>.<N> \
  -from syn_opt -to syn_opt -directory <workspace>/<design>/<design>.<process> \
  -log flowtool.syn_opt.log
```

Every per-invocation flag (`-interactive` in particular) is repeated on
every one of these calls, not just the first: Flowtool itself drops
`-interactive` past the first stage of a single call spanning several
stages, so a `wolf run --interactive -from syn_generic -to syn_opt` that
issued one wide-range call would silently fall out of interactive mode
partway through. The sequence stops at the first stage whose Flowtool
invocation exits nonzero, matching the legacy runner.

Before invoking Flowtool, `wolf run` prints a categorized pre-run summary
(design options, technology specification, workspace, inputs, flow
configuration, run sequence, execution backend) and asks for confirmation,
mirroring the historical Bash runner's summary and prompt. Pass `-y`/`--yes`
to skip it. `wolf run --plan` prints the same summary without prompting or
invoking Flowtool.

Preparation-only plans validate and report prospective paths without
allocating a run or invoking Flowtool. WOLF must validate `flowtool`, the
institution's Flowtool templates, and any explicitly configured technology
files before allocating a run. Physical views are not inferred or bundled
by WOLF; missing Liberty, LEF, QRC, or equivalent inputs must be reported
and the technology selected explicitly.

No licensed-tool execution is part of the local unit suite: the shared
`flow.tcl`/`presentation.tcl` are exercised under a crude Tcl stand-in for
`create_flow_step` (proves syntax validity and step-body behavior only --
see `tests/test_cadence_genus.py`'s `GenusFlowTclSyntaxTests`), not real
Flowtool. Real Flowtool/Genus execution, and in particular the
checkpoint/resume behavior this document describes, can only be validated
on Kona -- see
[Validating this before a real, expensive run](#validating-this-before-a-real-expensive-run).

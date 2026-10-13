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
[`flows/cadence-genus/synthesis.tcl`](../flows/cadence-genus/synthesis.tcl),
[`flows/cadence-genus/common_flows.tcl`](../flows/cadence-genus/common_flows.tcl),
[`flows/cadence-genus/common_steps.tcl`](../flows/cadence-genus/common_steps.tcl), and
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

### Flow identity, printed automatically once setup finishes

`flow-config.tcl` is Flowtool's own last `user_flow_steps` entry (see
`flow.template.yaml`), sourced after every `create_flow`/`create_flow_step`
above it has already registered -- the natural point for "run this once
setup finishes, before control passes to the user". Its tail prints a
content-hash identity banner automatically: a short hash for the whole
bundled flow plus one per real `create_flow_step`, so two runs' logs can
tell exactly which step's Tcl changed, not just that something did
(`wolf.backend.cadence_genus.flow_step_digests`). The same banner also
prints on the WOLF side (`wolf.commands.run._print_flow_identity`) right
after the run returns -- success or failure -- since nothing inside
Flowtool's own Tcl session is guaranteed to run on every exit path.

The banner deliberately does **not** also call the real `report_flow`
command automatically. An earlier version of this did, and it broke a
real run: `report_flow`, invoked this early while Flowtool is still
sourcing `user_flow_steps`, throws Flowtool's own internal Tcl error
("expected boolean value but got `\"\"`") -- some Flowtool db attribute
`report_flow` depends on apparently isn't initialized yet at this point
in setup. `report_flow` is a native Flowtool command outside WOLF's
control, so rather than guess at exactly which attribute or when it
becomes safe, the fix is to not call it automatically at all; type
`report_flow` by hand once control reaches the prompt if you want its
own output.

### Steps

Every real Cadence Stylus reference-flow step this flow performs is its
own separately named, separately checkpointable `create_flow_step` --
deliberately *not* merged into one big elaboration step, so a project can
comment out, reorder, or override any single one without touching the
rest, matching the reference flow's own step-by-step YAML structure:

```text
syn_generic:  block_start avoid_module_renaming read_mmmc apply_clock_derate
              read_physical read_hdl elaborate uniquify_modules
              preserve_blocks preserve_instances read_power_intent
              run_init_design read_def init_genus set_dont_use
              prevent_flattening max_routing_layer commit_power_intent
              create_cost_group run_syn_generic block_finish report_synth
syn_map:      block_start init_genus set_dont_use run_syn_map block_finish
              report_synth genus_to_lec
syn_opt:      block_start init_genus run_syn_opt block_finish report_synth
              genus_to_lec genus_to_clp genus_to_innovus
              build_sim_testbench build_xsim_files
report_synth: report_start init_genus report_area_genus
              report_timing_summary_late_genus report_late_paths
              report_power_genus report_hierarchy_genus
              report_messages_genus report_finish
```

(`report_synth` is itself a reusable sub-flow, referenced by name inside
each of the three stages above -- it runs after every stage, not only the
last one, so PPA is visible at each point. See
[`synthesis.tcl`](../flows/cadence-genus/synthesis.tcl) and
[`common_flows.tcl`](../flows/cadence-genus/common_flows.tcl).)

`-write_db` sits on `elaborate`, `run_init_design`, `run_syn_generic`,
`run_syn_map`, `run_syn_opt`, `block_finish`, and `genus_to_innovus` --
Flowtool checkpoints immediately after each one's real work, in the same
live session -- see
[Checkpointing and resuming a run](#checkpointing-and-resuming-a-run).
`init_genus`/`set_dont_use` re-run at the start of `syn_map`/`syn_opt` too
(not only `syn_generic`), since each stage now executes as its own
Flowtool/Genus invocation (see
[Why -interactive and friends apply per stage](#why-interactive-and-friends-apply-per-stage))
that restores a checkpoint rather than inheriting a live session.

### Steps WOLF does not resolve a value for yet

`apply_clock_derate`, `preserve_blocks`, `preserve_instances`,
`read_power_intent`, `max_routing_layer`, and `commit_power_intent` are
real, always-present, always-run steps -- not commented out, not left
undefined -- but each is guarded on a `wolf_*` value
(`wolf_clock_derate_early`/`_late`, `wolf_preserve_blocks`,
`wolf_preserve_instances`, `wolf_power_intent_file`,
`wolf_max_routing_layers`) that `flow-config.tcl` always emits empty today,
since no PDK/environment/design field resolves one yet. A guarded step
quietly skips (prints which value is missing) rather than erroring; wiring
one in later means resolving the value in `wolf.environment`/
`wolf.backend.cadence_genus`, not editing `synthesis.tcl`.

`genus_to_lec`, `genus_to_clp`, `build_sim_testbench`, and
`build_xsim_files` are real, always-invokable steps too, but their bodies
are intentionally left as extension points (banner + `wolf_inject_for_step`
only, same precedent as the reference flow's own `block_start`) rather
than WOLF fabricating Conformal LEC/CLP dofile syntax or a testbench/
compile-script shape it has no visibility into. Fill one in via
`backend.cadence-flowtool.inject.<step>.<pre|post>`, or fork this flow
(`wolf flow init`) and write the real command directly.

Still genuinely not modeled anywhere in WOLF's resolved context, and so
not present even as a guarded extension point: multi-corner MMMC
*generation* beyond what `wolf.environment`'s technology catalog already
resolves (named analysis views/delay corners are supported; see
[Physical views, floorplan DEF, and MMMC](#physical-views-floorplan-def-and-mmmc)).

**`read_physical`/`init_design`** (physical-aware synthesis, gated
automatically on the technology package declaring LEF views) and
**`read_def`** (a floorplan DEF, via `constraints.floorplan_def`) are both
real and resolved today -- see
[Physical views, floorplan DEF, and MMMC](#physical-views-floorplan-def-and-mmmc).

### Implementation (Innovus) flows: floorplan/prects/cts/postcts/route/postroute

[`floorplanning.tcl`](../flows/cadence-genus/floorplanning.tcl),
[`cts.tcl`](../flows/cadence-genus/cts.tcl),
[`route.tcl`](../flows/cadence-genus/route.tcl), and
[`postroute.tcl`](../flows/cadence-genus/postroute.tcl) carry the real
Innovus commands the reference flow's own YAML spells out verbatim
(`CMD_set_cong_aware`, `CMD_check_place`, `CMD_check_design_cts`,
`CMD_check_placement`, `run_place_opt`, `add_clock_tree`, `run_route`,
`run_opt_postroute`, ...), plus a shared `report_floorplan`/`report_prects`/
`report_postcts`/`report_postroute` reporting sub-flow (same reuse pattern
as `report_synth`) and a `signoff` entry point.

Several steps are, deliberately, extension points rather than guessed
content: `add_post_syn_constraints`, `create_fplan`,
`add_clock_route_types`, and `PPA_recipe_set_path_group_options` need
project-specific data (die size, post-synthesis constraint patches,
non-default clock routing rules) WOLF does not resolve; `lec`, `DRC`,
`LVS`, `create_virtuoso_lib`, `innovus_to_tempus`, `innovus_to_quantus`,
and `schedule_signoff_subflows` depend on Conformal/Calibre/Tempus/Quantus
conventions WOLF has no visibility into.
`report_early_summary_innovus`/`report_early_paths`/
`report_late_summary_innovus` are also extension points -- not because
nothing is known about them, but because the real read-only Innovus
command for a timing *summary* (`timeDesign`, in some modes) can also
perform real optimization as a side effect, and guessing the wrong flag
combination risks silently changing the design rather than just erroring.

`wolf run -from floorplan -to postroute` (or any single implementation
stage) drives this exactly the way `-from syn_generic -to syn_opt` drives
Genus: `run_genus`/`allocate_genus_run` are not Genus-specific despite the
name -- `STAGE_ORDER` now spans `SYNTHESIS_STAGES +
IMPLEMENTATION_STAGES`, and the same per-stage loop invokes the real
`flowtool` binary once per stage regardless of which section it's in,
never `genus`/`innovus` directly. A synthesis-only or implementation-only
`-from` with no `-to` still defaults to the end of its *own* section
(`-from syn_map` still means "through syn_opt"; `-from floorplan` alone
means "through postroute") -- adding the implementation stages to
`STAGE_ORDER` does not change what an existing bare `-from`/`-to` meant.
Giving both ends explicitly can still cross sections (`-from syn_generic
-to postroute` for the whole `block`).

Continuing from synthesis into implementation reuses the exact same
numbered run and provenance record -- `wolf run -from syn_opt` today,
`wolf run -from floorplan` tomorrow, same `<design>.<N>` directory, same
`wolf.resolved.yaml` (see `volatile_keys` in
[ENVIRONMENTS.md](ENVIRONMENTS.md)). A stage from `floorplan` onward is
rejected up front (before Flowtool is even invoked) if the technology
package declares no LEF/RC -- Innovus cannot do anything physical without
them, unlike Genus's synthesis stages where physical views are optional.

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
`physical.cell_lefs`, the `read_physical` step becomes active automatically
and loads those LEFs before `elaborate`; `run_init_design` then runs
`init_design` right after elaboration. Declaring `constraints.floorplan_def`
in `wolf.yaml` additionally reads a placed floorplan DEF (the `read_def`
step) once the physical design is initialized; it is rejected up front if
no physical views are configured, since there would be no physical
database for the DEF to load into.

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
`run_init_design` always calls `init_design` (Genus otherwise refuses
`syn_generic` with "Please use init_design command prior to syn_gen
command", regardless of whether physical/LEF views are configured), and
`create_cost_group` calls `set_interactive_constraint_modes [all_constraint_modes]`
before its `group_path` calls (Genus otherwise refuses with "SDC command
requires a constraint mode specification" once more than one constraint
mode exists). `elaborate` also skips its own plain `read_sdc` when MMMC
is active, since each corner's `create_constraint_mode -sdc_files` already
points at the same generated `constraints.sdc`.

`write_design -innovus` carries MMMC through to the handoff automatically
(it writes its own `<design>.mmmc.tcl` alongside the netlist/SDC/init
script, listing every corner) -- `genus_to_innovus` needed no changes for
this.

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

## Checking run status without an embedded terminal

`wolf status --environment NAME` (an existing, backend-agnostic command,
`wolf/status.py`) now works for a declarative-v1 Genus run. Rather than
embedding a live interactive pane inside a wrapping TUI -- which would
need full PTY/terminal emulation to keep `--interactive`'s arrow-key
history and autocomplete working inside Genus's own prompt, real
complexity this doesn't need -- `wolf run --interactive` is left
completely untouched (still inherits the real tty directly), and `wolf
status` is a separate, cheap, repeatable query you run in another
terminal/tab, exactly the way you'd run `watch -n 2 wolf status
--environment NAME` to keep an eye on progress without disturbing the
interactive session.

Two pieces make this work, both in `cadence_flowtool.py`/`cadence_genus.py`:

- **`stages()`** returns `STAGE_ORDER` (every Genus and Innovus stage
  name), the fixed, ordered list `wolf status` reports against.
- **`infer_stage_results(run_directory)`** calls `genus_run_status`, which
  reads Flowtool's own real per-run execution record directly off disk --
  `<run_directory>/flow.status` -- rather than shelling out to `flowtool
  ... -status`. Confirmed real against an actual run: one Tcl dict per
  line (a `{script flowtool status invoked ...}` line marks one flowtool
  invocation boundary and is skipped; every other line is one step's
  status transition, carrying a `status` word, an `errors` list, and a
  nested `steps_run` dict whose own `str` field is the step's real
  **canonical dotted path**, e.g.
  `block.synthesis.syn_generic.report_synth.report_finish`). A plain file
  read, no Tcl instrumentation and no subprocess call needed at all; a
  missing `flow.status` (nothing has invoked Flowtool yet) degrades to
  `("", {})` rather than raising. `run_genus` also now records
  `resolved["backend"] = {"name": context.backend}` in the frozen
  manifest (`wolf status`'s own backend lookup needs it) and maintains
  `<environment_directory>/run.latest.d` (the same symlink convention the
  legacy shell runner and `wolf status`'s `_latest_for_environment`
  already share), so `wolf status --environment NAME` finds a Genus run
  with no new resolution path of its own.

`load_status` only ever asks `stages()` for the fixed `STAGE_ORDER` list
(`syn_generic`, `syn_map`, ...), but `flow.status` only ever reports
per-real-leaf-step detail, keyed by canonical path -- `rollup_stage_states`
fills each `STAGE_ORDER` name in from `stage_canonical_paths(stage)`, the
real `create_flow` membership tree (`flow_membership`, parsed by
brace-matching `common_flows.tcl`'s own `create_flow -name X {members}`
calls, not guessed) walked while keeping every intermediate flow name as
its own path segment, exactly matching how `flow.status` itself qualifies
a step. Building the underlying tree-reachability check caught a real,
previously invisible bug: `init_implementation` and `add_tracks` (real
steps in `floorplanning.tcl`) were never referenced by `floorplan`'s own
member list in `common_flows.tcl`, meaning Flowtool would never load the
Genus handoff database before `wolf run -from floorplan` tried to do
anything in Innovus; fixed.

The open question from an earlier draft of this is now resolved: a step
name like `block_start` is reused by several different stages (one
shared real `create_flow_step`, invoked separately inside each), and
`flow.status`'s canonical paths *do* disambiguate that --
`block.synthesis.syn_generic.block_start` is a distinct path from
`block.synthesis.syn_map.block_start` -- confirmed against a real run's
own `flow.status`. `stage_canonical_paths` produces exactly that
qualified form per stage, so `rollup_stage_states` only ever rolls up a
stage's own steps, never an unrelated stage's run of a same-named one.

`genus_run_status` also overlays `wolf.step-status`'s own live,
bare-name-keyed data (see the "live per-step status" section below) onto
`flow.status`'s canonical-path states, scoped to the active flowtool
invocation's own `-from`/`-to` stage range (parsed from `flow.status`'s
own most recent `{script flowtool status invoked ...}` marker). Two real
gaps this closes, both hit continuing an actual run: a path whose only
known state is a *stale* "failed" from a previous, now-fixed attempt is
demoted to "running" once a fresh invocation covering it starts; and a
stage `flow.status` has logged **nothing at all** for yet -- not even a
stale failure -- is *promoted* from absent/"unknown" to "running" the
moment `wolf.step-status` shows real progress (hit continuing past
`syn_map` into `syn_opt`: `flow.status` had no `syn_opt` entries
whatsoever, so `syn_opt` stayed "unknown" and `wolf status --watch`'s
expanded tree, which only ever queries whichever stage the rollup says
is "running", never appeared at all, despite `wolf.step-status` already
showing real progress). Both are deliberately scoped to the active
invocation's own stage range, not applied blindly across every
`STAGE_ORDER` name -- `wolf.step-status` is keyed by bare step name, and
a name several stages share (like `block_start`) would otherwise falsely
promote an unrelated, not-yet-reached stage too.

`extract_metrics(run_directory)` reads Flowtool's own `flow.metrics`
(confirmed real, present on disk alongside `flow.status`): a single JSON
object whose top-level `metrics` list describes the *current*
in-progress snapshot (including `flowtool.status`, Flowtool's own
free-text one-line summary of what's running right now), `total_real`/
`total_cpu` are the whole flow's cumulative wall/CPU seconds so far, and
`snapshots` holds one entry per *completed* child stage at the current
nesting level with its own real timing. `genus_run_metrics` parses this
into `wolf status`'s Metrics section (flow elapsed/CPU time, memory,
peak memory, the live activity line) and an internal
`stage_elapsed_seconds` convention key that `load_status` uses to fill
`StageResult.elapsed_seconds` for a Cadence run's completed stages --
unlike a generically-tracked `wolf.stage-results` run, a Flowtool
invocation has no other source of real per-stage timing.

### `wolf status --watch`

`watch -n 2 wolf status` strips Rich's own color/formatting (it's piping
plain terminal output through an external process with no ANSI
awareness), so `wolf status` instead has its own built-in auto-refresh:
`--watch` re-renders a fresh panel in place via `rich.live.Live` until
the run reaches a terminal state, with a live spinner on the actively
running stage. When something is running, it also asks the active
backend for `stage_step_detail(run_directory, stage)` -- for Cadence/
Flowtool, the real `create_flow` membership tree one level under that
stage, each member's own current state (a leaf step's canonical-path
state directly, or a nested sub-flow's own rollup) -- and renders it as
an expanded tree under the stage, spinner included. A backend with no
finer-than-stage granularity (ORFS, tracked only via
`wolf.stage-results`) returns no detail, and the watch panel simply
omits the tree.

### Live per-step status independent of Flowtool's own buffering

Confirmed real on an actual run: Flowtool's own `flow.status`/
`flow.metrics` are **not** promptly updated per step when a step runs as
part of a manually-typed `run_flow` at an interactive Genus/Innovus
prompt -- `flow.status` sat completely unchanged for over an hour while
the console clearly showed several real steps completing one after
another (Flowtool's own writes there are tied to its driver loop
regaining control between steps, not to each step itself; they still
update promptly for a normal non-interactive `-from`/`-to` invocation,
or an interactive session where Flowtool itself steps through each
`create_flow_step` one at a time rather than the user calling `run_flow`
directly). Left alone, this meant `wolf status --watch`'s expanded tree
would go stale for exactly as long as a `run_flow` call was in flight --
precisely when live progress is most useful to see.

`presentation.tcl` fixes this by wrapping Flowtool's own native
`create_flow_step` (renamed to `::wolf_native_create_flow_step`) so
every real step -- without any of their own bodies being touched --
also writes a line to `<run_directory>/wolf.step-status`
(`<step_name>|starting|<time>`, then `|success|` or `|failed|`) as it
executes. The body is identified by its own structural property (the
one argument containing an embedded newline, since every real body in
this flow is a multi-line `{...}` block) rather than by position --
confirmed real that several steps (`elaborate`, `run_syn_generic`,
`block_finish`, ...) trail their own body with a bare `-write_db` flag,
`create_flow_step -name X -owner wolf {BODY} -write_db`, which a naive
"body is the last argument" wrapper mistakes for the body itself. A
real step failure is still re-raised via `return -options` with its
original error code/info intact, so Flowtool's own error handling sees
the exact same failure it always would have; a `wolf_write_step_status`
write failure (disk full, permissions, ...) is reported but never
allowed to break the real flow.

Each line also carries a real canonical dotted path (the same form
`flow.status` itself uses), via `presentation.tcl`'s own
`wolf_step_canonical_path` -- `get_db flow_hier_path`, confirmed real
and already in use elsewhere in this flow (`block_finish`'s own body
reads its last entry's `.name` to get the current stage name for
report file naming). `prepare_genus_inputs` truncating `wolf.step-status`
fresh per invocation makes a *bare* name safe to key by across stages
(there's only ever one stage's worth of events in it at a time), but
not safe *within* one stage: a step name can be reused at more than one
position in the same stage's own flow tree -- `init_genus` is both a
direct `syn_opt` member and one of `report_synth`'s own nested leaf
steps. Confirmed hit for real: `syn_opt`'s own already-complete direct
`init_genus` cross-matched, by bare name alone, into `report_synth`'s
own unrelated, not-yet-started nested `init_genus`, which (via
`_rollup_one_state`'s own correct "some but not all descendants
complete → running" logic) made `report_synth` falsely show "running"
too. `genus_run_step_events` now keys each event by its own canonical
path when one was recorded, falling back to the bare name only for an
older-format line (a session still running the previous
`presentation.tcl`); both `genus_run_status`'s own invocation-scoped
overlay and `stage_step_detail` check the exact path first and the bare
name second, which handles either format without needing to know which
is in effect.

`stage_step_detail` overlays this data onto `flow.status`'s own
canonical-path state, for both a stage's direct members and a nested
sub-flow's own leaf descendants, always preferring the live event when
one exists.

Each event also carries a real timestamp, so `wolf status --watch` can
show not just *that* something is running but *how long* it has been:
`genus_run_active_elapsed` derives the current invocation's own elapsed
time from `wolf.step-status`'s earliest timestamp (shown on the
currently-running stage's own row in the Stages table), and
`stage_step_detail`'s own per-leaf elapsed (its third tuple element)
does the same for whichever single step is actively running inside the
expanded tree. Both render as a blinking `HH:MM:SS` in the watch panel
-- the one visual cue that a number is actively ticking up in place,
not a stale snapshot sitting next to live spinners.

### QoR (area/timing/power) by stage

Genus already writes its own real, stable QoR reports to
`<run_directory>/reports/<kind>.<stage>.rpt` (named via `flow_report_name`,
see `common_flows.tcl`'s own header on `report_synth` -- confirmed real
against an actual run's `area.syn_generic.rpt`/`timing.syn_generic.rpt`/
`power.syn_generic.rpt`). Rather than have WOLF's own Tcl generate a
second, parallel metadata file duplicating what Genus already writes,
`genus_run_qor` parses these directly:

- **area**: the design's own top-level row (not an indented child) --
  confirmed real shape, a `---`-only separator line then one row per
  hierarchy level, the top row's own last four fields Cell Count/Cell
  Area/Net Area/Total Area regardless of how many name columns precede
  them.
- **timing**: the SETUP section's `View: ALL` row -- WNS/TNS/FEP. A
  second, DRV-section `View: ALL` line (all `N/A`, no trailing numbers)
  is skipped automatically since it has too few fields.
- **power**: the `Subtotal` row -- leakage/internal/switching/total
  watts.

Scoped to the synthesis stages for now (`syn_generic`/`syn_map`/
`syn_opt`) -- DRC/LVS/signoff reports don't exist until a run reaches
floorplan/route, a later extension once that evidence exists, not
guessed ahead of it.

Each report is Genus's own static snapshot, never rewritten once its
own step finishes, so `genus_run_qor` is mtime-cached per file (one
cheap `stat()` call either way; only a changed mtime triggers an actual
re-read/re-parse) -- re-parsing a 17000-line area report on every
`wolf status --watch` tick would be real, avoidable waste.

QoR columns (Area/WNS/TNS/Viol/Power) are merged directly into the same
Stages table rather than shown as a separate one -- QoR is the same
per-stage granularity as Status/Elapsed, so a second table repeating
the same row labels was just duplication. A report can land mid-stage
(e.g. `syn_map`'s own `area.syn_map.rpt` exists well before
`run_syn_map`/`report_synth` finish), so a "running" stage's QoR
columns genuinely can fill in before its own Status does; each column
stays `-` on its own until that one report exists.

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

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
setup finishes, before control passes to the user". It carries nothing but
that identity banner now (every resolved value the bundled flow's own step
bodies read comes from `setup.yaml` via `get_flow_config` instead -- see
"The Flowtool project descriptor" below): a short hash for the whole
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
undefined -- but each is guarded on a `get_flow_config -quiet` lookup
(`clock_derate_early`/`_late`, `preserve_blocks`, `preserve_instances`,
`power_intent_file`, `max_routing_layers`) that never resolves to
anything today, since no PDK/environment/design field supplies one yet
-- `-quiet` means the lookup simply returns `""`/empty rather than
erroring. A guarded step quietly skips (prints which value is missing)
rather than erroring; wiring one in later means resolving the value in
`wolf.environment`/`wolf.backend.cadence_genus` (so it's injected into
`setup.yaml`), not editing `synthesis.tcl`.

`genus_to_lec`, `genus_to_clp`, `build_sim_testbench`, and
`build_xsim_files` are real, always-invokable steps too, but their bodies
are intentionally left as extension points (banner + `wolf_inject_for_step`
only, same precedent as the reference flow's own `block_start`) rather
than WOLF fabricating Conformal LEC/CLP dofile syntax or a testbench/
compile-script shape it has no visibility into. Fill one in via this
design's own `setup.<design_name>.yaml` `inject.<step>.<pre|post>` key
(see "Design-level setup.yaml" below), or fork this flow
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
non-default clock routing rules) WOLF does not resolve --
[`create_fplan.template.tcl`](../flows/cadence-genus/create_fplan.template.tcl)
is a generic baseline for `create_fplan` specifically (die/core sizing, PG
net bring-up, a parameterized stripe stack, and the save step are generic;
macro/tile placement and pin assignment are explicitly left as a fill-in
section, since those are inherently design-specific); `lec`, `DRC`,
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

## The Flowtool project descriptor (flow.yaml) and setup.yaml

WOLF ships its own generic `flow.yaml` Flowtool project descriptor
(`flows/cadence-genus/flow.template.yaml`) and its own generic
`setup.yaml` template (`flows/cadence-genus/setup.template.yaml`), and
uses both by default -- no institution-supplied file is required.
`flow.yaml` only lists this flow's real Tcl scripts (`default_flow_steps`)
and points Flowtool at the per-run `flow-config.tcl` (`user_flow_steps`);
the actual flow sequencing is Tcl's own `create_flow`/`create_flow_step`
in `common_flows.tcl` and friends, not a yaml step tree, so this file
never needs anything technology-, library-, or institution-specific.

Every run also gets a real `setup.<design>.yaml` written into the run
directory, with `get_flow_config` access to three layers, all always
present regardless of whether the template text itself references them:

1. `design_name`/`design_top`/`tracks`/`vths`/`metal_stack`/
   `dont_use_cells`/`technology_lefs`/`cell_lefs`/`power_nets`/
   `ground_nets`/`library_sets`/`init_physical_files`/
   `std_cell_GDS_files` -- package- and environment-resolved facts,
   injected directly by WOLF (see `_catalog_document` in
   `wolf/backend/cadence_genus.py`), not via `${TOKEN}` substitution, so
   this works the same whether or not the resolved technology actually
   has a track/vth axis;
2. this run's own generated paths (`run_directory`, `reports_dir`,
   `outputs_dir`, `handoff_dir`, `sources_script`, `constraints_file`,
   and, when generated, `technology_script`/`mmmc_script`/
   `overrides_script`);
3. this design's own `setup.<design_name>.yaml` content -- see
   "Design-level setup.yaml" below -- the one layer actually meant to
   be hand-edited.

`get_flow_config` is the *only* access pattern now -- every bundled flow
step body reads every resolved value this way, including which of
`mmmc.tcl`/`technology.tcl` (still their own separate generated Tcl
files, real `create_library_set`/`set_db library` commands, not plain
data) to `source`: that choice is itself `get_flow_config -quiet
technology_script`/`mmmc_script`, same as everything else. A project's
own extension/injected Tcl gets exactly the same access, with no
per-project configuration required to get it.

A project with its own legacy institution `setup.yaml` (or wanting an
institution's existing Flowtool project descriptors instead of WOLF's
own) can still override the template pair via the same
`backend.cadence-flowtool` escape hatch used for `set_db` overrides:

```yaml
backend:
  cadence-flowtool:
    flowtool:
      setup_template: /asic/flows/wolf-registry/flowtool/tsmc65.setup.yaml.template
      flow_template: /asic/flows/wolf-registry/flowtool/tsmc65.flow.yaml.template
```

WOLF's own `design_name`/`tracks`/`vths`/`metal_stack`/catalog injection
still applies on top of an override's own content the same way it does
for the bundled default -- an override only needs to add
institution-specific keys beyond what WOLF already resolves. Both keys
are required when overriding at all (omit the whole `flowtool`
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

WOLF's own `mmmc.tcl`/`technology.tcl` generation still happens
regardless of whether `setup_template` is overridden -- they are what
WOLF's own bundled flow steps actually `source` (via `get_flow_config
-quiet mmmc_script`/`technology_script`, same as everything else).

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
and the rendered `flow.<design>.yaml` and `setup.<design>.yaml`) is
written directly into the run directory, fresh on every call.

`flow-config.tcl` holds nothing but the bundled-flow identity banner now
(see "Flow identity, printed automatically once setup finishes" above) --
every resolved value the flow's step bodies read (design name/top,
thread count, dont-use cell list, physical view paths, reports/outputs
directories, ...) comes from `setup.<design>.yaml` via `get_flow_config`
instead; see `synthesis.tcl`'s own header comment for the exact key list.

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

The same resolved thread count is also applied on the Innovus side, via
`floorplanning.tcl`'s `init_innovus` step (`set_multi_cpu_usage -local_cpu`
-- Innovus has no `set_db` equivalent). `init_innovus` re-runs at the
start of every implementation stage, since each one is a separate
Innovus invocation, so this is not a one-time setting.

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

Every `floorplan` run also always writes its own DEF snapshot back out
(`floorplanning.tcl`'s `export_floorplan_def`, between `commit_power_intent`
and `block_finish`, using the real Innovus `write_def`) to
`outputs/<design>.floorplan.def` inside the run directory -- a durable,
reloadable record independent of whatever actually built the floorplan
(`create_fplan`'s own injected Tcl, or a previously loaded
`constraints.floorplan_def`). To reuse it in a *later* run -- after
re-running synthesis, say, when there is no Innovus DB checkpoint left to
restore from -- copy it into the project's own
`inputs/floorplans/<design>/` and point `constraints.floorplan_def` at that
copy; WOLF does not promote run outputs into project inputs on its own.

### Power and ground nets (`constraints.power_nets`/`ground_nets`)

A design with no power intent (CPF/UPF) file read has no VDD/VSS nets at
all once handed off to Innovus -- `connect_global_net`/`route_special`/
`add_stripes` all fail with "net does not exist" until something creates
them. `constraints.power_nets`/`constraints.ground_nets` (each a list,
since a design can have more than one power net) set Genus's own
`init_power_nets`/`init_ground_nets` right before `init_design`
(`synthesis.tcl`'s `run_init_design`), so the real nets exist from
synthesis onward and carry through `write_design -innovus`'s own handoff
init script automatically -- no manual `create_net -physical` workaround
needed on the Innovus side. Also editable from `wolf env menu` ("Power/ground
nets"), and always resolvable via `get_flow_config power_nets`/
`get_flow_config ground_nets` regardless of how they were set (empty list
when not configured, today's unchanged default).

```yaml
constraints:
  power_nets: [VDD]
  ground_nets: [VSS]
```

### Tracked packages: technology LEF, cell LEF, and RC collateral

A *tracked* technology package (`technology.tracks.<track>.vths.<vth>`, the
TSMC65-shaped form -- see "Multi-corner (MMMC) technology packages" below
for the sibling per-corner axis) declares its own `lef` (and, optionally,
`cell_lef`) and `qrc_techfiles` per metal stack, parsed by
`environment._technology_variant`. Confirmed real against an actual tracked
package: `validate_genus`'s own physical-implementation gate
(`technology_lefs`/`cell_lefs`/`rc_files` all required non-empty) could
*never* pass for a tracked package before this was wired up --
`cell_lefs`/`rc_files` were both hardcoded empty in `environment.py`'s own
`_technology_inputs` regardless of what the manifest actually declared,
even though the real LEF and captable data was already being resolved
correctly into `technology_lefs`/`qrc_techfiles`.

- **`cell_lefs`** defaults to the same files as `technology_lefs` --
  TSMC's own standard-cell LEF deliverable is a single real *merged* LEF
  (routing-layer/site geometry and cell abstracts together), confirmed
  real, so a package that never declares a separate `cell_lef` key at all
  simply reuses `lef` for both roles rather than being required to
  redundantly repeat the same path under two keys. A package whose
  institution genuinely ships two distinct files declares `cell_lef`
  explicitly (same per-stack mapping/flat-list shape as `lef`), which wins
  over the merged default.
- **`rc_files`** is the same flattened list `qrc_techfiles` already is
  (`_resolve_qrc_techfiles`'s own cross-corner captable union, for the
  selected metal stack) -- the per-corner-named detail stays separately
  available via `qrc_corners` for anything that needs one specific
  corner's own captable, not just "is RC collateral present at all".

`validate_genus`'s own gate messages are also split per piece ("technology
LEF", "cell LEF", "technology RC" each their own check) rather than one
combined "technology and cell LEF required" message, so a real gap says
exactly which piece is missing instead of leaving someone with only one of
the two guessing which one Innovus actually lacks.

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

### Choosing which views are active in implementation (`active_views`)

Every declared analysis view is active for both setup and hold checks by
default, in Genus and (via `floorplanning.tcl`'s `init_innovus`, which
re-runs at the start of every implementation stage -- restored from the
previous stage's own checkpoint each time, so this is re-applied, not a
one-time setting) in Innovus too -- simple, but checking every corner
through every place/CTS/route iteration on a design with several corners
is far heavier than most implementation stages need. This design's own
`setup.<design_name>.yaml` (see "Design-level setup.yaml" below)
narrows it:

```yaml
active_views:
  setup: [wcl]
  hold: [bc]
```

Either key can be omitted or left an empty list, meaning "every declared
view" (today's default, unchanged). Each name must be one of the
technology package's own declared `timing.corners` keys -- an unlisted
name is rejected before Flowtool ever starts, not left to fail inside
Innovus as a confusing `set_analysis_view` error. This applies uniformly
to every implementation stage (`floorplan` through `postroute`); picking
a different set per stage (e.g. narrow through `postcts`, every corner
again at `route`/`postroute`) is not yet selectable without hand-editing
`setup.<design_name>.yaml` between stages.

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

### `wolf monitor`

A full-screen Textual TUI (`wolf.monitor_app.MonitorApp`), a richer
sibling of `wolf status --watch` -- not a replacement, since the simple,
scriptable, non-interactive panel is still the right choice for piping
to a log or running over a flaky SSH session.

Built as **one** nested tree-table, not a table alongside a separate
detail pane: a Textual `Tree` whose top-level nodes are the real stage
rows (Status/Elapsed/QoR columns, column-aligned via fixed widths
shared with the header line above it), each expandable in place into
its own step-detail children -- arrow to any stage row and press enter
to expand or collapse it, not just whichever stage is currently
running, with only one stage's detail ever shown at a time (selecting
a different row, or re-pressing enter on the same one, replaces/
collapses it; selecting a leaf step row itself is explicitly ignored,
not mistaken for a stage toggle). The currently running stage is
expanded automatically on startup. `_update_tree` rebuilds the whole
tree from `status.stages`/`stage_step_detail` on every refresh tick,
expanding only `self._expanded_stage`'s own node and leaving
everything else collapsed with no children materialized at all --
cheap, and the single source of truth for "which one stage is
expanded" stays entirely in `self._expanded_stage`, not in Tree's own
per-node state. Tree's own native toggle-on-select
(`auto_expand`) is turned off to avoid racing this rebuild.

Reuses `wolf.status`'s own formatting helpers directly
(`_format_elapsed`, `_STATE_MARKERS`, `_STATE_STYLES`) so the two views
stay visually consistent, but needed its own text-only row/label
builders: Textual's `Tree` only accepts a plain `str`/Rich `Text` for a
node label, not an arbitrary renderable, so it can't reuse
`wolf.status._step_label` (which returns a `Spinner` for a running
step, meant for `--watch`'s own `rich.live.Live` redraw loop). A
running step's own elapsed still renders with Rich's `blink` style,
which needs no animated object of its own.

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
currently-running stage's own row in the Stages table). That renders as
a blinking `HH:MM:SS` -- the one visual cue that a number is actively
ticking up in place, not a stale snapshot sitting next to live
spinners.

`stage_step_detail`'s own per-leaf elapsed (its third tuple element)
goes further than just the one actively-running step: `genus_run_step_elapsed`
and its sibling `genus_run_status_elapsed` (the same idea, from
`flow.status` instead) each track **both** a step's own `starting` and
later terminal (`success`/`failed`) timestamp for the same key, not just
the latest one -- `genus_run_step_events` only ever keeps the latest
(by design, for current status), which discards exactly the earlier
timestamp a *completed* step's own duration needs. So every leaf step in
the expanded tree shows its own real duration once it finishes, not just
the one still running -- `stage_step_detail` prefers
`genus_run_step_elapsed` (live, this invocation's own `wolf.step-status`)
and falls back to `genus_run_status_elapsed` (`flow.status`, for a step
that finished before this run's `wolf.step-status` existed, or one
genuinely driven by Flowtool's own prompt invocation where `flow.status`
itself stays prompt). A completed step's own duration renders plain, not
blinking -- only a still-running step's own live-ticking elapsed does.
One real bug caught checking this against an actual run: the fallback
chain was originally `a or b or c`, which silently treats a genuine
`0.0`-second duration as falsy and skips straight to the next fallback
-- fixed to check each source with `is not None` instead.

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

## Design-level setup.yaml

Every knob in this section (CTS cell selection, tie-offs, clock routing,
active analysis views, Genus `set_db` overrides, post-synthesis netlists,
injected Tcl) is a **design-level** tuning choice, not an environment-level
one -- it lives in its own file, not `wolf.yaml`:

```
<project.root>/inputs/env/<design_name>/setup.<design_name>.yaml
```

This file is the one place to hand-edit these for quick changes (it is
plain, native-ish-key YAML -- no `wolf_` prefix, no nesting under
`backend.cadence-flowtool`), and it is also what `wolf env set`/`wolf env
unset`/`wolf env menu` write to for exactly these keys -- `wolf.yaml`
keeps only genuinely environment-level fields (`workspace.root`,
`design.name`, `technology.*`, `flow.backend`, `constraints.*`,
`backend.cadence-flowtool.flowtool` for an institution's own Flowtool
template override). `wolf env set`/`unset` route automatically based on
the key's first segment -- a design-level key never needs
`backend.cadence-flowtool.` typed in front of it any more.

Alongside it, in the same `inputs/env/<design_name>/` directory,
`wolf.<environment_name>.yaml` is a **symlink** to that environment's own
`wolf.yaml` (kept fresh by `wolf env set`/`unset`/`auto-setup`/`menu`) --
so the environment-level configuration that produced a given project is
also readable right there, without needing to know WOLF's own
`~/.wolf/envs/` state directory path.

At `wolf run`, `prepare_genus_inputs` merges this file's content into the
real, rendered `setup.yaml` Flowtool actually reads (alongside the
always-injected catalog data -- see "The Flowtool project descriptor" and
"Multi-corner (MMMC) technology packages" above) -- so every value below
is reachable from a project's own injected Tcl via `get_flow_config`, not
only from WOLF's own bundled flow steps.

## Genus attribute overrides

Some Genus attributes are tool policy rather than package metadata or
canonical WOLF semantics, and cannot be inferred from a resolved design
(for example `hdl_max_memory_address_range`, which caps generic memory
inference during elaboration). These are supplied explicitly in this
design's own `setup.<design_name>.yaml`:

```yaml
genus_set_db:
  hdl_max_memory_address_range: 65536
```

When present, `prepare_genus_inputs` writes `overrides.tcl`; the
`elaborate` step sources it before HDL is read or the design is elaborated,
so overrides take effect before Genus touches the design. Override values
must be scalars (string, number, or boolean); the resolved key/value pairs
are also recorded in `genus-inputs.yaml` and frozen run provenance.

## CTS cell selection, timing targets, tie-offs, and clock routing

These all default to today's behaviour (CCOpt/add_tieoffs/
add_clock_route_types use their own library-wide defaults, unchanged)
when left unset, and are generic across any technology package -- WOLF
never hard-codes a cell or layer name; a project supplies its own.

**`cts_*`** -- CCOpt buffer/inverter/clock-gating cell selection and
timing targets, applied by a shared `set_cts_config` step at the start of
both `prects` (before `add_clock_spec`) and `cts` (before
`CMD_check_design_cts`), since each is a separate Innovus invocation
restored from a checkpoint and attribute persistence across that restore
is not documented (see "Settings across implementation stages" below):

```yaml
cts_buffer_cells: ["BUFX*"]           # name or pattern list
cts_inverter_cells: ["INVX*"]
cts_clock_gating_cells: ["CKGX*"]
cts_target_skew: 0.05                 # ns, optional
cts_target_max_transition_time: 0.2   # ns, optional
cts_max_fanout: 16                    # optional
```

Cell lists map directly onto Innovus's own `cts_buffer_cells`/
`cts_inverter_cells`/`cts_clock_gating_cells` (confirmed real, man 20.15):
each accepts exact names *or* patterns (`BUFX*`), expanded against the
loaded library by CCOpt itself -- WOLF does not need to query `base_cell`
attributes (`is_buffer`, ...) to offer this, and does not (no confirmed
20.15 reference for those attributes was found; guessing them risked the
same class of error `genus_turn_on_analysis_views`'s `.active` bug was).

**`add_tieoffs_*`** -- resolves `add_tieoffs_cells` (at most two: one
tie-high driver, one tie-low driver, man 20.15) and its companion
attributes, applied inside the existing `add_tieoffs` step right before
its own `[get_db add_tieoffs_cells] ne ""` guard:

```yaml
add_tieoffs_cells: ["TIEHIX1", "TIELOX1"]
add_tieoffs_honor_dont_use: true   # optional
add_tieoffs_max_fanout: 10         # optional
add_tieoffs_max_distance: 20.0     # optional, microns
```

Left unset, `add_tieoffs` stays a no-op, same as before this existed --
but a synthesized netlist with literal `1'b0`/`1'b1` connections and no
tie cells is a likely LVS/DRC problem, so `add_tieoffs` now logs a loud
`wolf_error` (not a silent skip) when nothing is configured. When cells
*are* configured, the step reports how many tie-cell instances were
actually added (`get_db insts -if {.base_cell.name == ...}`, confirmed
real query pattern, man 20.15) and runs `check_tieoffs` for a full
connectivity report. This is independent of, and coexists with, a
project's own floorplan script calling `connect_global_net -type tie_hi`/
`-type tie_lo`: that only ties *existing* tie pins on cells already in the
netlist to the power/ground rails, it does not insert any tie-cell
instances -- `add_tieoffs` is what actually inserts the driver cells for
synthesis's own literal constants, and should (and does, in the bundled
flow order) run after the floorplan script's own global net connections.

**`clock_routing_*`** -- a non-default routing rule and top/trunk/leaf
route types for `add_clock_route_types` (`CMD_set_cong_aware`'s sibling
extension point in the `prects` flow, previously always empty):

```yaml
clock_routing_width_multiplier: {"M6:M5": 2.0}
clock_routing_spacing_multiplier: {"M6:M5": 2.0}
clock_routing_types:
  trunk: {route_rule: true, top_preferred_layer: M6, bottom_preferred_layer: M5}
  leaf: {route_rule: true, top_preferred_layer: M4, bottom_preferred_layer: M3}
```

Maps directly onto `create_route_rule -width_multiplier/-spacing_multiplier`
and `create_route_type -route_rule/-top_preferred_layer/
-bottom_preferred_layer` (both confirmed real, man 20.15), then
`set_db cts_route_type_<name>` for each configured type. Layer names are
used exactly as given -- WOLF has no layer list to validate against at
config-generation time (that only exists once Innovus has loaded the
tech LEF) -- so `add_clock_route_types` itself validates every configured
layer against `get_db layers .name` and raises a clear error naming the
unknown layer before CTS ever runs, rather than a confusing failure deep
inside `create_route_rule`/`create_route_type`. `commit_route_types`
(`commit_clock_tree_route_attributes`) needed no changes: confirmed safe
whether or not any route type exists.

### Picking cell/layer/view names interactively (`wolf env menu`)

Hand-editing YAML to fill in `cts.buffer_cells`/`tieoffs.cells`/
`clock_routing`'s layer names means typing exact names from a library you
have to go look up separately. `wolf env menu`'s "CTS / tie-off /
routing cells..." row (shown once `flow.backend: cadence-flowtool` is
set) picks them interactively instead, against the real names the
selected technology package actually declares:

- **CTS buffer/inverter cells** (default, and the `_top`/`_leaf`
  variants), **clock-gating cells**, and **tie-off cells** (capped at
  two in the UI itself): a live checklist, not a type-a-pattern-then-
  decide flow. Selecting the field loads every cell name the resolved
  technology's own LEF files declare (names and area only) in a
  background worker -- a "Parsing \<file\>..." message names each file
  while a real, uncached scan is in progress, skipped entirely on a
  cache hit -- then every cell shows as a `[ ]`/`[x]` checkbox. Typing in
  the filter box narrows which entries are *shown*, live, while checked
  entries stay checked underneath whatever the filter currently hides.
  `Tab` moves focus between the filter and the list; with the list
  focused, `a` checks every currently visible entry, `d` unchecks every
  currently visible entry, `enter`/`space` toggles just the highlighted
  one, and `esc` stores whatever ended up checked (across every filter
  used, not just the last one) and returns to the "CTS / tie-off /
  routing cells..." submenu -- with that field's count now updated --
  rather than all the way back to the main menu, so picking several
  fields in a row doesn't mean re-opening the submenu each time; `esc`
  again from the submenu itself returns to the main menu. Every cell
  name comes from *every* selected track/vth (`technology.
  selected_tracks`/`selected_vths`), not just the single primary one --
  a run selecting lvt+rvt+hvt sees all three vths' own cells.
- **Active views (setup/hold)**: a checklist of the resolved technology's
  own declared corner names (`technology.timing_corners`) -- the exact
  same set `active_views` validates against -- or free text if the
  technology has no named corners.
- **Clock routing preferred layers** (trunk/leaf, top/bottom): a single
  pick from the resolved technology's own routing-type LEF layers, or
  free text if not resolvable. The route rule's own width/spacing
  multipliers are numeric, not name-based, and stay hand-edited YAML --
  picking a value doesn't help there, so it was left out rather than
  forced in.

No technology selected, or its files aren't readable, falls back to free
text everywhere above -- the picker never blocks on something it can't
resolve.

**Where this is stored**: exactly the same `setup.<design_name>.yaml`
keys documented above (`cts_*`, `add_tieoffs_*`, `clock_routing_*`,
`active_views`) -- the menu is a UI onto that same schema, not a
parallel mechanism, so hand-editing the file and the menu round-trip
through each other. Nothing from the library itself -- no file path, no
LEF/liberty content -- ever reaches `setup.<design_name>.yaml`, the
repo, or any other project file: only the cell/layer/view *names* you
actually picked. The extracted name list itself is cached once per
resolved technology under WOLF's own state directory
(`~/.wolf/cache/cells/`, or wherever `WOLF_HOME` points), keyed by the
technology's package/revision/track/vth/metal stack identity plus each
LEF file's own mtime, so re-opening the picker later filters an
already-scanned list instead of re-reading real files every time; a PDK
update (a file's mtime changing) invalidates it automatically.

**Scriptable equivalent** (non-interactive, e.g. for an institution's
own setup scripts): `wolf env set <name> <key> <yaml-value>` routes a
design-level key straight to `setup.<design_name>.yaml`, no
`backend.cadence-flowtool.` prefix and no pre-existing intermediate
mapping needed (unlike an environment-level `wolf.yaml` key, this one
writes a flat top-level key into a file WOLF creates on first use):

```bash
wolf env set myenv cts_buffer_cells '["BUFX*"]'
wolf env set myenv add_tieoffs_cells '["TIEHIX1", "TIELOX1"]'
wolf env unset myenv add_tieoffs_cells
```

A nested key (e.g. `active_views.setup`) still requires each intermediate
*segment* to resolve to a mapping once it exists, but the top-level key
itself does not need seeding first the way a fresh `wolf.yaml`'s
`backend.cadence-flowtool.*` once did.

### Active analysis views apply uniformly, not yet per stage

This design's `setup.<design_name>.yaml` `active_views` key (see
"Multi-corner (MMMC) technology packages" above) applies the same
setup/hold view selection to every implementation stage. A project
wanting a narrow view set through `prects`..`postcts` and every declared
view again at `route`/`postroute` has to edit `setup.<design_name>.yaml`
between stages today; per-stage selection (e.g. a mapping keyed by stage
name, falling back to the global value) is a real, reasonably-sized
follow-up, not implemented yet.

### Settings across implementation stages

Each implementation stage (`floorplan`/`prects`/`cts`/`postcts`/`route`/
`postroute`) is a separate Flowtool/Innovus invocation restored from the
previous stage's own checkpoint. Whether root `set_db` attributes set in
one stage (`design_cong_effort`/`opt_consider_routing_congestion`/
`place_global_cong_effort` from `CMD_set_cong_aware`, or the CTS
attributes above) survive that restore into the next stage is not
documented anywhere WOLF found, and was not assumed either way. The safe
default implemented here: re-apply idempotently at the start of every
stage that depends on them -- `CMD_set_cong_aware` now also runs at the
start of `prects` (previously only `floorplan`), `set_cts_config` runs
at the start of both `prects` and `cts`, and the `active_views`
setup/hold selection (`set_analysis_view`) is applied by `init_innovus`
itself rather than only by `genus_turn_on_analysis_views`, which only
ever appeared in `floorplan`'s own step list -- `prects`/`cts`/`postcts`/
`route`/`postroute` never re-applied it at all before this.
`genus_turn_on_analysis_views` is kept as a named, injectable extension
point (any existing `wolf_inject_for_step` hook for it still fires), but
the real work no longer lives there.

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

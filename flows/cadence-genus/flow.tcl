# WOLF's default Cadence Genus flow, expressed as real Stylus/Common-UI Flow
# Kit steps (create_flow_step). This file is a real, editable part of the
# flow, not generated output: every step WOLF's default flow runs is defined
# here, and Flowtool itself -- not WOLF -- sequences them, checkpoints them
# (via each step's -write_db), and resumes them (via `-from <step>`, which
# loads the nearest preceding checkpoint automatically). `wolf flow init
# --from flows/cadence-genus --to <your-copy>` clones this directory
# (and presentation.tcl) so a project can fork and edit either file freely;
# point `flow: {package: ...}` at the clone and WOLF resolves this file from
# there instead.
#
# flow-config.tcl (sourced before this file, alongside presentation.tcl, by
# whatever institution flow.yaml template points `flow_source_directory` at
# this directory) sets the resolved, run-specific values every step below
# reads:
#   wolf_design_name        design name, used for netlist output filenames
#   wolf_design_top         top-level module/entity passed to `elaborate`
#   wolf_max_cpus_per_server  thread count, or "" if none was resolved
#   wolf_technology_script  path to a generated technology.tcl, or ""
#   wolf_overrides_script   path to a generated overrides.tcl, or ""
#   wolf_sources_script     path to the generated sources.tcl
#   wolf_constraints_file   path to the generated constraints.sdc
#   wolf_dont_use_cells     list of PDK-declared dont-use cell name globs
#   wolf_technology_lefs    list of technology LEF paths, or {}
#   wolf_cell_lefs          list of cell LEF paths, or {}
#   wolf_floorplan_def      path to a floorplan DEF, or ""
#   wolf_reports_dir        absolute directory each step's reports are
#                           written under (stable across runs, not inside
#                           the flow.tcl/scripts.<N> snapshot itself)
#   wolf_outputs_dir        absolute directory each step's netlist is
#                           written under
#
# Steps, in flow order (a `wolf run -from X -to Y` selects a sub-range of
# these; Flowtool itself resolves everything before X from that step's own
# checkpoint rather than WOLF re-running it):
#   elaborate    (owner design)  -- project-specific: what RTL is read and
#                                   how it elaborates is the one part of
#                                   this flow every design customizes.
#   syn_generic  (owner cadence) -- standard, reusable: technology-
#   syn_map      (owner cadence)    independent through mapped synthesis
#   syn_opt      (owner cadence)    needs no per-design customization.
# Each is checkpointed (-write_db) immediately after its real work finishes,
# in the same live Flowtool/Genus session -- never round-tripped through an
# exported netlist, which does not preserve Genus's internal synthesis-stage
# state.

create_flow_step -name elaborate -owner design {
    wolf_step "Elaborating design"

    if {$::wolf_max_cpus_per_server ne ""} {
        set_db max_cpus_per_server $::wolf_max_cpus_per_server
    }
    if {$::wolf_technology_script ne ""} {
        source $::wolf_technology_script
    }
    if {$::wolf_overrides_script ne ""} {
        source $::wolf_overrides_script
    }

    # Physical views (LEF) are optional: technology-independent elaboration
    # needs none of this. When the technology package declares them, this
    # step becomes physical-aware -- loading LEF before elaboration and
    # initializing the physical design right after it.
    set has_physical_views [expr {
        [llength $::wolf_technology_lefs] > 0 || [llength $::wolf_cell_lefs] > 0
    }]
    if {$has_physical_views} {
        read_physical -lef [concat $::wolf_technology_lefs $::wolf_cell_lefs]
    }

    source $::wolf_sources_script
    elaborate $::wolf_design_top

    if {$has_physical_views} {
        init_design
    }
    if {$::wolf_floorplan_def ne ""} {
        read_def $::wolf_floorplan_def
    }

    read_sdc $::wolf_constraints_file
    check_design -unresolved

    puts [wolf_sep]
} -write_db


create_flow_step -name syn_generic -owner cadence {
    wolf_step "Synthesizing to generic gates"

    # Mark PDK-configured cells unusable, then group the standard Cadence
    # Genus synthesis cost paths (in2out/in2reg/reg2out/reg2reg) -- ordinary
    # Cadence Genus practice for any design, not project-specific. WOLF
    # resolves one flat SDC per run rather than multiple constraint-mode
    # views, so this happens once rather than once per analysis view.
    if {[llength $::wolf_dont_use_cells] > 0} {
        foreach dont_use_cell $::wolf_dont_use_cells {
            set_db [get_db base_cells $dont_use_cell] .dont_use true
        }
    }
    group_path -name in2out -from [all_inputs] -to [all_outputs]
    if {[sizeof_collection [all_registers]] > 0} {
        group_path -name in2reg -from [all_inputs] -to [all_registers]
        group_path -name reg2out -from [all_registers] -to [all_outputs]
        group_path -name reg2reg -from [all_registers] -to [all_registers]
    }

    syn_generic

    report_area > $::wolf_reports_dir/area.generic.rpt
    write_hdl > $::wolf_outputs_dir/$::wolf_design_name.generic.v

    puts [wolf_sep]
} -write_db


create_flow_step -name syn_map -owner cadence {
    wolf_step "Mapping to technology library"

    syn_map

    report_area > $::wolf_reports_dir/area.mapped.rpt
    write_hdl > $::wolf_outputs_dir/$::wolf_design_name.mapped.v

    puts [wolf_sep]
} -write_db


create_flow_step -name syn_opt -owner cadence {
    wolf_step "Optimizing mapped netlist"

    syn_opt

    check_design -unresolved
    report_hierarchy > $::wolf_reports_dir/hierarchy.rpt
    report_messages > $::wolf_reports_dir/messages.rpt
    report_area > $::wolf_reports_dir/area.opt.rpt
    write_hdl > $::wolf_outputs_dir/$::wolf_design_name.opt.v

    puts [wolf_sep]
} -write_db

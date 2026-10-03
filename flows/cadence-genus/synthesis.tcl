# WOLF's default Cadence Genus flow -- the actual synthesis work: reading
# and elaborating RTL, marking dont_use cells, and the three real Genus
# synthesis actions (generic, mapped, optimized). Cross-cutting flow
# infrastructure that isn't really "about synthesis" -- block_start/
# block_finish bookkeeping, the genus_to_innovus handoff to the next tool
# -- lives in common_steps.tcl instead, since a future flow (floorplan,
# route) would also want those but not these.
#
# init_elaborate and set_dont_use are the two steps every adopting project
# always writes itself: Cadence's own vendor-neutral Genus Stylus flow
# template deliberately leaves them undefined -- it references them in
# common_flows.tcl's step sequences without ever defining them, exactly
# the extension point they fill here. create_cost_group and
# run_syn_generic/run_syn_map/run_syn_opt are that same template's
# Genus-specific reference content (not institution-specific), just given
# wolf_step banners and wolf_inject hooks for consistency.
#
# This is a real, editable part of the flow, not generated output; see
# presentation.tcl's header for how to fork it.
#
# flow-config.tcl (sourced before this file, alongside presentation.tcl
# and common_steps.tcl, by whatever project points flow_source_directory
# at this directory) sets the resolved, run-specific values this file
# reads:
#   wolf_design_name          design name, used for netlist output filenames
#   wolf_design_top            top-level module/entity passed to `elaborate`
#   wolf_max_cpus_per_server    thread count, or "" if none was resolved
#   wolf_technology_script     path to a generated technology.tcl (single-
#                              corner set_db library), or "" when the
#                              technology package declares named corners
#                              instead (see wolf_mmmc_script)
#   wolf_mmmc_script           path to a generated mmmc.tcl (multi-corner
#                              library sets/delay corners/analysis views),
#                              or "" for a single-corner technology package
#   wolf_overrides_script      path to a generated overrides.tcl, or ""
#   wolf_sources_script        path to the generated sources.tcl
#   wolf_constraints_file      path to the generated constraints.sdc --
#                              generated clocks plus any constraints.files/
#                              constraints.lines content, unparsed by WOLF
#   wolf_dont_use_cells        list of PDK-declared dont-use cell name globs
#   wolf_technology_lefs       list of technology LEF paths, or {}
#   wolf_cell_lefs             list of cell LEF paths, or {}
#   wolf_floorplan_def         path to a floorplan DEF, or ""
#   wolf_reports_dir           absolute directory each step's reports are
#                              written under (stable across runs, not inside
#                              the scripts.<N> snapshot itself)
#   wolf_outputs_dir           absolute directory each step's netlist is
#                              written under
#   wolf_handoff_dir           absolute directory genus_to_innovus writes
#                              the Innovus-ready netlist/SDC/init script to
#   wolf_postsyn_netlists      pre-synthesized sub-block netlists to read
#                              before the Innovus handoff (hierarchical
#                              synthesis -- e.g. a tiled FPGA fabric where
#                              one repeated block was synthesized once and
#                              is reused many times rather than re-expanded)

create_flow_step -name init_elaborate -owner wolf {
    wolf_step "init_elaborate: elaborating $::wolf_design_name"
    wolf_inject_for_step init_elaborate pre

    if {$::wolf_max_cpus_per_server ne ""} {
        set_db max_cpus_per_server $::wolf_max_cpus_per_server
    }
    if {$::wolf_technology_script ne ""} {
        source $::wolf_technology_script
    }
    if {$::wolf_mmmc_script ne ""} {
        read_mmmc $::wolf_mmmc_script
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

    # init_design is also required once MMMC is active (Genus refuses
    # syn_generic otherwise: "Please use init_design command prior to
    # syn_gen command"), not only for physical views -- confirmed against
    # a real multi-corner MMMC run with no LEF data at all.
    if {$has_physical_views || $::wolf_mmmc_script ne ""} {
        init_design
    }
    if {$::wolf_floorplan_def ne ""} {
        read_def $::wolf_floorplan_def
    }

    # A multi-corner mmmc_script's own create_constraint_mode already
    # points at this same constraints.sdc for every analysis view -- a
    # plain read_sdc here would reapply (and error re-creating) the same
    # clocks a second time.
    if {$::wolf_mmmc_script eq ""} {
        read_sdc $::wolf_constraints_file
    }
    check_design -unresolved

    wolf_inject_for_step init_elaborate post
    puts [wolf_sep]
} -write_db

create_flow_step -name set_dont_use -owner wolf {
    wolf_inject_for_step set_dont_use pre
    foreach dont_use_cell $::wolf_dont_use_cells {
        set_db [get_db base_cells $dont_use_cell] .dont_use true
    }
    wolf_inject_for_step set_dont_use post
}

create_flow_step -name create_cost_group -owner wolf {
    wolf_step "Creating cost groups"
    wolf_inject_for_step create_cost_group pre

    # Once MMMC has more than one constraint mode active, group_path (an
    # interactive SDC-context command) refuses to run without one explicitly
    # selected ("SDC command requires a constraint mode specification",
    # confirmed against a real multi-corner run) -- apply it to every
    # declared corner's constraint mode, not just whichever is implicit.
    if {$::wolf_mmmc_script ne ""} {
        set_interactive_constraint_modes [all_constraint_modes]
    }

    #- Clear existing path_groups, then add the standard four
    get_db cost_groups -if {.name != default} -foreach {delete_obj $obj(.)}
    group_path -name in2out -from [all_inputs] -to [all_outputs]
    if {[sizeof_collection [all_registers]] > 0} {
        group_path -name in2reg -from [all_inputs] -to [all_registers]
        group_path -name reg2out -from [all_registers] -to [all_outputs]
        group_path -name reg2reg -from [all_registers] -to [all_registers]
    }

    wolf_inject_for_step create_cost_group post
    puts [wolf_sep]
}

create_flow_step -name run_syn_generic -owner wolf {
    wolf_step "run_syn_generic: synthesizing to generic gates"
    wolf_inject_for_step run_syn_generic pre

    syn_generic

    report_area > [file join $::wolf_reports_dir area.generic.rpt]
    write_hdl > [file join $::wolf_outputs_dir $::wolf_design_name.generic.v]

    wolf_inject_for_step run_syn_generic post
    puts [wolf_sep]
} -write_db

create_flow_step -name run_syn_map -owner wolf {
    wolf_step "run_syn_map: mapping to technology library"
    wolf_inject_for_step run_syn_map pre

    syn_map

    report_area > [file join $::wolf_reports_dir area.mapped.rpt]
    write_hdl > [file join $::wolf_outputs_dir $::wolf_design_name.mapped.v]

    wolf_inject_for_step run_syn_map post
    puts [wolf_sep]
} -write_db

create_flow_step -name run_syn_opt -owner wolf {
    wolf_step "run_syn_opt: optimizing mapped netlist"
    wolf_inject_for_step run_syn_opt pre

    syn_opt

    check_design -unresolved
    report_hierarchy > [file join $::wolf_reports_dir hierarchy.rpt]
    report_messages > [file join $::wolf_reports_dir messages.rpt]
    report_area > [file join $::wolf_reports_dir area.opt.rpt]
    report_timing_summary -checks {setup drv} > [file join $::wolf_reports_dir timing.opt.rpt]
    report_power > [file join $::wolf_reports_dir power.opt.rpt]
    write_hdl > [file join $::wolf_outputs_dir $::wolf_design_name.opt.v]

    wolf_inject_for_step run_syn_opt post
    puts [wolf_sep]
} -write_db

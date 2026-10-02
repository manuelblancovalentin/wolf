# WOLF's default Cadence Genus flow -- the steps every adopting project
# always writes itself: how RTL actually gets read and elaborated, and
# which cells are marked dont_use. Cadence's own vendor-neutral Genus
# Stylus flow template deliberately leaves these two undefined -- they
# reference "init_elaborate" and "set_dont_use" in common_flows.tcl's step
# sequences without ever defining them, exactly the extension point this
# file fills. This is a real, editable part of the flow, not generated
# output; see presentation.tcl's header for how to fork it.
#
# flow-config.tcl (sourced before this file, alongside presentation.tcl
# and common_steps.tcl, by whatever project points flow_source_directory
# at this directory) sets the resolved, run-specific values this file
# reads:
#   wolf_design_name          design name, used for netlist output filenames
#   wolf_design_top            top-level module/entity passed to `elaborate`
#   wolf_max_cpus_per_server    thread count, or "" if none was resolved
#   wolf_technology_script     path to a generated technology.tcl, or ""
#   wolf_overrides_script      path to a generated overrides.tcl, or ""
#   wolf_sources_script        path to the generated sources.tcl
#   wolf_constraints_file      path to the generated constraints.sdc
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

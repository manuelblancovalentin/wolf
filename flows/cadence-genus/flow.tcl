# WOLF's default Cadence Genus flow.
#
# This file is a real, editable part of the flow, not generated output --
# every step WOLF's default flow runs, and the order it runs them in, is
# defined here. `wolf flow init --from flows/cadence-genus --to <your-copy>`
# clones this directory (and presentation.tcl) so a project can fork and
# edit either file freely; point `flow: {package: ...}` at the clone and
# WOLF resolves this file from there instead. WOLF only ever writes a small
# per-run configuration file (flow-config.tcl, plain `set` statements) next
# to a clone of this directory; it never re-generates flow logic itself.
#
# flow-config.tcl (sourced before this file) sets the resolved, run-specific
# values every proc below reads:
#   wolf_flow_name          informational only (see wolf_from_stage/wolf_to_stage)
#   wolf_from_stage         first entry of wolf_stage_order (below) to run --
#                           anything after "elaborate" resumes from that
#                           stage's checkpoint instead of re-running earlier
#                           stages
#   wolf_to_stage           last entry of wolf_stage_order to run
#   wolf_checkpoint_dir     directory write_db/read_db checkpoints live in
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
#   wolf_interactive        1 to leave Genus at its own prompt when done or
#                           on failure instead of exiting; 0 to always exit

proc wolf_flow_configure_resources {} {
    if {$::wolf_max_cpus_per_server ne ""} {
        wolf_step "Configuring resources"
        set_db max_cpus_per_server $::wolf_max_cpus_per_server
    }
}

proc wolf_flow_load_technology {} {
    if {$::wolf_technology_script ne ""} {
        wolf_step "Loading technology"
        source $::wolf_technology_script
    }
}

proc wolf_flow_apply_overrides {} {
    if {$::wolf_overrides_script ne ""} {
        wolf_step "Applying overrides"
        source $::wolf_overrides_script
    }
}

# Physical views (LEF) are optional: technology-independent HDL elaboration
# needs none of this. When a technology package declares them, WOLF's
# default flow becomes physical-aware -- loading LEF before elaboration and
# initializing the physical design right after it -- so synthesis can use
# placement information (and a floorplan DEF, see wolf_flow_read_def).
proc wolf_flow_has_physical_views {} {
    return [expr {[llength $::wolf_technology_lefs] > 0 || [llength $::wolf_cell_lefs] > 0}]
}

proc wolf_flow_read_physical {} {
    if {[wolf_flow_has_physical_views]} {
        wolf_step "Reading physical views"
        read_physical -lef [concat $::wolf_technology_lefs $::wolf_cell_lefs]
    }
}

proc wolf_flow_read_sources {} {
    wolf_step "Reading sources"
    source $::wolf_sources_script
}

proc wolf_flow_elaborate {} {
    wolf_step "Elaborating design"
    elaborate $::wolf_design_top
}

proc wolf_flow_init_design {} {
    if {[wolf_flow_has_physical_views]} {
        wolf_step "Initializing physical design"
        init_design
    }
}

proc wolf_flow_read_def {} {
    if {$::wolf_floorplan_def ne ""} {
        wolf_step "Reading floorplan DEF"
        read_def $::wolf_floorplan_def
    }
}

proc wolf_flow_read_constraints {} {
    wolf_step "Reading constraints"
    read_sdc $::wolf_constraints_file
}

proc wolf_flow_set_dont_use {} {
    if {[llength $::wolf_dont_use_cells] > 0} {
        wolf_step "Applying dont-use cells"
        foreach dont_use_cell $::wolf_dont_use_cells {
            set_db [get_db base_cells $dont_use_cell] .dont_use true
        }
    }
}

# Standard Cadence Genus path-grouping idiom (in2out/in2reg/reg2out/reg2reg)
# -- ordinary Cadence Genus practice for any design, not project-specific.
# WOLF resolves one flat SDC per run rather than multiple constraint-mode
# views, so this happens once rather than once per analysis view.
proc wolf_flow_create_cost_group {} {
    wolf_step "Grouping synthesis cost paths"
    group_path -name in2out -from [all_inputs] -to [all_outputs]
    if {[sizeof_collection [all_registers]] > 0} {
        group_path -name in2reg -from [all_inputs] -to [all_registers]
        group_path -name reg2out -from [all_registers] -to [all_outputs]
        group_path -name reg2reg -from [all_registers] -to [all_registers]
    }
}

proc wolf_flow_syn_generic {} {
    wolf_step "Synthesizing to generic gates"
    syn_generic
}

proc wolf_flow_syn_map {} {
    wolf_step "Mapping to technology library"
    syn_map
}

proc wolf_flow_syn_opt {} {
    wolf_step "Optimizing mapped netlist"
    syn_opt
}

proc wolf_flow_check_design {} {
    wolf_step "Checking design"
    check_design -unresolved
}

proc wolf_flow_write_reports {netlist_suffix} {
    wolf_step "Writing reports"
    report_hierarchy > reports/hierarchy.rpt
    report_messages > reports/messages.rpt
    if {$netlist_suffix ne ""} {
        report_area > reports/area.rpt
        write_hdl > outputs/$::wolf_design_name.$netlist_suffix.v
    }
}

# Canonical stage order. wolf_from_stage/wolf_to_stage each name one entry;
# the range between them (inclusive) is what this run actually executes --
# see wolf_run_flow. genus-elaboration/-syn-generic/-syn-map/-syn-opt are
# shorthand `flow.name` values mapping to common (elaborate, X) ranges; the
# real primitive is always this from/to range plus checkpoint reuse.
set wolf_stage_order {elaborate syn_generic syn_map syn_opt}
array set wolf_flow_netlist_suffix {
    syn_generic generic
    syn_map     mapped
    syn_opt     opt
}

proc wolf_checkpoint_path {stage} {
    return [file join $::wolf_checkpoint_dir "$stage.db"]
}

# Every stage's post-run design state is saved so a later run can resume
# from it via wolf_flow_read_checkpoint instead of re-running everything
# before it -- the whole point being that an expensive stage (syn_generic on
# a large design, for instance) is only ever paid for once.
proc wolf_flow_write_checkpoint {stage} {
    wolf_step "Checkpointing $stage"
    file mkdir $::wolf_checkpoint_dir
    write_db [wolf_checkpoint_path $stage]
}

proc wolf_flow_read_checkpoint {stage} {
    set path [wolf_checkpoint_path $stage]
    if {![file exists $path]} {
        error "no checkpoint found for stage '$stage' at $path; run -from\
            a stage whose checkpoint already exists, or -from elaborate to\
            start fresh"
    }
    wolf_step "Restoring checkpoint: $stage"
    read_db $path
}

proc wolf_run_flow {} {
    set order $::wolf_stage_order
    set from_index [lsearch -exact $order $::wolf_from_stage]
    set to_index [lsearch -exact $order $::wolf_to_stage]
    if {$from_index < 0 || $to_index < 0 || $to_index < $from_index} {
        puts stderr "WOLF Genus failure: invalid stage range\
            $::wolf_from_stage..$::wolf_to_stage (expected an ordered pair\
            from {$order})"
        if {!$::wolf_interactive} { exit 1 }
        return
    }
    if {[catch {
        wolf_flow_configure_resources
        if {$from_index == 0} {
            wolf_flow_load_technology
            wolf_flow_apply_overrides
            wolf_flow_read_physical
            wolf_flow_read_sources
            wolf_flow_elaborate
            wolf_flow_init_design
            wolf_flow_read_def
            wolf_flow_read_constraints
            wolf_flow_write_checkpoint elaborate
        } else {
            # Re-asserting technology/overrides is harmless even though the
            # restored checkpoint already carries its own session state.
            wolf_flow_load_technology
            wolf_flow_apply_overrides
            wolf_flow_read_checkpoint [lindex $order [expr {$from_index - 1}]]
        }
        set netlist_suffix ""
        for {set i [expr {$from_index > 0 ? $from_index : 1}]} {$i <= $to_index} {incr i} {
            set stage [lindex $order $i]
            switch $stage {
                syn_generic {
                    wolf_flow_set_dont_use
                    wolf_flow_create_cost_group
                    wolf_flow_syn_generic
                }
                syn_map { wolf_flow_syn_map }
                syn_opt { wolf_flow_syn_opt }
            }
            wolf_flow_write_checkpoint $stage
            set netlist_suffix $::wolf_flow_netlist_suffix($stage)
        }
        wolf_flow_check_design
        wolf_flow_write_reports $netlist_suffix
    } error options]} {
        puts stderr "WOLF Genus failure: $error"
        if {[dict exists $options -errorinfo]} { puts stderr [dict get $options -errorinfo] }
        if {[dict exists $options -errorcode]} { puts stderr "ErrorCode: [dict get $options -errorcode]" }
        if {!$::wolf_interactive} { exit 1 }
        return
    }
    if {!$::wolf_interactive} { exit 0 }
}

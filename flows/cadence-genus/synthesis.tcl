# WOLF's default Cadence Genus flow -- the actual synthesis work: reading
# and elaborating RTL, the elaboration-time design prep steps every real
# Genus flow carries (uniquify, preserve, power intent, physical init),
# marking dont_use cells, the three real Genus synthesis actions (generic,
# mapped, optimized), and the per-stage reporting that follows each of
# them. Cross-cutting flow infrastructure that isn't really "about
# synthesis" -- block_start/block_finish bookkeeping, the genus_to_innovus/
# genus_to_lec/genus_to_clp/build_sim_testbench/build_xsim_files handoffs
# to tools downstream of Genus -- lives in common_steps.tcl instead, since
# a future flow (floorplan, route) would also want those but not these.
#
# Deliberately kept as separate, individually named steps -- matching the
# real Cadence Stylus reference flow this was adapted from -- rather than
# one merged elaboration step: a project can comment out, reorder, or
# replace any one of them without touching the rest, exactly as the
# reference flow's own YAML allows. Every step prints its own banner
# (wolf_step) and a trailing separator, so a run's log reads as one step
# at a time, not a block of merged output.
#
# Several of these need a value WOLF does not resolve from any PDK/design
# field today (clock derate, preserve lists, power intent, max routing
# layers) -- those steps are still real, always-present, always-run steps,
# just guarded to quietly skip (not error) when the backing wolf_* value
# is unset/empty. Flip them on later by resolving the value, not by
# un-commenting a step.
#
# This is a real, editable part of the flow, not generated output; see
# presentation.tcl's header for how to fork it.
#
# Every resolved, run-specific value this file reads comes from this
# run's own setup.<design_name>.yaml via get_flow_config -- not a
# flow-config.tcl plain-Tcl-global layer (removed; see presentation.tcl's
# header for why get_flow_config is now the only access pattern). Keys
# read here:
#   design_name           design name, used for netlist/report filenames
#   design_top             top-level module/entity passed to `elaborate`
#   max_cpus_per_server     thread count, -quiet absent if none was resolved
#   technology_script      path to a generated technology.tcl (single-
#                          corner set_db library), -quiet absent when the
#                          technology package declares named corners
#                          instead (see mmmc_script)
#   mmmc_script            path to a generated mmmc.tcl (multi-corner
#                          library sets/delay corners/analysis views),
#                          -quiet absent for a single-corner technology
#   overrides_script       path to a generated overrides.tcl, -quiet absent
#   sources_script         path to the generated sources.tcl
#   constraints_file       path to the generated constraints.sdc --
#                          generated clocks plus any constraints.files/
#                          constraints.lines content, unparsed by WOLF
#   dont_use_cells         list of PDK-declared dont-use cell name globs
#   technology_lefs        list of technology LEF paths, -quiet absent
#   cell_lefs              list of cell LEF paths, -quiet absent
#   floorplan_def          path to a floorplan DEF, -quiet absent
#   clock_derate_early     early-mode clock derate factor, -quiet absent --
#                          not resolved by WOLF yet; apply_clock_derate
#                          quietly skips until some PDK/environment field
#                          supplies one
#   clock_derate_late      late-mode clock derate factor, -quiet absent --
#                          same status as clock_derate_early
#   preserve_blocks        list of module name patterns to mark .preserve
#                          true before synthesis touches them, -quiet
#                          absent -- not resolved by WOLF yet
#   preserve_instances     list of instance name patterns to mark
#                          .preserve true, -quiet absent -- not resolved yet
#   power_intent_file      path to a UPF/CPF power intent file, -quiet
#                          absent -- not resolved by WOLF yet
#   max_routing_layers     integer cap on routing layers Genus may assume
#                          during physically-aware synthesis, -quiet
#                          absent -- not resolved by WOLF yet
#   reports_dir            absolute directory each step's reports are
#                          written under (stable across runs, not inside
#                          the scripts.<N> snapshot itself)
#   outputs_dir            absolute directory each step's netlist is
#                          written under

create_flow_step -name avoid_module_renaming -owner wolf {
    wolf_step "avoid_module_renaming: keep original module names for parameterized instances"
    wolf_inject_for_step avoid_module_renaming pre
    set_db hdl_parameter_naming_style ""
    wolf_inject_for_step avoid_module_renaming post
    puts [wolf_sep]
}

create_flow_step -name read_mmmc -owner wolf {
    wolf_step "read_mmmc: loading technology/corner setup"
    wolf_inject_for_step read_mmmc pre

    set wolf_max_cpus_per_server [get_flow_config -quiet max_cpus_per_server]
    set wolf_technology_script [get_flow_config -quiet technology_script]
    set wolf_mmmc_script [get_flow_config -quiet mmmc_script]
    set wolf_overrides_script [get_flow_config -quiet overrides_script]
    if {$wolf_max_cpus_per_server ne ""} {
        set_db max_cpus_per_server $wolf_max_cpus_per_server
        wolf_info "max_cpus_per_server: using $wolf_max_cpus_per_server CPU(s) (resources.threads/GENUS_NUM_CPUS)"
    } else {
        wolf_info "max_cpus_per_server: not set (resources.threads/GENUS_NUM_CPUS not configured) -- using Genus's own default"
    }
    if {$wolf_technology_script ne ""} {
        source $wolf_technology_script
    }
    if {$wolf_mmmc_script ne ""} {
        read_mmmc $wolf_mmmc_script
    }
    if {$wolf_overrides_script ne ""} {
        source $wolf_overrides_script
    }

    wolf_inject_for_step read_mmmc post
    puts [wolf_sep]
}

create_flow_step -name apply_clock_derate -owner wolf {
    wolf_step "apply_clock_derate"
    wolf_inject_for_step apply_clock_derate pre

    set wolf_clock_derate_early [get_flow_config -quiet clock_derate_early]
    set wolf_clock_derate_late [get_flow_config -quiet clock_derate_late]
    if {$wolf_clock_derate_early ne "" || $wolf_clock_derate_late ne ""} {
        set derate_args {}
        if {$wolf_clock_derate_early ne ""} {
            lappend derate_args -early $wolf_clock_derate_early
        }
        if {$wolf_clock_derate_late ne ""} {
            lappend derate_args -late $wolf_clock_derate_late
        }
        set_timing_derate -clock {*}$derate_args [all_clocks]
    } else {
        wolf_info "apply_clock_derate: no derate configured, skipping"
    }

    wolf_inject_for_step apply_clock_derate post
    puts [wolf_sep]
}

create_flow_step -name read_physical -owner wolf {
    wolf_step "read_physical: loading LEF"
    wolf_inject_for_step read_physical pre

    set wolf_technology_lefs [get_flow_config -quiet technology_lefs]
    set wolf_cell_lefs [get_flow_config -quiet cell_lefs]
    set has_physical_views [expr {
        [llength $wolf_technology_lefs] > 0 || [llength $wolf_cell_lefs] > 0
    }]
    if {$has_physical_views} {
        read_physical -lef [concat $wolf_technology_lefs $wolf_cell_lefs]
    } else {
        wolf_info "read_physical: no LEF resolved for this technology, skipping"
    }

    wolf_inject_for_step read_physical post
    puts [wolf_sep]
}

create_flow_step -name read_hdl -owner wolf {
    wolf_step "read_hdl: reading [get_flow_config design_name] sources"
    wolf_inject_for_step read_hdl pre
    source [get_flow_config sources_script]
    wolf_inject_for_step read_hdl post
    puts [wolf_sep]
}

# Not one of the reference flow's named steps -- the real Genus `elaborate`
# call has to happen somewhere between read_hdl and uniquify_modules (it
# can't run before RTL is read, and uniquify_modules/preserve_blocks/
# preserve_instances all operate on the elaborated design), so it lives
# here as its own explicit, separately checkpointed step rather than
# folded into read_hdl or left implicit.
create_flow_step -name elaborate -owner wolf {
    wolf_step "elaborate: elaborating [get_flow_config design_top]"
    wolf_inject_for_step elaborate pre

    elaborate [get_flow_config design_top]

    # A multi-corner mmmc_script's own create_constraint_mode already
    # points at this same constraints.sdc for every analysis view -- a
    # plain read_sdc here would reapply (and error re-creating) the same
    # clocks a second time.
    if {[get_flow_config -quiet mmmc_script] eq ""} {
        read_sdc [get_flow_config constraints_file]
    }
    check_design -unresolved

    wolf_inject_for_step elaborate post
    puts [wolf_sep]
} -write_db

create_flow_step -name uniquify_modules -owner wolf {
    wolf_step "uniquify_modules"
    wolf_inject_for_step uniquify_modules pre
    uniquify [get_flow_config design_top]
    wolf_inject_for_step uniquify_modules post
    puts [wolf_sep]
}

create_flow_step -name preserve_blocks -owner wolf {
    wolf_step "preserve_blocks"
    wolf_inject_for_step preserve_blocks pre

    set wolf_preserve_blocks [get_flow_config -quiet preserve_blocks]
    if {[llength $wolf_preserve_blocks] > 0} {
        foreach pattern $wolf_preserve_blocks {
            set_db [get_db modules $pattern] .preserve true
        }
    } else {
        wolf_info "preserve_blocks: none configured, skipping"
    }

    wolf_inject_for_step preserve_blocks post
    puts [wolf_sep]
}

create_flow_step -name preserve_instances -owner wolf {
    wolf_step "preserve_instances"
    wolf_inject_for_step preserve_instances pre

    set wolf_preserve_instances [get_flow_config -quiet preserve_instances]
    if {[llength $wolf_preserve_instances] > 0} {
        foreach pattern $wolf_preserve_instances {
            set_db [get_db instances $pattern] .preserve true
        }
    } else {
        wolf_info "preserve_instances: none configured, skipping"
    }

    wolf_inject_for_step preserve_instances post
    puts [wolf_sep]
}

create_flow_step -name read_power_intent -owner wolf {
    wolf_step "read_power_intent"
    wolf_inject_for_step read_power_intent pre

    set wolf_power_intent_file [get_flow_config -quiet power_intent_file]
    if {$wolf_power_intent_file ne ""} {
        read_power_intent -cpf $wolf_power_intent_file
    } else {
        wolf_info "read_power_intent: no power intent file configured, skipping"
    }

    wolf_inject_for_step read_power_intent post
    puts [wolf_sep]
}

create_flow_step -name run_init_design -owner wolf {
    wolf_step "run_init_design"
    wolf_inject_for_step run_init_design pre

    set wolf_technology_lefs [get_flow_config -quiet technology_lefs]
    set wolf_cell_lefs [get_flow_config -quiet cell_lefs]
    set wolf_mmmc_script [get_flow_config -quiet mmmc_script]
    set has_physical_views [expr {
        [llength $wolf_technology_lefs] > 0 || [llength $wolf_cell_lefs] > 0
    }]
    # init_design is also required once MMMC is active (Genus refuses
    # syn_generic otherwise: "Please use init_design command prior to
    # syn_gen command"), not only for physical views -- confirmed against
    # a real multi-corner MMMC run with no LEF data at all.
    if {$has_physical_views || $wolf_mmmc_script ne ""} {
        # constraints.power_nets/ground_nets (optional, default none): set
        # before init_design so the real VDD/VSS nets exist from here on
        # and carry through write_design -innovus's own handoff init
        # script automatically -- without this, a design with no power
        # intent (CPF/UPF) file has no power/ground nets at all on the
        # Innovus side, and connect_global_net/route_special/add_stripes
        # all fail with "net does not exist" until something creates them
        # by hand.
        set wolf_power_nets [get_flow_config -quiet power_nets]
        set wolf_ground_nets [get_flow_config -quiet ground_nets]
        if {[llength $wolf_power_nets]} {
            set_db init_power_nets $wolf_power_nets
            wolf_info "init_power_nets: $wolf_power_nets"
        }
        if {[llength $wolf_ground_nets]} {
            set_db init_ground_nets $wolf_ground_nets
            wolf_info "init_ground_nets: $wolf_ground_nets"
        }
        init_design
    } else {
        wolf_info "run_init_design: no physical views or MMMC active, skipping"
    }

    wolf_inject_for_step run_init_design post
    puts [wolf_sep]
} -write_db

create_flow_step -name read_def -owner wolf {
    wolf_step "read_def"
    wolf_inject_for_step read_def pre

    set wolf_floorplan_def [get_flow_config -quiet floorplan_def]
    if {$wolf_floorplan_def ne ""} {
        read_def $wolf_floorplan_def
    } else {
        wolf_info "read_def: no floorplan DEF configured, skipping"
    }

    wolf_inject_for_step read_def post
    puts [wolf_sep]
}

# Genus Common UI Flow Kit's own init_genus is a yaml/user-config
# extension point left undefined by the vendor template; re-run at the
# start of every synthesis stage (not just syn_generic), since each stage
# executes as its own Flowtool/Genus invocation (see run_genus) that
# restores a checkpoint rather than inheriting a live session.
create_flow_step -name init_genus -owner wolf {
    wolf_step "init_genus"
    wolf_inject_for_step init_genus pre
    set wolf_max_cpus_per_server [get_flow_config -quiet max_cpus_per_server]
    if {$wolf_max_cpus_per_server ne ""} {
        set_db max_cpus_per_server $wolf_max_cpus_per_server
        wolf_info "max_cpus_per_server: using $wolf_max_cpus_per_server CPU(s) (resources.threads/GENUS_NUM_CPUS)"
    }
    wolf_inject_for_step init_genus post
    puts [wolf_sep]
}

create_flow_step -name set_dont_use -owner wolf {
    wolf_step "set_dont_use"
    wolf_inject_for_step set_dont_use pre
    foreach dont_use_cell [get_flow_config -quiet dont_use_cells] {
        set_db [get_db base_cells $dont_use_cell] .dont_use true
    }
    wolf_inject_for_step set_dont_use post
    puts [wolf_sep]
}

create_flow_step -name prevent_flattening -owner wolf {
    wolf_step "prevent_flattening: disabling ungroup on every module"
    wolf_inject_for_step prevent_flattening pre
    set_db [get_db designs .modules *] .ungroup_ok false
    wolf_inject_for_step prevent_flattening post
    puts [wolf_sep]
}

create_flow_step -name max_routing_layer -owner wolf {
    wolf_step "max_routing_layer"
    wolf_inject_for_step max_routing_layer pre

    set wolf_max_routing_layers [get_flow_config -quiet max_routing_layers]
    if {$wolf_max_routing_layers ne ""} {
        set_db number_of_routing_layers $wolf_max_routing_layers
    } else {
        wolf_info "max_routing_layer: no routing layer cap configured, skipping"
    }

    wolf_inject_for_step max_routing_layer post
    puts [wolf_sep]
}

# commit_power_intent is defined once in common_steps.tcl -- Genus's own
# syn_generic (below, via common_flows.tcl) and Innovus's floorplan both
# reference it by that one shared name.

create_flow_step -name create_cost_group -owner wolf {
    wolf_step "Creating cost groups"
    wolf_inject_for_step create_cost_group pre

    # Once MMMC has more than one constraint mode active, group_path (an
    # interactive SDC-context command) refuses to run without one explicitly
    # selected ("SDC command requires a constraint mode specification",
    # confirmed against a real multi-corner run) -- apply it to every
    # declared corner's constraint mode, not just whichever is implicit.
    if {[get_flow_config -quiet mmmc_script] ne ""} {
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
    set run_syn_generic_netlist [file join [get_flow_config outputs_dir] [get_flow_config design_name].generic.v]
    write_hdl > $run_syn_generic_netlist
    wolf_file $run_syn_generic_netlist

    wolf_inject_for_step run_syn_generic post
    puts [wolf_sep]
} -write_db

create_flow_step -name run_syn_map -owner wolf {
    wolf_step "run_syn_map: mapping to technology library"
    wolf_inject_for_step run_syn_map pre

    syn_map
    set run_syn_map_netlist [file join [get_flow_config outputs_dir] [get_flow_config design_name].mapped.v]
    write_hdl > $run_syn_map_netlist
    wolf_file $run_syn_map_netlist

    wolf_inject_for_step run_syn_map post
    puts [wolf_sep]
} -write_db

create_flow_step -name run_syn_opt -owner wolf {
    wolf_step "run_syn_opt: optimizing mapped netlist"
    wolf_inject_for_step run_syn_opt pre

    syn_opt
    check_design -unresolved
    set run_syn_opt_netlist [file join [get_flow_config outputs_dir] [get_flow_config design_name].opt.v]
    write_hdl > $run_syn_opt_netlist
    wolf_file $run_syn_opt_netlist

    wolf_inject_for_step run_syn_opt post
    puts [wolf_sep]
} -write_db

#-------------------------------------------------------------------------
# report_synth -- run after every synthesis stage (syn_generic, syn_map,
# syn_opt alike; see common_flows.tcl), not only the last one, so PPA is
# visible at each point rather than only at the end. [get_db
# flow_report_name] is set by common_flows.tcl's flow_header_tcl to the
# current stage's own name (syn_generic/syn_map/syn_opt), so these steps
# naturally produce per-stage report filenames without WOLF resolving
# anything extra.
#-------------------------------------------------------------------------

create_flow_step -name report_start -owner wolf {
    wolf_step "[get_flow_config design_name] / [get_db flow_report_name]"
    wolf_inject_for_step report_start pre
    wolf_inject_for_step report_start post
}

create_flow_step -name report_area_genus -owner wolf {
    wolf_inject_for_step report_area_genus pre
    set report_area_genus_file [file join [get_flow_config reports_dir] "area.[get_db flow_report_name].rpt"]
    report_area > $report_area_genus_file
    wolf_file $report_area_genus_file
    wolf_inject_for_step report_area_genus post
}

create_flow_step -name report_timing_summary_late_genus -owner wolf {
    wolf_inject_for_step report_timing_summary_late_genus pre
    set report_timing_summary_late_genus_file \
        [file join [get_flow_config reports_dir] "timing.[get_db flow_report_name].rpt"]
    report_timing_summary -checks {setup drv} > $report_timing_summary_late_genus_file
    wolf_file $report_timing_summary_late_genus_file
    wolf_inject_for_step report_timing_summary_late_genus post
}

# report_late_paths is defined once in common_steps.tcl (identical body,
# same real fix -- report_timing has no -check flag, confirmed against a
# real Genus TUI-204 rejection) -- report_synth and the Innovus report_*
# sub-flows both reference it by that one shared name.

create_flow_step -name report_power_genus -owner wolf {
    wolf_inject_for_step report_power_genus pre
    set report_power_genus_file [file join [get_flow_config reports_dir] "power.[get_db flow_report_name].rpt"]
    report_power > $report_power_genus_file
    wolf_file $report_power_genus_file
    wolf_inject_for_step report_power_genus post
}

# WOLF additions beyond the reference report_synth (which has none of
# these) -- cheap and always useful, so folded into every stage's report
# pass rather than left opt-syn_opt-only.
create_flow_step -name report_hierarchy_genus -owner wolf {
    wolf_inject_for_step report_hierarchy_genus pre
    set report_hierarchy_genus_file [file join [get_flow_config reports_dir] "hierarchy.[get_db flow_report_name].rpt"]
    report_hierarchy > $report_hierarchy_genus_file
    wolf_file $report_hierarchy_genus_file
    wolf_inject_for_step report_hierarchy_genus post
}

create_flow_step -name report_messages_genus -owner wolf {
    wolf_inject_for_step report_messages_genus pre
    set report_messages_genus_file [file join [get_flow_config reports_dir] "messages.[get_db flow_report_name].rpt"]
    report_messages > $report_messages_genus_file
    wolf_file $report_messages_genus_file
    wolf_inject_for_step report_messages_genus post
}

create_flow_step -name report_finish -owner wolf {
    wolf_inject_for_step report_finish pre
    wolf_inject_for_step report_finish post
    puts [wolf_sep]
}

# WOLF's default Cadence Innovus implementation flow -- floorplan and
# placement. init_implementation and load_floorplan are WOLF-authored,
# same role as read_hdl/elaborate on the Genus side: Cadence's own
# vendor-neutral template leaves "how does the design actually get into
# Innovus" and "how is the floorplan actually created" as extension
# points every adopting project fills itself (die size, core margins, IO
# placement, and power intent are all inherently design-specific).
# CMD_set_cong_aware/add_tracks/add_clock_spec/commit_route_types/
# CMD_check_place/CMD_resolve_place_violations/run_place_opt are that same
# template's Innovus-specific reference content (the literal commands the
# reference flow's own YAML spells out), just given wolf_step banners and
# wolf_inject hooks for consistency.
#
# init_implementation sources the .invs_init.tcl that genus_to_innovus's
# `write_design -innovus` already wrote -- the standard, Cadence-blessed
# way to bring a Genus-synthesized design into Innovus, not a reimplementation
# of that handoff. It assumes this Innovus invocation shares the same
# wolf_handoff_dir/wolf_design_name as the Genus run that produced it
# (run-orchestration across two separate tool invocations is not wired up
# yet -- see docs/CADENCE_GENUS.md for current status).
#
# create_fplan, add_post_syn_constraints, add_clock_route_types, and
# PPA_recipe_set_path_group_options are left as real, named extension
# points (banner + wolf_inject_for_step only) -- same precedent as
# common_steps.tcl's genus_to_lec: die size/core margins/IO placement,
# post-synthesis constraint patches, and non-default clock routing rules
# are inherently project-specific data WOLF does not resolve, and
# PPA_recipe_set_path_group_options is institution-specific Tcl (the
# reference flow's own comments mark its init_innovus sibling as "Legacy
# from GF22NM") that WOLF has no visibility into and should not guess at.
#
# This is a real, editable part of the flow, not generated output; see
# presentation.tcl's header for how to fork it.

create_flow_step -name init_implementation -owner wolf -write_db {
    wolf_step "init_implementation: loading $::wolf_design_name from Genus handoff"
    wolf_inject_for_step init_implementation pre

    source [file join $::wolf_handoff_dir $::wolf_design_name.invs_init.tcl]

    wolf_inject_for_step init_implementation post
    puts [wolf_sep]
}

# Not one of the reference flow's named steps -- a lightweight re-init
# extension point for this tool, same role as synthesis.tcl's init_genus:
# re-run at the start of every implementation stage (not only floorplan),
# since each stage executes as its own Flowtool/Innovus invocation.
create_flow_step -name init_innovus -owner wolf {
    wolf_step "init_innovus"
    wolf_inject_for_step init_innovus pre
    wolf_inject_for_step init_innovus post
    puts [wolf_sep]
}

create_flow_step -name add_post_syn_constraints -owner wolf {
    wolf_step "add_post_syn_constraints"
    wolf_inject_for_step add_post_syn_constraints pre
    wolf_inject_for_step add_post_syn_constraints post
    puts [wolf_sep]
}

# Works around a real Genus/MMMC limitation: when more than one analysis
# view came through the genus_to_innovus handoff, only the first is
# active by default on the Innovus side too.
create_flow_step -name genus_turn_on_analysis_views -owner wolf {
    wolf_inject_for_step genus_turn_on_analysis_views pre
    if {[llength [get_db analysis_views]] > 1} {
        set_db [get_db analysis_views] .active true
    }
    wolf_inject_for_step genus_turn_on_analysis_views post
}

create_flow_step -name PPA_recipe_set_path_group_options -owner wolf {
    wolf_step "PPA_recipe_set_path_group_options"
    wolf_inject_for_step PPA_recipe_set_path_group_options pre
    wolf_inject_for_step PPA_recipe_set_path_group_options post
    puts [wolf_sep]
}

create_flow_step -name CMD_set_cong_aware -owner wolf {
    wolf_inject_for_step CMD_set_cong_aware pre
    set_db design_cong_effort high
    set_db opt_consider_routing_congestion true
    set_db place_global_cong_effort high
    wolf_inject_for_step CMD_set_cong_aware post
}

create_flow_step -name create_fplan -owner wolf {
    wolf_step "create_fplan"
    wolf_inject_for_step create_fplan pre
    wolf_inject_for_step create_fplan post
    puts [wolf_sep]
}

create_flow_step -name load_floorplan -owner wolf {
    wolf_step "load_floorplan"
    wolf_inject_for_step load_floorplan pre

    if {$::wolf_floorplan_def ne ""} {
        read_def $::wolf_floorplan_def
    } else {
        wolf_info "No floorplan DEF configured (constraints.floorplan_def) -- \
            inject floorplan creation Tcl via backend.cadence-flowtool.inject.create_fplan instead."
    }

    wolf_inject_for_step load_floorplan post
    puts [wolf_sep]
}

create_flow_step -name add_tracks -owner wolf {
    wolf_inject_for_step add_tracks pre
    #- generate tracks after creating floorplan
    if {[llength [get_db current_design .track_patterns]] == 0} {
        add_tracks
    }
    wolf_inject_for_step add_tracks post
}

create_flow_step -name add_clock_spec -owner wolf {
    wolf_inject_for_step add_clock_spec pre
    #- automatically create clock spec if one is not available
    if {[llength [get_db clock_trees]] == 0} {
        create_clock_tree_spec
    } else {
        wolf_info "reusing existing clock tree spec"
    }
    wolf_inject_for_step add_clock_spec post
}

create_flow_step -name add_clock_route_types -owner wolf {
    wolf_step "add_clock_route_types"
    wolf_inject_for_step add_clock_route_types pre
    wolf_inject_for_step add_clock_route_types post
    puts [wolf_sep]
}

create_flow_step -name commit_route_types -owner wolf {
    wolf_inject_for_step commit_route_types pre
    #- assign route_types to clock nets
    commit_clock_tree_route_attributes
    wolf_inject_for_step commit_route_types post
}

create_flow_step -name run_place_opt -owner wolf {
    wolf_step "run_place_opt: global placement and ideal-clock setup optimization"
    wolf_inject_for_step run_place_opt pre

    place_opt_design -report_dir $::wolf_reports_dir -report_prefix placed.

    set run_place_opt_area_file [file join $::wolf_reports_dir area.placed.rpt]
    report_area -min_count 1000 -out_file $run_place_opt_area_file
    wolf_file $run_place_opt_area_file

    wolf_inject_for_step run_place_opt post
    puts [wolf_sep]
} -write_db

create_flow_step -name CMD_check_place -owner wolf {
    wolf_inject_for_step CMD_check_place pre
    set cmd_check_place_file [file join [get_db flow_report_directory] checkDesignPlace.rpt]
    check_design -type place -out_file $cmd_check_place_file
    wolf_file $cmd_check_place_file
    wolf_inject_for_step CMD_check_place post
}

create_flow_step -name CMD_resolve_place_violations -owner wolf {
    wolf_inject_for_step CMD_resolve_place_violations pre
    place_detail
    wolf_inject_for_step CMD_resolve_place_violations post
}

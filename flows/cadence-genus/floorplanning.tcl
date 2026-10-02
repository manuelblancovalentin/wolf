# WOLF's default Cadence Innovus implementation flow -- floorplan and
# placement. init_implementation and init_floorplan are WOLF-authored,
# same role as init_elaborate on the Genus side: Cadence's own
# vendor-neutral template leaves "how does the design actually get into
# Innovus" and "how is the floorplan actually created" as extension
# points every adopting project fills itself (die size, core margins, IO
# placement, and power intent are all inherently design-specific).
# add_tracks/add_clock_spec/commit_route_types/run_place_opt are that same
# template's Innovus-specific reference content, just given wolf_step
# banners and wolf_inject hooks for consistency.
#
# init_implementation sources the .invs_init.tcl that genus_to_innovus's
# `write_design -innovus` already wrote -- the standard, Cadence-blessed
# way to bring a Genus-synthesized design into Innovus, not a reimplementation
# of that handoff. It assumes this Innovus invocation shares the same
# wolf_handoff_dir/wolf_design_name as the Genus run that produced it
# (run-orchestration across two separate tool invocations is not wired up
# yet -- see docs/CADENCE_GENUS.md for current status).
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

create_flow_step -name init_floorplan -owner wolf {
    wolf_step "init_floorplan"
    wolf_inject_for_step init_floorplan pre

    if {$::wolf_floorplan_def ne ""} {
        read_def $::wolf_floorplan_def
    } else {
        wolf_info "No floorplan DEF configured (constraints.floorplan_def) -- \
            inject floorplan creation Tcl via backend.cadence-flowtool.inject.init_floorplan instead."
    }

    wolf_inject_for_step init_floorplan post
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

    report_area -min_count 1000 -out_file [file join $::wolf_reports_dir area.placed.rpt]

    wolf_inject_for_step run_place_opt post
    puts [wolf_sep]
} -write_db

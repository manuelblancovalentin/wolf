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
    # Same resolved thread count synthesis.tcl's own init_genus already
    # applies to Genus (resources.threads/GENUS_NUM_CPUS, via
    # $::wolf_max_cpus_per_server) -- Innovus has no equivalent set_db;
    # set_multi_cpu_usage is its own real multithreading control, and
    # this step re-runs at the start of every implementation stage since
    # each one is a separate Innovus invocation.
    if {$::wolf_max_cpus_per_server ne ""} {
        set_multi_cpu_usage -local_cpu $::wolf_max_cpus_per_server
        wolf_info "set_multi_cpu_usage: using $::wolf_max_cpus_per_server CPU(s) (resources.threads)"
    } else {
        wolf_info "set_multi_cpu_usage: not set (resources.threads not configured) -- using Innovus's own default"
    }
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
# active by default on the Innovus side too. analysis_view's own
# is_active/is_setup/is_hold are read-only (Innovus rejects both
# `set_db .active` and `set_db .is_active`, IMPDBTCL-248/252) -- they
# reflect set_analysis_view, so re-running that same command Innovus-side
# with every view name is the actual fix, not a per-view attribute.
create_flow_step -name genus_turn_on_analysis_views -owner wolf {
    wolf_inject_for_step genus_turn_on_analysis_views pre
    set wolf_analysis_view_names [get_db analysis_views .name]
    if {[llength $wolf_analysis_view_names] > 1} {
        # backend.cadence-flowtool.active_views.{setup,hold} narrows which
        # of the handoff's declared views actually matter for this
        # implementation stage (e.g. one slow/fast corner through
        # place/CTS, every corner again at route/signoff) -- default
        # (both empty) is every declared view, same as before this
        # existed. Applies uniformly to every implementation stage, not
        # selectable per stage yet.
        set wolf_setup_views $wolf_analysis_view_names
        set wolf_hold_views  $wolf_analysis_view_names
        if {[llength $::wolf_active_setup_views]} { set wolf_setup_views $::wolf_active_setup_views }
        if {[llength $::wolf_active_hold_views]}  { set wolf_hold_views  $::wolf_active_hold_views }
        set_analysis_view -setup $wolf_setup_views -hold $wolf_hold_views
        wolf_info "active analysis views -- setup: $wolf_setup_views, hold: $wolf_hold_views"
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

create_flow_step -name export_floorplan_def -owner wolf {
    wolf_step "export_floorplan_def"
    wolf_inject_for_step export_floorplan_def pre
    # A durable, reloadable snapshot of this stage's own floorplan --
    # written every floorplan run (cheap), independent of whatever
    # created the floorplan (create_fplan's own injected Tcl, or a
    # previously loaded constraints.floorplan_def). Reload it in a later
    # run (e.g. after re-running synthesis, so there is no Innovus DB to
    # restore from) by copying it into the project's own
    # inputs/floorplans/<design>/ and pointing constraints.floorplan_def
    # at that copy -- load_floorplan's own read_def picks it up from
    # there automatically; WOLF does not promote run outputs into project
    # inputs on its own.
    set wolf_fp_def_out [file join $::wolf_outputs_dir "$::wolf_design_name.floorplan.def"]
    write_def $wolf_fp_def_out
    wolf_file $wolf_fp_def_out
    wolf_inject_for_step export_floorplan_def post
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
    # Visibility into how the SDC clocks turned into clock trees -- read
    # only (get_db clock_trees .name is the same enumeration already used
    # above to check whether a spec exists at all).
    set wolf_clock_tree_names [get_db clock_trees .name]
    wolf_info "clock trees after add_clock_spec: $wolf_clock_tree_names"
    wolf_inject_for_step add_clock_spec post
    puts [wolf_sep]
}

create_flow_step -name add_clock_route_types -owner wolf {
    wolf_step "add_clock_route_types"
    wolf_inject_for_step add_clock_route_types pre
    # backend.cadence-flowtool.clock_routing: an optional non-default rule
    # (create_route_rule -width_multiplier/-spacing_multiplier, confirmed
    # real, man 20.15) and top/trunk/leaf route types (create_route_type
    # -route_rule/-top_preferred_layer/-bottom_preferred_layer) for
    # cts_route_type_top/trunk/leaf below. Layer names are validated
    # against the loaded technology's own layers (get_db layers .name) --
    # not guessed -- and this step fails clearly, before CTS runs, if a
    # configured layer does not exist. Left unset (today's default): this
    # step is a no-op, same as before this existed.
    set wolf_route_rule_name ""
    if {[llength $::wolf_clock_routing_width_mult] || [llength $::wolf_clock_routing_spacing_mult]} {
        set wolf_configured_layers {}
        foreach {wolf_layer_range wolf_mult} [concat $::wolf_clock_routing_width_mult $::wolf_clock_routing_spacing_mult] {
            foreach wolf_layer [split $wolf_layer_range ":"] { lappend wolf_configured_layers $wolf_layer }
        }
        set wolf_known_layers [get_db layers .name]
        foreach wolf_layer $wolf_configured_layers {
            if {[lsearch -exact $wolf_known_layers $wolf_layer] < 0} {
                wolf_error "add_clock_route_types: layer '$wolf_layer' (from backend.cadence-flowtool.clock_routing.rule) does not exist in the loaded technology -- known layers: $wolf_known_layers"
                return -code error "add_clock_route_types: unknown layer '$wolf_layer'"
            }
        }
        set wolf_route_rule_name wolf_cts_rule
        set wolf_rule_args [list -name $wolf_route_rule_name]
        if {[llength $::wolf_clock_routing_width_mult]} {
            lappend wolf_rule_args -width_multiplier $::wolf_clock_routing_width_mult
        }
        if {[llength $::wolf_clock_routing_spacing_mult]} {
            lappend wolf_rule_args -spacing_multiplier $::wolf_clock_routing_spacing_mult
        }
        eval create_route_rule $wolf_rule_args
        wolf_info "create_route_rule $wolf_route_rule_name: width_multiplier=$::wolf_clock_routing_width_mult spacing_multiplier=$::wolf_clock_routing_spacing_mult"
    }
    foreach {wolf_type_name wolf_type_spec} $::wolf_clock_routing_types {
        set wolf_use_rule [dict get $wolf_type_spec use_rule]
        set wolf_top [dict get $wolf_type_spec top_preferred_layer]
        set wolf_bottom [dict get $wolf_type_spec bottom_preferred_layer]
        foreach wolf_layer [list $wolf_top $wolf_bottom] {
            if {$wolf_layer ne "" && [lsearch -exact [get_db layers .name] $wolf_layer] < 0} {
                wolf_error "add_clock_route_types: layer '$wolf_layer' (clock_routing.types.$wolf_type_name) does not exist in the loaded technology"
                return -code error "add_clock_route_types: unknown layer '$wolf_layer'"
            }
        }
        set wolf_type_name_full "wolf_cts_$wolf_type_name"
        set wolf_type_args [list -name $wolf_type_name_full]
        if {$wolf_use_rule && $wolf_route_rule_name ne ""} { lappend wolf_type_args -route_rule $wolf_route_rule_name }
        if {$wolf_top ne ""} { lappend wolf_type_args -top_preferred_layer $wolf_top }
        if {$wolf_bottom ne ""} { lappend wolf_type_args -bottom_preferred_layer $wolf_bottom }
        eval create_route_type $wolf_type_args
        set_db cts_route_type_$wolf_type_name $wolf_type_name_full
        wolf_info "create_route_type $wolf_type_name_full -> cts_route_type_$wolf_type_name (route_rule=$wolf_use_rule top=$wolf_top bottom=$wolf_bottom)"
    }
    if {[dict size $::wolf_clock_routing_types] == 0 && $wolf_route_rule_name eq ""} {
        wolf_info "add_clock_route_types: no backend.cadence-flowtool.clock_routing configured -- using CTS's own default route types"
    }
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

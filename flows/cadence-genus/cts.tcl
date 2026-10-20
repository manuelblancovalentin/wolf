# WOLF's default Cadence Innovus implementation flow -- clock tree
# synthesis and post-CTS hold optimization. Cadence's own vendor-neutral
# Genus Stylus flow template's Innovus-specific reference content
# (add_clock_tree/add_tieoffs/run_opt_postcts_hold), just given wolf_step
# banners and wolf_inject hooks for consistency. This is a real, editable
# part of the flow, not generated output; see presentation.tcl's header
# for how to fork it.

create_flow_step -name CMD_check_design_cts -owner wolf {
    wolf_inject_for_step CMD_check_design_cts pre
    set cmd_check_design_cts_file \
        [file join [get_db flow_report_directory] [get_db flow_report_name] checkDesignCTS.rpt]
    check_design -type cts -out_file $cmd_check_design_cts_file
    wolf_file $cmd_check_design_cts_file
    wolf_inject_for_step CMD_check_design_cts post
}

create_flow_step -name add_clock_tree -owner wolf {
    wolf_step "add_clock_tree: implementing clock trees, propagated-clock optimization"
    wolf_inject_for_step add_clock_tree pre

    set wolf_reports_dir [file join [get_flow_config reports_dir] [get_db flow_report_name]]
    ccopt_design -report_dir $wolf_reports_dir -report_prefix cts.

    set add_clock_tree_timing_file [file join $wolf_reports_dir timing.cts.rpt]
    report_timing_summary -checks {setup drv} > $add_clock_tree_timing_file
    wolf_file $add_clock_tree_timing_file

    # Visibility into how the SDC clocks turned into real clock trees
    # once CCOpt has actually built them (report_clock_trees: read-only,
    # usable "any time after defining or extracting clock trees" per its
    # own man page).
    set wolf_clock_tree_names [get_db clock_trees .name]
    wolf_info "clock trees after add_clock_tree: $wolf_clock_tree_names"
    set add_clock_tree_structure_file [file join $wolf_reports_dir clock_trees.cts.rpt]
    report_clock_trees -out_file $add_clock_tree_structure_file
    wolf_file $add_clock_tree_structure_file

    wolf_inject_for_step add_clock_tree post
    puts [wolf_sep]
} -write_db

create_flow_step -name add_tieoffs -owner wolf {
    wolf_inject_for_step add_tieoffs pre
    # backend.cadence-flowtool.tieoffs: resolves add_tieoffs_cells (at
    # most two: one tie-high driver, one tie-low driver, man 20.15) and
    # its companion attributes before the existing guard below. Left
    # unset (today's default): add_tieoffs_cells stays whatever it
    # already was (likely empty), same behavior as before this existed.
    # Coexists with a project's own floorplan script that already calls
    # connect_global_net -type tie_hi/-type tie_lo: that only ties
    # *existing* tie pins on cells already in the netlist to the
    # power/ground rails -- it does not insert any tie-cell instances.
    # add_tieoffs is what actually inserts tie-high/tie-low driver cells
    # for the literal 1'b0/1'b1 connections Genus left as constants; the
    # two are complementary; add_tieoffs should run after the floorplan
    # script's own global net connections, which it already does here.
    set wolf_tieoff_cells [get_flow_config add_tieoffs_cells -quiet]
    if {[llength $wolf_tieoff_cells]} {
        set_db add_tieoffs_cells $wolf_tieoff_cells
        wolf_info "add_tieoffs_cells: $wolf_tieoff_cells"
    }
    set wolf_tieoff_honor_dont_use [get_flow_config add_tieoffs_honor_dont_use -quiet]
    if {$wolf_tieoff_honor_dont_use ne ""} {
        set_db add_tieoffs_honor_dont_use $wolf_tieoff_honor_dont_use
    }
    set wolf_tieoff_max_fanout [get_flow_config add_tieoffs_max_fanout -quiet]
    if {$wolf_tieoff_max_fanout ne ""} {
        set_db add_tieoffs_max_fanout $wolf_tieoff_max_fanout
    }
    set wolf_tieoff_max_distance [get_flow_config add_tieoffs_max_distance -quiet]
    if {$wolf_tieoff_max_distance ne ""} {
        set_db add_tieoffs_max_distance $wolf_tieoff_max_distance
    }
    #- insert dedicated tieoff models, if any are configured
    if {[get_db add_tieoffs_cells] ne ""} {
        delete_tieoffs
        add_tieoffs -matching_power_domains true
        set wolf_tie_count 0
        foreach wolf_tie_cell [get_db add_tieoffs_cells] {
            incr wolf_tie_count [llength [get_db insts -if {.base_cell.name == $wolf_tie_cell}]]
        }
        wolf_info "add_tieoffs: $wolf_tie_count tie cell instance(s) added ([get_db add_tieoffs_cells])"
        set add_tieoffs_check_file \
            [file join [get_flow_config reports_dir] [get_db flow_report_name] tieoffs.cts.rpt]
        check_tieoffs -out_file $add_tieoffs_check_file
        wolf_file $add_tieoffs_check_file
    } else {
        wolf_error "add_tieoffs: no tie-high/tie-low cells configured (add_tieoffs_cells in setup.yaml) -- literal 1'b0/1'b1 connections from synthesis will have no tie-cell driver, a likely LVS/DRC problem"
    }
    wolf_inject_for_step add_tieoffs post
}

create_flow_step -name run_opt_postcts_hold -owner wolf {
    wolf_step "run_opt_postcts_hold: post-CTS hold optimization"
    wolf_inject_for_step run_opt_postcts_hold pre

    set wolf_reports_dir [file join [get_flow_config reports_dir] [get_db flow_report_name]]
    opt_design -post_cts -hold -report_dir $wolf_reports_dir -report_prefix postcts.

    set run_opt_postcts_hold_timing_file [file join $wolf_reports_dir timing.postcts_hold.rpt]
    report_timing_summary -checks {hold drv} > $run_opt_postcts_hold_timing_file
    wolf_file $run_opt_postcts_hold_timing_file

    wolf_inject_for_step run_opt_postcts_hold post
    puts [wolf_sep]
} -write_db

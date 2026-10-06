# WOLF's default Cadence Innovus implementation flow -- clock tree
# synthesis and post-CTS hold optimization. Cadence's own vendor-neutral
# Genus Stylus flow template's Innovus-specific reference content
# (add_clock_tree/add_tieoffs/run_opt_postcts_hold), just given wolf_step
# banners and wolf_inject hooks for consistency. This is a real, editable
# part of the flow, not generated output; see presentation.tcl's header
# for how to fork it.

create_flow_step -name CMD_check_design_cts -owner wolf {
    wolf_inject_for_step CMD_check_design_cts pre
    set cmd_check_design_cts_file [file join [get_db flow_report_directory] checkDesignCTS.rpt]
    check_design -type cts -out_file $cmd_check_design_cts_file
    wolf_file $cmd_check_design_cts_file
    wolf_inject_for_step CMD_check_design_cts post
}

create_flow_step -name add_clock_tree -owner wolf {
    wolf_step "add_clock_tree: implementing clock trees, propagated-clock optimization"
    wolf_inject_for_step add_clock_tree pre

    ccopt_design -report_dir $::wolf_reports_dir -report_prefix cts.

    set add_clock_tree_timing_file [file join $::wolf_reports_dir timing.cts.rpt]
    report_timing_summary -checks {setup drv} > $add_clock_tree_timing_file
    wolf_file $add_clock_tree_timing_file

    wolf_inject_for_step add_clock_tree post
    puts [wolf_sep]
} -write_db

create_flow_step -name add_tieoffs -owner wolf {
    wolf_inject_for_step add_tieoffs pre
    #- insert dedicated tieoff models, if any are configured
    if {[get_db add_tieoffs_cells] ne ""} {
        delete_tieoffs
        add_tieoffs -matching_power_domains true
    }
    wolf_inject_for_step add_tieoffs post
}

create_flow_step -name run_opt_postcts_hold -owner wolf {
    wolf_step "run_opt_postcts_hold: post-CTS hold optimization"
    wolf_inject_for_step run_opt_postcts_hold pre

    opt_design -post_cts -hold -report_dir $::wolf_reports_dir -report_prefix postcts.

    set run_opt_postcts_hold_timing_file [file join $::wolf_reports_dir timing.postcts_hold.rpt]
    report_timing_summary -checks {hold drv} > $run_opt_postcts_hold_timing_file
    wolf_file $run_opt_postcts_hold_timing_file

    wolf_inject_for_step run_opt_postcts_hold post
    puts [wolf_sep]
} -write_db

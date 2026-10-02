# WOLF's default Cadence Innovus implementation flow -- clock tree
# synthesis and post-CTS hold optimization. Cadence's own vendor-neutral
# Genus Stylus flow template's Innovus-specific reference content
# (add_clock_tree/add_tieoffs/run_opt_postcts_hold), just given wolf_step
# banners and wolf_inject hooks for consistency. This is a real, editable
# part of the flow, not generated output; see presentation.tcl's header
# for how to fork it.

create_flow_step -name add_clock_tree -owner wolf {
    wolf_step "add_clock_tree: implementing clock trees, propagated-clock optimization"
    wolf_inject_for_step add_clock_tree pre

    ccopt_design -report_dir $::wolf_reports_dir -report_prefix cts.

    report_timing_summary -checks {setup drv} > [file join $::wolf_reports_dir timing.cts.rpt]

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

    report_timing_summary -checks {hold drv} > [file join $::wolf_reports_dir timing.postcts_hold.rpt]

    wolf_inject_for_step run_opt_postcts_hold post
    puts [wolf_sep]
} -write_db

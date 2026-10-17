# WOLF's default Cadence Innovus implementation flow -- post-route setup
# and hold optimization, the last stage of `block` (RTL to a routed,
# DRC-clean design). Cadence's own vendor-neutral Genus Stylus flow
# template's Innovus-specific reference content (run_opt_postroute,
# CMD_check_placement -- the reference flow's own literal command), just
# given wolf_step banners, wolf_inject hooks, and a final report set for
# consistency. This is a real, editable part of the flow, not generated
# output; see presentation.tcl's header for how to fork it.
#
# lec/innovus_to_tempus/innovus_to_quantus/export/DRC/LVS/create_virtuoso_lib
# live in common_steps.tcl instead -- cross-cutting signoff/handoff
# concerns a future floorplan-only or route-only run would also want, not
# specific to post-route itself.

create_flow_step -name run_opt_postroute -owner wolf {
    wolf_step "run_opt_postroute: post-route setup/hold optimization"
    wolf_inject_for_step run_opt_postroute pre

    set wolf_reports_dir [get_flow_config reports_dir]
    opt_design -post_route -setup -hold -report_dir $wolf_reports_dir -report_prefix postroute.

    check_design -unresolved
    set run_opt_postroute_area_file [file join $wolf_reports_dir area.postroute.rpt]
    report_area -min_count 1000 -out_file $run_opt_postroute_area_file
    wolf_file $run_opt_postroute_area_file

    set run_opt_postroute_setup_file [file join $wolf_reports_dir timing.postroute_setup.rpt]
    report_timing_summary -checks {setup drv} > $run_opt_postroute_setup_file
    wolf_file $run_opt_postroute_setup_file

    set run_opt_postroute_hold_file [file join $wolf_reports_dir timing.postroute_hold.rpt]
    report_timing_summary -checks {hold drv} > $run_opt_postroute_hold_file
    wolf_file $run_opt_postroute_hold_file

    set run_opt_postroute_power_file [file join $wolf_reports_dir power.postroute.rpt]
    report_power -no_wrap -out_file $run_opt_postroute_power_file
    wolf_file $run_opt_postroute_power_file

    set run_opt_postroute_drc_file [file join $wolf_reports_dir route.drc.postroute.rpt]
    check_drc -out_file $run_opt_postroute_drc_file
    wolf_file $run_opt_postroute_drc_file

    wolf_inject_for_step run_opt_postroute post
    puts [wolf_sep]
} -write_db

create_flow_step -name CMD_check_placement -owner wolf {
    wolf_inject_for_step CMD_check_placement pre
    set cmd_check_placement_file \
        [file join [get_db flow_report_directory] "checkPlace.[get_db flow_report_name].rpt"]
    check_place $cmd_check_placement_file
    wolf_file $cmd_check_placement_file
    wolf_inject_for_step CMD_check_placement post
}

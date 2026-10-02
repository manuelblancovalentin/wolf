# WOLF's default Cadence Innovus implementation flow -- post-route setup
# and hold optimization, the last stage of `block` (RTL to a routed,
# DRC-clean design). Cadence's own vendor-neutral Genus Stylus flow
# template's Innovus-specific reference content (run_opt_postroute), just
# given wolf_step banners, wolf_inject hooks, and a final report set for
# consistency. This is a real, editable part of the flow, not generated
# output; see presentation.tcl's header for how to fork it.
#
# GDS/signoff export is not part of this flow yet -- it belongs to a later
# phase (real DRC/LVS signoff is a different concern from implementation).

create_flow_step -name run_opt_postroute -owner wolf {
    wolf_step "run_opt_postroute: post-route setup/hold optimization"
    wolf_inject_for_step run_opt_postroute pre

    opt_design -post_route -setup -hold -report_dir $::wolf_reports_dir -report_prefix postroute.

    check_design -unresolved
    report_area -min_count 1000 -out_file [file join $::wolf_reports_dir area.postroute.rpt]
    report_timing_summary -checks {setup drv} > [file join $::wolf_reports_dir timing.postroute_setup.rpt]
    report_timing_summary -checks {hold drv} > [file join $::wolf_reports_dir timing.postroute_hold.rpt]
    report_power -no_wrap -out_file [file join $::wolf_reports_dir power.postroute.rpt]
    check_drc -out_file [file join $::wolf_reports_dir route.drc.postroute.rpt]

    wolf_inject_for_step run_opt_postroute post
    puts [wolf_sep]
} -write_db

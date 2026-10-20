# WOLF's default Cadence Innovus implementation flow -- detail routing.
# Cadence's own vendor-neutral Genus Stylus flow template's Innovus-specific
# reference content (add_fillers/run_route), just given wolf_step banners
# and wolf_inject hooks for consistency. This is a real, editable part of
# the flow, not generated output; see presentation.tcl's header for how to
# fork it.

create_flow_step -name add_fillers -owner wolf {
    wolf_inject_for_step add_fillers pre
    #- insert filler cells before final routing, if any are configured
    if {[get_db add_fillers_cells] ne ""} {
        add_fillers
    }
    wolf_inject_for_step add_fillers post
}

create_flow_step -name run_route -owner wolf {
    wolf_step "run_route: detail routing and DRC cleanup"
    wolf_inject_for_step run_route pre

    route_design

    set run_route_drc_file \
        [file join [get_flow_config reports_dir] [get_db flow_report_name] route.drc.rpt]
    check_drc -out_file $run_route_drc_file
    wolf_file $run_route_drc_file

    wolf_inject_for_step run_route post
    puts [wolf_sep]
} -write_db

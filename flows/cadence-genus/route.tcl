# WOLF's default Cadence Innovus implementation flow -- detail routing.
# Cadence's own vendor-neutral Genus Stylus flow template's Innovus-specific
# reference content (add_fillers/run_route), just given wolf_step banners
# and wolf_inject hooks for consistency. This is a real, editable part of
# the flow, not generated output; see presentation.tcl's header for how to
# fork it.

create_flow_step -name add_fillers -owner wolf {
    wolf_inject_for_step add_fillers pre
    # add_fillers_cells (man 20.15): exact filler cell names, no pattern
    # expansion documented (unlike cts_buffer_cells/etc) -- its own
    # default is empty, so without this, add_fillers below never had
    # anything to insert and silently stayed a no-op.
    set wolf_add_fillers_cells [get_flow_config add_fillers_cells -quiet]
    if {[llength $wolf_add_fillers_cells]} {
        set_db add_fillers_cells $wolf_add_fillers_cells
        wolf_info "add_fillers_cells: $wolf_add_fillers_cells"
    }
    #- insert filler cells before final routing, if any are configured
    if {[get_db add_fillers_cells] ne ""} {
        add_fillers
    } else {
        wolf_error "add_fillers: no filler cells configured (add_fillers_cells in setup.yaml) -- no filler cell instances will be inserted, a likely LVS/DRC problem (missing power/ground rail and n-well continuity)"
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

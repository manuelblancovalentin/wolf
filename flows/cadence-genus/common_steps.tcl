# WOLF's default Cadence Genus flow -- cross-cutting flow infrastructure.
#
# Not "about synthesis": block_start/block_finish are generic Flowtool
# bookkeeping any future flow (floorplan, route, whatever Phase 2 adds)
# would also want, and genus_to_innovus is the handoff to the *next* tool,
# not the synthesis work itself. The actual synthesis actions --
# init_elaborate, set_dont_use, create_cost_group, run_syn_generic/map/opt
# -- live in synthesis.tcl instead.
#
# block_start/block_finish come from Cadence's own vendor-neutral Genus
# Stylus flow template (`write_flow_template -type stylus -tools genus`),
# not from any particular institution's flow -- block_start is itself an
# empty extension point there, block_finish's report-naming/metric-capture
# body is Cadence's generic reference content. genus_to_innovus (the
# update_names/SDC-exclusion/write_design handoff) is the same template's
# Genus-specific content, just given wolf_step banners and wolf_inject
# hooks so it's consistent with synthesis.tcl. This file is a real,
# editable part of the flow, not generated output; see presentation.tcl's
# header for how to fork it.

create_flow_step -name block_start -owner wolf {
    wolf_inject_for_step block pre
}

create_flow_step -name block_finish -owner wolf -categories flow {
    apply {{} {
        #- Reset flow_report_name from any reports executed during the step
        set_db flow_report_name [get_db [lindex [get_db flow_hier_path] end] .name]

        #- Store non-default root attributes to metrics
        catch {report_obj -tcl} flow_root_config
        if {[dict exists $flow_root_config root:/]} {
            set flow_root_config [dict get $flow_root_config root:/]
        } elseif {[dict exists $flow_root_config root:]} {
            set flow_root_config [dict get $flow_root_config root:]
        }
        foreach key [dict keys $flow_root_config] {
            if {[string length [dict get $flow_root_config $key]] > 200} {
                dict set flow_root_config $key "\[long value truncated\]"
            }
        }
        set_metric -name flow.root_config -value $flow_root_config
    }}
    wolf_inject_for_step block post
} -write_db

create_flow_step -name genus_to_innovus -owner wolf {
    wolf_step "genus_to_innovus: writing Innovus handoff"
    wolf_inject_for_step genus_to_innovus pre

    #- Apply change_name rules so the netlist is Verilog/Innovus-legal
    update_names \
        [get_db current_design] \
        -force \
        -verilog \
        -module \
        -append_log \
        -log [file join $::wolf_reports_dir design.change_names.rpt]

    #- SDCs with set_timing_derate or group_path are ignored by Innovus
    set_db write_sdc_exclude {set_timing_derate group_path}

    #- Extra pre-synthesized sub-block netlists (e.g. a hierarchically
    #  synthesized repeated tile) -- see hierarchical-synthesis notes in
    #  common_flows.tcl. Read before the handoff write so the combined
    #  netlist references them by name rather than re-expanding them.
    foreach netlist $::wolf_postsyn_netlists {
        wolf_info "Reading pre-synthesized netlist $netlist"
        read_hdl -sv -library work $netlist
    }

    file mkdir $::wolf_handoff_dir
    write_design \
        -innovus \
        -gzip_files \
        -basename [file join $::wolf_handoff_dir $::wolf_design_name]

    wolf_inject_for_step genus_to_innovus post
    puts [wolf_sep]
    wolf_info "Handoff written to $::wolf_handoff_dir"
} -write_db

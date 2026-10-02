# WOLF's default Cadence Genus flow -- shared, reusable step definitions.
#
# These step bodies come from Cadence's own vendor-neutral Genus Stylus
# flow template (`write_flow_template -type stylus -tools genus`), not
# from any particular institution's flow -- genus_to_innovus, the cost
# groups, and the report steps are Cadence's generic reference content,
# only with wolf_step banners and wolf_inject hooks layered on so they're
# consistent with synthesis.tcl's project-specific steps. This file is a
# real, editable part of the flow, not generated output; see
# presentation.tcl's header for how to fork it.
#
# block_start/block_finish and report_start/report_finish are themselves
# empty extension points in Cadence's own template -- real Flowtool
# bookkeeping happens around them regardless (report directory naming,
# metric capture on block_finish). WOLF uses them for the inject hooks and
# banner, same as every other step.

create_flow_step -name block_start -owner wolf {
    wolf_inject_for_step block pre
}

create_flow_step -name block_finish -owner wolf -write_db -categories flow {
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
}

create_flow_step -name create_cost_group -owner wolf {
    wolf_step "Creating cost groups"
    wolf_inject_for_step create_cost_group pre

    #- Clear existing path_groups, then add the standard four
    get_db cost_groups -if {.name != default} -foreach {delete_obj $obj(.)}
    group_path -name in2out -from [all_inputs] -to [all_outputs]
    if {[sizeof_collection [all_registers]] > 0} {
        group_path -name in2reg -from [all_inputs] -to [all_registers]
        group_path -name reg2out -from [all_registers] -to [all_outputs]
        group_path -name reg2reg -from [all_registers] -to [all_registers]
    }

    wolf_inject_for_step create_cost_group post
    puts [wolf_sep]
}

create_flow_step -name run_syn_generic -owner wolf {
    wolf_step "run_syn_generic: synthesizing to generic gates"
    wolf_inject_for_step run_syn_generic pre

    syn_generic

    report_area > [file join $::wolf_reports_dir area.generic.rpt]
    write_hdl > [file join $::wolf_outputs_dir $::wolf_design_name.generic.v]

    wolf_inject_for_step run_syn_generic post
    puts [wolf_sep]
} -write_db

create_flow_step -name run_syn_map -owner wolf {
    wolf_step "run_syn_map: mapping to technology library"
    wolf_inject_for_step run_syn_map pre

    syn_map

    report_area > [file join $::wolf_reports_dir area.mapped.rpt]
    write_hdl > [file join $::wolf_outputs_dir $::wolf_design_name.mapped.v]

    wolf_inject_for_step run_syn_map post
    puts [wolf_sep]
} -write_db

create_flow_step -name run_syn_opt -owner wolf {
    wolf_step "run_syn_opt: optimizing mapped netlist"
    wolf_inject_for_step run_syn_opt pre

    syn_opt

    check_design -unresolved
    report_hierarchy > [file join $::wolf_reports_dir hierarchy.rpt]
    report_messages > [file join $::wolf_reports_dir messages.rpt]
    report_area > [file join $::wolf_reports_dir area.opt.rpt]
    report_timing_summary -checks {setup drv} > [file join $::wolf_reports_dir timing.opt.rpt]
    report_power > [file join $::wolf_reports_dir power.opt.rpt]
    write_hdl > [file join $::wolf_outputs_dir $::wolf_design_name.opt.v]

    wolf_inject_for_step run_syn_opt post
    puts [wolf_sep]
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

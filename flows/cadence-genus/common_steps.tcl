# WOLF's default Cadence Genus flow -- cross-cutting flow infrastructure.
#
# Not "about synthesis": block_start/block_finish are generic Flowtool
# bookkeeping any future flow (floorplan, route, whatever Phase 2 adds)
# would also want, and genus_to_innovus/genus_to_lec/genus_to_clp/
# build_sim_testbench/build_xsim_files are all handoffs to a tool or
# artifact *downstream* of Genus, not the synthesis work itself. The
# actual synthesis actions -- read_hdl, elaborate, set_dont_use,
# create_cost_group, run_syn_generic/map/opt, report_synth -- live in
# synthesis.tcl instead.
#
# block_start/block_finish come from Cadence's own vendor-neutral Genus
# Stylus flow template (`write_flow_template -type stylus -tools genus`),
# not from any particular institution's flow -- block_start is itself an
# empty extension point there, block_finish's report-naming/metric-capture
# body is Cadence's generic reference content. genus_to_innovus (the
# update_names/SDC-exclusion/write_design handoff) is the same template's
# Genus-specific content, just given wolf_step banners and wolf_inject
# hooks so it's consistent with synthesis.tcl.
#
# genus_to_lec, genus_to_clp, build_sim_testbench, and build_xsim_files
# are left as real, named, always-invokable extension points -- block_start
# itself is the established precedent for this -- rather than WOLF
# fabricating Conformal LEC/CLP dofile syntax or a testbench/compile-script
# shape it has no visibility into. Fill a step's body through
# wolf_inject_for_step, or fork this flow (see below) and write the real
# command directly.
#
# This file is a real, editable part of the flow, not generated output;
# see presentation.tcl's header for how to fork it.

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
    set genus_to_innovus_change_names_log [file join $::wolf_reports_dir design.change_names.rpt]
    update_names \
        [get_db current_design] \
        -force \
        -verilog \
        -module \
        -append_log \
        -log $genus_to_innovus_change_names_log
    wolf_file $genus_to_innovus_change_names_log

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
    wolf_file "$::wolf_handoff_dir/$::wolf_design_name.{v,sdc,invs_init.tcl}.gz"

    wolf_inject_for_step genus_to_innovus post
    puts [wolf_sep]
    wolf_info "Handoff written to $::wolf_handoff_dir"
} -write_db

# Conformal LEC dofile handoff. Left as a real extension point rather than
# WOLF emitting a guessed `write_do_lec` invocation: golden/revised design
# selection and LEC script conventions are project- and license-specific,
# not something WOLF can resolve from a technology or design package.
create_flow_step -name genus_to_lec -owner wolf {
    wolf_step "genus_to_lec"
    wolf_inject_for_step genus_to_lec pre
    wolf_inject_for_step genus_to_lec post
    puts [wolf_sep]
}

# Conformal CLP (low-power verification) dofile handoff. Same status as
# genus_to_lec -- a real, named extension point, not a guessed command.
create_flow_step -name genus_to_clp -owner wolf {
    wolf_step "genus_to_clp"
    wolf_inject_for_step genus_to_clp pre
    wolf_inject_for_step genus_to_clp post
    puts [wolf_sep]
}

# Gate-level simulation testbench generation. Same status as
# genus_to_lec/genus_to_clp -- the real testbench shape is project-specific.
create_flow_step -name build_sim_testbench -owner wolf {
    wolf_step "build_sim_testbench"
    wolf_inject_for_step build_sim_testbench pre
    wolf_inject_for_step build_sim_testbench post
    puts [wolf_sep]
}

# Xcelium/xsim compile-script generation for the testbench above. Same
# status as build_sim_testbench.
create_flow_step -name build_xsim_files -owner wolf {
    wolf_step "build_xsim_files"
    wolf_inject_for_step build_xsim_files pre
    wolf_inject_for_step build_xsim_files post
    puts [wolf_sep]
}

#=============================================================================
# Innovus implementation reporting -- shared across report_floorplan/
# report_prects/report_postcts/report_postroute (see common_flows.tcl),
# same reuse pattern as synthesis.tcl's report_synth. Real, read-only
# Innovus commands whose name matches the step name exactly (the same
# convention already confirmed safe for read_mmmc/read_hdl/read_def
# in synthesis.tcl -- create_flow_step's name and the Tcl command it
# calls live in separate namespaces, so this is not a collision).
#=============================================================================

create_flow_step -name report_check_design -owner wolf {
    wolf_inject_for_step report_check_design pre
    set report_check_design_file \
        [file join [get_db flow_report_directory] "checkDesign.[get_db flow_report_name].rpt"]
    # "place" is the one -type value already confirmed real and valid
    # against this flow (see CMD_check_place/CMD_check_design_cts) --
    # reused here rather than guessing a per-stage enum value Innovus
    # may not actually accept.
    check_design -type place -out_file $report_check_design_file
    wolf_file $report_check_design_file
    wolf_inject_for_step report_check_design post
}

create_flow_step -name report_area_innovus -owner wolf {
    wolf_inject_for_step report_area_innovus pre
    set report_area_innovus_file [file join $::wolf_reports_dir "area.[get_db flow_report_name].rpt"]
    report_area -min_count 1000 > $report_area_innovus_file
    wolf_file $report_area_innovus_file
    wolf_inject_for_step report_area_innovus post
}

create_flow_step -name report_power_innovus -owner wolf {
    wolf_inject_for_step report_power_innovus pre
    set report_power_innovus_file [file join $::wolf_reports_dir "power.[get_db flow_report_name].rpt"]
    report_power -no_wrap > $report_power_innovus_file
    wolf_file $report_power_innovus_file
    wolf_inject_for_step report_power_innovus post
}

create_flow_step -name report_late_paths -owner wolf {
    wolf_inject_for_step report_late_paths pre
    set report_late_paths_file [file join $::wolf_reports_dir "late_paths.[get_db flow_report_name].rpt"]
    report_timing -nworst 5 > $report_late_paths_file
    wolf_file $report_late_paths_file
    wolf_inject_for_step report_late_paths post
}

create_flow_step -name report_clock_timing -owner wolf {
    wolf_inject_for_step report_clock_timing pre
    set report_clock_timing_file [file join $::wolf_reports_dir "clock_timing.[get_db flow_report_name].rpt"]
    report_clock_timing > $report_clock_timing_file
    wolf_file $report_clock_timing_file
    wolf_inject_for_step report_clock_timing post
}

create_flow_step -name report_route_drc -owner wolf {
    wolf_inject_for_step report_route_drc pre
    set report_route_drc_file [file join $::wolf_reports_dir "route_drc.[get_db flow_report_name].rpt"]
    check_drc -out_file $report_route_drc_file
    wolf_file $report_route_drc_file
    wolf_inject_for_step report_route_drc post
}

create_flow_step -name report_route_density -owner wolf {
    wolf_inject_for_step report_route_density pre
    set report_route_density_file [file join $::wolf_reports_dir "route_density.[get_db flow_report_name].rpt"]
    report_route_density > $report_route_density_file
    wolf_file $report_route_density_file
    wolf_inject_for_step report_route_density post
}

# Early-mode (hold-oriented) timing summary/paths. Left as extension
# points rather than guessing: the real Innovus command for a *report*
# here is `timeDesign`, which in some modes also performs real timing
# optimization as a side effect -- guessing the wrong flag combination
# risks silently changing the design, not just erroring loudly the way a
# bad report command would. Fill in via wolf_inject_for_step once the
# exact read-only invocation for this project's Innovus version is
# confirmed.
create_flow_step -name report_early_summary_innovus -owner wolf {
    wolf_inject_for_step report_early_summary_innovus pre
    wolf_inject_for_step report_early_summary_innovus post
}

create_flow_step -name report_early_paths -owner wolf {
    wolf_inject_for_step report_early_paths pre
    wolf_inject_for_step report_early_paths post
}

create_flow_step -name report_late_summary_innovus -owner wolf {
    wolf_inject_for_step report_late_summary_innovus pre
    wolf_inject_for_step report_late_summary_innovus post
}

#=============================================================================
# Signoff/handoff extension points downstream of Innovus -- export, DRC/LVS
# (Calibre), LEC (Conformal), and schematic/Virtuoso library generation.
# Same status as genus_to_lec/genus_to_clp/build_sim_testbench above: real,
# named, always-invokable steps, bodies intentionally left for
# wolf_inject_for_step or a forked flow to fill in, since the actual
# commands (TSMC65_run_Calibre_DRC/LVS in particular) are institution-
# specific Calibre integration WOLF has no visibility into.
#=============================================================================

create_flow_step -name export -owner wolf {
    wolf_step "export: writing design data"
    wolf_inject_for_step export pre
    wolf_inject_for_step export post
    puts [wolf_sep]
}

create_flow_step -name DRC -owner wolf {
    wolf_step "DRC"
    wolf_inject_for_step DRC pre
    wolf_inject_for_step DRC post
    puts [wolf_sep]
}

create_flow_step -name LVS -owner wolf {
    wolf_step "LVS"
    wolf_inject_for_step LVS pre
    wolf_inject_for_step LVS post
    puts [wolf_sep]
}

create_flow_step -name lec -owner wolf {
    wolf_step "lec"
    wolf_inject_for_step lec pre
    wolf_inject_for_step lec post
    puts [wolf_sep]
}

create_flow_step -name innovus_to_tempus -owner wolf {
    wolf_step "innovus_to_tempus"
    wolf_inject_for_step innovus_to_tempus pre
    wolf_inject_for_step innovus_to_tempus post
    puts [wolf_sep]
}

create_flow_step -name innovus_to_quantus -owner wolf {
    wolf_step "innovus_to_quantus"
    wolf_inject_for_step innovus_to_quantus pre
    wolf_inject_for_step innovus_to_quantus post
    puts [wolf_sep]
}

create_flow_step -name create_virtuoso_lib -owner wolf {
    wolf_step "create_virtuoso_lib"
    wolf_inject_for_step create_virtuoso_lib pre
    wolf_inject_for_step create_virtuoso_lib post
    puts [wolf_sep]
}

create_flow_step -name schedule_signoff_subflows -owner wolf {
    wolf_step "schedule_signoff_subflows"
    wolf_inject_for_step schedule_signoff_subflows pre
    wolf_inject_for_step schedule_signoff_subflows post
    puts [wolf_sep]
}

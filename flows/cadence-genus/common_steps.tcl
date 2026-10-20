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
    set genus_to_innovus_change_names_log \
        [file join [get_flow_config reports_dir] [get_db flow_report_name] design.change_names.rpt]
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
    foreach netlist [get_flow_config postsyn_netlists -quiet] {
        wolf_info "Reading pre-synthesized netlist $netlist"
        read_hdl -sv -library work $netlist
    }

    set wolf_handoff_dir [get_flow_config handoff_dir]
    set wolf_design_name [get_flow_config design_name]
    file mkdir $wolf_handoff_dir
    write_design \
        -innovus \
        -gzip_files \
        -basename [file join $wolf_handoff_dir $wolf_design_name]
    wolf_file "$wolf_handoff_dir/$wolf_design_name.{v,sdc,invs_init.tcl}.gz"

    wolf_inject_for_step genus_to_innovus post
    puts [wolf_sep]
    wolf_info "Handoff written to $wolf_handoff_dir"
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
        [file join [get_db flow_report_directory] [get_db flow_report_name] \
            "checkDesign.[get_db flow_report_name].rpt"]
    # "place" and "cts" are both confirmed real, valid -type values (man
    # 20.15; "cts" is also already used as-is by CMD_check_design_cts).
    # This step is shared by report_floorplan/report_prects (still in
    # place-oriented stages) and report_postcts/report_postroute (already
    # past CTS) -- [lindex [get_db flow_hier_path] 0] is the same
    # top-level stage-name lookup block_finish's own flow_report_name
    # reset already relies on, just indexed at the start of the path
    # instead of the end.
    set report_check_design_stage [lindex [get_db flow_hier_path] 0]
    if {[lsearch -exact {cts postcts} $report_check_design_stage] >= 0} {
        set report_check_design_type cts
    } else {
        set report_check_design_type place
    }
    check_design -type $report_check_design_type -out_file $report_check_design_file
    wolf_file $report_check_design_file
    wolf_inject_for_step report_check_design post
}

#=============================================================================
# set_cts_config -- shared by prects and cts: CCOpt cell selection
# (cts_buffer_cells/cts_inverter_cells/cts_clock_gating_cells) and timing
# targets (cts_target_skew/cts_target_max_transition_time/cts_max_fanout),
# from this design's own setup.<design>.yaml (get_flow_config). Cell
# selection defaults to the loaded library's own is_buffer/is_inverter/
# is_integrated_clock_gating cells (excluding dont_use) when setup.yaml
# gives no explicit value -- see the foreach below. Each stage is a
# separate Innovus invocation restored from a checkpoint, and whether
# these root attributes survive that restore is not documented anywhere
# WOLF found -- re-applying idempotently at the start of both stages
# (prects, before add_clock_spec; cts, before CMD_check_design_cts) is
# the safe default rather than assuming persistence.
#=============================================================================

create_flow_step -name set_cts_config -owner wolf {
    wolf_inject_for_step set_cts_config pre
    set wolf_cts_applied 0
    # cts_buffer_cells/cts_inverter_cells/cts_clock_gating_cells: when
    # setup.yaml gives no explicit value, default to every real
    # buffer/inverter/integrated-clock-gate cell the loaded library
    # itself reports (base_cell's own is_buffer/is_inverter/
    # is_integrated_clock_gating, confirmed real attributes), excluding
    # anything already dont_use -- not left for CCOpt to pick from the
    # whole library on its own, since a name that happens to collide
    # with a different cell family (confirmed real: a plain "CKND*"
    # prefix glob also matched the unrelated CKND2D* NAND family) is
    # exactly the kind of mistake querying the real attributes avoids.
    # setup.yaml's own value, when given, replaces this default outright
    # (not merged with it) -- same precedence as every other cts_* key.
    foreach {wolf_cts_attr wolf_cts_is_attr} {
        cts_buffer_cells is_buffer
        cts_inverter_cells is_inverter
        cts_clock_gating_cells is_integrated_clock_gating
    } {
        set wolf_cts_value [get_flow_config $wolf_cts_attr -quiet]
        set wolf_cts_source "[ansicolor::+ bold cyan](setup.yaml override)[ansicolor::+]"
        if {![llength $wolf_cts_value]} {
            set wolf_cts_filter ".$wolf_cts_is_attr == true && .dont_use == false"
            set wolf_cts_value [get_db [get_db base_cells -if $wolf_cts_filter] .name]
            set wolf_cts_source "[ansicolor::+ bold green](library default)[ansicolor::+]"
        }
        if {[llength $wolf_cts_value]} {
            set_db $wolf_cts_attr $wolf_cts_value
            wolf_info "$wolf_cts_attr: $wolf_cts_value $wolf_cts_source"
            set wolf_cts_applied 1
        }
    }
    # cts_buffer_cells_top/_leaf and cts_inverter_cells_top/_leaf
    # (confirmed real, man 20.15) narrow the plain/default attribute to
    # top-net-only or leaf-net-only cells; there is no _trunk variant for
    # either (trunk nets use the plain attribute). clock_gating_cells has
    # no top/leaf variant at all. These stay opt-in-only refinements --
    # no library-attribute default, since "leaf-only buffer" has no
    # equivalent base_cell attribute to query.
    foreach wolf_cts_attr {
        cts_buffer_cells_top cts_buffer_cells_leaf
        cts_inverter_cells_top cts_inverter_cells_leaf
    } {
        set wolf_cts_value [get_flow_config $wolf_cts_attr -quiet]
        if {[llength $wolf_cts_value]} {
            set_db $wolf_cts_attr $wolf_cts_value
            wolf_info "$wolf_cts_attr: $wolf_cts_value"
            set wolf_cts_applied 1
        }
    }
    set wolf_cts_target_skew [get_flow_config cts_target_skew -quiet]
    set wolf_cts_target_max_transition_time [get_flow_config cts_target_max_transition_time -quiet]
    set wolf_cts_max_fanout [get_flow_config cts_max_fanout -quiet]
    if {$wolf_cts_target_skew ne ""} {
        set_db cts_target_skew $wolf_cts_target_skew
        wolf_info "cts_target_skew: $wolf_cts_target_skew"
        set wolf_cts_applied 1
    }
    if {$wolf_cts_target_max_transition_time ne ""} {
        set_db cts_target_max_transition_time $wolf_cts_target_max_transition_time
        wolf_info "cts_target_max_transition_time: $wolf_cts_target_max_transition_time"
        set wolf_cts_applied 1
    }
    if {$wolf_cts_max_fanout ne ""} {
        set_db cts_max_fanout $wolf_cts_max_fanout
        wolf_info "cts_max_fanout: $wolf_cts_max_fanout"
        set wolf_cts_applied 1
    }
    if {!$wolf_cts_applied} {
        wolf_info "set_cts_config: no cts_* overrides in setup.yaml and no matching library cells found -- CCOpt uses its own built-in defaults"
    }
    wolf_inject_for_step set_cts_config post
}

#=============================================================================
# commit_power_intent -- shared by Genus's syn_generic (synthesis.tcl calls
# it via common_flows.tcl) and Innovus's floorplan (floorplanning.tcl):
# identical content on both sides (commit whatever UPF/CPF read_power_intent
# loaded, if any), so defined once here rather than duplicated per tool.
#=============================================================================

create_flow_step -name commit_power_intent -owner wolf {
    wolf_step "commit_power_intent"
    wolf_inject_for_step commit_power_intent pre

    if {[get_flow_config power_intent_file -quiet] ne ""} {
        commit_power_intent
    } else {
        wolf_info "commit_power_intent: no power intent was read, skipping"
    }

    wolf_inject_for_step commit_power_intent post
    puts [wolf_sep]
}

create_flow_step -name report_area_innovus -owner wolf {
    wolf_inject_for_step report_area_innovus pre
    set report_area_innovus_file \
        [file join [get_flow_config reports_dir] [get_db flow_report_name] \
            "area.[get_db flow_report_name].rpt"]
    report_area -min_count 1000 > $report_area_innovus_file
    wolf_file $report_area_innovus_file
    wolf_inject_for_step report_area_innovus post
}

create_flow_step -name report_power_innovus -owner wolf {
    wolf_inject_for_step report_power_innovus pre
    set report_power_innovus_file \
        [file join [get_flow_config reports_dir] [get_db flow_report_name] \
            "power.[get_db flow_report_name].rpt"]
    report_power -no_wrap > $report_power_innovus_file
    wolf_file $report_power_innovus_file
    wolf_inject_for_step report_power_innovus post
}

create_flow_step -name report_late_paths -owner wolf {
    wolf_inject_for_step report_late_paths pre
    set report_late_paths_file \
        [file join [get_flow_config reports_dir] [get_db flow_report_name] \
            "late_paths.[get_db flow_report_name].rpt"]
    report_timing -nworst 5 > $report_late_paths_file
    wolf_file $report_late_paths_file
    wolf_inject_for_step report_late_paths post
}

create_flow_step -name report_clock_timing -owner wolf {
    wolf_inject_for_step report_clock_timing pre
    set report_clock_timing_file \
        [file join [get_flow_config reports_dir] [get_db flow_report_name] \
            "clock_timing.[get_db flow_report_name].rpt"]
    # -type is a required argument (man 20.15, TCLCMD-982 otherwise) --
    # skew is the report's own first documented example ("reports worst
    # case skew for all clocks in a design") and the plain, no-argument
    # default every other report_* step here already uses elsewhere.
    report_clock_timing -type skew > $report_clock_timing_file
    wolf_file $report_clock_timing_file
    wolf_inject_for_step report_clock_timing post
}

create_flow_step -name report_route_drc -owner wolf {
    wolf_inject_for_step report_route_drc pre
    set report_route_drc_file \
        [file join [get_flow_config reports_dir] [get_db flow_report_name] \
            "route_drc.[get_db flow_report_name].rpt"]
    check_drc -out_file $report_route_drc_file
    wolf_file $report_route_drc_file
    wolf_inject_for_step report_route_drc post
}

create_flow_step -name report_route_density -owner wolf {
    wolf_inject_for_step report_route_density pre
    set report_route_density_file \
        [file join [get_flow_config reports_dir] [get_db flow_report_name] \
            "route_density.[get_db flow_report_name].rpt"]
    report_route_density > $report_route_density_file
    wolf_file $report_route_density_file
    wolf_inject_for_step report_route_density post
}

# Early (hold) / late (setup) timing summary and paths -- report_timing_summary
# and report_timing are both confirmed pure read-only report commands
# (man 20.15: neither's description mentions any optimization side
# effect, unlike timeDesign, which some modes of *do* perform real
# optimization -- that risk is why these were left empty before).
# -checks drv is included in both summaries the same way the Genus-side
# report_timing_summary_late_genus and this file's own run_opt_postcts_hold
# already do.
create_flow_step -name report_early_summary_innovus -owner wolf {
    wolf_inject_for_step report_early_summary_innovus pre
    set report_early_summary_innovus_file \
        [file join [get_flow_config reports_dir] [get_db flow_report_name] \
            "early_summary.[get_db flow_report_name].rpt"]
    report_timing_summary -checks {hold drv} > $report_early_summary_innovus_file
    wolf_file $report_early_summary_innovus_file
    wolf_inject_for_step report_early_summary_innovus post
}

create_flow_step -name report_early_paths -owner wolf {
    wolf_inject_for_step report_early_paths pre
    set report_early_paths_file \
        [file join [get_flow_config reports_dir] [get_db flow_report_name] \
            "early_paths.[get_db flow_report_name].rpt"]
    report_timing -early -nworst 5 > $report_early_paths_file
    wolf_file $report_early_paths_file
    wolf_inject_for_step report_early_paths post
}

create_flow_step -name report_late_summary_innovus -owner wolf {
    wolf_inject_for_step report_late_summary_innovus pre
    set report_late_summary_innovus_file \
        [file join [get_flow_config reports_dir] [get_db flow_report_name] \
            "late_summary.[get_db flow_report_name].rpt"]
    report_timing_summary -checks {setup drv} > $report_late_summary_innovus_file
    wolf_file $report_late_summary_innovus_file
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

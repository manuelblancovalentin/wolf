# WOLF's default Cadence Genus flow -- flow sequencing, expressed as real
# Stylus/Common-UI-Flow-Kit flows (create_flow), not reimplemented by WOLF:
# Flowtool itself sequences these, checkpoints them (via each step's
# -write_db), and resumes them (-from/-to select by FLOW name here --
# syn_generic/syn_map/syn_opt -- each flow's own steps, like
# init_elaborate inside syn_generic, are not independently selectable).
#
# Adapted from Cadence's own vendor-neutral Genus/Innovus Stylus flow
# template (`write_flow_template -type stylus -tools {genus innovus}`):
# the attribute definitions and flow_header_tcl below are its generic
# bookkeeping, unchanged. Its init_design/init_innovus flows
# (read_mmmc/read_physical/read_hdl/read_power_intent/run_init_design,
# init_innovus_yaml/init_innovus_user) are MMMC- and yaml-config-oriented
# and not something WOLF resolves today -- WOLF's own init_elaborate
# (synthesis.tcl) and init_implementation/init_floorplan (floorplanning.tcl)
# steps cover what WOLF does resolve for the single-corner case, so those
# vendor flows/steps are dropped from the sequences below rather than
# defined as no-ops. The implementation stages below execute the Innovus
# PnR work (floorplan/place/cts/route); they are not wired up to `wolf
# run` yet -- see docs/CADENCE_GENUS.md for current execution status.
#
# `wolf flow init --from flows/cadence-genus --to <your-copy>` clones this
# directory (presentation.tcl, common_steps.tcl, synthesis.tcl,
# floorplanning.tcl, cts.tcl, route.tcl, postroute.tcl) so a project can
# fork and edit any of these files freely; point `flow: {package: ...}`
# at the clone and WOLF resolves this file from there instead.

#- Define attribute for report name
if {![is_attribute -obj_type root flow_report_name]} {
    define_attribute flow_report_name -category flow -data_type string \
        -default "" -help_string "Name to use during report generation" -obj_type root
}

#- Define attribute for report prefix
if {![is_attribute -obj_type root flow_report_prefix]} {
    define_attribute flow_report_prefix -category flow -data_type string \
        -default "" -help_string "File prefix to use during report generation" -obj_type root
}

#- Flow header: runs at the start of run_flow, names each block's report dir
set_db flow_header_tcl {
    if {[regexp {block_start|hier_start|eco_start} [get_db flow_step_current]]} {
        set_db flow_report_name [get_db [lindex [get_db flow_hier_path] end] .name]
    }
    file mkdir [file normalize [file join [get_db flow_report_directory] [get_db flow_report_name]]]
}

# report_synth: run after every synthesis stage below, not only the last
# one -- see synthesis.tcl's own header on how its steps pick up a
# per-stage report filename automatically via [get_db flow_report_name].
create_flow -name report_synth -owner wolf -tool genus -tool_options -disable_user_startup \
    {report_start init_genus report_area_genus report_timing_summary_late_genus \
     report_late_paths report_power_genus report_hierarchy_genus report_messages_genus \
     report_finish}

create_flow -name syn_generic -owner wolf -tool genus -tool_options -disable_user_startup \
    {block_start avoid_module_renaming read_mmmc apply_clock_derate \
     read_physical read_hdl elaborate uniquify_modules preserve_blocks preserve_instances \
     read_power_intent run_init_design read_def init_genus set_dont_use prevent_flattening \
     max_routing_layer commit_power_intent create_cost_group run_syn_generic block_finish \
     report_synth}

create_flow -name syn_map -owner wolf -tool genus -tool_options -disable_user_startup \
    {block_start init_genus set_dont_use run_syn_map block_finish report_synth genus_to_lec}

create_flow -name syn_opt -owner wolf -tool genus -tool_options -disable_user_startup \
    {block_start init_genus run_syn_opt block_finish report_synth genus_to_lec genus_to_clp \
     genus_to_innovus build_sim_testbench build_xsim_files}

create_flow -name floorplan -owner wolf -tool innovus -tool_options -disable_user_startup \
    {block_start init_implementation init_floorplan add_tracks block_finish}

create_flow -name prects -owner wolf -tool innovus -tool_options -disable_user_startup \
    {block_start add_clock_spec commit_route_types run_place_opt block_finish}

create_flow -name cts -owner wolf -tool innovus -tool_options -disable_user_startup \
    {block_start add_clock_tree add_tieoffs block_finish}

create_flow -name postcts -owner wolf -tool innovus -tool_options -disable_user_startup \
    {block_start run_opt_postcts_hold block_finish}

create_flow -name route -owner wolf -tool innovus -tool_options -disable_user_startup \
    {block_start add_fillers run_route block_finish}

create_flow -name postroute -owner wolf -tool innovus -tool_options -disable_user_startup \
    {block_start run_opt_postroute block_finish}

#=============================================================================
# Flow: Toplevel Flows
#=============================================================================

create_flow -name synthesis -owner wolf -tool genus -skip_metric -tool_options -disable_user_startup \
    {syn_generic syn_map syn_opt}

create_flow -name implementation -owner wolf -tool innovus -skip_metric -tool_options -disable_user_startup \
    {floorplan prects cts postcts route postroute}

create_flow -name block -owner wolf -skip_metric {synthesis implementation}
set_db flow_top flow:block

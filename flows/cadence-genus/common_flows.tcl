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
# bookkeeping, unchanged. init_innovus_yaml/PPA_recipe_*/
# TSMC65_base_recipe_init_innovus (the vendor template's own init_innovus
# sub-steps) are explicitly legacy content from an unrelated process node
# (self-marked "Legacy from GF22NM" in the reference flow this was
# adapted from), not real TSMC65/Cadence vendor content -- dropped rather
# than ported; WOLF's own lightweight init_innovus (floorplanning.tcl)
# covers the per-stage re-init role instead. TMR is dropped per explicit
# instruction, not an oversight.
#
# The implementation flows below (floorplan/prects/cts/postcts/route/
# postroute) execute the real Innovus Tcl commands the reference flow's
# own YAML spells out verbatim (CMD_set_cong_aware, CMD_check_place,
# CMD_check_design_cts, CMD_check_placement, ...); steps whose real body
# depends on project-specific data WOLF does not resolve (die size,
# power intent file, non-default clock routing rules) or on a downstream
# tool/institution convention WOLF has no visibility into (Conformal LEC/
# CLP, Calibre DRC/LVS, Virtuoso library export, Tempus/Quantus handoff)
# are still real, named, invokable steps -- just extension points (banner
# + wolf_inject_for_step only), same precedent as the vendor template's
# own block_start. None of this is wired up to `wolf run` yet on the
# Python side -- there is no Innovus-driving equivalent of run_genus --
# see docs/CADENCE_GENUS.md for current execution status.
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

# report_floorplan/report_prects/report_postcts/report_postroute: each a
# reusable sub-flow, same report_synth-style reuse as the synthesis side
# (report_postcts is referenced by both cts and postcts below, and
# report_postroute by both route and postroute, matching the reference
# flow's own reuse exactly).
create_flow -name report_floorplan -owner wolf -tool innovus -tool_options -disable_user_startup \
    {report_start init_innovus report_check_design report_area_innovus report_route_drc \
     report_finish}

create_flow -name report_prects -owner wolf -tool innovus -tool_options -disable_user_startup \
    {report_start init_innovus report_check_design report_area_innovus \
     report_late_summary_innovus report_late_paths report_power_innovus report_finish}

create_flow -name report_postcts -owner wolf -tool innovus -tool_options -disable_user_startup \
    {report_start init_innovus report_check_design report_area_innovus \
     report_early_summary_innovus report_early_paths report_late_summary_innovus \
     report_late_paths report_clock_timing report_power_innovus report_finish}

create_flow -name report_postroute -owner wolf -tool innovus -tool_options -disable_user_startup \
    {report_start init_innovus report_check_design report_area_innovus \
     report_early_summary_innovus report_early_paths report_late_summary_innovus \
     report_late_paths report_clock_timing report_power_innovus report_route_drc \
     report_route_density report_finish}

create_flow -name floorplan -owner wolf -tool innovus -tool_options -disable_user_startup \
    {block_start init_innovus add_post_syn_constraints genus_turn_on_analysis_views \
     PPA_recipe_set_path_group_options CMD_set_cong_aware create_fplan load_floorplan \
     commit_power_intent block_finish report_floorplan lec export DRC}

create_flow -name prects -owner wolf -tool innovus -tool_options -disable_user_startup \
    {block_start init_innovus add_clock_spec add_clock_route_types commit_route_types \
     run_place_opt CMD_check_place CMD_resolve_place_violations block_finish report_prects}

create_flow -name cts -owner wolf -tool innovus -tool_options -disable_user_startup \
    {block_start init_innovus CMD_check_design_cts add_clock_tree add_tieoffs block_finish \
     report_postcts}

create_flow -name postcts -owner wolf -tool innovus -tool_options -disable_user_startup \
    {block_start init_innovus run_opt_postcts_hold block_finish report_postcts export}

create_flow -name route -owner wolf -tool innovus -tool_options -disable_user_startup \
    {block_start init_innovus add_fillers run_route block_finish report_postroute}

create_flow -name postroute -owner wolf -tool innovus -tool_options -disable_user_startup \
    {block_start init_innovus run_opt_postroute CMD_check_placement block_finish \
     report_postroute lec innovus_to_tempus innovus_to_quantus export build_xsim_files DRC LVS \
     create_virtuoso_lib}

#=============================================================================
# Flow: Toplevel Flows
#=============================================================================

create_flow -name synthesis -owner wolf -tool genus -skip_metric -tool_options -disable_user_startup \
    {syn_generic syn_map syn_opt}

create_flow -name implementation -owner wolf -tool innovus -skip_metric -tool_options -disable_user_startup \
    {floorplan prects cts postcts route postroute}

create_flow -name block -owner wolf -skip_metric {synthesis implementation}
set_db flow_top flow:block

# signoff is deliberately not part of block/implementation above -- a
# separate, explicitly invoked entry point once routing is clean, not a
# stage every run chains through automatically.
create_flow -name signoff -owner wolf -skip_metric {schedule_signoff_subflows}

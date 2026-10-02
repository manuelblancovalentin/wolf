# WOLF's default Cadence Genus flow -- flow sequencing, expressed as real
# Stylus/Common-UI-Flow-Kit flows (create_flow), not reimplemented by WOLF:
# Flowtool itself sequences these, checkpoints them (via each step's
# -write_db), and resumes them (-from/-to select by FLOW name here --
# syn_generic/syn_map/syn_opt -- each flow's own steps, like
# init_elaborate inside syn_generic, are not independently selectable).
#
# Adapted from Cadence's own vendor-neutral Genus Stylus flow template
# (`write_flow_template -type stylus -tools genus`): the attribute
# definitions and flow_header_tcl below are its generic bookkeeping,
# unchanged. Its init_design flow (read_mmmc/read_physical/read_hdl/
# read_power_intent/run_init_design) is MMMC-oriented and not something
# WOLF resolves today -- WOLF's own init_elaborate step in synthesis.tcl
# already covers technology libraries, optional physical views, RTL, and
# constraints for the single-corner case WOLF resolves, so init_design is
# dropped from the sequences below rather than defined as a no-op.
#
# `wolf flow init --from flows/cadence-genus --to <your-copy>` clones this
# directory (and presentation.tcl/common_steps.tcl/synthesis.tcl) so a
# project can fork and edit any of these files freely; point
# `flow: {package: ...}` at the clone and WOLF resolves this file from
# there instead.

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

create_flow -name syn_generic -owner wolf -tool genus -tool_options -disable_user_startup \
    {block_start init_elaborate set_dont_use create_cost_group run_syn_generic block_finish}

create_flow -name syn_map -owner wolf -tool genus -tool_options -disable_user_startup \
    {block_start run_syn_map block_finish}

create_flow -name syn_opt -owner wolf -tool genus -tool_options -disable_user_startup \
    {block_start run_syn_opt block_finish genus_to_innovus}

#=============================================================================
# Flow: Toplevel Flows
#=============================================================================

create_flow -name synthesis -owner wolf -tool genus -skip_metric -tool_options -disable_user_startup \
    {syn_generic syn_map syn_opt}

create_flow -name block -owner wolf -skip_metric {synthesis}
set_db flow_top flow:block

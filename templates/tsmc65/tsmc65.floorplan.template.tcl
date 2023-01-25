
# Get design name
set design_name [get_flow_config design_name]

# Create main floorplan with specific die size
set die_width [get_flow_config floorplan_spef die_width]
set die_height [get_flow_config floorplan_spef die_height]
set margin_horizontal [get_flow_config floorplan_spef margin_horizontal]
set margin_vertical [get_flow_config floorplan_spef margin_vertical]

# Delete pevious floorplan, in case
set_io_flow_flag 0
delete_all_floorplan_objs
delete_io_fillers
set_io_flow_flag 0

set core_site_name "core"
if { [expr [llength [get_flow_config -quiet core_site_name]] > 0] } {
    # check if valid core name
    if {[lsearch -exact [get_db sites .name] [get_flow_config -quiet core_site_name]] >= 0} {
        set core_site_name [get_flow_config core_site_name]
    }
} 

create_floorplan \
    -flip s \
    -die_size $die_width $die_height $margin_horizontal $margin_vertical $margin_horizontal $margin_vertical \
    -core_margins_by io \
    -site $core_site_name \

puts "\033\[1;33m\[INFO\] - \033\[1;32mCreated \033\[1;31mfloorplan\033\[1;32m with size \033\[1;32m\{$die_width $die_height $margin_horizontal $margin_vertical $margin_horizontal $margin_vertical\}\033\[0m"

######################
# IO pins
######################
# Get io template
set io_template_file "[file join [get_flow_config inputs_dir] floorplans [get_flow_config design_name] [get_flow_config design_name].io]"
if { [expr [file readable $io_template_file] && [file exists $io_template_file] ] } {
    read_io_file $io_template_file
} else {
    # Place pins manually

}

# Power grid, etc.
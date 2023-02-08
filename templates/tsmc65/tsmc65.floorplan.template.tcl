
# Get design name
set design_name [get_flow_config design_name]

# Temporarily report area to get the total area and calculate the width/height
report_area > tmp.area
set areas [exec tail -n 1 tmp.area]
set total_area [lindex $areas 2]
rm tmp.area

# Set die_width and height to default minimum values according to total area
set margin_horizontal 1.0
set margin_vertical 1.0
set die_width [expr sqrt($total_area/0.7) + 2*$margin_horizontal]
set die_height [expr sqrt($total_area/0.7) + 2*$margin_vertical]

# Create main floorplan with specific die size
if { [get_flow_config -q floorplan_spef] ne "" } {

    if { [get_flow_config -q floorplan_spef die_width] ne "" } {
        set die_width [get_flow_config floorplan_spef die_width]
    } 
    if { [get_flow_config -q floorplan_spef die_height] ne "" } {
        set die_height [get_flow_config floorplan_spef die_height]
    } 
    if { [get_flow_config -q floorplan_spef margin_horizontal] ne "" } {
        set margin_horizontal [get_flow_config floorplan_spef margin_horizontal]
    }
    if { [get_flow_config -q floorplan_spef margin_vertical] ne "" } {
        set margin_vertical [get_flow_config floorplan_spef margin_vertical]
    }
}

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
    -site $core_site_name 

puts "\033\[1;33m\[INFO\] - \033\[1;32mCreated \033\[1;31mfloorplan\033\[1;32m with size \033\[1;32m\{$die_width $die_height $margin_horizontal $margin_vertical $margin_horizontal $margin_vertical\}\033\[0m"

######################
# IO pins
######################
# Get io template
set io_template_file "[file join [get_flow_config inputs_dir] floorplans [get_flow_config design_name] [get_flow_config design_name].io]"
if { [expr [file readable $io_template_file] && [file exists $io_template_file] ] } {
    read_io_file $io_template_file
} else {
    
    # [@manuelbv]: Unassign all pins
    set_partition_pin_status -pins [get_db ports .name] -status unplaced -quiet

    # [@manuelbv]: Set batch to true
    set_db assign_pins_edit_in_batch true

    # [@manuelbv]: Syntax: [dict create "direction" {Side layer separation_between_pins}]
    set pin_position [dict create "in" {"Left" 4 1.0} "out" { "Right" 4 1.0} ]

    dict for {pin_dir pin_loc_layer_and_sep} $pin_position {
        set these_pins_loc [lindex $pin_loc_layer_and_sep 0]
        set these_pins_layer [lindex $pin_loc_layer_and_sep 1]
        set these_pins_sep [lindex $pin_loc_layer_and_sep 2]
        set these_pins [get_db [get_db ports -if {.direction == "$pin_dir"}] .name]
        set npins [llength $these_pins]
        if { ($these_pins_loc eq "Left") || ($these_pins_loc eq "Right") } {
            puts "y"
            set these_pins_offset [list 0.0 [expr ($die_height - ($npins - 1)*$these_pins_sep)/2 ]]
            if { $these_pins_loc eq "Left" } { 
                set spread_dir "clockwise"
            } else {
                set spread_dir "counterclockwise"
            }
        } else {
            puts "x"
            set these_pins_offset [list [expr ($die_width - ($npins - 1)*$these_pins_sep)/2 ] 0.0]
            if { $these_pins_loc eq "Top" } { 
                set spread_dir "clockwise"
            } else {
                set spread_dir "counterclockwise"
            }
        }
        # Place pins
        edit_pin \
            -fix_overlap 1 \
            -unit micron \
            -spread_direction "$spread_dir" \
            -side "$these_pins_loc" \
            -layer "$these_pins_layer" \
            -spread_type start \
            -spacing $these_pins_sep \
            -start $these_pins_offset \
            -pin "$these_pins"
    }

    # Place pins manually
    set_db assign_pins_edit_in_batch false

    # Now write io file
    pinfo "Writing IO file to [+ green]$io_template_file[+]"
    write_io_file "$io_template_file"


}

######################
# GLOBAL CONNECTS
######################
# MANU: GET all layers that we are going to use for the power grid
set vlayers [get_db [get_db layers -if {.type == routing && .direction == vertical} ] .name]
set hlayers [get_db [get_db layers -if {.type == routing && .direction == horizontal} ] .name]

# Delete other previous routes (if any)
set pg_layers {  } 


if { [get_flow_config -q floorplan_spef power_grid layers vertical] ne "" } { 
    set vlayers [get_flow_config floorplan_spef power_grid layers vertical]

    for {set i 0} {$i < [ expr [llength $vlayers]/2]} {incr i} {
        lappend pg_layers [lindex $vlayers [expr 2*$i] ]
    }
} else {
    set pg_layers [list {*}$vlayers]
}
if { [get_flow_config -q floorplan_spef power_grid layers horizontal] ne "" } { 
    set hlayers [get_flow_config floorplan_spef power_grid layers horizontal]
    
    for {set i 0} {$i < [ expr [llength $hlayers]/2]} {incr i} {
        lappend pg_layers [lindex $hlayers [expr 2*$i] ]
    }
} else {
    set pg_layers [list {*}$pg_layers {*}$hlayers]
}

set all_pg_nets [list {*}[get_flow_config init_power_nets] {*}[get_flow_config init_ground_nets]]
select_routes -wires_only 0 -type special -nets $all_pg_nets -layer $pg_layers -shapes {stripe followpin}
delete_routes -selected -type special -net $all_pg_nets -layer $pg_layers -shapes {stripe followpin}

# The first step of power planning is to declare global connections: this consists in declaring the pins 
# that connect to power and ground nets. The power and ground nets are VDD and VSS in this example.
# The below commands will instruct the tool to connect all the pins named VSS to the ground net named VSS, 
# all the pins named VDD to connect to the power net VDD, and all the tielow/high to respectively connect to VSS/VDD
foreach pgnet [get_flow_config init_power_nets] {
    puts "\033\[1;33m\[INFO\] - \033\[1;32mConnecting global net \033\[1;31m$pgnet\033\[0m"
    connect_global_net $pgnet -type pg_pin -pin_base_name $pgnet -inst_base_name *
    #connect_global_net $pgnet -type tie_hi -inst_base_name * -hinst {}
}
foreach pgnet [get_flow_config init_ground_nets] {
    puts "\033\[1;33m\[INFO\] - \033\[1;32mConnecting global net \033\[1;31m$pgnet\033\[0m"
    connect_global_net $pgnet -type pg_pin -pin_base_name $pgnet -inst_base_name *
    #connect_global_net $pgnet -type tie_lo -inst_base_name * -hinst {}
}

# Connect tie-low and tie-high
connect_global_net VDD -type tie_hi -inst_base_name * -hinst {}
connect_global_net VSS -type tie_lo -inst_base_name * -hinst {}

set pgnets [get_flow_config user_global_nets]
foreach item [dict keys $pgnets] {
    set value [dict get $pgnets $item]
    puts "\033\[1;33m\[INFO\] - \033\[1;32mConnecting global net \033\[1;31m$value ($item)\033\[0m"
    connect_global_net $value -pin_base_name $item -type pg_pin -inst_base_name * -hinst {}
}



#########################3
# add well taps only for hvt
if { "hvt" in [get_flow_config vths] } {
    add_well_taps -cell [get_flow_config well_tap_cell] \
        -cell_interval [get_flow_config welltap_interval] \
        -prefix "WELLTAP" \
        -checker_board
}



############################################
# POWER GRID 
###########################################

####################################################################
# Follow pins for VDD/VSS
####################################################################
set_db route_special_via_connect_to_shape { noshape }
route_special -connect {core_pin} \
    -layer_change_range { M1(1) M1(1) } \
    -block_pin_target {nearest_target} \
    -pad_pin_port_connect {all_port one_geom} \
    -pad_pin_target {nearest_target} \
    -core_pin_target {first_after_row_end} \
    -floating_stripe_target {block_ring pad_ring ring stripe ring_pin block_pin followpin} \
    -allow_jogging 0 \
    -crossover_via_layer_range { M1(1) M1(1) } \
    -nets { VDD VSS } \
    -allow_layer_change 0 \
    -block_pin use_lef \
    -target_via_layer_range { M1(1) M1(1) } 


# ADD STRIPES MANUALLY

set stripe_width 1.8
set stripe_separation $stripe_width
set set_to_set_distance [expr 2*$stripe_width + 2*$stripe_separation]


# Vertical stripes on M4 vias down to M1
set_db add_stripes_ignore_block_check false ; 
set_db add_stripes_break_at none ; 
set_db add_stripes_route_over_rows_only false ; 
set_db add_stripes_rows_without_stripes_only false ; 
set_db add_stripes_extend_to_closest_target none ; 
set_db add_stripes_stop_at_last_wire_for_area false ; 
set_db add_stripes_partial_set_through_domain false ; 
set_db add_stripes_ignore_non_default_domains false ; 
set_db add_stripes_trim_antenna_back_to_shape none ; 
set_db add_stripes_spacing_type edge_to_edge ; 
set_db add_stripes_spacing_from_block 0 ; 
set_db add_stripes_stripe_min_length stripe_width ; 
set_db add_stripes_stacked_via_top_layer M4 ; 
set_db add_stripes_stacked_via_bottom_layer M1 ; 
set_db add_stripes_via_using_exact_crossover_size false ; 
set_db add_stripes_split_vias false ; 
set_db add_stripes_orthogonal_only true ; 
set_db add_stripes_allow_jog { padcore_ring  block_ring } ; 
set_db add_stripes_skip_via_on_pin {  standardcell } ; 
set_db add_stripes_skip_via_on_wire_shape {  noshape   }
add_stripes -nets {VDD VSS} \
    -layer M4 -direction vertical \
    -width $stripe_width -spacing $stripe_separation \
    -set_to_set_distance $set_to_set_distance \
    -start_from left -start 2 \
    -switch_layer_over_obs false \
    -max_same_layer_jog_length 2 \
    -pad_core_ring_top_layer_limit AP \
    -pad_core_ring_bottom_layer_limit M1 \
    -block_ring_top_layer_limit AP \
    -block_ring_bottom_layer_limit M1 \
    -use_wire_group 0 \
    -snap_wire_center_to_grid none

# Horizontal stripes on M5 vias down to M4
set_db add_stripes_stacked_via_top_layer M5 ; 
set_db add_stripes_stacked_via_bottom_layer M4 ; 
add_stripes -nets {VDD VSS} \
    -layer M5 -direction horizontal \
    -width $stripe_width -spacing $stripe_separation \
    -set_to_set_distance $set_to_set_distance \
    -start_from left -start 2 \
    -switch_layer_over_obs false \
    -max_same_layer_jog_length 2 \
    -pad_core_ring_top_layer_limit AP \
    -pad_core_ring_bottom_layer_limit M1 \
    -block_ring_top_layer_limit AP \
    -block_ring_bottom_layer_limit M1 \
    -use_wire_group 0 \
    -snap_wire_center_to_grid none

# Vertical stripes on M6 vias down to M5
set stripe_width [expr 2*$stripe_width]
set stripe_separation $stripe_width
set set_to_set_distance [expr 2*$stripe_width + 2*$stripe_separation]
set_db add_stripes_stacked_via_top_layer M6 ; 
set_db add_stripes_stacked_via_bottom_layer M5 ; 
add_stripes -nets {VDD VSS} \
    -layer M6 -direction vertical \
    -width $stripe_width -spacing $stripe_separation \
    -set_to_set_distance $set_to_set_distance \
    -start_from left -start 2 \
    -switch_layer_over_obs false \
    -max_same_layer_jog_length 2 \
    -pad_core_ring_top_layer_limit AP \
    -pad_core_ring_bottom_layer_limit M1 \
    -block_ring_top_layer_limit AP \
    -block_ring_bottom_layer_limit M1 \
    -use_wire_group 0 \
    -snap_wire_center_to_grid none

# Horizontal stripes on M7 wias down to M6
set_db add_stripes_stacked_via_top_layer M7 ; 
set_db add_stripes_stacked_via_bottom_layer M6 ; 
add_stripes -nets {VDD VSS} \
    -layer M7 -direction horizontal \
    -width $stripe_width -spacing $stripe_separation \
    -set_to_set_distance $set_to_set_distance \
    -start_from left -start 2 \
    -switch_layer_over_obs false \
    -max_same_layer_jog_length 2 \
    -pad_core_ring_top_layer_limit AP \
    -pad_core_ring_bottom_layer_limit M1 \
    -block_ring_top_layer_limit AP \
    -block_ring_bottom_layer_limit M1 \
    -use_wire_group 0 \
    -snap_wire_center_to_grid none


# Vertical stripes on M8 vias down to M7
set stripe_width [expr 2*$stripe_width]
set stripe_separation $stripe_width
set set_to_set_distance [expr 2*$stripe_width + 2*$stripe_separation]
set_db add_stripes_stacked_via_top_layer M8 ; 
set_db add_stripes_stacked_via_bottom_layer M7 ; 
add_stripes -nets {VDD VSS} \
    -layer M8 -direction vertical \
    -width $stripe_width -spacing $stripe_separation \
    -set_to_set_distance $set_to_set_distance \
    -start_from left -start 2 \
    -switch_layer_over_obs false \
    -max_same_layer_jog_length 2 \
    -pad_core_ring_top_layer_limit AP \
    -pad_core_ring_bottom_layer_limit M1 \
    -block_ring_top_layer_limit AP \
    -block_ring_bottom_layer_limit M1 \
    -use_wire_group 0 \
    -snap_wire_center_to_grid none

# Horizontal stripes on M9 wias down to M8
set_db add_stripes_stacked_via_top_layer M9 ; 
set_db add_stripes_stacked_via_bottom_layer M8 ; 
add_stripes -nets {VDD VSS} \
    -layer M9 -direction horizontal \
    -width $stripe_width -spacing $stripe_separation \
    -set_to_set_distance $set_to_set_distance \
    -start_from left -start 2 \
    -switch_layer_over_obs false \
    -max_same_layer_jog_length 2 \
    -pad_core_ring_top_layer_limit AP \
    -pad_core_ring_bottom_layer_limit M1 \
    -block_ring_top_layer_limit AP \
    -block_ring_bottom_layer_limit M1 \
    -use_wire_group 0 \
    -snap_wire_center_to_grid none
    
# SAVE FLOORPLAN
set floorplan_file [string map {".latest" "" } [get_flow_config init_floorplan_file]]
set new_floorplan_file [lindex [next_file_version_number $floorplan_file] 1]
pinfo "Now saving floorplan to file [+ green]$new_floorplan_file[+ blue] and linking it to [+ red]$floorplan_file.latest[+]"
write_floorplan $new_floorplan_file
# Link to latest
ln -sf $new_floorplan_file $floorplan_file.latest
puts [sep]
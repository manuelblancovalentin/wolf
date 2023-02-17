set sdc_version 2.0

###############################################################################################
# Units setup
###############################################################################################
set_units -capacitance 1fF
set_units -time 1ps

# ###############################################################################################
# # Clock periods for each clock signal
# ###############################################################################################
# set external_clk_period 1000
# set clk_period 2000
# # FPGA CLOCK 100MHz
# set clk_in_period 10000

# ###############################################################################################
# # Setup some variables
# ###############################################################################################
# set pre_cts_clock_uncertainty 80
# set clk_jitter 20

# ###############################################################################################
# # Definition of dco pins
# ###############################################################################################
# set DCO_hinst [get_db hinsts -if {.base_name == *DCO_GF22* }]
# set dco_clk_pin [vfind . -hpin *mux_clk/Y]
# #set dco_clk_pin [vfind $DCO_hinst -hpin CLK]

# # [maico]: We don't need the clock_div anymore cause we are using the output of the mux (above)
# #set dco_div_pin [vfind $DCO_hinst -hpin CLK_DIV]
# #set dco_div_pin [vfind $DCO_hinst -hpin clk_div]

# ###############################################################################################
# # Definition of reset port
# ###############################################################################################
# set rst [get_ports reset]

# ###############################################################################################
# # Clock signals creation
# ###############################################################################################
# create_clock -period $clk_in_period -name CLK_IN [get_ports iolink_clk_in ]
# create_clock -period $clk_period -name CLK [get_pins $dco_clk_pin -hier]
# create_clock -period $external_clk_period -name EXT_CLK [get_ports ext_clk]

# # VCLK
# create_clock -period $clk_in_period -name VCLK
# set clk_ports [list ext_clk iolink_clk_in]

# # Generate CLK
# #create_generated_clock -source $dco_clk_pin -name CLK_GEN -divide_by 2 $dco_div_pin ; #dco dependent

# # Clock uncertainty
# set_clock_uncertainty -setup [expr $pre_cts_clock_uncertainty + $clk_jitter] [get_clocks CLK]
# set_clock_uncertainty -hold [expr $pre_cts_clock_uncertainty + $clk_jitter] [get_clocks CLK]
# set_clock_uncertainty -setup [expr $pre_cts_clock_uncertainty + $clk_jitter] [get_clocks CLK_IN]
# set_clock_uncertainty -hold [expr $pre_cts_clock_uncertainty + $clk_jitter] [get_clocks CLK_IN]
# set_clock_uncertainty -setup [expr $pre_cts_clock_uncertainty + $clk_jitter] [get_clocks EXT_CLK]
# set_clock_uncertainty -hold [expr $pre_cts_clock_uncertainty + $clk_jitter] [get_clocks EXT_CLK]
# set_clock_uncertainty -setup [expr $pre_cts_clock_uncertainty + $clk_jitter] [get_clocks VCLK]
# set_clock_uncertainty -hold [expr $pre_cts_clock_uncertainty + $clk_jitter] [get_clocks VCLK]

# set inputs  [remove_from_collection [all_inputs] \
#     [list $clk_ports $rst] ]
# set outputs [remove_from_collection [all_outputs] \
#     [list iolink_clk_out] ]

# ###############################################################################################
# # Set buffers and ios 
# ###############################################################################################
# set buffCell SC8T_BUFX2_CSC24L
# set buffCellIO SC8T_BUFX20_CSC24L
# set buffPin_in A
# set buffPin_out Z
# set buffIOPin_in A
# set buffIOPin_out Z

# set IOPADCell_IO_H IN22FDX_GPIO18_9M20S20PS_IO_H
# set IOPADCell_IO_V IN22FDX_GPIO18_9M20S20PS_IO_V
# set IOPADCell_H IN22FDX_GPIO18_9M20S20PS_I_H
# set IOPADCell_V IN22FDX_GPIO18_9M20S20PS_I_V
# set PADCell_out Y
# set PADCell_in PAD

# # IN22FDX_GPIO18_9M20S20PS_I_V PADS for: 
# # reset, ext_clk
# set I_V_inputs [get_ports reset ext_clk]

# # IN22FDX_GPIO18_9M20S20PS_I_H PADS for IN: 
# # iolink_clk_in, iolink_valid_in, iolink_credit_in
# set I_H_inputs [get_ports iolink_clk_in, iolink_valid_in, iolink_credit_in ]

# # IN22FDX_GPIO18_9M20S20PS_IO_V PADS for IN: 
# # inouts
# # iolink_data[0..7]
# set IO_V_inputs [get_ports iolink_data\[0\] iolink_data\[1\] iolink_data\[2\] iolink_data\[3\] iolink_data\[4\] iolink_data\[5\] iolink_data\[6\] iolink_data\[7\]]

# # IN22FDX_GPIO18_9M20S20PS_IO_H PADS for IN: 
# # outputs
# # iolink_clk_out, iolink_valid_out, iolink_credit_out
# # inouts
# # iolink_data[8..15], clk_div
# set IO_H_inputs [get_ports iolink_clk_out iolink_valid_out iolink_credit_out iolink_data\[8\] iolink_data\[9\] iolink_data\[10\] iolink_data\[11\] iolink_data\[12\] iolink_data\[13\] iolink_data\[14\] iolink_data\[15\]]

# # Values extracted from:
# set IO_H_max_input_rise_transition 90 
# set IO_H_max_input_fall_transition 120
# set IO_V_max_input_rise_transition 130
# set IO_V_max_input_fall_transition 170
# set I_H_max_input_rise_transition 70 
# set I_H_max_input_fall_transition 85
# set I_V_max_input_rise_transition 65
# set I_V_max_input_fall_transition 80

# set_driving_cell -lib_cell $IOPADCell_I_H \
#                  -pin $PADCell_out \
#                  -input_transition_rise $I_H_max_input_rise_transition \
#                  -input_transition_fall $I_H_max_input_fall_transition \
#                  $I_H_inputs
# set_driving_cell -lib_cell $IOPADCell_I_V \
#                  -pin $PADCell_out \
#                  -input_transition_rise $I_V_max_input_rise_transition \
#                  -input_transition_fall $I_V_max_input_fall_transition \
#                  $I_V_inputs
# set_driving_cell -lib_cell $IOPADCell_IO_H \
#                  -pin $PADCell_out \
#                  -input_transition_rise $IO_H_max_input_rise_transition \
#                  -input_transition_fall $IO_H_max_input_fall_transition \
#                  $IO_H_inputs
# set_driving_cell -lib_cell $IOPADCell_IO_V \
#                  -pin $PADCell_out \
#                  -input_transition_rise $IO_V_max_input_rise_transition \
#                  -input_transition_fall $IO_V_max_input_fall_transition \
#                  $IO_V_inputs


# # Set IO delay on core clock referenced to a pin
# set in_delay 70
# set out_delay 70

# set_input_delay 0.0 -clock VCLK $rst -add_delay

# set_input_delay $in_delay -max -clock VCLK $inputs -add_delay 
# set_output_delay $out_delay -max -clock VCLK [all_outputs] -add_delay

# #Hold now underconstrained on IOs, but these paths should be fixed in the SoC
# set_input_delay $in_delay -min -clock VCLK $inputs -add_delay
# set_output_delay  $out_delay -min -clock VCLK [all_outputs]  -add_delay

# set_load 1 [all_outputs]
# set_max_fanout 10 [all_inputs]

# set_max_transition 100
# set_max_transition 100 [get_clocks CLK] -clock_path
# set_max_transition 100 [get_clocks CLK_IN] -clock_path
# set_max_transition 100 [get_clocks EXT_CLK ] -clock_path

# set_false_path -from [get_clocks CLK]      -to [get_clocks CLK_IN]
# set_false_path -from [get_clocks CLK_IN]   -to [get_clocks CLK]

# set_false_path -from [get_clocks EXT_CLK] -to [get_clocks CLK_IN] 
# set_false_path -from [get_clocks CLK_IN ] -to [get_clocks EXT_CLK]

# # In theory we don't need the following constraints. 

# #set_false_path -from [get_clocks CLK]     -to [get_clocks VCLK]
# #set_false_path -from [get_clocks VCLK] -to [get_clocks CLK]

# #set_false_path -from [get_clocks EXT_CLK] -to [get_clocks VCLK ]
# #set_false_path -from [get_clocks VCLK] -to [get_clocks EXT_CLK ]



set sdc_version 2.0

###############################################################################################
# Units setup
###############################################################################################
set_units -capacitance 1fF
set_units -time 1ps

###############################################################################################
# Clock periods for each clock signal
###############################################################################################
# set clk_period_SPI 100000
# set clk_period_DAC  10000

###############################################################################################
# Setup some variables
###############################################################################################
# set pre_cts_clock_uncertainty_SPI 200
# set clk_jitter_SPI 50
# #set pre_cts_clock_uncertainty_DAC 20
# #[@csyal]: increase uncertainty
# set pre_cts_clock_uncertainty_DAC 100
# set clk_jitter_DAC 5


# ###############################################################################################
# # Definition of reset port
# ###############################################################################################
# set rst [get_ports nRST]

# ###############################################################################################
# # Clock signals creation
# ###############################################################################################
# create_clock -period $clk_period_SPI -name SPI_CLK [get_ports SPI_CLK]
# create_clock -period $clk_period_DAC -name DAC_CLK [get_ports DAC_CLK]

# #create_generated_clock -name TEST_CLK -source SPI_CLK -divide_by 1 case1_g70290__1705/Z
# # set delay_val_max 160
# # set delay_val_min 145
# # set_max_delay $delay_val_max -from TEST_CLK -to case1_channel_sram_gen\[*\].sram*/D*
# # set_min_delay $delay_val_min -from TEST_CLK -to case1_channel_sram_gen\[*\].sram*/D*


# set clk_ports [list SPI_CLK DAC_CLK ]


# # [@ffahim]: We are not supposed to be telling innovus SPI/DAC clocks are unrelated, cause they actually are related.
# # set_false_path -from [get_clocks SPI_CLK] -to [get_clocks DAC_CLK]
# # set_false_path -from [get_clocks DAC_CLK] -to [get_clocks SPI_CLK]


# # Clock uncertainty
# # set_clock_uncertainty -setup [expr $pre_cts_clock_uncertainty_SPI + $clk_jitter_SPI] [get_clocks SPI_CLK]
# # set_clock_uncertainty -hold [expr $pre_cts_clock_uncertainty_SPI + $clk_jitter_SPI] [get_clocks SPI_CLK]
# # set_clock_uncertainty -setup [expr $pre_cts_clock_uncertainty_DAC + $clk_jitter_DAC] [get_clocks DAC_CLK]
# # set_clock_uncertainty -hold [expr $pre_cts_clock_uncertainty_DAC + $clk_jitter_DAC] [get_clocks DAC_CLK]
# set_clock_uncertainty -setup 250.0 [get_clocks SPI_CLK]
# set_clock_uncertainty -hold 100.0 [get_clocks SPI_CLK]
# set_clock_uncertainty -setup 250.0 [get_clocks DAC_CLK]
# set_clock_uncertainty -hold 100.0 [get_clocks DAC_CLK]
# set inputs  [remove_from_collection [all_inputs] \
#     [list $clk_ports $rst] ]
# set outputs [all_outputs] 
    

# ###############################################################################################
# # Set buffers and ios 
# ###############################################################################################
# set buffCell SC8T_BUFX2_CSC24SL
# set buffCellIO SC8T_BUFX20_CSC24SL
# set buffPin_in A
# set buffPin_out Z
# set buffIOPin_in A
# set buffIOPin_out Z

# set_driving_cell -lib_cell $buffCell \
#                  -pin $buffPin_out \
#                  [get_ports $inputs]

# ## Set IO delay on core clock referenced to a pin
# set in_delay_SPI 5000
# set out_delay_SPI 5000
# set in_delay_DAC 500
# set out_delay_DAC 500

# set_input_delay 0.0 -clock SPI_CLK $rst 
# set_input_delay $in_delay_SPI -max -clock SPI_CLK $inputs  
# set_input_delay $in_delay_SPI -min -clock SPI_CLK $inputs 
# set_output_delay $out_delay_SPI -max -clock SPI_CLK $outputs 
# set_output_delay  $out_delay_SPI -min -clock SPI_CLK $outputs  

# set_input_delay 0.0 -clock DAC_CLK $rst 
# set_input_delay $in_delay_DAC -max -clock DAC_CLK $inputs  
# set_input_delay $in_delay_DAC -min -clock DAC_CLK $inputs 
# set_output_delay $out_delay_DAC -max -clock DAC_CLK $outputs 
# set_output_delay  $out_delay_DAC -min -clock DAC_CLK $outputs  


# set_load 3 [all_outputs]
# set_max_fanout 10 [all_inputs]

# set_input_transition 200 [all_inputs]

# # [@ffahim]: max_transition should not be more than 10% of the clock period
# set_max_transition 300
# set_max_transition 200 [get_clocks SPI_CLK] -clock_path
# set_max_transition 200 [get_clocks DAC_CLK] -clock_path


# # [@manuelbv]: Set IO buffers to don't touch 
# set_dont_touch udigIOBUFF*




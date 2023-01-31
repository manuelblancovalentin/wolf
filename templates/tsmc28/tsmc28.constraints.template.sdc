set sdc_version 2.0

###############################################################################################
# Units setup
###############################################################################################
set_units -capacitance 1fF
set_units -time 1ps

###############################################################################################
# Clock periods for each clock signal
#   configClk := 1 MHz
#   clk := 40 MHz
###############################################################################################
# set clocks { "clk" 25000 "configClk" 1000000 "scanClk" 1000000 "BXCLK" 25000 "BXCLK_ANA" 25000 }

# ###############################################################################################
# # Definition of reset port
# ###############################################################################################
# set rst [get_ports rst]


# ###############################################################################################
# # Clock signals creation
# ###############################################################################################
# # [@ffahim]: uncertainty 
# # 10% of clock period 
# # clk -> 1ns for 25ns clock 
# # configClk -> 1ns for 100kHz too 

# # jitter 
# # 100ps or 200ps for clk and configClk

# # [@csyal]: 1000ps for uncertainty, for 28nm, is too much. Change it to ~100ps including jitter. 
# set clk_uncertainty 80
# set clk_jitter 20
# set nclocks [expr [llength $clocks]/2]
# puts $nclocks
# set clk_names {}
# for {set iclk 0} { $iclk < $nclocks } { incr iclk } {
#     set clkName [lindex $clocks [expr 2*$iclk]]
#     set clkPeriod [lindex $clocks [expr 2*$iclk + 1]]

#     lappend $clk_names $clkName

#     ###############################################################################################
#     #   [@manuelbv]: Create clock
#     ###############################################################################################
#     pinfo "[+ blue]Creating clock [+ green]$clkName[+ blue] with period [+ green]$clkPeriod[+]"
#     create_clock -period $clkPeriod -name $clkName [get_ports $clkName]
    
#     ###############################################################################################
#     #   [@manuelbv]: jitter as 0.5% of period
#     #                uncertainty as 2% of period
#     # --
#     #   [@ffahim]:   uncertainty 2ns 
#     #                jitter 0.5ns
#     ###############################################################################################
#     if { $clk_uncertainty eq "" } { set pre_cts_clk_uncertainty [expr 2*$clkPeriod/1000] } else { set pre_cts_clk_uncertainty $clk_uncertainty }
#     if { $clk_jitter eq "" } { set pre_cts_clk_jitter [expr 5*$clkPeriod/10000] } else { set pre_cts_clk_jitter $clk_jitter }

#     # Setup uncertainty and jitter now 
#     pinfo "[+ blue]Setting up [+ green]$clkName[+ blue] uncertainty to [+ green]$pre_cts_clk_uncertainty[+ blue] and jitter to [+ green]$pre_cts_clk_jitter[+]"
#     set_clock_uncertainty -setup [expr $pre_cts_clk_uncertainty + $pre_cts_clk_jitter] [get_clocks $clkName]
#     set_clock_uncertainty -hold [expr $pre_cts_clk_uncertainty + $pre_cts_clk_jitter] [get_clocks $clkName]
# }

# ###############################################################################################
# # Set false paths
# ###############################################################################################
# foreach k $clk_names {
#     foreach kv $clk_names {
#         if { $kv ne $k } {
#             pinfo "[+ blue]Setting false path from [+ green]$k[+ blue] to [+ green]$kv[+]"
#             set_false_path -from [get_clocks $k] -to [get_clocks $kv]
#         }
#     }
# }

# ###############################################################################################
# # Set load (100 fF)
# #   [@ffahim]:   uncertainty 2ns 
# #                jitter 0.5ns
# ###############################################################################################
# pinfo "[+ blue]Setting load of [+ green]100 fF[+ blue] load to all output[+]"
# set_load 100 [all_outputs]

# ###############################################################################################
# # Get all inputs and outputs (removing clocks from there)
# ###############################################################################################
# set inputs  [remove_from_collection [all_inputs] [list {*}$clk_names $rst] ]
# set outputs [all_outputs] 

# ###############################################################################################
# # Set input/output delays
# #   [@ffahim]: input_delay 1ns ~ 2ns 
# #              output_delay input_delay 
# #   [@manuelbv]: 5% of clock
# ###############################################################################################
# #set in_delay 1250
# set in_delay 125
# set out_delay $in_delay
# for {set iclk 0} { $iclk < $nclocks } { incr iclk } {
#     set clkName [lindex $clocks [expr 2*$iclk]]
#     set clkPeriod [lindex $clocks [expr 2*$iclk + 1]]

#     # [@manuelbv]: input_delay from rst to clk is zero 
#     pinfo "[+ blue]Setting input_delay from clock [+ green]$clkName[+ blue] to [+ green]$rst[+ blue] signal to [+ red]0.0[+]"
#     set_input_delay 0.0 -clock $clkName $rst 

#     # Set input_delays for clock to all inputs 
#     if { $in_delay eq "" } { set in_delay_tmp [expr 5*$clkPeriod/100] } else { set in_delay_tmp $in_delay }
#     if { $out_delay eq "" } { set out_delay_tmp $in_delay_tmp } else { set out_delay_tmp $out_delay }

#     pinfo "[+ blue]Setting input/out delays from clock [+ green]$clkName[+ blue] to [+ green]all inputs[+ blue] to [+ red]$in_delay_tmp[+]"
#     set_input_delay     $in_delay_tmp   -max -clock $clkName $inputs  
#     set_input_delay     $in_delay_tmp   -min -clock $clkName $inputs 
#     set_output_delay    $out_delay_tmp  -max -clock $clkName $outputs 
#     set_output_delay    $out_delay_tmp  -min -clock $clkName $outputs  

# }


# ###############################################################################################
# # Set max_fanout (100 fF)
# #   [@ffahim]:   fanout <= 50  
# ###############################################################################################
# pinfo "[+ blue]Setting max fanout of [+ green]50[+ blue] to all inputs[+]"
# set_max_fanout 50 [all_inputs]



# ###############################################################################################
# # Set input transition 
# #   [@ffahim]: max_transition should not be more than 10% of the clock period
# #              max_transition 300ps ~ 500ps 
# #              transition -> 10% clk_period  (~1ns)
# #              ( if it buffers too much drop it to ~100ps or something)
# ###############################################################################################
# # [@ffahim]: max transition and input transition -> 500ps 

# pinfo "[+ blue]Setting max transition of [+ green]300[+]"
# set_max_transition 500
# pinfo "[+ blue]Setting input transition of [+ green]200 [+ blue] for all inputs[+]"
# set_input_transition 500 [all_inputs]

# set max_clk_transition 500
# for {set iclk 0} { $iclk < $nclocks } { incr iclk } {
#     set clkName [lindex $clocks [expr 2*$iclk]]
#     set clkPeriod [lindex $clocks [expr 2*$iclk + 1]]

#     if { $max_clk_transition eq "" } { set max_trans_tmp [expr 10*$clkPeriod/100] } else { set max_trans_tmp $max_clk_transition }
#     pinfo "[+ blue]Setting max transition for clock [+ green]$clkName[+ blue] to [+ green]$max_trans_tmp[+]"
#     set_max_transition $max_trans_tmp [get_clocks $clkName] -clock_path

# }


# # [@manuelbv]: Set IO buffers to don't touch 
# #set_dont_touch udigIOBUFF*
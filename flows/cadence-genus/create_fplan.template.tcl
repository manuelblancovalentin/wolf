# create_fplan.template.tcl - generic baseline floorplan for WOLF's bundled
# Cadence Genus/Innovus flow.
#
# This is a STARTING POINT, not a finished floorplan: die/core sizing, PG
# net bring-up, and the M1 rail + stripe stack below are generic enough to
# work for any design (parameterized by the knobs section), but real macro/
# tile placement and pin assignment are inherently design-specific -- see
# section 2 below, left as an explicit fill-in point.
#
# Use it by copying this file into your own project
# (inputs/scripts/<design>/create_fplan.tcl, see `wolf env auto-setup`),
# editing the knobs and section 2 for your design, then wiring it in:
#   inject.create_fplan.pre: [<your copy>]
# in this design's own setup.<design_name>.yaml
# (<project.root>/inputs/env/<design_name>/). Safe to re-source while
# iterating: step 0 removes whatever a previous run of this script left
# behind first.
#
# Adapted from a real pad-less TSMC65 floorplan (ESP_ASIC_TOP, 8-metal
# stack) -- die/core sizing, PG net creation, and the M1-rail-plus-stripe
# power grid are unchanged from that design's own script; design-specific
# tile regions and per-tile pin ownership were stripped out into the
# fill-in section below.

# ---- knobs -------------------------------------------------------------------------------------
set UTILIZATION     0.60  ;# target core utilization
set ASPECT          1.0   ;# core height / width
set MARGIN          30.0  ;# um between core and die edge
set PG_NETS         {VDD VSS}
# PG stripe layer stack: {layer direction width_um bottom_via_layer mult} per row. mult controls
# stripe sparsity (set-to-set distance = 4 * width * mult; mult 1 ~= 50% of the layer's tracks on
# VDD+VSS, mult 4 ~= 12.5%). Edit this list to match your own metal stack -- the one below is a
# generic 4-stripe-layer example, not tied to any particular process.
set PG_STRIPE_STACK {
    {M4 vertical   1.8 M1 4}
    {M5 horizontal 1.8 M4 4}
    {M6 vertical   3.6 M5 2}
    {M7 horizontal 3.6 M6 2}
}
set ::PG_NETS $PG_NETS    ;# visible inside procs even when this file is sourced from a proc

# ---- messages ------------------------------------------------------------------------------------
# WOLF's presentation.tcl provides wolf_step/wolf_info/wolf_error/wolf_file but no warning proc;
# fp_warn is defined here in the same style. Stand-ins keep this script usable outside the flow too.
if {[llength [info commands wolf_info]] == 0} {
    namespace eval ansicolor {
        variable codes [dict create bold 1 red 31 green 32 yellow 33 blue 34 purple 35 cyan 36 white 37]
        proc + {args} {
            variable codes
            if {[llength $args] == 0} { return "\033\[0m" }
            set out ""
            foreach name $args { append out "\033\[[dict get $codes $name]m" }
            return $out
        }
    }
    proc wolf_sep {} { return "[ansicolor::+ blue][string repeat - 100][ansicolor::+]" }
    proc wolf_step {args} {
        puts [wolf_sep]
        foreach line $args { puts "[ansicolor::+ bold blue]| $line[ansicolor::+]" }
        puts [wolf_sep]
    }
    proc wolf_info {text}  { puts "[ansicolor::+ bold yellow]\[INFO\][ansicolor::+] [ansicolor::+ blue]$text[ansicolor::+]" }
    proc wolf_error {text} { puts "[ansicolor::+ bold red]\[ERROR\][ansicolor::+] [ansicolor::+ blue]$text[ansicolor::+]" }
    proc wolf_file {path}  { puts "[ansicolor::+ bold cyan]\[FILE\][ansicolor::+] [ansicolor::+ cyan]$path[ansicolor::+]" }
}
proc fp_info {msg} { wolf_info "create_fplan: $msg" }
proc fp_warn {msg} {
    puts "[ansicolor::+ bold purple]\[WARN\][ansicolor::+] [ansicolor::+ blue]create_fplan: $msg[ansicolor::+]"
}
proc fp_err {msg} { wolf_error "create_fplan: $msg" }

set ::fp_nfail 0
proc fp_try {label body} {
    if {[catch {uplevel 1 $body} err]} {
        incr ::fp_nfail
        fp_err "FAILED $label: $err"
    } else {
        fp_info "ok $label"
    }
}

wolf_step "create_fplan: baseline floorplan" "script: [info script]"

# ---- 0. clean up whatever a previous run of this script left behind ------------------------------
fp_info "cleaning previous floorplan and PG routes (if any)"
foreach step {
    {set_io_flow_flag 0}
    {delete_all_floorplan_objs}
    {delete_io_fillers}
    {set_io_flow_flag 0}
} {
    if {[catch {eval $step} err]} { fp_warn "cleanup '$step': $err" }
}
if {[catch {
    set_partition_pin_status -pins [get_db ports .name] -status unplaced -quiet
} err]} { fp_warn "cleanup unplace pins: $err" }
if {[catch {
    select_routes -wires_only 0 -type special -nets $PG_NETS -shapes {stripe followpin}
    delete_routes -selected -type special -net $PG_NETS -shapes {stripe followpin}
} err]} { fp_warn "cleanup PG routes (none to delete on a first run): $err" }

# ---- 1. die and core -----------------------------------------------------------------------------
set site "core"
if {[lsearch -exact [get_db sites .name] $site] < 0} {
    fp_warn "site 'core' not found; sites are [get_db sites .name] -- edit the knob"
}
fp_try "create_floorplan ($UTILIZATION util, aspect $ASPECT)" {
    create_floorplan -site $site -core_density_size $ASPECT $UTILIZATION $MARGIN $MARGIN $MARGIN $MARGIN
}
set die_bbox [lindex [get_db designs .bbox] 0]
set die_w    [expr {[lindex $die_bbox 2] - [lindex $die_bbox 0]}]
set die_h    [expr {[lindex $die_bbox 3] - [lindex $die_bbox 1]}]
fp_info [format "die %.0f x %.0f um" $die_w $die_h]

# ---- 2. YOUR DESIGN GOES HERE ---------------------------------------------------------------------
# Everything above is generic; everything below this point is design-specific and left for you to
# fill in. A real example (ESP_ASIC_TOP) did, roughly, in this order:
#   a. Divide the core bbox into regions, one per top-level hierarchy/tile, sized from each one's
#      synthesized cell area (reports/area.<stage>.rpt) -- keeps the regions proportionate without
#      hardcoding absolute coordinates.
#   b. Soft placement guides, not hard regions, when there are no hard macros to place:
#        create_group -name fp_<name> -type guide -rects [list {x0 y0 x1 y1}]
#        update_group -name fp_<name> -add -objs [get_db hinsts <hierarchy glob>]
#   c. Pins, grouped by which region/hierarchy owns them (from the synthesized netlist's own port
#      names or hierarchy, not guessed), spread evenly over each owning edge with edit_pin -- see
#      ESP_ASIC_TOP's own create_fplan.tcl (inputs/scripts/<design>/) for a complete worked example,
#      including handling both small (<=3 pins, spacing-based) and large (range-based) groups.
#   d. Hard macros, if any, placed explicitly (create_inst/place_inst or floorplan regions) --
#      skipped entirely in the example above since that design has none.
#
# fp_try is available here the same way it's used above/below:
#   fp_try "my step" { <your real Innovus commands> }

# ---- 3. global power connections ------------------------------------------------------------------
# A Genus-handoff design commonly has no VDD/VSS nets yet (init_power_nets/init_ground_nets are
# never set by write_design's own init script), so connect_global_net/route_special/add_stripes all
# fail with "net does not exist" until the nets exist. Create them as physical power/ground nets when
# missing -- see "WOLF generic power/ground net names" in docs/CADENCE_GENUS.md for an alternative
# that sets this up once, before init_design, instead of per-floorplan-script.
fp_try "create PG nets $PG_NETS" {
    foreach {net kind} [list [lindex $PG_NETS 0] -power [lindex $PG_NETS 1] -ground] {
        if {[llength [get_db nets $net]] == 0} {
            create_net -name $net -physical $kind
        }
    }
}
foreach net $PG_NETS {
    if {[llength [get_db nets $net]] == 0} {
        incr ::fp_nfail
        fp_err "PG net $net still does not exist -- global connects, followpins and stripes below will fail"
    }
}
fp_try "connect_global_net" {
    connect_global_net VDD -type pg_pin -pin_base_name VDD -inst_base_name *
    connect_global_net VSS -type pg_pin -pin_base_name VSS -inst_base_name *
    connect_global_net VDD -type tie_hi -inst_base_name * -hinst {}
    connect_global_net VSS -type tie_lo -inst_base_name * -hinst {}
}

# ---- 4. power grid ---------------------------------------------------------------------------------
# Standard-cell rails (M1), then the stripe stack from the PG_STRIPE_STACK knob above.
fp_try "followpins on M1" {
    set_db route_special_via_connect_to_shape { noshape }
    route_special -connect {core_pin} -nets $PG_NETS \
        -layer_change_range { M1(1) M1(1) } -crossover_via_layer_range { M1(1) M1(1) } \
        -target_via_layer_range { M1(1) M1(1) } -allow_layer_change 0 -allow_jogging 0 \
        -core_pin_target first_after_row_end -block_pin use_lef
}
proc fp_stripes {layer dir width bottom mult} {
    set_db add_stripes_stacked_via_top_layer    $layer
    set_db add_stripes_stacked_via_bottom_layer $bottom
    set_db add_stripes_orthogonal_only true
    add_stripes -nets $::PG_NETS -layer $layer -direction $dir \
        -width $width -spacing $width -set_to_set_distance [expr {4 * $width * $mult}] \
        -start_from left -start 2 -switch_layer_over_obs false -max_same_layer_jog_length 2 \
        -use_wire_group 0 -snap_wire_center_to_grid none
}
foreach row $PG_STRIPE_STACK {
    lassign $row layer dir width bottom mult
    fp_try [format "stripes %s (%s, %.1f um wide, mult %s)" $layer $dir $width $mult] {
        fp_stripes $layer $dir $width $bottom $mult
    }
}

# Innovus prints **ERROR lines instead of throwing for some failures, so fp_try above can say "ok"
# even when add_stripes/route_special did nothing. Count what actually landed on the PG nets.
foreach net $PG_NETS {
    set nw 0
    catch {set nw [llength [get_db [get_db nets $net] .special_wires]]}
    if {$nw == 0} {
        incr ::fp_nfail
        fp_err "no special wires on net $net after followpins + stripes"
    } else {
        fp_info "net $net: $nw special wires (followpins + stripes)"
    }
}

# ---- 5. save -----------------------------------------------------------------------------------
# inputs/floorplans/<design>/ -- the directory `wolf env auto-setup` already scaffolds, resolved
# relative to this script's own location ([info script]) rather than hardcoded, so the same script
# works no matter where the project checks it out.
set fp_design [get_flow_config design_name -quiet]
if {$fp_design eq ""} { set fp_design "design" }
set fp_dir [file normalize [file join [file dirname [info script]] .. .. floorplans $fp_design]]
file mkdir $fp_dir
fp_try "write_floorplan $fp_dir" {
    write_floorplan [file join $fp_dir $fp_design.fp]
    write_io_file   [file join $fp_dir $fp_design.io]
}
foreach suffix {fp io} {
    set f [file join $fp_dir $fp_design.$suffix]
    if {[file exists $f]} { wolf_file $f }
}
fp_info "next: after place_opt_design, 'assign_io_pins' can re-assign pins to where the placed logic ended up (pins placed here are a seed only)."
if {$::fp_nfail == 0} {
    fp_info "done, all steps ok"
} else {
    fp_err "done with $::fp_nfail failed step(s) -- scroll up to the FAILED lines and fix those knobs/options"
}
puts [wolf_sep]

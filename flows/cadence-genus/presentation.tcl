# WOLF's default Cadence Genus flow -- step presentation helpers.
#
# This file is a real, editable part of the flow, not generated output.
# `wolf flow init --from flows/cadence-genus --to <your-copy>` clones this
# directory so a project can fork and edit it freely; WOLF only ever writes
# a small per-run configuration file (flow-config.tcl) alongside it.

proc wolf_sep {} {
    return "\033\[34m[string repeat - 100]\033\[0m"
}

proc wolf_step {title} {
    puts [wolf_sep]
    puts "\033\[1;34m| $title\033\[0m"
    puts [wolf_sep]
}

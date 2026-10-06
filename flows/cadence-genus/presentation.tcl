# WOLF's default Cadence Genus flow -- presentation and injection helpers.
#
# This file is a real, editable part of the flow, not generated output.
# `wolf flow init --from flows/cadence-genus --to <your-copy>` clones this
# directory so a project can fork and edit it freely; WOLF only ever writes
# a small per-run configuration file (flow-config.tcl) alongside it.

namespace eval ansicolor {
    variable codes [dict create \
        bold 1 red 31 green 32 yellow 33 blue 34 purple 35 cyan 36 white 37]

    # `+` with no arguments resets; with names, concatenates their codes.
    proc + {args} {
        variable codes
        if {[llength $args] == 0} {
            return "\033\[0m"
        }
        set out ""
        foreach name $args {
            append out "\033\[[dict get $codes $name]m"
        }
        return $out
    }
}

proc wolf_sep {} {
    return "[ansicolor::+ blue][string repeat - 100][ansicolor::+]"
}

# One or more banner lines between separators -- a step's name, and
# (when given) which file/step it comes from, so a long log stays
# readable about which stage and which real Tcl is currently running.
proc wolf_step {args} {
    puts [wolf_sep]
    foreach line $args {
        puts "[ansicolor::+ bold blue]| $line[ansicolor::+]"
    }
    puts [wolf_sep]
}

proc wolf_info {text} {
    puts "[ansicolor::+ bold yellow]\[INFO\][ansicolor::+] [ansicolor::+ blue]$text[ansicolor::+]"
}

proc wolf_error {text} {
    puts "[ansicolor::+ bold red]\[ERROR\][ansicolor::+] [ansicolor::+ blue]$text[ansicolor::+]"
}

# Announces a file a step just wrote (a report, a netlist, a handoff
# bundle) in its own color -- distinct from wolf_step's blue banners and
# wolf_info's yellow tag -- so a scrollback full of otherwise-monochrome
# Genus/Innovus output has an unmistakable marker for "here's something
# that landed on disk". Call this right after the write, with the exact
# path written.
proc wolf_file {path} {
    puts "[ansicolor::+ bold cyan]\[FILE\][ansicolor::+] [ansicolor::+ cyan]$path[ansicolor::+]"
}

# Each entry is either a file path (sourced) or inline Tcl (evaluated at
# the global scope). An inline snippet's error is reported but does not
# abort the step -- a bad one-off injection shouldn't take down a whole
# run; a bad *file* is not caught, since that's much more likely to be a
# real authoring mistake worth stopping on.
proc wolf_inject {snippets} {
    foreach snippet $snippets {
        if {$snippet eq ""} {
            continue
        }
        if {[file exists $snippet]} {
            wolf_step "Injecting $snippet"
            source $snippet
        } else {
            wolf_step "Injecting inline Tcl"
            if {[catch {uplevel #0 $snippet} message]} {
                wolf_error "injected Tcl failed: $message"
            }
        }
        puts [wolf_sep]
    }
}

# Reads backend.cadence-flowtool.inject.<step>.<pre|post>, generated into
# flow-config.tcl as `set wolf_inject(<step>,<pre|post>) {...}` entries --
# only for steps that actually have something configured, so this is a
# no-op everywhere else.
proc wolf_inject_for_step {step phase} {
    global wolf_inject
    if {[info exists wolf_inject($step,$phase)]} {
        wolf_inject $wolf_inject($step,$phase)
    }
}

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

# WOLF's own live per-step status record -- confirmed real, hit on an
# actual run, that Flowtool's own flow.status/flow.metrics are NOT
# promptly updated per step when a step runs as part of a manually-typed
# `run_flow` at an interactive Genus/Innovus prompt (Flowtool's own
# writes there are tied to its driver loop regaining control between
# steps, not to each step itself, so `wolf status --watch`'s live view
# goes stale for exactly as long as a `run_flow` call is in flight).
# wolf.step-status is instead written directly by each real
# create_flow_step's own wrapped body as it executes (see
# create_flow_step's own redefinition below), so it stays accurate
# regardless of how control reaches a step.
#
# wolf_run_directory is set by flow-config.tcl (flow.template.yaml's
# last user_flow_steps entry); a step that somehow runs before that --
# shouldn't happen in the bundled flow -- degrades to writing nothing
# rather than guessing a path. A write failure for any other reason
# (disk full, permissions, ...) is reported but never allowed to break
# the real flow -- this is bookkeeping, not synthesis.
proc wolf_write_step_status {step_name status} {
    global wolf_run_directory
    if {![info exists wolf_run_directory] || $wolf_run_directory eq ""} {
        return
    }
    if {[catch {
        set handle [open [file join $wolf_run_directory wolf.step-status] a]
        puts $handle "$step_name|$status|[clock seconds]"
        close $handle
    } message]} {
        wolf_error "wolf_write_step_status failed (ignored): $message"
    }
}

# Wraps Flowtool's own native create_flow_step so every real step --
# without editing any of their own bodies -- also calls
# wolf_write_step_status as it starts, succeeds, or fails. Every other
# argument is passed through to the native command completely
# unchanged, in its original position -- confirmed real that the body
# is NOT always the command's last argument: several real steps (e.g.
# synthesis.tcl's own elaborate) trail it with a bare -write_db flag
# after their own closing brace. The body is instead identified by its
# own structural property -- every real body in this flow is written
# as a multi-line {...} block, so it is always
# the one argument containing an embedded newline, where no flag name
# or flag value (-name/-owner/-categories/-write_db/...) ever is. A
# step whose body happens to contain no newline at all (not seen
# anywhere in the bundled flow today) falls back to treating the last
# argument as the body, same as this wrapper's first version.
#
# `catch` around the raw body text evaluates it in exactly the same
# scope it always ran in (catch, unlike apply/proc, introduces no new
# variable scope of its own), and a real failure is re-raised via
# `return -options` with the original error code/info intact, so
# Flowtool's own error handling and flow.status/flow.metrics
# bookkeeping see the exact same failure they always would have.
#
# Guarded so sourcing this file twice (a project forking the flow and
# re-including it) renames the native command only once.
if {[llength [info commands ::wolf_native_create_flow_step]] == 0} {
    rename ::create_flow_step ::wolf_native_create_flow_step

    proc create_flow_step {args} {
        set body_index -1
        for {set i 0} {$i < [llength $args]} {incr i} {
            if {[string first "\n" [lindex $args $i]] >= 0} {
                set body_index $i
                break
            }
        }
        if {$body_index < 0} {
            set body_index [expr {[llength $args] - 1}]
        }
        set body [lindex $args $body_index]
        set before [lrange $args 0 [expr {$body_index - 1}]]
        set after [lrange $args [expr {$body_index + 1}] end]
        set name ""
        foreach {flag value} $before {
            if {$flag eq "-name"} {
                set name $value
            }
        }
        if {$name eq ""} {
            # Can't attribute an event to an unnamed step -- fall back
            # to the native command untouched rather than guess.
            uplevel 1 [list ::wolf_native_create_flow_step {*}$args]
            return
        }
        set wrapped [format {
            wolf_write_step_status {%s} starting
            if {[catch {%s} wolf_step_error wolf_step_options]} {
                wolf_write_step_status {%s} failed
                return -options $wolf_step_options $wolf_step_error
            }
            wolf_write_step_status {%s} success
        } $name $body $name $name]
        uplevel 1 [list ::wolf_native_create_flow_step {*}$before $wrapped {*}$after]
    }
}

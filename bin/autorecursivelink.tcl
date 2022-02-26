#!/bin/tclsh

proc recursive_link {prev_dir out_dir tabs} {
    #puts "prev: $prev_dir"
    #puts "out:  $out_dir"
    # Make sure out_dir exists
    exec mkdir -p "$out_dir"
    # Find files in this dir
    set files [glob -directory $prev_dir -type f -nocomplain *]
    foreach f $files {
        set outfiletmp [string map [list $prev_dir $out_dir] $f]
        set origfilemsg [string map [list $prev_dir "\$root_dir"] $f]
        set outfilemsg [string map [list $out_dir "\$root_dir"] $outfiletmp]
        set msgout "$tabs\033\[31mLinking \033\[37m$origfilemsg\033\[31m -> \033\[1;34m$outfilemsg\033\[0m"
        puts "$msgout"
        exec ln -sf "$f" "$outfiletmp"
    }
    # Find children dirs in this dir
    set dirs [glob -directory $prev_dir -type d -nocomplain *]
    foreach dir $dirs {
        set outtmp [string map [list $prev_dir $out_dir] $dir]
        set outtmpmsg [string map [list $out_dir "\$out_dir"] $outtmp]
        set msgout "$tabs\033\[37mCreating dir \033\[1;32m$outtmpmsg\033\[0m"
        puts "$msgout"
        exec mkdir -p "$outtmp"
        recursive_link "$dir" "$outtmp" " $tabs"
    }


}

set root_dir [lindex $argv 0]
set out_dir [lindex $argv 1]

#mkdir -p "$outdir"
#puts "$root_dir"
recursive_link "$root_dir" "$out_dir" ""
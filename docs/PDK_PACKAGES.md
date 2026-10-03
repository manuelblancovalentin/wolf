# PDK registry manifests

A `pdk/<name>` registry manifest (`<registry>/pdk/<name>.yaml`) declares
one technology's real, on-disk library/physical/behavioral views by path
only -- never their content. WOLF never commits, copies, or reads these
files for anything but existence checks and checksums; a `local-path`
source (the common case on an institutional host) just points at a
directory that is already there.

`wolf pdk menu <name>` creates or edits one of these manifests
interactively -- see [Editing with `wolf pdk menu`](#editing-with-wolf-pdk-menu)
below. This document describes the shape it edits, for anyone reading or
hand-writing the yaml directly.

## Two ways to declare a technology's views

### Flat (one implicit corner)

```yaml
metadata:
  technology:
    name: asap7
    timing:
      corner: typical
      libraries:
        - lib/NLDM/asap7sc7p5t_AO_RVT_TT_nldm_211120.lib.gz
        - ...
    physical:
      technology_lefs: [lef/asap7_tech_1x_201209.lef]
      cell_lefs: [lef/asap7sc7p5t_28_R_1x_220121a.lef]
      rc: [setRC.tcl, rcx_patterns.rules]
      gds: [gds/asap7sc7p5t_28_R_220121a.gds]
    synthesis:
      dont_use: ["*_lvt"]
```

This is the whole shape most packages need: one library set, one set of
physical views. `timing.corners` (plural, see below) can replace
`timing.corner`/`timing.libraries` even in a flat package, to declare
several named MMMC corners without introducing tracks at all.

### Tracked (several track/vth combinations)

Real standard-cell libraries commonly vary by track height (9T/7T/12T) and
threshold voltage (lvt/rvt/hvt), each combination with its own corners,
LEF, GDS, Verilog/SPICE behavioral models, and QRC extraction captables.
Declare `tracks` instead of `timing`/`physical` (the two are mutually
exclusive -- a package is one shape or the other, not a mix):

```yaml
metadata:
  technology:
    name: tsmc65
    generic:
      tech_layermap: config/tsmc65.sorted.gds2map
      rc_corners:
        rc_25C: {temperature: 25, qrc_tech_file: qrc/rc_25C.captable}
    tracks:
      9T:
        vths:
          lvt:
            lef: [lef/9t_lvt.lef]
            gds: [gds/9t_lvt.gds]
            verilog_models: [verilog/9t_lvt.v]
            spice_models: [spice/9t_lvt.spi]
            qrc_techfiles: [qrc/9t_lvt.captable]
            timing:
              corners:
                typical: {libraries: [lib/9t_lvt_typical.lib]}
                worst_case:
                  libraries: [lib/9t_lvt_worst.lib]
                  qrc_tech_file: qrc/9t_lvt_worst.captable
                  format: ecsm
          rvt: {...}
      7T:
        vths:
          rvt: {...}
```

Every file-list field (`lef`, `gds`, `verilog_models`, `spice_models`,
`qrc_techfiles`, a corner's `libraries`) is a list, even when there's only
one entry -- almost everything in a real library tree can legitimately be
several files (a tech LEF plus a pad LEF plus a custom LEF, say). Only a
corner's own `qrc_tech_file` is a single path, since that's what
`create_rc_corner -qrc_tech_file` actually takes.

A corner's optional `format` (default `liberty`) records what kind of
library it actually is -- plain Liberty, ECSM, a variation/AOCV-SOCV
library, or whatever else shows up -- for whatever future consumer cares.
Genus/Innovus auto-detect Liberty-family content regardless, so this
isn't interpreted by WOLF today; it exists so the information isn't lost
at declaration time, the same declared-but-not-yet-consumed boundary as
`generic` below.

An environment picks which (track, vth) a run uses via `technology.track`/
`technology.vth` in its own `wolf.yaml`:

```yaml
technology:
  package: pdk/tsmc65
  track: 9T
  vth: lvt
```

Omit both when the package declares only one combination -- it's selected
automatically. Resolution always flattens the selected variant down into
the same shape a flat package produces (`timing_corners`, `technology_lefs`,
`gds_files`, ...), so nothing downstream (the Genus MMMC generation, say)
needs to know which shape a package was declared in.

### `generic`: whatever doesn't depend on track/vth

Some real fields genuinely don't vary by track or vth at all -- a GDS
layer map, RC extraction corners keyed by temperature. `technology.generic`
carries these through completely verbatim, with no schema WOLF validates
or interprets:

```yaml
generic:
  tech_layermap: config/tsmc65.sorted.gds2map
  rc_corners:
    rc_M40C: {temperature: -40, qrc_tech_file: qrc/rc_M40C.captable}
    rc_25C: {temperature: 25, qrc_tech_file: qrc/rc_25C.captable}
    rc_125C: {temperature: 125, qrc_tech_file: qrc/rc_125C.captable}
```

A resolved environment gets this back as `context.technology.generic`,
a plain dict, available to anything that knows what to do with it (nothing
does yet -- the same "declared, not yet consumed" boundary as
`backend.cadence-flowtool.inject`). Paths inside `generic` are not
resolved or existence-checked by WOLF; join them against
`context.technology.root` yourself if you add a consumer for one.

## Listing and inspecting

`wolf pdk list` lists every `pdk/*` manifest across all configured
registries, with its pinned revision, installation status, owning
registry, and a one-line summary (flat corner count, or track/vth combo
count). `wolf pdk info <name>` shows one package's source, revision,
license, and full track/vth/corner breakdown.

## Editing with `wolf pdk menu`

`wolf pdk menu <name>` opens the existing `pdk/<name>` manifest (wherever
it's registered), or offers to create it -- asking which configured local
registry to place it in if more than one is configured, then for the
package's local filesystem root.

The menu walks the same shape this document describes: Tracks → a
track's vths → a vth's corners and file-category lists (LEF, GDS, Verilog
models, SPICE models, QRC techfiles) → a corner's own libraries and
optional QRC tech file. `a` adds (browsing the filesystem for file
lists, typed text for names and cell-glob lists), `d` deletes the
highlighted entry, `enter` opens whatever is highlighted, `esc` finishes
a screen. `generic` is edited as raw YAML in `$EDITOR` rather than through
dedicated fields, deliberately -- see the section above.

Every file/directory picker remembers the last directory it was used in
for the rest of the session and starts there next time, rather than
restarting from the package root -- useful since a corner's libraries,
QRC file, and neighboring LEF/GDS usually live near each other on disk.

`q`/`escape` quits without saving; `s` saves in place without closing;
the Save button saves and closes.

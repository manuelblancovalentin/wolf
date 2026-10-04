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

GDS is listed here for completeness but is always flat, same as
verilog_models/spice_models -- see [Metal stack](#metal-stack-lefqrc_techfiles-per-named-stack)
below for why it doesn't share lef/qrc_techfiles' per-stack axis.

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
            default_metal_stack: 9lmT2
            lef:
              9lmT2: [lef/9t_lvt_9lmT2.lef]
              7lmT1: [lef/9t_lvt_7lmT1.lef]
            gds: [gds/9t_lvt.gds]
            qrc_techfiles:
              9lmT2: [qrc/9t_lvt_9lmT2.captable]
              7lmT1: [qrc/9t_lvt_7lmT1.captable]
            verilog_models: [verilog/9t_lvt.v]
            spice_models: [spice/9t_lvt.spi]
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

### Metal stack (`lef`/`qrc_techfiles` per named stack)

`lef`/`qrc_techfiles` are physically tied to a **metal stack** -- how
many routing layers the design commits to, plus a top-metal routing
option (e.g. TSMC's `9lmT2` = 9 metal layers, top-metal option "T2").
It's a real, independent design axis: the *same* track/vth cells can be
implemented against any of several stacks, and switching stacks (even
just to try two for the same design) should be as simple as changing one
field, not re-declaring the whole vth. A cell's own LEF (pin layers,
blockages) and its QRC extraction captable (BEOL parasitics) genuinely
depend on which stack you're routing against -- confirmed by diffing
real LEF files across stacks (different `PITCH`, different via rules).

`gds` is *not* stack-keyed, even though it may look like it should be by
analogy: a cell's own GDS geometry (its transistors, local interconnect,
pin shapes) lives on the lower metal layers shared by every stack
option, so the same GDS file serves every stack a track/vth is built
against. It's declared the same way as `verilog_models`/`spice_models`
-- always a flat list, never a per-stack mapping. (A package written
before this distinction existed, with `gds` as a `{stack: [...]}`
mapping, still resolves -- the selected `metal_stack`'s entry is used --
but `wolf pdk menu` flattens it to the new shape automatically the
moment you open that vth.)

Instead of a flat list, declare each of `lef`/`qrc_techfiles` as a
mapping of stack name to its file list (as in the example above). Both
that are present must declare the *same* set of stack names -- WOLF
rejects a vth where `lef` has `{9lmT2, 7lmT1}` but `qrc_techfiles` only
has `{9lmT2}`, rather than silently resolving an inconsistent pair. A
vth with only one stack can still use a flat list (no selection needed,
exactly like a single-corner technology).

An environment picks the stack via `technology.metal_stack`:

```yaml
technology:
  package: pdk/tsmc65
  track: 9T
  vth: lvt
  metal_stack: 7lmT1
```

Resolution order: explicit `technology.metal_stack` in the environment,
else the vth's own `default_metal_stack`, else auto-selected if only one
stack is declared, else a clear error listing what's available. Cloning
an environment and changing only `metal_stack` is meant to just work --
it's one field, resolved the same way `track`/`vth` already are.

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

### `setup_yaml_fragment`: this PDK's own Flowtool setup.yaml chunk

`technology.setup_yaml_fragment` points at one yaml file -- process/PDK-
specific flow knobs (max routing layers, dont-use cells, decap cells,
whatever your institution's real flow tunes per PDK), not committed
library content. It's concatenated onto the institution's own
`backend.cadence-flowtool.flowtool.setup_template` at run time (see
[CADENCE_GENUS.md](CADENCE_GENUS.md)'s `setup_template` section for the
exact mechanism and token set) -- a flat path field like any other,
available for both flat and tracked packages:

```yaml
technology:
  name: tsmc65
  setup_yaml_fragment: setup/tsmc65.setup.fragment.yaml
  tracks: {...}
```

Every track/vth/corner a tracked package declares is also injected into
that same rendered setup.yaml automatically, as `library_sets`,
`init_physical_files.lef_files`, and `std_cell_GDS_files` -- the exact
`get_flow_config`-indexed shape a real Flowtool-driven flow's own Tcl
expects. Nothing needs to be hand-maintained for that part; it comes
straight from the same track/vth/corner data `wolf pdk menu` already
edits.

## Listing and inspecting

`wolf pdk list` lists every `pdk/*` manifest across all configured
registries, with its pinned revision, installation status, owning
registry, and a one-line summary (flat corner count, or track/vth combo
count). `wolf pdk info <name>` shows one package's source, revision,
license, full track/vth/corner breakdown, and -- when present --
`author`/`creation-date`/`last-modified-date`.

For a tracked package, `wolf pdk info` also breaks each declared metal
stack down by where it's actually used -- every track/vth combo that
populates it, and which of lef/qrc_techfiles each one has files for
(`9lmT2: 9T/lvt (lef+qrc_techfiles), 7T/rvt (lef)`) -- the same "where
is this stack really used" view `wolf pdk menu`'s own clone flow needs
you to already have in your head, surfaced without opening the menu.

Those three are plain top-level yaml fields (siblings of `schema_version`/
`kind`/`name`), not under `metadata`, and `wolf pdk menu` stamps them
itself: `author` and `creation-date` are set once, the first time a new
package is saved (`author` from `$USER`), and `last-modified-date` is
updated on every save after that, new or existing. Hand-editing the yaml
works too -- `wolf pdk menu` never overwrites `author`/`creation-date`
if they're already set, only adds them when missing.

## Editing with `wolf pdk menu`

`wolf pdk menu <name>` opens the existing `pdk/<name>` manifest (wherever
it's registered), or offers to create it -- asking which configured local
registry to place it in if more than one is configured, then for the
package's local filesystem root.

Two ways to get to the same data:

**Tracks** → a track's vths → a vth's corners, metal stacks (LEF/QRC
techfiles together, one named stack at a time), and flat GDS/Verilog/
SPICE model lists → a corner's own libraries, format, and optional QRC
tech file. This is the structural view: pick track/vth first, then what to
declare for it.

**Front-End** / **Back-End** mirror the real library layout instead:
Front-End → Timing/Power → a delay-model format (ECSM/NLDM/CCS, or type
your own) lands you picking, creating, or deleting a track, then a vth,
then any of that vth's corners (a new one created from here is pre-set
to this format, but every existing corner shows regardless of its own
format -- this is the same corner list Tracks shows for that vth, not a
filtered view of it) -- the same corner editor Tracks would open, just
reached by "what kind of file is this" instead of "which track/vth
first". Front-End → Verilog, and Back-End → GDS / SPICE work the same
way -- pick/create/delete a track and vth, then edit that one flat file
list directly. Back-End → LEF / LEF → Techfiles add one more step: a
metal stack (LEF and QRC techfiles are stack-dependent; GDS isn't, so it
skips straight to the file list like Verilog/SPICE do). Nothing about
the underlying data differs between the two paths; pick whichever
matches how you're currently thinking about the library.

Every picker along either path shows the full path so far at the top
(`tsmc65 / Front-End / Timing-Power / ECSM / 9T / lvt`, say), and `esc`
always goes back exactly one of those levels -- to the vth picker from a
corner, to the track picker from a vth, to the format picker from a
track, and so on -- never straight back to the main menu partway through
a chain. Finishing with one item (saving a corner, picking a different
metal stack) lands you back on the picker for that same level rather
than kicking you out entirely, so adding several corners, vths, or
tracks in a row doesn't mean re-entering Front-End/Back-End each time.
`d` deletes the highlighted track, vth, corner, or metal stack in place,
without closing the picker -- the same way to remove a corner you no
longer want (a legacy name you've since renamed away from, say) as `d`
already works in the Tracks path's own corner/track/vth list editors.

### Cloning a track, vth, or metal stack

Once one is fully populated, `c` on the highlighted entry clones it to a
new name -- rewriting every path it carries with one or more regex
substitutions. The fast way to populate a second vth (`rvt` → `lvt`,
say), a second track, or a second metal stack once the first one's
corners, formats, and files are already right, rather than re-declaring
all of that by hand. This works from every place a track, vth, or metal
stack is picked, both paths: the Tracks path's own tracks/track/metal-
stacks screens, and the Front-End/Back-End track/vth/metal-stack pickers
(`_PickCreateDeleteScreen`) -- the same underlying `c` on whichever
screen you're on, regardless of which path got you there. Cloning a
metal stack always clones the whole stack (LEF + QRC techfiles
together), even if you reached it through Back-End → LEF specifically,
to stay consistent with what cloning the same stack from the Tracks
path's metal-stacks screen does. GDS isn't part of a metal stack (see
[Metal stack](#metal-stack-lefqrc_techfiles-per-named-stack) above), so
cloning a vth or track still carries its GDS list along -- there's just
no separate "clone the stack's GDS" step, since there's no per-stack GDS
to begin with.

You're asked for the new name, then land on a screen for building the
substitution list itself: `a` adds one (find regex, then replace) pair,
`enter` edits the highlighted pair, `d` deletes it, `esc` finishes with
however many pairs you've built. More than one pair is for a path that
needs more than one rewrite (the track token and the vth token both
changing, say) -- they apply in the order you added them, left to right.
A preview screen then shows every resulting path with a green OK or red
MISSING depending on whether it actually exists on disk, before
anything is written. `c` confirms -- paths that don't exist are
silently dropped (a corner with no file left for the clone is still
created, just empty, rather than written pointing at nothing); `esc` at
any point (no substitution pairs added, or cancelling the preview)
leaves the source completely untouched.

`a` adds (browsing the filesystem for file lists, typed text for names
and cell-glob lists), `d` deletes the highlighted entry, `enter` opens
whatever is highlighted, `esc` finishes a screen. `generic` is edited as
raw YAML in `$EDITOR` rather than through dedicated fields, deliberately
-- see the section above.

Every file/directory picker remembers the last directory it was used in
for the rest of the session and starts there next time, rather than
restarting from the package root -- useful since a corner's libraries and
its QRC file usually live near each other on disk. That starting point is
never a dead end, though: `u` climbs one directory level at a time, since
the QRC techfile just as often lives in a sibling directory as the
libraries picked moments earlier, not the same one.

The file browser also takes `r` to narrow the file names shown to those
matching a regex -- directories stay visible so you can keep navigating,
only files are filtered. Submit an empty pattern to clear it. Real
libraries routinely pack every track/vth/corner variant into one
directory (`tcbn65lpbc1d11d32_ecsm.lib`, `tcbn65lpwc1d08m40_ecsm.lib`,
...); this is for narrowing that down to the one you actually want --
`bc1d11` to find just the `bc` corner at that voltage, say -- instead of
scanning the whole directory by eye.

`q`/`escape` quits without saving; `s` saves in place without closing;
the Save button saves and closes.

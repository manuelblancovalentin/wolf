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
              9lmT2:
                rcbest: [qrc/9t_lvt_9lmT2_rcbest.captable]
                rcworst: [qrc/9t_lvt_9lmT2_rcworst.captable]
                typical: [qrc/9t_lvt_9lmT2_typical.captable]
              7lmT1:
                rcbest: [qrc/9t_lvt_7lmT1_rcbest.captable]
                rcworst: [qrc/9t_lvt_7lmT1_rcworst.captable]
                typical: [qrc/9t_lvt_7lmT1_typical.captable]
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

Every file-list field (`lef`, `gds`, `verilog_models`, `spice_models`, a
corner's `libraries`) is a list, even when there's only one entry --
almost everything in a real library tree can legitimately be several
files (a tech LEF plus a pad LEF plus a custom LEF, say). Only a corner's
own `qrc_tech_file` is a single path, since that's what `create_rc_corner
-qrc_tech_file` actually takes. `qrc_techfiles` nests one level deeper
than that -- see [RC extraction corners](#rc-extraction-corners-qrc_techfiles-per-named-corner)
below.

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
mapping of stack name to its file list (as in the example above). `lef`
and `qrc_techfiles` are allowed to declare different stack sets -- real
PDK data routinely does (a qrc captable existing for a stack that vth's
own `lef` doesn't declare yet, or at all, is a normal, valid state, not
an authoring mistake). Picking a stack that only one of the two fields
actually has just resolves that field and leaves the other empty, the
same tolerance the full-package catalog (`wolf pdk info`, the
`get_flow_config` export) already extends to a track/vth missing a file.
A vth with only one stack can still use a flat list (no selection needed,
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

`technology.process_node_nm` (optional, a positive integer) declares the
real process node size in nanometers for backends that need it (Cadence
Innovus's own `design_process_node` attribute defaults to 90 regardless
of the actual resolved PDK -- see `docs/CADENCE_GENUS.md`). Not derived
from the package name: not every PDK package names itself after its
node size the same way, so a project declares it explicitly rather than
WOLF guessing.

A corner's optional `format` (default `liberty`) records what kind of
library it actually is -- plain Liberty, ECSM, a variation/AOCV-SOCV
library, or whatever else shows up -- for whatever future consumer cares.
Genus/Innovus auto-detect Liberty-family content regardless, so this
isn't interpreted by WOLF today; it exists so the information isn't lost
at declaration time, the same declared-but-not-yet-consumed boundary as
`generic` below.

### RC extraction corners (`qrc_techfiles` per named corner)

Unlike `lef`, a stack's `qrc_techfiles` is not itself a flat file list --
it's a mapping of **RC extraction corner** name (e.g. `rcbest`, `rcworst`,
`typical`) to that corner's file list, one level deeper than `lef`:

```yaml
qrc_techfiles:
  9lmT2:
    rcbest: [qrc/9t_lvt_9lmT2_rcbest.captable]
    rcworst: [qrc/9t_lvt_9lmT2_rcworst.captable]
```

This is a real, independent axis from both the metal stack above and the
PVT timing corners declared under `timing.corners` -- a captable
characterizes *BEOL* (metal/via) process variation across a stack, not
*FEOL* transistor skew, confirmed by real captable filenames that encode
metal-layer count, top-metal option, and RC corner all at once (e.g.
`..._Vp9m+alrdl_top2_rcworst.captable`). An RC corner name has no fixed
relationship to a PVT corner name (`bc`/`lt`/`tc`/`wc`/...) -- pairing one
of each for a given analysis (fast silicon + best-case RC for hold, slow
silicon + worst-case RC for setup) is a signoff methodology decision, not
a PDK fact, so WOLF doesn't encode that pairing here.

A legacy flat `qrc_techfiles: {stack: [files]}` (no named RC corners,
predating this axis) still resolves -- every file in it is available, just
with no corner name attached -- and `wolf pdk menu` lets you add named RC
corners to it at any time without losing the existing files.

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

### Signoff: `opconds`, `delay_corners`, `analysis_views`

The real Cadence MMMC object chain is `library_set` (a timing corner's
own `.lib` files, already covered above) → `timing_condition` → one
`opcond` (optional) → `delay_corner` (one RC-extraction corner paired
with one timing condition) → `analysis_view` (one delay corner plus which
kind of analysis it drives, against a design's own constraint mode). Most
of that chain turns out to be a PDK fact, not a per-run one -- which PVT
corner pairs with which RC corner for signoff is fixed for a given
process, not something that changes design to design -- so it's declared
once here, at the top of `technology`, the same way `timing.corners` and
`qrc_techfiles`' rc-corner names already are:

```yaml
technology:
  opconds:
    typ_25c: {process: "1.0", voltage: "1.2", temperature: "25"}
  delay_corners:
    wc_rcworst: {timing_corner: wc, rc_corner: rcworst}
    bc_rcbest: {timing_corner: bc, rc_corner: rcbest}
  analysis_views:
    func_setup_wc: {delay_corner: wc_rcworst, is_setup: true}
    func_hold_bc: {delay_corner: bc_rcbest, is_hold: true}
```

Each level references the one below it **by name only** -- `opconds` is
free-standing (optional metadata most real `.lib` files already embed, so
most packages declare none at all), `delay_corners` references an already-
declared PVT timing-corner name and RC-extraction-corner name, and
`analysis_views` references an already-declared `delay_corners` name plus
`create_analysis_view`'s own `is_setup`/`is_hold`/`is_dynamic`/`is_leakage`
flags. `constraint_mode` is deliberately not part of an `analysis_view`
here -- which SDC a view uses is a design-level pairing, resolved at run
time from the environment (via WOLF's existing `inputs/constraints/
${design_name}.sdc` convention), not a PDK fact.

Resolution rejects a `delay_corners` entry referencing a timing-corner or
rc-corner name that isn't actually declared anywhere in the package, and
an `analysis_views` entry referencing an undeclared `delay_corners` name
-- a real authoring mistake, not something to silently resolve around.
A package with none of these declared (the common case -- most runs don't
need MMMC at all) resolves to empty catalogs, at no cost.

`wolf pdk menu`'s main menu has a **Signoff** entry for all three, each a
simple named-entry list (`a` add, `d` delete, `enter` edit, `esc` done).
Creating a `delay_corners` entry walks you through picking its timing
corner, then its rc corner, from whatever's actually declared elsewhere
in the package; creating an `analysis_views` entry walks you through
picking its delay corner, then toggling setup/hold/dynamic/leakage. If
the prerequisite level is empty (no timing/rc corners declared yet, for
a delay corner; no delay corners declared yet, for an analysis view),
`a` warns and aborts rather than letting you reference something that
doesn't exist -- go declare that first.

This is the static half of signoff. The dynamic half -- which of the
declared `analysis_views` actually drive a given run -- is meant to be
an environment-level `wolf.yaml` selection (a list of names into this
catalog, defaulting to "all" if omitted), not edited here; that half is
not yet implemented.

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

### `gds_layermap`: one shared GDS stream-out layer map for the whole PDK

`technology.gds_layermap` points at one GDSII/OASIS layer-map file --
`write_stream`'s own `-map_file` (man 20.15), real tool input, not
committed library content. Same flat-path shape as
`setup_yaml_fragment`, available for both flat and tracked packages:

```yaml
technology:
  name: tsmc65
  gds_layermap: config/tsmc65.sorted.gds2map
  tracks: {...}
```

Confirmed real need: a foundry-provided layer map has to be available
to everyone with access to that PDK, not re-typed into every design's
own `setup.yaml`. Declared once here, it flows into every run's
rendered `setup.yaml` as the top-level `gds_layermap` key
automatically (see `export` in [CADENCE_GENUS.md](CADENCE_GENUS.md)) --
a design's own `setup.<design>.yaml` can still set `gds_layermap`
itself to override this package default for that one design.

## Listing and inspecting

`wolf pdk list` lists every `pdk/*` manifest across all configured
registries, with its pinned revision, installation status, owning
registry, and a one-line summary (flat corner count, or track/vth combo
count). `wolf pdk info <name>` shows one package's source, revision,
license, full track/vth/corner breakdown, and -- when present --
`author`/`creation-date`/`last-modified-date`.

For a tracked package, `wolf pdk info` also prints a table breaking each
declared metal stack down by where it's actually used -- one row per
(stack, track/vth) combo, which of lef/qrc_techfiles that combo has files
for, and which named RC extraction corners (rcbest/rcworst/typical, ...)
its qrc_techfiles declares, if any -- the same "where is this stack
really used" view `wolf pdk menu`'s own clone flow needs you to already
have in your head, surfaced without opening the menu.

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

`c` is also available one level further in, on a metal stack's own
rc-corner editor (`wolf pdk menu` → Back-End → LEF → Techfiles → track →
vth → stack, or the equivalent spot via Tracks → metal stacks → edit a
stack → QRC techfiles) -- the same highlighted-entry → new-name → regex
shape as cloning a whole track/vth/metal stack: clone `rcbest` into a new
`rcworst`, say, leaving the source rc-corner's own files untouched.

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

`q`/`escape` quits without saving; `s` (or `ctrl+s`, from anywhere in the
menu -- any modal screen, even with a text field actively focused) saves
in place without closing; the Save button saves and closes.

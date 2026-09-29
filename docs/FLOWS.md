# WOLF flows

A `flow` package describes the digital-implementation scripts a backend runs
against a resolved design and technology. Like `pdk` packages, `flow`
packages can come from the committed `builtin` registry (for example
`flow/orfs`) or from a `local` registry pointing at host- or project-owned
content (see [Registries](REGISTRIES.md)).

## Base flows stay generic; projects get their own editable copy

A shared, institution-maintained flow (for example a Cadence Stylus flow
rooted under a site's own tool tree) should never be edited in place just
because one project needs a different `dont_use_cells` list, a different
step, or some other structural change: every other project pointed at that
same base flow would inherit the edit.

`wolf flow init` avoids that by copying the base flow's scripts into a new,
independently editable directory and emitting a ready-to-register `flow`
package manifest for it:

```bash
wolf flow init ibex-fabulous-genus-tsmc65 \
  --from /path/to/base/flow/scripts \
  --to /path/to/project-repo/wolf/flows/ibex-fabulous-genus-tsmc65 \
  --manifest /path/to/project-repo/wolf/registry/flow/ibex-fabulous-genus-tsmc65.yaml \
  --backend cadence-flowtool \
  --revision "$(git -C /path/to/project-repo rev-parse HEAD)"
```

The base flow tree is only ever read. The destination directory is the
project's own copy — freely editable, and normally committed inside the
project's own repository (not WOLF's `registry/`, and not the base flow's
tree) so edits get real version-control history and review, same as any
other source change.

Register the directory containing the emitted manifest as a `local` registry
so the flow becomes installable, then wire it into an environment exactly
like a technology package:

```bash
wolf registry add my-flows /path/to/project-repo/wolf/registry --type local
wolf install flow/ibex-fabulous-genus-tsmc65
wolf env set ibex-fabulous-genus-elab flow "{package: flow/ibex-fabulous-genus-tsmc65}"
```

## Relationship to per-run script snapshots

None of this changes how WOLF preserves reproducibility for a specific run.
The legacy runner already snapshots whatever `PROCESS_SCRIPTS` resolves to
into a numbered `scripts.<N>` directory inside each run, deduplicated by a
content digest so unchanged scripts are never re-copied. `wolf flow init`
only changes *what* `PROCESS_SCRIPTS` points at going forward — a project's
own editable copy instead of the shared base — the per-run snapshot behavior
is unmodified.

## Lighter-weight tweaks: backend overrides

A full editable copy is the right tool when a project needs to change flow
*structure* — steps, cell lists, and similar content that lives in the
flow's own scripts. For a small, tool-native attribute that only needs a
value supplied (not a structural change), prefer the narrower
`backend.cadence-flowtool` escape hatch instead of forking scripts just to
set one value — see [Genus attribute overrides](CADENCE_GENUS.md#genus-attribute-overrides).

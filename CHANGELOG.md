# Changelog

All notable user-visible changes to the installed `wolf` CLI and its bundled
shell/flow files are listed here, newest first.

## 0.1.4

- `setup.<design>.yaml` (a design's own Cadence Flowtool tuning knobs) is
  now generated as a fully commented template -- every accepted key, with
  its description, value shape, WOLF's own default, and a commented
  example (never a real cell name) -- the first time a design-setup key
  is set, or `wolf env create --from` resolves one. A project's own flow
  package can add its own per-design keys by declaring
  `metadata.flow.scripts.design_setup_template` (or shipping a
  `design_setup.template.yaml` by convention in its own scripts root);
  its section is appended under its own header, and its keys become
  usable the same way as WOLF's own. `DESIGN_SETUP_TEMPLATE`, an ordinary
  environment variable, overrides which template that section comes
  from; `wolf env menu` shows the resolved path and where it came from
  (set/package/convention/none). `wolf env set`/`unset`/`menu` now edit
  the file's text in place -- only the one key's own stanza changes,
  never the rest of the file, so a user's own comments survive. Setting
  a key's value also runs the same shape/choice validator a run's own
  render would, immediately, instead of only the next time a run
  actually renders setup.yaml.

## 0.1.3

- `wolf run -from/-to`, `wolf status`/`wolf monitor`, `wolf run --plan`, and
  shell completion now derive their valid Cadence Flowtool stage names from
  the active environment's own flow instead of a fixed nine-name list. A
  project flow package declaring more than the bundled nine (its own
  stages past `postroute`, or separate sections like `export`/
  `signoff_checks`) can now run and be watched through WOLF the same way
  the bundled flow always could; an unsupported-stage error now names that
  environment's own real choices, and a name used more than once in the
  flow is accepted as a dotted path. `wolf status`/`wolf monitor` also gain
  a `skipped` stage status -- a stage with no evidence it ever ran, while a
  later one in the same run did, shows `skipped` instead of a misleading
  `pending` (a retroactive heuristic, not real feature-flag introspection --
  WOLF has no visibility into which flag, if any, disabled it). An existing
  run's own expanded step detail now reflects its own frozen flow snapshot
  rather than always the bundled flow's steps.

## 0.1.2

- Cadence Genus backend (`genus_run_status`): a project flow package with
  its own top flow name and step set (e.g. `flow_current.implementation.
  floorplan.<step>` instead of the bundled flow's `block.implementation.
  floorplan.<step>`) kept every stage showing `pending`/`not started` in
  `wolf status`/`wolf monitor`, even while the run was genuinely working --
  `wolf.step-status`'s own live events never matched the bundled flow's
  canonical paths, by path or by bare name. A live event whose own real
  path still names the stage as one of its own dotted components is now
  picked up by `rollup_stage_states`'s existing tolerant fallback, marking
  the stage `running` (and `inferred`) instead of leaving it stuck. The
  stage's own expanded step list in `wolf monitor` still reflects the
  bundled flow's steps, not the project flow's real ones -- a separate,
  not-yet-fixed limitation.

## 0.1.1

- Cadence Genus backend (`genus_run_status`): a non-empty `errors` list on a
  `flow.status` record no longer overrides a literal success status word.
  Innovus attaches every error-severity message a step printed to that
  step's own `errors` list even when the step itself succeeded, so a
  finished, successful run could be reported `failed` by `wolf status`/
  `wolf monitor` at its first implementation stage. A known success or
  failure status word now always wins; a non-empty `errors` list only
  marks a step failed when the word is neither.

## 0.1.0

Changes since the previously installed build (`0.1.0.dev0`):

- `wolf activate`/`wolf deactivate`: the `«env»` prompt marker in both Bash
  and zsh now hides itself while kona's `proj` is drawing its own wolf token
  in the same prompt, and reappears once `proj` stops drawing it or once the
  environment is deactivated. Recomputed on every prompt, not frozen at
  activation.
- Registry commands (`wolf registry add`/`remove`, and anything that reads
  `config.yaml`) now honor `WOLF_HOME` for the configuration file itself,
  matching the priority `WOLF_HOME` already had for packages, environments,
  and registry content.
- Cadence Genus backend: fixed an invalid `check_design -unresolved` call in
  the post-route stage, switched metal-density checking to
  `check_metal_density`, and implemented `export` (GDS/netlist/DEF/LEF/SDC,
  with optional SPEF), including a fix to the exported GDS's merge/unit
  handling and moving `gds_layermap` to the PDK-package level. These affect
  `wolf run` and `wolf run --plan` for the `cadence-flowtool` backend only.
- `wolf catalog [--json]`: prints WOLF's canonical-concepts catalog
  (variables, processes, flow stages, commands), generated from WOLF's own
  code and documentation each time it runs.
- `wolf env describe [NAME] [--json]`: prints a sanitized, website-safe
  description of an environment (schema `wolf.describe/v1`); refreshed
  automatically on `wolf env set`/`unset`.
- A run now gets its own small `wolf.digest.json` (schema `wolf.digest/v1`),
  written into the run directory after every stage attempt and once more at
  run end: per-stage status/attempts/elapsed, a closed metric vocabulary,
  and DRC/LVS checks. QoR reports are now scanned for every implementation
  stage, not just synthesis, for the `cadence-flowtool` backend.
- `wolf status`/`wolf monitor`: a stage recorded "running" with no process
  actually still working in its run directory now reports as `stalled`
  instead of a misleading "running", and both commands show a `Processes`
  section (PID, elapsed, memory) for whatever is genuinely still running.
- Added `skills/`: short, tested usage guides (`SKILL.md` + `smoke.sh` +
  `golden.jsonl`) for running a flow, browsing environments, creating or
  adapting one, troubleshooting common failures, pre-flight tool checks, and
  monitoring a run -- bundled with the installed package under
  `share/wolf/skills/`.

## 0.1.0.dev0

Previously installed build; no changelog entry was kept for it.

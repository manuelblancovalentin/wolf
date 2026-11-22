# Changelog

All notable user-visible changes to the installed `wolf` CLI and its bundled
shell/flow files are listed here, newest first.

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

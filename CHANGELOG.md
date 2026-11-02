# Changelog

All notable user-visible changes to the installed `wolf` CLI and its bundled
shell/flow files are listed here, newest first.

## 0.1.0.dev1 (unreleased)

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

## 0.1.0.dev0

Previously installed build; no changelog entry was kept for it.

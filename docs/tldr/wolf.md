# wolf

> Manage WOLF EDA environments and inspect workflow support.
> A WOLF environment represents an EDA experiment, not a Python virtual environment.

- Show command help or the installed version:

`wolf {{--help|--version}}`

- List environments, including an empty environment collection:

`wolf env list`

- Create an environment or inspect one with the common info command:

`wolf env create {{environment}}`

`wolf info {{environment}}`

- Import and clone a declarative environment:

`wolf env create {{environment}} --from {{wolf.yaml}}`

`wolf env clone {{environment}} {{new_environment}}`

- Create or edit a declarative environment interactively instead of hand-writing YAML
  (defaults to the active environment, so the usual flow is create, activate, menu, deactivate):

`wolf env menu`

`wolf env menu {{environment}}`

- Scaffold a project's inputs/outputs/workspace directories:

`wolf env auto-setup {{environment}}`

- Persist a variable in an environment:

`wolf env set {{environment}} {{KEY}} {{value}}`

- Change a canonical clock period in a declarative environment:

`wolf env set {{environment}} constraints.clocks.0.period_ps {{1100}}`

- Pass an arbitrary variable through to whatever the backend execs, and into
  the interactive shell on activation (set `env: {}` first if the block
  doesn't exist yet):

`wolf env set {{environment}} env.{{GENUS_NUM_CPUS}} {{64}}`

- Set a design-level cadence-flowtool knob -- routed to that design's own setup.<design>.yaml, not wolf.yaml:

`wolf env set {{environment}} add_tieoffs_cells {{'["TIEHIX1", "TIELOX1"]'}}`

- Remove a key set by `wolf env set` (same routing rule, either file):

`wolf env unset {{environment}} {{KEY}}`

- Activate an environment, then omit its name on later commands:

`wolf activate {{environment}} && wolf info && wolf run --plan`

- Remove an environment without prompting:

`wolf env remove --yes {{environment}}`

- List legacy process definitions:

`wolf process list`

- Bootstrap an independently editable copy of a base flow's scripts:

`wolf flow init {{name}} --from {{/path/to/base/flow}} --to {{/path/to/project/flows/name}} --manifest {{/path/to/registry/flow/name.yaml}} --backend {{cadence-flowtool}} --revision {{label}}`

- Cut an inspectable, versioned snapshot of an environment's flow scripts under inputs/flows/<design>/ (only when you ask -- never automatic):

`wolf flow snapshot {{environment}}`

- List all pdk/* registry manifests, or show one in detail:

`wolf pdk {{list|info tsmc65}}`

- Create or edit a PDK registry manifest's tracks/vths/corners and file lists (omit the name to pick from existing packages):

`wolf pdk menu {{tsmc65}}`

- List built-in backends:

`wolf backend list`

- Inspect local ORFS backend configuration:

`wolf backend info orfs`

- Install the pinned Ibex, ASAP7, and ORFS packages:

`wolf install {{rtl/ibex|flow/orfs|pdk/asap7}}`

- List installed packages or inspect one package:

`wolf package list`

`wolf package info rtl/ibex`

- Resolve a named environment without starting EDA tools:

`wolf run --environment {{environment}} --plan`

- Run an environment with an explicit invocation-relative workspace override:

`wolf run --environment {{environment}} --workspace ./work --yes`

- Run without confirmation prompts while retaining progress and summaries:

`wolf run --yes`

- Run Cadence Genus and stay at its own prompt to inspect it when done:

`wolf run --environment {{environment}} --interactive`

- Resume Cadence Genus at a mapping stage using a prior run's checkpoint:

`wolf run --environment {{environment}} -from syn_map -to syn_map`

- Load Bash integration to enable in-place activation and command completion:

`source ./shell/wolf.bash && wolf activate {{environment}}`

- For zsh, load its native prompt and completion integration instead:

`source ./shell/wolf.zsh && wolf activate {{environment}}`

- Inspect or deactivate the active environment:

`wolf {{info|deactivate}}`

- Inspect the latest run for the active environment:

`wolf status`

- Emit run status as JSON or inspect a specific run directory:

`wolf status --json`

`wolf status --run {{/path/to/run}}`

- Auto-refresh in place with a live spinner/tree until the run finishes:

`wolf status --watch`

- Full-screen TUI: arrow keys to pick a stage, enter to expand/collapse its own steps:

`wolf monitor`

- Report basic installation and runtime facts:

`wolf doctor`

- Inspect or update persistent installation settings:

`wolf config list`

`wolf config set paths.packages {{/tools/wolf/packages}}`

`wolf config menu`

- Manage package-manifest registries:

`wolf registry list`

`wolf registry add {{lab}} {{/projects/eda/wolf-registry}} --type local`

`wolf registry sync {{shared}}`

- Configure WOLF interactively for first use:

`wolf init`

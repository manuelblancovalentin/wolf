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

- Persist a variable in an environment:

`wolf env set {{environment}} {{KEY}} {{value}}`

- Change a canonical clock period in a declarative environment:

`wolf env set {{environment}} constraints.clocks.0.period_ps {{1100}}`

- Remove an environment without prompting:

`wolf env remove --yes {{environment}}`

- List legacy process definitions:

`wolf process list`

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

- Report basic installation and runtime facts:

`wolf doctor`

- Inspect or update persistent installation settings:

`wolf config list`

`wolf config set paths.packages {{/tools/wolf/packages}}`

- Manage package-manifest registries:

`wolf registry list`

`wolf registry add {{lab}} {{/projects/eda/wolf-registry}} --type local`

`wolf registry sync {{shared}}`

- Configure WOLF interactively for first use:

`wolf init`

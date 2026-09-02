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

- Persist a variable in an environment:

`wolf env set {{environment}} {{KEY}} {{value}}`

- Remove an environment without prompting:

`wolf env remove --yes {{environment}}`

- List legacy process definitions:

`wolf process list`

- List built-in backends:

`wolf backend list`

- Inspect local ORFS backend configuration:

`wolf backend info orfs`

- Resolve a named environment without starting EDA tools:

`wolf run --environment {{environment}} --plan`

- Run an environment with an explicit invocation-relative workspace override:

`wolf run --environment {{environment}} --workspace ./work --yes`

- Load Bash integration to enable in-place activation and command completion:

`source ./shell/wolf.bash && wolf activate {{environment}}`

- For zsh, load its native prompt and completion integration instead:

`source ./shell/wolf.zsh && wolf activate {{environment}}`

- Inspect or deactivate the active environment:

`wolf {{info|deactivate}}`

- Report basic installation and runtime facts:

`wolf doctor`

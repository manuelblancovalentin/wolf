# WOLF command-line presentation

The installed Python CLI preserves the vibrant terminal identity of the legacy
WOLF interface. Human-facing commands display a command-specific banner and a
section title, followed by consistently styled status messages and values.

Python commands must use `wolf.ui` rather than embedding ANSI escape sequences
or importing Rich throughout individual command modules. This keeps headers,
colors, error routing, and treatment of user-provided text consistent. Values
are rendered as literal `Text` objects and are never interpreted as Rich markup.

The initial header mapping is:

- general commands and `wolf doctor`: WOLF;
- `wolf env ...` and shell-activation messages: WOLF ENV;
- `wolf process ...`: WOLF PROCESS;
- `wolf backend ...`: WOLF;
- future run commands: WOLF RUN.

Rich performs normal terminal capability detection and honors `NO_COLOR`.
Redirected and captured output remains plain text without escape sequences.
`wolf --version` deliberately remains a single unadorned line for scripting.

Package commands use `wolf package info KIND/NAME` for the same terminology as
environment and backend inspection. `wolf package list` shows installed
versions, while `wolf install KIND/NAME` resolves a pinned built-in manifest.

Declarative environments are imported with `wolf env create NAME --from FILE`.
`wolf env clone SOURCE DEST` creates an independent declarative profile, and
`wolf env set NAME constraints.clocks.0.period_ps 1100` demonstrates the narrow
structured setter. `wolf info` labels profiles as `declarative-v1` or `legacy`
and presents canonical semantic values rather than dumping raw YAML.

The Bash implementation continues to use `bin/defs` and `bin/utils`. It should
remain visually compatible, but its rendering implementation does not need to
be shared with Python.

## Active environments

After loading the Bash integration, `wolf activate NAME` sets
`WOLF_ACTIVE_ENV=NAME` in the current shell. It selects configuration only and
does not change the working directory. `wolf deactivate` restores the original
prompt and removes WOLF-owned state. Activating another environment switches
in place.

`wolf info NAME` describes a stored profile using the same semantic view as
`wolf info` inside an active environment. Without an active environment the
name is required. `wolf run --plan` describes a prospective run. Explicit
`wolf run --environment NAME` overrides the active environment for that
invocation only.

Execution location does not define experiment location. The active/resolved
WOLF environment does.

Use `shell/wolf.bash` for Bash and `shell/wolf.zsh` for zsh. The zsh integration
uses a `precmd` hook so theme-managed prompts retain the active-environment
marker.

## Shell completion

The Bash and zsh integration files also register native completion for the
installed `wolf` command. Completion currently covers public commands and
subcommands, their current options, stored environment names, built-in backend
names, and built-in package identifiers. Dynamic candidates come from a private machine-readable Python
protocol; shell code does not scrape WOLF's formatted output or duplicate state
discovery.

Examples include `wolf <TAB>`, `wolf env <TAB>`,
`wolf activate <TAB>`, `wolf backend info <TAB>`, and environment/backend values
for `wolf run`. Completion uses `WOLF_HOME`, so an isolated or non-default state
root is reflected automatically.

This is the initial completion surface. Later CLI work should extend the same
protocol with stage names, executor choices, canonical configuration keys, and
other contextual values as those interfaces become stable. Automatic shell RC
initialization remains an installation concern; for now completion is enabled
when the appropriate shell integration file is sourced.

## Global configuration and registries

`wolf config list|get|set|unset|path|edit` manages installation-wide XDG
configuration. `wolf init` provides a confirmed first-use wizard and can add a
marked Bash startup snippet without duplicating it. Package manifests come
from the always-available built-in registry plus configured local or Git
registries managed by `wolf registry list|add|info|sync|remove`.

Use `wolf run -y` or `--yes` to skip confirmations while retaining normal
progress and summaries. Package installs stream Git progress and report
elapsed wall time. Declarative runs print canonical semantic pre-run values;
legacy profiles retain their compatibility summary. A completed run reports
stage timing and a small set of backend-owned optional metrics.

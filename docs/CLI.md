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

The Bash implementation continues to use `bin/defs` and `bin/utils`. It should
remain visually compatible, but its rendering implementation does not need to
be shared with Python.

## Active environments

After loading the Bash integration, `wolf activate NAME` sets
`WOLF_ACTIVE_ENV=NAME` in the current shell. It selects configuration only and
does not change the working directory. `wolf deactivate` restores the original
prompt and removes WOLF-owned state. Activating another environment switches
in place.

`wolf env show NAME` describes a stored profile. `wolf info` describes the
current active resolved environment. `wolf run --plan` describes a prospective
run. Explicit `wolf run --environment NAME` overrides the active environment
for that invocation only.

Execution location does not define experiment location. The active/resolved
WOLF environment does.

Use `shell/wolf.bash` for Bash and `shell/wolf.zsh` for zsh. The zsh integration
uses a `precmd` hook so theme-managed prompts retain the active-environment
marker.

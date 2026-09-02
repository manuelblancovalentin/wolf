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

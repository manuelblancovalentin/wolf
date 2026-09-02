# WOLF configuration

WOLF's persistent installation configuration is `wolf.config/v1` at
`$XDG_CONFIG_HOME/wolf/config.yaml` (normally `~/.config/wolf/config.yaml`).
It contains only installation behavior: data/package/environment/cache paths,
default workspace, preferred container runtime, shell prompt preference, and
registry definitions. It does not contain experiment design or timing values.

Use `wolf config list`, `get`, `set`, `unset`, `path`, and `edit`. Path values
typed to `config set` are made absolute immediately, so they are independent
of caller cwd. Writes are validated and atomic. `wolf init` is a line-oriented
first-use wizard with the same settings and optional, confirmed Bash rc-file
integration; it never silently edits dotfiles and is not a TUI.

`WOLF_HOME` remains a compatibility/testing override for WOLF-owned data
(legacy environments, packages, cache, and registry checkouts). It does not
move the XDG configuration file and does not override workspace or runtime
settings. Explicit command options take precedence over configuration.

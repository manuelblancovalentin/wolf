# WOLF configuration

WOLF keeps everything it owns -- configuration and all data -- under one
default home, `~/.wolf`:

```text
~/.wolf/
  config.yaml     installation configuration (wolf.config/v1)
  envs/           environments (legacy vars.env and declarative-v1 alike)
  packages/       installed rtl/pdk/flow packages, keyed by revision
  registries/     configured local/git registry checkouts
  cache/          container image pulls and other disposable cache
```

One tree was chosen over a split XDG layout (`~/.config`, `~/.local/share`,
`~/.cache`) because it's the convention WOLF's own legacy environments
already use on real installations, and because it's simply easier to find,
back up, or point a fresh install at as a single directory. If a user
explicitly sets `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, or `XDG_CACHE_HOME`,
that opt-in is still honored for the piece it names -- WOLF never ignores
an explicit XDG variable, it just doesn't assume one.

Each piece can also be moved independently, with `wolf config set
paths.{data,packages,environments,registries,cache} PATH`; `paths.data` is
`~/.wolf` itself (moving it moves everything that isn't independently
overridden). It does not contain experiment design or timing values.

Use `wolf config list`, `get`, `set`, `unset`, `path`, `edit`, and `menu`
(a full-screen, arrow-key picker over the same keys, via `textual`). `menu`
also has a "Registries" row -- list, add, and remove the registries `wolf
registry add/list/remove` manage, from inside the same screen. Path
values typed to `config set` are made absolute immediately, so they are
independent of caller cwd. Writes are validated and atomic. `wolf init` is a
line-oriented first-use wizard with the same settings and optional,
confirmed Bash rc-file integration; it never silently edits dotfiles and is
not a TUI.

`WOLF_HOME` remains a compatibility/testing override that redirects all of
the above (environments, packages, cache, and registry checkouts) to one
directory at once, bypassing `wolf config set paths.*` entirely. It does
not move the configuration file and does not override workspace or runtime
settings. Explicit command options take precedence over configuration.

`wolf init` detects Bash or zsh when possible and offers the matching marked
startup snippet (`~/.bashrc` or `~/.zshrc`). Installation is explicit and
idempotent; uncertain shells are reported with both supported choices.

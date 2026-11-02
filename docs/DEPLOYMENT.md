# Deploying a new wolf build

This is the short checklist for installing the current working tree into the
shared conda environment with `rebuild-wolf`, and for rolling back if
something looks wrong afterward. It assumes the reader already has
`rebuild-wolf` available and knows which conda environment name to pass it;
this document does not name one.

## Before you deploy

1. **Save the current wheel.** `rebuild-wolf` builds a wheel with a fixed file
   name (`wolf_eda-<version>-py3-none-any.whl`) into the checkout's `dist`
   directory and overwrites whatever is already there. Before rebuilding,
   copy the current wheel out to a backup location you control, named with
   its version and the date, so you have something to roll back to. Confirm
   `wolf --version` beforehand so the backup is labeled with the version it
   actually corresponds to.
2. **Check the working tree is clean.** `git status --short` in the checkout
   should print nothing (no modified tracked files). `rebuild-wolf` builds
   from the working tree, not from a commit, so an uncommitted edit would be
   deployed silently. Untracked files you know are deliberately set aside are
   fine; a modified tracked file is not.

## Deploy

3. Run `rebuild-wolf <env>` with the conda environment name.

## After you deploy

4. **`wolf --version`** — confirm it reports the new version, not the one you
   backed up.
5. **`wolf info` on one already-existing legacy environment** — confirm it
   resolves and prints without error; a pass looks like a normal environment
   summary, no traceback.
6. **Shell marker behavior, in both bash and zsh** — source the updated
   `shell/wolf.bash` or `shell/wolf.zsh` (or open a fresh login shell) and:
   - `wolf activate <environment>` shows the `«name»` marker in the prompt.
   - If `proj` is also active and drawing its own wolf token
     (`PROJ_PROMPT_TOKENS` contains `wolf`), wolf's own marker stays hidden
     instead of doubling up.
   - `wolf deactivate` removes the marker and restores the prompt exactly as
     it was before activation.
   A pass looks like the marker appearing, disappearing, and reappearing
   exactly as described, with no leftover marker text and no shell errors.

## Rollback

If any check above fails, reinstall the backed-up wheel over the new one:

```sh
pip install --force-reinstall --no-deps /path/to/backup/wolf_eda-<old-version>-py3-none-any.whl
```

using the same Python environment `rebuild-wolf` installs into. Confirm
`wolf --version` reports the old version again.

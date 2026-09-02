# Testing the legacy WOLF implementation

Run the complete suite from the repository root:

```bash
tests/run
```

For development from a clone, install the CLI in editable mode (preferably in a
virtual environment used only for development):

```bash
python3 -m pip install -e .
```

This installs the `wolf` console command. A normal WOLF environment remains an
EDA experiment environment; it is unrelated to the optional Python environment
used to isolate developer tooling.

The suite uses Python's standard `unittest` runner around isolated Bash subprocesses. It requires Bash, Python 3, PyYAML (already used by legacy WOLF), Rich (installed with the Python package), and the GNU command-line utilities used by the current scripts. It does not require Bats, Cadence software, licenses, proprietary PDKs, `shyaml`, or institutional filesystems.

Every test creates a temporary `HOME`, WOLF state directory, project, workspace, and tool path. CLI tests also set `WOLF_HOME` to an independent temporary state root. The real user `~/.wolf` and project directories are never read or written.

## Mocked behavior

Tests install a temporary `flowtool` stub. The Flowtool stub records exact arguments, creates representative logs, and can return success, nonzero status, or the legacy `Flow failed` log marker. Small synthetic Flowtool-style configuration files exercise run allocation, stage ranges, snapshots, links, and history without invoking EDA tools. Regression coverage runs the Cadence compatibility path without a `shyaml` executable; YAML queries use WOLF's internal PyYAML helper.

Installed-CLI tests invoke the Python module directly and exercise environment
mutations through an isolated legacy Bash bridge. No external EDA command is
used by the CLI tests. Captured CLI output is also checked to ensure Rich emits
plain text rather than ANSI control sequences when output is redirected.

Backend tests inspect the built-in Python registry and use a tiny shell fake
backend with stages `a`, `b`, and `c`. The fake proves that range selection,
passthrough arguments, execution dispatch, and failure stopping do not depend
on Flowtool. Legacy Cadence tests continue to use the temporary `flowtool` stub
for default and explicit `cadence-flowtool` selection.

Test names distinguish intent:

- `test_characterization_*` protects intended legacy semantics.
- `test_regression_*` protects a confirmed bug fix.

## Still requiring real Cadence testing

Institutional regression remains necessary for real Flowtool YAML/templates and stage discovery, license/tool setup, Genus/Innovus database continuation, interactive stage behavior, Tcl PID injection, tool-generated log naming, and actual PDK/library integration. Those tests must remain separately gated and must not place proprietary content in this repository.

The old generated installer is known to be incomplete and is not exercised or repaired by this suite.

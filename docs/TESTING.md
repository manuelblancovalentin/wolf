# Testing the legacy WOLF implementation

Run the complete suite from the repository root:

```bash
tests/run
```

The suite uses Python's standard `unittest` runner around isolated Bash subprocesses. It requires Bash, Python 3, PyYAML (already used by legacy WOLF), and the GNU command-line utilities used by the current scripts. It does not require Bats, Cadence software, licenses, proprietary PDKs, `shyaml`, or institutional filesystems.

Every test creates a temporary `HOME`, WOLF state directory, project, workspace, and tool path. The real user `~/.wolf` and project directories are never read or written.

## Mocked behavior

Tests install temporary `flowtool` and `shyaml` stubs. The Flowtool stub records exact arguments, creates representative logs, and can return success, nonzero status, or the legacy `Flow failed` log marker. Small synthetic Flowtool-style configuration files exercise run allocation, stage ranges, snapshots, links, and history without invoking EDA tools.

Test names distinguish intent:

- `test_characterization_*` protects intended legacy semantics.
- `test_regression_*` protects a confirmed bug fix.

## Still requiring real Cadence testing

Institutional regression remains necessary for real Flowtool YAML/templates and stage discovery, license/tool setup, Genus/Innovus database continuation, interactive stage behavior, Tcl PID injection, tool-generated log naming, and actual PDK/library integration. Those tests must remain separately gated and must not place proprietary content in this repository.

The old generated installer is known to be incomplete and is not exercised or repaired by this suite.

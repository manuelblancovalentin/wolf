# WOLF packages

WOLF packages are managed, reusable EDA assets. They are distinct from host
dependencies: `rtl/ibex`, `pdk/asap7`, and `flow/orfs` are packages, while Git,
Python, PyYAML, and a usable container runtime are dependencies.

## Phase 1 model

Phase 1 supports the package kinds `rtl`, `pdk`, and `flow`. A trusted,
file-backed registry under `registry/` contains declarative YAML manifests.
Classes implement generic package identity, registry, store, and installation
behavior; manifests describe concrete assets.

Each manifest records schema version, kind/name, description, source type and
URL, pinned revision, recursive-submodule policy, validation paths, license
metadata, and a small package-specific semantic metadata mapping. This is only
the schema needed by the first packages; it is not a dependency solver or a
final public registry format.

| Package | Pinned identity | Representation |
| --- | --- | --- |
| `rtl/ibex` | `77d801001554cce8fe69e742e96539eecbe74425` | Upstream lowRISC Git checkout |
| `flow/orfs` | `8c0616910615e843780ba527526f2b83a564ba70` | ORFS Git checkout with recursive submodules |
| `pdk/asap7` | tree `b9b4c9266113c67978f75b987f1d5a0841c2f15f` | Validated view of `flow/platforms/asap7` in the pinned ORFS checkout |

At the validated ORFS revision, ASAP7 is tracked directly in ORFS rather than
as a submodule. Its platform tree is about 222 MB. WOLF therefore installs
`pdk/asap7` as a distinct metadata record and relative symbolic-link view into
the installed `flow/orfs` content. This preserves a distinct technology
identity and exact Git tree revision without copying the collateral. Install
`flow/orfs` before `pdk/asap7`; Phase 1 does not resolve dependencies
automatically.

## Storage and commands

Packages live separately from implementation workspaces:

```text
WOLF_HOME/packages/<kind>/<name>/<revision>/
  installed.yaml
  source/       # Git sources, or
  content       # relative view into another installed package
```

The human-readable `installed.yaml` records identity, source URL/type, pinned
and resolved revisions, UTC installation time, and content location. The
versioned absolute destination is derived only from `WOLF_HOME` and the
manifest; caller cwd is irrelevant.

```bash
wolf package list
wolf package info rtl/ibex
wolf install flow/orfs
wolf install rtl/ibex
wolf install pdk/asap7
```

Git packages are fetched at the pinned commit into a staging directory,
checked out detached, initialized recursively when declared, validated, and
then moved atomically to the deterministic destination. Reinstalling an exact,
valid revision is idempotent. WOLF refuses to overwrite a partial, corrupt, or
mismatched installation.

An installed `flow/orfs` supplies the ORFS flow root when `ORFS_ROOT` is not
configured. Explicit/environment `ORFS_ROOT` remains higher precedence, so
external and institutional checkouts continue to work.

## Integration smoke test

The real network test is opt-in because ORFS recursive submodules consume
substantial disk space and bandwidth. Choose a dedicated retained directory:

```bash
export WOLF_PACKAGE_TEST_HOME=/tmp/wolf-package-smoke
tests/integration/run_packages
```

The harness never removes the directory and rejects `/` and the normal
`~/.wolf` state root. Repeated runs exercise idempotency.

Phase 1 has no uninstall, update, search, version negotiation, dependency
solving, publishing, remote index, signing, or proprietary-asset distribution.
Completion currently suggests built-in identifiers for `wolf install` and
`wolf package info`; later package kinds and registry capabilities will extend
the same protocol.

Package semantic metadata feeds `wolf.environment/v1` resolution. It provides
component defaults rather than complete experiments: `rtl/ibex` provides
design/top and canonical source patterns, `pdk/asap7` provides the technology
identity, and `flow/orfs` provides flow/backend identity and its flow root.
Environment values override these defaults, and resolved contexts retain the
pinned revisions. See `docs/ENVIRONMENTS.md`.

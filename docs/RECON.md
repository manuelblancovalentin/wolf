# WOLF Reconnaissance

## Current architecture

WOLF is currently a sourced Bash application with one monolithic Cadence runner and a partially implemented host-local process registry.

- `bin/wolf.init.sh`: installation bootstrap and `wolf` command dispatcher. It sources shared definitions, environment/process functions, and completion; it also dispatches runs and process tracking.
- `bin/wolf.env`: environment lifecycle (`create`, `activate`, `deactivate`, `reload`, `set`, `status`, `history`) plus a large Cadence/Calibre-oriented project scaffolder (`auto-setup`). Environment state lives under `~/.wolf/envs/<name>` as generated shell, `vars.env`, bucket sources, history, and run links.
- `bin/wolf.run`: run allocation, script snapshots, generated configuration, `.latest` links, UUID/history records, stage selection/tracking, and direct Flowtool invocation. This is where generic run management and the Cadence backend are most tightly interleaved.
- `bin/wolf.process`: early process/library/metal-stack/flow registry under `~/.wolf/config`. It generates exact-hostname shell fragments from `config/technodes`, but only TSMC65 has a skeletal definition. Its closing design notes already describe the sound RTL/process/flow composition model.
- `bin/utils`, `bin/defs`: presentation, errors, indexed-path helpers, input helpers, and global variable lists. Indexed artifacts are generic core behavior; most presentation code is incidental.
- `bin/flow_yaml_parser.py`: Cadence flow-step extraction after shell text filters reduce a Flowtool YAML file. It is not a general WOLF manifest parser.
- `bin/wolf.autocomplete.sh`: Bash completion, including Flowtool flags and cached Flowtool stages. `bin/autorecursivelink.tcl` is an unused recursive symlink helper. `bin/wolf.wizard` is a hard-coded TSMC65 prototype, not a reusable command.
- `templates/activate.template`, `templates/deactivate.template`: shell-state capture/restore. `templates/{tsmc65,tsmc28,gf22}` are Cadence Stylus/Genus/Innovus/Calibre and process-specific setup, constraint, floorplan, and environment assets.
- `config/technodes/tsmc65`: incomplete host-local process scaffolding inputs. `README.md` documents the legacy workflow. `wolf-latest-Linux-x86_64.sh` is a stale/incomplete generated installer. Packaging stubs (`__init__.py`, `MANIFEST.in`) do not form a working Python package. There is no test suite or CI configuration.

Conceptually, the intended layers are already visible: a generic environment composes design + process/libraries/stack + flow; a run snapshots that resolved composition; a backend prepares and executes tool-specific stages.

## Behaviors worth preserving

- Allocate separate design/process run trees, append numbered clean runs, and allow intentional continuation of an existing run.
- Preserve prior databases/results and snapshot the exact scripts/configuration used; reuse an unchanged script snapshot rather than duplicating it.
- Maintain convenient run-, script-, configuration-, log-, floorplan-, and stage-summary `.latest` links.
- Keep UUID-addressable environment run links and human-readable command/date/directory history.
- Preserve explicit environment creation/activation/deactivation, saved variables, ordered bucket sourcing, and the ability to recreate an environment.
- Keep design/RTL, process/PDK, libraries, metal stack, and flow independently selectable; the composition model in `bin/wolf.process:506-545` is conceptually sound and should not be rewritten away.
- Preserve project scaffolding as a capability, but let each backend contribute its own files instead of making Calibre/Cadence files universal.
- Preserve Cadence stage discovery, `-from`/`-to`/single-stage behavior, passthrough arguments, interactive-per-stage execution, PID tracking, and failure stopping through characterization tests before extraction.
- Retain the existing Cadence Tcl/YAML/SDC assets as backend/process assets. They need deduplication and validation, not translation merely for consistency.

## Backend-specific coupling

- `bin/wolf.run:223-313,425-483` assumes `shyaml`, Cadence-tagged setup/flow YAML, three-way Flowtool template concatenation, and placeholder substitution. Configuration preparation belongs behind a Cadence backend.
- `bin/wolf.run:508-610` constructs Flowtool commands and derives stages by regex-filtering Flowtool YAML into `bin/flow_yaml_parser.py`. Stage discovery and command construction are backend operations.
- `bin/wolf.run:617-785` implements Flowtool-specific one-stage-at-a-time execution and Tcl PID injection. Core should request stages and record results; the Cadence adapter should retain these mechanics.
- `bin/wolf.autocomplete.sh:23-26,43-56` embeds Flowtool flags and reads Cadence stage caches. Completion should ask the selected backend for flags/stages.
- `bin/wolf.env:425-1176` treats Calibre directories, SDC, Stylus YAML, design `.env.csh`, and Innovus floorplan Tcl as universal project structure. Generic scaffolding should delegate backend additions.
- `templates/*/*.setup.template.yaml` carry the Cadence Stylus tag and Genus/Innovus/Calibre settings; `*.floorplan.template.tcl` uses Innovus/Flowtool commands. These are valid Cadence backend assets, with process-specific values layered within them.
- `bin/wolf.process:303-316,475-490` names all flows `STYLUS` and stores executable Bash declarations rather than backend-neutral metadata.

## Host/process coupling

- `bin/wolf.process:139-158,185,269-315,386-488` keys process, stack, library, and flow fragments by exact `hostname`; this prevents a definition from moving between machines and conflates host overrides with process identity.
- `bin/wolf.env:977-1064`, `README.md:217-231`, and `bin/wolf.wizard:9-47` encode Kona, Beast1/Fermilab, user-specific profiles, and `/asic` paths. The wizard also performs hard-coded file displays on execution.
- `config/technodes/tsmc65/tsmc65.bucket.template.csh` is mostly commented institutional TSMC65 layout knowledge; `bin/wolf.process` expects a differently named `*.process.setup.template.wlf` (`bin/wolf.process:190`) that is absent. GF22 and TSMC28 have flow templates but no technode registry definitions.
- `templates/*/*.env.template.csh` are actually Bash, compute process-specific metal-stack/Vt/track choices, and assume a Cadence variable vocabulary. Their `.csh` suffix is misleading.
- The three floorplan Tcl templates are effectively duplicates; setup templates also contain copied TSMC65/FLORA/Beast1 assumptions in other process directories. Shared Cadence logic and process data are not separated.
- Linux/GNU assumptions include `/proc` UUID/PID access (`bin/wolf.run:518,744-766`), GNU `find -regextype`, `grep -P/-z`, `sed -i`, GNU `top` options, Bash associative arrays/process substitution/readline, `dialog`, `sha512sum`, `shyaml`, and PyYAML. Dependencies are neither centrally declared nor checked per backend.

## Technical debt / likely bugs

### P0 correctness

- `bin/wolf.run:419-422` deletes `*.out`, `*.cmd*`, and `*.log` below the caller's current directory, not the run directory. A run can remove unrelated user files.
- History serialization is invalid: `bin/wolf.run:532-533` omits the newline between `dir` and `date`; unescaped commands can also break YAML. `wolf history` then relies on that YAML (`bin/wolf.env:398-417`).
- `--design` assigns `DESIGN`, while all run paths and parsing use `DESIGN_NAME` (`bin/wolf.run:29-30,108-110,129`), so the advertised override is ineffective.
- New process creation references a missing `tsmc65.process.setup.template.wlf` even though the committed file is named `tsmc65.ip.setup.template.wlf` (`bin/wolf.process:190-193`). Before the P0 fixes, it logged an installation error but continued and produced a misleading/incomplete process directory rather than failing cleanly. Unknown technodes likewise logged an error but continued.
- Auto-setup error paths use arithmetic expansion instead of calling error functions (`bin/wolf.env:437-485`), and `if OVERWRITE` at line 923 invokes a command rather than testing the variable.
- Flowtool exit status is ignored; failure detection depends on matching `Flow failed` in an anticipated log (`bin/wolf.run:771-779`). The cross-stage guard at lines 716-719 tests numeric `$?` against text and `steps_run` is never incremented.
- `wolf-latest-Linux-x86_64.sh` is a 423-line truncated constructor expecting payload after line 556 and invoking an unset `CONDA_EXEC`; its empty-payload MD5 masks the truncation. It is not a usable installer.

### P1 architecture/portability

- `bin/wolf.run` owns both generic run lifecycle and nearly every Cadence action, so adding ORFS by branching inside it would duplicate or destabilize the preservation logic.
- Executable configuration is assembled and run through `eval`, `source`, `export $(cat ...)`, and unquoted expansion (`bin/wolf.init.sh:100-112`; `templates/activate.template:7-13`; `templates/deactivate.template:3-16`; `bin/wolf.run:238-253,467-482`). Spaces, arrays, metacharacters, and untrusted project values can alter commands or corrupt state.
- Indexed-path discovery builds `find | sed | grep` programs as strings and evaluates them (`bin/utils:94-185`, callers throughout `bin/wolf.run`). It is GNU-specific, injection-prone, race-prone, and inconsistent: setup/flow filename regexes at `bin/wolf.run:302,311` only recognize one-digit suffixes.
- Templates are merged by dropping fixed header lines and substituted with unescaped `sed` replacement values (`bin/wolf.run:425-483`); paths containing `;`, `&`, backslashes, or newlines can produce invalid configuration.
- Host identity, process metadata, backend choice, and executable environment setup are all encoded in sourced shell fragments. There is no resolved manifest containing backend/tool/RTL/PDK/config versions.
- Environment deactivation attempts to reconstruct shell state by diffing `declare` output and evaluating the result. This is inherently fragile for functions, readonly/special variables, arrays, quoting, and nested environments.

### P2 maintainability

- `bin/wolf.env` duplicates preview/create/overwrite logic for every scaffold file and hard-codes process option lists into generated scripts; a data-driven scaffold plan would eliminate divergent branches without changing behavior.
- Nearly identical Cadence floorplan and environment templates are copied per process, already carrying stale cross-process comments/settings. Factor only proven common Cadence portions; do not generalize process values prematurely.
- Argument parsers silently consume neighboring tokens, mix environment and local names, and expose unreachable/stale commands (`UNSET` has a dispatch case but is not accepted by `bin/wolf.init.sh:69`). Help and README content disagree with implementation.
- `bin/flow_yaml_parser.py` reports YAML errors to stdout with success status, lacks argument/schema validation, and is fed YAML reconstructed by regex. `shyaml` and PyYAML duplicate YAML dependencies.
- Empty packaging/config stubs, extensive dead/commented experiments, and the unused Tcl helper/wizard obscure what is supported. These should be classified or retired only after tests establish usage.

## Candidate backend boundary

Keep the core responsible for environment resolution, run IDs/directories, immutable snapshots, `.latest` links, history/provenance, locking, and user interaction. A selected backend needs only to provide:

1. `validate(context)` — report backend-local tool/data dependencies.
2. `prepare(context, run_dir)` — materialize backend configuration into the snapshot and return the ordered stage list plus reproducible command metadata.
3. `run_stage(context, stage, passthrough_args)` — execute one stage and return status/artifact/log information.

The Cadence implementation can initially wrap the existing code unchanged. ORFS can prepare its native config and run Yosys/OpenROAD in a pinned container. Process/PDK/design definitions remain inputs to `context`, not backend implementations.

## Bash vs Python

Clear value from Python:

- CLI parsing/validation and typed resolution of environment, design, process, stack, flow, and backend.
- Atomic run-number allocation, locking, symlink updates, UUID generation, and structured history/manifests.
- YAML/JSON/TOML parsing, schema validation, safe template rendering/merging, version/provenance capture, and stage-plan handling.
- Portable registry/package resolution and backend-local dependency probes.
- Data-driven project scaffolding and testable subprocess/container orchestration.

Keep in shell:

- Activation/deactivation that must mutate the caller's shell and prompt.
- Small native-environment adapters that source institutional tool setup or module files before executing a backend command.
- Tool-native Tcl/SDC and concise launch wrappers where shell pipelines or process semantics are genuinely the interface.

## Recommended migration sequence

1. Capture Cadence characterization fixtures/tests for CLI parsing, environment composition, run numbering/reuse, snapshots, links, history, stage ranges, passthrough flags, and failure behavior; quarantine the broken installer from release paths.
2. Fix P0 data-loss/history/argument/process-creation issues with narrowly scoped compatibility tests, and define the current on-disk run/environment contract.
3. Add explicit backend selection with `cadence-flowtool` as the compatibility default; introduce the three-operation adapter and route existing Cadence behavior through it without changing layouts.
4. Move generic run allocation, locking, snapshots, links, and structured provenance into a small Python core while keeping the Cadence adapter and shell activation stable.
5. Replace executable host/process metadata with portable declarative definitions plus optional uncommitted host overlays; record resolved versions/paths in each run manifest.
6. Add an ORFS adapter using a pinned Docker/Podman image and backend-local checks; keep ORFS-native configuration and stages out of Cadence templates.
7. Establish the Ibex + ASAP7 + 1050 ps golden regression, verifying RTL-to-GDS completion, setup/hold closure, and route DRC results from machine-readable reports.
8. Migrate scaffolding and install/registry concepts incrementally once both backends exercise the boundary; retain shell shims and legacy file compatibility until deprecation is explicit.

## Open questions

- Must the first multibackend release preserve the exact current CLI and on-disk paths/symlink names, or only their semantics? This determines whether compatibility shims are mandatory.
- Should backend selection be an explicit environment field/flag, or inferred from the selected flow with an explicit override? Inference is convenient but can make manifests ambiguous.
- Is continuing an existing run the desired default long-term, or should runs become strictly immutable with continuation represented as a new child/attempt? Existing Cadence behavior currently permits reuse.

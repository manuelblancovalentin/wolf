#!/usr/bin/env bash
# Smoke test of skills/run-flow/SKILL.md: builds a throwaway local-path PDK
# package and a declarative environment in a scratch WOLF_HOME, then checks
# the plan/status commands and claims of the skill. Never starts a real
# vendor tool (no licence needed) -- only `wolf run --plan` (static
# resolution) and `wolf status` against a synthetic run directory. Writes
# only inside the scratch folder. Takes a few seconds.
#   bash skills/run-flow/smoke.sh
set -u
S=$(mktemp -d)
trap 'rm -rf "$S"' EXIT
fail=0
ok()   { printf 'ok   %s\n' "$1"; }
bad()  { printf 'FAIL %s\n' "$1"; fail=1; }
skip() { printf 'skip %s\n' "$1"; }

WOLF_BIN=$(command -v wolf 2>/dev/null) || { skip "wolf is not installed on this machine"; exit 0; }
WOLF_DIR=$(dirname "$WOLF_BIN")

# A fake `flowtool` shim on PATH -- wolf's own --plan only checks that
# *something* named flowtool resolves on PATH (shutil.which), never runs
# it, so this is enough to exercise --plan on a machine with no Cadence
# tools installed, without needing the real (licensed) one.
mkdir -p "$S/shim"
printf '#!/bin/sh\nexit 0\n' > "$S/shim/flowtool"
chmod +x "$S/shim/flowtool"

lm() {  # lm '<commands>' -- a clean shell, scratch HOME, isolated WOLF state
  env -i HOME="$S" USER="$(id -un)" PATH="$S/shim:$WOLF_DIR:/usr/bin:/bin" LC_ALL=C.UTF-8 bash --noprofile --norc -c "
    export WOLF_HOME='$S/WOLF_HOME' XDG_CONFIG_HOME='$S/XDG_CONFIG' XDG_DATA_HOME='$S/XDG_DATA' XDG_CACHE_HOME='$S/XDG_CACHE'
    $1" 2>&1
}

out=$(lm 'command -v wolf; wolf --version')
grep -q '^wolf ' <<<"$out" && ok "wolf is runnable with just its own directory on PATH" || { bad "wolf --version failed: $(head -3 <<<"$out")"; exit 1; }

# A throwaway local-path PDK package: every file an empty placeholder, never
# real library content.
NODE="$S/toy-root"; PROJ="$S/project"; REG="$S/registry"
mkdir -p "$NODE/lib" "$NODE/lef" "$NODE/gds" "$PROJ/inputs/hdl/demo" "$PROJ/inputs/constraints/demo" "$REG/pdk"
touch "$NODE/lib/9t_rvt_typical.lib" "$NODE/lef/9t_rvt.lef" "$NODE/gds/9t_rvt.gds"
cat > "$REG/pdk/toydemo.yaml" <<EOF
schema_version: 1
kind: pdk
name: toydemo
description: toy technology package for smoke-testing only
source: {type: local-path, root: $NODE, revision: unset}
metadata:
  technology:
    name: toydemo
    tracks:
      9T:
        vths:
          rvt:
            default_metal_stack: stackA
            lef: {stackA: [lef/9t_rvt.lef]}
            gds: [gds/9t_rvt.gds]
            timing: {corners: {typical: {libraries: [lib/9t_rvt_typical.lib]}}}
EOF
cat > "$PROJ/inputs/hdl/demo/demo.sv" <<'EOF'
module demo(input logic clk);
endmodule
EOF
echo '# placeholder' > "$PROJ/inputs/constraints/demo/demo.sdc"
cat > "$S/demo.yaml" <<EOF
schema: wolf.environment/v1
name: demo
design: {name: demo, sources: [{path: $PROJ/inputs/hdl/demo/demo.sv}]}
technology: {package: pdk/toydemo, track: 9T, vth: rvt}
flow: {backend: cadence-flowtool}
project: {root: $PROJ}
constraints: {files: [$PROJ/inputs/constraints/demo/demo.sdc]}
EOF

out=$(lm "wolf registry add toy-registry '$REG' --type local; wolf install pdk/toydemo; wolf env create demo --from '$S/demo.yaml'")
grep -q "Created declarative WOLF environment 'demo'" <<<"$out" && ok "the toy environment is created" || { bad "env create: $(tail -5 <<<"$out")"; exit 1; }

out=$(lm "wolf run --environment demo --plan")
expected_run_dir="$PROJ/workspace/demo/demo.toydemo/demo.1"
grep -qF "$expected_run_dir" <<<"$out" && ok "the run directory follows <project>/workspace/<design>/<design>.<process>/<design>.<N>" || bad "run directory not found or shaped differently: $(grep -i 'run director' <<<"$out")"

out=$(lm "wolf run --environment demo --plan -from syn_generic -to syn_opt")
grep -q 'From stage: syn_generic' <<<"$out" && grep -q 'To stage: syn_opt' <<<"$out" && ok "-from/-to accept real stage names" || bad "stage range not reflected in the plan: $(tail -5 <<<"$out")"

out=$(lm "wolf run --environment demo --plan -from not_a_real_stage")
grep -q "unsupported stage 'not_a_real_stage'; expected one of" <<<"$out" && ok "an unknown stage name fails with the exact list of real ones" || bad "unexpected error text: $(tail -3 <<<"$out")"

# A synthetic run directory -- wolf's own flow.status format, never a real
# tool's report -- to check the failed-stage status wording.
RUN="$S/fakerun"; mkdir -p "$RUN"
cat > "$RUN/wolf.resolved.yaml" <<'EOF'
backend: {name: cadence-flowtool}
environment: demo
EOF
printf '{status complete time 1732000000 errors {} steps_run {str block.synthesis.syn_generic.block_start}}\n{status failed time 1732000100 errors {x} steps_run {str block.synthesis.syn_map.block_start}}\n' > "$RUN/flow.status"
out=$(lm "wolf status --run '$RUN'")
grep -q 'Status: failed' <<<"$out" && grep -q 'Failed stage: syn_map' <<<"$out" && ok "a failed run's status names the failed stage" || bad "status text: $(tail -8 <<<"$out")"

out=$(lm "wolf status --run '$RUN' --json")
grep -q '"schema": "wolf.status/v1"' <<<"$out" && ok "wolf status --json emits wolf.status/v1" || bad "status json schema missing: $(head -3 <<<"$out")"

[ "$fail" = 0 ] && echo "ALL OK" || { echo "FAILURES"; exit 1; }

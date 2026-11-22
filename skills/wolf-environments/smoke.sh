#!/usr/bin/env bash
# Smoke test of skills/wolf-environments/SKILL.md: builds a throwaway
# declarative environment in a scratch WOLF_HOME and checks the read-only
# listing/describing commands. Writes only inside the scratch folder.
# Takes a few seconds.
#   bash skills/wolf-environments/smoke.sh
set -u
S=$(mktemp -d)
trap 'rm -rf "$S"' EXIT
fail=0
ok()   { printf 'ok   %s\n' "$1"; }
bad()  { printf 'FAIL %s\n' "$1"; fail=1; }
skip() { printf 'skip %s\n' "$1"; }

WOLF_BIN=$(command -v wolf 2>/dev/null) || { skip "wolf is not installed on this machine"; exit 0; }
WOLF_DIR=$(dirname "$WOLF_BIN")

mkdir -p "$S/shim"
printf '#!/bin/sh\nexit 0\n' > "$S/shim/flowtool"
chmod +x "$S/shim/flowtool"

lm() {
  env -i HOME="$S" USER="$(id -un)" PATH="$S/shim:$WOLF_DIR:/usr/bin:/bin" LC_ALL=C.UTF-8 bash --noprofile --norc -c "
    export WOLF_HOME='$S/WOLF_HOME' XDG_CONFIG_HOME='$S/XDG_CONFIG' XDG_DATA_HOME='$S/XDG_DATA' XDG_CACHE_HOME='$S/XDG_CACHE'
    $1" 2>&1
}

NODE="$S/toy-root"; PROJ="$S/project"; REG="$S/registry"
mkdir -p "$NODE/lib" "$NODE/lef" "$NODE/gds" "$PROJ/inputs/hdl/demo" "$PROJ/inputs/constraints/demo" "$REG/pdk"
touch "$NODE/lib/9t_rvt_typical.lib" "$NODE/lef/9t_rvt.lef" "$NODE/gds/9t_rvt.gds"
cat > "$REG/pdk/toydemo.yaml" <<EOF
schema_version: 1
kind: pdk
name: toydemo
description: toy
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
echo 'module demo(input logic clk); endmodule' > "$PROJ/inputs/hdl/demo/demo.sv"
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
grep -q "Created declarative WOLF environment 'demo'" <<<"$out" || { bad "could not create the toy environment: $(tail -5 <<<"$out")"; exit 1; }

out=$(lm "wolf env list")
grep -q 'demo' <<<"$out" && ok "wolf env list shows the environment" || bad "env list: $(tail -3 <<<"$out")"

out=$(lm "wolf info demo")
grep -q 'Format: declarative-v1' <<<"$out" && grep -q 'Technology package: pdk/toydemo' <<<"$out" \
  && ok "wolf info shows format and technology package" || bad "wolf info: $(tail -10 <<<"$out")"

out=$(lm "wolf env describe demo --json")
grep -q '"schema": "wolf.describe/v1"' <<<"$out" && ok "wolf env describe --json emits wolf.describe/v1" || bad "describe json: $(tail -5 <<<"$out")"

out=$(lm "wolf backend list")
grep -q 'cadence-flowtool' <<<"$out" && grep -q 'orfs' <<<"$out" && ok "wolf backend list shows both backends" || bad "backend list: $(tail -5 <<<"$out")"

out=$(lm "wolf backend info cadence-flowtool")
grep -q 'flowtool: available' <<<"$out" && ok "wolf backend info reports flowtool availability" || bad "backend info: $(tail -8 <<<"$out")"

out=$(lm "wolf flow snapshot demo")
[ -d "$PROJ/inputs/flows/demo" ] && ok "wolf flow snapshot writes under the project's inputs/flows/" || bad "flow snapshot: $(tail -5 <<<"$out"); no inputs/flows/demo"

[ "$fail" = 0 ] && echo "ALL OK" || { echo "FAILURES"; exit 1; }

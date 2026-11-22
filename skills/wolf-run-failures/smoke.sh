#!/usr/bin/env bash
# Smoke test of skills/wolf-run-failures/SKILL.md: provokes each failure the
# skill documents against a throwaway environment in a scratch WOLF_HOME
# and checks the exact message. Writes only inside the scratch folder.
# Takes a few seconds.
#   bash skills/wolf-run-failures/smoke.sh
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

lm() {  # lm '<commands>' [noflowtool] -- second arg "noflowtool" leaves the shim off PATH
  local path="$S/shim:$WOLF_DIR:/usr/bin:/bin"
  [ "${2-}" = "noflowtool" ] && path="$WOLF_DIR:/usr/bin:/bin"
  env -i HOME="$S" USER="$(id -un)" PATH="$path" LC_ALL=C.UTF-8 bash --noprofile --norc -c "
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
cat > "$S/notech.yaml" <<EOF
schema: wolf.environment/v1
name: notech
design: {name: demo, sources: [{path: $PROJ/inputs/hdl/demo/demo.sv}]}
flow: {backend: cadence-flowtool}
project: {root: $PROJ}
EOF

lm "wolf registry add toy-registry '$REG' --type local; wolf install pdk/toydemo; wolf env create demo --from '$S/demo.yaml'; wolf env create notech --from '$S/notech.yaml'" >/dev/null

out=$(lm "wolf run --environment demo --plan -from not_a_real_stage")
grep -q "unsupported stage 'not_a_real_stage'; expected one of" <<<"$out" && ok "bad stage name: exact message" || bad "stage message: $(tail -3 <<<"$out")"

out=$(lm "wolf run --environment bogus-env --plan")
grep -q "WOLF environment 'bogus-env' does not exist" <<<"$out" && ok "unknown environment: exact message" || bad "unknown env message: $(tail -3 <<<"$out")"

out=$(lm "wolf run --environment notech --plan")
grep -q "unresolved required field: technology" <<<"$out" && ok "missing technology: exact message" || bad "missing field message: $(tail -3 <<<"$out")"

cat > "$S/badpkg.yaml" <<EOF
schema: wolf.environment/v1
name: badpkg
design: {name: demo, sources: [{path: $PROJ/inputs/hdl/demo/demo.sv}]}
technology: {package: pdk/doesnotexist, track: 9T, vth: rvt}
flow: {backend: cadence-flowtool}
project: {root: $PROJ}
EOF
lm "wolf env create badpkg --from '$S/badpkg.yaml'" >/dev/null
out=$(lm "wolf run --environment badpkg --plan")
grep -q "unknown WOLF package 'pdk/doesnotexist'; available packages:" <<<"$out" && ok "unknown package: exact message" || bad "unknown package message: $(tail -3 <<<"$out")"

out=$(lm "wolf run --environment demo --plan" noflowtool)
grep -q 'flowtool: unavailable' <<<"$out" && ok "no flowtool on PATH: exact message" || bad "flowtool message: $(tail -5 <<<"$out")"

[ "$fail" = 0 ] && echo "ALL OK" || { echo "FAILURES"; exit 1; }

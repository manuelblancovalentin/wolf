#!/usr/bin/env bash
# Smoke test of skills/new-environment/SKILL.md: creates, clones, edits and
# auto-setups a throwaway declarative environment in a scratch WOLF_HOME.
# Writes only inside the scratch folder. Takes a few seconds.
#   bash skills/new-environment/smoke.sh
set -u
S=$(mktemp -d)
trap 'rm -rf "$S"' EXIT
fail=0
ok()   { printf 'ok   %s\n' "$1"; }
bad()  { printf 'FAIL %s\n' "$1"; fail=1; }
skip() { printf 'skip %s\n' "$1"; }

WOLF_BIN=$(command -v wolf 2>/dev/null) || { skip "wolf is not installed on this machine"; exit 0; }
WOLF_DIR=$(dirname "$WOLF_BIN")

lm() {
  env -i HOME="$S" USER="$(id -un)" PATH="$WOLF_DIR:/usr/bin:/bin" LC_ALL=C.UTF-8 bash --noprofile --norc -c "
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
grep -q "Created declarative WOLF environment 'demo'" <<<"$out" && ok "wolf env create makes the environment" || { bad "env create: $(tail -5 <<<"$out")"; exit 1; }

out=$(lm "wolf env clone demo demo2")
grep -qi 'clon' <<<"$out" && [ -d "$S/WOLF_HOME/envs/demo2" ] && ok "wolf env clone makes an independent copy" || bad "env clone: $(tail -5 <<<"$out")"

out=$(lm "wolf env set demo2 active_views '{\"setup\": [\"func_setup\"], \"hold\": [\"func_hold\"]}'")
setup_file="$PROJ/inputs/env/demo/setup.demo.yaml"
grep -q 'active_views' <<<"$out" && [ -f "$setup_file" ] && grep -q 'active_views' "$setup_file" \
  && ok "wolf env set writes the design-level setup.<design>.yaml" || bad "env set: $(tail -5 <<<"$out")"

out=$(lm "wolf env unset demo2 active_views")
! grep -q 'active_views' "$setup_file" 2>/dev/null && ok "wolf env unset removes the key again" || bad "env unset left active_views: $(cat "$setup_file" 2>/dev/null)"

out=$(lm "wolf env auto-setup demo")
[ -d "$PROJ/inputs/hdl/demo" ] && [ -d "$PROJ/workspace" ] && [ -d "$PROJ/outputs" ] && [ -d "$PROJ/inputs/lib/lef" ] \
  && ok "wolf env auto-setup scaffolds inputs/outputs/workspace" || bad "auto-setup: $(tail -8 <<<"$out")"

[ "$fail" = 0 ] && echo "ALL OK" || { echo "FAILURES"; exit 1; }

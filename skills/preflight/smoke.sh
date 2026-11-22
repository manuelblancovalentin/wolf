#!/usr/bin/env bash
# Smoke test of skills/preflight/SKILL.md: checks wolf doctor and wolf
# backend info in a scratch WOLF_HOME. Writes only inside the scratch
# folder. Takes a few seconds.
#   bash skills/preflight/smoke.sh
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

out=$(lm "wolf doctor")
grep -q 'WOLF version:' <<<"$out" && grep -q 'Python:' <<<"$out" && ok "wolf doctor reports WOLF and Python versions" || bad "doctor: $(tail -10 <<<"$out")"

out=$(lm "wolf backend info cadence-flowtool")
grep -qE 'flowtool: (available|unavailable)' <<<"$out" && ok "wolf backend info reports flowtool availability either way" || bad "backend info cadence-flowtool: $(tail -8 <<<"$out")"

out=$(lm "wolf backend info orfs")
grep -qE 'ORFS_ROOT: (available|unavailable)' <<<"$out" && ok "wolf backend info reports ORFS_ROOT either way" || bad "backend info orfs: $(tail -10 <<<"$out")"

[ "$fail" = 0 ] && echo "ALL OK" || { echo "FAILURES"; exit 1; }

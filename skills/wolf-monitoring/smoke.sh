#!/usr/bin/env bash
# Smoke test of skills/wolf-monitoring/SKILL.md: checks the stalled-stage
# detection and the live-process line against a synthetic run directory
# (wolf's own flow.status format, never a real tool's report) and a real
# short-lived subprocess. Writes only inside the scratch folder. Takes a
# few seconds.
#   bash skills/wolf-monitoring/smoke.sh
set -u
S=$(mktemp -d)
trap 'rm -rf "$S"' EXIT
fail=0
ok()   { printf 'ok   %s\n' "$1"; }
bad()  { printf 'FAIL %s\n' "$1"; fail=1; }
skip() { printf 'skip %s\n' "$1"; }

# This checks the `stalled` status and the process line this repository's
# own checkout adds (see src/wolf/process_watch.py). An installed `wolf`
# elsewhere on this machine may predate this feature, so this runs the
# checkout directly (PYTHONPATH) rather than whatever `wolf` is on PATH.
REPO_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../src" && pwd)"
[ -f "$REPO_SRC/wolf/cli.py" ] || { skip "this repository's own src/wolf checkout was not found"; exit 0; }

lm() {
  env -i HOME="$S" USER="$(id -un)" PATH=/usr/bin:/bin PYTHONPATH="$REPO_SRC" LC_ALL=C.UTF-8 bash --noprofile --norc -c "
    wolf() { python3 -m wolf.cli \"\$@\"; }
    export WOLF_HOME='$S/WOLF_HOME' XDG_CONFIG_HOME='$S/XDG_CONFIG' XDG_DATA_HOME='$S/XDG_DATA' XDG_CACHE_HOME='$S/XDG_CACHE'
    $1" 2>&1
}

RUN="$S/fakerun"
mkdir -p "$RUN"
cat > "$RUN/wolf.resolved.yaml" <<'EOF'
backend: {name: cadence-flowtool}
environment: demo
EOF
printf '{status complete time 1732000000 errors {} steps_run {str block.synthesis.syn_generic.block_start}}\n{status running time 1732000100 errors {} steps_run {str block.synthesis.syn_map.block_start}}\n' > "$RUN/flow.status"

out=$(lm "wolf status --run '$RUN'")
grep -q 'Stalled stage: syn_generic' <<<"$out" && ok "a running stage with no process is reported stalled" || bad "stalled text: $(tail -14 <<<"$out")"
grep -q 'syn_map.*stalled' <<<"$out" && ok "both affected stages show as stalled in the table" || bad "stage table: $(tail -14 <<<"$out")"
grep -q 'No process: nothing of yours is working' <<<"$out" && ok "the Processes section says so when nothing is alive" || bad "no-process line: $(tail -3 <<<"$out")"

out=$(lm "wolf status --run '$RUN' --json")
grep -q '"stalled_stage": "syn_generic"' <<<"$out" && ok "wolf status --json reports stalled_stage" || bad "json: $(tail -8 <<<"$out")"

# Now with a real process genuinely working in the run directory: the
# stage must stay "running", and the Processes section must name it.
sleep 5 &
sleep_pid=$!
(cd "$RUN" && exec sleep 5) &
worker_pid=$!
sleep 0.3
out=$(lm "wolf status --run '$RUN'")
kill "$sleep_pid" "$worker_pid" 2>/dev/null
wait "$sleep_pid" "$worker_pid" 2>/dev/null
grep -q 'Stalled stage' <<<"$out" && bad "a real process in the run directory was still reported stalled: $(tail -12 <<<"$out")" \
  || ok "a run with a real process working in it is never reported stalled"
grep -q "pid $worker_pid" <<<"$out" && ok "the Processes section names the real pid" || bad "process line missing: $(tail -6 <<<"$out")"

[ "$fail" = 0 ] && echo "ALL OK" || { echo "FAILURES"; exit 1; }

#!/usr/bin/env bash
# Run the contributor gates, and SAY WHAT WAS NOT RUN.
#
# WHY THIS EXISTS. Until 2026-08-28 there were 27 gates and no runner -- and a
# count in a comment goes stale the moment one is added, so the roster below is
# discovered from gates/*.py and the live count is printed, never asserted. CI cannot
# help -- ci.yml states it: the gates need a real X4 install. So they ran when
# someone remembered, which makes every gate's coverage a matter of chance rather
# than of process. A gate nobody runs is indistinguishable from a gate that passes.
#
# The contract this inherits from the tools themselves: a run that examined less
# than everything must SAY SO. Skipped gates are named, with the reason, and the
# buckets sum to the population -- never a bare "all green".
#
#   scripts/run-gates.sh            quick gates only (seconds to ~1 min each)
#   scripts/run-gates.sh --all      everything, including the ~55 min sweep
#   scripts/run-gates.sh --list     show the roster and exit
#
# Exit: 0 all attempted gates passed · 1 a gate failed · 2 could not run any
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

# Runtimes from gates/README.md, MEASURED on the reference machine.
SLOW="corpus_sweep perf_guard xsd_fast_parity schema_sweep noop_audit regress stress_sweep update_corpus"
# Rewrites source in place; must never run beside anything that reads the tree.
MUTATING="mutation_probe"

mode="quick"
case "${1:-}" in
  --all)  mode="all" ;;
  --list) mode="list" ;;
  "")     ;;
  *) echo "unknown option: $1" >&2; exit 2 ;;
esac

all_gates=()
for f in gates/*.py; do
  b=$(basename "$f" .py)
  case "$b" in __init__|_env) continue ;; esac
  all_gates+=("$b")
done
[ ${#all_gates[@]} -eq 0 ] && { echo "no gates found under gates/" >&2; exit 2; }

if [ "$mode" = "list" ]; then
  printf '%s\n' "${all_gates[@]}"; exit 0
fi

run=(); skip_slow=(); skip_mut=()
for g in "${all_gates[@]}"; do
  if [[ " $MUTATING " == *" $g "* ]]; then skip_mut+=("$g"); continue; fi
  if [ "$mode" = "quick" ] && [[ " $SLOW " == *" $g "* ]]; then skip_slow+=("$g"); continue; fi
  run+=("$g")
done

echo "GATE RUN — mode=$mode — ${#all_gates[@]} gate(s) known"
echo "=================================================================="
pass=(); fail=(); cannot=()
for g in "${run[@]}"; do
  out=$(uv run python "gates/$g.py" 2>&1); rc=$?
  case $rc in
    0) pass+=("$g");   printf '  ok      %-26s\n' "$g" ;;
    2) cannot+=("$g"); printf '  CANNOT  %-26s %s\n' "$g" "$(echo "$out" | tail -1 | cut -c1-70)" ;;
    *) fail+=("$g");   printf '  FAIL    %-26s rc=%s\n' "$g" "$rc"
       echo "$out" | tail -6 | sed 's/^/            /' ;;
  esac
done

echo "=================================================================="
printf 'attempted %d   passed %d   failed %d   could-not-run %d\n' \
       "${#run[@]}" "${#pass[@]}" "${#fail[@]}" "${#cannot[@]}"
total=$(( ${#run[@]} + ${#skip_slow[@]} + ${#skip_mut[@]} ))
printf 'NOT ATTEMPTED %d  (buckets sum to %d of %d)\n' \
       "$(( ${#skip_slow[@]} + ${#skip_mut[@]} ))" "$total" "${#all_gates[@]}"
[ ${#skip_slow[@]} -gt 0 ] && echo "  slow, use --all: ${skip_slow[*]}"
[ ${#skip_mut[@]}  -gt 0 ] && echo "  MUTATING, run alone and announce it: ${skip_mut[*]}"
[ ${#cannot[@]}    -gt 0 ] && echo "  could not run (missing baseline/fixture): ${cannot[*]}"

[ ${#fail[@]} -gt 0 ] && exit 1
[ ${#pass[@]} -eq 0 ] && { echo "NOTHING PASSED — this is not a green run." >&2; exit 2; }
exit 0

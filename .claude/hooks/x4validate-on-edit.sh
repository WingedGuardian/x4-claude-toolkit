#!/bin/bash
# PostToolUse (Edit|Write): advisory x4validate on a mod's diff-XML edits.
# Non-blocking — surfaces unmatched sel= findings as additionalContext. Never denies.
JQ="${JQ:-jq}"
UV="${UV:-uv}"
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/_x4-env.sh"
X4V="${X4V:-$X4_TOOLKIT/tools/x4validate}"

INPUT=$(x4_hook_input)
# Advisory only, so an absent payload must NOT prompt -- it exits below.
# Recurrence is caught statically by test-hooks.sh, which fails if any
# hook reads /dev/stdin again.
# x4_field, not a bare jq call. This line read through jq ALONE, so with jq missing
# it produced an empty FP and the next line exited 0 -- which made the python fallback
# added further down (for the same reason, in the same chain) structurally
# UNREACHABLE. MEASURED 2026-09-05 with `bash -x` and JQ=/nonexistent: `FP=` then
# `exit 0`, the whole hook inert. `_x4-env.sh` ships x4_field for exactly this, and
# documents the identical bug for search-scope.sh at its own definition: teach EVERY
# step of the chain, not the last one.
#
# It also removes a second interpreter probe further down that disagreed with the
# shared one: `x4_python` REFUSES when $X4_PYTHON is set to something missing, while
# the local loop silently fell through to python3 -- "a guard that runs under an
# interpreter the operator did not choose is a guard nobody configured".
FP=$(x4_field "$INPUT" tool_input.file_path)
[ -z "$FP" ] && exit 0

# Only XML files, and never the read-only reference tree.
echo "$FP" | grep -qiE '\.xml$' || exit 0
x4_under "$FP" "$X4_REFERENCE" && exit 0

F="${FP//\\//}"                  # normalize backslashes for bash
[ -f "$F" ] || exit 0
grep -qi '<diff' "$F" 2>/dev/null || exit 0   # only diff patches

# Mod root = nearest ancestor with content.xml (so this works wherever mods live)
D=$(dirname "$F"); ROOT=""
for _ in $(seq 1 25); do
  [ -f "$D/content.xml" ] && { ROOT="$D"; break; }
  ND=$(dirname "$D"); [ "$ND" = "$D" ] && break; D="$ND"
done
[ -z "$ROOT" ] && exit 0

# TIER SELECTION.  A file at <mod>/extensions/<target>/... is a CROSS-MOD patch, and
# Tier A builds base+DLC only -- so it reports "no base game file ... can never apply"
# for EVERY such file.  MEASURED 2026-08-28 on a real cross-mod overlay: Tier A
# error_count=1, Tier B error_count=0, same correct file.  Left on Tier A this hook
# cries wolf on every edit to a cross-mod overlay and trains the reader to ignore it,
# which is worse than not running at all.
REL="${F#"$ROOT"/}"
TIER=""
case "$REL" in
  extensions/*) TIER="--tier b" ;;
esac

OUT=$(cd "$X4V" && "$UV" run --python 3.13 x4validate "$ROOT" --file "$F" $TIER --json 2>/dev/null)
[ -z "$OUT" ] && exit 0
# Both the PARSE and the EMIT need a renderer. With jq missing this block used to go
# quiet -- ERRS came back empty, `${ERRS:-0}` made it 0, and a real validation failure
# produced no advisory at all. Python is already a hard prerequisite here (the line above
# runs x4validate through uv), so it is always the right fallback.
if printf '%s' '{}' | "$JQ" -e . >/dev/null 2>&1; then
  ERRS=$(printf '%s' "$OUT" | "$JQ" -r '.error_count // 0' 2>/dev/null)
  MSG=$(printf '%s' "$OUT" | "$JQ" -r '.findings[] | "  [\(.severity)] \(.message) (\(.vpath):\(.line))"' 2>/dev/null)
else
  PY="$(x4_python)"      # ONE implementation, shared with every other hook
  if [ -n "$PY" ]; then
    ERRS=$(X4_OUT="$OUT" "$PY" -c 'import json, os, sys
try: sys.stdout.write(str(json.loads(os.environ["X4_OUT"]).get("error_count") or 0))
except Exception: sys.stdout.write("0")' 2>/dev/null)
    MSG=$(X4_OUT="$OUT" "$PY" -c 'import json, os, sys
try: f = json.loads(os.environ["X4_OUT"]).get("findings") or []
except Exception: f = []
sys.stdout.write("\n".join("  [%s] %s (%s:%s)" % (x.get("severity"), x.get("message"), x.get("vpath"), x.get("line")) for x in f))' 2>/dev/null)
  else
    ERRS=0; MSG=""
  fi
fi
if [ "${ERRS:-0}" -gt 0 ]; then
  x4_advise "x4validate (advisory${TIER:+, tier B}) flagged this edit:
$MSG" PostToolUse
fi
exit 0

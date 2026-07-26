#!/bin/bash
# PostToolUse (Edit|Write): advisory x4validate on a mod's diff-XML edits.
# Non-blocking — surfaces unmatched sel= findings as additionalContext. Never denies.
JQ="${JQ:-jq}"
UV="${UV:-uv}"
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/_x4-env.sh"
X4V="${X4V:-$X4_TOOLKIT/tools/x4validate}"

INPUT=$(cat /dev/stdin)
FP=$(echo "$INPUT" | "$JQ" -r '.tool_input.file_path // empty')
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

OUT=$(cd "$X4V" && "$UV" run --python 3.13 x4validate "$ROOT" --file "$F" --json 2>/dev/null)
[ -z "$OUT" ] && exit 0
ERRS=$(echo "$OUT" | "$JQ" -r '.error_count // 0' 2>/dev/null)
if [ "${ERRS:-0}" -gt 0 ]; then
  MSG=$(echo "$OUT" | "$JQ" -r '.findings[] | "  [\(.severity)] \(.message) (\(.vpath):\(.line))"')
  "$JQ" -n --arg c "x4validate (advisory) flagged this edit:
$MSG" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$c}}'
fi
exit 0

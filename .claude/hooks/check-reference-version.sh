#!/bin/bash
# SessionStart: warn if the game build differs from the build reference\ was unpacked from.
# Plain stdout becomes session context for SessionStart hooks.
ACF="/c/Program Files (x86)/Steam/steamapps/appmanifest_392160.acf"
STORE="$CLAUDE_PROJECT_DIR/.claude/.reference-buildid"
[ -f "$ACF" ] || exit 0
CUR=$(grep -i '"buildid"' "$ACF" | head -1 | grep -oE '[0-9]+' | tail -1)
[ -z "$CUR" ] && exit 0
STORED=""
[ -f "$STORE" ] && STORED=$(tr -d '[:space:]' < "$STORE")
if [ -n "$STORED" ] && [ "$STORED" != "$CUR" ]; then
  echo "[x4 stale-reference] reference\\ was unpacked from build $STORED but the game is now build $CUR. Re-unpack reference\\ (remove the .unpacked-and-locked sentinel) before trusting line numbers in deep fixes, and update .claude/.reference-buildid afterward."
fi
exit 0

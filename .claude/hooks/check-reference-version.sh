#!/bin/bash
# SessionStart: warn if the game build differs from the build reference/ was unpacked from.
# Plain stdout becomes session context for SessionStart hooks. Cross-platform Steam detection.
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/_x4-env.sh"

STORE="$X4_TOOLKIT/.claude/.reference-buildid"
ACF="${X4_APPMANIFEST:-}"                      # may already be derived from X4_GAME in _x4-env.sh
if [ -z "$ACF" ] || [ ! -f "$ACF" ]; then
  for c in \
    "$HOME/.steam/steam/steamapps/appmanifest_392160.acf" \
    "$HOME/.local/share/Steam/steamapps/appmanifest_392160.acf" \
    "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/appmanifest_392160.acf" \
    "$HOME/Library/Application Support/Steam/steamapps/appmanifest_392160.acf" \
    "/c/Program Files (x86)/Steam/steamapps/appmanifest_392160.acf" \
    "/mnt/c/Program Files (x86)/Steam/steamapps/appmanifest_392160.acf"; do
    [ -f "$c" ] && { ACF="$c"; break; }
  done
fi
[ -f "$ACF" ] || exit 0

CUR=$(grep -i '"buildid"' "$ACF" | head -1 | grep -oE '[0-9]+' | tail -1)
[ -z "$CUR" ] && exit 0
STORED=""
[ -f "$STORE" ] && STORED=$(tr -d '[:space:]' < "$STORE")
if [ -n "$STORED" ] && [ "$STORED" != "$CUR" ]; then
  echo "[x4 stale-reference] reference/ was unpacked from build $STORED but the game is now build $CUR. Re-unpack (remove reference/.unpacked-and-locked, then run bin/unpack-reference.sh) before trusting line numbers in deep fixes; update .claude/.reference-buildid afterward."
fi
exit 0

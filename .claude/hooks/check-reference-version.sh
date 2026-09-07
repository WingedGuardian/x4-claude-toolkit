#!/bin/bash
# SessionStart: warn if the game build differs from the build reference/ was unpacked from.
# Plain stdout becomes session context for SessionStart hooks. Cross-platform Steam detection.
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/_x4-env.sh"

# WHICH marker is authoritative, and it is not the obvious one.
#
# `reference/.unpacked-and-locked` is written BY the unpack, INTO the tree it
# describes, and names the build in its text. It therefore cannot drift from its
# subject: copy the tree, the marker comes with it; delete the marker, the tree is
# unlocked and gets re-unpacked. `$X4_TOOLKIT/.claude/.reference-buildid` is a
# DETACHED file that has to be updated by hand as a separate step, which is exactly
# the step that gets missed.
#
# MEASURED 2026-09-06: it had been missed. The two detached copies disagreed --
# <toolkit>/.claude said 23524486 and the game-root one said 23660954 -- while the
# sentinel and the live game both said 23660954. This hook read the stale one, so it
# announced a stale reference/ AT EVERY SESSION START while reference/ was current,
# and the "fix" it recommended is a ~60 GB re-unpack. A banner that is always wrong
# trains you to ignore the banner, which is the failure mode _freshness.py is written
# to prevent; here it was costing a real re-unpack recommendation every session.
#
# Confirmed the tree really had not moved: 1 of 510,711 files under reference/ has an
# mtime after the schema baseline, and it IS the sentinel -- XRCatTool preserves the
# catalogs' timestamps, so a re-run of bin/unpack-reference.sh rewrites the marker
# and changes nothing else. An mtime on that file is evidence about the SCRIPT.
#
# So: sentinel first, detached file only as a fallback for a tree that predates it.
SENTINEL="$X4_REFERENCE/.unpacked-and-locked"
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
SRC=""
if [ -f "$SENTINEL" ]; then
  # "... (steam buildid 23660954) on 2026-06-22 ..." -- take the number after the word.
  STORED=$(grep -oE 'buildid[^0-9]*[0-9]+' "$SENTINEL" | head -1 | grep -oE '[0-9]+' | tail -1)
  [ -n "$STORED" ] && SRC="reference/.unpacked-and-locked"
fi
if [ -z "$STORED" ] && [ -f "$STORE" ]; then
  STORED=$(tr -d '[:space:]' < "$STORE")
  [ -n "$STORED" ] && SRC=".claude/.reference-buildid"
fi
if [ -n "$STORED" ] && [ "$STORED" != "$CUR" ]; then
  echo "[x4 stale-reference] reference/ was unpacked from build $STORED (per $SRC) but the game is now build $CUR. Re-unpack (remove reference/.unpacked-and-locked, then run bin/unpack-reference.sh) before trusting line numbers in deep fixes; update .claude/.reference-buildid afterward so the detached copy stops disagreeing."
fi
exit 0

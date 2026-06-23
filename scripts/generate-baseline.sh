#!/bin/bash
# Capture a known-good X4 baseline to diff against later (after scaling up the mod list,
# or after a game update). Records: game version, every physically-installed mod folder
# with a rollup SHA256, the live content.xml/config.xml, and a NORMALIZED debug.txt error
# fingerprint (timestamps + volatile ids masked) so a future run diffs cleanly.
#
# Usage:
#   GAME_DIR=".../X4 Foundations" PROFILE_DIR=".../Documents/Egosoft/X4/<id>" \
#     bash scripts/generate-baseline.sh
#
# Defaults assume you run it from the game root and pass PROFILE_DIR explicitly.

set -euo pipefail

GAME_DIR="${GAME_DIR:-$(pwd)}"
PROFILE_DIR="${PROFILE_DIR:-}"
STAMP="${STAMP:-baseline}"   # pass a date, e.g. STAMP=2026-06-23, to name the folder
OUT="$GAME_DIR/.claude/backups/known-good-${STAMP}"

if [ -z "$PROFILE_DIR" ] || [ ! -d "$PROFILE_DIR" ]; then
  echo "ERROR: set PROFILE_DIR to your active X4 user profile (Documents/Egosoft/X4/<id>)."
  echo "Tip: the active profile has the newest debug.txt / save timestamps."
  exit 1
fi

mkdir -p "$OUT"
echo "Game dir:    $GAME_DIR"
echo "Profile dir: $PROFILE_DIR"
echo "Output:      $OUT"
echo

# --- game version ---
VER="$(cat "$GAME_DIR/version.dat" 2>/dev/null || echo unknown)"
echo "Game version (version.dat): $VER"

# --- installed mods = source of truth is the extensions/ FOLDER, not content.xml ---
# (content.xml routinely lists dead/unsubscribed entries the engine ignores.)
EXT="$GAME_DIR/extensions"
TSV="$OUT/installed-mods.tsv"
printf "folder\tfiles\tbytes\trollup_sha256\n" > "$TSV"
if [ -d "$EXT" ]; then
  for d in "$EXT"/*/; do
    name="$(basename "$d")"
    case "$name" in ego_dlc_*) continue;; esac   # skip official DLC
    cnt=$(find "$d" -type f | wc -l | tr -d ' ')
    bytes=$(find "$d" -type f -printf "%s\n" 2>/dev/null | awk '{s+=$1} END{print s+0}')
    roll=$(find "$d" -type f -exec sha256sum {} \; 2>/dev/null | sort | sha256sum | cut -d' ' -f1)
    printf "%s\t%s\t%s\t%s\n" "$name" "$cnt" "$bytes" "$roll" >> "$TSV"
    echo "  mod: $name (files=$cnt, rollup=${roll:0:12}…)"
  done
fi

# --- copy live artifacts verbatim ---
for f in content.xml config.xml debug.txt; do
  [ -f "$PROFILE_DIR/$f" ] && cp "$PROFILE_DIR/$f" "$OUT/$f"
done

# --- normalized, diffable error fingerprint from debug.txt ---
if [ -f "$PROFILE_DIR/debug.txt" ]; then
  {
    echo "# Known-good error fingerprint — game version $VER"
    echo "# Normalized: timestamps + hex ids + player ids masked, sorted by frequency."
    echo "# Later: regenerate and 'diff' against this; only NEW signatures are suspects."
    echo "#----------------------------------------------------------------------"
    grep -a "=ERROR=" "$PROFILE_DIR/debug.txt" \
      | sed -E 's/^\[=ERROR=\] [0-9]+\.[0-9]+ //' \
      | sed -E 's/0x[0-9a-fA-F]+/0xADDR/g; s/inst:[0-9a-fA-F]+/inst:ID/g; s/player_[0-9]+/player_ID/g; s/<[0-9a-fA-F]+>/<ID>/g' \
      | sort | uniq -c | sort -rn
  } > "$OUT/error-fingerprint.txt"
  N=$(grep -ac "=ERROR=" "$PROFILE_DIR/debug.txt" || true)
  echo "  error fingerprint: $N [=ERROR=] lines captured"
fi

echo
echo "Baseline written to: $OUT"
echo "Re-run after scaling up the mod list, then diff error-fingerprint.txt and re-hash mods vs installed-mods.tsv."

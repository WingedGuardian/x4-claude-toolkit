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

# Honour the toolkit's own config: .claude/x4-paths.env (X4_GAME / X4_PROFILE),
# then this script's legacy GAME_DIR / PROFILE_DIR names, then CWD as last resort.
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
[ -f "$_here/.claude/x4-paths.env" ] && . "$_here/.claude/x4-paths.env"
# Never $(pwd). A baseline is a RECOVERY artifact: silently taking it from
# whatever directory you happened to stand in writes a "known-good" snapshot of
# the wrong game install, and you find out at the moment you need to restore.
# Refusing to guess is the same rule the Python side follows.
GAME_DIR="${GAME_DIR:-${X4_GAME:-}}"
PROFILE_DIR="${PROFILE_DIR:-${X4_PROFILE:-}}"

if [ -z "$GAME_DIR" ] || [ ! -d "$GAME_DIR" ]; then
  echo "ERROR: set GAME_DIR (or X4_GAME) to your X4 install — the folder holding 01.cat..09.cat." >&2
  echo "       Configure it in .claude/x4-paths.env, or pass GAME_DIR=... on the command line." >&2
  exit 2
fi
STAMP="${STAMP:-baseline}"   # pass a date, e.g. STAMP=2026-06-23, to name the folder
OUT="$GAME_DIR/.claude/backups/known-good-${STAMP}"

# Same condition as the GAME_DIR check above, so the same answer: rc 2, on stderr.
# "Exit 2 == this toolkit is not configured, everywhere in the toolkit. Kept distinct
# from 1 (it ran and something was wrong) so a caller can tell 'set X4_GAME' from 'the
# unpack failed' -- they need opposite responses." (bin/unpack-reference.sh)
if [ -z "$PROFILE_DIR" ] || [ ! -d "$PROFILE_DIR" ]; then
  echo "ERROR: set PROFILE_DIR (or X4_PROFILE) to your active X4 user profile (Documents/Egosoft/X4/<id>)." >&2
  echo "       Configure it in .claude/x4-paths.env, or pass PROFILE_DIR=... on the command line." >&2
  echo "       Tip: the active profile has the newest debug.txt / save timestamps." >&2
  exit 2
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
#
# A BASELINE THAT RECORDS NOTHING MUST NOT REPORT SUCCESS. This walk used to sit
# inside a bare `if [ -d "$EXT" ]`, so a missing extensions/ wrote a HEADER-ONLY
# TSV and the script still printed "Baseline written to: ..." and exited 0.
# MEASURED in a sandbox: zero mods recorded, no config.xml, no error fingerprint,
# and not one word about any of it. This file's own comment above already says a
# baseline is a RECOVERY artifact and that you find out at the moment you need to
# restore -- that argument was applied to the game DIRECTORY and not to its
# contents.
#
# An existing but EMPTY extensions/ stays accepted: no mods is a real state a
# player can be in. A MISSING one means we are looking at the wrong place.
EXT="$GAME_DIR/extensions"
if [ ! -d "$EXT" ]; then
  echo "ERROR: no extensions/ directory under $GAME_DIR." >&2
  echo "       A known-good baseline of an install whose mod folder cannot be" >&2
  echo "       enumerated would record ZERO mods and look identical to a clean" >&2
  echo "       vanilla install. Refusing to write one." >&2
  exit 2
fi
TSV="$OUT/installed-mods.tsv"
printf "folder\tfiles\tbytes\trollup_sha256\n" > "$TSV"
NMODS=0
for d in "$EXT"/*/; do
  [ -d "$d" ] || continue          # no match: the glob stays literal
  name="$(basename "$d")"
  case "$name" in ego_dlc_*) continue;; esac   # skip official DLC
  cnt=$(find "$d" -type f | wc -l | tr -d ' ')
  bytes=$(find "$d" -type f -printf "%s\n" 2>/dev/null | awk '{s+=$1} END{print s+0}')
  # NB the rollup hashes sha256sum's output INCLUDING each absolute path, so a
  # baseline is tied to the install location. Left as it is deliberately: changing
  # it would silently invalidate the existing baselines on disk, and comparing
  # across two different install paths is not a workflow this tool has. Recorded
  # rather than fixed, so the next reader does not rediscover it as a surprise.
  roll=$(find "$d" -type f -exec sha256sum {} \; 2>/dev/null | sort | sha256sum | cut -d' ' -f1)
  # A ROW WITH NO HASH CANNOT DETECT A CHANGE, so it must not be written as though
  # it could. An unreadable mod folder produced exactly that, silently.
  if [ -z "$roll" ] || [ -z "$cnt" ]; then
    echo "ERROR: could not hash $name -- a baseline row with no rollup cannot" >&2
    echo "       detect any later change, and a partial baseline is worse than" >&2
    echo "       none because it looks complete." >&2
    exit 2
  fi
  printf "%s\t%s\t%s\t%s\n" "$name" "$cnt" "$bytes" "$roll" >> "$TSV"
  echo "  mod: $name (files=$cnt, rollup=${roll:0:12})"
  NMODS=$((NMODS + 1))
done
echo "  installed mods recorded: $NMODS"

# --- copy live artifacts verbatim, and NAME the ones that were not there --------
MISSING_ART=""
for f in content.xml config.xml debug.txt; do
  if [ -f "$PROFILE_DIR/$f" ]; then
    cp "$PROFILE_DIR/$f" "$OUT/$f"
  else
    MISSING_ART="$MISSING_ART $f"
  fi
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
# AN INVENTORY, NOT JUST A DESTINATION. "Baseline written to: ..." was the whole
# report, so a baseline missing its mod list, its config and its error fingerprint
# announced itself in exactly the same words as a complete one. What a recovery
# artifact does NOT contain is the thing you need to know before you rely on it.
echo "  contains: installed-mods.tsv ($NMODS mod(s))"
for f in content.xml config.xml debug.txt error-fingerprint.txt; do
  [ -f "$OUT/$f" ] && echo "            $f"
done
if [ -n "$MISSING_ART" ]; then
  echo "  NOT CAPTURED (absent from $PROFILE_DIR):$MISSING_ART" >&2
  case "$MISSING_ART" in
    *debug.txt*) echo "            — so there is NO error fingerprint to diff against later." >&2;;
  esac
fi
if [ "$NMODS" -eq 0 ]; then
  echo "  NOTE: extensions/ exists but holds no non-DLC mod, so this baseline" >&2
  echo "        records a vanilla install. That is a real state; it is called out" >&2
  echo "        because a zero here is otherwise indistinguishable from a failure." >&2
fi
echo "Re-run after scaling up the mod list, then diff error-fingerprint.txt and re-hash mods vs installed-mods.tsv."

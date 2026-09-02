#!/usr/bin/env bash
# Unpack YOUR OWN X4 base game + DLCs into a local reference/ tree for x4validate and
# "vanilla as frame of reference". Text only (.xml/.xsd/.lua/.xpl) — skips meshes/textures/
# audio, so the tree stays ~0.6 GB instead of ~29 GB. Cross-platform (uses bin/xrcat).
#
# reference/ is read-only base-game data: never edit it, never redistribute it.
# Configure paths via .claude/x4-paths.env (X4_GAME, X4_REFERENCE) or env vars.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/../.claude/hooks/_x4-env.sh"        # X4_GAME, X4_REFERENCE, X4_TOOLKIT

XRCAT="$HERE/xrcat"
INCLUDE='\.(xml|xsd|lua|xpl)$'               # text/markup only — keeps the tree small

# Exit 2 == "this toolkit is not configured", everywhere in the toolkit. Kept
# distinct from 1 ("it ran and something was wrong") so a caller can tell "set
# X4_GAME" from "the unpack failed" — they need opposite responses.
[ -n "${X4_GAME:-}" ]  || { echo "ERROR: X4_GAME not set (path to 'X4 Foundations' with 01.cat..09.cat). Set it in .claude/x4-paths.env." >&2; exit 2; }
[ -d "$X4_GAME" ]      || { echo "ERROR: game dir not found: $X4_GAME" >&2; exit 2; }
[ -n "${X4_REFERENCE:-}" ] || { echo "ERROR: X4_REFERENCE not set (where to write the unpacked tree). Set it in .claude/x4-paths.env." >&2; exit 2; }
REF="$X4_REFERENCE"

# THE LOCK, CHECKED. The sentinel was only ever WRITTEN here (line ~60) and read
# nowhere in this script -- so its own text, "reference/ is read-only; remove this
# file manually to re-unpack", was false for the one path that actually unpacks.
#
# The lock did exist, but only in protect-bash.sh, which guards commands CLAUDE runs
# through its Bash tool. It cannot see an XRCatTool invocation made by this script in
# a child process, and it does not run at all for a user typing
# `bash bin/unpack-reference.sh` or `bash install.sh --unpack`. So the protection
# covered the assistant's path and not the user's.
#
# MEASURED 2026-09-02: an `install.sh --unpack` re-unpacked 510,711 files / 27 GB over
# an already-locked reference tree without a word. The content was identical (same
# .cat files) so nothing was corrupted, but every mtime in the tree changed -- and a
# real re-unpack after a game update would silently overwrite a tree someone had
# deliberately pinned.
if [ -f "$REF/.unpacked-and-locked" ] && [ "${X4_FORCE_UNPACK:-0}" != "1" ]; then
  echo "REFUSING: $REF is locked by .unpacked-and-locked, so it has already been" >&2
  echo "  unpacked and is treated as read-only base-game data." >&2
  echo "  To re-unpack (e.g. after a game update):  rm \"$REF/.unpacked-and-locked\"" >&2
  echo "  or set X4_FORCE_UNPACK=1 for this one run." >&2
  exit 2
fi

echo "Game:      $X4_GAME"
echo "Reference: $REF"
mkdir -p "$REF"

# --- base game (later cat overrides earlier; 09 wins) ---
echo "[1/2] base 01..09.cat"
base=()
for n in 01 02 03 04 05 06 07 08 09; do
  [ -f "$X4_GAME/$n.cat" ] && base+=( -in "$X4_GAME/$n.cat" )
done
[ ${#base[@]} -gt 0 ] || { echo "ERROR: no 01.cat..09.cat found in $X4_GAME" >&2; exit 1; }
"$XRCAT" "${base[@]}" -out "$REF" -include "$INCLUDE"

# --- DLCs: each into reference/extensions/ego_dlc_* (matches X4's index path prefixes) ---
echo "[2/2] DLCs"
for d in "$X4_GAME"/extensions/ego_dlc_*/; do
  [ -d "$d" ] || continue
  name="$(basename "$d")"
  cats=()
  for c in "$d"ext_*.cat; do
    case "$c" in *_sig.cat) continue;; esac
    [ -f "$c" ] && cats+=( -in "$c" )
  done
  [ ${#cats[@]} -eq 0 ] && continue
  mkdir -p "$REF/extensions/$name"
  echo "  $name (${#cats[@]} cats)"
  "$XRCAT" "${cats[@]}" -out "$REF/extensions/$name" -include "$INCLUDE"
done

# --- record the build id reference/ was unpacked from (stale-reference SessionStart hook) ---
if [ -n "${X4_APPMANIFEST:-}" ] && [ -f "$X4_APPMANIFEST" ]; then
  mkdir -p "$X4_TOOLKIT/.claude"
  grep -i '"buildid"' "$X4_APPMANIFEST" | grep -oE '[0-9]+' | tail -1 > "$X4_TOOLKIT/.claude/.reference-buildid" || true
fi

# lock against accidental re-unpacks (remove this sentinel to re-unpack, e.g. after a game update)
touch "$REF/.unpacked-and-locked"

echo "DONE: $(find "$REF" -type f | wc -l) files, $(du -sh "$REF" | cut -f1)"

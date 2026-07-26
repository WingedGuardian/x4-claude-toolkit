#!/bin/bash
# Shared, cross-platform path/config resolver for the X4 toolkit hooks & scripts.
# SOURCE this (do not execute). Single source of truth for the configurable X4 locations
# so nothing is hardcoded to one OS or one user's folder layout.
#
# Resolution order for each value:  existing env var  >  .claude/x4-paths.env  >  default.
# All locations are overridable; see .claude/x4-paths.env.example for the keys.

# Toolkit root (where this toolkit lives).
: "${X4_TOOLKIT:=${CLAUDE_PROJECT_DIR:-$(pwd)}}"

# Load the user's path config if present (KEY=VALUE lines).
_x4_cfg="${X4_CONFIG:-$X4_TOOLKIT/.claude/x4-paths.env}"
if [ -f "$_x4_cfg" ]; then
  set -a; . "$_x4_cfg"; set +a
fi

# Fill only what config/env did not set. (Game/profile/mods/etc. have no safe default — may be empty.)
: "${X4_REFERENCE:=$X4_TOOLKIT/reference}"

# Derive the Steam app manifest from the game dir when possible (…/steamapps/common/X4 Foundations).
if [ -z "${X4_APPMANIFEST:-}" ] && [ -n "${X4_GAME:-}" ]; then
  _sa="$(dirname "$(dirname "$X4_GAME")")"
  [ -f "$_sa/appmanifest_392160.acf" ] && X4_APPMANIFEST="$_sa/appmanifest_392160.acf"
fi

# --- path helpers: case-insensitive + backslash-insensitive (Windows/Git-Bash/macOS/Linux) ---
x4_norm() { printf '%s' "$1" | tr 'A-Z\\' 'a-z/'; }   # lowercase, backslashes -> slashes
# x4_canon PATH -> resolve symlinks + .. (so e.g. a game-dir 'extensions' symlink and its real
# target compare equal). Uses realpath -m when available (no need for the file to exist);
# falls back to the raw path otherwise. Then normalized for case/slash-insensitive compare.
x4_canon() {
  local p="$1"
  # Only canonicalize POSIX-absolute paths (Linux/macOS, and Git-Bash "/c/..."). A Windows
  # "C:\..." path must NOT be fed to realpath (no leading "/" -> treated as relative -> mangled);
  # it falls through to pure string normalization instead.
  case "$1" in
    /*) command -v realpath >/dev/null 2>&1 && p="$(realpath -m -- "$1" 2>/dev/null || printf '%s' "$1")" ;;
  esac
  x4_norm "$p"
}
# x4_under FILE DIR -> 0 (true) if FILE is inside DIR or equals it; false if DIR empty.
x4_under() {
  [ -n "$2" ] || return 1
  local f d; f="$(x4_canon "$1")"; d="$(x4_canon "$2")"; d="${d%/}"
  case "$f" in "$d"/*|"$d") return 0;; *) return 1;; esac
}

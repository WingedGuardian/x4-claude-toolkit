#!/bin/bash
# Shared, cross-platform path/config resolver for the X4 toolkit hooks & scripts.
# SOURCE this (do not execute). Single source of truth for the configurable X4 locations
# so nothing is hardcoded to one OS or one user's folder layout.
#
# Resolution order for each value:  existing env var  >  .claude/x4-paths.env  >  default.
# All locations are overridable; see .claude/x4-paths.env.example for the keys.

# Toolkit root (where this toolkit lives).
# Prefer $CLAUDE_PROJECT_DIR; otherwise derive it from the hook's OWN location
# (<toolkit>/.claude/hooks/ -> <toolkit>), because falling back to $(pwd) makes every
# path resolve against whatever directory the shell happened to be in — which silently
# scattered auto-backups outside the toolkit whenever the var was unset.
if [ -z "${X4_TOOLKIT:-}" ]; then
  if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    X4_TOOLKIT="$CLAUDE_PROJECT_DIR"
  elif [ -n "${HOOK_DIR:-}" ] && [ -d "$HOOK_DIR/../.." ]; then
    X4_TOOLKIT="$(cd "$HOOK_DIR/../.." && pwd)"
  else
    X4_TOOLKIT="$(pwd)"
  fi
fi

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
# x4_norm PATH_OR_COMMAND -> lowercase, backslashes to slashes, and the DRIVE DIALECT
# unified. MEASURED 2026-08-30: without the last step, Git Bash's "/c/Users/..." and
# Windows' "C:/Users/..." never compare equal, so any guard rooted purely on a
# configured PATH missed one of the two dialects -- the same Documents write asked in
# one form and was ALLOWED in the other. 2,553 historical commands use the MSYS form,
# and no probe in the suite had ever used a drive-lettered root, so nothing could have
# caught it. Rules carrying a NAME backstop (the game, the profile) were unaffected.
#
# Windows-to-MSYS is the safe direction: "c:/" is unambiguous, since a colon is illegal
# elsewhere in a Windows path, whereas "/c/" also occurs mid-path. The guard on the
# preceding character is what keeps "https://" from matching as a drive named "s".
x4_norm() { printf '%s' "$1" | tr 'A-Z\\' 'a-z/' | sed -E 's#(^|[^a-z0-9])([a-z]):/#\1/\2/#g'; }
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

# --- user documents ----------------------------------------------------------
# Everything a person keeps outside the toolkit: game settings, saves, other games'
# data. On the reference machine Documents holds Elder Scrolls Online, Paradox
# Interactive, My Games and a backup archive alongside the X4 profile -- none of it
# reproducible, none of it ours.
#
# MEASURED 2026-08-29 before adding the rules that use this: over 11,133 historical
# commands, guarding all of Documents fires on 7 MORE commands (0.06%) than the
# existing X4-profile rules already did, and on ZERO more Edit/Write calls. Cheap.
#
# Empty when it cannot be resolved, and every rule below is guarded on non-empty --
# so an unconfigured machine gets no rule rather than a rule against "".
if [ -z "${X4_DOCUMENTS:-}" ]; then
  for _d in "${USERPROFILE:-}/Documents" "$HOME/Documents" "$HOME/My Documents"; do
    [ -n "${_d#/Documents}" ] && [ -d "$_d" ] && { X4_DOCUMENTS="$_d"; break; }
  done
fi
# The save folder, named separately because deleting one is unrecoverable and the
# message should say so rather than talking about "an X4 directory".
: "${X4_SAVES:=${X4_PROFILE:+$X4_PROFILE/save}}"

# --- hook payload -------------------------------------------------------------
# Read the hook's JSON payload from stdin.
#
# ⚠ MEASURED 2026-08-29, and it had made EVERY HOOK HERE INERT: `cat /dev/stdin`
# returns ZERO BYTES in the Claude Code hook environment, while a bare `cat`
# returns the payload. Seven consecutive probes: 0 bytes via /dev/stdin,
# 641-2840 bytes via bare cat, PreToolUse and PostToolUse alike.
#
# All five hooks used the former. The failure is invisible by construction: a hook
# that reads nothing falls through its first guard clause and exits 0, which is
# byte-identical to deciding "this is fine". Independent confirmation: no
# AUDIT_LOG.txt existed anywhere, and the only one that did contained 17 entries,
# all of them the test suite's synthetic /tmp fixture -- not one real edit in five
# weeks, while CLAUDE.md stated every edit was backed up.
#
# The suites passed throughout, because a suite pipes stdin explicitly and
# /dev/stdin resolves fine there. Green in the harness, dead in production.
x4_hook_input() { cat; }

# x4_require_input <payload> <reason> [event]
# A guard that cannot see its input cannot vouch for it, so it must not stay
# silent -- silence IS allow, and that is exactly how the defect above survived.
#
# The refusal must not depend on the tool that may have failed. MEASURED
# 2026-08-30: this emitted its `ask` THROUGH jq, so with jq unavailable an empty
# payload was reported by nothing at all -- allow again, one layer in. If jq
# cannot render the reason, a static literal goes out instead (no interpolation:
# a reason with a quote in it would need escaping we no longer have).
x4_require_input() {
  [ -n "$1" ] && return 0
  "${JQ:-jq}" -n --arg r "$2" --arg e "${3:-PreToolUse}" \
    '{hookSpecificOutput:{hookEventName:$e,permissionDecision:"ask",permissionDecisionReason:$r}}' 2>/dev/null \
  || printf '%s' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"X4 GUARD INERT: this hook received NO INPUT and could not run jq to report it, so it checked nothing. Confirm only if you know why both are missing."}}'
  exit 0
}

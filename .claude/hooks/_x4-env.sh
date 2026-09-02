#!/bin/bash
# Shared, cross-platform path/config resolver for the X4 toolkit hooks & scripts.
# SOURCE this (do not execute). Single source of truth for the configurable X4 locations
# so nothing is hardcoded to one OS or one user's folder layout.
#
# Resolution order for each value:  .claude/x4-paths.env  >  existing env var  >  default.
#
# NB the FILE WINS over the environment, which is the opposite of what this line said
# until 2026-09-01. install.sh writes bare KEY="value" lines and this file sources them
# with `set -a`, so a plain assignment overwrites whatever was exported. If you need an
# env var to take precedence, write the entry as: KEY="${KEY:-value}".
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
#
# ONE subprocess, not two: sed's `y` transliterates, which is all `tr` was doing. This
# helper is the hot path of protect-files.sh -- MEASURED 2026-08-31 at 145 ms per call
# and ~22 calls per Edit/Write, i.e. ~6 s on every file edit, because x4_under
# canonicalises BOTH of its arguments on all 11 of its call sites. Process spawn is the
# whole cost on Windows; halving the spawns halves the bill.
#
# Behaviour is UNCHANGED and that was proven, not assumed: 43 of 43 path shapes agree
# with the two-process form, including the live configured roots, and the differential
# harness was shown able to detect a deliberately-wrong implementation. x4_norm is shared
# by every guard, and F93 is the entry about a shared helper quietly re-scoping the rules
# above it -- so this may cost less, and must not decide differently.
x4_norm() {
  # Lowercase, backslash -> slash, drive dialect unified, THEN dot segments resolved.
  #
  # The dot-segment pass is not cosmetic. x4_canon only feeds POSIX-absolute paths to
  # realpath, so a WINDOWS-dialect path kept its `..` and compared unequal to the root:
  # MEASURED 2026-09-01, C:/<toolkit>/other/../reference/libraries/w.xml was NOT under
  # reference/, and protect-files.sh returned EMPTY -- a silent allow past a HARD BLOCK
  # -- while the identical /c/... form was correctly caught. hook_facts.norm() has
  # always collapsed them (posixpath.normpath); this is the same rule on the bash side,
  # so two implementations of one path fact stop disagreeing.
  #
  # Still ONE subprocess: the loops live inside the same sed program.
  printf '%s' "$1" | sed -E 'y/ABCDEFGHIJKLMNOPQRSTUVWXYZ\\/abcdefghijklmnopqrstuvwxyz\//
s#(^|[^a-z0-9])([a-z]):/#\1/\2/#g
:dot
s#/[.]/#/#g
tdot
s#/[.]$#/#
:dotdot
s#/[^/]+/[.][.](/|$)#/#
tdotdot
s#(.)/$#\1#'
}
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
#
# The FIRST argument is memoised. protect-files.sh calls this 11 times and passes the
# SAME file path every time, so the identical canonicalisation was recomputed 10 times
# for nothing -- a subprocess each. A one-entry cache is enough precisely because the
# repetition is in argument one; the roots differ per call and caching them would buy
# little and cost correctness questions.
#
# Cache CORRECTNESS: keyed on the exact input string, and x4_canon is a pure function of
# it (realpath is read-only and the filesystem does not move mid-hook), so a hit returns
# what a recomputation would. Plain variables, not an associative array -- macOS ships
# bash 3.2, where `declare -A` fails silently and takes the guard with it.
#
# Returns through a GLOBAL, not stdout. A memo read with `x="$(memo ...)"` caches
# NOTHING: command substitution forks a subshell, the array writes land in the child and
# die with it. MEASURED 2026-08-31 -- 0 cache entries after two calls -- and the first
# version of this cost MORE than no cache at all, because every call was a miss plus a
# scan of a permanently empty array. The interleaved benchmark showed the memo slower
# than the un-memoised form, which read as noise and was not.
#
# Indexed arrays, not `declare -A`: macOS ships bash 3.2, where the associative form
# fails and takes the guard with it.
_X4_CK=()                 # cache keys
_X4_CV=()                 # cache values
_X4_CANON_RESULT=""       # the out-parameter
x4_canon_memo() {
  local i=0 n=${#_X4_CK[@]}
  while [ "$i" -lt "$n" ]; do
    if [ "${_X4_CK[$i]}" = "$1" ]; then _X4_CANON_RESULT="${_X4_CV[$i]}"; return 0; fi
    i=$((i+1))
  done
  _X4_CANON_RESULT="$(x4_canon "$1")"
  _X4_CK[$n]="$1"; _X4_CV[$n]="$_X4_CANON_RESULT"
}
x4_under() {
  [ -n "$2" ] || return 1
  local f d
  x4_canon_memo "$1"; f="$_X4_CANON_RESULT"
  x4_canon_memo "$2"; d="${_X4_CANON_RESULT%/}"
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
# x4_python -> print the interpreter to use, or nothing.
#
# ONE implementation. The three hooks that need Python each grew their own, and they
# DISAGREED on the case that matters: with X4_PYTHON set to something that does not
# resolve, protect-bash.sh refused (correctly -- an explicitly configured interpreter
# that is missing is an error, not a cue to quietly pick a different one), while
# protect-files.sh and backup-before-edit.sh fell through to python3/python/py. They
# also probed in opposite orders. A guard that runs under an interpreter the operator
# did not choose is a guard nobody configured.
x4_python() {
  if [ -n "${X4_PYTHON:-}" ]; then
    command -v "$X4_PYTHON" >/dev/null 2>&1 && printf '%s' "$X4_PYTHON"
    return 0                      # set but unresolvable -> print NOTHING, deliberately
  fi
  for _c in python python3 py; do
    if command -v "$_c" >/dev/null 2>&1; then printf '%s' "$_c"; return 0; fi
  done
  return 0
}

# x4_field <payload> <dotted path, e.g. tool_input.path>
# Read one field from a hook payload without depending on jq alone.
#
# Fixing only the EMIT was a half fix: search-scope.sh READS its path with jq too, so
# with jq missing the read returned empty, the next line exited 0, and the shared
# emitter was never reached. MEASURED 2026-09-01 -- working jq: 420 bytes of advisory;
# broken jq: 0 bytes, still silent, after the emitter had supposedly been fixed. Teach
# EVERY step of the chain, not the last one.
#
# Returns empty for "absent" AND for "unreadable" -- fine for the ADVISORY hooks that
# use it, which have nothing to say either way. The two hooks that emit VERDICTS
# (protect-files, backup-before-edit) deliberately keep their own readers, because they
# must tell those two cases apart and ASK on the second.
x4_field() {
  if printf '%s' '{}' | "${JQ:-jq}" -e . >/dev/null 2>&1; then
    printf '%s' "$1" | "${JQ:-jq}" -r ".$2 // empty" 2>/dev/null
    return 0
  fi
  local _py; _py="$(x4_python)"
  [ -n "$_py" ] || return 0
  X4_IN="$1" X4_PATH="$2" "$_py" -c 'import json, os, sys
cur = json.loads(os.environ["X4_IN"])
for k in os.environ["X4_PATH"].split("."):
    if not isinstance(cur, dict):
        cur = None
        break
    cur = cur.get(k)
sys.stdout.write("" if cur is None else str(cur))' 2>/dev/null
}

# x4_advise <reason> [event]
# Emit an ADVISORY (an allow that carries a note to the model) without depending on jq
# alone. MEASURED 2026-09-01: search-scope.sh and x4validate-on-edit.sh emitted straight
# through `"$JQ"`, so with jq unavailable they produced 0 bytes and the advisory was
# simply lost -- silently, since 0 bytes is also how "nothing to say" looks. The cost is
# a lost note rather than a lost refusal, which is exactly why it could sit unnoticed.
#
# ONE implementation, so a third advisory hook cannot reintroduce the gap: the two
# guards that emit VERDICTS carry their own emitter because they also need deny/ask.
x4_advise() {
  if printf '%s' '{}' | "${JQ:-jq}" -e . >/dev/null 2>&1; then
    "${JQ:-jq}" -n --arg r "$1" --arg e "${2:-PreToolUse}" \
      '{hookSpecificOutput:{hookEventName:$e,additionalContext:$r}}'
    return 0
  fi
  local _py; _py="$(x4_python)"
  if [ -n "$_py" ]; then
    X4_REASON="$1" X4_EVENT="${2:-PreToolUse}" "$_py" -c 'import json, os, sys
sys.stdout.buffer.write(json.dumps({"hookSpecificOutput": {
  "hookEventName": os.environ.get("X4_EVENT") or "PreToolUse",
  "additionalContext": os.environ["X4_REASON"]}}).encode("utf-8"))'
    return 0
  fi
  # Neither renderer. An advisory is a note, not a decision, so a static literal that
  # says the note was lost beats emitting nothing and pretending there was none.
  printf '%s' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"X4 ADVISORY LOST: this hook had something to tell you but neither jq nor python is available to render it. Install jq, or set X4_PYTHON."}}'
}

x4_require_input() {
  [ -n "$1" ] && return 0
  "${JQ:-jq}" -n --arg r "$2" --arg e "${3:-PreToolUse}" \
    '{hookSpecificOutput:{hookEventName:$e,permissionDecision:"ask",permissionDecisionReason:$r}}' 2>/dev/null \
  || printf '%s' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"X4 GUARD INERT: this hook received NO INPUT and could not run jq to report it, so it checked nothing. Confirm only if you know why both are missing."}}'
  exit 0
}

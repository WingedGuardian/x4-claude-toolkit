#!/bin/bash
# Protect X4 mod files from unintended edits. Cross-platform & config-driven.
# Locations come from .claude/x4-paths.env / env vars (see _x4-env.sh); when those are
# unset the legacy path-name patterns act as a backstop, so it still protects out of the box.
# - Hard blocks: reference/ (read-only base game), .cat/.dat, the game installation
# - Confirmation: user profile, live extensions/ (deploy target)
# - Advisory only: content.xml (manifests) -- the user turned the prompt off 2026-08-29
JQ="${JQ:-jq}"
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/_x4-env.sh"

INPUT=$(x4_hook_input)
x4_require_input "$INPUT" "X4 GUARD INERT: this hook received NO INPUT, so it checked nothing. Allowing silently is how five hooks sat dead for weeks while their suites passed. Confirm only if you know why the payload is missing."

# Is jq actually usable? A BROKEN jq made every verdict below print nothing, and empty
# stdout from a hook means ALLOW -- so the guard failed open, silently, exactly like
# F79. protect-bash.sh gained this fallback in bccffc1; this file never did.
PY="$(x4_python)"   # shared: refuses a misconfigured X4_PYTHON
JQ_OK=0
printf '%s' '{}' | "$JQ" -e . >/dev/null 2>&1 && JQ_OK=1

emit() {   # emit <deny|ask|advise> <reason>
  if [ "$JQ_OK" = 1 ]; then
    if [ "$1" = "advise" ]; then
      "$JQ" -n --arg r "$2" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$r}}'
    else
      "$JQ" -n --arg k "$1" --arg r "$2" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:$k,permissionDecisionReason:$r}}'
    fi
  elif [ -n "$PY" ]; then
    X4_KIND="$1" X4_REASON="$2" "$PY" -c 'import json, os, sys
k = os.environ["X4_KIND"]; r = os.environ["X4_REASON"]
h = {"hookEventName": "PreToolUse"}
if k == "advise":
    h["additionalContext"] = r
else:
    h["permissionDecision"] = k; h["permissionDecisionReason"] = r
sys.stdout.buffer.write(json.dumps({"hookSpecificOutput": h}).encode("utf-8"))'
  else
    # Neither emitter available. Hand-rolled JSON is the last resort, and the reason is
    # deliberately literal: a verdict that cannot be rendered must still be a verdict.
    printf '%s' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"X4 GUARD: neither jq nor python is available, so this hook could not evaluate its rules. Confirm only if you know the edit is safe."}}'
  fi
}

if [ "$JQ_OK" = 1 ]; then
  FILE_PATH=$(printf '%s' "$INPUT" | "$JQ" -r '.tool_input.file_path // empty')
  FP_OK=1
elif [ -n "$PY" ]; then
  FILE_PATH=$(X4_IN="$INPUT" "$PY" -c 'import json, os, sys
try:
    sys.stdout.write((json.loads(os.environ["X4_IN"]).get("tool_input") or {}).get("file_path") or "")
except Exception:
    sys.exit(9)')
  FP_OK=$?
  [ "$FP_OK" -eq 0 ] && FP_OK=1 || FP_OK=0
else
  FP_OK=0
fi

# An EMPTY path and an UNREADABLE payload are different facts, and conflating them is
# how a guard reports success over nothing. Only the first is an allow.
if [ "$FP_OK" != 1 ]; then
  VERDICT=1
  emit ask "X4 GUARD: could not read the file path from this payload (no working jq or python), so NO rule below was evaluated. This is not a clean pass. Confirm only if you know the edit is safe."
  exit 0
fi
[ -z "$FILE_PATH" ] && exit 0

deny() { VERDICT=1; emit deny "$1"; exit 0; }
# advise <reason> -- ALLOW, and explain to CLAUDE. Added 2026-08-29 when the user
# turned off the content.xml confirmation: the reminder is still worth having, the
# INTERRUPTION is not. A prompt spends the user's attention; an advisory spends mine.
#
# ACCUMULATES, and does NOT exit (2026-08-30, F84). An advisory is an ALLOW THAT
# CARRIES A NOTE, not a decision, so it must never make the rules below it
# unreachable. Here that had teeth: the manifest advisory sits ABOVE the profile
# confirmation, the deployed-extensions confirmation AND the game-install hard
# block, so editing a DEPLOYED mod manifest was advised and never confirmed.
VERDICT=""
ADVICE=""
# Flush on EVERY exit path. A tail-only flush is silently skipped by the
# whitelist `exit 0`s in the middle of this file -- MEASURED 2026-08-30: it turned
# the manifest advisory into a plain allow. Nothing is emitted if a terminal
# verdict already spoke, or if no advisory accumulated.
flush_advice() {
  [ -n "$VERDICT" ] && return 0
  [ -n "$ADVICE" ] || return 0
  emit advise "$ADVICE"
}
trap flush_advice EXIT
advise() { if [ -n "$ADVICE" ]; then ADVICE="$ADVICE
$1"; else ADVICE="$1"; fi; }
ask()  { VERDICT=1; emit ask "$1"; exit 0; }

# === HARD BLOCK — read-only reference data (unpacked base game, never edit) ===
# X4_REFERENCE defaults to $X4_TOOLKIT/reference, so this covers the default layout too.
x4_under "$FILE_PATH" "$X4_REFERENCE" && deny "BLOCKED: reference/ is read-only unpacked base game data — never edit. Make a diff patch in your mod instead."

# === HARD BLOCK — CAT/DAT archive files (use bin/xrcat / XRCatTool only) ===
# Scoped 2026-08-29: only where X4 keeps archives. `.dat` is a generic extension --
# this denied editing another game's save in Documents, which is not ours to block.
if echo "$FILE_PATH" | grep -qiE '\.(cat|dat)$'; then
  for _r in "${X4_GAME:-}" "${X4_EXTENSIONS:-}" "${X4_MODS:-}" "${X4_TOOLKIT:-}"; do
    x4_under "$FILE_PATH" "$_r" && deny "BLOCKED: cannot write .cat/.dat archives directly. Use bin/xrcat (XRCatTool) to pack/unpack."
  done
fi

# === CONFIRMATION — content.xml (mod manifests; changing breaks mod loading) ===
# Deliberately ABOVE the workspace whitelist: a manifest edit always confirms, even inside
# dev/ or X4_MODS. (Before this it was below the whitelist, so mod manifests in the working
# dirs were silently allowed — contradicting the documented safety rule.)
# The profile's own manifest is the mod enable/disable list and the Steam Workshop
# toggle, and the profile CONFIRMATION below owns it. That used to need a guard here,
# because this advisory exited and would have bypassed the prompt the user kept; since
# advisories accumulate (F84) the confirmation below is reached on its own and wins.
if true; then
  echo "$FILE_PATH" | grep -qiE '(^|[/\\])content\.xml$' && advise "MOD MANIFEST: $FILE_PATH controls what this mod loads, its id, version and dependencies. A wrong id makes every dependent mod report MISSING, and `save=\"1\"` bakes the mod into save files. Allowed without confirmation (user decision 2026-08-29) -- so check the change yourself rather than expecting a prompt."
fi

# === WHITELIST — the toolkit's own working dirs & docs (editable in every install mode) ===
case "$(x4_norm "$FILE_PATH")" in */claude.md|*/knowledgebase.md) exit 0;; esac
# dev/ and dist/ are the documented mod workspace; they MUST be whitelisted before the
# game-install block below, because in the "in-game" install method X4_TOOLKIT *is* the game
# folder — without this, editing your own mod source is hard-denied in the default layout.
for sub in .claude/hooks .claude/skills .claude/agents .claude/commands .claude/plans .claude/backups .claude/memory .claude/projects tools bin scripts dev dist; do
  x4_under "$FILE_PATH" "$X4_TOOLKIT/$sub" && exit 0
done
# Mod sources may live outside the toolkit entirely (X4_MODS); same reasoning.
x4_under "$FILE_PATH" "${X4_MODS:-}" && exit 0
echo "$FILE_PATH" | grep -qiE '\.claude[/\\](hooks|skills|agents|commands|plans|backups|memory|projects)[/\\]' && exit 0

# NOTE: the "ask" rules below run BEFORE the game-install block, so the deploy target
# (extensions/), mod manifests and the profile get a confirmation even when they live inside
# (or are symlinked into) the game folder — x4_under resolves symlinks via realpath.
# (content.xml is handled earlier, above the whitelist, so the advisory reaches Claude
# even for a manifest inside dev/ or X4_MODS.)

# === CONFIRMATION — user profile files (saves, config, active mod list) ===
x4_under "$FILE_PATH" "$X4_PROFILE" && ask "EDITING USER PROFILE FILE: $FILE_PATH — changes affect live game config/saves. Confirm?"
# Saves first: the message must name what is actually at risk.
x4_under "$FILE_PATH" "${X4_SAVES:-}" && ask "EDITING A SAVE GAME: $FILE_PATH -- saves are not reproducible and there is no undo. Confirm?"
# ...and the rest of Documents: game settings, other games, personal files.
# Not ours, not reproducible, and nothing else here guards them.
x4_under "$FILE_PATH" "${X4_DOCUMENTS:-}" && ask "EDITING A FILE IN YOUR DOCUMENTS FOLDER: $FILE_PATH -- this is outside the toolkit and the game. Confirm?"
echo "$FILE_PATH" | grep -qiE 'Egosoft[/\\]X4[/\\]' && ask "EDITING USER PROFILE FILE: $FILE_PATH — changes affect live game config/saves. Confirm?"

# === CONFIRMATION — live extensions/ (deploy target, overwritten on every deploy) ===
# This is mod territory, NOT base-game content — so it's an "ask", even though it usually sits
# inside the game folder (often as a symlink). Must precede the game-install block below.
# Whether the deployed copy is EDITABLE depends on whether a source copy exists elsewhere.
# If a separate mods root is configured and it is NOT inside the game folder, the source
# lives there, every deploy overwrites this copy, and editing it is simply a mistake -- so
# it is a hard block naming where to go instead. When mods live only inside the game folder
# (the common single-location setup) there IS no other copy, and denying would block all
# normal work -- so it stays a confirmation.
x4_mods_are_separate() {
  [ -n "${X4_MODS:-}" ] && [ -n "${X4_GAME:-}" ] || return 1
  x4_under "$X4_MODS" "$X4_GAME" && return 1
  return 0
}
if x4_under "$FILE_PATH" "$X4_EXTENSIONS"; then
  x4_mods_are_separate     && deny "BLOCKED: $FILE_PATH is a DEPLOYED copy; the live extensions/ folder is overwritten on every deploy. Edit the source under $X4_MODS and redeploy."
  ask "EDITING DEPLOYED MOD: $FILE_PATH -- the live extensions/ folder is overwritten on each deploy; edit the source instead. Confirm?"
fi

# === HARD BLOCK — game installation files (base-game content that isn't the toolkit) ===
if [ -n "${X4_GAME:-}" ] && x4_under "$FILE_PATH" "$X4_GAME"; then
  deny "BLOCKED: cannot edit files in the game installation directory. Work in your mod folder instead."
fi
echo "$FILE_PATH" | grep -qiE 'X4 Foundations[/\\]' && deny "BLOCKED: cannot edit files in the game installation directory. Work in your mod folder instead."

exit 0

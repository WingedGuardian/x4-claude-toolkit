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
FILE_PATH=$(echo "$INPUT" | "$JQ" -r '.tool_input.file_path // empty')
[ -z "$FILE_PATH" ] && exit 0

deny() { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'; exit 0; }
# advise <reason> -- ALLOW, and explain to CLAUDE. Added 2026-08-29 when the user
# turned off the content.xml confirmation: the reminder is still worth having, the
# INTERRUPTION is not. A prompt spends the user's attention; an advisory spends mine.
advise() { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$r}}'; exit 0; }
ask()  { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:$r}}'; exit 0; }

# === HARD BLOCK — read-only reference data (unpacked base game, never edit) ===
# X4_REFERENCE defaults to $X4_TOOLKIT/reference, so this covers the default layout too.
x4_under "$FILE_PATH" "$X4_REFERENCE" && deny "BLOCKED: reference/ is read-only unpacked base game data — never edit. Make a diff patch in your mod instead."

# === HARD BLOCK — CAT/DAT archive files (use bin/xrcat / XRCatTool only) ===
echo "$FILE_PATH" | grep -qiE '\.(cat|dat)$' && deny "BLOCKED: cannot write .cat/.dat archives directly. Use bin/xrcat (XRCatTool) to pack/unpack."

# === CONFIRMATION — content.xml (mod manifests; changing breaks mod loading) ===
# Deliberately ABOVE the workspace whitelist: a manifest edit always confirms, even inside
# dev/ or X4_MODS. (Before this it was below the whitelist, so mod manifests in the working
# dirs were silently allowed — contradicting the documented safety rule.)
# ...but NOT the profile's own content.xml: that is the mod enable/disable list
# and the Steam Workshop toggle, and the profile CONFIRMATION below must own it.
# This advisory exits 0, so firing here would silently bypass a prompt the user kept.
if ! x4_under "$FILE_PATH" "${X4_PROFILE:-}"; then
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

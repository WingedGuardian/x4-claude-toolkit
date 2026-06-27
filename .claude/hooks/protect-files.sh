#!/bin/bash
# Protect X4 mod files from unintended edits. Cross-platform & config-driven.
# Locations come from .claude/x4-paths.env / env vars (see _x4-env.sh); when those are
# unset the legacy path-name patterns act as a backstop, so it still protects out of the box.
# - Hard blocks: reference/ (read-only base game), .cat/.dat, the game installation
# - Confirmation: content.xml (manifests), user profile, live extensions/ (deploy target)
JQ="${JQ:-jq}"
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/_x4-env.sh"

INPUT=$(cat /dev/stdin)
FILE_PATH=$(echo "$INPUT" | "$JQ" -r '.tool_input.file_path // empty')
[ -z "$FILE_PATH" ] && exit 0

deny() { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'; exit 0; }
ask()  { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:$r}}'; exit 0; }

# === HARD BLOCK — read-only reference data (unpacked base game, never edit) ===
# X4_REFERENCE defaults to $X4_TOOLKIT/reference, so this covers the default layout too.
x4_under "$FILE_PATH" "$X4_REFERENCE" && deny "BLOCKED: reference/ is read-only unpacked base game data — never edit. Make a diff patch in your mod instead."

# === HARD BLOCK — CAT/DAT archive files (use bin/xrcat / XRCatTool only) ===
echo "$FILE_PATH" | grep -qiE '\.(cat|dat)$' && deny "BLOCKED: cannot write .cat/.dat archives directly. Use bin/xrcat (XRCatTool) to pack/unpack."

# === WHITELIST — the toolkit's own working dirs & docs (editable in every install mode) ===
case "$(x4_norm "$FILE_PATH")" in */claude.md|*/knowledgebase.md) exit 0;; esac
for sub in .claude/hooks .claude/skills .claude/agents .claude/commands .claude/plans .claude/backups .claude/memory .claude/projects tools bin scripts; do
  x4_under "$FILE_PATH" "$X4_TOOLKIT/$sub" && exit 0
done
echo "$FILE_PATH" | grep -qiE '\.claude[/\\](hooks|skills|agents|commands|plans|backups|memory|projects)[/\\]' && exit 0

# NOTE: the "ask" rules below run BEFORE the game-install block, so the deploy target
# (extensions/), mod manifests and the profile get a confirmation even when they live inside
# (or are symlinked into) the game folder — x4_under resolves symlinks via realpath.

# === CONFIRMATION — content.xml (mod manifests; changing breaks mod loading) ===
echo "$FILE_PATH" | grep -qiE '(^|[/\\])content\.xml$' && ask "EDITING MOD MANIFEST: $FILE_PATH — this controls what the mod loads. Confirm?"

# === CONFIRMATION — user profile files (saves, config, active mod list) ===
x4_under "$FILE_PATH" "$X4_PROFILE" && ask "EDITING USER PROFILE FILE: $FILE_PATH — changes affect live game config/saves. Confirm?"
echo "$FILE_PATH" | grep -qiE 'Egosoft[/\\]X4[/\\]' && ask "EDITING USER PROFILE FILE: $FILE_PATH — changes affect live game config/saves. Confirm?"

# === CONFIRMATION — live extensions/ (deploy target, overwritten on every deploy) ===
# This is mod territory, NOT base-game content — so it's an "ask", even though it usually sits
# inside the game folder (often as a symlink). Must precede the game-install block below.
x4_under "$FILE_PATH" "$X4_EXTENSIONS" && ask "EDITING DEPLOYED MOD: $FILE_PATH — the live extensions/ folder is overwritten on each deploy; edit the source instead. Confirm?"

# === HARD BLOCK — game installation files (base-game content that isn't the toolkit) ===
if [ -n "${X4_GAME:-}" ] && x4_under "$FILE_PATH" "$X4_GAME"; then
  deny "BLOCKED: cannot edit files in the game installation directory. Work in your mod folder instead."
fi
echo "$FILE_PATH" | grep -qiE 'X4 Foundations[/\\]' && deny "BLOCKED: cannot edit files in the game installation directory. Work in your mod folder instead."

exit 0

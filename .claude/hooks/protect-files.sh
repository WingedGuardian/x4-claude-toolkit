#!/bin/bash
# Protect X4 mod files from unintended edits.
# Paths resolve relative to $CLAUDE_PROJECT_DIR (portable across install
# locations), with a legacy substring fallback when that var is unset.
# - Hard blocks: reference/ (read-only base game data), .cat/.dat files
# - Confirmation: content.xml (mod manifests), user profile files
# - Whitelist: .claude/, dev/, dist/, tools/ (our working dirs) + workspace docs
JQ="${JQ:-jq}"

INPUT=$(cat /dev/stdin)
FILE_PATH=$(echo "$INPUT" | "$JQ" -r '.tool_input.file_path // empty')

[ -z "$FILE_PATH" ] && exit 0

deny() { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'; exit 0; }
ask()  { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:$r}}'; exit 0; }

# Normalize backslashes so matching is separator-agnostic; case-insensitive (Windows paths).
shopt -s nocasematch
FP=$(printf '%s' "$FILE_PATH" | sed 's#\\#/#g')
PD=$(printf '%s' "${CLAUDE_PROJECT_DIR:-}" | sed 's#\\#/#g')
PD="${PD%/}"  # drop any trailing slash

# Path relative to the project root, when the edit is inside it.
REL=""
[ -n "$PD" ] && [[ "$FP/" == "$PD"/* ]] && REL="${FP#"$PD"/}"

# === HARD BLOCK — CAT/DAT archive files (use XRCatTool only) — path-independent ===
{ [[ "$FP" == *.cat ]] || [[ "$FP" == *.dat ]]; } && \
  deny "BLOCKED: Cannot directly write .cat or .dat archive files. Use XRCatTool to pack/unpack."

# === HARD BLOCK — read-only reference data (unpacked base game, never edit) ===
# Project-relative first (portable); legacy substring fallback for external workspaces.
{ [ -n "$REL" ] && [[ "$REL" == reference/* ]]; } && \
  deny "BLOCKED: reference/ is read-only base game data — never edit directly. Make a diff patch in dev/ instead."
echo "$FP" | grep -qiE 'Modding/X4/reference/' && \
  deny "BLOCKED: reference/ is read-only base game data — never edit directly. Make a diff patch in dev/ instead."

# === EARLY WHITELIST — workspace docs (edit-allowed anywhere) ===
{ [[ "$FP" == */CLAUDE.md ]] || [[ "$FP" == */KNOWLEDGEBASE.md ]]; } && exit 0

# === WHITELIST — our own working dirs (no confirmation needed) ===
if [ -n "$REL" ]; then
  case "$REL" in
    .claude/*|dev/*|dist/*|tools/*) exit 0 ;;
  esac
fi
echo "$FP" | grep -qiE '\.claude/(hooks|plans|backups|memory|skills|agents|commands|projects)/' && exit 0
echo "$FP" | grep -qiE 'Modding/X4/(dev|dist|tools)/' && exit 0

# === CONFIRMATION — content.xml (mod manifests, changing breaks mod loading) ===
[[ "$FP" == */content.xml ]] && ask "EDITING MOD MANIFEST: $FILE_PATH — this controls what the mod loads. Confirm?"

# === CONFIRMATION — user profile files (game saves, config, active mod list) ===
echo "$FP" | grep -qiE 'Documents/Egosoft/X4/' && ask "EDITING USER PROFILE FILE: $FILE_PATH — changes affect live game config/saves. Confirm?"

exit 0

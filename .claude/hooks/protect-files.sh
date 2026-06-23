#!/bin/bash
# Protect X4 mod files from unintended edits.
# - Hard blocks: reference\ (read-only base game data), .cat/.dat files, game core installation
# - Confirmation: content.xml (mod manifests), user profile files
# - Whitelist: .claude/ workspace, dev\, dist\ (our working dirs)
JQ="${JQ:-jq}"

INPUT=$(cat /dev/stdin)
FILE_PATH=$(echo "$INPUT" | "$JQ" -r '.tool_input.file_path // empty')

[ -z "$FILE_PATH" ] && exit 0

deny() { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'; exit 0; }
ask()  { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:$r}}'; exit 0; }

# === HARD BLOCK — read-only reference data (unpacked base game, never edit) ===
echo "$FILE_PATH" | grep -qiE 'Modding[/\\]X4[/\\]reference[/\\]' && deny "BLOCKED: reference\\ is read-only. This is unpacked base game data — never edit directly. Make a diff patch in dev\\ instead."

# === HARD BLOCK — CAT/DAT archive files (use XRCatTool only) ===
echo "$FILE_PATH" | grep -qiE '\.(cat|dat)$' && deny "BLOCKED: Cannot directly write .cat or .dat archive files. Use XRCatTool to pack/unpack."

# === EARLY WHITELIST — CLAUDE.md and KNOWLEDGEBASE.md (workspace docs, edit-allowed at game root or workspace) ===
echo "$FILE_PATH" | grep -qiE '(X4 Foundations|Modding[/\\]X4)[/\\](CLAUDE\.md|KNOWLEDGEBASE\.md)$' && exit 0

# === HARD BLOCK — core game installation files (outside .claude/) ===
echo "$FILE_PATH" | grep -qiE 'X4 Foundations[/\\](?!\.claude)' && \
  echo "$FILE_PATH" | grep -qviE 'X4 Foundations[/\\]\.claude[/\\]' && \
  deny "BLOCKED: Cannot edit files in the game installation directory. Work in Desktop\\Modding\\X4\\dev\\ instead."

# === WHITELIST — our own workspace (no confirmation needed) ===
echo "$FILE_PATH" | grep -qiE '\.claude[/\\](hooks|plans|backups|memory|skills|agents|commands)[/\\]' && exit 0
echo "$FILE_PATH" | grep -qiE '\.claude[/\\]projects[/\\]' && exit 0
echo "$FILE_PATH" | grep -qiE 'Modding[/\\]X4[/\\](dev|dist|tools)[/\\]' && exit 0
echo "$FILE_PATH" | grep -qiE 'Modding[/\\]X4[/\\](CLAUDE\.md|KNOWLEDGEBASE\.md)$' && exit 0

# === CONFIRMATION — content.xml (mod manifests, changing breaks mod loading) ===
echo "$FILE_PATH" | grep -qiE 'content\.xml$' && ask "EDITING MOD MANIFEST: $FILE_PATH — this controls what the mod loads. Confirm?"

# === CONFIRMATION — user profile files (game saves, config, active mod list) ===
echo "$FILE_PATH" | grep -qiE 'Documents[/\\]Egosoft[/\\]X4[/\\]' && ask "EDITING USER PROFILE FILE: $FILE_PATH — changes affect live game config/saves. Confirm?"

exit 0

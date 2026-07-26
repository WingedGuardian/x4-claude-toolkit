#!/bin/bash
# Protect against destructive bash commands. Cross-platform & config-driven.
# Matches the configured paths (.claude/x4-paths.env / env vars) in the command text, with
# legacy folder-name patterns as a backstop so it still guards out of the box.
JQ="${JQ:-jq}"
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/_x4-env.sh"

INPUT=$(cat /dev/stdin)
COMMAND=$(echo "$INPUT" | "$JQ" -r '.tool_input.command // empty')
[ -z "$COMMAND" ] && exit 0

deny() { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'; exit 0; }
ask()  { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:$r}}'; exit 0; }

nCMD="$(x4_norm "$COMMAND")"
# has VALUE -> 0 if the (normalized) command mentions that (non-empty, normalized) path/name.
has() { [ -n "$1" ] && printf '%s' "$nCMD" | grep -qF "$(x4_norm "$1")"; }
is_rm() { printf '%s' "$COMMAND" | grep -qE '(^|[;&|[:space:]])rm([[:space:]]|$)'; }

# === HARD BLOCK — delete the game installation ===
{ is_rm && { has "$X4_GAME" || printf '%s' "$nCMD" | grep -qF 'x4 foundations'; }; } && deny "BLOCKED: cannot delete the X4 game installation directory."

# === HARD BLOCK — delete the reference folder (read-only base game data) ===
{ is_rm && has "$X4_REFERENCE"; } && deny "BLOCKED: cannot delete reference/ — it is the read-only unpacked base game data (re-unpack only via bin/unpack-reference.sh)."

# === HARD BLOCK — re-unpack into a locked reference/ ===
# Sentinel-gated: once reference/.unpacked-and-locked exists, block accidental re-unpacks.
if printf '%s' "$COMMAND" | grep -qiE 'xrcat|XRCatTool' && printf '%s' "$nCMD" | grep -qE '\-out' \
   && has "$X4_REFERENCE" && [ -f "$X4_REFERENCE/.unpacked-and-locked" ]; then
  deny "BLOCKED: reference/ is locked (reference/.unpacked-and-locked exists). Re-unpacking would overwrite the read-only base. Remove the sentinel first if you really mean to re-unpack."
fi

# === CONFIRM — rm targeting the game, profile, reference, mods, or toolkit ===
{ is_rm && { has "$X4_GAME" || has "$X4_PROFILE" || has "$X4_MODS" || has "$X4_TOOLKIT" \
    || printf '%s' "$nCMD" | grep -qE 'x4 foundations|egosoft/x4'; }; } \
  && ask "Deleting files in an X4 directory — confirm: $COMMAND"

# === CONFIRM — mv/cp into the game or profile dirs ===
printf '%s' "$COMMAND" | grep -qiE '^[[:space:]]*(mv|cp|move|copy)\b' \
  && { has "$X4_GAME" || has "$X4_PROFILE" || printf '%s' "$nCMD" | grep -qE 'x4 foundations|egosoft/x4'; } \
  && ask "Moving/copying into game or profile directory — confirm: $COMMAND"

# === CONFIRM — output redirect into game or profile dirs ===
printf '%s' "$COMMAND" | grep -qE '>' \
  && { has "$X4_GAME" || has "$X4_PROFILE" || printf '%s' "$nCMD" | grep -qE 'x4 foundations|egosoft/x4'; } \
  && ask "Redirecting output into game/profile directory — confirm: $COMMAND"

# === CONFIRM — sed -i on game or profile files ===
printf '%s' "$COMMAND" | grep -qE 'sed[[:space:]]+-i' \
  && { has "$X4_GAME" || has "$X4_PROFILE" || printf '%s' "$nCMD" | grep -qE 'x4 foundations|egosoft/x4'; } \
  && ask "In-place edit in game/profile directory — confirm: $COMMAND"

# === CONFIRM — direct reference to .cat/.dat archives ===
printf '%s' "$COMMAND" | grep -qiE '\.(cat|dat)\b' && ask "Command references archive files (.cat/.dat) — confirm: $COMMAND"

exit 0

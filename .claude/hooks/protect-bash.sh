#!/bin/bash
# Protect against destructive bash commands in the X4 modding environment.
JQ="${JQ:-jq}"

INPUT=$(cat /dev/stdin)
COMMAND=$(echo "$INPUT" | "$JQ" -r '.tool_input.command // empty')

deny() { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'; exit 0; }
ask()  { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:$r}}'; exit 0; }

# === HARD BLOCK — delete game installation ===
echo "$COMMAND" | grep -qiE 'rm\s+(-[a-z]*f[a-z]*\s+)?["'"'"']?C:.*X4 Foundations' && deny "BLOCKED: Cannot delete the X4 game installation directory."

# === HARD BLOCK — delete reference folder (read-only base game data) ===
echo "$COMMAND" | grep -qiE 'rm\s.*Modding[/\\]X4[/\\]reference' && deny "BLOCKED: Cannot delete the reference\\ folder. It is the read-only unpacked base game data."

# === HARD BLOCK — XRCatTool unpacks into reference\ once setup is locked ===
# Sentinel-gated: while reference\.unpacked-and-locked does not exist, unpacks are allowed (initial setup).
# After all base+DLC unpacks, touch the sentinel to lock; afterward this rule blocks accidental re-unpacks.
if echo "$COMMAND" | grep -qiE 'XRCatTool.*-out.*reference' && [ -f "${X4_REFERENCE_DIR:-$CLAUDE_PROJECT_DIR/reference}/.unpacked-and-locked" ]; then
  deny "BLOCKED: reference\\ is locked (sentinel .unpacked-and-locked exists). Re-unpacking would overwrite the read-only base. If you really need to re-unpack, remove the sentinel manually first."
fi

# === CONFIRM — any rm targeting mod working dirs ===
echo "$COMMAND" | grep -qiE 'rm\s.*(Modding[/\\]X4|X4 Foundations)' && ask "Deleting files in X4 modding directory — confirm: $COMMAND"

# === CONFIRM — mv/cp modifying game or profile dirs ===
echo "$COMMAND" | grep -qiE '(mv|cp|move|copy)\s.*(X4 Foundations|Documents[/\\]Egosoft[/\\]X4)' && ask "Moving/copying files in game or profile directory — confirm: $COMMAND"

# === CONFIRM — output redirect into game or profile dirs ===
echo "$COMMAND" | grep -qiE '>\s*["'"'"']?.*X4 Foundations' && ask "Redirecting output into game installation — confirm: $COMMAND"
echo "$COMMAND" | grep -qiE '>\s*["'"'"']?.*Documents[/\\]Egosoft[/\\]X4' && ask "Redirecting output into user profile — confirm: $COMMAND"

# === CONFIRM — sed -i on game or profile files ===
echo "$COMMAND" | grep -qiE 'sed\s+-i.*(X4 Foundations|Documents[/\\]Egosoft[/\\]X4)' && ask "In-place edit in game/profile directory — confirm: $COMMAND"

# === CONFIRM — direct reference to .cat or .dat files ===
echo "$COMMAND" | grep -qiE '\.(cat|dat)\b' && ask "Command references archive files (.cat/.dat) — confirm: $COMMAND"

exit 0

#!/bin/bash
# Auto-backup any file before Claude edits it.
# Saves to <toolkit>/.claude/backups/ with a timestamp and logs to an audit trail.
JQ="${JQ:-jq}"
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/_x4-env.sh"

INPUT=$(cat /dev/stdin)
TOOL_NAME=$(echo "$INPUT" | "$JQ" -r '.tool_name // "unknown"')
FILE_PATH=$(echo "$INPUT" | "$JQ" -r '.tool_input.file_path // empty')

# Skip if no file path or file doesn't exist yet (new file creation)
[ -z "$FILE_PATH" ] && exit 0
SRC="${FILE_PATH//\\//}"          # normalize backslashes so -f works on Windows paths
[ ! -f "$SRC" ] && exit 0

# Skip transient workspace files (backups themselves, hooks, plans)
echo "$FILE_PATH" | grep -qiE '(\.claude[/\\](backups|hooks|plans)[/\\])' && exit 0

# Anchor to the toolkit, NOT the cwd. _x4-env.sh resolves X4_TOOLKIT from
# $CLAUDE_PROJECT_DIR (or the hook's own location), so backups always land in one
# known place — the old "${CLAUDE_PROJECT_DIR:-.}" fallback scattered them into
# whatever directory the shell happened to be in.
BACKUP_DIR="${X4_BACKUPS:-$X4_TOOLKIT/.claude/backups}"
mkdir -p "$BACKUP_DIR" 2>/dev/null || exit 0

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
# Flatten path for backup filename: replace / \ : with _
SAFE_NAME=$(echo "$FILE_PATH" | sed 's|[/\\:]|_|g' | sed 's|^_*||')
BACKUP_PATH="$BACKUP_DIR/${TIMESTAMP}__${SAFE_NAME}"

cp "$SRC" "$BACKUP_PATH" 2>/dev/null

# Audit log — append a record of every file touched
AUDIT_LOG="$BACKUP_DIR/AUDIT_LOG.txt"
echo "[$TIMESTAMP] $TOOL_NAME → $FILE_PATH (backup: ${TIMESTAMP}__${SAFE_NAME})" >> "$AUDIT_LOG"

exit 0

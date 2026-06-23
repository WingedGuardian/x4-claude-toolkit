#!/bin/bash
# Auto-backup any file before Claude edits it.
# Saves to .claude/backups/ with timestamp and logs to audit trail.
JQ="${JQ:-jq}"

INPUT=$(cat /dev/stdin)
TOOL_NAME=$(echo "$INPUT" | "$JQ" -r '.tool_name // "unknown"')
FILE_PATH=$(echo "$INPUT" | "$JQ" -r '.tool_input.file_path // empty')

# Skip if no file path or file doesn't exist yet (new file creation)
[ -z "$FILE_PATH" ] && exit 0
[ ! -f "$FILE_PATH" ] && exit 0

# Skip transient workspace files (backups themselves, hooks, plans)
echo "$FILE_PATH" | grep -qiE '(\.claude[/\\](backups|hooks|plans)[/\\])' && exit 0

# Create backup directory
BACKUP_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/backups"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
# Flatten path for backup filename: replace / \ : with _
SAFE_NAME=$(echo "$FILE_PATH" | sed 's|[/\\:]|_|g' | sed 's|^_*||')
BACKUP_PATH="$BACKUP_DIR/${TIMESTAMP}__${SAFE_NAME}"

cp "$FILE_PATH" "$BACKUP_PATH" 2>/dev/null

# Audit log — append a record of every file touched
AUDIT_LOG="$BACKUP_DIR/AUDIT_LOG.txt"
echo "[$TIMESTAMP] $TOOL_NAME → $FILE_PATH (backup: ${TIMESTAMP}__${SAFE_NAME})" >> "$AUDIT_LOG"

exit 0

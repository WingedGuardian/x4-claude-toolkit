#!/bin/bash
# Restore a file that Claude auto-backed-up before editing.
# Backups live in .claude/backups/ as  <timestamp>__<flattened-path>  with an AUDIT_LOG.txt.
#
# Usage:
#   bash scripts/restore-from-backup.sh            # list recent backups
#   bash scripts/restore-from-backup.sh <pattern>  # show matching backups
#   RESTORE=1 bash scripts/restore-from-backup.sh <backup-filename> <dest-path>

set -euo pipefail
BACKUP_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/backups"

if [ ! -d "$BACKUP_DIR" ]; then
  echo "No backup dir at $BACKUP_DIR"; exit 0
fi

if [ "${RESTORE:-0}" = "1" ]; then
  SRC="$BACKUP_DIR/$1"; DEST="$2"
  [ -f "$SRC" ] || { echo "No such backup: $SRC"; exit 1; }
  cp "$SRC" "$DEST"
  echo "Restored $DEST from $1"
  exit 0
fi

PAT="${1:-}"
echo "Backups in $BACKUP_DIR:"
ls -1t "$BACKUP_DIR" 2>/dev/null | grep -vi '^AUDIT_LOG.txt$' | grep -i "${PAT}" | head -40
echo
echo "To restore:  RESTORE=1 bash scripts/restore-from-backup.sh <backup-filename> <dest-path>"

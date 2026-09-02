#!/bin/bash
# Auto-backup any file before Claude edits it.
# Saves to <toolkit>/.claude/backups/ with a timestamp and logs to an audit trail.
JQ="${JQ:-jq}"
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/_x4-env.sh"

INPUT=$(x4_hook_input)
x4_require_input "$INPUT" "X4 BACKUP INERT: this hook received NO INPUT, so NO BACKUP was taken and nothing was written to the audit log. Confirm only if you accept this edit being unrecoverable."

# A BROKEN jq silently disabled this hook entirely: both reads below returned empty, the
# empty-path check exited 0, and nothing was backed up and nothing logged. MEASURED
# 2026-09-01 against a working control -- jq present: 1 backup + 1 audit line;
# JQ=no_such_binary: 0 backups, 0 audit lines, exit 0, no output. The two other guards
# gained a Python fallback; this one -- the only hook standing between an edit and an
# unrecoverable loss -- never did.
PY="$(x4_python)"   # shared: refuses a misconfigured X4_PYTHON
_ask() {   # a backup that cannot be taken is the user's call, not ours to wave through
  if [ -n "$PY" ]; then
    X4_REASON="$1" "$PY" -c 'import json, os, sys
sys.stdout.buffer.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
  "permissionDecision": "ask", "permissionDecisionReason": os.environ["X4_REASON"]}}).encode("utf-8"))'
  else
    printf '%s' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"X4 BACKUP: no backup could be taken and neither jq nor python is available to explain why. Confirm only if you accept this edit being unrecoverable."}}'
  fi
  exit 0
}

JQ_OK=0
printf '%s' '{}' | "$JQ" -e . >/dev/null 2>&1 && JQ_OK=1
if [ "$JQ_OK" = 1 ]; then
  TOOL_NAME=$(printf '%s' "$INPUT" | "$JQ" -r '.tool_name // "unknown"')
  FILE_PATH=$(printf '%s' "$INPUT" | "$JQ" -r '.tool_input.file_path // empty')
elif [ -n "$PY" ]; then
  TOOL_NAME=$(X4_IN="$INPUT" "$PY" -c 'import json, os, sys
sys.stdout.write(json.loads(os.environ["X4_IN"]).get("tool_name") or "unknown")' 2>/dev/null) || TOOL_NAME=""
  FILE_PATH=$(X4_IN="$INPUT" "$PY" -c 'import json, os, sys
sys.stdout.write((json.loads(os.environ["X4_IN"]).get("tool_input") or {}).get("file_path") or "")' 2>/dev/null) \
    || _ask "X4 BACKUP: could not read this payload, so NO BACKUP was taken. Confirm only if you accept this edit being unrecoverable."
else
  _ask "X4 BACKUP: neither jq nor python is available, so the file path could not be read and NO BACKUP was taken. Confirm only if you accept this edit being unrecoverable."
fi

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

AUDIT_LOG="$BACKUP_DIR/AUDIT_LOG.txt"

# The cp result is CHECKED, and the audit line records what actually happened.
# Before this, `cp ... 2>/dev/null` was unchecked and the audit line was appended
# unconditionally -- so a failed copy produced a log entry ASSERTING a backup that did
# not exist. MEASURED 2026-09-01 with a source whose flattened name exceeds the
# filename limit (routine for deep mod trees): 0 backup files, 1 audit line claiming
# one, exit 0, stderr swallowed. An audit trail that can lie is worse than none, because
# it is consulted precisely when something has gone wrong.
if cp "$SRC" "$BACKUP_PATH" 2>/dev/null && [ -f "$BACKUP_PATH" ]; then
  echo "[$TIMESTAMP] $TOOL_NAME → $FILE_PATH (backup: ${TIMESTAMP}__${SAFE_NAME})" >> "$AUDIT_LOG"
  exit 0
fi

echo "[$TIMESTAMP] $TOOL_NAME → $FILE_PATH (BACKUP FAILED — no copy was made)" >> "$AUDIT_LOG"
_ask "X4 BACKUP FAILED for $FILE_PATH — the copy into $BACKUP_DIR did not succeed (commonly a path-length limit on the flattened backup name). This edit would NOT be recoverable from the backup trail. Confirm only if you accept that."

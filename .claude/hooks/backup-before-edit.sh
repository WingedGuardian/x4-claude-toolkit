#!/bin/bash
# Auto-backup any file before Claude edits it.
# Saves to <toolkit>/.claude/backups/ with a timestamp and logs to an audit trail.
JQ="${JQ:-jq}"
# Parameter expansion, not `$(cd "$(dirname "$0")" && pwd)`: that was a subshell AND
# a dirname process on every call (AUDIT-2026-09-24 HK-4). The settings command passes
# an absolute path, and a relative one still resolves: nothing here changes directory.
# BOTH separators: a hook started as `bash C:\...\protect-bash.sh` has a $0 with no
# forward slash at all, and reading it as "." sourced _x4-env.sh from the CALLER's
# directory -- MEASURED: the guard then found no python and asked on every command.
case "$0" in */*|*\\*) HOOK_DIR="${0%[/\\]*}" ;; *) HOOK_DIR=. ;; esac
. "$HOOK_DIR/_x4-env.sh"

INPUT=$(x4_hook_input)
x4_require_input "$INPUT" "X4 BACKUP INERT: this hook received NO INPUT, so NO BACKUP was taken and nothing was written to the audit log. Confirm only if you accept this edit being unrecoverable."

# A BROKEN jq silently disabled this hook entirely: both reads below returned empty, the
# empty-path check exited 0, and nothing was backed up and nothing logged. MEASURED
# 2026-09-01 against a working control -- jq present: 1 backup + 1 audit line;
# JQ=no_such_binary: 0 backups, 0 audit lines, exit 0, no output. The two other guards
# gained a Python fallback; this one -- the only hook standing between an edit and an
# unrecoverable loss -- never did.
x4_resolve_python; PY="$X4_PY"   # shared: refuses a misconfigured X4_PYTHON
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

# ONE jq process for both fields, and no separate health probe (AUDIT-2026-09-24 HK-4:
# that was three jq processes per Edit/Write). Two output lines; a path cannot contain
# a newline. jq failing -- missing, broken, or an UNREADABLE payload -- falls through to
# the python reader, which _ask()s on an unreadable payload exactly as before: the edit
# must never proceed with NO BACKUP AND NO AUDIT LINE because a parse error read as
# "new file, nothing to back up".
if _x4_jq=$(printf '%s' "$INPUT" | "$JQ" -r '(.tool_name // "unknown"), (.tool_input.file_path // .tool_input.notebook_path // "")' 2>/dev/null); then
  TOOL_NAME="${_x4_jq%%
*}"
  FILE_PATH="${_x4_jq#*
}"
  [ "$FILE_PATH" = "$_x4_jq" ] && FILE_PATH=""
elif [ -n "$PY" ]; then
  TOOL_NAME=$(X4_IN="$INPUT" "$PY" -c 'import json, os, sys
sys.stdout.write(json.loads(os.environ["X4_IN"]).get("tool_name") or "unknown")' 2>/dev/null) || TOOL_NAME=""
  FILE_PATH=$(X4_IN="$INPUT" "$PY" -c 'import json, os, sys
sys.stdout.write((json.loads(os.environ["X4_IN"]).get("tool_input") or {}).get("file_path") or (json.loads(os.environ["X4_IN"]).get("tool_input") or {}).get("notebook_path") or "")' 2>/dev/null) \
    || _ask "X4 BACKUP: could not read this payload, so NO BACKUP was taken. Confirm only if you accept this edit being unrecoverable."
else
  _ask "X4 BACKUP: neither jq nor python is available, so the file path could not be read and NO BACKUP was taken. Confirm only if you accept this edit being unrecoverable."
fi

# Skip if no file path or file doesn't exist yet (new file creation)
[ -z "$FILE_PATH" ] && exit 0
SRC="${FILE_PATH//\\//}"          # normalize backslashes so -f works on Windows paths
# ...and drop an extended-length prefix, which is a real spelling the Write tool accepts.
# Without this, `//?/C:/...` is not a file bash can stat, `[ ! -f "$SRC" ]` is true, and
# the hook exits 0 -- NO backup and NO audit line, silently. The same spelling walked
# past protect-files.sh's reference hard block, so the edit was both allowed and
# unrecoverable. Two guards, one path form.
case "$SRC" in
  //?/UNC/*|//./UNC/*|//?/unc/*|//./unc/*) SRC="//${SRC#//?/???/}" ;;
  //?/*|//./*)                             SRC="${SRC#//?/}" ; SRC="${SRC#//./}" ;;
esac
[ ! -f "$SRC" ] && exit 0

# Skip transient workspace files (backups themselves, hooks, plans) -- decided on the
# path with `..` RESOLVED, never the raw text. AUDIT-2026-09-24 HK-3, MEASURED: the raw
# test skipped `<game>/.claude/hooks/../../libraries/wares.xml`, so a base-game file
# spelled through a skipped directory was edited with NO backup and NO audit line.
# The raw test is only a cheap pre-filter; the normalised path decides, so the common
# case (no `.claude/` in the path at all) still costs no subprocess.
shopt -s nocasematch                 # bash 3.1+; `${v,,}` would need bash 4
case "$FILE_PATH" in
  *.claude[/\\]*)
    case "$(x4_norm "$FILE_PATH")" in
      *.claude/backups/*|*.claude/hooks/*|*.claude/plans/*) exit 0 ;;
    esac ;;
esac
shopt -u nocasematch

# Anchor to the toolkit, NOT the cwd. _x4-env.sh resolves X4_TOOLKIT from
# $CLAUDE_PROJECT_DIR (or the hook's own location), so backups always land in one
# known place — the old "${CLAUDE_PROJECT_DIR:-.}" fallback scattered them into
# whatever directory the shell happened to be in.
BACKUP_DIR="${X4_BACKUPS:-$X4_TOOLKIT/.claude/backups}"
# A backup directory that cannot be created is the SAME failure as a cp that fails --
# "the backup did not happen" -- and that one _ask()s and writes an audit line. This
# one exited 0 in silence, leaving nothing in the trail to notice it by. Given that
# AUDIT_LOG.txt once sat empty for five weeks while CLAUDE.md asserted every edit was
# backed up, the silent path is the wrong one to keep.
if ! mkdir -p "$BACKUP_DIR" 2>/dev/null; then
  echo "$(date +%Y-%m-%d\ %H:%M:%S) | $TOOL_NAME | $FILE_PATH | (BACKUP FAILED - could not create $BACKUP_DIR)" >> "${AUDIT_LOG:-$BACKUP_DIR/../AUDIT_LOG.txt}" 2>/dev/null || true
  _ask "X4 BACKUP FAILED for $FILE_PATH: could not create the backup directory $BACKUP_DIR, so NO copy was made. Confirm only if you accept this edit being unrecoverable."
fi

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

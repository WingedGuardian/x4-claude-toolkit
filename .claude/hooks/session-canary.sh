#!/bin/bash
# SessionStart: has anything irreplaceable been lost since it was last committed?
#
# WHY THIS RUNS AUTOMATICALLY. On 2026-09-03 the mod registry went from 196,363 bytes
# and 258 hand-triaged entries to 46 bytes. `dev/` is a git repository and `git status`
# showed it from the moment it happened -- ` M _registry/modlist.yaml`, 8,222 deletions.
# Nobody ran it. The loss was found six hours later, by accident, while investigating
# something unrelated.
#
# The detector existed and nothing invoked it. That is the entire failure, so the fix is
# not a better detector -- it is a detector that runs without anyone remembering to run
# it. SessionStart stdout becomes session context, which is the one channel that is
# always read.
#
# Deliberately never fails the session. A refusal here would block work over a condition
# the user may already know about; the banner is what matters, and it is unmissable.
# `x4canary` itself still exits 1 on a loss and 2 when it could not check, for callers
# that want a gate (a subagent batch, CI).

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/_x4-env.sh"

# The canary lives in the toolkit, not beside the hooks: it is a tool, and it needs the
# x4validate package to resolve roots. If the toolkit is not configured there is nothing
# to say -- but say THAT, rather than printing a reassuring nothing.
CANARY=""
for c in "${X4_TOOLKIT:-}/scripts/x4canary.py" "$HOOK_DIR/../../scripts/x4canary.py"; do
  [ -f "$c" ] && { CANARY="$c"; break; }
done
if [ -z "$CANARY" ]; then
  echo "[x4 canary] NOT RUN: scripts/x4canary.py not found under \$X4_TOOLKIT."
  echo "            Irreplaceable files are UNCHECKED this session."
  exit 0
fi

PY="$(command -v python 2>/dev/null || command -v python3 2>/dev/null)"
if [ -z "$PY" ]; then
  echo "[x4 canary] NOT RUN: no python on PATH. Irreplaceable files are UNCHECKED."
  exit 0
fi

OUT=$("$PY" "$CANARY" 2>&1)
RC=$?

case $RC in
  0) : ;;   # nothing lost; stay quiet, the session start is not the place for noise
  1)
    echo "[x4 canary] *** A TRACKED IRREPLACEABLE FILE HAS BEEN LOST ***"
    echo "$OUT" | sed 's/^/            /'
    echo "            Recover it BEFORE doing anything else, and do not re-run"
    echo "            whatever wrote it:  git -C <repo> checkout -- <path>"
    ;;
  *)
    echo "[x4 canary] COULD NOT CHECK (exit $RC) -- this is not a clean result."
    echo "$OUT" | sed 's/^/            /'
    ;;
esac
exit 0

#!/usr/bin/env bash
# Verify the suite the way a NEW USER sees it: a fresh checkout, no X4 installed.
#
# WHY THIS IS A SCRIPT AND NOT A PARAGRAPH. Doing this by hand failed THREE TIMES
# IN A ROW on the v2.4.0 release, each time producing a confident green from an
# environment that was never actually cold:
#
#   `env -u X4_REFERENCE -u X4_EXTENSIONS pytest`   -> still resolved everything
#   the same, run inside a `git archive` extract    -> still resolved everything
#
# The reason is not obvious and is exactly why nobody gets it right from memory:
# path resolution falls through to **$X4_TOOLKIT**, which points at the toolkit's
# own .claude/x4-paths.env. Clear the two obvious variables and leave that one,
# and a fully configured machine masquerades as a clean one.
#
# What it hid: every module under gates/ resolves paths at IMPORT time, and
# gates/_env.py signals "no install" with `raise SystemExit(2)`. A SystemExit
# during pytest COLLECTION is an INTERNALERROR -- the whole session aborts with
# exit 3 rather than one module failing. A second variant raises TypeError from
# Path(None). Both are invisible on a configured machine and fatal on a fresh
# clone, which is the first thing a new user runs.
#
# THE LOAD-BEARING PART is the precondition check below. It REFUSES to run the
# suite until it has proven the environment is unresolvable. A cold-run script
# that quietly runs warm is worse than no script: it manufactures exactly the
# false confidence it was written to prevent.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="$(cd "$HERE/.." && pwd)"
# ASK git for the root rather than counting "../.." -- the package sits at the repo
# root in the development tree and under tools/x4validate/ in the public bundle,
# and a hardcoded depth silently picks the wrong directory in one of them.
REPO="$(git -C "$PKG" rev-parse --show-toplevel 2>/dev/null)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "== extracting a fresh checkout =="
if [ -z "$REPO" ]; then
  echo "ERROR: $PKG is not inside a git repository; cannot take a clean checkout." >&2
  exit 2
fi
git -C "$REPO" archive "${1:-HEAD}" | tar -x -C "$WORK"
echo "   $(find "$WORK" -type f | wc -l) files -> $WORK"

# Clear EVERY X4_* var, not a hand-picked few. The one that bites is X4_TOOLKIT.
UNSET=()
while IFS= read -r v; do UNSET+=(-u "$v"); done < <(env | grep '^X4_' | cut -d= -f1)
UNSET+=(-u XRCATTOOL)
echo "== cleared ${#UNSET[@]} environment entr(ies) =="

# Same two layouts as above: bundle puts the package under tools/, dev at the root.
if [ -d "$WORK/tools/x4validate" ]; then cd "$WORK/tools/x4validate"
elif [ -f "$WORK/pyproject.toml" ]; then cd "$WORK"
else echo "ERROR: no x4validate package found in the checkout" >&2; exit 2; fi
echo "== package: ${PWD#$WORK/} =="

echo "== PRECONDITION: the environment must be unresolvable =="
RESOLVED=$(env "${UNSET[@]}" uv run --frozen python -c "
from x4validate import _paths
vals = (_paths.registry(), _paths.game_extensions(), _paths.reference())
print('|'.join('None' if v is None else str(v) for v in vals))" 2>/dev/null | tail -1)

if [ "$RESOLVED" != "None|None|None" ]; then
  echo >&2
  echo "REFUSING TO RUN: this is not a cold environment." >&2
  echo "  registry|game_extensions|reference = $RESOLVED" >&2
  echo >&2
  echo "Something is still resolving X4 paths -- most likely \$X4_TOOLKIT, or a" >&2
  echo ".claude/x4-paths.env in a PARENT of the temp checkout ($WORK)." >&2
  echo "A green result from here would be meaningless, so it is not offered." >&2
  exit 3
fi
echo "   registry=None game_extensions=None reference=None  <- genuinely cold"

echo
echo "== running the suite as a new user would =="
env "${UNSET[@]}" uv run --frozen python -m pytest -q
rc=$?

echo
if [ "$rc" -eq 0 ]; then
  echo "COLD RUN CLEAN — the suite passes on a machine with no X4 installed."
else
  echo "COLD RUN FAILED (pytest exit $rc)."
  echo "  exit 3 = INTERNALERROR, usually a gates/ module imported at test-module"
  echo "           scope: see tests/conftest.py::import_gate."
fi
exit "$rc"

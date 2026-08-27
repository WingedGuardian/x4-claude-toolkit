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

# --- the CLI matrix ---------------------------------------------------------
# The suite proves the LIBRARY behaves cold. This proves the EXECUTABLES do,
# which is what a new user actually types. Two properties per CLI:
#
#   exit code 2   "this toolkit is not configured" — never 0 (a plausible-looking
#                 answer computed from nothing) and never 1, which several CLIs
#                 use for "the thing you asked about has findings". A caller that
#                 cannot tell those apart is told to fix the wrong thing. Until
#                 2.5.0, `x4validate <mod>` on a cold machine guessed a relative
#                 `reference/`, found nothing there, and reported the whole base
#                 game missing as MOD ERRORS with rc=1.
#   no traceback  a stack trace is not a refusal. It is the tool failing to have
#                 an opinion, and it is what an unwrapped main() produces.
#
# Arguments are the minimum that gets PAST argparse, because argparse's own usage
# error is also exit 2 -- a bare `x4validate` would pass this check while proving
# nothing. Each invocation must actually reach path resolution.
MOD="$WORK/_coldmod"; mkdir -p "$MOD/libraries"
printf '<diff/>' > "$MOD/libraries/wares.xml"

cli_case() {  # module  function  args...
  local mod="$1" fn="$2"; shift 2
  local out crc
  out=$(env "${UNSET[@]}" uv run --frozen python -c "
import sys
from x4validate import $mod
sys.exit($mod.$fn(sys.argv[1:]) or 0)" "$@" 2>&1); crc=$?

  if printf '%s' "$out" | grep -q '^Traceback'; then
    echo "   FAIL $mod: traceback instead of a refusal"; MFAIL=$((MFAIL+1)); return
  fi
  if [ "$crc" -ne 2 ]; then
    echo "   FAIL $mod: exit $crc (want 2 = not configured)"; MFAIL=$((MFAIL+1)); return
  fi
  echo "   ok   $mod: exit 2, no traceback"; MOK=$((MOK+1))
}

echo
echo "== COLD CLI MATRIX: every executable must refuse with exit 2 =="
MFAIL=0; MOK=0
cli_case _cli        main "$MOD"
cli_case _compat     main check "$MOD"
cli_case _stats      main wares "$MOD"
cli_case _similarity main --candidate "$MOD"
cli_case _xref       main who-calls somecue
cli_case _effectivecli  main ls
cli_case _debugcli   main triage
cli_case _modlist    main refresh
cli_case _savecli    main info

# x4diff is DELIBERATELY not in the matrix. It compares two mod folders to each
# other -- `_merge.overlay_root` / `apply_overlay`, no Config, no reference tree --
# so it is genuinely usable with no game installed, and exit 0 there is the right
# answer. Asserting 2 for it was a bug in THIS script, caught on the first cold
# run: the checker was wrong, not the tool. Recorded rather than deleted, because
# the next person will otherwise "fix" the gap by adding it back.

if [ "$MFAIL" -ne 0 ]; then
  echo "   $MFAIL CLI(s) did not refuse cleanly."
  rc=1
else
  # The count is DERIVED, never a literal. This line read "all 8" until a tenth
  # CLI was added, and it was correct-then-stale exactly as `>= 9` had been in
  # tests/test_unconfigured_refusal.py -- the same defect, in the sentence that
  # reports the result. It now says what it ran, and reconciles that against the
  # source of truth so drift is LOUD instead of silent.
  # Counted with awk, NOT `uv run python`: the first version of this shelled out to
  # uv, which fails whenever pyproject.toml has drifted from uv.lock -- exactly the
  # moment a CLI is being added. DECLARED fell back to "?", the comparison was
  # skipped, and the run reported success. A check that cannot run must never be
  # quiet: an undeterminable count is now a FAILURE, not a skip.
  DECLARED=$(awk '/^\[project\.scripts\]/{f=1;next} /^\[/{f=0} f && /=/{n++} END{print n+0}' pyproject.toml)
  echo "   all $MOK configuration-dependent CLIs refuse cleanly (x4diff needs none)."
  if ! [ "$DECLARED" -gt 0 ] 2>/dev/null; then
    echo "   CANNOT DETERMINE how many CLIs pyproject declares -- this matrix proves nothing."
    rc=1
  elif [ "$((MOK+1))" -ne "$DECLARED" ]; then
    echo "   DRIFT: pyproject declares $DECLARED CLIs; this matrix exercised $MOK + x4diff."
    echo "   A matrix that silently covers a subset is the defect this file exists to catch."
    rc=1
  fi
fi

echo
if [ "$rc" -eq 0 ]; then
  echo "COLD RUN CLEAN — suite and every CLI behave on a machine with no X4 installed."
else
  echo "COLD RUN FAILED (exit $rc)."
  echo "  exit 3 = INTERNALERROR, usually a gates/ module imported at test-module"
  echo "           scope: see tests/conftest.py::import_gate."
fi
exit "$rc"

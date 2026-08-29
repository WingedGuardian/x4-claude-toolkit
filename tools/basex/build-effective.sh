#!/usr/bin/env bash
# Build the x4eff BaseX database: X4's EFFECTIVE merged tree, not files as written.
#
#   x4raw  every file AS WRITTEN, per mod   -> "who WROTE this, in which mod"
#   x4eff  _merge.build_effective per vpath -> "what does the ENGINE SEE"
#
# Both are wanted; x4eff is the one a negative claim should be made against,
# because it applies diffs in load order and resolves conflict winners.
#
# ADVISORY LIMIT: inter-mod load order is community convention (dependencies
# first, then alphabetical), not documented by Egosoft. Any x4eff answer that
# depends on WHICH mod won is advisory to exactly that degree.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASEX_DIR="$HERE/basex"
. "$HERE/_x4v-tree.sh"
X4VALIDATE="$(x4v_resolve "$HERE")"
x4v_announce "$X4VALIDATE"
EFF="$HERE/_eff"
DB=x4eff
MANIFEST="$EFF/effective-manifest.json"

winpath() { cygpath -m "$1" 2>/dev/null || echo "$1"; }

# Fail BEFORE the long work, not after it. build-effective.py takes minutes and
# java is not touched until well after that, so a missing JVM used to surface as
# a class-not-found error at the end of a build that had already done its work.
# uv is checked here in bash because everything else, preflight included, is
# invoked THROUGH it.
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv is not on PATH. This script drives x4validate via 'uv run python'." >&2
  echo "       Install it from https://docs.astral.sh/uv/" >&2
  exit 2
fi
echo "== preflight =="
(cd "$X4VALIDATE" && uv run python "$HERE/preflight.py" --need java jar disk)

# Delete the previous run's artifacts BEFORE building, not after.
#
# MEASURED 2026-08-24 by crash-injection on this exact script: with a stub that
# exited non-zero, the run continued, indexed a LEFTOVER tree from the previous
# build, reconciled the new DB against the PREVIOUS manifest, stamped it FRESH,
# and exited 0. Every downstream reader would have been told a crashed build
# succeeded. The manifest is written by build-effective.py itself (line ~242),
# so its ABSENCE is the honest signal that the builder never finished -- but
# only if a survivor cannot masquerade as it.
rm -rf "$EFF/tree"
rm -f "$MANIFEST"

echo "== serializing the effective tree =="
BUILD_RC=0
(cd "$X4VALIDATE" && uv run python "$HERE/build-effective.py" --out "$EFF/tree") || BUILD_RC=$?

# rc 3 is NOT a crash. build-effective.py returns `0 if not failures else 3`
# AFTER writing the manifest: the tree is built and the manifest describes it
# accurately, some vpaths simply failed to merge. Continuing is correct, and
# coverage.py reconciles the shortfall. Any OTHER non-zero means it died before
# writing the manifest, so there is nothing to reconcile against and going on
# would build an index nobody can score.
if [ "$BUILD_RC" -eq 3 ]; then
  echo "  (build-effective reported per-file failures — see effective-manifest.json)"
elif [ "$BUILD_RC" -ne 0 ]; then
  echo >&2
  echo "ERROR: build-effective.py died with rc $BUILD_RC before writing a manifest." >&2
  echo "       Refusing to continue: the DB would be built from whatever tree" >&2
  echo "       happened to be on disk and scored against a manifest that does not" >&2
  echo "       describe it. Nothing has been indexed or stamped." >&2
  exit "$BUILD_RC"
fi

if [ ! -f "$MANIFEST" ]; then
  echo >&2
  echo "ERROR: build-effective.py exited $BUILD_RC but wrote no manifest at" >&2
  echo "       $MANIFEST -- so coverage has no denominator. Refusing to continue." >&2
  exit 1
fi

EFF_WIN="$(winpath "$EFF/tree")"
echo
echo "== building $DB =="
cd "$BASEX_DIR"
java -cp BaseX.jar org.basex.BaseX -c "DROP DB $DB" >/dev/null 2>&1 || true

BUILD_LOG="$(mktemp)"
java -cp BaseX.jar org.basex.BaseX -c "
SET SKIPCORRUPT true
CREATE DB $DB
SET CREATEFILTER *.xml
ADD TO / $EFF_WIN
OPTIMIZE ALL
INFO DB
" 2>&1 | tee "$BUILD_LOG"

if grep -qi "not found\|Improper use\|Stopped at" "$BUILD_LOG"; then
  echo "ERROR: BaseX rejected an input above — the index is INCOMPLETE." >&2
  rm -f "$BUILD_LOG"; exit 1
fi
rm -f "$BUILD_LOG"

# The serialized tree is large and reproducible; the DB is the durable artifact.
if [ "${KEEP_EFF:-0}" != "1" ]; then
  rm -rf "$EFF/tree"
  echo "serialized tree discarded (KEEP_EFF=1 to keep it); manifest retained"
fi

echo
echo "== reconciling x4eff coverage =="
# Report the verdict, do not abort: the DB is built and usable, it simply cannot
# back a NEGATIVE claim until the delta is explained.
#
# Exit codes on THIS path (--eff-manifest) are 0 complete / 4 unexplained / 2
# refusal. Note it differs from the x4raw path, which has a third tier:
# {complete: 0, accounted: 3, unexplained: 4} (coverage.py:305). "accounted"
# means the whole deficit is explained by named unparseable files, and the eff
# path has no such tier -- do not copy build-corpus.sh's "exit 3" wording here,
# because this path never produces a 3.
#
# The verdict is PROPAGATED (see the exit at the end) -- it used to be swallowed
# by `|| true`, which is how a build with an unexplained shortfall exited 0 and
# read to every caller as a clean build. build-corpus.sh has always propagated
# it; the asymmetry meant the two halves of one corpus reported differently.
COVERAGE_RC=0
(cd "$X4VALIDATE" && uv run python "$HERE/coverage.py" --db "$DB" \
    --eff-manifest "$MANIFEST") || COVERAGE_RC=$?

# x4eff is ENGINE-dependent: it is a product of _merge, so a merge fix
# invalidates it even when not one input file changed. That is exactly how this
# DB went eleven days serving pre-fix values. Stamp both axes.
(cd "$X4VALIDATE" && uv run python "$HERE/staleness.py" --write --db "$DB")

exit "$COVERAGE_RC"

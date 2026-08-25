#!/usr/bin/env bash
# Build (or rebuild) the x4raw BaseX database from real X4 XML — base+DLC
# reference, every INSTALLED extension's loose XML, and (since 2026-07-27) every
# extension's PACKED XML plus the two mini-DLC, via stage.py. Internal dev tool,
# not part of the public toolkit (BaseX needs a separate JVM install).
#
# PACKED CONTENT IS 62% OF ALL MOD XML (vro alone is 1,613 files). Before staging
# was added, this index could not support ANY negative claim — "nothing
# references X" was a statement about the 38% that happened to be loose.
#
# STILL NOT THE EFFECTIVE TREE: this indexes files AS WRITTEN — no diff
# application, no load order, no conflict winner. That is x4eff's job (see
# build-effective.py). x4raw answers "who WROTE this"; x4eff answers "what does
# the engine SEE".
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASEX_DIR="$HERE/basex"
X4VALIDATE="${X4VALIDATE_DIR:-$HERE/../x4validate}"
# Resolve, never guess. These used to fall back to one developer's absolute
# paths, so on any other machine the build ran happily over directories that do
# not exist -- and reported success. (It also shipped a username.)
# x4validate._paths is the ONE resolver: $VAR -> .claude/x4-paths.env -> default.
# Fail BEFORE the long work, not after it.
#
# MEASURED 2026-08-24: this script runs stage.py to completion (:49) and does not
# touch java until :54, so on a machine with no JVM the entire staging pass was
# spent before anything could fail -- and it then failed with "command not found"
# rather than "install Java 17". uv is checked here in bash because everything
# else, preflight included, is invoked THROUGH it.
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv is not on PATH. This script drives x4validate via 'uv run python'." >&2
  echo "       Install it from https://docs.astral.sh/uv/" >&2
  exit 2
fi
echo "== preflight =="
(cd "$X4VALIDATE" && uv run python "$HERE/preflight.py" --need java jar disk)

resolve_path() {  # $1 = env var name, $2 = _paths function
  local v="${!1:-}"
  if [ -z "$v" ]; then
    v=$(cd "$X4VALIDATE" && uv run python -c "from x4validate import _paths; p=_paths.$2(); print(p or '')" 2>/dev/null)
  fi
  if [ -z "$v" ]; then
    echo "ERROR: cannot resolve \$$1. Set it, or configure .claude/x4-paths.env." >&2
    echo "Refusing to guess: a corpus built over a path that does not exist indexes" >&2
    echo "ZERO documents and still exits 0." >&2
    exit 2
  fi
  printf '%s' "$v"
}
REFERENCE="$(resolve_path X4_REFERENCE reference)"
EXTENSIONS="$(resolve_path X4_EXTENSIONS game_extensions)"
DB=x4raw

# Java is a native Windows process and does not understand Git Bash's /c/... form:
# passing it verbatim made BaseX look for "C:/c/Users/..." and report the resource
# missing — while the build still exited 0. Hand Java a real Windows path.
winpath() { cygpath -m "$1" 2>/dev/null || echo "$1"; }
STAGE="$HERE/_stage"
STAGE_WIN="$(winpath "$STAGE")"

echo "== staging packed content =="
(cd "$X4VALIDATE" && uv run python "$HERE/stage.py" --out "$STAGE" --extensions "$EXTENSIONS")

echo
echo "== building $DB =="
cd "$BASEX_DIR"
java -cp BaseX.jar org.basex.BaseX -c "DROP DB $DB" >/dev/null 2>&1 || true

# BaseX exits 0 even when an ADD names a path it cannot find, so the exit code is
# not a usable gate. Capture the output and fail loudly on "not found".
BUILD_LOG="$(mktemp)"
java -cp BaseX.jar org.basex.BaseX -c "
SET SKIPCORRUPT true
CREATE DB $DB
SET CREATEFILTER *.xml
ADD TO /base $REFERENCE
ADD TO /base/extensions $STAGE_WIN/base_extensions
ADD TO /mods $EXTENSIONS
ADD TO /mods $STAGE_WIN/mods
OPTIMIZE ALL
INFO DB
" 2>&1 | tee "$BUILD_LOG"

if grep -qi "not found\|Improper use\|Stopped at" "$BUILD_LOG"; then
  echo >&2
  echo "ERROR: BaseX rejected at least one input above — the index is INCOMPLETE." >&2
  echo "       (BaseX exits 0 on this, so it would otherwise pass silently.)" >&2
  rm -f "$BUILD_LOG"
  exit 1
fi
rm -f "$BUILD_LOG"

echo
echo "== reconciling coverage (SKIPCORRUPT drops files SILENTLY) =="
# Exit 3 = coverage incomplete. Report it, do not abort: the DB is built and
# usable, it simply cannot back a NEGATIVE claim until the delta is explained.
COVERAGE_RC=0
(cd "$X4VALIDATE" && uv run python "$HERE/coverage.py" --db "$DB" --stage "$STAGE" \
    --reference "$REFERENCE" --extensions "$EXTENSIONS") || COVERAGE_RC=$?

# Stamp WHEN this index was true, not just how much of it was indexed. Without
# this, ask.py cannot tell a current answer from one about a superseded world —
# x4eff served 858 wrong values for 11 days because nothing recorded it.
(cd "$X4VALIDATE" && uv run python "$HERE/staleness.py" --write --db "$DB")

# Staging is transient by design — the index is the durable artifact. Keep it
# only if KEEP_STAGE=1 (useful when debugging an extraction failure).
if [ "${KEEP_STAGE:-0}" != "1" ]; then
  rm -rf "$STAGE"
  echo "staging discarded (KEEP_STAGE=1 to keep it)"
fi

exit "$COVERAGE_RC"

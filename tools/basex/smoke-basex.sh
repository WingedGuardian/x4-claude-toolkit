#!/usr/bin/env bash
# Prove the VENDORED BaseX jar actually runs a query — with a real JVM, on a real DB.
#
# WHY THIS EXISTS. The 24 BaseX unit tests pass on a machine with no Java at all,
# because they mock: test_preflight.py monkeypatches shutil.which and writes a jar
# that is literally b"not really a jar, but it is a file". MEASURED 2026-08-26: no
# CI job had ever started a JVM, on any OS, since the jar was vendored. A bad jar, a
# classpath change, or an untracked .basexhome would have shipped silently -- a green
# that could not have gone red.
#
# Deliberately NOT a pytest that skips when java is missing: a skip in CI is
# indistinguishable from a pass, which is the defect this file exists to remove. It
# fails loudly instead.
#
# Scope: 3 documents, not the real corpus. This checks that the jar RUNS, not that the
# corpus is correct -- a full build is minutes and needs a game install.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASEX_DIR="$HERE/basex"
DB=basex_smoke
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; (cd "$BASEX_DIR" && java -cp BaseX.jar org.basex.BaseX -c "DROP DB $DB" >/dev/null 2>&1) || true' EXIT

winpath() { cygpath -m "$1" 2>/dev/null || echo "$1"; }

command -v java >/dev/null 2>&1 || { echo "FAIL: java is not on PATH"; exit 2; }
[ -f "$BASEX_DIR/BaseX.jar" ] || { echo "FAIL: BaseX.jar missing at $BASEX_DIR"; exit 2; }
# .basexhome is a 0-byte marker; without it BaseX relocates its home to $HOME/basex
# and a build "succeeds" into a directory nothing else looks in.
[ -f "$BASEX_DIR/.basexhome" ] || { echo "FAIL: .basexhome marker missing -- BaseX would use \$HOME/basex"; exit 2; }

for i in 1 2 3; do printf '<doc id="%s"><ware id="w%s"/></doc>\n' "$i" "$i" > "$TMP/d$i.xml"; done

cd "$BASEX_DIR"
java -cp BaseX.jar org.basex.BaseX -c "DROP DB $DB" >/dev/null 2>&1 || true
OUT="$(java -cp BaseX.jar org.basex.BaseX -c "
SET CREATEFILTER *.xml
CREATE DB $DB $(winpath "$TMP")
XQUERY count(collection('$DB')//ware)
" 2>&1)" || { echo "FAIL: BaseX invocation errored"; echo "$OUT"; exit 1; }

COUNT="$(printf '%s\n' "$OUT" | tr -d '\r' | grep -oE '^[0-9]+$' | tail -1 || true)"
if [ "${COUNT:-}" != "3" ]; then
  echo "FAIL: expected 3 <ware> nodes, got '${COUNT:-<none>}'"
  echo "--- BaseX output ---"; echo "$OUT"
  exit 1
fi
echo "OK: vendored BaseX ran a real query (3 of 3 nodes) on $(java -version 2>&1 | head -1)"

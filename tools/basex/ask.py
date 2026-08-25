r"""Ask the corpus a question and get an answer that carries its own denominator.

The whole point
---------------
A discovery tool that cannot prove a negative is just a faster way to guess. Two
things stood between BaseX and a usable "nobody references X":

  Gap 1  62% of mod XML was PACKED and invisible  -> fixed by stage.py
  Gap 2  the index held files AS WRITTEN, not the effective tree -> fixed by x4eff
  Gap 3  SKIPCORRUPT drops files SILENTLY          -> fixed by coverage.py + this

Gap 3 is the one that turns "more complete" into "proof". A zero-result is only
a finding if you can say what it is zero *over*:

    "nothing references turret_x"                       <- not a claim
    "0 hits over 13,672 of 13,684 documents; the 12
     exclusions are malformed XML the engine also
     cannot read, listed by name"                       <- a claim

So this REFUSES to render a zero-result as a negative finding unless coverage.json
says the index is complete or fully accounted. A positive result needs no such
guard — one hit is one hit regardless of what else was missed.

Which DB
--------
  --db x4raw  (default)  files as written  -> "who WROTE this, in which mod"
  --db x4eff             effective tree    -> "what does the ENGINE see"

Prefer x4eff for a claim about what is live; x4raw for provenance/authorship.

Usage
-----
  uv run python ask.py refs <macro_or_ware_id> [--db x4eff]
  uv run python ask.py attr <attribute-name>
  uv run python ask.py xq   '<raw xquery>'
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import preflight

HERE = Path(__file__).resolve().parent
BASEX_DIR = HERE / "basex"



def run_xq(xquery: str) -> str:
    out = subprocess.run(["java", "-cp", "BaseX.jar", "org.basex.BaseX", "-q", xquery],
                         cwd=BASEX_DIR, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:500])
    return out.stdout.rstrip("\n")


#: Separates the item count from the payload in a wrapped query. Printable on
#: purpose: U+0001 is not a legal XML character, so a control byte makes the
#: wrapper fail to compile and silently costs every count.
_SEP = "@@ASK-COUNT-SEP@@"


def run_counted(xquery: str) -> tuple[str, int | None]:
    """Run *xquery* and return (output, item_count).

    The count is the number of items in the RESULT SEQUENCE. Until 2026-08-01
    this module reported `len(output_lines)` as "hits", which is a different
    number entirely: 847 occurrences across 4 documents printed as "32 hit(s)",
    because BaseX had wrapped the serialized sequence over 32 lines.

    That mattered far beyond a cosmetic miscount — the zero-result guard, the
    whole point of this tool, keyed off the line list being empty. A `count()`
    query returning 0 emits the single line "0", so the guard never ran and a
    zero result rendered as "1 hit(s)".

    *item_count* is None when the wrapper will not compile (a query with its own
    prolog, say). The caller must then say the count is unavailable rather than
    quote the line count as though it were meaningful.
    """
    wrapped = f'let $__ask := ( {xquery} ) return (count($__ask), "{_SEP}", $__ask)'
    try:
        raw = run_xq(wrapped)
    except RuntimeError:
        return run_xq(xquery), None
    head, sep, body = raw.partition(_SEP)
    if not sep:
        return raw, None
    try:
        return body.lstrip("\n"), int(head.strip())
    except ValueError:
        return raw, None


def _looks_like_zero_count(lines: list[str]) -> bool:
    """A single serialized `0` — i.e. count(...) that counted nothing."""
    return len(lines) == 1 and lines[0].strip() == "0"


def load_coverage(db: str) -> dict:
    """Per-DB coverage report. x4raw and x4eff have different denominators, so
    they must never share one — a claim about the effective tree cannot borrow
    the raw index's completeness."""
    path = BASEX_DIR / f"coverage-{db}.json"
    if not path.is_file():
        return {}
    cov = json.loads(path.read_text(encoding="utf-8"))
    return cov if cov.get("db") == db else {}


def staleness_verdict(db: str):
    """Does this index still describe the current world? (see staleness.py)

    Coverage answers "how much was indexed"; this answers "as of when". A stale
    index is neither an absence nor a non-answer — it is an answer about a world
    that has moved on, and x4eff served 858 wrong values for eleven days because
    nothing asked. Monkeypatched in tests.
    """
    import staleness
    try:
        reference, extensions, engine = staleness._defaults()
    except (staleness.EngineUnavailable, ImportError) as exc:
        # MEASURED 2026-08-24 on a proven-cold checkout: this used to escape as a
        # raw traceback with rc **1** — which in this toolkit means "the thing you
        # asked about has findings", when the truth was "this toolkit is not set
        # up". Opposite responses from whoever reads the code, and exactly the
        # confusion F39 removed from the CLIs. Reported as UNDETERMINABLE rather
        # than STALE: the query itself still ran and its positive answers stand;
        # what nobody established is whether the index still describes the world.
        return staleness.Verdict(False, [str(exc)], db, determinable=False)
    return staleness.check(BASEX_DIR / f"coverage-{db}.json",
                           reference, extensions, engine, db)


def _xq_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def q_refs(db: str, ident: str) -> str:
    lit = _xq_literal(ident)
    return f"""
for $n in collection('{db}')//*[@ref = {lit} or @macro = {lit} or @name = {lit}
                              or @ware = {lit} or @component = {lit}]
let $u := substring-after(document-uri(root($n)), '/{db}/')
order by $u
return $u || '  <' || name($n) || '>'
"""


def q_attr(db: str, attr: str) -> str:
    return f"""
for $v in distinct-values(collection('{db}')//@{attr})
let $n := count(collection('{db}')//*[@{attr} = $v])
order by $n descending
return $v || ' : ' || $n
"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["refs", "attr", "xq"])
    p.add_argument("arg")
    p.add_argument("--db", default="x4raw", choices=["x4raw", "x4eff"])
    args = p.parse_args(argv)

    xq = {"refs": q_refs, "attr": q_attr}.get(args.mode)
    query = xq(args.db, args.arg) if xq else args.arg

    # `--db` chooses the coverage AND freshness denominator; the query text
    # chooses what is actually searched. If they disagree the result is scored
    # against the wrong world — which is exactly what this module's own
    # `load_coverage` docstring forbids ("they must never share one"). Found
    # end-to-end 2026-08-13: `xq "count(collection('x4eff')//macro)"` searched
    # x4eff, reported "in x4raw", and a STALE x4eff raised no warning because
    # x4raw happened to be fresh.
    named = set(re.findall(r"collection\(\s*['\"]([^'\"]+)['\"]\s*\)", query))
    foreign = sorted(n for n in named if n != args.db)
    if foreign:
        print(f"error: the query searches {', '.join(foreign)} but --db is "
              f"'{args.db}'.", file=sys.stderr)
        print(f"       Coverage and staleness would be judged against "
              f"'{args.db}', which is not what you queried.", file=sys.stderr)
        print(f"       Re-run with --db {foreign[0]}.", file=sys.stderr)
        return 2

    # Cheap preconditions first -- filesystem only, no JVM start. A missing jar or
    # an unbuilt database is knowable before spending anything, and BaseX's own
    # words for both name neither the cause nor the cure: an unbuilt DB reports
    # "[FODC0002] Resource '<abs path>/x4raw' not found" and never mentions
    # build-corpus.sh, because the one line that does sits on the ZERO-RESULT
    # path an unbuilt DB can never reach.
    problems = preflight.check(["jar", "db"], db=args.db)
    if problems:
        print(preflight.render(problems), file=sys.stderr)
        return 2

    try:
        out, n_items = run_counted(query)
    except (RuntimeError, FileNotFoundError) as exc:
        # Before quoting BaseX's own error, ask whether the ENVIRONMENT explains
        # it. MEASURED 2026-08-24 with java off PATH: this printed "error: BaseX
        # query failed: [WinError 2] The system cannot find the file specified"
        # -- blaming BaseX for a missing JVM, and not even naming the file. The
        # full check (which does start a JVM to read its version) runs only here,
        # on the path that has already failed.
        problems = preflight.check(["java", "jar", "db"], db=args.db)
        if problems:
            print(preflight.render(problems), file=sys.stderr)
            return 2
        print(f"error: BaseX query failed: {exc}", file=sys.stderr)
        return 2

    lines = [ln for ln in out.splitlines() if ln.strip()]
    cov = load_coverage(args.db)
    indexed = cov.get("indexed", {}).get("total")
    expected = cov.get("expected", {}).get("total")
    status = cov.get("status", "unknown")

    # `n_items is None` = the wrap would not compile, so we are back to counting
    # LINES and must say so rather than print a number that looks authoritative.
    hits = len(lines) if n_items is None else n_items
    unit = "output line(s), item count unavailable" if n_items is None else "item(s)"

    # Printed on EVERY run until the index is rebuilt — including alongside a
    # POSITIVE result, which is still an answer about a superseded world.
    stale = staleness_verdict(args.db)
    if not stale.fresh:
        print(stale.banner())

    if hits:
        print("\n".join(lines))
        print(f"\n{hits} {unit} in {args.db}.")
        # A count()-shaped query returns ONE item — the number — even when it
        # counted nothing. Before 2026-08-01 that printed "1 hit(s)" and skipped
        # the guard below entirely, which is the exact false positive this whole
        # tool exists to prevent, reached through its most natural phrasing.
        if n_items == 1 and lines and _looks_like_zero_count(lines):
            print("\n  ** NOT A NEGATIVE FINDING. ** That is one atomic value, not one")
            print("  match: a count()-shaped query returns a number even when it counted")
            print("  nothing. The denominator guard applies to an EMPTY SEQUENCE, so it")
            print("  did not run here. Re-run returning the nodes themselves — drop the")
            print("  count(...) wrapper — for a claim with coverage behind it.")
            return 4
        return 0

    # --- the zero-result path: this is where a denominator is mandatory -------
    print(f"0 items in {args.db}.")
    if not cov:
        print("\n  ** NOT A NEGATIVE FINDING. ** No coverage report for this database")
        print("  (run build-corpus.sh / build-effective.sh). Without a denominator this")
        print("  means only 'not found in whatever happens to be indexed'.")
        return 4
    if not cov.get("supports_negative_claim"):
        print(f"\n  ** NOT A NEGATIVE FINDING. ** Coverage status: {status}.")
        print(f"  {indexed} of {expected} documents indexed, and the shortfall is")
        print("  UNEXPLAINED — something is wrong with the build, so 'zero hits' here")
        print("  cannot be distinguished from 'we never looked'.")
        return 4

    # Coverage is satisfied — the build indexed what it claimed. Currency is a
    # SEPARATE question, checked last so the coverage diagnostics above still
    # speak for themselves: a denominator taken from a world that has since
    # changed is not a denominator for the question being asked now.
    if not stale.fresh:
        print("\n  ** NOT A NEGATIVE FINDING. ** Coverage is complete, but the index is")
        print("  STALE (see the banner above), so 'zero hits' describes the world as of")
        print("  the build, not the world now. Rebuild before making this claim.")
        return 4

    missing = (expected or 0) - (indexed or 0)
    print(f"\n  NEGATIVE CONFIRMED over {indexed} of {expected} documents"
          + (f" ({missing} excluded)." if missing else " (complete)."))
    if missing:
        print("  The exclusions are malformed XML the ENGINE cannot read either, so they")
        print("  hold no live content. Named in coverage.json -> unparseable:")
        for u in cov.get("unparseable", [])[:15]:
            print(f"    - {u}")
    if args.db == "x4raw":
        print("\n  NOTE: x4raw is files AS WRITTEN. For a claim about what is LIVE, re-run")
        print("  with --db x4eff (diffs applied, load order resolved).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

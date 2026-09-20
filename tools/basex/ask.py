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
  uv run python ask.py xq   --file <query.xq>

From Git Bash, pass an xq query with --file: MSYS rewrites path-like parts of command-line
arguments before Python sees them (`//` becomes `/`; a leading `/ware` becomes
`C:/Program Files/Git/ware`), and a zero from an argument there is refused.
"""

from __future__ import annotations

import argparse
import json
import os
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
    try:
        cov = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        # A truncated or half-written coverage file used to escape as a raw
        # traceback with rc 1, which in this toolkit means "the thing you asked
        # about has findings" — when the truth is "this artifact
        # is unreadable". F39 removed exactly that confusion from the CLIs; this
        # reader was missed, and it sits on the path every query takes.
        #
        # {} is the SAFE value, not a shrug: with no coverage,
        # supports_negative_claim is falsy and the negative is REFUSED. It is
        # named because a silent {} looks like an index that was never stamped.
        print(f"  coverage-{db}.json is unreadable ({type(exc).__name__}: {exc}); "
              f"treating this index as carrying NO coverage, so no negative "
              f"claim can be made from it.", file=sys.stderr)
        return {}
    if not isinstance(cov, dict):
        print(f"  coverage-{db}.json does not contain a JSON object; treating "
              f"this index as carrying NO coverage.", file=sys.stderr)
        return {}
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
    # THE GUARD ABOVE COVERS `_defaults()` ONLY, AND THERE ARE TWO CALLERS.
    # `check()` calls `fingerprint()` -> `_core()` -> `from x4validate import
    # _freshness`, which can raise EngineUnavailable on a HALF-INSTALL even when
    # `_paths` imported fine. `staleness.check` deliberately re-raises that one
    # ("NOT OURS TO CATCH -- main() owns this") and it is right about
    # `staleness.main()`; ask.py is the other caller and was catching nothing.
    #
    # VERIFIED by the v3.1.0 reviewer with `_defaults` stubbed to succeed and
    # `_core` raising: the exception escaped `staleness_verdict` and reached the
    # user as a raw traceback with rc 1 — "the thing you asked about has
    # findings", when the truth is "this toolkit is not set up". That is exactly
    # the F39 confusion the block above documents, one call deeper. A 243-file
    # half-install really happened, which is why the installers have a CI step.
    try:
        return staleness.check(BASEX_DIR / f"coverage-{db}.json",
                               reference, extensions, engine, db)
    except (staleness.EngineUnavailable, ImportError) as exc:
        return staleness.Verdict(False, [str(exc)], db, determinable=False)


def _xq_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


_XQ_COMMENT = re.compile(r"\(:(?:(?!\(:|:\)).)*:\)", re.S)


def _strip_xq_comments(text: str) -> str:
    """The query with its XQuery comments removed. They nest, so the innermost go first."""
    prev = None
    while prev != text:
        prev, text = text, _XQ_COMMENT.sub("", text)
    return text


def _git_bash_argv_state() -> tuple[str | None, bool]:
    """(MSYSTEM, conversion switched off) for THIS process; see `argv_under_git_bash` in main().

    These describe the shell that launched this process and whether it rewrote our arguments.
    They are not configuration, so `_paths` is the wrong door: a value in x4-paths.env cannot
    say whether THIS invocation's argv was rewritten.
    """
    # env-ok: reads the launching shell's own markers (MSYSTEM, MSYS_NO_PATHCONV,
    # MSYS2_ARG_CONV_EXCL) -- a fact about this process, not configuration.
    env = os.environ
    # PRESENCE, not truthiness, on both -- MEASURED 2026-09-20 from Git Bash. With
    # `MSYSTEM=` (defined, empty) the runtime STILL rewrote argv (`//ware` arrived as
    # `/ware`), so `or None` switched this guard off while the rewrite continued: F122
    # reopened. And MSYS treats MSYS_NO_PATHCONV as SET when merely defined, so an empty
    # value means conversion is OFF and a zero is a REAL negative -- bool() read that as
    # "on" and refused it. Twins for both directions are in test_ask.py.
    msystem = env["MSYSTEM"] if "MSYSTEM" in env else None
    off = "MSYS_NO_PATHCONV" in env or env.get("MSYS2_ARG_CONV_EXCL", "").strip() == "*"
    return msystem, off


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
    p.add_argument("arg", nargs="?",
                   help="the id (refs), the attribute name (attr) or the XQuery text (xq)")
    p.add_argument("--file", default=None,
                   help="xq only: read the query from this file. Git Bash rewrites path-like parts "
                        "of command-line arguments (`//` becomes `/`) before Python sees them; a "
                        "file is not rewritten")
    p.add_argument("--db", default=None, choices=["x4raw", "x4eff"],
                   help="default: x4raw, the files AS WRITTEN (who wrote this, in which mod). "
                        "x4eff is the effective merged tree the engine sees: use it for any "
                        "claim about what is live")
    args = p.parse_args(argv)
    # Resolved HERE, from an explicit None, so the output can say when the as-written
    # database was searched only because nobody chose one (cold E2E agent, 2026-09-14).
    db_defaulted = args.db is None
    if db_defaulted:
        args.db = "x4raw"

    if args.mode == "xq":
        if (args.arg is None) == (args.file is None):
            p.error("xq takes its query EITHER as an argument OR with --file -- exactly one")
    else:
        if args.file is not None:
            p.error(f"--file is for xq only; {args.mode} takes its value as an argument")
        if args.arg is None or not args.arg.strip():
            p.error(f"{args.mode} needs a non-empty argument")
    query_text = args.arg
    if args.file is not None:
        try:
            # utf-8-sig: Notepad and Windows PowerShell 5.1 write a BOM, and BaseX rejects
            # U+FEFF with a context error that names the wrong cause (review, 2026-09-14).
            query_text = Path(args.file).read_bytes().decode("utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"error: cannot read the query file {args.file}: {exc}", file=sys.stderr)
            return 2
    # MEASURED 2026-09-14: from Git Bash, `ask.py xq 'count(collection("x4raw")//ware)'` reached
    # Python as `.../ware`, and `'//ware'` as `/ware` -- MSYS path conversion rewrites the
    # ARGUMENT before any of this runs, and nothing here can see what was typed. The zero
    # guard below then certified a negative over a query nobody wrote. Git Bash exports
    # MSYSTEM to its native children; a PowerShell started on its own does not (one started FROM
    # Git Bash inherits it and refuses too -- the safe direction, and --file still works).
    # refs/attr build their query here from an id or attribute name, so nothing crosses argv.
    # The conversion is wider than `//` -- a leading `/ware` arrives as `C:/Program Files/Git/ware`
    # -- and MSYS_NO_PATHCONV, or MSYS2_ARG_CONV_EXCL=*, switches it off, measured both ways
    # (review, 2026-09-14). The guard keys on the CHANNEL, never on a pattern in the query.
    if args.mode == "xq" and not _strip_xq_comments(query_text).strip():
        # An empty query returns an empty sequence, and the zero guard would certify it -- a
        # truncated or unsaved query file printed NEGATIVE CONFIRMED rc 0 (review, 2026-09-14).
        print("error: the xq query is empty (or only comments), so there is nothing to run; "
              "an empty result from it would not be a negative", file=sys.stderr)
        return 2
    msystem, conversion_off = _git_bash_argv_state()
    argv_under_git_bash = (args.mode == "xq" and args.file is None
                           and bool(msystem) and not conversion_off)

    xq = {"refs": q_refs, "attr": q_attr}.get(args.mode)
    query = xq(args.db, args.arg) if xq else query_text

    # `--db` chooses the coverage AND freshness denominator; the query text
    # chooses what is actually searched. If they disagree the result is scored
    # against the wrong world — which is exactly what this module's own
    # `load_coverage` docstring forbids ("they must never share one"). Found
    # end-to-end 2026-08-13: `xq "count(collection('x4eff')//macro)"` searched
    # x4eff, reported "in x4raw", and a STALE x4eff raised no warning because
    # x4raw happened to be fresh.
    # `collection(...)` is not the only spelling. BaseX addresses a database
    # directly with db:get('<name>') -- db:open before BaseX 10, and the vendored
    # jar is 12.4 -- and those walked past this guard entirely: a db:get('x4eff')
    # query ran against x4eff while being scored against x4raw's coverage AND
    # x4raw's freshness. That is the very failure this block exists to stop,
    # reached through a different spelling of the same intent.
    named = set(re.findall(
        r"(?:collection|db:get|db:open)\(\s*['\"]([^'\"]+)['\"]\s*\)", query))
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
        # The CHANGELOG promises every argument-query result shows what ARRIVED, and this
        # path owed it too: a leading `/` rewritten to `C:/Program Files/Git/...` is the
        # MSYS outcome most likely to ERROR rather than return a zero, and the error then
        # quotes the rewritten text without saying it was rewritten.
        if argv_under_git_bash:
            print(f"       query as received (Git Bash, MSYSTEM={msystem!r}): {query}",
                  file=sys.stderr)
            print("       Git Bash rewrites path-like parts of arguments; if that is not "
                  "what you typed, re-run with --file.", file=sys.stderr)
        # BaseX's own verdict stays above as the evidence; these lines add what it does
        # not say. MEASURED 2026-09-19: `xq --file` with `count(//ware)` reports
        # "[XPDY0002] .: Context value is undefined" -- true, and naming neither the
        # cause (an xq query addresses its own database; there is no implicit context
        # node) nor the cure. It is the same translation `preflight` already does for an
        # unbuilt DB's "[FODC0002] Resource not found", which never mentions
        # build-corpus.sh. Found by a cold, docs-only agent that reached for `//ware`
        # because CLAUDE.md sends you here without saying a query names its collection,
        # and the game-root file has 37 characters of budget left.
        #
        # Keyed to BaseX'S VERDICT, never to the query text. An earlier attempt read the
        # query for a `collection(` literal and pre-empted the run: it refused `1+1` --
        # legal, and needing no database -- plus every placeholder query in this module's
        # own tests, 22 red at once. Only the engine knows whether a context was actually
        # needed. Twins for both directions are in test_ask.py.
        if "XPDY0002" in str(exc) or "Context value is undefined" in str(exc):
            print("       That means the query names no database, so it had nothing "
                  "to search.", file=sys.stderr)
            print(f"       An xq query addresses its own: "
                  f"collection('{args.db}')//ware, not //ware.", file=sys.stderr)
            print(f"       --db {args.db} sets the coverage denominator, not the input.",
                  file=sys.stderr)
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
        # What the number counts. A docs-only agent read "3541 item(s) in x4eff." as wares
        # or files; it is XQuery items -- for `refs`, one matching element per line.
        if n_items is not None:
            print("  (an item is one node or value the query returned -- not a count of "
                  "files or entities)")
        # Not for `xq`: that query names its own collection, and the foreign-collection
        # guard above refuses a --db that disagrees, so "add --db x4eff" would be advice
        # that fails if followed (review, 2026-09-14).
        if argv_under_git_bash:
            print(f"  query as received (Git Bash, MSYSTEM={msystem}): {query}")
            print("  Git Bash rewrites path-like parts of arguments (`//` becomes `/`); if that is "
                  "not what you typed, "
                  "re-run with --file.")
        if db_defaulted and args.mode in ("refs", "attr"):
            print("  searched x4raw, the default: the files AS WRITTEN. For what the game "
                  "actually loads, add --db x4eff.")
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

    # Prior to every other refusal: they all judge the RESULT of a query, and this one says
    # the query that ran may not be the query that was typed (see argv_under_git_bash).
    if argv_under_git_bash:
        print("\n  ** NOT A NEGATIVE FINDING. ** This query arrived as a command-line argument")
        print(f"  under Git Bash (MSYSTEM={msystem}), which rewrites path-like parts")
        print("  of it (`//` becomes `/`, a leading `/x` becomes a Windows path)")
        print("  before Python sees it, so the query that ran may not be the one you typed:")
        print(f"    as received: {query}")
        print("  Put the query in a file and re-run with --file <path>; a file is not rewritten.")
        return 4

    # AN EMPTY SERIALIZATION IS NOT AN EMPTY SEQUENCE. `run_counted` returns
    # (output, None) when its count wrapper will not compile -- the documented
    # case being a query carrying its own prolog, so any query needing a
    # namespace declaration or a user-defined function. `hits` then falls back to
    # the LINE count, and three genuine matches that each serialize to a
    # zero-length string produce zero lines.
    #
    # MEASURED against real BaseX: that query printed
    #     NEGATIVE CONFIRMED over 2 of 2 documents (complete).   rc 0
    # while the identical query WITHOUT the prolog reported `3 item(s)`.
    #
    # The positive branch already says `item count unavailable` (that is what
    # `unit` is for); the zero branch computed `unit` and never used it, then
    # issued the guarantee. run_counted's own docstring required otherwise:
    # "The caller must then say the count is unavailable rather than quote the
    # line count as though it were meaningful."
    #
    # First of the refusals on this path, because it is prior to all of them: if
    # the count is unknown we do not know the result is empty at all, and a
    # denominator cannot help with a numerator nobody measured.
    if n_items is None:
        print("\n  ** NOT A NEGATIVE FINDING. ** 0 output lines, but the ITEM")
        print("  COUNT could not be obtained -- the count wrapper would not compile,")
        print("  which happens when the query carries its own prolog. An empty")
        print("  serialization is not an empty sequence: matches that serialize to")
        print("  zero-length strings produce no lines and are still matches.")
        print("  Re-run as count(...), or without the prolog, for a claim with a")
        print("  numerator behind it as well as a denominator.")
        return 4
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

    # A DENOMINATOR OF ZERO IS NOT A DENOMINATOR, and neither is an absent one.
    # The three guards above ask whether a coverage report EXISTS, whether it
    # CLAIMS to support a negative, and whether it is FRESH. None of them asks
    # whether it counted anything -- so a report answering yes to all three
    # printed the bare zero this tool exists to refuse, wearing the one sentence
    # that means it was checked:
    #
    #     NEGATIVE CONFIRMED over 0 of 0 documents (complete).      rc 0
    #     NEGATIVE CONFIRMED over None of None documents (complete). rc 0
    #
    # Both are reachable. None arrives whenever the key is absent, because
    # `cov.get('indexed', {}).get('total')` yields it and nothing re-checks.
    # Zero arrives from coverage.py, which validates its roots for NON-EMPTINESS
    # and never for EXISTENCE: a typo'd --reference makes count_disk_xml return 0
    # and publishes status 'complete' over nothing at all.
    #
    # `(expected or 0) - (indexed or 0)` below is what hid it: it turns None into
    # 0, so `missing` is falsey and the sentence ends '(complete).'
    if not isinstance(expected, int) or not isinstance(indexed, int) \
            or expected <= 0 or indexed <= 0:
        print("\n  ** NOT A NEGATIVE FINDING. ** The coverage report claims to")
        print(f"  support a negative claim, but its denominator is {indexed} of")
        print(f"  {expected} -- nothing was indexed, so 'zero hits' here cannot be")
        print("  distinguished from 'we never looked', which is the one distinction")
        print("  this tool exists to make.")
        print("  Rebuild the index (build-corpus.sh / build-effective.sh), and check")
        print("  that coverage.py's --reference and --extensions name directories")
        print("  that actually exist.")
        return 4

    missing = (expected or 0) - (indexed or 0)
    # THE EXCLUSIONS ARE A DIFFERENT AXIS FROM THE DOCUMENT COUNT, and reading only
    # the count is how a negative over an INCOMPLETE tree printed as complete. A
    # malformed overlay does not reduce `documents_total` -- that is written+copied,
    # and the document still exists, merely without that overlay applied -- so
    # `missing` is 0, the unparseable list never prints, and the sentence ends
    # "(complete)" while coverage.json carries a non-zero
    # negative_claim_excludes.unparseable_overlays.
    #
    # coverage.py publishes that field precisely so a caller can "RENDER the caveat
    # instead of reading a bare boolean" -- and no shipped caller asked. A disclosure
    # with no reader is decoration.
    excl = cov.get("negative_claim_excludes") or {}
    n_unparseable = excl.get("unparseable_overlays") or 0
    n_unbuilt = excl.get("vpaths_without_effective_tree") or 0
    print(f"\n  NEGATIVE CONFIRMED over {indexed} of {expected} documents"
          + (f" ({missing} excluded)." if missing
             else ("" if (n_unparseable or n_unbuilt) else " (complete).")))
    if n_unparseable or n_unbuilt:
        print("  ** NOT COMPLETE. ** This tree EXCLUDES:")
        if n_unparseable:
            print(f"      {n_unparseable} overlay(s) that would not parse")
        if n_unbuilt:
            print(f"      {n_unbuilt} vpath(s) with no effective tree")
        print("  so a zero here is a negative over the tree MINUS those, which is a")
        print("  narrower claim than the sentence above reads as. coverage.json ->")
        print("  negative_claim_excludes carries the counts; -> unparseable names them.")
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

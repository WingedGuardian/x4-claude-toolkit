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


#: The databases `--db` accepts, i.e. the only ones ask.py holds a coverage report for.
DBS = ("x4raw", "x4eff")

# --- what does the query ADDRESS? (AUDIT-2026-09-24 BX-1) ----------------------
#
# The coverage denominator describes a WHOLE database. A zero is a negative over that
# denominator only if the query searched that whole database, so ask.py reads every
# call that reaches a database and classifies it. MEASURED by the audit:
# `db:get('x4eff','no/such/typo.xml')//ware` printed "NEGATIVE CONFIRMED over 10970 of
# 10970 documents", rc 0 -- a zero over ONE path that does not exist, certified with the
# whole database's count. The old guard matched only `name('<db>')` with nothing after
# the literal, so a second argument, a variable db name and doc() all walked past it.
#
# Calls whose first argument names a database (BaseX's db module, and fn:collection /
# fn:uri-collection / fn:doc whose argument is `<db>[/<path>]`):
#: Always addresses a DOCUMENT or a node, never the whole database.
_DOC_FNS = ("doc", "db:get-id", "db:get-pre", "db:open-id", "db:open-pre",
            "db:get-value", "db:get-binary", "db:retrieve")
#: Whole database with one argument; a SECOND argument is a path inside it.
_PATH_ARG_FNS = ("db:get", "db:open", "db:list", "db:list-details", "db:dir", "db:exists")
#: Whole database whatever follows (index lookups, metadata).
_WHOLE_DB_FNS = ("db:text", "db:text-range", "db:attribute", "db:attribute-range",
                 "db:token", "db:info", "db:property")
#: `<db>` or `<db>/<path>` in the single literal argument.
_URI_FNS = ("collection", "uri-collection")
_REACH_FNS = _DOC_FNS + _PATH_ARG_FNS + _WHOLE_DB_FNS + _URI_FNS
_REACH_CALL = re.compile(
    r"(?<![\w:.\-])(?:fn:)?("
    + "|".join(re.escape(f) for f in sorted(_REACH_FNS, key=len, reverse=True))
    + r")\s*\(")
_LITERAL_ARG = re.compile(r"\s*(['\"])((?:(?!\1).|\1\1)*)\1\s*([,)])", re.S)


def _db_reaches(query: str) -> list[dict]:
    """Every call in *query* (comments already stripped) that reaches a database.

    Each is {"call", "db", "scoped"}: `db` is None when the name is not a string
    literal (a variable, a concatenation, no argument) -- then nobody can say which
    database was searched; `scoped` is True when the call addresses less than the
    whole database (a document, a node, a path inside it).
    """
    reaches = []
    for m in _REACH_CALL.finditer(query):
        fn = m.group(1)
        lit = _LITERAL_ARG.match(query, m.end())
        if lit is None:
            close = query.find(")", m.end())
            reaches.append({"call": query[m.start():close + 1 if close >= 0 else m.end()],
                            "db": None, "scoped": True})
            continue
        quote, after = lit.group(1), lit.group(3)
        value = lit.group(2).replace(quote * 2, quote)       # XQuery escapes '' / ""
        call = query[m.start():lit.end()] + ("" if after == ")" else "...)")
        if fn in _URI_FNS or fn == "doc":
            parts = [p for p in value.strip().split("/") if p]
            db = parts[0] if parts else None
            scoped = fn == "doc" or len(parts) > 1
        else:
            db = value.strip() or None
            scoped = fn in _DOC_FNS or (fn in _PATH_ARG_FNS and after == ",")
        reaches.append({"call": call, "db": db, "scoped": scoped or db is None})
    return reaches


# --- scope narrowed OUTSIDE the reach call's argument list (fu-ask, 2026-09-26) ---
#
# `_db_reaches` above only ever looks INSIDE a reach call's own parentheses --
# `doc(...)`, `db:get('<db>', '<path>')`, `collection('<db>/<path>')`. A query can
# narrow its scope just as effectively OUTSIDE that argument list, by testing a
# document-identity function in a predicate, a `where` clause, or a comparison:
#
#   collection('x4eff')[matches(document-uri(.),'libraries/wares')]//*[@id='x']
#   for $d in collection('x4eff') where contains(base-uri($d),'libraries/wares')
#       return $d//*[@id='x']
#
# MEASURED (two people): both printed "NEGATIVE CONFIRMED over 10970 of 10970
# documents", rc 0, over a query that in fact addressed 9 of them.
#
# Design choice, agreed rather than discovered: do not parse XQuery. Instead, name
# the functions whose result IDENTIFIES a document (or a node/path inside one) and
# refuse whenever one is used to TEST something -- inside a predicate `[...]`, a
# `where` clause, or as an operand of matches/contains/starts-with/ends-with or a
# comparison. A call that only APPEARS in the query (a `return`, an argument to an
# unrelated function, a simple-map `!` that merely emits it) is not itself a test
# and is left alone -- refusing those would refuse `for $d in collection('x4eff')
# return document-uri($d)`, which addresses the whole database and answers fine.
#
# `db:node-pre` / `db:node-id` are deliberately NOT in this set: they return a pre
# or id VALUE, not a document identity by themselves, and whether a given use of
# one narrows the scope needs judgement a text scan cannot make safely. Left as a
# named residual (see the fix's commit message), not silently "handled".
_IDENTITY_FNS = ("document-uri", "base-uri", "db:path")
_IDENTITY_CALL = re.compile(
    r"(?<![\w:.\-])(?:fn:)?(" + "|".join(re.escape(f) for f in _IDENTITY_FNS) + r")\s*\(")

#: A call whose argument being an identity call is itself the filtering test,
#: wherever it sits -- `matches(document-uri(.), 'x')` narrows the scope whether or
#: not it also sits inside a `[...]` predicate or a `where` clause.
_TEST_FNS = frozenset({"matches", "contains", "starts-with", "ends-with"})

#: Comparison operators/keywords: an identity call standing next to one of these is
#: being tested against a value, the same filtering shape as a `[...]` predicate.
# `=` never as part of `=>` (the arrow operator) or `:=` (a let / group-by binding):
# neither compares, and both used to refuse a query that narrows nothing.
_CMP_AFTER = re.compile(r"\s*(?:!=|<=|>=|=(?!>)|<|>|eq\b|ne\b|lt\b|gt\b|le\b|ge\b)")
_CMP_BEFORE = re.compile(
    r"(?:!=|<=|>=|(?<!:)=|<|>|(?<![\w:.\-])(?:eq|ne|lt|gt|le|ge))\s*\Z")

#: The identifier immediately before a `(`, if there is one -- used to name the
#: call whose argument list a position falls inside.
_CALL_OPEN = re.compile(r"([A-Za-z_][\w:.\-]*)\s*\(\Z")

#: A string literal's CONTENTS, single- or double-quoted, `''`/`""` doubling as the
#: XQuery escape for a literal quote char.
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", re.S)


def _blank_strings(text: str) -> str:
    """*text* with every string literal's CONTENTS replaced by 'x', same length,
    quotes kept in place -- so a literal that happens to spell a function name
    (`'see document-uri() in the docs'`) can neither trigger this scan nor a
    literal that hides a real one defeat it. Length and every other character's
    position are unchanged, so an offset into the result also indexes the
    original (comment-stripped) text.
    """
    return _STRING_LITERAL.sub(
        lambda m: m.group(0)[0] + "x" * (len(m.group(0)) - 2) + m.group(0)[-1], text)


def _matching_close(text: str, open_pos: int) -> int:
    """Index of the ')' matching the '(' at *open_pos*, or len(text) if unmatched."""
    depth = 0
    for i in range(open_pos, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return len(text)


def _predicate_mask(text: str) -> list[bool]:
    """True at every position at depth > 0 inside a `[ ... ]`.

    That is a predicate almost always, and an array constructor (same bracket)
    occasionally -- over-included on purpose, since this scan prefers refusing a
    query that turns out to be safe over missing one that is not.
    """
    mask = [False] * len(text)
    depth = 0
    for i, ch in enumerate(text):
        if ch == "[":
            depth += 1
            mask[i] = True
        elif ch == "]":
            mask[i] = depth > 0
            depth = max(0, depth - 1)
        else:
            mask[i] = depth > 0
    return mask


def _where_clause_spans(text: str) -> list[tuple[int, int]]:
    """[start, end) of every FLWOR `where` clause's condition.

    Found by tracking bracket/paren/brace depth from each `where` keyword forward
    to the next clause keyword (`return`, `for`, `let`, `where`, `order by`,
    `group by`, `count`, `window`) seen at the SAME depth -- enough to tell a
    `where` from a nested FLWOR's own `return` inside it, without parsing XQuery.
    """
    spans = []
    for m in re.finditer(r"(?<![\w:.\-])where(?![\w:.\-])", text):
        start = m.end()
        depth = 0
        end = len(text)
        i = start
        while i < len(text):
            ch = text[i]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                if depth == 0:
                    end = i
                    break
                depth -= 1
            elif depth == 0:
                km = re.match(r"(?:return|for|let|where|order\s+by|group\s+by|count|window)"
                              r"(?![\w:.\-])", text[i:])
                if km:
                    end = i
                    break
            i += 1
        spans.append((start, end))
    return spans


def _enclosing_call_names(text: str, positions: set[int]) -> dict[int, frozenset[str]]:
    """For each position of interest, the set of function names whose argument
    list encloses it -- one forward pass tracking '(' / ')' nesting. A '(' with no
    identifier immediately before it (a bare grouping paren, `if (`, `return (`)
    contributes an empty name and is otherwise harmless: nothing here tests for it.
    """
    found: dict[int, frozenset[str]] = {}
    stack: list[str] = []
    for i, ch in enumerate(text):
        if i in positions:
            found[i] = frozenset(stack)
        if ch == "(":
            m = _CALL_OPEN.search(text[:i + 1])
            stack.append(m.group(1) if m else "")
        elif ch == ")":
            if stack:
                stack.pop()
    return found


def _identity_narrowing(stripped_query: str) -> list[str]:
    """Every identity-function call in *stripped_query* (comments already gone)
    that narrows the scope OUTSIDE a reach call's own argument list: one used
    inside a predicate, a `where` clause, or a direct comparison / matches /
    contains / starts-with / ends-with test. One description per call found,
    naming the function, the snippet, and why it was flagged -- never why some
    OTHER call was not; a call this scan does not flag is simply not reported,
    which is not the same as proving it safe.
    """
    scan = _blank_strings(stripped_query)
    calls = list(_IDENTITY_CALL.finditer(scan))
    if not calls:
        return []
    pred_mask = _predicate_mask(scan)
    where_spans = _where_clause_spans(scan)
    starts = {m.start() for m in calls}
    enclosing = _enclosing_call_names(scan, starts)

    findings = []
    for m in calls:
        start = m.start()
        open_paren = m.end() - 1
        close_paren = _matching_close(scan, open_paren)
        reasons = []
        if pred_mask[start]:
            reasons.append("in a predicate")
        if any(s <= start < e for s, e in where_spans):
            reasons.append("in a where clause")
        test_fns = enclosing.get(start, frozenset()) & _TEST_FNS
        if test_fns:
            reasons.append("argument to " + "/".join(sorted(test_fns)))
        after = close_paren + 1
        if _CMP_AFTER.match(scan, after) or _CMP_BEFORE.search(scan[:start]):
            reasons.append("compared")
        if reasons:
            snippet = stripped_query[start:close_paren + 1]
            findings.append(f"{snippet} ({', '.join(reasons)})")
    return findings


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
    #
    # AUDIT-2026-09-24 BX-1 widened this from one regex to `_db_reaches`: a second
    # argument (a path), a db name held in a variable, and doc() all escaped it. Three
    # refusals, all rc 2 and all BEFORE the run, because each makes the per-database
    # coverage and freshness the wrong yardstick for the answer, positive or zero.
    #
    # fu-ask, 2026-09-26: `_db_reaches` only ever looks INSIDE a reach call's own
    # argument list. A query can narrow its scope just as effectively OUTSIDE it --
    # `collection('x4eff')[matches(document-uri(.),'libraries/wares')]` -- and MEASURED
    # (two people) printed a whole-database denominator over 9 of 10970 documents, rc 0.
    # `_identity_narrowing` catches that shape; see its docstring for what it does and
    # does not flag.
    stripped_query = _strip_xq_comments(query)
    reaches = _db_reaches(stripped_query)
    unknown = [r["call"] for r in reaches if r["db"] is None]
    foreign = sorted({r["db"] for r in reaches if r["db"] and r["db"] != args.db})
    scoped = [r["call"] for r in reaches if r["db"] and r["scoped"]]
    narrowing = _identity_narrowing(stripped_query)
    if unknown or foreign or scoped or narrowing:
        if unknown:
            print(f"error: the query names its database through an expression ask.py "
                  f"cannot read: {'; '.join(unknown)}", file=sys.stderr)
            print("       Which database was searched decides which coverage and "
                  "staleness apply, so it must be a string literal.", file=sys.stderr)
        if foreign:
            print(f"error: the query searches {', '.join(foreign)} but --db is "
                  f"'{args.db}'.", file=sys.stderr)
            print(f"       Coverage and staleness would be judged against "
                  f"'{args.db}', which is not what you queried.", file=sys.stderr)
        if scoped or narrowing:
            print(f"error: the query addresses PART of a database: "
                  f"{'; '.join(scoped + narrowing)}", file=sys.stderr)
            print("       The coverage denominator counts every document in the "
                  "database; a zero over one path is not a zero over those, and a "
                  "mistyped path matches nothing at all.", file=sys.stderr)
            if narrowing:
                print("       A document-identity function tested in a predicate, a "
                      "where clause, or a comparison narrows the scope the same way, "
                      "even though it never appears inside the reach call's own "
                      "argument list.", file=sys.stderr)
            print("       Search the whole database instead -- a negative over all of "
                  "it covers every path in it.", file=sys.stderr)
        # Advise only what argparse will accept: `--db x4eff/libraries` was once
        # printed here and following it was an argparse error (AUDIT-2026-09-24 BX-5).
        targets = [d for d in foreign if d in DBS] or ([args.db] if not foreign else [])
        bad = [d for d in foreign if d not in DBS]
        if bad:
            print(f"       ask.py holds coverage only for {' and '.join(DBS)}; it cannot "
                  f"score a query over {', '.join(bad)}.", file=sys.stderr)
        if len(targets) == 1 and len(set(foreign) - set(targets)) == 0:
            print(f"       Re-run over collection('{targets[0]}') with --db {targets[0]}.",
                  file=sys.stderr)
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

    # A VALUE COMPUTED FROM NOTHING IS NOT A HIT (AUDIT-2026-09-24 BX-5). `false` from
    # exists(...) and "" from string(...) over an empty sequence are one item each, and
    # were printed as "1 item(s)", rc 0 -- a positive answer to a question whose answer
    # was "none". Same family as the count()-of-nothing refusal below: one atomic value
    # that says "nothing", and the empty-sequence guard never ran. Items that all
    # serialize to nothing (n_items > 0, no output line) cannot be told apart from
    # such values either, so they are not a hit -- and not a negative.
    if n_items and not lines:
        print(f"{n_items} item(s) in {args.db}, every one of them serializing to an "
              f"empty string.")
        print("\n  ** NOT A FINDING EITHER WAY. ** An empty string is a VALUE, not a")
        print("  match: string(...) of nothing returns one. It is not an empty")
        print("  sequence either, so the denominator guard did not run. Re-run returning")
        print("  the nodes themselves for an answer with coverage behind it.")
        return 4
    if n_items == 1 and [ln.strip() for ln in lines] == ["false"]:
        print("false")
        print(f"\n1 item(s) in {args.db}.")
        print("\n  ** NOT A NEGATIVE FINDING. ** That is one boolean, not one match:")
        print("  exists(...)/boolean(...) return false when they found nothing, and the")
        print("  denominator guard applies to an EMPTY SEQUENCE, so it did not run.")
        print("  Re-run returning the nodes themselves -- drop the exists(...) wrapper --")
        print("  for a claim with coverage behind it.")
        return 4

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

    # A QUERY THAT NAMES NO DATABASE SEARCHED NONE (AUDIT-2026-09-24 BX-1). `()` or
    # `let $x := () return $x` returns an empty sequence without reading one document,
    # and the denominator below describes a database it never touched. refs/attr always
    # name --db; an xq query must name it itself (`collection('<db>')`). Checked LAST so
    # every refusal above still speaks for its own reason.
    if not reaches:
        print("\n  ** NOT A NEGATIVE FINDING. ** The query names no database -- no")
        print(f"  collection('{args.db}'), no db:get('{args.db}') -- so its empty result")
        print(f"  is not a search of {args.db}, and {indexed} of {expected} documents is not")
        print("  its denominator. Address the database in the query and re-run.")
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

"""Tests for ask.py's counting and negative-claim contract.

Run:  cd tools\\basex && python -m pytest test_ask.py -q

No BaseX and no JVM required — `run_xq` is monkeypatched, because what is under
test is the counting and the guard, not XQuery evaluation.

Background (audit 2026-08-01, finding F9): "hits" was `len(output_lines)`, which
is unrelated to the number of matches — 847 occurrences across 4 documents
printed as "32 hit(s)". Worse, the zero-result guard keyed off that same empty
line list, so `count(...)` returning 0 emitted the single line "0", the guard
never ran, and a zero result rendered as "1 hit(s)" with exit 0 — the exact false
positive this tool exists to prevent, reached by its most natural phrasing.
"""
from __future__ import annotations

import pytest

import ask


@pytest.fixture(autouse=True)
def _preflight_is_satisfied(monkeypatch):
    """Neutralise the environment preflight for every test in this module.

    `ask.main()` checks the jar and the database BEFORE running a query (F47), so
    without this, every test that goes through `main()` exits 2 on a machine with
    no index built -- and passes on a machine that has one.

    MEASURED 2026-08-25, and the reason this exists: 9 of these tests were green
    on the development machine and red on a fresh checkout of the same commit.
    Their verdict was coming from whether a multi-GB database happened to exist,
    not from anything in the fixture. A test whose answer depends on mutable state
    outside itself is not testing what its name says.

    Neutralising the preflight here is only safe because the wiring is pinned
    separately by `test_the_preflight_is_actually_wired_into_main` below. Without
    that companion this fixture would be a way to silently delete a guard.
    """
    monkeypatch.setattr(ask.preflight, "check", lambda *a, **k: [])


def test_the_preflight_is_actually_wired_into_main(monkeypatch, capsys):
    """The falsification twin for the fixture above.

    If `main()` ever stopped consulting the preflight, every other test here would
    still pass -- they stub it out. This one fails instead.
    """
    monkeypatch.setattr(ask.preflight, "check",
                        lambda *a, **k: ["synthetic problem: the environment is not ready"])
    rc = ask.main(["xq", "1+1", "--db", "x4raw"])
    assert rc == 2, "an unusable environment must refuse with 2 (not configured), never 0 or 1"
    assert "synthetic problem" in capsys.readouterr().err


def _fake_basex(monkeypatch, payload: str, *, wrap_fails: bool = False):
    """Stand in for BaseX. Honours the count wrapper the way BaseX would."""
    def fake(q: str) -> str:
        if ask._SEP in q:
            if wrap_fails:
                raise RuntimeError("[XPST0003] Static error: simulated prolog clash")
            items = [] if not payload else payload.split("\n")
            return f"{len(items)}\n{ask._SEP}\n{payload}"
        return payload
    monkeypatch.setattr(ask, "run_xq", fake)


# --- counting -----------------------------------------------------------------

def test_item_count_is_items_not_lines(monkeypatch):
    _fake_basex(monkeypatch, "a\nb\nc")
    out, n = ask.run_counted("//whatever")
    assert n == 3 and out == "a\nb\nc"


def test_empty_result_counts_zero(monkeypatch):
    _fake_basex(monkeypatch, "")
    _, n = ask.run_counted("//nothing")
    assert n == 0


def test_uncompilable_wrapper_reports_unknown_not_a_wrong_number(monkeypatch):
    """A count we could not take must be None so the caller says so, rather than
    quoting the line count as though it meant something."""
    _fake_basex(monkeypatch, "a\nb", wrap_fails=True)
    out, n = ask.run_counted("declare namespace x = 'urn:x'; //a")
    assert n is None and out == "a\nb"


def test_separator_is_a_legal_xml_character():
    """U+0001 is not a legal XML character: using it made the wrapper fail to
    compile, which silently cost the count on every single query."""
    assert ask._SEP.isprintable() and ask._SEP not in ("", " ")


# --- the negative-claim contract ---------------------------------------------

def test_zero_count_query_refuses_to_render_a_negative(monkeypatch, capsys):
    """The headline: count() of nothing must NOT read as a hit, and must not
    quietly bypass the coverage guard."""
    _fake_basex(monkeypatch, "0")
    rc = ask.main(["xq", "count(//nothing)"])
    text = capsys.readouterr().out
    assert rc == 4, "must refuse, not return success"
    assert "NOT A NEGATIVE FINDING" in text
    assert "one atomic value, not one" in text


def test_empty_sequence_still_reaches_the_coverage_guard(monkeypatch, capsys):
    """The other side: the guard must still fire for a genuinely empty result."""
    _fake_basex(monkeypatch, "")
    monkeypatch.setattr(ask, "load_coverage", lambda db: {
        "db": db, "status": "complete", "supports_negative_claim": True,
        "indexed": {"total": 100}, "expected": {"total": 100}, "unparseable": [],
    })
    # Staleness is a SEPARATE gate (added 2026-08-13) and would otherwise refuse
    # here on the real on-disk fingerprint. Pin it so this test keeps testing the
    # coverage guard rather than whatever the local databases happen to be.
    _stale(monkeypatch, fresh=True)
    rc = ask.main(["xq", "//nothing"])
    text = capsys.readouterr().out
    assert rc == 0 and "NEGATIVE CONFIRMED over 100 of 100" in text


def test_a_real_nonzero_result_is_not_second_guessed(monkeypatch, capsys):
    """A count() returning a REAL number is a positive answer; only zero is the
    trap. Pins that the refusal is not fired indiscriminately."""
    _fake_basex(monkeypatch, "42")
    rc = ask.main(["xq", "count(//something)"])
    text = capsys.readouterr().out
    assert rc == 0 and "NOT A NEGATIVE FINDING" not in text


def test_missing_coverage_still_refuses(monkeypatch, capsys):
    _fake_basex(monkeypatch, "")
    monkeypatch.setattr(ask, "load_coverage", lambda db: {})
    rc = ask.main(["xq", "//nothing"])
    assert rc == 4 and "No coverage report" in capsys.readouterr().out


# --- staleness: an index that no longer describes the world -------------------

def _stale(monkeypatch, fresh: bool):
    """Force ask.py's staleness verdict without touching the real DBs."""
    import staleness
    monkeypatch.setattr(
        ask, "staleness_verdict",
        lambda db: staleness.Verdict(fresh, [] if fresh else ["engine changed: test"], db))


def test_a_stale_index_warns_even_on_a_POSITIVE_result(monkeypatch, capsys):
    """The user's requirement: warn every time it is run, until rebuilt. A
    positive answer from a stale index is still an answer about a world that has
    moved on -- silence here is what let x4eff serve 858 wrong values for 11 days."""
    _fake_basex(monkeypatch, "hit-one\nhit-two")
    _stale(monkeypatch, fresh=False)
    rc = ask.main(["xq", "//x"])
    cap = capsys.readouterr()          # capture ONCE: readouterr() resets the buffers,
    out = cap.out + cap.err            # so calling it twice discards stderr
    assert "STALE INDEX" in out, "a stale index answered without saying so"
    assert rc == 0, "a positive result still stands; it is warned about, not withheld"


def test_a_stale_index_REFUSES_to_render_a_negative(monkeypatch, capsys):
    """Same contract as missing coverage: a zero-result needs a denominator, and
    a denominator from a superseded world is not one."""
    _fake_basex(monkeypatch, "")
    monkeypatch.setattr(ask, "load_coverage", lambda db: {
        "db": db, "status": "complete", "supports_negative_claim": True,
        "indexed": {"total": 100}, "expected": {"total": 100}, "unparseable": [],
    })
    _stale(monkeypatch, fresh=False)
    rc = ask.main(["xq", "//x"])
    out = capsys.readouterr().out
    assert rc == 4, "a negative from a stale index must not be admissible"
    assert "NOT A NEGATIVE FINDING" in out


def test_a_fresh_index_says_nothing_extra(monkeypatch, capsys):
    """The banner must not become background noise, or it stops being read."""
    _fake_basex(monkeypatch, "hit-one")
    _stale(monkeypatch, fresh=True)
    ask.main(["xq", "//x"])
    assert "STALE INDEX" not in capsys.readouterr().out


def test_a_query_naming_a_DIFFERENT_collection_than_db_is_refused(monkeypatch, capsys):
    """`--db` picks the coverage AND freshness denominator; the query text picks
    what is actually searched. When they disagree the answer is scored against
    the wrong world -- `ask.py`'s own docstring says the two databases "must never
    share" a denominator, and this is how they silently did.

    Found end-to-end 2026-08-13: `ask.py xq "count(collection('x4eff')//macro)"`
    ran against x4eff while reporting "in x4raw", and a stale x4eff produced no
    warning because x4raw was fresh."""
    _fake_basex(monkeypatch, "5")
    _stale(monkeypatch, fresh=True)
    rc = ask.main(["--db", "x4raw", "xq", "count(collection('x4eff')//macro)"])
    cap = capsys.readouterr()
    text = cap.out + cap.err
    assert rc == 2, "a denominator/query mismatch must not answer"
    assert "x4eff" in text and "--db" in text


def test_a_query_naming_the_SAME_collection_is_fine(monkeypatch, capsys):
    _fake_basex(monkeypatch, "5")
    _stale(monkeypatch, fresh=True)
    rc = ask.main(["--db", "x4eff", "xq", "count(collection('x4eff')//macro)"])
    assert rc == 0


# --- freshness that cannot be DETERMINED (distinct from stale) ----------------

def _undeterminable(monkeypatch):
    """Make the freshness check itself fail, the way an unconfigured machine does.

    Patches the REAL seam (`staleness._defaults`) rather than `ask.staleness_verdict`,
    because the latter is the function under test -- patching it would prove only
    that the test can patch things.
    """
    import staleness

    def boom():
        raise staleness.EngineUnavailable(
            "cannot resolve reference and extensions")
    monkeypatch.setattr(staleness, "_defaults", boom)


def test_undeterminable_freshness_is_UNKNOWN_not_a_traceback(monkeypatch, capsys):
    """MEASURED 2026-08-24 on a proven-cold checkout: raw traceback, rc **1**.

    rc 1 is the damaging part. In this toolkit it means "the thing you asked about
    has findings"; the truth was "this toolkit is not set up", and those demand
    opposite responses. Same defect F39 removed from the CLIs, still alive here.

    A positive result still STANDS -- the query ran and BaseX answered. What is
    unknown is whether the index still describes the world, and the honest move is
    to say so rather than to withhold a real answer or to imply a freshness nobody
    established.
    """
    _undeterminable(monkeypatch)
    _fake_basex(monkeypatch, "hit-one\nhit-two")
    rc = ask.main(["xq", "//x"])
    cap = capsys.readouterr()
    both = cap.out + cap.err
    assert "Traceback" not in both, "an unconfigured machine got a raw traceback"
    assert rc == 0, "a positive result still stands; freshness is a caveat, not a veto"
    assert "UNKNOWN" in both.upper(), "silence would imply a freshness nobody established"


def test_undeterminable_freshness_REFUSES_to_render_a_negative(monkeypatch, capsys):
    """Same contract as stale and as missing coverage: a zero needs a denominator,
    and a denominator whose currency cannot be established is not one."""
    _undeterminable(monkeypatch)
    _fake_basex(monkeypatch, "")
    monkeypatch.setattr(ask, "load_coverage", lambda db: {
        "db": db, "status": "complete", "supports_negative_claim": True,
        "indexed": {"total": 100}, "expected": {"total": 100}, "unparseable": [],
    })
    rc = ask.main(["xq", "//x"])
    cap = capsys.readouterr()
    assert "Traceback" not in cap.out + cap.err
    assert rc == 4, "a negative from an index of unknown currency must not be admissible"


# --- the denominator FLOOR (Track 2 audit, 2026-09-06) ------------------------
#
# The three guards above this point ask "is there a coverage report", "does it
# claim to support a negative", and "is it fresh". None of them asks whether the
# denominator is a NUMBER GREATER THAN ZERO -- so a report that answered yes to
# all three published the bare zero this tool exists to refuse, wearing the one
# sentence that means it was checked.
#
# Both shapes are reachable, not hypothetical:
#   * None -- `cov.get("indexed", {}).get("total")` yields None whenever the key
#     is absent, and nothing downstream re-checks it.
#   * 0    -- coverage.py validates --reference/--extensions for NON-EMPTINESS
#     and never for EXISTENCE, and count_disk_xml returns 0 for a root that is
#     not a directory. A typo'd path therefore publishes
#     {"expected": {"total": 0}, "indexed": {"total": 0}, "status": "complete",
#      "supports_negative_claim": true}, which is precisely this input.

def test_a_ZERO_denominator_is_refused_not_confirmed(monkeypatch, capsys):
    """`NEGATIVE CONFIRMED over 0 of 0 documents (complete).` with rc 0.

    Nothing was indexed, so "zero hits" cannot be distinguished from "we never
    looked" -- the founding distinction of this tool, inverted by its own verdict
    line.
    """
    _fake_basex(monkeypatch, "")
    monkeypatch.setattr(ask, "load_coverage", lambda db: {
        "db": db, "status": "complete", "supports_negative_claim": True,
        "indexed": {"total": 0}, "expected": {"total": 0}, "unparseable": [],
    })
    _stale(monkeypatch, fresh=True)
    rc = ask.main(["xq", "//nothing"])
    text = capsys.readouterr().out
    assert "NEGATIVE CONFIRMED" not in text, (
        "a denominator of zero was rendered as a confirmed negative")
    assert rc == 4 and "NOT A NEGATIVE FINDING" in text


def test_an_ABSENT_denominator_is_refused_not_confirmed(monkeypatch, capsys):
    """The other shape: `NEGATIVE CONFIRMED over None of None documents`.

    A coverage report missing its `indexed`/`expected` keys reaches the verdict
    line with None on both sides, and `(expected or 0) - (indexed or 0)` quietly
    turns that into 0, so the sentence reads `(complete)`.
    """
    _fake_basex(monkeypatch, "")
    monkeypatch.setattr(ask, "load_coverage", lambda db: {
        "db": db, "status": "complete", "supports_negative_claim": True,
        "unparseable": [],
    })
    _stale(monkeypatch, fresh=True)
    rc = ask.main(["xq", "//nothing"])
    text = capsys.readouterr().out
    assert "NEGATIVE CONFIRMED" not in text, (
        "an absent denominator was rendered as a confirmed negative")
    assert "None of None" not in text
    assert rc == 4 and "NOT A NEGATIVE FINDING" in text


def test_the_floor_does_not_over_fire_on_a_REAL_denominator(monkeypatch, capsys):
    """The falsification twin for the two above.

    A floor that refused everything would make them pass while deleting the
    feature. One real document is enough to support a negative, and must still
    read as one.
    """
    _fake_basex(monkeypatch, "")
    monkeypatch.setattr(ask, "load_coverage", lambda db: {
        "db": db, "status": "complete", "supports_negative_claim": True,
        "indexed": {"total": 1}, "expected": {"total": 1}, "unparseable": [],
    })
    _stale(monkeypatch, fresh=True)
    rc = ask.main(["xq", "//nothing"])
    text = capsys.readouterr().out
    assert rc == 0 and "NEGATIVE CONFIRMED over 1 of 1" in text


# --- the cross-DB guard knows only ONE spelling (Track 2 audit, 2026-09-06) ---

def test_a_foreign_db_named_via_db_get_is_refused(monkeypatch, capsys):
    """`collection('x4eff')` is not the only way to name a database.

    BaseX addresses one directly with `db:get('<name>')` (`db:open` before BaseX
    10; the vendored jar is 12.4). The guard's regex matched `collection(...)`
    only, so a `db:get('x4eff')` query ran against x4eff while being scored
    against x4raw's coverage AND x4raw's freshness -- the exact failure the guard
    was written for in the first place, reached through a different spelling.
    """
    _fake_basex(monkeypatch, "5")
    _stale(monkeypatch, fresh=True)
    rc = ask.main(["--db", "x4raw", "xq", "db:get('x4eff')//macro"])
    cap = capsys.readouterr()
    text = cap.out + cap.err
    assert rc == 2, "a db:get() naming another database was answered, not refused"
    assert "x4eff" in text and "--db" in text


def test_the_legacy_db_open_spelling_is_refused_too(monkeypatch, capsys):
    """BaseX 10 renamed db:open to db:get. Habit and older notes still use the
    old name, and the guard should not depend on which one the caller reached for."""
    _fake_basex(monkeypatch, "5")
    _stale(monkeypatch, fresh=True)
    rc = ask.main(["--db", "x4raw", "xq", "db:open('x4eff')//macro"])
    assert rc == 2


def test_db_get_naming_the_SAME_database_is_fine(monkeypatch, capsys):
    """The falsification twin: a guard that refused every db:get() would make the
    two above pass while breaking the ordinary case."""
    _fake_basex(monkeypatch, "5")
    _stale(monkeypatch, fresh=True)
    rc = ask.main(["--db", "x4raw", "xq", "db:get('x4raw')//macro"])
    assert rc == 0, "a db:get() naming the queried database must not be refused"


# --- an unavailable item count cannot confirm anything ------------------------

def test_an_UNAVAILABLE_item_count_cannot_confirm_a_negative(monkeypatch, capsys):
    """`run_counted` returns (output, None) when its count wrapper will not
    compile -- the documented case being a query carrying its own prolog, i.e.
    any query needing a namespace declaration or a user-defined function.

    The positive branch honestly labels the number `output line(s), item count
    unavailable`. The zero branch dropped that caveat entirely -- `unit` is
    computed and never used there -- and issued the guarantee anyway. MEASURED
    against real BaseX: three genuine matches, each serializing to a zero-length
    string, printed `NEGATIVE CONFIRMED over 2 of 2 documents (complete).` with
    rc 0, while the identical query without the prolog reported `3 item(s)`.

    An empty SERIALIZATION is not an empty SEQUENCE, and this is exactly what
    `run_counted`'s own docstring already required of its caller: "The caller must
    then say the count is unavailable rather than quote the line count as though
    it were meaningful."
    """
    _fake_basex(monkeypatch, "", wrap_fails=True)
    monkeypatch.setattr(ask, "load_coverage", lambda db: {
        "db": db, "status": "complete", "supports_negative_claim": True,
        "indexed": {"total": 100}, "expected": {"total": 100}, "unparseable": [],
    })
    _stale(monkeypatch, fresh=True)
    rc = ask.main(["xq", "//nothing"])
    text = capsys.readouterr().out
    assert "NEGATIVE CONFIRMED" not in text, (
        "a negative was confirmed while the item count was unavailable")
    assert rc == 4 and "NOT A NEGATIVE FINDING" in text
    # This names a phrase the output does NOT line-wrap. The first draft
    # asserted a two-word phrase the message splits across two lines, so it
    # failed against a correct fix -- the checker, not the subject.
    assert "serialization is not an empty sequence" in text

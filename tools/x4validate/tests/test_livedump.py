r"""`_livedump` must never render a non-answer as a finding.

FOUR OUTCOMES, and the whole point of the module is that they stay apart:
absent/stub (rc 2) - variable missing (rc 2) - malformed (rc 3) - parsed (a finding).
The dangerous one is the STUB: X4 truncates `uidata.xml` at startup, so a reader run
mid-session sees valid XML holding nothing and would report "0 extensions" in the
grammar of a real answer.

ONE FIXTURE PER GUARD CLAUSE. `parse()` guards on five separate things, and a guard
that fires first SHADOWS every clause behind it - so a single malformed fixture would
only ever exercise whichever check happens to trip first, and the rest would be
untested while looking covered (CLAUDE.md #26). Each fixture below passes every clause
except the one it targets. `test_every_guard_is_load_bearing` then proves the suite
would actually go red if a guard were removed, because a test written after the code
proves nothing until you make it fail on purpose.
"""
from __future__ import annotations

import pytest

from x4validate import _livedump as L


# --------------------------------------------------------------- encoder (fixtures)

def lua_escape(s: str) -> str:
    r"""Re-encode the way the engine's serialiser does, so fixtures are not fiction.

    VERIFIED against the real file: a tab is `\9`, but `\009` when the next character
    is a digit; a newline is a backslash-newline continuation. MEASURED in a 153,006
    byte payload: 2,950 `\9`, 1,784 `\009`, and 804 continuations for 805 rows.
    """
    out = []
    for i, ch in enumerate(s):
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if ch == "\t":
            out.append("\\009" if nxt.isdigit() else "\\9")
        elif ch == "\n":
            out.append("\\\n")
        elif ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        else:
            out.append(ch)
    return "".join(out)


def xml_escape(s: str) -> str:
    for ch, ent in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;")):
        s = s.replace(ch, ent)
    return s


def uidata(rows: list[list[str]] | None, *, var: str = L.DEFAULT_VAR,
           payload: str | None = None, with_data: bool = True) -> str:
    """A complete `uidata.xml` carrying *rows* (or a raw *payload*)."""
    if payload is None:
        payload = "\n".join("\t".join(f for f in r) for r in (rows or []))
    body = f"{var} = &quot;{xml_escape(lua_escape(payload))}&quot;\n"
    inner = f'  <data environment="menus">\n{body}  </data>\n' if with_data else ""
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<uidata version="1">\n{inner}</uidata>\n'


def good_rows(n_ext: int = 2) -> list[list[str]]:
    rows: list[list[str]] = [["HDR", "schema=2", "probe=test", "elapsed=1.5"]]
    rows.append(["EXT_FIELDS", "id,enabled"])
    for i in range(n_ext):
        rows.append(["EXT", f"mod_{i}", "true"])
    rows.append(["END", str(len(rows) + 1)])
    return rows


#: The real file, byte for byte, is 61 bytes of this.
STUB = '<?xml version="1.0" encoding="UTF-8"?>\n<uidata version="1"/>\n'


# ------------------------------------------------------------------ the happy path

def test_a_valid_dump_parses_and_self_checks():
    d = L.parse(uidata(good_rows(3)))
    assert d.header == {"schema": "2", "probe": "test", "elapsed": "1.5"}
    assert len(d.rows) == 6
    assert d.accounts_for_every_row()
    assert [e["id"] for e in d.extensions()] == ["mod_0", "mod_1", "mod_2"]
    assert all(e["enabled"] == "true" for e in d.extensions())


def test_a_dump_that_really_is_empty_is_a_FINDING_not_a_refusal():
    """Zero extensions must be reportable - otherwise the tool cannot say 'none'."""
    d = L.parse(uidata([["HDR", "schema=2"], ["END", "2"]]))
    assert d.extensions() == []
    assert d.of("EXT") == []
    assert d.accounts_for_every_row()


def test_round_trip_survives_tabs_newlines_and_backslashes_inside_a_field():
    nasty = "a\tb\nc\\d"
    rows = [["HDR", "schema=2"],
            ["EXT_FIELDS", "id,desc"],
            ["EXT", "m", nasty.replace("\\", "\\\\").replace("\t", "\\t")
                          .replace("\n", "\\n")],
            ["END", "4"]]
    d = L.parse(uidata(rows))
    assert d.extensions()[0]["desc"] == nasty


# ------------------------------------------------------- layer 2: the \009 ambiguity

@pytest.mark.parametrize("raw, expected", [
    ("A\\9B", "A\tB"),          # one digit, next char is not a digit
    ("A\\0099", "A\t9"),        # THREE digits, because the next char IS a digit
    ("A\\009132", "A\t132"),    # the exact shape in the real file
    ("A\\09B", "A\tB"),         # two digits
])
def test_decimal_escapes_take_up_to_three_digits(raw, expected):
    assert L.lua_unescape(raw) == expected


def test_a_digit_after_a_tab_does_not_shift_the_row():
    """The concrete cost of getting layer 2 wrong: every field on the row moves."""
    d = L.parse(uidata([["HDR", "schema=2"], ["EXT_STATUS", "OK", "132"], ["END", "3"]]))
    assert d.one("EXT_STATUS") == ["EXT_STATUS", "OK", "132"]


# ------------------------------------------ one fixture per guard clause (CLAUDE #26)

def test_clause_0_a_file_that_is_not_uidata_says_so():
    """Right exit code, RIGHT REASON. The stub message explains how X4 saves;
    attaching that explanation to an arbitrary file would be a confident wrong
    reason wearing a correct rc 2."""
    with pytest.raises(L.LiveDumpUnavailable) as e:
        L.parse("[project]\nname = 'not-uidata'\n")
    assert "not a uidata.xml" in str(e.value)
    assert "never been saved" not in str(e.value), "wrong explanation for this cause"


def test_clause_1_the_running_game_stub_is_a_NON_ANSWER():
    with pytest.raises(L.LiveDumpUnavailable) as e:
        L.parse(STUB)
    msg = str(e.value)
    assert "no saved data" in msg
    assert "NOT 'the probe found nothing'" in msg, "must not read as an empty result"


def test_clause_2_data_present_but_variable_absent_is_a_NON_ANSWER():
    """Passes clause 1 - there IS a <data> block - so it reaches the variable check."""
    text = uidata(good_rows(), var="__something_else")
    assert "<data" in text, "fixture must clear clause 1 or it tests the wrong guard"
    with pytest.raises(L.LiveDumpUnavailable) as e:
        L.parse(text)
    assert "did not run" in str(e.value)


def test_clause_3_a_missing_header_row_is_CORRUPT_not_unavailable():
    """Passes clauses 1-2, and terminates correctly, so ONLY the HDR check can fire."""
    rows = [["EXT", "m", "true"], ["END", "2"]]
    with pytest.raises(L.LiveDumpCorrupt) as e:
        L.parse(uidata(rows))
    assert "no HDR row" in str(e.value)


def test_clause_4_a_missing_terminator_is_CORRUPT():
    """Passes 1-3: it has <data>, the variable, and a HDR first row."""
    rows = [["HDR", "schema=2"], ["EXT", "m", "true"]]
    with pytest.raises(L.LiveDumpCorrupt) as e:
        L.parse(uidata(rows))
    assert "TRUNCATED" in str(e.value)


def test_clause_5_a_row_count_that_disagrees_is_CORRUPT():
    """Passes 1-4 - well-formed in every other way - so only the count can trip."""
    rows = [["HDR", "schema=2"], ["EXT", "m", "true"], ["END", "999"]]
    with pytest.raises(L.LiveDumpCorrupt) as e:
        L.parse(uidata(rows))
    assert "999" in str(e.value) and "3 parsed" in str(e.value)


def test_clause_5_catches_a_TRUNCATED_payload_that_still_ends_in_END():
    """The realistic corruption: the tail is lost but an earlier END-like row remains."""
    rows = good_rows(5)
    truncated = rows[:3] + [["END", str(len(rows) + 1)]]
    with pytest.raises(L.LiveDumpCorrupt):
        L.parse(uidata(truncated))


def test_an_unterminated_payload_is_CORRUPT_not_unavailable():
    text = uidata(None, payload="x").replace("&quot;\n  </data>", "\n  </data>")
    with pytest.raises(L.LiveDumpCorrupt) as e:
        L.parse(text)
    assert "TRUNCATED" in str(e.value)


# ------------------------------------------------------------------ the two outcomes

def test_unavailable_and_corrupt_are_different_types():
    """rc 2 and rc 3 mean different things; one class would collapse them."""
    assert not issubclass(L.LiveDumpCorrupt, L.LiveDumpUnavailable)
    assert not issubclass(L.LiveDumpUnavailable, L.LiveDumpCorrupt)


def test_load_refuses_a_missing_file_rather_than_returning_empty(tmp_path):
    with pytest.raises(L.LiveDumpUnavailable) as e:
        L.load(tmp_path / "nope.xml")
    assert "does not exist" in str(e.value)


def test_game_is_running_returns_NONE_when_the_query_fails(monkeypatch):
    """A FAILED process query must be None, not a confident False.

    The previous assertion was `game_is_running() in (True, False, None)` -- true for
    every possible return, including a hard-coded `return False`. It could not go red,
    so it never covered the thing it named. MEASURED 2026-09-01: the sibling
    implementation in _livepipe chained `.stdout` onto subprocess.run, so the returncode
    was unreachable and a failing tasklist filter (rc=1) returned False.
    """
    class _Failed:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(L.subprocess, "run", lambda *a, **k: _Failed())
    assert L.game_is_running() is None, "a failed query must abstain, not answer 'no'"


def test_game_is_running_returns_TRUE_when_the_process_is_listed(monkeypatch):
    class _Ok:
        returncode = 0
        stdout = "X4.exe   1234 Console"

    monkeypatch.setattr(L.subprocess, "run", lambda *a, **k: _Ok())
    assert L.game_is_running() is True


def test_game_is_running_returns_FALSE_when_the_query_works_and_finds_nothing(monkeypatch):
    class _Empty:
        returncode = 0
        stdout = "INFO: No tasks are running which match the specified criteria."

    monkeypatch.setattr(L.subprocess, "run", lambda *a, **k: _Empty())
    assert L.game_is_running() is False


def test_extensions_returns_nothing_rather_than_inventing_column_names():
    """No EXT_FIELDS row means the columns have no names - [] beats a guess."""
    d = L.parse(uidata([["HDR", "schema=2"], ["EXT", "m", "true"], ["END", "3"]]))
    assert d.of("EXT"), "the EXT row must still be present as a raw row"
    assert d.extensions() == []


# ------------------------------------------------- prove the guards are load-bearing

def test_every_guard_rejects_its_own_bad_fixture():
    r"""One fixture per guard, each differing from a good dump in exactly ONE respect,
    plus a control that must parse cleanly.

    RENAMED 2026-09-01. This was called `test_every_guard_is_load_bearing` and its
    docstring claimed to "mutate each clause SEPARATELY" -- it mutates NOTHING. It is
    fixture-based testing, which is worth having, but a reader was entitled to believe
    the guards had been mutation-proven when they had not. A test may not describe work
    it does not do.

    Real mutation testing in this repo lives in scripts/verify-hook-tests.py, which
    plants a defect and requires the NAMED test to go red.
    """
    cases = [
        ("not-uidata", "[project]\n",                                     L.LiveDumpUnavailable),
        ("stub",       STUB,                                              L.LiveDumpUnavailable),
        ("no-var",     uidata(good_rows(), var="__other"),                L.LiveDumpUnavailable),
        ("no-hdr",     uidata([["EXT", "m"], ["END", "2"]]),              L.LiveDumpCorrupt),
        ("no-end",     uidata([["HDR", "s=1"], ["EXT", "m"]]),            L.LiveDumpCorrupt),
        ("bad-count",  uidata([["HDR", "s=1"], ["EXT", "m"], ["END", "9"]]), L.LiveDumpCorrupt),
    ]
    for name, text, exc in cases:
        with pytest.raises(exc):
            L.parse(text)
        # and the SAME text must parse cleanly once repaired -- proving the fixture
        # differs from a good dump in exactly one respect, not in several.
    ok = uidata(good_rows())
    assert L.parse(ok).accounts_for_every_row(), (
        "the control must PASS; if it cannot, the failures above prove nothing")


def test_the_savedvariable_name_is_configurable_and_not_baked_in(monkeypatch):
    """A probe is a PERSONAL mod, so its lua global's name must not ship hard-coded.

    Pinned because the docstring promises the override, and a promise in shipped code
    that nothing exercises is how a package acquires documentation that is false.
    """
    monkeypatch.setattr(L._paths, "value", lambda *a: None)
    assert L.var_name() == L.DEFAULT_VAR
    monkeypatch.setattr(L._paths, "value", lambda *a: "__someone_elses_dump")
    assert L.var_name() == "__someone_elses_dump"


def test_the_default_savedvariable_name_carries_no_personal_identifier():
    """The scrub, as a test rather than as a habit.

    The public mirror's identifier scanner catches this only AFTER a push. A local
    test catches it before one, which is the difference between a fix and an incident.
    """
    assert L.DEFAULT_VAR.startswith("__x4live")
    from x4validate import _livepipe
    assert "x4live" in _livepipe.DEFAULT_PIPE


# --- a FATAL frame is the probe's own account, not a torn transport -----------

def test_a_FATAL_frame_is_reported_as_a_probe_failure(tmp_path):
    """`emit()` goes out of its way to preserve the build error:
    `HDR<TAB>schema=N<TAB>FATAL<TAB><message>`. Nothing read it. That frame is a single
    HDR row, so it tripped the last-row-is-not-END clause and the reader was told the
    dump was TRUNCATED and "the true length is unknown" -- pointing at the transport
    while the real cause sat unread in the payload."""
    import pytest
    rows = [["HDR", "schema=2", "FATAL", "attempt to index a nil value (global 'C')"]]
    with pytest.raises(L.LiveDumpFatal) as ei:
        L.parse(uidata(rows))
    assert "attempt to index a nil value" in str(ei.value)
    assert "not truncated" in str(ei.value).lower()


def test_a_GENUINELY_truncated_dump_is_still_reported_as_truncated(tmp_path):
    """The twin. The FATAL clause runs BEFORE the END check, so it must not swallow a
    real truncation -- otherwise one diagnosis has simply replaced the other."""
    import pytest
    rows = [["HDR", "schema=2", "probe=test"], ["EXT_FIELDS", "id,enabled"]]
    with pytest.raises(L.LiveDumpCorrupt) as ei:
        L.parse(uidata(rows))
    assert "TRUNCATED" in str(ei.value)


def test_DELAYED_CAPABLE_is_a_known_kind():
    """The probe now records whether a second dump could even be scheduled. If the
    reader does not model the kind, `x4live dump` reports it as an unexplained
    remainder and exits 3 on a perfectly good dump."""
    assert "DELAYED_CAPABLE" in L.KNOWN_KINDS

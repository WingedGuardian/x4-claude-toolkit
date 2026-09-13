"""gates/claude_md_budget.py -- CLAUDE.md may not grow silently.

WHY A RATCHET AND NOT A CEILING. "Under 40,000 chars" is a threshold that cannot go
red in the way that matters: it reports PASS on a file full of content that has a
better home. MEASURED 2026-09-12, the two CLAUDE.md files on this machine moved in
OPPOSITE directions -- the game-root one 154,425 -> 38,056 (-75%), and the SHIPPED
one 18,420 -> 70,118 in a single commit (`8289d5a`, +3.8x) which nothing announced.
A ratchet would not have blocked that commit; it would have made it name what it
displaced.
"""

from __future__ import annotations

import json

import pytest

from conftest import import_gate

b_ = import_gate("claude_md_budget")

CR, LF = chr(13), chr(10)


def _write(p, text, crlf=False):
    data = text.replace(LF, CR + LF) if crlf else text
    p.write_bytes(data.encode("utf-8"))
    return p


def test_char_count_preserves_newlines_and_counts_the_CR(tmp_path):
    """`read_text()` applies UNIVERSAL NEWLINES and deletes one char per line, so a
    ratchet built on it is lax by the LINE COUNT and gets laxer as the file grows.
    MEASURED on the real file: 38,056 preserving vs 37,460 normalised -- a 596 gap
    that is exactly its CRLF count."""
    lf = _write(tmp_path / "lf.md", "a" + LF + "b" + LF)
    crlf = _write(tmp_path / "crlf.md", "a" + LF + "b" + LF, crlf=True)
    assert b_.char_count(lf) == 4
    assert b_.char_count(crlf) == 6, "CR must be counted, not swallowed"


def test_char_count_of_a_multibyte_file_is_chars_not_bytes(tmp_path):
    p = _write(tmp_path / "m.md", "\u2605\u26a0" + LF)
    assert b_.char_count(p) == 3
    assert p.stat().st_size > 3


def test_growth_beyond_baseline_is_a_violation_naming_the_overage():
    v = b_.violations({"a": 100}, {"a": 90})
    assert len(v) == 1 and v[0].name == "a"
    assert v[0].measured == 100 and v[0].baseline == 90 and v[0].over == 10


def test_shrinking_or_equal_is_no_violation():
    assert b_.violations({"a": 90, "b": 50}, {"a": 90, "b": 60}) == []


def test_a_file_absent_from_the_baseline_is_not_a_violation():
    """First sight of a file is not growth. It is recorded on the next --record."""
    assert b_.violations({"new": 999}, {}) == []


def test_an_unreadable_file_is_a_REFUSAL_not_a_pass(tmp_path):
    with pytest.raises(b_.Unmeasurable):
        b_.char_count(tmp_path / "does-not-exist.md")


def test_resolving_no_files_at_all_exits_2(monkeypatch):
    """A ratchet that passes when it measured nothing is the defect it exists to
    prevent."""
    monkeypatch.setattr(b_, "budget_files", lambda: [])
    assert b_.main() == 2


def test_a_missing_baseline_says_drift_is_not_checked_and_never_passes_silently(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(b_, "BASELINE", tmp_path / "absent.json")
    rc = b_.main()
    # ONE readouterr(): the first call drains BOTH streams, so a second `.err` is
    # always empty. The refusal line goes to stderr and this test read only stdout
    # while believing it read both (checker bug, 2026-09-13).
    cap = capsys.readouterr()
    out = cap.out + cap.err
    assert "NOT being checked" in out, out
    assert rc == 2, "an unrecorded ratchet must REFUSE, not pass: rc %r" % rc


def test_record_then_check_is_green_and_the_baseline_round_trips(monkeypatch, tmp_path):
    bl = tmp_path / "b.json"
    monkeypatch.setattr(b_, "BASELINE", bl)
    assert b_.main(record=True) == 0
    data = json.loads(bl.read_text(encoding="utf-8"))
    assert data, "recorded an empty baseline"
    assert all(isinstance(v, int) for v in data.values()), data
    assert b_.main() == 0


def test_the_real_files_are_found_and_named():
    """END TO END: at least the game-root CLAUDE.md must resolve on this machine."""
    files = b_.budget_files()
    assert files, "no CLAUDE.md resolved at all"
    names = {n for n, _ in files}
    # The shipped copy is in every clone; the game-root copy only where X4 is configured.
    assert any("shipped" in n for n in names), names
    for _, p in files:
        assert b_.char_count(p) > 1000

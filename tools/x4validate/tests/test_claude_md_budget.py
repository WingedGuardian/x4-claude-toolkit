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


def test_char_count_is_the_same_for_an_LF_and_a_CRLF_checkout(tmp_path):
    """A checkout's line endings are not content (F120). MEASURED 2026-09-13: counting the
    raw CR made a fast-forward that rewrote the shipped CLAUDE.md as CRLF read as GREW +872,
    on a file 52 characters SMALLER than its baseline."""
    lf = _write(tmp_path / "lf.md", "a" + LF + "b" + LF)
    crlf = _write(tmp_path / "crlf.md", "a" + LF + "b" + LF, crlf=True)
    assert b_.char_count(lf) == b_.char_count(crlf) == 4


def test_TWIN_each_newline_still_counts_once_and_real_growth_shows_in_either_ending(tmp_path):
    """The twin: normalising must not swallow newlines -- the `read_text()`-style loss this
    gate was first built to avoid -- and one added character is one in both endings."""
    for crlf in (False, True):
        base = _write(tmp_path / ("base%s.md" % crlf), "a" + LF + "b" + LF, crlf=crlf)
        grown = _write(tmp_path / ("grown%s.md" % crlf), "a" + LF + "bc" + LF, crlf=crlf)
        assert b_.char_count(base) == 4, "a newline must count as a character"
        assert b_.char_count(grown) - b_.char_count(base) == 1


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
    assert data.pop("_counting") == b_.COUNTING, data
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


def test_a_baseline_for_DIFFERENT_files_is_a_REFUSAL(monkeypatch, tmp_path, capsys):
    """Disjoint keys compared nothing -- that is not 'within the floor'."""
    bl = tmp_path / "b.json"
    bl.write_text(json.dumps({"_counting": b_.COUNTING, "some other file": 10}), encoding="utf-8")
    monkeypatch.setattr(b_, "BASELINE", bl)
    assert b_.main() == 2
    cap = capsys.readouterr()
    assert "NOT CHECKED" in cap.out and "REFUSING" in cap.err


def test_a_PARTIAL_baseline_names_the_file_it_does_not_check(monkeypatch, tmp_path, capsys):
    files = b_.budget_files()
    if len(files) < 2:
        pytest.skip("needs two resolvable CLAUDE.md files -- NOT CHECKED")
    first = files[0][0]
    bl = tmp_path / "b.json"
    bl.write_text(json.dumps({"_counting": b_.COUNTING, first: 10_000_000}), encoding="utf-8")
    monkeypatch.setattr(b_, "BASELINE", bl)
    assert b_.main() == 0
    assert "NOT CHECKED  " + files[1][0] in capsys.readouterr().out


def test_a_baseline_from_the_OLD_counting_method_is_a_REFUSAL(monkeypatch, tmp_path, capsys):
    """A pre-F120 baseline counted raw CRs, so on a CRLF checkout it is too HIGH by the line
    count and would pass that much growth in silence. It must be re-recorded, not read."""
    bl = tmp_path / "b.json"
    bl.write_text(json.dumps({"shipped (repo root)": 10_000_000}), encoding="utf-8")
    monkeypatch.setattr(b_, "BASELINE", bl)
    assert b_.main() == 2
    assert "counting method" in capsys.readouterr().err

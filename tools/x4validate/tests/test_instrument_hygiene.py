"""`gates/instrument_hygiene.py` — and above all, that its patterns are LIVE.

THE DEFECT THIS PINS. Writing one regex to match a literal backslash failed three
times in ten minutes, inside the gate built to count exactly that kind of mistake:

  1. `r"\\\\[nrt]"` in a raw string is FOUR backslashes — a regex for TWO literal
     ones. It counted 9 where the answer was 395.
  2. rebuilt as `chr(92) + "[nrt]"`, which is a regex for a literal `[nrt]`. Counted 0.
  3. the verification of (2) was itself written through a Bash heredoc, where `\\b`
     collapsed to a backspace character — so it agreed with the broken pattern.

Every one of those reported a comfortable, well-formed number. **A pattern that has
never been shown to match anything is a check that cannot go red**, and no amount of
care substitutes for a fixture: attempt 3 was made by someone who had just written
attempts 1 and 2 down as lessons.

So each `Shape` carries a known-bad example it MUST match and a near-miss it must
NOT, `verify_fixtures()` runs before any count is produced, and the tests below make
that contract enforceable rather than conventional.
"""

from __future__ import annotations

import json
import re

import pytest

from conftest import import_gate

ih = import_gate("instrument_hygiene")

NL = chr(10)
BS = chr(92)


# --------------------------------------------------------------------------
# the contract: every shipped pattern is live, and provably so
# --------------------------------------------------------------------------
def test_every_shipped_pattern_matches_its_own_known_bad_example():
    """The load-bearing test. If this fails, some pattern has gone inert and the
    gate has been reporting zero for a shape it can no longer see."""
    assert ih.verify_fixtures() == []


def test_every_shape_actually_carries_a_fixture():
    """A Shape added without one would satisfy verify_fixtures() vacuously — an
    empty string matches nothing and is matched by nothing, so both checks pass."""
    for s in ih.SHAPES:
        assert s.hits.strip(), f"{s.key} has no known-bad example"
        assert s.misses.strip(), f"{s.key} has no near-miss"
        assert s.why.strip(), f"{s.key} does not say why it matters"


def test_an_INERT_pattern_is_reported(monkeypatch):
    """Falsification: reproduce failure (2) above — a pattern that compiles, runs,
    and matches nothing it should."""
    dead = ih.Shape("dead", "w", re.compile("ZZZ-never-occurs"),
                    hits="a real bad example", misses="fine")
    bad = ih.verify_fixtures([dead])
    assert len(bad) == 1 and "inert" in bad[0]


def test_an_OVER_BROAD_pattern_is_reported():
    """The other direction. Without this, `re.compile('')` would pass the first
    check and the fixture would prove nothing at all."""
    greedy = ih.Shape("greedy", "w", re.compile(""), hits="x", misses="y")
    bad = ih.verify_fixtures([greedy])
    assert len(bad) == 1 and "too broad" in bad[0]


def test_a_healthy_pattern_reports_nothing():
    """The positive twin, so the two assertions above cannot pass for a
    verify_fixtures() that complains about everything."""
    ok = ih.Shape("ok", "w", re.compile(r"\bfoo\b"), hits="a foo here", misses="food")
    assert ih.verify_fixtures([ok]) == []


def test_the_bare_python_rule_does_not_flag_a_uv_run_invocation():
    """The regression that made this rule report 52 where the answer was 2. A
    lookbehind inspects a FIXED width — seven characters — so anything between
    `uv run` and `python` defeated it."""
    s = next(x for x in ih.SHAPES if x.key == "bare-python-on-project-code")
    assert s.pattern.search("python -m pytest -q")
    for exonerated in ("uv run python -m pytest",
                       "uv run --frozen python -m pytest",
                       "cd x && uv run --project ../y python -m pytest a.py"):
        assert not s.pattern.search(exonerated), exonerated


# --------------------------------------------------------------------------
# scanning: absence, non-answer and a real reading are three different states
# --------------------------------------------------------------------------
def _rec(cmd, tid="t1"):
    return json.dumps({"message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}]}})


def _res(text, tid="t1"):
    return json.dumps({"message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text}]}})


def test_a_directory_with_no_transcripts_refuses(tmp_path):
    with pytest.raises(SystemExit) as e:
        ih.scan(tmp_path)
    assert e.value.code == 2


def test_an_unparseable_line_is_RECORDED_not_swallowed(tmp_path):
    (tmp_path / "s.jsonl").write_text("{not json" + NL + _rec("echo hi") + NL,
                                      encoding="utf-8")
    c = ih.scan(tmp_path)
    assert len(c.unreadable) == 1
    assert c.commands == 1


def test_a_shape_is_counted(tmp_path):
    (tmp_path / "s.jsonl").write_text(_rec("grep -c ERROR debug.txt") + NL,
                                      encoding="utf-8")
    c = ih.scan(tmp_path)
    assert c.counts.get("grep-c-or-wc-l-as-a-count") == 1


# --------------------------------------------------------------------------
# the exit-code rung: a side effect BEFORE the failure point almost certainly ran
# --------------------------------------------------------------------------
def test_a_side_effect_in_the_FIRST_segment_is_not_counted_as_lost(tmp_path):
    """`cp a b && grep x f` exits 1 with the cp having run perfectly well. Counting
    those inflated this figure from 8 to 39 in the first draft — an overcount found
    by red-teaming rather than by any test."""
    (tmp_path / "s.jsonl").write_text(
        _rec("cp a b && grep missing f") + NL + _res("Exit code 1") + NL,
        encoding="utf-8")
    c = ih.scan(tmp_path)
    assert c.nonzero == 1
    assert c.lost_side_effects == []


def test_a_side_effect_AFTER_the_failure_point_is_counted(tmp_path):
    """The positive twin. Without it the test above would pass for an
    implementation that never counted anything."""
    (tmp_path / "s.jsonl").write_text(
        _rec("grep missing f && cp a b") + NL + _res("Exit code 1") + NL,
        encoding="utf-8")
    c = ih.scan(tmp_path)
    assert len(c.lost_side_effects) == 1


def test_a_zero_exit_is_not_counted_at_all(tmp_path):
    (tmp_path / "s.jsonl").write_text(
        _rec("grep found f && cp a b") + NL + _res("some output") + NL,
        encoding="utf-8")
    c = ih.scan(tmp_path)
    assert c.nonzero == 0 and c.lost_side_effects == []


# --------------------------------------------------------------------------
# the baseline distinguishes ABSENT from UNREADABLE
# --------------------------------------------------------------------------
def test_an_absent_baseline_accepts_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(ih, "BASELINE", tmp_path / "nope.json")
    assert ih._baseline() == {}


def test_a_damaged_baseline_RAISES_rather_than_reading_as_empty(tmp_path, monkeypatch):
    b = tmp_path / "b.json"
    b.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(ih, "BASELINE", b)
    with pytest.raises(RuntimeError):
        ih._baseline()


def test_the_hookable_threshold_is_a_measured_constant_not_a_guess():
    """It decides whether a shape can become a PreToolUse rule at all. Pinned so a
    silent widening cannot make a flooding rule look viable."""
    assert ih.HOOKABLE_MAX == 0.02


def test_a_run_with_NO_BASELINE_is_a_REFUSAL_rc2_never_a_pass(tmp_path, monkeypatch, capsys):
    """run-gates.sh reads rc 0 as `ok` and discards stdout, so "measures but cannot judge"
    at rc 0 printed a passing gate over a comparison that never happened (review,
    2026-09-14)."""
    t = tmp_path / "t"
    t.mkdir()
    (t / "s.jsonl").write_text(_rec("echo hi") + NL + _res("hi") + NL, encoding="utf-8")
    monkeypatch.setattr(ih, "transcript_dir", lambda: t)
    monkeypatch.setattr(ih, "BASELINE", tmp_path / "absent.json")
    monkeypatch.setattr(ih, "RECORD", False)
    assert ih.main() == 2
    assert "cannot judge" in capsys.readouterr().out

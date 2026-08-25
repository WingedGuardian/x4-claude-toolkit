"""The perf guard's threshold predicate.

Round 7 lesson: an AGGREGATE hides per-item regressions (total read 1.00x while
two mods went 39x and 51x slower), so the guard compares items. This pins the
rule that decides what counts as a regression — both a large ratio AND a
material absolute delta, never either alone.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gates"))


@pytest.mark.parametrize("label,base,curr,expected", [
    ("Round 7: arck_job_registry 39x",      2.842, 112.156, True),
    ("Round 7: battle_repair_support 51x",  2.377, 121.387, True),
    ("bug #10 style hang",                 12.200, 900.000, True),
    ("noise: 4x but 3ms",                   0.001,   0.004, False),
    ("large mod, negligible drift",        16.240,  16.360, False),
    ("got FASTER",                         17.600,   6.100, False),
    ("3.1x but only 1.9s absolute",         0.900,   2.790, False),
    ("4.0s absolute but only 2.9x",         2.100,   6.090, False),
])
def test_regression_predicate(label, base, curr, expected):
    import perf_guard
    assert perf_guard.is_regression(base, curr) is expected, label


def test_both_conditions_are_required():
    """Guards against someone loosening it to `or` — which would make the gate
    fire on every sub-millisecond fluctuation and then get ignored."""
    import perf_guard
    assert perf_guard.is_regression(1.0, 100.0) is True      # both
    assert perf_guard.is_regression(0.001, 0.5) is False     # ratio only (delta 0.5s)
    assert perf_guard.is_regression(100.0, 150.0) is False   # delta only (1.5x)


# --- the suspend false-positive (MEASURED 2026-08-24) ------------------------

def _row(mod, base, curr):
    """A row in perf_guard's internal shape: (delta, ratio, base, curr, mod)."""
    return (curr - base, curr / base, base, curr, mod)


def test_a_spike_that_does_not_reproduce_is_discarded():
    """The real case: `time.perf_counter()` advances while Windows is SUSPENDED.

    A sweep left running overnight charged the whole sleep to whichever mod was
    timing when the machine slept:

        bh_shader   2.71s -> 2210.88s  (814.9x)   PERF REGRESSION

    The same mod re-timed at 3.47s minutes later, and the Windows event log
    independently showed Kernel-Power 131 with ResumeCount: 3 across an 18-hour
    wall-clock window. A timing that spans a suspend is a NON-ANSWER; rendering
    it as a finding would have blocked a release on a phantom.
    """
    import perf_guard
    bad = [_row("bh_shader", 2.71, 2210.88)]
    confirmed, spurious = perf_guard.confirm_regressions(bad, lambda m: 3.47)
    assert confirmed == []
    assert len(spurious) == 1 and spurious[0][1] == 3.47


def test_a_spike_that_DOES_reproduce_is_kept():
    """The falsification twin. Without this, "discards spikes" would be
    indistinguishable from "discards everything", and the gate would be off."""
    import perf_guard
    bad = [_row("arck_job_registry", 2.842, 112.156)]
    confirmed, spurious = perf_guard.confirm_regressions(bad, lambda m: 109.4)
    assert spurious == []
    assert len(confirmed) == 1 and confirmed[0][1] == 109.4


def test_a_regression_that_cannot_be_retimed_is_UNCONFIRMED_not_cleared():
    """"Could not check" is not "not a regression".

    Silently clearing an item the re-timer could not measure would turn this
    confirmation step into a way of LOSING findings — the exact narrowing shape
    the register exists to ban.
    """
    import perf_guard
    bad = [_row("vanished_mod", 2.0, 50.0)]
    confirmed, spurious = perf_guard.confirm_regressions(bad, lambda m: None)
    assert spurious == []
    assert len(confirmed) == 1 and confirmed[0][1] is None


def test_confirmation_uses_the_SAME_predicate_as_detection():
    """A second, looser rule in the confirmation step would let a real
    regression through on the re-timing. One predicate, both places."""
    import perf_guard
    base, slow = 2.0, 50.0
    assert perf_guard.is_regression(base, slow) is True
    confirmed, _ = perf_guard.confirm_regressions([_row("m", base, slow)],
                                                  lambda m: slow)
    assert len(confirmed) == 1
    # just under the threshold on re-timing -> discarded
    _c, spurious = perf_guard.confirm_regressions([_row("m", base, slow)],
                                                  lambda m: base * 2.9)
    assert len(spurious) == 1

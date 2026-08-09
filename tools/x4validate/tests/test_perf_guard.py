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

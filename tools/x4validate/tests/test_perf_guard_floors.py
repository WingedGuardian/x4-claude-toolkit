"""`perf_guard` had two verdict lines reachable with nothing measured behind them.

1. COMPARE: with an EMPTY `set(base) & set(curr)` there are no rows, so nothing lands
   in `bad`, `regressed_to_crash` or `new_crash`, and it fell through to "No per-mod
   regression beyond tolerance." at rc 0 -- a clean pass over ZERO comparisons.

2. RECORD: a baseline over zero timed mods "succeeded" at rc 0 and then POISONED every
   later run, because the intersection is empty forever after.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

GATES = Path(__file__).resolve().parents[1] / "gates"


@pytest.fixture()
def pg():
    sys.path.insert(0, str(GATES))
    try:
        import perf_guard as mod
        importlib.reload(mod)
    except SystemExit as exc:
        pytest.skip("gates/_env refused to resolve: %s" % exc)
    finally:
        sys.path.remove(str(GATES))
    return mod


def _run(pg, tmp_path, base, curr, retime_val):
    b = tmp_path / "baseline.json"
    b.write_text(json.dumps(base), encoding="utf-8")
    pg.BASELINE = b
    pg.RECORD = False
    pg.measure = lambda: (curr, {})
    pg.retime = lambda mod, cfg: retime_val
    return pg.main()


def test_an_EMPTY_intersection_REFUSES_instead_of_passing(pg, tmp_path):
    assert _run(pg, tmp_path, {"a": 1.0}, {"b": 1.0}, 1.0) == 2


def test_an_OVERLAPPING_run_with_no_regression_still_PASSES(pg, tmp_path):
    """Twin one: without it the refusal above is satisfied by a gate that never
    passes at all."""
    assert _run(pg, tmp_path, {"a": 1.0}, {"a": 1.02}, 1.02) == 0


def test_a_REPRODUCED_regression_still_FAILS(pg, tmp_path):
    """Twin two, and it caught a bug in my own first probe: I stubbed `retime` to
    return a FAST number, so the spike did not reproduce and the gate correctly
    DISCARDED it -- and I read that rc 0 as "the gate cannot detect a regression"."""
    assert _run(pg, tmp_path, {"a": 1.0}, {"a": 100.0}, 100.0) == 1


def test_RECORDING_an_empty_baseline_is_REFUSED(pg, tmp_path):
    pg.BASELINE = tmp_path / "baseline.json"
    pg.RECORD = True
    pg.measure = lambda: ({}, {})
    assert pg.main() == 2
    assert not pg.BASELINE.exists(), "an empty baseline must not reach disk"


def test_RECORDING_a_real_baseline_still_works(pg, tmp_path):
    """The twin: the floor must key on emptiness, not on recording."""
    pg.BASELINE = tmp_path / "baseline.json"
    pg.RECORD = True
    pg.measure = lambda: ({"a": 1.0}, {})
    assert pg.main() == 0
    assert json.loads(pg.BASELINE.read_text(encoding="utf-8")) == {"a": 1.0}

"""`gates/obtainability_audit.py::main` had NO test reaching it.

The mutation gate reported both of this round's changes to the file as wholly
uncovered, which is the honest description of a function nothing calls: its three
branches -- record, refuse-without-a-baseline, and drift -- were each reasoned about
and none was executed.

`audit()` is replaced by a stub. That is the point rather than a shortcut: the real
one walks the effective tree and needs a configured install and a modlist, so a test
that ran it would be a corpus measurement, would SKIP on every machine without X4,
and would leave `main()` exactly as uncovered as it is now. What is under test here is
the decision logic -- what it returns, and whether it refuses -- not the corpus.

The refusal branch matters most: a gate that reports "unchanged" against a baseline
that does not exist is a green with no reachable red, and this file exists to keep
that branch honest.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

GATES = pathlib.Path(__file__).resolve().parent.parent / "gates"
SRC = GATES / "obtainability_audit.py"

# The gate imports its sibling `_env`, which is only importable from gates/.
if str(GATES) not in sys.path:
    sys.path.insert(0, str(GATES))

#: A whole audit result, small enough to read. The keys are the ones main() compares;
#: derived from the module's own list below so a new key cannot silently go unchecked.
NOW = {
    "base_macro_files_scanned": 100,
    "base_macro_files_unreadable": 0,
    "deprecated_only_macros_vanilla": 3,
    "deprecated_only_macros_effective": 2,
    "live_macros_with_deprecated_ammo": 1,
    "of_those_sold_by_a_live_ware": 0,
    "mods_referencing_deprecated": {"some_mod": 2},
}


def _load(monkeypatch, tmp_path, record: bool):
    if not SRC.is_file():
        pytest.skip(f"no {SRC.name} -- NOT CHECKED")
    spec = importlib.util.spec_from_file_location("obtainability_under_test", SRC)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit as exc:
        # `gates/_env.py` signals "no X4 install configured" with SystemExit(2) at
        # IMPORT time. That is a machine fact, not a defect -- and it must SKIP
        # rather than error, because a SystemExit escaping collection aborts the
        # whole pytest session (gotcha #26, three cold-verify failures in a row).
        pytest.skip(f"gates/ needs a configured X4 install (SystemExit {exc.code}) "
                    "-- main() NOT CHECKED here")
    monkeypatch.setattr(mod, "BASELINE", tmp_path / "baseline.json")
    monkeypatch.setattr(mod, "RECORD", record)
    monkeypatch.setattr(mod, "audit", lambda: dict(NOW))
    return mod


def test_it_REFUSES_when_there_is_no_baseline(monkeypatch, tmp_path, capsys):
    """rc 2 = CANNOT CHECK, which is not rc 0 = unchanged. Reporting 'no drift'
    against nothing is the failure the whole gate is shaped around."""
    mod = _load(monkeypatch, tmp_path, record=False)
    assert mod.main() == 2
    err = capsys.readouterr().err
    assert "no baseline" in err and "--record" in err, err


def test_record_writes_a_baseline_and_returns_zero(monkeypatch, tmp_path, capsys):
    mod = _load(monkeypatch, tmp_path, record=True)
    assert mod.main() == 0
    written = json.loads(mod.BASELINE.read_text(encoding="utf-8"))
    assert written == NOW, written


def test_an_unchanged_corpus_is_green(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path, record=False)
    mod.BASELINE.write_text(json.dumps(NOW), encoding="utf-8")
    assert mod.main() == 0


def test_drift_in_a_DENOMINATOR_is_a_failure(monkeypatch, tmp_path, capsys):
    """A collapse in coverage must not surface disguised as a change in findings."""
    mod = _load(monkeypatch, tmp_path, record=False)
    was = dict(NOW, base_macro_files_scanned=40)
    mod.BASELINE.write_text(json.dumps(was), encoding="utf-8")
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "base_macro_files_scanned: 40 -> 100" in out, out


def test_drift_is_reported_PER_MOD(monkeypatch, tmp_path, capsys):
    """A mod losing 3 references while another gains 3 nets to zero, and both are
    real. Per item, never the total."""
    mod = _load(monkeypatch, tmp_path, record=False)
    was = dict(NOW, mods_referencing_deprecated={"other_mod": 2})
    mod.BASELINE.write_text(json.dumps(was), encoding="utf-8")
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "mod some_mod: 0 -> 2" in out, out
    assert "mod other_mod: 2 -> 0" in out, out


def test_a_baseline_predating_a_key_is_NOT_COMPARABLE_rather_than_unchanged(
        monkeypatch, tmp_path, capsys):
    mod = _load(monkeypatch, tmp_path, record=False)
    was = {k: v for k, v in NOW.items() if k != "live_macros_with_deprecated_ammo"}
    mod.BASELINE.write_text(json.dumps(was), encoding="utf-8")
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "predates this key" in out, out

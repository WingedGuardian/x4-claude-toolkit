"""x4conformance harness: the dump, the reference verdict, the neutral extras, and the identity
control that proves the engine itself agrees with the guards (#22: check the checker first)."""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("x4conformance", REPO / "scripts" / "x4conformance.py")
xc = importlib.util.module_from_spec(spec); spec.loader.exec_module(xc)

pytestmark = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("jq")),
                                reason="needs Git Bash and jq -- conformance harness NOT checked here")


def test_the_dump_is_big_enough_and_every_row_is_classified(conformance_dump):
    rows, _ = conformance_dump
    assert len(rows) >= 100
    kinds = [xc.classify(r) for r in rows]
    assert set(kinds) <= set(xc.KINDS) | {"no_native_analogue"}
    assert sum(k != "no_native_analogue" for k in kinds) >= 80


def test_the_dump_sandbox_is_under_the_toolkit_never_tmp(conformance_dump):
    _, sbx = conformance_dump
    assert (REPO / ".test-sandbox") in sbx.parents


def test_neutral_extras_add_powershell_cases_and_their_reference_controls_hold(conformance_dump):
    rows, _ = conformance_dump
    extras = xc.extra_rows(REPO, rows)
    assert sum(xc.classify(r) == "shell-powershell" for r in extras) >= 3
    for r in extras:                       # the reference control: the guard still says what the case expects
        assert xc.reference_verdict(r, REPO) == r["expect"], r["id"]


def test_identity_control_claude_profile_agrees_on_every_row(conformance_dump):
    rows, _ = conformance_dump
    rows = rows + xc.extra_rows(REPO, rows)
    prof = xc.load_profile("claude", REPO)
    res = xc.replay(rows, prof, None, REPO, workers=4)
    assert len(res) >= 80
    bad = [r for r in res if r["reference"] != r["adapter"]]
    assert not bad, bad[:10]               # PER ITEM


def test_cleanup_removes_only_the_recorded_sandbox(tmp_path):
    base = tmp_path / "base"; keep = tmp_path / "keep"
    (base / "hooks.abc").mkdir(parents=True); keep.mkdir()
    xc.remove_sandbox(base / "hooks.abc", base)
    assert not (base / "hooks.abc").exists() and keep.exists()
    with pytest.raises(ValueError):
        xc.remove_sandbox(keep, base)      # TWIN: outside the base it refuses, deletes nothing
    assert keep.exists()

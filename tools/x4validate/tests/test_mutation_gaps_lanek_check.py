"""Mutation-campaign gaps in `_check`, lane K (2026-09-26). Each test names the surviving
mutant it was written to kill and was verified to FAIL with it applied and PASS without."""
from __future__ import annotations

from pathlib import Path

import pytest

from x4validate import _check, _merge


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_nested_target_installed_under_a_DIFFERENT_CASE_is_not_called_uninstalled(
        tmp_path, monkeypatch):
    """C8: the installed set is lowercased, so `extensions/SomeMod/...` whose target IS
    installed (as `somemod`) must not be excused as 'not installed' -- it is a real
    path mismatch."""
    ref = tmp_path / "reference"
    _write(ref / "libraries/wares.xml", "<wares/>")
    cfg = _merge.Config(reference=ref)
    monkeypatch.setattr(_check, "_installed_folders", lambda: {"somemod"})
    monkeypatch.setattr(_check, "_target_disabled", lambda target, config: False)
    sev, cat, _msg = _check._no_base_finding("extensions/SomeMod/libraries/nope.xml", cfg)
    assert (sev, cat) == ("error", "path")


class _TierBCalled(Exception):
    pass


def test_tier_b_does_not_rebuild_overlays_the_caller_already_supplied(tmp_path, monkeypatch):
    """C12: a config that already carries overlays is used as given under tier b --
    tier_b_trees() is only consulted when there are none."""
    monkeypatch.setattr(_check, "reference_ready", lambda config, report: True)
    monkeypatch.setattr(_check, "check_packed_dlc_available", lambda config, report: None)

    def _boom(*_a, **_k):
        raise _TierBCalled

    monkeypatch.setattr(_check, "tier_b_trees", _boom)
    mod = tmp_path / "mod"
    _write(mod / "content.xml", '<content id="mod"/>')
    ov = tmp_path / "other"
    ov.mkdir()
    cfg = _merge.Config(reference=tmp_path / "reference", overlays=[ov])
    try:
        _check.validate(mod, cfg, tier="b", sel_only=True)
    except _TierBCalled:
        pytest.fail("tier_b_trees() rebuilt overlays the caller supplied")
    except Exception:  # noqa: BLE001 -- anything later in the run is not this test's concern
        pass


def test_empty_debug_log_reads_as_no_errors_parsed(tmp_path):
    """C14: a log with ZERO engine errors is 'no [=ERROR=] lines parsed', never 'none
    of the 0 engine error(s) identify a mod file'."""
    log = tmp_path / "debug.txt"
    log.write_text("", encoding="utf-8")
    mod = tmp_path / "mod"
    mod.mkdir()
    rep = _check.Report()
    _check.check_debug_correlation(mod, _merge.Config(reference=tmp_path / "ref"), rep, log)
    joined = "\n".join(rep.notes)
    assert "no [=ERROR=] lines parsed" in joined
    assert "none of the 0" not in joined

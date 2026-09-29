"""conftest's fake install must WIN over a real one, or "hermetic" is a word.

`gate_install` / `hermetic_gate` exist so gate-logic tests RUN on a machine with no X4
(v3.3.0 CI: 16 such tests skipped and broke the skip ceiling). They hand the fake roots
over through the environment layer of `_paths`. If that layer ever stopped outranking
`.claude/x4-paths.env`, a CONFIGURED machine would import the gate against the REAL
install -- and every converted test would silently mean something different warm than
cold. These pin that the gate saw the fake, on whatever machine runs them.
"""
from __future__ import annotations

from pathlib import Path

from conftest import _FAKE_INSTALL_ENV, hermetic_gate


def test_a_gate_loaded_by_gate_install_resolves_the_FAKE_roots(gate_install):
    na = gate_install.load("noop_audit")
    assert Path(na.EXT) == gate_install.ext and Path(na.REF) == gate_install.ref, (
        na.EXT, na.REF)


def test_the_fake_reaches_a_resolution_made_at_CALL_time_too(gate_install):
    gate_install.load("provenance_audit")
    import _env                                   # on sys.path once a gate is loaded
    assert Path(_env.effective_db()) == gate_install.db
    assert Path(_env.oracle_log()) == gate_install.log
    assert Path(_env.mods_dir()) == gate_install.mods


def test_every_fake_variable_is_actually_set(gate_install, monkeypatch):
    import os
    assert {k: os.environ.get(k) for k in _FAKE_INSTALL_ENV} == gate_install.env


def test_TWIN_each_gate_install_load_is_a_FRESH_module(gate_install):
    """A cached module would carry state (and paths) from whoever imported it first."""
    a = gate_install.load("consistency_audit")
    a._FOLDER_TO_PATH["sentinel"] = 1
    b = gate_install.load("consistency_audit")
    assert a is not b and "sentinel" not in b._FOLDER_TO_PATH


def test_hermetic_gate_points_at_roots_that_no_longer_exist():
    """Module scope, pure functions only: the fake is deleted after import, so a test that
    wrongly reached for EXT fails loudly instead of reading an install."""
    na = hermetic_gate("noop_audit")
    assert "x4-fake-install-" in str(na.EXT) and not Path(na.EXT).exists(), na.EXT

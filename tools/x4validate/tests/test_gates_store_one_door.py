"""The effective store is located through ONE door: `_effective.effective_db()`.

Release review 2026-09-26 (pre-arc): `gates/claims_audit.py` and
`gates/tool_properties.py` located the store as `DEFAULT_REGISTRY.parent /
"effective.sqlite"`, bypassing `$X4_EFFECTIVE_DB` -- the setting `x4effective`, `_env`
and every other gate honour (tests/test_env_one_door.py). With the store configured
anywhere else, these two audited a different file, or none, than the one the tools use.
"""
from __future__ import annotations

import sqlite3
import types

import pytest

from conftest import import_gate


@pytest.fixture
def elsewhere(tmp_path, monkeypatch):
    """A registry in one directory and the configured store in ANOTHER."""
    from x4validate import _effective, _registry
    reg = tmp_path / "reg" / "modlist.yaml"
    reg.parent.mkdir()
    store = tmp_path / "stores" / "configured.sqlite"
    store.parent.mkdir()
    monkeypatch.setattr(_registry, "DEFAULT_REGISTRY", reg)
    monkeypatch.setattr(_effective, "effective_db", lambda: store)
    return reg, store


def test_claims_audit_reads_the_CONFIGURED_store(elsewhere):
    reg, store = elsewhere
    ca = import_gate("claims_audit", module_level=False)
    assert ca._store() == store, (
        f"claims_audit looked for {ca._store()}, not the configured {store}")


def test_TWIN_claims_audit_refuses_when_no_store_is_configured(monkeypatch):
    from x4validate import _effective, _paths
    ca = import_gate("claims_audit", module_level=False)
    monkeypatch.setattr(_effective, "effective_db", lambda: None)
    with pytest.raises(_paths.Unconfigured):
        ca._store()


def _tool_properties():
    import importlib.util
    import sys
    from pathlib import Path
    gates = Path(__file__).resolve().parents[1] / "gates"
    sys.path.insert(0, str(gates))
    try:
        spec = importlib.util.spec_from_file_location("tool_properties_one_door",
                                                      gates / "tool_properties.py")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except SystemExit as exc:
            pytest.skip(f"gates/_env refused to resolve: {exc}")
    finally:
        sys.path.remove(str(gates))
    mod.failures.clear()
    mod.skips.clear()
    return mod


def test_tool_properties_reads_the_CONFIGURED_store(elsewhere, monkeypatch):
    """The configured store EXISTS (and is stale); the registry directory holds none. The
    old lookup skipped 'no effective.sqlite' -- it never saw the configured file."""
    from x4validate import _effective
    reg, store = elsewhere
    sqlite3.connect(store).close()
    monkeypatch.setattr(_effective, "store_freshness",
                        lambda con, config=None: types.SimpleNamespace(fresh=False))
    tp = _tool_properties()
    tp.check_store_key_uniqueness()
    assert len(tp.skips) == 1 and "STALE" in tp.skips[0], tp.skips


def test_TWIN_tool_properties_skips_when_the_configured_store_is_absent(elsewhere):
    tp = _tool_properties()
    tp.check_store_key_uniqueness()
    assert len(tp.skips) == 1 and "STALE" not in tp.skips[0], tp.skips
    assert not tp.failures


def test_tool_properties_mod_scope_check_uses_the_door_not_the_import_snapshot(elsewhere):
    """`check_mod_scope_agreement` read `_effective.DB_PATH`, a snapshot taken at import:
    a store configured afterwards (or a test's) was invisible. The configured store here
    does not exist, so the check must say so -- whatever DB_PATH happened to hold."""
    tp = _tool_properties()
    tp.check_mod_scope_agreement()
    assert any("no effective store" in s for s in tp.skips), (tp.skips, tp.failures)

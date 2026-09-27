"""`gates/oracle_index.py`: "the attribution scan is broken" is a REFUSAL (rc 2), not rc 1.

Release review 2026-09-26 (pre-arc): the no-ground-truth branch was moved to rc 2 by
AUDIT-2026-09-24 GT-4, but the scan-is-broken branch beside it still raised
`SystemExit(<str>)`, which the interpreter exits with rc 1 -- run-gates.sh then read
a broken instrument as a failed gate.
"""
from __future__ import annotations

import sys
import types

import pytest

from conftest import import_gate


class _PastTheRefusal(Exception):
    """Raised by a stub once the gate has gone past the attribution refusal."""


def _gate(tmp_path, monkeypatch, mod_dirs):
    _env = import_gate("_env", module_level=False)
    log = tmp_path / "debug.txt"
    log.write_text("", encoding="utf-8")
    monkeypatch.setattr(_env, "oracle_log", lambda: log)
    monkeypatch.setattr(_env, "extensions", lambda: tmp_path)
    sys.modules.pop("oracle_index", None)
    oi = import_gate("oracle_index", module_level=False)
    sys.modules.pop("oracle_index", None)
    entry = types.SimpleNamespace(lookup="x_probe_macro")
    monkeypatch.setattr(oi._debuglog, "parse_debug", lambda p: [entry])
    mods = [{"folder": d.name, "path": str(d)} for d in mod_dirs]
    monkeypatch.setattr(oi._registry, "mods", lambda scope, *a, **k: mods)
    monkeypatch.setattr(oi._compat, "compute_load_order", lambda m: [x["folder"] for x in m])
    monkeypatch.setattr(oi._merge, "Config", lambda *a, **k: None)

    def stop(*_a, **_k):
        raise _PastTheRefusal
    monkeypatch.setattr(oi, "verdict", stop)
    return oi


def _exit_code(exc: SystemExit) -> int:
    code = exc.code
    return code if isinstance(code, int) else 1      # what the interpreter would exit with


def test_an_attribution_scan_that_finds_NOTHING_refuses_with_rc2(tmp_path, monkeypatch):
    empty = tmp_path / "some_mod"
    empty.mkdir()
    (empty / "content.xml").write_text('<content id="some_mod"/>', encoding="utf-8")
    oi = _gate(tmp_path, monkeypatch, [empty])
    with pytest.raises(SystemExit) as exc:
        oi.main()
    assert _exit_code(exc.value) == 2, f"a broken scan read as a FAILED gate: {exc.value.code!r}"


def test_TWIN_a_scan_that_finds_a_reference_does_not_refuse(tmp_path, monkeypatch):
    mod = tmp_path / "ref_mod"
    (mod / "libraries").mkdir(parents=True)
    (mod / "content.xml").write_text('<content id="ref_mod"/>', encoding="utf-8")
    (mod / "libraries" / "wares.xml").write_text(
        '<wares><ware id="w"><component ref="x_probe_macro"/></ware></wares>',
        encoding="utf-8")
    oi = _gate(tmp_path, monkeypatch, [mod])
    with pytest.raises(_PastTheRefusal):
        oi.main()

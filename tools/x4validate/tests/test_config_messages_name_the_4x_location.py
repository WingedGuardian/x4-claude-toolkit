"""User-facing refusals must name the config file 4.x READS (v4.0.0 review R5-8 / R6-07).

4.0 moved the path config to `<toolkit>/x4-paths.env` (the 3.x `<toolkit>/.claude/x4-paths.env`
is still read for all of 4.x, deprecated). Two refusals -- `_merge.Config` with no reference
tree and `_registry.require` -- still told the user to edit `.claude/x4-paths.env`, i.e. to
create a file in the DEPRECATED location. Both modules are freshness ENGINE_SOURCES; this
release already invalidates built stores (34d3fde), so the message change costs nothing more.
"""
from __future__ import annotations

import pytest

from x4validate import _merge, _registry, _paths


def test_the_merge_refusal_names_the_4x_config(monkeypatch):
    monkeypatch.setattr(_merge, "REFERENCE", None)
    with pytest.raises(_paths.Unconfigured) as e:
        _merge.Config(reference=None)
    msg = str(e.value)
    assert "<toolkit>/x4-paths.env" in msg, msg
    assert "in .claude/x4-paths.env" not in msg, msg


def test_the_registry_refusal_names_the_4x_config(capsys):
    with pytest.raises(SystemExit) as e:
        _registry.require(None, "the registry", "set X4_REGISTRY")
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "<toolkit>/x4-paths.env" in err, err
    assert "config file: .claude/x4-paths.env)" not in err, err

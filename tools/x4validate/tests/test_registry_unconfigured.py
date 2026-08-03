"""Unconfigured locations are a named loss, never a CWD guess (v2.02 red-team F2).

`_registry`'s module constants used to fall back to CWD-relative paths
(`Path("content.xml")`, `Path("extensions")`, `Path("_registry/modlist.yaml")`).
On a fresh, docs-verbatim install with only the profile configured, `x4modlist
ingest` scanned nothing, printed "installed folders (PRIMARY, 0 found)" and
exited 0 — "you have no mods" as a statement about the user's modlist instead
of the missing setting — and wrote its registry into whatever the CWD was.
Every test here was verified to FAIL against that behavior (constants restored
to their `or Path(...)` form).
"""

import types

import pytest

from x4validate import _modlist, _registry


def _ingest_args(**kw):
    base = dict(registry=None, installed_only=False, content=None, all=False,
                dirs=None, build=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _unconfigure(monkeypatch):
    for name in ("DEFAULT_REGISTRY", "PROFILE_CONTENT", "GAME_EXTENSIONS",
                 "PROFILE_EXTENSIONS", "WORKSHOP_CONTENT"):
        monkeypatch.setattr(_registry, name, None)


def test_require_exits_2_and_names_the_setting(capsys):
    with pytest.raises(SystemExit) as e:
        _registry.require(None, "the registry location", "set X4_MODS")
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "the registry location" in err and "X4_MODS" in err
    assert "x4validate --paths" in err  # points at the diagnostic, not a guess


def test_ingest_totally_unconfigured_refuses(monkeypatch, tmp_path, capsys):
    """No registry location -> exit 2 before anything is read or written."""
    _unconfigure(monkeypatch)
    monkeypatch.chdir(tmp_path)  # a stray CWD content.xml must NOT be ingested
    (tmp_path / "content.xml").write_text(
        '<content><extension id="stray" enabled="true"/></content>', encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        _modlist.cmd_ingest(_ingest_args())
    assert e.value.code == 2
    assert not (tmp_path / "_registry").exists()  # no CWD registry written


def test_ingest_no_roots_configured_is_a_named_loss(monkeypatch, tmp_path, capsys):
    """Registry configured, no installed-mod roots -> exit 2 naming the fix,
    NOT 'PRIMARY, 0 found' exit 0 (the red-team's realistic fresh-install case)."""
    _unconfigure(monkeypatch)
    monkeypatch.setattr(_registry, "DEFAULT_REGISTRY", tmp_path / "modlist.yaml")
    rc = _modlist.cmd_ingest(_ingest_args())
    assert rc == 2
    err = capsys.readouterr().err
    assert "no installed-mod roots configured" in err
    assert "X4_GAME" in err and "--dirs" in err


def test_ingest_configured_but_missing_roots_refuse(monkeypatch, tmp_path, capsys):
    """Roots configured but none exist -> exit 2 listing each tried path."""
    _unconfigure(monkeypatch)
    monkeypatch.setattr(_registry, "DEFAULT_REGISTRY", tmp_path / "modlist.yaml")
    gone = tmp_path / "no-such-extensions"
    monkeypatch.setattr(_registry, "GAME_EXTENSIONS", gone)
    rc = _modlist.cmd_ingest(_ingest_args())
    assert rc == 2
    err = capsys.readouterr().err
    assert "none of the configured installed-mod roots exist" in err
    assert str(gone) in err


def test_ingest_secondary_skip_is_named_not_silent(monkeypatch, tmp_path, capsys):
    """Profile unconfigured but primary roots fine: ingest proceeds, and the
    skipped SECONDARY cross-check is announced rather than passed off as
    'ran and found nothing'."""
    _unconfigure(monkeypatch)
    ext = tmp_path / "extensions"
    (ext / "somemod").mkdir(parents=True)
    (ext / "somemod" / "content.xml").write_text(
        '<content id="somemod" name="Some Mod" version="100" enabled="1"/>',
        encoding="utf-8")
    monkeypatch.setattr(_registry, "DEFAULT_REGISTRY", tmp_path / "reg" / "modlist.yaml")
    monkeypatch.setattr(_registry, "GAME_EXTENSIONS", ext)
    rc = _modlist.cmd_ingest(_ingest_args())
    assert rc == 0
    out, err = capsys.readouterr()
    assert "SECONDARY cross-check skipped" in err and "X4_PROFILE" in err
    assert "PRIMARY, 1 found" in out
    assert "scanning roots:" in out  # the denominator is stated


def test_ingest_content_xml_unconfigured_raises_named_error(monkeypatch):
    """Library-level: no lxml OSError traceback about a CWD 'content.xml'."""
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", None)
    with pytest.raises(FileNotFoundError, match="X4_PROFILE"):
        _registry.ingest_content_xml(None)


def test_constants_carry_no_cwd_fallback():
    """Source-level pin (same pattern as the `# silent-ok:` scan guard): the
    module constants must resolve through _paths ONLY. The other tests here
    monkeypatch the constants, so a reintroduced `or Path("extensions")`
    fallback would slip past them — the first mutation run proved it. This
    test fails on the fallback ITSELF."""
    import inspect
    src = inspect.getsource(_registry)
    block = src[src.index("DEFAULT_REGISTRY ="):src.index("def require(")]
    assert "or Path(" not in block, (
        "a module constant grew a CWD-relative fallback again — unresolved "
        "must stay None so require() can name the loss:\n" + block)

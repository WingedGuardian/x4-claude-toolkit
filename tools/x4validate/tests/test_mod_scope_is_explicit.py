r""""The mod list" is TWO different sets, and a caller must say which it means.

    "active"    — what the ENGINE WILL LOAD: installed, enabled in its own
                  manifest, AND enabled in the profile content.xml.
    "installed" — what is ON DISK, enabled or not.

THE DEFECT THIS PINS (MEASURED 2026-08-22). Nothing in the code said which set a
caller wanted, so it was decided by whichever helper got imported. Across 13 call
sites: 5 were right, 3 were defensible but silent, and **4 were wrong — all wrong
the same way**, modelling the running game from the disk.

With exactly ONE mod installed-but-disabled (`escape_pod`, 19 XML files):

  x4eff      carried its 3 macros as LIVE content. x4eff is the index we point at
             when the question is "what does the ENGINE see", so this corrupts
             POSITIVE answers -- and unlike a missing document, nothing else in
             the toolkit guards those.
  x4compat   listed it as a participant in 4 collision rows of the 08-22 baseline,
             in a tool used to make modlist decisions.
  Tier B     would resolve a cross-mod selector against it and report OK. A FALSE
             PASS, in the mode built to catch silent no-ops.

The blast radius was 1 mod only because the machine happened to have one mod
switched off. It scales with the disabled set, and nothing warned.

WHAT TO DO: call `_registry.mods(scope, ...)` with the scope NAMED at the call
site, and a comment saying why that scope. `scan_installed` remains the raw disk
reader and belongs to `_registry`; this test keeps the boundary.

HONEST SCOPE: this walks `x4validate/`, `gates/` and `tools/basex/`. A throwaway
script is covered by no linter -- the same caveat as the sibling guards.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOTS = [ROOT / "x4validate", ROOT / "gates", ROOT.parent / "basex"]
MARKER = "mod-scope-ok"

#: `_registry.py` defines both; `mods()` is the one legitimate caller of the other.
EXEMPT_FILES = {"_registry.py"}


def _bare_calls(path: Path) -> list[tuple[int, str]]:
    """(lineno, source) for each `scan_installed(...)` outside `_registry`.

    Parse errors RAISE. A guard that skips a file it cannot read reports a clean
    sweep over a population it never scanned -- the very shape this register
    exists to police. It has bitten already: an ad-hoc scan on Python 3.10
    silently dropped `_check.py`, whose PEP 701 f-string needs 3.12+.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "scan_installed"):
            continue
        start, end = node.lineno - 1, getattr(node, "end_lineno", node.lineno)
        if any(MARKER in ln for ln in lines[max(0, start - 3):end]):
            continue
        out.append((node.lineno, (ast.get_source_segment(source, node) or "")[:70]))
    return out


def _scope_calls(path: Path) -> list[tuple[int, str | None]]:
    """(lineno, scope-literal-or-None) for each `_registry.mods(...)` call."""
    source = path.read_text(encoding="utf-8")
    out = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "mods"):
            continue
        # The RECEIVER is checked, not just the attribute name. `gates/_env.py`
        # calls `_paths.mods()` -- an unrelated function returning the mod SOURCE
        # DIRECTORY -- and the first cut of this detector flagged it. A guard that
        # fires on a name collision is a guard people learn to ignore.
        recv = node.func.value
        if not (isinstance(recv, ast.Name) and recv.id.endswith("_registry")):
            continue
        first = node.args[0] if node.args else None
        scope = first.value if isinstance(first, ast.Constant) else None
        out.append((node.lineno, scope))
    return out


def _files() -> list[Path]:
    return [p for root in SCAN_ROOTS if root.is_dir()
            for p in sorted(root.glob("*.py")) if p.name not in EXEMPT_FILES]


def test_the_scan_population_is_not_empty():
    """Denominator guard — every assertion below passes over an empty file list."""
    assert len(_files()) >= 40, f"only {len(_files())} file(s); the roots are wrong"


def test_nobody_calls_scan_installed_behind_the_scopes_api():
    """THE GATE. `scan_installed` answers only 'what is on disk'; a caller that
    reaches past `mods()` is silently choosing that, usually without meaning to."""
    offenders = [f"{p.name}:{ln}  {src}" for p in _files() for ln, src in _bare_calls(p)]
    assert not offenders, (
        "these call `scan_installed` directly instead of naming a scope:\n  "
        + "\n  ".join(offenders)
        + '\n\nUse `_registry.mods("active")` (what the engine will load) or '
          '`_registry.mods("installed")` (what is on disk), and say WHY in a '
          f"comment. If the raw reader really is right here, add `# {MARKER}:` "
          "with the reason.")


def test_every_scope_is_a_literal_the_reader_can_see():
    """A scope computed at runtime puts the choice back out of sight, which is
    the entire defect. If a caller genuinely needs to vary it, that call belongs
    behind a named function whose name says which world it models."""
    bad = [f"{p.name}:{ln}" for p in _files() for ln, scope in _scope_calls(p)
           if scope is None]
    assert not bad, f"`mods()` called without a literal scope at: {bad}"


def test_both_scopes_are_actually_used():
    """Tripwire against a mass-rewrite that collapsed the distinction. If one
    scope disappears from the codebase, the API is decorative."""
    used = {scope for p in _files() for _ln, scope in _scope_calls(p) if scope}
    assert used == {"active", "installed"}, (
        f"scopes in use: {sorted(used)} — expected both. One of the two worlds "
        f"has stopped being modelled anywhere.")


def test_an_invalid_scope_is_rejected_loudly():
    """Fail fast and by name. A silent fallback to either world would reintroduce
    exactly the ambiguity this API removes."""
    from x4validate import _registry
    with pytest.raises(ValueError, match="mod scope must be one of"):
        _registry.mods("enabled")


def test_the_detector_actually_detects(tmp_path):
    """Proven to fail: without this, a detector gone blind reports the same green
    as a clean tree."""
    bad = tmp_path / "offender.py"
    bad.write_text("from x4validate import _registry\n"
                   "x = _registry.scan_installed()\n", encoding="utf-8")
    assert _bare_calls(bad)

    # ... and does NOT fire on an unrelated function that shares the name.
    collide = tmp_path / "namecollision.py"
    collide.write_text("from x4validate import _paths\n"
                       "d = _paths.mods()\n", encoding="utf-8")
    assert _scope_calls(collide) == [], "a name collision is being flagged"

    ok = tmp_path / "acknowledged.py"
    ok.write_text("from x4validate import _registry\n"
                  f"# {MARKER}: raw disk reader is the point here\n"
                  "x = _registry.scan_installed()\n", encoding="utf-8")
    assert not _bare_calls(ok)


def test_a_file_that_will_not_parse_raises(tmp_path):
    """A file we cannot read is a NON-ANSWER, never an absence."""
    broken = tmp_path / "broken.py"
    broken.write_text("def f(:\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        _bare_calls(broken)


# --- the manifest's OWN enabled flag (mutation survivor, 2026-09-02) ---------
#
# `mods("active")` reads:
#     [m for m in installed if m["enabled"] and prof.get(m["id"], True)]
# Dropping the `m["enabled"] and` half survived the whole suite. It is the half that
# honours a mod's OWN content.xml, and losing it models a mod the engine will not load
# as loaded -- which is the #24 defect in the opposite direction to the one already
# pinned: Tier B, x4compat, x4effective and x4eff would all resolve against content
# that is switched off.


def _mod(folder, mod_id, enabled):
    return {"folder": folder, "id": mod_id, "enabled": enabled, "path": "/x/" + folder}


def test_a_mod_disabled_in_its_OWN_manifest_is_not_ACTIVE(monkeypatch):
    from x4validate import _registry
    installed = [_mod("keep", "KeepMe", True), _mod("off", "SwitchedOff", False)]
    monkeypatch.setattr(_registry, "scan_installed", lambda *a, **k: list(installed))
    monkeypatch.setattr(_registry, "ingest_content_xml", lambda *a, **k: {})
    ids = {m["id"] for m in _registry.mods("active")}
    assert "KeepMe" in ids, "an enabled mod must still be active"
    assert "SwitchedOff" not in ids, (
        "a mod disabled in its own content.xml was modelled as loaded -- the engine "
        "will not load it, so every tier built on this set is answering about a world "
        "that does not exist")


def test_the_manifest_flag_does_not_also_hide_it_from_INSTALLED(monkeypatch):
    """The twin: `installed` is the on-disk answer and must NOT apply the flag, or
    the two scopes collapse into one and #24 comes back the other way."""
    from x4validate import _registry
    installed = [_mod("keep", "KeepMe", True), _mod("off", "SwitchedOff", False)]
    monkeypatch.setattr(_registry, "scan_installed", lambda *a, **k: list(installed))
    monkeypatch.setattr(_registry, "ingest_content_xml", lambda *a, **k: {})
    ids = {m["id"] for m in _registry.mods("installed")}
    assert ids == {"KeepMe", "SwitchedOff"}, ids

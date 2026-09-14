"""A bare `test_name` citation must name a test that EXISTS -- and cannot be shadowed.

THE DEFECT (review of `7915dc4`, 2026-09-13). `names_a_check` rewrote a bare
`` `test_x` `` to `tests/test_x.py` and returned the FIRST citation that resolved. Two
consequences, both silent passes:

* a bare name for a test defined inside some other file (the hook suites keep dozens of
  tests in one `.claude/hooks/test_hook_facts.py`) never resolved on its own, so it
  counted only when a FILE was cited beside it -- and then
* the file citation shadowed it. An entry citing `.claude/hooks/test_hook_facts.py` plus
  a test name that was never written there read as covered. That is F112's stated worst
  case -- a citation that resolves to a file while not covering the claim -- and the
  session that closed F112 nearly built exactly that.

THE RULE NOW. A bare name resolves iff `tests/<name>.py` exists (a file stem, which
entries do use) or `def <name>(` is defined in a file the entry cites or in any
`tests/**/*.py` / `.claude/hooks/*.py` under `_roots()`. An entry is covered only if
EVERY bare name it cites resolves.

MEASURED before changing, over the real register: 30 bare citations, 0 of 57 covered
FIXED entries flip. F40 and F74 name tests defined in files the entries do not cite, so
a rule restricted to CITED files would have flagged two true citations -- which is why
the pool is the whole tests tree, not just the cited files.

One twin per clause, because each clause shadows the ones behind it.
"""

from __future__ import annotations

from conftest import import_gate

rr = import_gate("register_rederivation")


def _tree(tmp_path, files: dict[str, str]):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def _only(monkeypatch, root):
    monkeypatch.setattr(rr, "_roots", lambda _r: [root])


def test_a_cited_FILE_does_not_shadow_a_bare_name_defined_nowhere(tmp_path, monkeypatch):
    """Clause: every bare name must resolve. The F112 near-miss, exactly."""
    root = _tree(tmp_path, {".claude/hooks/test_hooks.py": "def test_real_one():\n    pass\n"})
    _only(monkeypatch, root)
    body = "fixed; see `.claude/hooks/test_hooks.py` and `test_never_written`"
    assert rr.names_a_check(body, root) is None


def test_a_bare_name_defined_in_a_CITED_file_resolves(tmp_path, monkeypatch):
    """Clause: def in a cited file. The cited file is under `scripts/`, which the pool
    does NOT cover -- a hooks or tests file would also satisfy the pool clause, so this
    test could not tell the cited-file clause had been deleted."""
    root = _tree(tmp_path, {"scripts/check_suite.py": "def test_real_one():\n    pass\n"})
    _only(monkeypatch, root)
    body = "fixed; see `scripts/check_suite.py` and `test_real_one`"
    assert rr.names_a_check(body, root)


def test_a_bare_name_defined_in_an_UNCITED_tests_file_resolves(tmp_path, monkeypatch):
    """Clause: def anywhere under tests/. F40 and F74 are this shape in the real register."""
    root = _tree(tmp_path, {"tests/test_elsewhere.py": "def test_somewhere():\n    pass\n"})
    _only(monkeypatch, root)
    assert rr.names_a_check("fixed; see `test_somewhere`", root)


def test_a_bare_name_defined_in_an_UNCITED_hooks_file_resolves(tmp_path, monkeypatch):
    """Clause: def anywhere under .claude/hooks/."""
    root = _tree(tmp_path, {".claude/hooks/test_hooks.py": "def test_hook_thing():\n    pass\n"})
    _only(monkeypatch, root)
    assert rr.names_a_check("fixed; see `test_hook_thing`", root)


def test_a_bare_name_that_is_a_FILE_STEM_still_resolves(tmp_path, monkeypatch):
    """Clause: tests/<name>.py. The pre-existing behaviour, kept -- real entries use it."""
    root = _tree(tmp_path, {"tests/test_stem.py": ""})
    _only(monkeypatch, root)
    assert rr.names_a_check("fixed; see `test_stem`", root) == "tests/test_stem.py"


def test_one_resolving_bare_name_does_not_cover_one_that_does_not(tmp_path, monkeypatch):
    """Clause: EVERY, not ANY -- with no file citation in front to shadow it."""
    root = _tree(tmp_path, {"tests/test_stem.py": ""})
    _only(monkeypatch, root)
    assert rr.names_a_check("fixed; see `test_stem` and `test_ghost`", root) is None


def test_a_def_that_merely_MENTIONS_the_name_is_not_a_definition(tmp_path, monkeypatch):
    """A name in a comment or a string is not a test. Only `def <name>(` counts."""
    root = _tree(tmp_path, {"tests/test_other.py":
                            "# test_only_mentioned is planned\n"
                            "X = 'test_only_mentioned'\n"
                            "def test_only_mentioned_but_longer():\n    pass\n"})
    _only(monkeypatch, root)
    assert rr.names_a_check("fixed; see `test_only_mentioned`", root) is None


def test_selftest_and_plain_file_citations_behave_as_before(tmp_path, monkeypatch):
    root = _tree(tmp_path, {"tests/test_real.py": ""})
    _only(monkeypatch, root)
    assert rr.names_a_check("fixed; selftest", root) == "selftest"
    assert rr.names_a_check("fixed; `tests/test_real.py`", root) == "tests/test_real.py"
    assert rr.names_a_check("fixed; `tests/test_absent.py`", root) is None


# --- tools/basex/ (2026-09-14) -----------------------------------------------------------
# F122's checks live in tools/basex/test_ask.py, which the citation pattern could not see, so a
# TRUE citation read as "names no check" and the entry had to use the NO RE-DERIVATION opt-out.
# Only TEST files there count: F46 cites tools/basex/ask.py, the tool itself, which is not a check.

def test_a_tools_basex_TEST_FILE_citation_resolves(tmp_path, monkeypatch):
    root = _tree(tmp_path, {"tools/basex/test_ask.py": "def test_real():\n    pass\n"})
    _only(monkeypatch, root)
    assert rr.names_a_check("fixed; see `tools/basex/test_ask.py`", root) == "tools/basex/test_ask.py"


def test_a_bare_name_defined_in_a_CITED_tools_basex_test_resolves(tmp_path, monkeypatch):
    """F122's shape: the entry cites tools/basex/test_ask.py AND names tests defined in it."""
    root = _tree(tmp_path, {"tools/basex/test_ask.py": "def test_only_here():\n    pass\n"})
    _only(monkeypatch, root)
    body = "fixed; see `tools/basex/test_ask.py` (`test_only_here`)"
    assert rr.names_a_check(body, root) == "tools/basex/test_ask.py"


def test_TWIN_a_bare_name_defined_only_in_an_UNCITED_tools_basex_test_does_not_resolve(tmp_path, monkeypatch):
    """F46's shape, MEASURED on the real register: that entry names
    `test_unimportable_engine_reports_UNKNOWN_not_a_traceback` as a test the defect BROKE, and the
    file it lives in (tools/basex/test_staleness.py) is not cited. Pooling tools/basex made the
    mention count as the entry's check. It must not."""
    root = _tree(tmp_path, {"tools/basex/test_staleness.py": "def test_a_casualty():\n    pass\n"})
    _only(monkeypatch, root)
    assert rr.names_a_check("the defect broke `test_a_casualty`", root) is None


def test_TWIN_a_tools_basex_TOOL_is_not_a_check(tmp_path, monkeypatch):
    """F46 names tools/basex/ask.py -- the program the fix is in, not a test of it."""
    root = _tree(tmp_path, {"tools/basex/ask.py": "print('a tool')\n"})
    _only(monkeypatch, root)
    assert rr.names_a_check("the fix is in `tools/basex/ask.py`", root) is None


def test_TWIN_a_MISSING_tools_basex_test_file_is_not_a_check(tmp_path, monkeypatch):
    root = _tree(tmp_path, {"tools/basex/test_other.py": "def test_x():\n    pass\n"})
    _only(monkeypatch, root)
    assert rr.names_a_check("see `tools/basex/test_nope.py`", root) is None

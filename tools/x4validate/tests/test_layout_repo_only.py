"""`_layout.require_repo` -- the one door for a test that needs repo-only content (R2-B1).

Each clause of "skip iff installed layout AND content absent" has its own twin, so neither
clause can be dropped without a test going red (CLAUDE.md #26)."""
from __future__ import annotations

import pytest

import _layout


def _installed(tmp_path):
    (tmp_path / "tools").mkdir()                 # an install: no agent/
    return tmp_path


def _checkout(tmp_path):
    (tmp_path / "agent").mkdir()
    return tmp_path


def test_installed_layout_and_ABSENT_content_SKIPS_with_a_counted_named_reason(tmp_path):
    root = _installed(tmp_path)
    with pytest.raises(pytest.skip.Exception) as e:
        _layout.require_repo("agent/rules/codex-rules.yaml", why="the rule rows", root=root)
    msg = str(e.value)
    assert _layout.REASON in msg and "agent/rules/codex-rules.yaml" in msg and "rule rows" in msg


def test_TWIN_a_CHECKOUT_missing_the_same_file_does_NOT_skip(tmp_path):
    """A checkout that lost a source file is broken, not installed: the test must run (and fail)."""
    _layout.require_repo("agent/rules/codex-rules.yaml", root=_checkout(tmp_path))


def test_TWIN_an_installed_layout_WITH_the_content_does_NOT_skip(tmp_path):
    root = _installed(tmp_path)
    (root / "docs").mkdir()
    _layout.require_repo("docs", root=root)


def test_installed_layout_is_keyed_on_the_agent_source_dir(tmp_path):
    assert _layout.installed_layout(_installed(tmp_path)) is True
    assert _layout.installed_layout(_checkout(tmp_path)) is False

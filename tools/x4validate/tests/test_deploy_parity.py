"""`gates/deploy_parity.py` -- the game root's `.claude/` must equal the repo's.

WHY. The repo is the SOURCE; the game root's `.claude/` is a deployed copy that this
machine's sessions load. MEASURED 2026-09-13: 25 vs 23 files, five drifted -- two skills
written straight into the game root and never shipped, one skill newer in the game root,
two agents with personal absolute paths hand-edited into the deployed copy. Dev's
`published_surface_drift.py` saw drift of this kind and had an ACCEPT baseline, which is
how it lasted. This gate has none: any drift is rc 1, named with its direction.

One twin per clause.
"""

from __future__ import annotations

import pytest

from conftest import import_gate

dp = import_gate("deploy_parity")

NL = chr(10)
CRLF = chr(13) + chr(10)


def _tree(root, files: dict[str, str | bytes]):
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return root


def _pair(tmp_path, repo: dict, game: dict):
    return (_tree(tmp_path / "repo" / ".claude", repo),
            _tree(tmp_path / "game" / ".claude", game))


def test_identical_files_are_identical(tmp_path):
    r, g = _pair(tmp_path, {"skills/a/SKILL.md": "x\n"}, {"skills/a/SKILL.md": "x\n"})
    rows = dp.compare_trees(r, g)
    assert [(x.name, x.state) for x in rows] == [("skills/a/SKILL.md", "identical")]


def test_CRLF_alone_is_not_drift(tmp_path):
    r, g = _pair(tmp_path, {"hooks/h.sh": "a" + NL + "b" + NL},
                 {"hooks/h.sh": "a" + CRLF + "b" + CRLF})
    assert dp.compare_trees(r, g)[0].state == "identical"


def test_the_installer_rewrite_alone_is_not_drift(tmp_path):
    """install.sh:776 rewrites $CLAUDE_PROJECT_DIR -> $X4_TOOLKIT for the global/separate
    layout. A deployed copy that differs ONLY by that rewrite is the same file."""
    r, g = _pair(tmp_path, {"skills/a/SKILL.md": "cd $CLAUDE_PROJECT_DIR/tools/x4validate\n"},
                 {"skills/a/SKILL.md": "cd $X4_TOOLKIT/tools/x4validate\n"})
    assert dp.compare_trees(r, g)[0].state == "identical (after the installer rewrite)"


def test_the_rewrite_is_NOT_excused_outside_skills_and_agents(tmp_path):
    """install.sh rewrites skills and agents ONLY. A rewritten settings.json or hook would
    point a session at the repo's hooks instead of its own -- that is drift."""
    r, g = _pair(tmp_path,
                 {"settings.json": '"bash $CLAUDE_PROJECT_DIR/.claude/hooks/h.sh"\n',
                  "hooks/h.sh": ". $CLAUDE_PROJECT_DIR/x\n"},
                 {"settings.json": '"bash $X4_TOOLKIT/.claude/hooks/h.sh"\n',
                  "hooks/h.sh": ". $X4_TOOLKIT/x\n"})
    assert {x.name: x.state for x in dp.compare_trees(r, g)} == \
        {"hooks/h.sh": "drift", "settings.json": "drift"}


def test_an_AGENT_rewrite_is_excused_like_a_skill(tmp_path):
    r, g = _pair(tmp_path, {"agents/a.md": "cd $CLAUDE_PROJECT_DIR/tools\n"},
                 {"agents/a.md": "cd $X4_TOOLKIT/tools\n"})
    assert dp.compare_trees(r, g)[0].state == "identical (after the installer rewrite)"


def test_the_reverse_rewrite_is_NOT_excused(tmp_path):
    """The rewrite goes one way. A REPO file carrying $X4_TOOLKIT would break every
    in-game install, so it must read as drift, not as the installed form."""
    r, g = _pair(tmp_path, {"skills/a/SKILL.md": "cd $X4_TOOLKIT/tools/x4validate\n"},
                 {"skills/a/SKILL.md": "cd $CLAUDE_PROJECT_DIR/tools/x4validate\n"})
    assert dp.compare_trees(r, g)[0].state == "drift"


def test_only_in_repo_is_reported_with_that_direction(tmp_path):
    r, g = _pair(tmp_path, {"skills/new/SKILL.md": "x\n"}, {})
    assert [(x.name, x.state) for x in dp.compare_trees(r, g)] == \
        [("skills/new/SKILL.md", "only in repo")]


def test_only_in_game_root_is_reported_with_that_direction(tmp_path):
    r, g = _pair(tmp_path, {}, {"skills/local/SKILL.md": "x\n"})
    assert [(x.name, x.state) for x in dp.compare_trees(r, g)] == \
        [("skills/local/SKILL.md", "only in game root")]


def test_drift_counts_lines_on_EACH_side_and_names_no_winner(tmp_path):
    r, g = _pair(tmp_path, {"agents/a.md": "one\ntwo\nrepo-only\n"},
                 {"agents/a.md": "one\ntwo\ngame-only-1\ngame-only-2\n"})
    row = dp.compare_trees(r, g)[0]
    assert row.state == "drift"
    assert (row.game_only, row.repo_only) == (2, 1)


def test_KEEP_LOCAL_files_are_excluded(tmp_path):
    """install.sh's X4_KEEP_LOCAL: per-machine files that must never travel."""
    r, g = _pair(tmp_path,
                 {"settings.json": "{}\n"},
                 {"settings.json": "{}\n", "x4-paths.env": "X4_GAME=here\n",
                  "settings.local.json": "{}\n", "backups/2026/x.bak": "old\n"})
    assert [x.name for x in dp.compare_trees(r, g)] == ["settings.json"]


def test_caches_and_editor_backups_are_excluded(tmp_path):
    r, g = _pair(tmp_path, {"hooks/h.sh": "x\n"},
                 {"hooks/h.sh": "x\n", "hooks/__pycache__/h.cpython-313.pyc": b"\x00",
                  "hooks/h.sh.bak": "x\n"})
    assert [x.name for x in dp.compare_trees(r, g)] == ["hooks/h.sh"]


def test_files_outside_the_whitelisted_subtrees_are_ignored(tmp_path):
    """The population is what the game-root repo's own .gitignore whitelists. Claude
    Code's runtime files under .claude/ are not part of the deployment."""
    r, g = _pair(tmp_path, {"hooks/h.sh": "x\n"},
                 {"hooks/h.sh": "x\n", "scheduled_tasks.lock": "", ".reference-buildid": "1",
                  "some-runtime-dir/state.json": "{}"})
    assert [x.name for x in dp.compare_trees(r, g)] == ["hooks/h.sh"]


def test_a_skill_SUBFILE_is_compared_not_just_SKILL_md(tmp_path):
    """The generated x4-cli-reference skill carries reference/*.md; dev's gate compared
    SKILL.md only and would never have seen those go stale."""
    r, g = _pair(tmp_path, {"skills/a/SKILL.md": "x\n", "skills/a/reference/b.md": "new\n"},
                 {"skills/a/SKILL.md": "x\n", "skills/a/reference/b.md": "old\n"})
    states = {x.name: x.state for x in dp.compare_trees(r, g)}
    assert states == {"skills/a/SKILL.md": "identical", "skills/a/reference/b.md": "drift"}


def test_no_game_root_is_a_REFUSAL(monkeypatch, capsys):
    monkeypatch.setattr(dp, "game_claude_dir", lambda: None)
    assert dp.main() == 2
    assert "REFUSING" in capsys.readouterr().err


def test_an_empty_comparison_is_a_REFUSAL(tmp_path, monkeypatch, capsys):
    """Two empty trees agree about nothing. That is not parity."""
    r, g = _pair(tmp_path, {}, {})
    monkeypatch.setattr(dp, "repo_claude_dir", lambda: r)
    monkeypatch.setattr(dp, "game_claude_dir", lambda: g)
    assert dp.main() == 2
    assert "REFUSING" in capsys.readouterr().err


def test_main_is_rc_1_on_drift_and_names_every_row(tmp_path, monkeypatch, capsys):
    r, g = _pair(tmp_path, {"skills/a/SKILL.md": "x\n", "skills/b/SKILL.md": "x\n"},
                 {"skills/a/SKILL.md": "x\n", "skills/c/SKILL.md": "x\n"})
    monkeypatch.setattr(dp, "repo_claude_dir", lambda: r)
    monkeypatch.setattr(dp, "game_claude_dir", lambda: g)
    assert dp.main() == 1
    out = capsys.readouterr()
    assert "skills/b/SKILL.md" in out.err and "only in repo" in out.err
    assert "skills/c/SKILL.md" in out.err and "only in game root" in out.err


def test_main_is_rc_0_only_when_every_row_is_identical(tmp_path, monkeypatch):
    r, g = _pair(tmp_path, {"skills/a/SKILL.md": "x\n"}, {"skills/a/SKILL.md": "x\n"})
    monkeypatch.setattr(dp, "repo_claude_dir", lambda: r)
    monkeypatch.setattr(dp, "game_claude_dir", lambda: g)
    assert dp.main() == 0


def test_the_real_trees(capsys):
    """END TO END on this machine. Skips only when no game root is configured -- a
    machine WITH one must be at parity, or the deploy script has work to do."""
    if dp.game_claude_dir() is None:
        pytest.skip("no game root configured -- deploy parity NOT CHECKED")
    rc = dp.main()
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err

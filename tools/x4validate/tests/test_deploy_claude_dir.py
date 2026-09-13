"""`scripts/deploy-claude-dir.py` -- repo `.claude/` into a game root, one direction.

Every case runs against a SCRATCH git repo and a scratch destination, never the real game
root. One test per clause, because each guard shadows the ones behind it.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent
SRC = PKG / "scripts" / "deploy-claude-dir.py"


def _load():
    import sys
    spec = importlib.util.spec_from_file_location("deploy_claude_dir_under_test", SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod     # @dataclass needs its module registered (see the script)
    spec.loader.exec_module(mod)
    return mod


dep = _load()


def _git(root: Path, *args: str) -> None:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / ".claude" / "skills" / "a").mkdir(parents=True)
    try:
        _git(root, "init", "-q")
    except (OSError, AssertionError):
        pytest.skip("git unavailable -- the deploy's history check cannot be exercised")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "core.autocrlf", "false")
    return root


def _commit(repo: Path, rel: str, content: bytes, msg: str = "c") -> None:
    p = repo / ".claude" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    _git(repo, "add", "--", f".claude/{rel}")
    _git(repo, "commit", "-q", "-m", msg)


@pytest.fixture
def dest(tmp_path):
    """A destination WITHOUT tools/x4validate beside it -- the game-root layout."""
    d = tmp_path / "game" / ".claude"
    d.mkdir(parents=True)
    return d


def _kinds(actions):
    return {a.name: a.kind for a in actions}


def test_a_dry_run_writes_nothing(repo, dest):
    _commit(repo, "skills/a/SKILL.md", b"v1\n")
    rc = dep.main(["--repo", str(repo), "--dest", str(dest)])
    assert rc == 0
    assert not (dest / "skills" / "a" / "SKILL.md").exists()


def test_apply_creates_a_missing_file(repo, dest):
    _commit(repo, "skills/a/SKILL.md", b"v1\n")
    assert dep.main(["--repo", str(repo), "--dest", str(dest), "--apply"]) == 0
    assert (dest / "skills" / "a" / "SKILL.md").read_bytes() == b"v1\n"


def test_a_STALE_deploy_that_matches_an_older_commit_is_updated(repo, dest):
    _commit(repo, "skills/a/SKILL.md", b"v1\n")
    _commit(repo, "skills/a/SKILL.md", b"v2\n")
    (dest / "skills" / "a").mkdir(parents=True)
    (dest / "skills" / "a" / "SKILL.md").write_bytes(b"v1\n")
    assert _kinds(dep.plan(repo, dest))["skills/a/SKILL.md"] == dep.UPDATE


def test_a_NEVER_PORTED_local_edit_is_REFUSED_and_left_untouched(repo, dest):
    _commit(repo, "skills/a/SKILL.md", b"v1\n")
    (dest / "skills" / "a").mkdir(parents=True)
    (dest / "skills" / "a" / "SKILL.md").write_bytes(b"v1\nlocal rung nobody ported\n")
    assert dep.main(["--repo", str(repo), "--dest", str(dest), "--apply"]) == 1
    assert (dest / "skills" / "a" / "SKILL.md").read_bytes() == b"v1\nlocal rung nobody ported\n"


def test_force_overrides_the_refusal_for_that_one_file(repo, dest):
    _commit(repo, "skills/a/SKILL.md", b"v1\n")
    (dest / "skills" / "a").mkdir(parents=True)
    (dest / "skills" / "a" / "SKILL.md").write_bytes(b"hand-edited\n")
    assert dep.main(["--repo", str(repo), "--dest", str(dest), "--apply",
                     "--force", "skills/a/SKILL.md"]) == 0
    assert (dest / "skills" / "a" / "SKILL.md").read_bytes() == b"v1\n"


def test_force_naming_a_file_outside_the_deployment_is_a_refusal(repo, dest):
    _commit(repo, "skills/a/SKILL.md", b"v1\n")
    assert dep.main(["--repo", str(repo), "--dest", str(dest), "--force", "nope.md"]) == 2


def test_the_rewrite_is_applied_when_the_toolkit_is_NOT_beside_the_destination(repo, dest):
    _commit(repo, "skills/a/SKILL.md", b"cd $CLAUDE_PROJECT_DIR/tools/x4validate\n")
    assert dep.main(["--repo", str(repo), "--dest", str(dest), "--apply"]) == 0
    assert (dest / "skills" / "a" / "SKILL.md").read_bytes() == b"cd $X4_TOOLKIT/tools/x4validate\n"


def test_HOOKS_and_SETTINGS_are_never_rewritten(repo, dest):
    """The bug the first real dry run found: an unscoped rewrite planned to point the game
    root's settings.json at the REPO's hooks. install.sh rewrites skills and agents only."""
    _commit(repo, "settings.json", b'"bash $CLAUDE_PROJECT_DIR/.claude/hooks/h.sh"\n')
    _commit(repo, "hooks/h.sh", b". $CLAUDE_PROJECT_DIR/.claude/hooks/_env.sh\n")
    assert dep.main(["--repo", str(repo), "--dest", str(dest), "--apply"]) == 0
    assert (dest / "settings.json").read_bytes() == b'"bash $CLAUDE_PROJECT_DIR/.claude/hooks/h.sh"\n'
    assert (dest / "hooks" / "h.sh").read_bytes() == b". $CLAUDE_PROJECT_DIR/.claude/hooks/_env.sh\n"


def test_an_identical_unrewritten_HOOK_is_left_alone(repo, dest):
    """The game root's hooks today: byte-identical to the repo. Must be 'identical', not
    an update that rewrites them."""
    _commit(repo, "hooks/h.sh", b". $CLAUDE_PROJECT_DIR/x\n")
    (dest / "hooks").mkdir(parents=True)
    (dest / "hooks" / "h.sh").write_bytes(b". $CLAUDE_PROJECT_DIR/x\n")
    assert _kinds(dep.plan(repo, dest))["hooks/h.sh"] == dep.SKIP


def test_a_hand_REWRITTEN_hook_is_refused_not_recognised(repo, dest):
    """The installer never produces a rewritten hook, so one is a local edit."""
    _commit(repo, "hooks/h.sh", b". $CLAUDE_PROJECT_DIR/x\n")
    (dest / "hooks").mkdir(parents=True)
    (dest / "hooks" / "h.sh").write_bytes(b". $X4_TOOLKIT/x\n")
    assert _kinds(dep.plan(repo, dest))["hooks/h.sh"] == dep.REFUSE


def test_the_rewrite_is_NOT_applied_when_the_toolkit_IS_beside_the_destination(repo, tmp_path):
    d = tmp_path / "inplace" / ".claude"
    d.mkdir(parents=True)
    (tmp_path / "inplace" / "tools" / "x4validate").mkdir(parents=True)
    _commit(repo, "skills/a/SKILL.md", b"cd $CLAUDE_PROJECT_DIR/tools/x4validate\n")
    assert dep.main(["--repo", str(repo), "--dest", str(d), "--apply"]) == 0
    assert (d / "skills" / "a" / "SKILL.md").read_bytes() == b"cd $CLAUDE_PROJECT_DIR/tools/x4validate\n"


def test_a_deployed_UNREWRITTEN_copy_is_a_known_version_and_gets_rewritten(repo, dest):
    """The game root's five skills today: identical to the repo, never rewritten."""
    _commit(repo, "skills/a/SKILL.md", b"cd $CLAUDE_PROJECT_DIR/x\n")
    (dest / "skills" / "a").mkdir(parents=True)
    (dest / "skills" / "a" / "SKILL.md").write_bytes(b"cd $CLAUDE_PROJECT_DIR/x\n")
    assert _kinds(dep.plan(repo, dest))["skills/a/SKILL.md"] == dep.UPDATE


def test_a_CRLF_destination_stays_CRLF(repo, dest):
    _commit(repo, "skills/a/SKILL.md", b"one\ntwo\n")
    _commit(repo, "skills/a/SKILL.md", b"one\ntwo\nthree\n")
    (dest / "skills" / "a").mkdir(parents=True)
    (dest / "skills" / "a" / "SKILL.md").write_bytes(b"one\r\ntwo\r\n")
    assert dep.main(["--repo", str(repo), "--dest", str(dest), "--apply"]) == 0
    assert (dest / "skills" / "a" / "SKILL.md").read_bytes() == b"one\r\ntwo\r\nthree\r\n"


def test_a_read_only_destination_is_written_and_RE_LOCKED(repo, dest):
    _commit(repo, "skills/a/SKILL.md", b"v1\n")
    _commit(repo, "skills/a/SKILL.md", b"v2\n")
    f = dest / "skills" / "a" / "SKILL.md"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"v1\n")
    os.chmod(f, stat.S_IREAD)
    try:
        assert dep.main(["--repo", str(repo), "--dest", str(dest), "--apply"]) == 0
        assert f.read_bytes() == b"v2\n"
        assert not (f.stat().st_mode & stat.S_IWRITE), "the lock was not restored"
    finally:
        os.chmod(f, stat.S_IREAD | stat.S_IWRITE)


def test_a_file_only_in_the_destination_is_REPORTED_never_deleted(repo, dest):
    _commit(repo, "skills/a/SKILL.md", b"v1\n")
    (dest / "skills" / "local").mkdir(parents=True)
    (dest / "skills" / "local" / "SKILL.md").write_bytes(b"mine\n")
    assert dep.main(["--repo", str(repo), "--dest", str(dest), "--apply"]) == 0
    assert (dest / "skills" / "local" / "SKILL.md").read_bytes() == b"mine\n"
    assert _kinds(dep.plan(repo, dest))["skills/local/SKILL.md"] == dep.REPORT


def test_per_machine_files_are_never_touched(repo, dest):
    _commit(repo, "settings.json", b"{}\n")
    (dest / "x4-paths.env").write_bytes(b"X4_GAME=here\n")
    assert dep.main(["--repo", str(repo), "--dest", str(dest), "--apply"]) == 0
    assert (dest / "x4-paths.env").read_bytes() == b"X4_GAME=here\n"
    assert "x4-paths.env" not in _kinds(dep.plan(repo, dest))


def test_after_apply_the_parity_gate_agrees(repo, dest):
    _commit(repo, "skills/a/SKILL.md", b"cd $CLAUDE_PROJECT_DIR/x\n")
    _commit(repo, "hooks/h.sh", b"echo hi\n")
    assert dep.main(["--repo", str(repo), "--dest", str(dest), "--apply"]) == 0
    rows = dep.parity.compare_trees(repo / ".claude", dest)
    assert rows and all(r.at_parity for r in rows), [(r.name, r.state) for r in rows]


def test_the_destination_being_the_repo_is_a_refusal(repo):
    _commit(repo, "skills/a/SKILL.md", b"v1\n")
    assert dep.main(["--repo", str(repo), "--dest", str(repo / ".claude")]) == 2

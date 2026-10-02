"""x4guard copied under .codex/hooks finds its roots exactly as under .claude/hooks (lane B Task 6).

Kept in its own file (not test_x4guard_check.py) so it merges cleanly with lane E's edits there.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1]
REPO = PKG.parents[1]
GUARDS = REPO / "agent" / "guards" / "claude-hooks"


@pytest.fixture
def env_without_toolkit(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "X4_TOOLKIT"}
    env.update(X4_CONFIG="/nonexistent", X4_REFERENCE=str(tmp_path / "ref"), X4_GAME=str(tmp_path / "game"))
    env.pop("X4_BASH", None)
    return env


def check(env, script):
    r = subprocess.run([sys.executable, str(script), "check", "--kind", "shell", "--shell", "bash",
                        "--command", "echo hi"], capture_output=True, env=env, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_runs_when_deployed_under_codex_hooks(tmp_path, env_without_toolkit):
    codex_hooks = tmp_path / "root" / ".codex" / "hooks"
    shutil.copytree(GUARDS, codex_hooks)
    v = check(env_without_toolkit, codex_hooks / "x4guard.py")
    assert not v["inert"] and v["decision"] == "allow", v["reason"]


def test_TWIN_claude_hooks_still_runs(tmp_path, env_without_toolkit):
    claude_hooks = tmp_path / "root" / ".claude" / "hooks"
    shutil.copytree(GUARDS, claude_hooks)
    assert not check(env_without_toolkit, claude_hooks / "x4guard.py")["inert"]


@pytest.mark.parametrize("where", [("x", "hooks"), (".codex", "guards"), (".codexx", "hooks")])
def test_TWIN_other_dir_without_toolkit_still_inert(tmp_path, env_without_toolkit, where):
    lone = tmp_path.joinpath(*where)
    shutil.copytree(GUARDS, lone)
    v = check(env_without_toolkit, lone / "x4guard.py")
    assert v["inert"] and v["decision"] == "deny"

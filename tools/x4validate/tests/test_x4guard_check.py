"""x4guard check: one side-effect-free front door to the guards, for any agent.

A guard that cannot run must never read as allow -- it is an inert deny with the cause named.
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
X4GUARD = REPO / ".claude" / "hooks" / "x4guard.py"
HAS_PWSH = bool(shutil.which("pwsh") or shutil.which("powershell"))


@pytest.fixture
def sandbox(tmp_path):
    tk, game = tmp_path / "toolkit", tmp_path / "X4 Foundations"
    for d in (tk / "dev" / "mymod", tk / "reference" / "libraries", game / "extensions",
              tmp_path / "profile" / "save", tmp_path / "mods", tmp_path / "docs", tmp_path / "backups"):
        d.mkdir(parents=True)
    (tk / "reference" / "libraries" / "wares.xml").write_text("ref\n", encoding="utf-8")
    env = dict(os.environ, X4_TOOLKIT=str(tk), X4_GAME=str(game), X4_REFERENCE=str(tk / "reference"),
               X4_PROFILE=str(tmp_path / "profile"), X4_MODS=str(tmp_path / "mods"),
               X4_EXTENSIONS=str(game / "extensions"), X4_SAVES=str(tmp_path / "profile" / "save"),
               X4_DOCUMENTS=str(tmp_path / "docs"), X4_BACKUPS=str(tmp_path / "backups"),
               X4_CONFIG="/nonexistent")
    env.pop("X4_BASH", None)
    return tmp_path, tk, env


def check(env, *args, script=X4GUARD):
    r = subprocess.run([sys.executable, str(script), "check", *args], capture_output=True, env=env, timeout=120)
    return r.returncode, (json.loads(r.stdout) if r.returncode == 0 else None), r.stderr.decode("utf-8", "replace")


def test_shell_bash_delete_in_reference_denies(sandbox):
    _, tk, env = sandbox
    rc, v, _ = check(env, "--kind", "shell", "--shell", "bash", "--command",
                     f"rm -rf '{(tk / 'reference' / 'libraries').as_posix()}'")
    assert rc == 0 and v["decision"] == "deny" and not v["inert"] and v["guards"] == ["protect-bash.sh"]


@pytest.mark.skipif(not HAS_PWSH, reason="no PowerShell to translate with -- routing NOT checked here")
def test_shell_routing_decides_the_verdict(sandbox):
    """The measured Codex hole: PowerShell text judged as bash. The flag must decide."""
    _, tk, env = sandbox
    cmd = f"Set-Content -Path '{tk / 'reference' / 'libraries' / 'wares.xml'}' -Value 'x'"
    _, as_ps, _ = check(env, "--kind", "shell", "--shell", "powershell", "--command", cmd)
    _, as_bash, _ = check(env, "--kind", "shell", "--shell", "bash", "--command", cmd)
    assert as_ps["decision"] == "deny" and not as_ps["inert"]
    assert as_bash["decision"] != "deny"   # if this ever denies, pick a new twin: routing is no longer shown


def test_shell_echo_allows(sandbox):
    _, _, env = sandbox
    rc, v, _ = check(env, "--kind", "shell", "--shell", "bash", "--command", "echo hello")
    assert rc == 0 and v["decision"] == "allow" and not v["inert"]


@pytest.mark.parametrize("kind", ["write", "delete"])
def test_write_and_delete_into_reference_deny(sandbox, kind):
    _, tk, env = sandbox
    rc, v, _ = check(env, "--kind", kind, "--path", str(tk / "reference" / "libraries" / "wares.xml"))
    assert rc == 0 and v["decision"] == "deny"
    # a delete is judged by protect-files AND an rm through protect-bash (final-review ruling I4)
    assert v["guards"] == (["protect-files.sh"] if kind == "write" else ["protect-files.sh", "protect-bash.sh"])


def test_write_path_with_spaces_and_backslashes(sandbox):
    tmp, _, env = sandbox
    p = str(tmp / "X4 Foundations" / "libraries" / "wares.xml").replace("/", "\\")
    _, v, _ = check(env, "--kind", "write", "--path", p)
    assert v["decision"] == "deny" and not v["inert"]    # a base-game file, backslashes and a space


def test_manifest_advises_and_profile_asks(sandbox):
    tmp, tk, env = sandbox
    _, adv, _ = check(env, "--kind", "write", "--path", str(tk / "dev" / "mymod" / "content.xml"))
    _, ask, _ = check(env, "--kind", "write", "--path", str(tmp / "profile" / "content.xml"))
    assert adv["decision"] == "advise" and ask["decision"] == "ask"


def test_check_has_no_side_effects(sandbox):
    """backup-before-edit.sh copies an EXISTING file into $X4_BACKUPS. A check must never run it.
    The target exists (the backup hook skips absent files, which would make this vacuous) and
    the check must have produced a real verdict (a check that never ran has no side effects)."""
    tmp, tk, env = sandbox
    target = tk / "dev" / "mymod" / "content.xml"
    target.write_text("<content/>\n", encoding="utf-8")
    rc, v, _ = check(env, "--kind", "write", "--path", str(target))
    assert rc == 0 and v["decision"] == "advise" and not v["inert"]
    assert list((tmp / "backups").iterdir()) == []


def test_missing_guard_is_inert_deny(sandbox, tmp_path):
    _, _, env = sandbox
    lone = tmp_path / "lone"
    lone.mkdir()
    shutil.copy2(X4GUARD, lone / "x4guard.py")
    rc, v, _ = check(env, "--kind", "shell", "--shell", "bash", "--command", "echo hi", script=lone / "x4guard.py")
    assert rc == 0 and v["decision"] == "deny" and v["inert"] and "missing" in v["reason"]


def test_wsl_bash_refused(sandbox):
    _, _, env = sandbox
    env = dict(env, X4_BASH=r"C:\Windows\System32\bash.exe")
    _, v, _ = check(env, "--kind", "shell", "--shell", "bash", "--command", "echo hi")
    assert v["decision"] == "deny" and v["inert"] and "WSL" in v["reason"]


def test_missing_bash_is_inert_deny(sandbox, tmp_path):
    _, _, env = sandbox
    env = dict(env, X4_BASH=str(tmp_path / "no-such-bash.exe"))
    _, v, _ = check(env, "--kind", "shell", "--shell", "bash", "--command", "echo hi")
    assert v["decision"] == "deny" and v["inert"]


def test_unparseable_guard_output_is_inert_deny():
    sys.path.insert(0, str(X4GUARD.parent))
    try:
        import x4guard
    finally:
        sys.path.pop(0)
    with pytest.raises(ValueError):
        x4guard.parse_hook_output("{not json")
    with pytest.raises(ValueError):
        x4guard.parse_hook_output('{"hookSpecificOutput": {"permissionDecision": "maybe"}}')


def test_usage_error_is_rc2(sandbox):
    _, _, env = sandbox
    rc, _, err = check(env, "--kind", "shell", "--shell", "bash")
    assert rc == 2 and "--command" in err


# ---------------------------------------------------------------- final-review fixes (I1-I5)

def _check_in(env, cwd, *args, script=X4GUARD):
    r = subprocess.run([sys.executable, str(script), "check", *args], capture_output=True, env=env,
                       timeout=120, cwd=str(cwd))
    return json.loads(r.stdout)


def test_I1_relative_path_is_resolved_from_the_callers_cwd(sandbox):
    """Codex apply_patch paths are relative; judged unresolved, a reference/ write was ALLOWED."""
    _, tk, env = sandbox
    v = _check_in(env, tk, "--kind", "write", "--path", "reference/libraries/wares.xml")
    assert v["decision"] == "deny" and not v["inert"]


def _hooks_copy(dst):
    shutil.copytree(X4GUARD.parent, dst, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return dst / "x4guard.py"


def test_I2_a_copy_outside_claude_hooks_refuses_without_X4_TOOLKIT(sandbox, tmp_path):
    """The SOURCE copy (agent/guards/claude-hooks) derives the toolkit root from its own folder
    and so never finds the configured roots: it allowed a hard-blocked write. It must refuse."""
    _, tk, env = sandbox
    script = _hooks_copy(tmp_path / "agent" / "guards" / "claude-hooks")
    env = {k: v for k, v in env.items() if k not in ("X4_TOOLKIT", "CLAUDE_PROJECT_DIR")}
    v = _check_in(env, tmp_path, "--kind", "write", "--path", str(tk / "reference" / "libraries" / "wares.xml"),
                  script=script)
    assert v["decision"] == "deny" and v["inert"] and ".claude/hooks" in v["reason"]


def test_I2_TWIN_a_deployed_claude_hooks_copy_is_not_refused_for_location(tmp_path):
    """The twin of the location clause only. Root RESOLUTION is not asserted here: under %TEMP%
    Git Bash spells the tree /tmp/..., the payload spells C:/.../Temp/..., and they never match
    (MEASURED 2026-10-01), so a tmp tree cannot show a real install's verdict."""
    root = tmp_path / "tk2"
    script = _hooks_copy(root / ".claude" / "hooks")
    env = {k: v for k, v in os.environ.items() if not k.startswith("X4_") and k != "CLAUDE_PROJECT_DIR"}
    env["X4_CONFIG"] = "/nonexistent"
    v = _check_in(env, root, "--kind", "write", "--path", str(root / "x.txt"), script=script)
    assert not v["inert"], v

@pytest.mark.skipif(not HAS_PWSH, reason="no PowerShell -- the untranslatable path is NOT checked here")
def test_I3_a_guard_that_checked_nothing_is_inert_not_a_plain_ask(sandbox):
    _, tk, env = sandbox
    env = dict(env, X4_PWSH=str(tk / "no-such-pwsh.exe"))
    v = _check_in(env, tk, "--kind", "shell", "--shell", "powershell", "--command",
                  f"Remove-Item -Force '{tk / 'reference' / 'libraries' / 'wares.xml'}'")
    assert v["decision"] == "deny" and v["inert"], v


def test_I4_a_delete_is_at_least_as_strict_as_rm(sandbox):
    tmp, tk, env = sandbox
    target = tmp / "profile" / "save" / "quick.xml.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x")
    rank = {"allow": 0, "advise": 1, "ask": 2, "deny": 3}
    d = _check_in(env, tk, "--kind", "delete", "--path", str(target))
    w = _check_in(env, tk, "--kind", "write", "--path", str(target))
    s = _check_in(env, tk, "--kind", "shell", "--shell", "bash", "--command", f"rm -f '{target.as_posix()}'")
    assert rank[d["decision"]] == max(rank[w["decision"]], rank[s["decision"]])
    assert d["guards"] == ["protect-files.sh", "protect-bash.sh"]
    assert target.exists()                      # verdict only: nothing executed


@pytest.mark.parametrize("body", ["exit 1", "printf 'not json'", "sleep 6"])
def test_I5_a_guard_that_fails_is_an_inert_deny(sandbox, tmp_path, body):
    _, tk, env = sandbox
    hooks = tmp_path / "stub" / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy2(X4GUARD, hooks / "x4guard.py")
    (hooks / "protect-bash.sh").write_text(f"cat >/dev/null\n{body}\n", encoding="utf-8")
    env = dict(env, X4_GUARD_TIMEOUT_S="2")
    v = _check_in(env, tk, "--kind", "shell", "--shell", "bash", "--command", "echo hi",
                  script=hooks / "x4guard.py")
    assert v["decision"] == "deny" and v["inert"], v


@pytest.mark.skipif(not HAS_PWSH, reason="no PowerShell -- the untranslatable path is NOT checked here")
def test_guard_signals_not_checked_with_exit_2_only_under_X4_GUARD_CHECK(sandbox):
    """Structured 'could not evaluate' signal (ported from the Codex audit session's game-root
    edit): with X4_GUARD_CHECK=1 a not-checked state exits 2; without it the hook ASKS exactly
    as before, so Claude Code's behaviour does not change."""
    _, tk, env = sandbox
    env = dict(env, X4_PWSH=str(tk / "no-such-pwsh.exe"))
    payload = json.dumps({"tool_name": "PowerShell", "tool_input": {"command":
              f"Remove-Item -Force '{tk / 'reference' / 'libraries' / 'wares.xml'}'"}}).encode()
    bash = shutil.which("bash.exe") or shutil.which("bash")
    hook = str(X4GUARD.parent / "protect-bash.sh")
    plain = subprocess.run([bash, hook], input=payload, capture_output=True, env=env, timeout=120)
    check = subprocess.run([bash, hook], input=payload, capture_output=True, timeout=120,
                           env=dict(env, X4_GUARD_CHECK="1"))
    assert plain.returncode == 0 and b'"ask"' in plain.stdout.replace(b" ", b"")
    assert check.returncode == 2

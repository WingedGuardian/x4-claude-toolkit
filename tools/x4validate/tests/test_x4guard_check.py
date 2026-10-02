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
    assert rc == 0 and v["decision"] == "deny" and v["guards"] == ["protect-files.sh"]


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

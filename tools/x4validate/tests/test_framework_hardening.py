"""Exercise recovery and advisory failure paths against disposable trees."""
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[3] / ".claude" / "hooks"


@pytest.fixture
def hook_env(tmp_path):
    env = dict(os.environ, X4_TOOLKIT=str(tmp_path), X4_CONFIG=str(tmp_path / "absent.env"),
               X4_PYTHON=sys.executable, X4_REFERENCE=str(tmp_path / "reference"),
               X4_BACKUPS=str(tmp_path / "backups"))
    env.pop("X4_GUARD_CHECK", None)
    return env


def run_hook(name, target, env):
    bash = shutil.which("bash.exe") or shutil.which("bash")
    return subprocess.run([bash, str(HOOKS / name)],
                          input=json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(target)}}),
                          capture_output=True, text=True, env=env, timeout=30)


def test_same_second_and_concurrent_backups_preserve_every_snapshot(tmp_path, hook_env):
    target = tmp_path / "record.xml"
    env = dict(hook_env)
    env["BASH_FUNC_date%%"] = "() { printf '%s\\n' '20000101_000000'; }"
    target.write_text("original", encoding="utf-8")
    first = run_hook("backup-before-edit.sh", target, env)
    target.write_text("intermediate", encoding="utf-8")
    second = run_hook("backup-before-edit.sh", target, env)
    assert first.returncode == second.returncode == 0 and not first.stdout and not second.stdout
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        calls = list(pool.map(lambda _: run_hook("backup-before-edit.sh", target, env), range(8)))
    assert all(r.returncode == 0 and not r.stdout for r in calls)
    snapshots = [p for p in (tmp_path / "backups").iterdir() if p.name != "AUDIT_LOG.txt"]
    assert len(snapshots) == 10
    assert {p.name.split("__", 1)[0] for p in snapshots} == {"20000101_000000"}
    assert sorted(p.read_text(encoding="utf-8") for p in snapshots) == ["intermediate"] * 9 + ["original"]
    log = (tmp_path / "backups" / "AUDIT_LOG.txt").read_text(encoding="utf-8")
    assert log.count("(backup:") == 10
    assert all(p.name in log for p in snapshots)


@pytest.mark.parametrize("reader", ["jq", "python"])
@pytest.mark.parametrize("mode", ["missing", "crash", "invalid", "wrong_shape", "invalid_finding"])
def test_validator_failures_are_disclosed_without_blocking(tmp_path, hook_env, mode, reader):
    mod = tmp_path / "mod"
    (mod / "libraries").mkdir(parents=True)
    (mod / "content.xml").write_text('<content id="decoy"/>', encoding="utf-8")
    target = mod / "libraries" / "wares.xml"
    target.write_text('<diff><remove sel="/wares/missing"/></diff>', encoding="utf-8")
    uv = tmp_path / "fake-uv"
    body = {"crash": "exit 42", "invalid": "printf 'not-json'", "wrong_shape": "printf '{}'",
            "invalid_finding": "printf '%s' '{\"error_count\":1,\"findings\":[{}]}'"}
    if mode != "missing":
        uv.write_text("#!/bin/sh\n" + body[mode] + "\n", encoding="utf-8")
        uv.chmod(0o755)
    env = dict(hook_env, UV=str(uv), X4V=str(tmp_path))
    if reader == "python":
        env["JQ"] = str(tmp_path / "missing-jq")
    r = run_hook("x4validate-on-edit.sh", target, env)
    assert r.returncode == 0
    message = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "VALIDATION NOT COMPLETED" in message


@pytest.mark.parametrize("reader", ["jq", "python"])
@pytest.mark.parametrize("degraded", [True, False])
def test_degraded_results_keep_findings_and_disclose_incompleteness(tmp_path, hook_env, reader, degraded):
    mod = tmp_path / "mod"
    mod.mkdir()
    (mod / "content.xml").write_text('<content id="decoy"/>', encoding="utf-8")
    target = mod / "patch.xml"
    target.write_text("<diff/>", encoding="utf-8")
    uv = tmp_path / "fake-uv"
    data = json.dumps({"error_count": 1, "degraded": degraded,
                      "skipped": [{"what": "selector check", "why": "decoy input unavailable", "degraded": degraded}], "findings":
                      [{"severity": "error", "message": "CONTROL", "vpath": "patch.xml", "line": 1}]})
    uv.write_text("#!/bin/sh\nprintf '%s' '" + data + "'\nexit 1\n", encoding="utf-8")
    uv.chmod(0o755)
    env = dict(hook_env, UV=str(uv), X4V=str(tmp_path))
    if reader == "python":
        env["JQ"] = str(tmp_path / "missing-jq")
    r = run_hook("x4validate-on-edit.sh", target, env)
    assert r.returncode == 0
    message = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert ("VALIDATION NOT COMPLETED" if degraded else "VALIDATION PARTIAL") in message
    assert "CONTROL" in message and "decoy input unavailable" in message


def test_validator_clean_output_stays_quiet_and_findings_still_show(tmp_path, hook_env):
    mod = tmp_path / "mod"
    mod.mkdir()
    (mod / "content.xml").write_text('<content id="decoy"/>', encoding="utf-8")
    target = mod / "patch.xml"
    target.write_text("<diff/>", encoding="utf-8")
    uv = tmp_path / "fake-uv"
    env = dict(hook_env, UV=str(uv), X4V=str(tmp_path))
    for errors in (0, 1):
        data = json.dumps({"error_count": errors, "findings": [] if not errors else
                          [{"severity": "error", "message": "CONTROL", "vpath": "patch.xml", "line": 1}]})
        uv.write_text("#!/bin/sh\nprintf '%s' '" + data + "'\nexit " + str(errors) + "\n", encoding="utf-8")
        uv.chmod(0o755)
        r = run_hook("x4validate-on-edit.sh", target, env)
        assert r.returncode == 0
        if errors:
            assert "CONTROL" in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        else:
            assert r.stdout == ""


def test_setup_refuses_stale_lock_without_rewriting_it(tmp_path):
    uv = shutil.which("uv")
    assert uv, "this setup integration check requires uv"
    pkg = tmp_path / "tools" / "x4validate"
    pkg.mkdir(parents=True)
    project = pkg / "pyproject.toml"
    project.write_text('[project]\nname = "guard-lock-decoy"\nversion = "1.0.0"\nrequires-python = ">=3.10"\ndependencies = []\n', encoding="utf-8")
    env = dict(os.environ, UV_PYTHON=sys.executable, UV_PYTHON_DOWNLOADS="never",
               CLAUDE_PROJECT_DIR=str(tmp_path))
    r = subprocess.run([uv, "lock", "--offline"], cwd=pkg, env=env, capture_output=True, timeout=30)
    assert r.returncode == 0, r.stderr
    locked = (pkg / "uv.lock").read_bytes()
    project.write_text(project.read_text().replace('"1.0.0"', '"2.0.0"'), encoding="utf-8")
    bash = shutil.which("bash.exe") or shutil.which("bash")
    r = subprocess.run([bash, str(HOOKS.parents[1] / "setup.sh")], cwd=tmp_path,
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0, r.stdout + r.stderr
    assert (pkg / "uv.lock").read_bytes() == locked


@pytest.mark.parametrize("shell", ["bash", "powershell"])
def test_package_manager_tripwire_stops_both_shell_routes(tmp_path, shell):
    from conftest import package_manager_tripwire
    env = dict(os.environ, **package_manager_tripwire(tmp_path / "blockers"))
    if shell == "bash":
        cmd = [shutil.which("bash.exe") or shutil.which("bash"), "-c", "winget --version"]
    else:
        exe = shutil.which("pwsh") or shutil.which("powershell")
        if not exe:
            pytest.skip("no PowerShell -- native package-manager lookup NOT tested")
        cmd = [exe, "-NoProfile", "-Command", "winget --version; exit $LASTEXITCODE"]
    r = subprocess.run(cmd, capture_output=True, env=env, timeout=30)
    assert r.returncode == 97
    assert Path(env["X4_PACKAGE_MANAGER_LOG"]).read_text().strip() == "winget"

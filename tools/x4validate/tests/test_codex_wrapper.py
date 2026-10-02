"""The fail-closed Codex entry wrappers: EVERY failure path prints a JSON deny and exits 0.

MEASURED on Codex 0.160.0: a hook that crashes, exits non-zero or prints anything Codex cannot
parse is "Failed" and the tool call RUNS. So the wrapper -- not the adapter -- is what makes a
broken adapter a refusal. Each fault double below replaces the adapter in a copy of the
rendered .codex/hooks; the control proves a real allow still passes through as an allow.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from codex_testlib import HOOKS

PWSH = shutil.which("pwsh") or shutil.which("powershell")
BASH = os.environ.get("X4_BASH") or shutil.which("bash")
FAULTS = {
    "crash": "import sys; sys.exit(3)",
    "garbage": "print('hello')",
    "empty": "pass",
    "twolines": "print('X4OK '); print('X4OK ')",
    "extrakey": "print('X4OK {\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"r\"},\"inert\":true}')",
    "allow_decision": "print('X4OK {\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"allow\"}}')",
    "ask_decision": "print('X4OK {\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"ask\",\"permissionDecisionReason\":\"r\"}}')",
    "inner_extra": "print('X4OK {\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"r\",\"inert\":true}}')",
    "badjson": "print('X4OK {not json')",
    "hang": "import time; time.sleep(600)",
    "raise_after_partial": "import sys; sys.stdout.write('X4O'); raise SystemExit(0)",
}


def wrappers():
    out = []
    if PWSH:
        out.append(("ps1", [PWSH, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]))
    if BASH and "system32" not in BASH.lower():
        out.append(("sh", [BASH]))
    return out


WRAPPERS = wrappers() or [pytest.param("none", None, marks=pytest.mark.skip(reason="no PowerShell and no bash"))]


@pytest.fixture
def tree(tmp_path):
    t = tmp_path / ".codex" / "hooks"
    shutil.copytree(HOOKS, t)
    return t


def _run(launcher, script, event, payload: bytes, env=None):
    return subprocess.run(launcher + [str(script), event], input=payload, capture_output=True,
                          env=env or dict(os.environ), timeout=90)


@pytest.mark.parametrize("kind,launcher", WRAPPERS)
@pytest.mark.parametrize("fault", sorted(FAULTS) + ["missing_adapter", "missing_python"])
def test_every_fault_yields_json_deny(tree, kind, launcher, fault):
    env = dict(os.environ, X4_WRAPPER_TIMEOUT_S="5")
    if fault == "missing_adapter":
        (tree / "codex_adapter.py").unlink()
    elif fault == "missing_python":
        env["X4_PYTHON"] = str(tree / "no-such-python.exe")
        env["X4_NO_PYTHON_FALLBACK"] = "1"
    else:
        (tree / "codex_adapter.py").write_text(FAULTS[fault], encoding="utf-8")
    script = tree / ("codex-entry.ps1" if kind == "ps1" else "codex-entry.sh")
    r = _run(launcher, script, "pre_tool_use", b'{"hook_event_name":"PreToolUse"}', env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert set(out) == {"hookSpecificOutput"}
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "X4 GUARD INERT" in out["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("kind,launcher", WRAPPERS)
@pytest.mark.parametrize("event,name", [("post_tool_use", "PostToolUse"), ("session_start", "SessionStart")])
def test_a_fault_on_a_non_blocking_event_is_an_advisory(tree, kind, launcher, event, name):
    (tree / "codex_adapter.py").write_text(FAULTS["crash"], encoding="utf-8")
    script = tree / ("codex-entry.ps1" if kind == "ps1" else "codex-entry.sh")
    r = _run(launcher, script, event, b"{}")
    out = json.loads(r.stdout)
    assert r.returncode == 0 and set(out["hookSpecificOutput"]) == {"hookEventName", "additionalContext"}
    assert out["hookSpecificOutput"]["hookEventName"] == name


@pytest.mark.parametrize("kind,launcher", WRAPPERS)
def test_control_allow_passes_through_empty(tree, kind, launcher):
    (tree / "codex_adapter.py").write_text("print('X4OK ')", encoding="utf-8")
    script = tree / ("codex-entry.ps1" if kind == "ps1" else "codex-entry.sh")
    r = _run(launcher, script, "pre_tool_use", b"{}")
    assert r.returncode == 0 and r.stdout.strip() == b""          # the control: a real allow is NOT a deny


@pytest.mark.parametrize("kind,launcher", WRAPPERS)
def test_control_a_real_deny_passes_through_verbatim(tree, kind, launcher):
    body = '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"BLOCKED: x"}}'
    (tree / "codex_adapter.py").write_text(f"print('X4OK ' + {body!r})", encoding="utf-8")
    script = tree / ("codex-entry.ps1" if kind == "ps1" else "codex-entry.sh")
    r = _run(launcher, script, "pre_tool_use", b"{}")
    assert r.returncode == 0 and json.loads(r.stdout) == json.loads(body)


@pytest.mark.parametrize("kind,launcher", WRAPPERS)
def test_payload_reaches_the_adapter_byte_for_byte(tree, kind, launcher, tmp_path):
    seen = tmp_path / "seen.bin"
    (tree / "codex_adapter.py").write_text(
        f"import sys; open({str(seen)!r}, 'wb').write(sys.stdin.buffer.read()); print('X4OK ')", encoding="utf-8")
    payload = '{"hook_event_name":"PreToolUse","tool_input":{"command":"echo é — x"}}'.encode("utf-8")
    script = tree / ("codex-entry.ps1" if kind == "ps1" else "codex-entry.sh")
    r = _run(launcher, script, "pre_tool_use", payload)
    assert r.returncode == 0 and seen.read_bytes() == payload

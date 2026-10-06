"""X4_GUARD may not be written into a Claude Code settings file's `env` (user decision 2026-10-05).

MEASURED on Claude Code 2.1.290: a project `.claude/settings.json` `env` block reaches every hook
process, so `"env": {"X4_GUARD": "off"}` written by an agent switches every guard to advisory at
the next launch. One channel per test, each with a twin (a settings edit that does NOT touch
X4_GUARD is allowed): the file tools (protect-files.sh), the shell (protect-bash.sh -- unit-tested
in test_hook_facts.py, E2E in scripts/test-hooks.sh), the Codex apply_patch adapter, `x4guard
check`, and the session-canary report. Driven through the RENDERED .codex/hooks tree.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from codex_testlib import HOOKS, make_sandbox, native, run_adapter

BASH = os.environ.get("X4_BASH") or shutil.which("bash")
if BASH and "system32" in BASH.lower():
    BASH = None
GW = r"C:\Program Files\Git\bin\bash.exe"
if not BASH and os.path.isfile(GW):
    BASH = GW
needs_bash = pytest.mark.skipif(not BASH, reason="no Git Bash -- the shell hooks are NOT checked here")

ON = {"env": {"X4_GUARD": "off"}, "permissions": {"allow": []}}
OFF = {"env": {"OTHER": "1"}, "permissions": {"allow": []}}


@pytest.fixture
def sandbox(tmp_path):
    tmp, tk, env = make_sandbox(tmp_path)
    (tk / ".claude").mkdir(exist_ok=True)
    s = tk / ".claude" / "settings.json"
    s.write_text(json.dumps(OFF, indent=2), encoding="utf-8")
    return tmp, tk, env, s


def _hook(env, hook, payload):
    r = subprocess.run([BASH, str(HOOKS / hook)], input=json.dumps(payload).encode(),
                       capture_output=True, env=env, timeout=120)
    out = r.stdout.decode("utf-8", "replace").strip()
    if not out:
        return "allow", ""
    h = json.loads(out)["hookSpecificOutput"]
    return h.get("permissionDecision") or "advise", h.get("permissionDecisionReason") or ""


# --- the file tools (Claude Code Write / Edit / MultiEdit) -----------------------------------
@needs_bash
def test_write_that_sets_X4_GUARD_is_denied_and_twin_allowed(sandbox):
    _tmp, _tk, env, s = sandbox
    d, why = _hook(env, "protect-files.sh", {"tool_name": "Write", "tool_input": {
        "file_path": str(s), "content": json.dumps(ON)}})
    assert d == "deny" and "X4_GUARD" in why and "at the next launch" in why
    for key in ("X4_GUARD_CHECK", "x4_guard"):                     # the other key; any case
        d2, _ = _hook(env, "protect-files.sh", {"tool_name": "Write", "tool_input": {
            "file_path": str(s), "content": json.dumps({"env": {key: "1"}})}})
        assert d2 == "deny", key
    d, _ = _hook(env, "protect-files.sh", {"tool_name": "Write", "tool_input": {
        "file_path": str(s), "content": json.dumps(OFF)}})
    assert d == "allow"


@needs_bash
def test_edit_is_judged_on_the_RESULTING_file(sandbox):
    _tmp, _tk, env, s = sandbox
    d, _ = _hook(env, "protect-files.sh", {"tool_name": "Edit", "tool_input": {
        "file_path": str(s), "old_string": '"OTHER": "1"', "new_string": '"X4_GUARD": "off"'}})
    assert d == "deny"
    # TWIN: an edit of another key in the same env block
    d, _ = _hook(env, "protect-files.sh", {"tool_name": "Edit", "tool_input": {
        "file_path": str(s), "old_string": '"OTHER": "1"', "new_string": '"OTHER": "2"'}})
    assert d == "allow"
    # MultiEdit: the key arrives in the SECOND edit
    d, _ = _hook(env, "protect-files.sh", {"tool_name": "MultiEdit", "tool_input": {
        "file_path": str(s), "edits": [{"old_string": '"OTHER": "1"', "new_string": '"A": "1"'},
                                       {"old_string": '"A": "1"', "new_string": '"X4_GUARD": "off"'}]}})
    assert d == "deny"


@needs_bash
def test_an_unreadable_result_that_could_spell_it_is_denied(sandbox):
    """Cannot tell -> DENY with an actionable reason (the user's no-prompt rule), never ask."""
    _tmp, _tk, env, s = sandbox
    d, why = _hook(env, "protect-files.sh", {"tool_name": "Write", "tool_input": {
        "file_path": str(s), "content": '{"env": {"X4_GUARD": "off"'}})
    assert d == "deny" and "cannot tell" in why
    d, _ = _hook(env, "protect-files.sh", {"tool_name": "Write", "tool_input": {
        "file_path": str(s), "content": '{"env": {"X4\\u005fGUARD": "off"}}'}})   # a JSON escape
    assert d == "deny"


@needs_bash
def test_TWIN_a_file_merely_named_settings_elsewhere_is_not_this_rule(sandbox):
    _tmp, tk, env, _s = sandbox
    d, _ = _hook(env, "protect-files.sh", {"tool_name": "Write", "tool_input": {
        "file_path": str(tk / "dev" / "mymod" / "settings.json"), "content": json.dumps(ON)}})
    assert d == "allow"


# --- the shell ---------------------------------------------------------------------------------
@needs_bash
def test_a_shell_write_is_denied_and_a_read_is_allowed(sandbox):
    _tmp, _tk, env, s = sandbox
    p = str(s).replace("\\", "/")
    d, why = _hook(env, "protect-bash.sh", {"tool_name": "Bash", "tool_input": {
        "command": f"jq '.env.X = 1' a.json > '{p}'"}})
    assert d == "deny" and "file-edit tool" in why
    d, _ = _hook(env, "protect-bash.sh", {"tool_name": "Bash", "tool_input": {"command": f"cat '{p}'"}})
    assert d == "allow"


# --- the Codex apply_patch adapter --------------------------------------------------------------
def test_codex_patch_adding_X4_GUARD_is_denied_and_twin_allowed(sandbox):
    _tmp, tk, env, _s = sandbox
    bad = ('*** Begin Patch\n*** Update File: .claude/settings.json\n@@\n-    "OTHER": "1"\n'
           '+    "X4_GUARD": "off"\n*** End Patch')
    d, why = run_adapter(env, native("apply_patch_update", tk, command=bad))
    assert d == "deny" and "X4_GUARD" in (why or "")
    ok = ('*** Begin Patch\n*** Update File: .claude/settings.json\n@@\n-    "OTHER": "1"\n'
          '+    "OTHER": "2"\n*** End Patch')
    assert run_adapter(env, native("apply_patch_update", tk, command=ok))[0] == "allow"


def test_codex_patch_on_a_file_that_ALREADY_sets_it_is_denied(sandbox):
    """A patch's result cannot be proven to remove an existing key: deny, actionable."""
    _tmp, tk, env, s = sandbox
    s.write_text(json.dumps(ON, indent=2), encoding="utf-8")
    ok = ('*** Begin Patch\n*** Update File: .claude/settings.json\n@@\n-    "allow": []\n'
          '+    "allow": ["Bash"]\n*** End Patch')
    assert run_adapter(env, native("apply_patch_update", tk, command=ok))[0] == "deny"


# --- x4guard check (any other agent) ------------------------------------------------------------
def _check(env, *args):
    r = subprocess.run([sys.executable, str(HOOKS / "x4guard.py"), "check", *args],
                       capture_output=True, text=True, env=env, timeout=120)
    return json.loads(r.stdout)["decision"]


def test_x4guard_check_needs_the_written_text_for_a_settings_file(sandbox):
    _tmp, _tk, env, s = sandbox
    assert _check(env, "--kind", "write", "--path", str(s)) == "deny"            # text not given
    assert _check(env, "--kind", "write", "--path", str(s), "--command", json.dumps(ON)) == "deny"
    assert _check(env, "--kind", "write", "--path", str(s), "--command", json.dumps(OFF)) == "allow"


# --- session-canary -----------------------------------------------------------------------------
@needs_bash
def test_the_canary_names_a_settings_file_that_sets_it(sandbox):
    tmp, tk, env, s = sandbox
    env = dict(env, CLAUDE_PROJECT_DIR=str(tk), HOME=str(tmp / "home"))
    run = lambda: subprocess.run([BASH, str(HOOKS / "session-canary.sh")], capture_output=True,
                                 env=env, timeout=120).stdout.decode("utf-8", "replace")
    assert "settings env block" not in run()                                   # twin: clean file
    s.write_text(json.dumps(ON), encoding="utf-8")
    out = run()
    assert "X4_GUARD is set in a Claude Code settings env block" in out
    assert "settings.json" in out and "off" not in out.split("File(s):", 1)[1]   # paths, no value

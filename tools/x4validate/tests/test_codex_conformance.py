"""Cross-agent conformance (spec 7.2): every guard case in scripts/test-hooks.sh, replayed through
the Claude hooks AND through the full Codex chain (codex-entry wrapper -> adapter -> guards) in
NATIVE Codex shape, must reach the SAME verdict.

Both verdicts are taken NOW, in the same kept sandbox and env, so the comparison is fair; the
expected verdict is never hard-coded -- it is whatever the Claude hook says (the guards are the
policy; this suite checks the Codex translation keeps it). Per item, never a total.

  Claude verdict: the hook script itself on the Claude-shaped payload (independent of x4guard).
  Codex verdict:  Bash -> captured bash_powershell fixture, X4_CODEX_SHELL=bash (POSIX stand-in,
                  M9); PowerShell -> same fixture, X4_CODEX_SHELL=powershell; Edit -> an
                  apply_patch Update File; Write -> an apply_patch Add File carrying the content.
                  Grep/Glob/NotebookEdit, and payloads Codex cannot produce (no path, no
                  command), are counted as no_native_analogue.
  Normalised:     an ask/deny whose reason says nothing was checked -> inert; a Codex deny
                  "NEEDS YOUR APPROVAL:" -> ask.

Slow (~200 cases through PowerShell + Python + bash): runs in parallel, 6 workers.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from codex_testlib import FIX, HOOKS, REPO, make_sandbox, native, parse_output

BUCKETS = ("replayed", "no_native_analogue")
CLAUDE_HOOKS = REPO / ".claude" / "hooks"
PWSH = shutil.which("pwsh") or shutil.which("powershell")
BASH = os.environ.get("X4_BASH") or shutil.which("bash")
NOT_CHECKED = re.compile(r"X4 GUARD INERT|NO rule (?:below )?was evaluated|NEVER checked against any rule"
                         r"|could not be translated|could not be analysed")
RANK = {"allow": 0, "advise": 1, "ask": 2, "deny": 3, "inert": 4}
EXTRAS = FIX.parent / "conformance_extra.yaml"
WORKERS = 6

pytestmark = pytest.mark.skipif(not (PWSH and BASH and shutil.which("jq")),
                                reason="needs PowerShell, Git Bash and jq -- conformance NOT checked here")


# ------------------------------------------------------------------ dump -------------- #

@pytest.fixture(scope="session")
def dumped(tmp_path_factory):
    base = tmp_path_factory.mktemp("conf")
    dump = base / "cases.jsonl"
    # FORWARD slashes: the harness interpolates sandbox paths unquoted into probe commands, and a
    # backslash base made 2 of its probes fail for that reason alone (MEASURED 2026-10-02).
    env = dict(os.environ, X4_DECIDE_DUMP=str(dump), X4_TEST_SANDBOX=(base / "sbx").as_posix())
    r = subprocess.run([BASH, str(REPO / "scripts" / "test-hooks.sh")], cwd=REPO, env=env,
                       capture_output=True, timeout=1500)
    assert r.returncode == 0, r.stdout[-3000:]
    rows = [json.loads(line) for line in dump.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) >= 100, f"only {len(rows)} cases dumped -- the harness or the dump hook changed"
    return rows


def classify(row) -> str:
    p = row["payload"]
    tool, ti = p.get("tool_name"), p.get("tool_input") if isinstance(p.get("tool_input"), dict) else None
    if ti is None:
        return "no_native_analogue"
    if tool in ("Bash", "PowerShell") and isinstance(ti.get("command"), str) and ti["command"]:
        return "replayed"
    if tool in ("Edit", "Write") and isinstance(ti.get("file_path"), str) and ti["file_path"]:
        return "replayed"
    return "no_native_analogue"


# ------------------------------------------------------------------ verdicts ---------- #

def _hook_decision(out: str) -> str:
    out = out.strip()
    if not out:
        return "allow"
    try:
        hso = json.loads(out)["hookSpecificOutput"]
    except (ValueError, KeyError, TypeError):
        return "unreadable"
    d = hso.get("permissionDecision")
    if d in ("deny", "ask"):
        return "inert" if NOT_CHECKED.search(hso.get("permissionDecisionReason") or "") else d
    return "advise" if hso.get("additionalContext") else "allow"


def claude_hook(hook: str, payload: dict, env: dict, cwd: str) -> str:
    data = json.dumps(payload).encode("utf-8")
    r = subprocess.run([BASH, str(CLAUDE_HOOKS / hook)], input=data, capture_output=True, env=env, cwd=cwd, timeout=120)
    d = _hook_decision(r.stdout.decode("utf-8", "replace"))
    if d in ("ask", "deny"):
        # Is this a "checked nothing" verdict? Ask the guard itself, through its own check
        # protocol (X4_GUARD_CHECK=1: such paths exit 2) -- the same signal x4guard uses, so
        # the normalisation is derived from the guards, not from a phrase list that can drift
        # (MEASURED: "could evaluate NO rule" matched no NOT_CHECKED phrase, 2 false diffs).
        c = subprocess.run([BASH, str(CLAUDE_HOOKS / hook)], input=data, capture_output=True, cwd=cwd,
                           env=dict(env, X4_GUARD_CHECK="1"), timeout=120)
        if c.returncode == 2:
            return "inert"
    return d


def codex_chain(payload: dict, env: dict, shell: str, event: str = "pre_tool_use") -> str:
    r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                        str(HOOKS / "codex-entry.ps1"), event], input=json.dumps(payload).encode("utf-8"),
                       capture_output=True, env=dict(env, X4_CODEX_SHELL=shell, X4_PYTHON=sys.executable),
                       timeout=180)
    assert r.returncode == 0, r.stderr
    return parse_output(r.stdout)[0]


def _env(row) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("X4_") or "KEY" in k}
    env.update(row["env"])
    return env


def _patch(op: str, path: str, content: str = "") -> str:
    if op == "add":
        body = "".join("+" + ln + "\n" for ln in (content.split("\n") if content else [""]))
        return f"*** Begin Patch\n*** Add File: {path}\n{body}*** End Patch"
    return f"*** Begin Patch\n*** Update File: {path}\n@@\n-x\n+y\n*** End Patch"


def native_for(row) -> tuple[dict, str]:
    p, cwd = row["payload"], row["cwd"]
    tool, ti = p["tool_name"], p["tool_input"]
    if tool in ("Bash", "PowerShell"):
        return native("bash_powershell", cwd, command=ti["command"]), ("powershell" if tool == "PowerShell" else "bash")
    if tool == "Edit":
        return native("apply_patch_update", cwd, command=_patch("update", ti["file_path"])), "bash"
    return native("apply_patch_add", cwd, command=_patch("add", ti["file_path"], str(ti.get("content") or ""))), "bash"


def judge_row(row):
    env = _env(row)
    cwd = row["cwd"] if os.path.isdir(row["cwd"]) else str(REPO)
    claude = claude_hook(row["hook"], row["payload"], env, cwd)
    payload, shell = native_for(row)
    payload["cwd"] = cwd
    return claude, codex_chain(payload, env, shell)


# ------------------------------------------------------------------ tests ------------- #

def test_buckets_sum(dumped):
    counts = {b: sum(1 for r in dumped if classify(r) == b) for b in BUCKETS}
    assert sum(counts.values()) == len(dumped), counts
    assert counts["replayed"] >= 80, counts
    print("conformance buckets:", counts)


def test_live_claude_verdicts_matched_the_harness(dumped):
    """The dump's `got` IS the Claude verdict at decide() time; the harness passed, so got == exp
    for every row. A row where they differ means the dump is not what the harness judged."""
    bad = [(r["label"], r["exp"], r["got"]) for r in dumped if r["exp"] != r["got"]]
    assert not bad, bad


def test_every_replayable_case_agrees(dumped):
    rows = [r for r in dumped if classify(r) == "replayed"]
    with ThreadPoolExecutor(WORKERS) as ex:
        results = list(ex.map(judge_row, rows))
    drift = [(r["label"], r["got"], c) for r, (c, _) in zip(rows, results)
             if c != r["got"] and not (c == "inert" and r["got"] in ("ask", "deny"))]   # inert = normalised ask/deny
    diffs = [(r["label"], r["payload"]["tool_name"], c, x) for r, (c, x) in zip(rows, results) if c != x]
    print(f"replayed {len(rows)}; replay drift vs the live harness verdict: {len(drift)}")
    for d in drift:
        print("  DRIFT", d)
    assert not diffs, "\n".join(map(str, diffs))     # PER ITEM, never a total


# ------------------------------------------------------------------ extras ------------ #

def _extra_cases():
    return YAML(typ="safe").load(EXTRAS.read_text(encoding="utf-8"))


@pytest.fixture
def sandbox(tmp_path):
    return make_sandbox(tmp_path)


def _fill(s: str, tmp: Path, tk: Path) -> str:
    return (s.replace("{TK}", str(tk)).replace("{TKP}", tk.as_posix()).replace("{TMP}", str(tmp))
             .replace("{TKMSYS}", "/" + tk.as_posix()[0].lower() + tk.as_posix()[2:]))


def extra_claude(case, tmp, tk, env) -> str:
    worst = "allow"
    for call in case["claude"]:
        if "path" in call:
            payload = {"tool_name": call.get("tool", "Write"),
                       "tool_input": {"file_path": _fill(call["path"], tmp, tk), "content": ""}}
            hook = "protect-files.sh"
        else:
            payload = {"tool_name": call.get("tool", "Bash"), "tool_input": {"command": _fill(call["command"], tmp, tk)}}
            hook = "protect-bash.sh"
        d = claude_hook(hook, payload, env, str(tk))
        worst = max(worst, d, key=RANK.get)
    return worst


def extra_codex(case, tmp, tk, env) -> str:
    cwd = _fill(case.get("cwd", "{TK}"), tmp, tk)
    payload = native(case["fixture"], cwd, command=_fill(case["command"], tmp, tk))
    return codex_chain(payload, env, case.get("shell", "bash"))


@pytest.mark.parametrize("case", _extra_cases(), ids=lambda c: c["id"])
def test_codex_specific_extras(case, sandbox):
    tmp, tk, env = sandbox
    for f in case.get("files", []):
        p = Path(_fill(f, tmp, tk))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n", encoding="utf-8")
    x = extra_codex(case, tmp, tk, env)
    c = extra_claude(case, tmp, tk, env)
    assert x == c, (case["id"], "codex", x, "claude", c)
    if "expect" in case:
        assert x == case["expect"], (case["id"], "expected", case["expect"], "both said", x)

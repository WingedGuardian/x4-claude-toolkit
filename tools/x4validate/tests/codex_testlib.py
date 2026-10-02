"""Shared helpers for the Codex adapter tests (lane B): the sandbox roots, the RENDERED
.codex/hooks tree, native Codex payloads built from captured fixtures, and the one parser of
an adapter's output that enforces the only JSON shapes Codex honours (C4)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
REPO = PKG.parents[1]
HOOKS = REPO / ".codex" / "hooks"
ADAPTER = HOOKS / "codex_adapter.py"
FIX = PKG / "tests" / "fixtures" / "codex" / "0.160.0"
HAS_PWSH = bool(shutil.which("pwsh") or shutil.which("powershell"))
ALLOWED_TOP = {"continue", "decision", "hookSpecificOutput", "reason", "stopReason", "suppressOutput", "systemMessage"}
ALLOWED_HSO = {"additionalContext", "hookEventName", "permissionDecision", "permissionDecisionReason", "updatedInput"}
SANDBOX_KEYS = ("X4_TOOLKIT", "X4_GAME", "X4_REFERENCE", "X4_PROFILE", "X4_MODS", "X4_EXTENSIONS",
                "X4_SAVES", "X4_DOCUMENTS", "X4_BACKUPS", "X4_CONFIG")


def make_sandbox(tmp_path: Path):
    tk, game = tmp_path / "toolkit", tmp_path / "X4 Foundations"
    for d in (tk / "dev" / "mymod", tk / "reference" / "libraries", game / "extensions",
              tmp_path / "profile" / "save", tmp_path / "mods", tmp_path / "docs", tmp_path / "backups"):
        d.mkdir(parents=True)
    (tk / "reference" / "libraries" / "wares.xml").write_text("ref\n", encoding="utf-8")
    env = dict(os.environ, X4_TOOLKIT=str(tk), X4_GAME=str(game), X4_REFERENCE=str(tk / "reference"),
               X4_PROFILE=str(tmp_path / "profile"), X4_MODS=str(tmp_path / "mods"),
               X4_EXTENSIONS=str(game / "extensions"), X4_SAVES=str(tmp_path / "profile" / "save"),
               X4_DOCUMENTS=str(tmp_path / "docs"), X4_BACKUPS=str(tmp_path / "backups"),
               X4_CONFIG="/nonexistent", X4_CODEX_TOOL_LOG=str(tmp_path / "unknown-tools.log"))
    env.pop("X4_BASH", None)
    env.pop("X4_CODEX_SHELL", None)
    return tmp_path, tk, env


def native(name: str, cwd, **tool_input) -> dict:
    """A captured fixture with <CWD> filled in and tool_input overridden -- never a hand-built envelope."""
    text = (FIX / f"{name}.json").read_text(encoding="utf-8")
    d = json.loads(text.replace("<CWD>", json.dumps(str(cwd))[1:-1]))
    d["cwd"] = str(cwd)
    if "tool_input" in d:
        d["tool_input"].update(tool_input)
    return d


def parse_output(stdout: bytes):
    """(decision, text) from what a Codex hook printed; asserts the C4 shape contract."""
    body = stdout.decode("utf-8").strip()
    if not body:
        return "allow", None
    out = json.loads(body)
    assert set(out) <= ALLOWED_TOP and set(out["hookSpecificOutput"]) <= ALLOWED_HSO, out   # extra key = fail-open
    hso = out["hookSpecificOutput"]
    if hso.get("permissionDecision") == "deny":
        r = hso["permissionDecisionReason"]
        if "X4 GUARD INERT" in r:
            return "inert", r
        return ("ask" if r.startswith("NEEDS YOUR APPROVAL:") else "deny"), r
    assert "permissionDecision" not in hso, "Codex fails open on 'ask' and 'allow'-with-reason; never emit them"
    return "advise", hso["additionalContext"]


def run_adapter(env, payload, event="pre_tool_use", shell="powershell", adapter=ADAPTER, raw: bytes | None = None):
    data = raw if raw is not None else json.dumps(payload).encode("utf-8")
    r = subprocess.run([sys.executable, str(adapter), event], input=data, capture_output=True,
                       env=dict(env, X4_CODEX_SHELL=shell), timeout=180)
    lines = r.stdout.decode("utf-8").splitlines()
    assert r.returncode == 0 and len(lines) == 1 and lines[0].startswith("X4OK"), (r.returncode, r.stdout, r.stderr)
    return parse_output(lines[0][len("X4OK"):].encode("utf-8"))

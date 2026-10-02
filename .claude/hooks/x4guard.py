#!/usr/bin/env python3
"""x4guard -- one front door to the toolkit's guards (Layer 0 of the agent-portability design).

    python x4guard.py check --kind shell --shell {bash,powershell} --command CMD
    python x4guard.py check --kind {write,delete} --path P

Prints ONE JSON verdict and exits 0:
    {"v":1,"decision":"allow|advise|ask|deny","reason":...,"context":...,"inert":bool,"guards":[...]}
Exit 2 only on a usage error. It runs the SAME guard scripts Claude Code runs, with the payload
shape they already read, and NO side effects: backup-before-edit.sh is never run by a check.

--shell names the shell that will EXECUTE the command, not the tool that sent it. Codex, for
one, labels PowerShell commands "Bash" (MEASURED 2026-09-30); judged as bash, a PowerShell
write into reference/ was allowed.

A guard that could not run is never an allow: missing script, no bash, the WSL bash stub, a
timeout, a non-zero exit or unreadable output all return decision "deny" with inert=true and
the cause named. An agent that can ask its user may present an inert deny as a question; it may
not present it as an allow. Stdlib only; Python >= 3.10.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMEOUT_S = 25


def resolve_bash() -> tuple[str | None, str | None]:
    """Git Bash, never the WSL stub. `bash` alone can resolve to C:\\Windows\\System32\\bash.exe,
    which cannot run a Windows-path script (gates/hook_false_positives.py records this)."""
    cand = os.environ.get("X4_BASH") or shutil.which("bash.exe") or shutil.which("bash")
    if not cand:
        return None, "no bash found (set X4_BASH to Git Bash)"
    if "system32" in cand.replace("/", "\\").lower():
        return None, f"refusing the WSL bash stub ({cand}): it cannot run a Windows-path guard; set X4_BASH to Git Bash"
    if not Path(cand).is_file():
        return None, f"X4_BASH points at nothing: {cand}"
    return cand, None


def guard_payload(kind: str, shell: str | None, command: str | None, path: str | None) -> dict:
    if kind == "shell":
        return {"tool_name": "PowerShell" if shell == "powershell" else "Bash",
                "tool_input": {"command": command}}
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": ""}}


def parse_hook_output(out: str) -> tuple[str, str | None, str | None]:
    out = out.strip()
    if not out:
        return "allow", None, None
    try:
        hso = json.loads(out)["hookSpecificOutput"]
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(f"guard output is not a hook verdict: {out[:120]!r}") from e
    if not isinstance(hso, dict):
        raise ValueError(f"guard output is not a hook verdict: {out[:120]!r}")
    decision = hso.get("permissionDecision")
    if decision in ("deny", "ask"):
        return decision, hso.get("permissionDecisionReason"), None
    if decision is None and "additionalContext" in hso:
        return "advise", None, hso["additionalContext"]
    raise ValueError(f"unrecognised hook verdict: {hso!r}")


def _inert(reason: str, guards: list[str]) -> dict:
    return {"v": 1, "decision": "deny", "inert": True, "guards": guards, "context": None,
            "reason": f"X4 GUARD INERT: {reason}. NOTHING was checked; this is a refusal, "
                      "not a verdict on the command."}


def verdict_for(kind: str, shell: str | None, command: str | None, path: str | None) -> dict:
    script = "protect-bash.sh" if kind == "shell" else "protect-files.sh"
    guards = [script]
    target = HERE / script
    if not target.is_file():
        return _inert(f"guard script missing: {script}", guards)
    bash, why = resolve_bash()
    if not bash:
        return _inert(why, guards)
    payload = json.dumps(guard_payload(kind, shell, command, path)).encode("utf-8")
    try:
        r = subprocess.run([bash, str(target)], input=payload, capture_output=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return _inert(f"{script} timed out after {TIMEOUT_S}s", guards)
    except OSError as e:
        return _inert(f"{script} could not start: {e}", guards)
    if r.returncode != 0:
        return _inert(f"{script} exited {r.returncode}", guards)
    try:
        decision, reason, context = parse_hook_output(r.stdout.decode("utf-8", "replace"))
    except ValueError as e:
        return _inert(str(e), guards)
    return {"v": 1, "decision": decision, "reason": reason, "context": context,
            "inert": False, "guards": guards}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="x4guard", description="Ask the toolkit's guards for a verdict.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="verdict on one shell command or one file path; no side effects")
    c.add_argument("--kind", required=True, choices=("shell", "write", "delete"))
    c.add_argument("--shell", choices=("bash", "powershell"),
                   help="the shell that will EXECUTE the command (not the tool that sent it)")
    c.add_argument("--command")
    c.add_argument("--path")
    a = ap.parse_args(argv)
    if a.kind == "shell" and (not a.shell or a.command is None):
        ap.error("--kind shell needs --shell and --command")
    if a.kind != "shell" and not a.path:
        ap.error(f"--kind {a.kind} needs --path")
    v = verdict_for(a.kind, a.shell, a.command, a.path)
    sys.stdout.write(json.dumps(v) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

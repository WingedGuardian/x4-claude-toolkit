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
timeout, a non-zero exit, unreadable output or an invalid X4_GUARD_TIMEOUT_S all return
decision "deny" with inert=true and the cause named.

X4_GUARD_TIMEOUT_S (default 25, a positive number of seconds) is the budget for the WHOLE
check: a delete's two guards share it. On a timeout the guard's whole process tree is killed,
and the worst-case wall clock is that budget plus KILL_WAIT_S + DRAIN_GRACE_S. An agent that can ask its user may present an inert deny as a question; it may
not present it as an allow. Stdlib only; Python >= 3.10.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _timeout_setting() -> tuple:
    """X4_GUARD_TIMEOUT_S: ONE budget for the whole check (both guards of a delete share it).
    A bad value is a configuration error: an inert deny naming it, never a traceback."""
    raw = os.environ.get("X4_GUARD_TIMEOUT_S")
    if raw is None or not raw.strip():
        return 25.0, None
    try:
        t = float(raw)
    except ValueError:
        t = math.nan
    if not math.isfinite(t) or t <= 0:
        return None, f"X4_GUARD_TIMEOUT_S={raw!r} is not a positive number of seconds"
    return t, None


TIMEOUT_S, TIMEOUT_ERROR = _timeout_setting()
RANK = {"allow": 0, "advise": 1, "ask": 2, "deny": 3}
#: How the guards say "I checked nothing" (or only part). They ASK in those states, which an
#: agent would put to its user as an ordinary confirmation; here it is an inert deny instead.
NOT_CHECKED = re.compile(r"X4 GUARD INERT|NO rule (?:below )?was evaluated|NEVER checked against any rule"
                         r"|could not be translated|could not be analysed")
#: After a timeout: how long taskkill may take, and how long to wait for the pipes to close once
#: the tree is dead. A check's wall clock is bounded by TIMEOUT_S + KILL_WAIT_S + DRAIN_GRACE_S
#: even if the kill fails, because the drain is never unbounded.
KILL_WAIT_S = 5
DRAIN_GRACE_S = 3
_TASKKILL = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "taskkill.exe")


def _clock() -> float:
    return time.monotonic()


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the guard AND its descendants. On Windows a killed bash.exe leaves its children
    running and holding the pipes (MEASURED 2026-10-02, 3 of 3 process shapes), so the tree is
    killed while the root is still known: taskkill /T walks parent PIDs from it. The PID cannot
    be reused meanwhile -- Popen holds a handle to the process. On POSIX the guard leads its own
    process group (start_new_session), so killpg reaches every descendant that did not leave it."""
    if os.name == "nt":
        try:
            subprocess.run([_TASKKILL, "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=KILL_WAIT_S)
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _run_bounded(argv: list, payload: bytes, env: dict, timeout: float):
    """(returncode, stdout, stderr), or (None, b"", b"") on timeout. Never `subprocess.run`:
    on Windows its timeout path ends in an UNBOUNDED communicate() that waits for every pipe
    holder, so a guard's grandchild stretched a 2 s budget to 10.9 s (MEASURED). Not
    `with Popen(...)` either: its __exit__ waits."""
    extra = {} if os.name == "nt" else {"start_new_session": True}
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, **extra)
    try:
        out, err = proc.communicate(payload, timeout=timeout)
        return proc.returncode, out, err
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            proc.communicate(timeout=DRAIN_GRACE_S)
        except subprocess.TimeoutExpired:
            pass        # abandon: the reader threads are daemons and die with this process
        return None, b"", b""


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
        # `cwd` at the TOP level, where Claude Code and Codex put it: a relative operand is judged
        # from the caller's directory, so `check` and the hooks agree (lane F). The Codex adapter
        # has already entered the payload's cwd, so this is the Codex session cwd too.
        return {"tool_name": "PowerShell" if shell == "powershell" else "Bash",
                "tool_input": {"command": command}, "cwd": os.getcwd()}
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


def _failure_detail(out: bytes, err: bytes) -> str | None:
    """The guard's own reason when it printed a hook verdict before failing (every X4_GUARD_CHECK
    exit 2 does: the verdict is printed BEFORE x4_guard_check_inert exits), else the last 300
    characters of its stderr. Without this the cause was only "exited N" (MEASURED 2026-10-02)."""
    try:
        _, reason, context = parse_hook_output(out.decode("utf-8", "replace"))
        if reason or context:
            return reason or context
    except ValueError:
        pass
    tail = err.decode("utf-8", "replace").strip()[-300:]
    return tail or None


def _deployed() -> bool:
    """A deployed copy (.claude/hooks for Claude Code, .codex/hooks for Codex) finds its roots
    through _x4-env.sh (HOOK_DIR/../..); any other copy needs X4_TOOLKIT."""
    return HERE.name == "hooks" and HERE.parent.name in (".claude", ".codex")


#: Which budget a timeout message names (lane J, Plan 3): x4guard's own, or the CALLER's (the
#: Codex adapter passes its own deadline, X4_CODEX_BUDGET_S, so X4_GUARD_TIMEOUT_S played no part).
CALLER_BUDGET = "the caller's deadline (the Codex adapter's X4_CODEX_BUDGET_S)"


def _own_budget() -> str:
    return f"this check's {TIMEOUT_S:g}s budget (X4_GUARD_TIMEOUT_S)"


def run_guard(script: str, payload: dict, deadline: float | None = None,
              budget: str | None = None) -> dict:
    """One guard, one verdict dict. Anything that keeps it from producing a real verdict is inert.
    `deadline` (a _clock() value) is the CHECK's deadline: a second guard gets only what is left.
    `budget` names whose deadline it is in a timeout message (default: x4guard's own)."""
    guards = [script]
    if TIMEOUT_ERROR:
        return _inert(TIMEOUT_ERROR, guards)
    target = HERE / script
    if not target.is_file():
        return _inert(f"guard script missing: {script}", guards)
    if not _deployed() and not os.environ.get("X4_TOOLKIT"):
        return _inert(f"this copy is not under .claude/hooks or .codex/hooks and X4_TOOLKIT is unset, so the guard "
                      f"cannot find the configured roots; run the deployed .claude/hooks/x4guard.py", guards)
    bash, why = resolve_bash()
    if not bash:
        return _inert(why, guards)
    if deadline is None:
        deadline = _clock() + TIMEOUT_S
    remaining = deadline - _clock()
    if remaining <= 0:
        return _inert(f"{script} was not run: {budget or _own_budget()} was already spent", guards)
    try:
        # X4_GUARD_CHECK=1: the guards' internal check protocol. Every "checked nothing" path exits
        # 2 instead of asking (a no-op for Claude Code's hooks, where the variable is unset).
        rc, out, err = _run_bounded([bash, str(target)], json.dumps(payload).encode("utf-8"),
                                    dict(os.environ, X4_GUARD_CHECK="1"), remaining)
    except OSError as e:
        return _inert(f"{script} could not start: {e}", guards)
    if rc is None:
        return _inert(f"{script} timed out: {budget or _own_budget()} ran out", guards)
    if rc != 0:
        why = _failure_detail(out, err)
        head = (f"{script} reported it could not evaluate this (exit 2, X4_GUARD_CHECK)" if rc == 2
                else f"{script} exited {rc}")
        return _inert(head + (f": {why}" if why else ""), guards)
    try:
        decision, reason, context = parse_hook_output(out.decode("utf-8", "replace"))
    except ValueError as e:
        return _inert(str(e), guards)
    if decision in ("ask", "deny") and reason and NOT_CHECKED.search(reason):
        return _inert(f"{script} could not check all or part of this: {reason}", guards)
    return {"v": 1, "decision": decision, "reason": reason, "context": context,
            "inert": False, "guards": guards}


#: Leads every non-inert verdict while X4_GUARD=off, so it can never read as a plain allow.
GUARDS_OFF_NOTE = ("X4 GUARDS OFF (X4_GUARD=off at launch): every guard verdict is an advisory this "
                   "session and nothing here was enforced.")


def verdict_for(kind: str, shell: str | None, command: str | None, path: str | None,
                deadline: float | None = None) -> dict:
    """The verdict, plus spec 5.7's escape hatch: with X4_GUARD exactly "off" the guards turn a
    deny/ask into an advisory naming what it would have been (they read the variable
    themselves), and this says GUARDS OFF on every verdict -- a would-be allow included. An inert
    verdict stays an inert deny: a guard that could not run judged nothing to relax."""
    v = _verdict(kind, shell, command, path, deadline)
    if os.environ.get("X4_GUARD") != "off" or v["inert"]:
        return v
    v = dict(v)
    if RANK[v["decision"]] < RANK["advise"]:
        v["decision"] = "advise"
    v["context"] = GUARDS_OFF_NOTE + ("\n\n" + v["context"] if v.get("context") else "")
    return v


def _verdict(kind: str, shell: str | None, command: str | None, path: str | None,
             deadline: float | None = None) -> dict:
    """A relative path is resolved from the CALLER's working directory (Codex apply_patch paths
    are relative). A delete is judged as the stricter of a write and an `rm -rf --` of that path:
    recursive, because the path may be a directory. No protect-bash rule distinguishes it from
    `rm -f` today (MEASURED 9/9 paths identical); the probe says what a delete IS, for any
    future rule keyed on recursion."""
    # A caller that judges MANY checks under one budget (the Codex adapter's apply_patch batch)
    # passes its own absolute deadline; otherwise each check gets TIMEOUT_S of its own.
    budget = None if deadline is None else CALLER_BUDGET
    if deadline is None:
        deadline = _clock() + TIMEOUT_S if TIMEOUT_S else None
    if kind == "shell":
        return run_guard("protect-bash.sh", guard_payload(kind, shell, command, None), deadline, budget)
    path = os.path.abspath(path)
    parts = [run_guard("protect-files.sh", guard_payload("write", None, None, path), deadline, budget)]
    if kind == "delete":
        quoted = path.replace("\\", "/").replace("'", "'\"'\"'")    # close, "'", reopen
        rm = "rm -rf -- '" + quoted + "'"
        parts.append(run_guard("protect-bash.sh", guard_payload("shell", "bash", rm, None), deadline, budget))
    worst = max(parts, key=lambda v: (v["inert"], RANK[v["decision"]]))
    worst = dict(worst)
    worst["guards"] = [g for v in parts for g in v["guards"]]
    # EVERY guard's advisory, in guard order, whoever wins: a delete that ASKs (protect-bash)
    # used to drop protect-files' manifest advisory entirely (MEASURED 2026-10-02).
    ctx = [v["context"] for v in parts if v.get("context")]
    worst["context"] = "\n\n".join(ctx) or None
    return worst


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

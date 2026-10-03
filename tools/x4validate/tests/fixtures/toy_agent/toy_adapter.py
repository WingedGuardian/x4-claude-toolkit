#!/usr/bin/env python3
"""Toy Agent before_tool adapter. Translates; decides nothing. Fail-closed: every path prints
a TOY-BLOCK line and exits 0 (Toy Agent fails open on non-zero exit, crash or >30 s)."""
import json
import os
import subprocess
import sys
import threading

MAX_CHARS = 10000            # X4_HOOK_MAX_CHARS default (measured by sourcing _x4-env.sh)
GUARD_BUDGET_S = 15          # x4guard worst case = 15 + KILL_WAIT 5 + DRAIN 3 = 23 s
DEADLINE_S = 26              # ours: above 23, below Toy Agent's 30 s hook timeout
HERE = os.path.dirname(os.path.abspath(__file__))


def emit(line):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def flat(text):
    # ASCII only: Toy Agent decodes our stdout as UTF-8 but prints it with the console codepage
    # (cp1252 here); a non-ASCII byte in a reason crashed the harness itself (MEASURED).
    t = " ".join(str(text).split())
    return t.encode("ascii", "replace").decode("ascii")[:MAX_CHARS]


def deny(reason):
    emit("TOY-BLOCK " + flat(reason))


def watchdog():
    deny("X4 GUARD INERT: toy adapter missed its own %ds deadline" % DEADLINE_S)
    os._exit(0)


def guard_path():
    p = os.environ.get("X4_GUARD_PY")
    if p and os.path.isfile(p):
        return p
    p = os.path.join(HERE, "x4guard.py")
    return p if os.path.isfile(p) else None


def ask_guard(args, cwd):
    gp = guard_path()
    if not gp:
        return {"decision": "deny", "inert": True,
                "reason": "X4 GUARD INERT: x4guard.py not found (set X4_GUARD_PY)"}
    env = dict(os.environ)
    env["X4_GUARD_TIMEOUT_S"] = str(GUARD_BUDGET_S)
    try:
        r = subprocess.run([sys.executable, gp, "check"] + args, cwd=cwd, env=env,
                           capture_output=True, timeout=DEADLINE_S - 2)
        out = r.stdout.decode("utf-8", "replace").strip()
        if r.returncode != 0:
            raise ValueError("x4guard exit %s" % r.returncode)
        v = json.loads(out)
        if not isinstance(v, dict) or v.get("v") != 1 or v.get("decision") not in (
                "allow", "advise", "ask", "deny"):
            raise ValueError("unexpected x4guard answer")
        return v
    except Exception as e:  # anything unexpected is an inert deny
        return {"decision": "deny", "inert": True,
                "reason": "X4 GUARD INERT: guard check failed (%s)" % type(e).__name__}


RANK = {"allow": 0, "advise": 1, "ask": 2, "deny": 3}


def main():
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    tool = payload.get("tool")
    args = payload.get("args") or {}
    cwd = payload.get("workdir") or os.getcwd()
    if tool == "run_shell":
        sh = args.get("interpreter")
        if sh not in ("bash", "powershell"):
            return deny("X4 GUARD INERT: unknown interpreter %r" % (sh,))
        checks = [["--kind", "shell", "--shell", sh, "--command", args["cmdline"]]]
    elif tool in ("write_file", "edit_file"):
        checks = [["--kind", "write", "--path", args["target"]]]
    else:
        return deny("X4 GUARD INERT: unknown tool %r" % (tool,))
    worst = None
    for c in checks:
        v = ask_guard(c, cwd)
        if worst is None or RANK[v["decision"]] > RANK[worst["decision"]]:
            worst = v
    d = worst["decision"]
    if d == "allow":
        return
    if d == "advise":
        return emit("TOY-NOTE " + flat(worst.get("context") or worst.get("reason") or "advisory"))
    reason = worst.get("reason") or "blocked by X4 guard"
    if d == "ask":
        reason = "NEEDS YOUR APPROVAL: " + reason
    deny(reason)


if __name__ == "__main__":
    t = threading.Timer(DEADLINE_S, watchdog)
    t.daemon = True
    t.start()
    try:
        main()
    except BaseException as e:
        deny("X4 GUARD INERT: toy adapter error (%s)" % type(e).__name__)
    t.cancel()
    sys.exit(0)

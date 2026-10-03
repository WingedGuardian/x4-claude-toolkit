#!/usr/bin/env python3
"""Toy Agent: a minimal, deliberately FAIL-OPEN agent harness (see TOY-AGENT.md).

    python toy_agent.py --root DIR --script CALLS.jsonl --hook "<command line>"

For each call in CALLS.jsonl it runs the before_tool hook with the call on stdin, then obeys
the hook's first stdout line: `TOY-BLOCK <reason>` blocks, anything else runs. A hook that
exits non-zero, crashes or takes longer than HOOK_TIMEOUT_S does NOT block -- like Codex
(MEASURED 2026-09-30), which is exactly what an adapter author must discover and design for.
write_file really writes, inside --root only; run_shell and edit_file only log. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK_TIMEOUT_S = 30


def run_hook(hook: str, call: dict) -> tuple:
    """(first stdout line, failure or None). The hook runs in THIS process's cwd, not workdir."""
    payload = {"event": "before_tool", "tool": call["tool"], "args": call.get("args", {}),
               "workdir": call.get("workdir") or os.getcwd()}
    try:
        r = subprocess.run(hook, shell=True, input=json.dumps(payload).encode("utf-8"),
                           capture_output=True, timeout=HOOK_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return "", f"hook timed out after {HOOK_TIMEOUT_S}s"
    except OSError as e:
        return "", f"hook could not start: {e}"
    lines = [ln for ln in r.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
    first = lines[0].strip() if lines else ""
    if r.returncode != 0:
        return first, f"hook exited {r.returncode}"
    return first, None


def execute(call: dict, root: Path) -> str:
    args = call.get("args", {})
    workdir = Path(call.get("workdir") or os.getcwd())
    if call["tool"] == "write_file":
        target = Path(args["target"])
        target = target if target.is_absolute() else workdir / target
        target = Path(os.path.abspath(target))
        if root != target and root not in target.parents:
            return f"refused: {target} is outside --root"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(args.get("text", ""), encoding="utf-8")
        return f"wrote {target}"
    if call["tool"] == "edit_file":
        return f"would edit {args.get('target')}"
    if call["tool"] == "run_shell":
        return f"would run ({args.get('interpreter')}) {args.get('cmdline')}"
    return f"unknown tool {call['tool']}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="toy_agent")
    ap.add_argument("--root", required=True)
    ap.add_argument("--script", required=True)
    ap.add_argument("--hook", required=True)
    a = ap.parse_args(argv)
    root = Path(os.path.abspath(a.root))
    for ln in Path(a.script).read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        call = json.loads(ln)
        first, failure = run_hook(a.hook, call)
        print(f"[toy] {call['tool']}: hook said: {first or '(nothing)'}")
        if failure is None and first.startswith("TOY-BLOCK "):
            print(f"[toy] {call['tool']}: BLOCKED -- {first[len('TOY-BLOCK '):]}")
            continue
        if failure:
            print(f"[toy] {call['tool']}: {failure} -- running the call anyway (fails open)")
        elif first.startswith("TOY-NOTE "):
            print(f"[toy] {call['tool']}: note for the model: {first[len('TOY-NOTE '):]}")
        print(f"[toy] {call['tool']}: {execute(call, root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

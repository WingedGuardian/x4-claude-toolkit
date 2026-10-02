#!/usr/bin/env python3
"""Capture REAL Codex hook payloads and sanitise them into test fixtures (spec section 7.2).

    python capture-codex-fixtures.py hook --out RAW_DIR
        A Codex hook: reads one payload on stdin and writes it, untouched, to RAW_DIR. Point a
        SCRATCH project's .codex/hooks.json at it, never a real one (it prints nothing, so it
        never blocks anything). Run `codex exec --dangerously-bypass-hook-trust -s workspace-write
        -C <scratch> "<prompt>" </dev/null` to drive it (exec blocks on an open stdin otherwise).

    python capture-codex-fixtures.py sanitise --raw RAW_FILE --name NAME --out FIX_DIR
        Writes FIX_DIR/NAME.json with cwd -> <CWD>, transcript_path -> <TRANSCRIPT>, the
        session/turn/tool-use/agent ids -> <SESSION_ID>..., and an opaque spawn_agent message ->
        <OPAQUE-ENCRYPTED-BLOB>. Every other byte of tool_input is kept, and a reverse
        substitution must reproduce the raw tool_input exactly or the fixture is refused.

The raw files carry personal paths and stay OUT of the repo. How the 0.160.0 set was captured
(probes P1-P12, predictions, results): docs/superpowers/measurements/2026-10-02-codex-0160.md.
The hook never logs the environment: hooks inherit the full parent environment, secrets included
(MEASURED on 0.160.0). Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

IDS = ("session_id", "turn_id", "tool_use_id", "agent_id")


def cmd_hook(out: Path) -> int:
    raw = sys.stdin.buffer.read()
    try:
        d = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        d = {}
    tool = "".join(c for c in str(d.get("tool_name", "")) if c.isalnum())
    name = f"{time.strftime('%H%M%S')}-{d.get('hook_event_name', 'X')}-{tool}-{uuid.uuid4().hex[:6]}.json"
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_bytes(raw)
    return 0


def sanitise(d: dict) -> dict:
    cwd = d["cwd"]
    s = json.dumps(d, ensure_ascii=False)
    for form in sorted({cwd, cwd.replace("\\", "/")}, key=len, reverse=True):
        s = s.replace(json.dumps(form)[1:-1], "<CWD>")
    e = json.loads(s)
    e["transcript_path"] = "<TRANSCRIPT>"
    for k in IDS:
        if k in e:
            e[k] = "<" + k.upper() + ">"
    opaque = str(d.get("tool_name", "")).endswith("spawn_agent")
    if opaque and isinstance(e.get("tool_input"), dict) and "message" in e["tool_input"]:
        e["tool_input"]["message"] = "<OPAQUE-ENCRYPTED-BLOB>"
    return e


def reverse_ok(raw: dict, fixture: dict) -> bool:
    if str(raw.get("tool_name", "")).endswith("spawn_agent"):
        return True                     # the message is blanked by design
    back = json.dumps(fixture.get("tool_input"), ensure_ascii=False).replace(
        "<CWD>", json.dumps(raw["cwd"])[1:-1])
    return back == json.dumps(raw.get("tool_input"), ensure_ascii=False)


def cmd_sanitise(raw_file: Path, name: str, out: Path) -> int:
    raw = json.loads(raw_file.read_text(encoding="utf-8"))
    fix = sanitise(raw)
    if not reverse_ok(raw, fix):
        print(f"REFUSING {name}: sanitising changed tool_input beyond the cwd prefix", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(fix, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    (out / f"{name}.json").write_bytes(data)
    print(f"wrote {name}.json")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hook")
    h.add_argument("--out", required=True, type=Path)
    s = sub.add_parser("sanitise")
    s.add_argument("--raw", required=True, type=Path)
    s.add_argument("--name", required=True)
    s.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "hook":
        return cmd_hook(a.out)
    return cmd_sanitise(a.raw, a.name, a.out)


if __name__ == "__main__":
    sys.exit(main())

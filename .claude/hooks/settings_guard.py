#!/usr/bin/env python3
"""May an agent write this Claude Code settings file? -- the X4_GUARD-in-settings rule.

USER DECISION (2026-10-05, relayed by the orchestrator): "Block X4_GUARD there". MEASURED on
Claude Code 2.1.290: a project `.claude/settings.json` `env` block reaches every hook process
(a SessionStart and a UserPromptSubmit hook both saw the value). So an agent that writes
`"env": {"X4_GUARD": "off"}` into a settings file switches every guard to advisory at the next
launch -- the switch the launch environment alone is meant to hold (R1-F1).

The rule: an agent write to `.claude/settings*.json` whose RESULTING content names X4_GUARD or
X4_GUARD_CHECK -- in an `env` block or ANYWHERE else, e.g. a `hooks` command prefix
`X4_GUARD=off bash ...` (FX-G4 / H4a) -- is DENIED; every other settings edit is allowed. When the
result cannot be known, it is denied with a reason the agent can act on -- never an ask (the
user's no-prompt rule).

One implementation, three callers:
  protect-files.sh  stdin = the Write/Edit/MultiEdit payload  -> a reason on stdout, or nothing
  x4guard / adapters a write whose text is an apply_patch or an OpenCode write/edit (`x4_written`)
  session-canary.sh --scan FILE...  -> one line per settings file that sets it now
Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import sys

#: `.claude/settings.json`, `.claude/settings.local.json`, and any other settings*.json there --
#: project or user level, any dialect (backslashes and case folded by the caller's norm).
SETTINGS = re.compile(r"(^|/)\.claude/settings[^/]*\.json$")
KEYS = ("X4_GUARD", "X4_GUARD_CHECK")
#: Either key named anywhere in a string (X4_GUARD_CHECK contains X4_GUARD).
_MENTION = re.compile(r"X4_GUARD(?:_CHECK)?", re.IGNORECASE)
#: The text could spell a key without containing it literally: a JSON \u escape.
_ESCAPE = re.compile(r"\\u[0-9a-fA-F]{4}")

REASON = ("BLOCKED: this write would put {key} into {path}, a Claude Code settings file whose "
          "`env` block and hook commands reach every hook -- it could switch the X4 guards off at "
          "the next launch. Agents may not do that (user decision, 2026-10-05). The user can set "
          "X4_GUARD=off themselves, in the environment they launch from. Make the settings edit "
          "without that key.")
UNKNOWN = ("BLOCKED: the guard cannot tell what this write leaves in {path}, a Claude Code "
           "settings file -- and its `env` block reaches every hook, so X4_GUARD there would "
           "switch the X4 guards off. {why} Write it with your file-edit tool (Write / Edit / "
           "apply_patch), whose content the guard checks; X4_GUARD itself is the user's to set, "
           "at launch.")


def norm(p: str) -> str:
    return (p or "").replace(chr(92), "/").lower()


def is_settings(path: str) -> bool:
    return bool(SETTINGS.search(norm(path)))


def guard_keys(text: str):
    """(keys set in an `env` block, decidable?) for settings-file TEXT. Unparseable JSON is
    decidable only when the text cannot spell a key at all."""
    try:
        doc = json.loads(text) if text.strip() else {}
    except ValueError:
        if any(k in text.upper() for k in KEYS) or _ESCAPE.search(text):
            return [], False
        return [], True
    found = []
    stack = [doc]
    while stack:                                   # an `env` at ANY depth counts
        o = stack.pop()
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "env" and isinstance(v, dict):
                    found += [x for x in v if str(x).upper() in KEYS]
                elif _MENTION.search(str(k)):
                    found.append(_MENTION.search(str(k)).group(0))
                if k == "permissions" and o is doc:
                    continue    # rule STRINGS (`Bash(export X4_GUARD=off)`) set nothing (USER, 2026-10-06)
                stack.append(v)
        elif isinstance(o, list):
            stack.extend(o)
        elif isinstance(o, str) and _MENTION.search(o):
            # FX-G4 / reviewer H4a, MEASURED: `X4_GUARD=off bash .../protect-bash.sh` as a
            # `hooks` COMMAND string switches that hook off and was allowed -- only an `env`
            # block was read. The key ANYWHERE in the file is refused (USER DECISION: "block
            # X4_GUARD there"); a settings file has no legitimate use for it.
            found.append(_MENTION.search(o).group(0))
    return found, True


def _read(path: str):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return f.read()
    except FileNotFoundError:
        return ""
    except OSError:
        return None


def _apply(text: str, edits: list):
    """The Edit/MultiEdit result, or None when an old_string does not apply (the tool fails)."""
    for e in edits:
        old, new = e.get("old_string"), e.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            return None
        if old == "":
            text = new + text
        elif old not in text:
            return None
        else:
            text = text.replace(old, new) if e.get("replace_all") else text.replace(old, new, 1)
    return text


def judge(tool_input: dict) -> str:
    """'' to allow, else the refusal."""
    path = tool_input.get("file_path") or tool_input.get("filePath") or ""
    if not is_settings(path):
        return ""
    if "x4_written" in tool_input:                 # a patch / opaque write: its TEXT is all we see
        written = tool_input.get("x4_written")
        if not isinstance(written, str):
            return UNKNOWN.format(path=path, why="The caller passed no written text (x4guard check: "
                                  "--command <the text>).")
        cur = _read(path)
        if cur is None:
            return UNKNOWN.format(path=path, why="The file cannot be read.")
        cur_keys, ok = guard_keys(cur)
        if not ok or cur_keys:
            return UNKNOWN.format(path=path, why="The file already sets (or may set) the key, and a "
                                  "patch's result cannot be proven to remove it.")
        if any(k in written.upper() for k in KEYS) or _ESCAPE.search(written):
            return REASON.format(key="X4_GUARD", path=path)
        return ""
    if "content" in tool_input:
        result = tool_input.get("content")
        if not isinstance(result, str):
            return UNKNOWN.format(path=path, why="The content is not text.")
    else:
        edits = tool_input.get("edits")
        if not isinstance(edits, list):
            edits = [tool_input]
        cur = _read(path)
        if cur is None:
            return UNKNOWN.format(path=path, why="The file cannot be read.")
        result = _apply(cur, edits)
        if result is None:
            # The edit does not apply to the file as READ here -- but the tool may see a
            # different file (it changed in between, another spelling of the path). FX-G4 /
            # reviewer H-M1: the text being written is then judged on its own.
            for e in edits:
                new = e.get("new_string") if isinstance(e, dict) else None
                if isinstance(new, str) and (_MENTION.search(new) or _ESCAPE.search(new)):
                    return REASON.format(key="X4_GUARD", path=path)
            return ""
    keys, ok = guard_keys(result)
    if not ok:
        return UNKNOWN.format(path=path, why="The result is not valid JSON and mentions the key.")
    if keys:
        return REASON.format(key=keys[0], path=path)
    return ""


def main(argv: list) -> int:
    if argv[1:2] == ["--scan"]:
        for p in argv[2:]:
            text = _read(p)
            if not text:
                continue
            keys, ok = guard_keys(text)
            if keys or not ok:
                print(p)
        return 0
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        return 3
    ti = payload.get("tool_input") if isinstance(payload, dict) else None
    ti = dict(ti) if isinstance(ti, dict) else {}
    if argv[1:2] == ["--path"] and len(argv) > 2:  # the caller's CANONICAL path (Windows aliases)
        ti["file_path"] = argv[2]
    out = judge(ti)
    if out:
        sys.stdout.buffer.write(out.encode("utf-8", "replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

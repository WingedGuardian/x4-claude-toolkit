r"""Parse X4's `debug.txt` engine log into structured errors, for correlation.

x4validate's static checks (XSD, exprlint heuristic) are *necessary but not
sufficient* — the authoritative verdict on what actually breaks at load/runtime is
the game engine's own `[=ERROR=]` output. This module parses that log so
`_check.check_debug_correlation` can fold the engine's errors for *this* mod into
the same report and GATE on them (a real engine error = exit 1).

Four real shapes occur (all verified against a live 9.0 log):
  A. load parse error   `[=ERROR=] <t> extensions\<folder>\<rel>(<line>): <msg>`
  B. load lookup error  `... Originated from: extensions\<folder>\<rel>.(xml|xml.gz)`  (no line)
  C. runtime MD cue     `[=ERROR=] <t> Error in MD cue md.<Script>.<Cue><inst:..>: <msg>`
                        followed by  `* Action: <tag>, line <N>`
  D. runtime AI script  `[=ERROR=] <t> Error in AI script <name> on entity <id>: <msg>`
                        followed by  `* Action: <tag>, line <N>`
A/B identify a FILE (path); C/D identify a SCRIPT by NAME (resolved to a file by
the caller, via each mdscript/aiscript's `name=` attribute). The `'null' is not a
list` runtime error is shape C — hence why the file-path-only parse would miss it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_RE_PARSE = re.compile(r"extensions[\\/](?P<path>[^()\r\n]+?)\((?P<line>\d+)\):\s*(?P<msg>.*)")
_RE_ORIG = re.compile(r"(?P<msg>.*?)\s*Originated from:\s*extensions[\\/](?P<path>[^\r\n]+?)\.\(xml")
_RE_MDCUE = re.compile(r"Error in MD cue\s+md\.(?P<script>[^.]+)\.(?P<cue>[^<:]+?)(?:<[^>]*>)?:\s*(?P<msg>.*)")
_RE_AISCR = re.compile(r"Error in AI script\s+(?P<script>\S+)\s+on entity\s+[^:]+:\s*(?P<msg>.*)")
_RE_ACTION_LINE = re.compile(r"\bline\s+(?P<line>\d+)")


@dataclass
class DebugError:
    ident_kind: str   # "path" (A/B) | "script" (C/D)
    folder: str       # A/B: the extensions\<folder> token; else ""
    vpath: str        # A/B: mod-relative posix path; else ""
    script_name: str  # C/D: the mdscript/aiscript name; else ""
    line: int         # 0 if unknown
    message: str
    severity: str     # "error" | "warn"


def _sev(msg: str) -> str:
    low = msg.lower()
    if "warning" in low or "not recommended" in low or "inefficient" in low:
        return "warn"
    return "error"


def _split_path(p: str) -> tuple[str, str]:
    parts = [x for x in re.split(r"[\\/]", p.strip()) if x]
    if not parts:
        return "", ""
    return parts[0], "/".join(parts[1:])


def _lookahead_line(lines: list[str], i: int) -> int:
    """Runtime errors put their source line on a `* Action: ..., line N`
    continuation line following the `[=ERROR=]` header. Scan the `*`-prefixed
    continuation block for it."""
    for j in range(i + 1, min(i + 8, len(lines))):
        s = lines[j].strip()
        if not s.startswith("*"):
            break
        m = _RE_ACTION_LINE.search(s)
        if m:
            return int(m.group("line"))
    return 0


def parse_debug(path: str | Path) -> list[DebugError]:
    out: list[DebugError] = []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for i, raw in enumerate(lines):
        if "[=ERROR=]" not in raw:
            continue
        content = raw.split("[=ERROR=]", 1)[1]
        content = re.sub(r"^\s*[\d.]+\s+", "", content).strip()  # drop game-time stamp

        m = _RE_PARSE.search(content)  # A
        if m:
            folder, vpath = _split_path(m.group("path"))
            out.append(DebugError("path", folder, vpath, "", int(m.group("line")),
                                  m.group("msg").strip(), _sev(m.group("msg"))))
            continue
        m = _RE_ORIG.search(content)  # B
        if m:
            folder, vpath = _split_path(m.group("path"))
            out.append(DebugError("path", folder, vpath, "", 0,
                                  m.group("msg").strip(), _sev(m.group("msg"))))
            continue
        m = _RE_MDCUE.search(content)  # C
        if m:
            out.append(DebugError("script", "", "", m.group("script").strip(),
                                  _lookahead_line(lines, i), m.group("msg").strip(),
                                  _sev(m.group("msg"))))
            continue
        m = _RE_AISCR.search(content)  # D
        if m:
            out.append(DebugError("script", "", "", m.group("script").strip(),
                                  _lookahead_line(lines, i), m.group("msg").strip(),
                                  _sev(m.group("msg"))))
            continue
    return out

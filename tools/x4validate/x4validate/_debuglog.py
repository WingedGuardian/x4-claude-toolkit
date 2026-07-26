r"""Parse X4's `debug.txt` engine log into structured errors, for correlation.

x4validate's static checks (XSD, exprlint heuristic) are *necessary but not
sufficient* — the authoritative verdict on what actually breaks at load/runtime is
the game engine's own `[=ERROR=]` output. This module parses that log so
`_check.check_debug_correlation` can fold the engine's errors for *this* mod into
the same report and GATE on them (a real engine error = exit 1).

Six real shapes occur (all verified against a live 9.0 log):
  A. load parse error   `[=ERROR=] <t> extensions\<folder>\<rel>(<line>): <msg>`
  B. load lookup error  `... Originated from: extensions\<folder>\<rel>.(xml|xml.gz)`  (no line)
  C. runtime MD cue     `[=ERROR=] <t> Error in MD cue md.<Script>.<Cue><inst:..>: <msg>`
                        followed by  `* Action: <tag>, line <N>`
  D. runtime AI script  `[=ERROR=] <t> Error in AI script <name> on entity <id>: <msg>`
                        followed by  `* Action: <tag>, line <N>`
  E. diff op, 0 matches `<t> No matching node for path '<sel>' in patch file '<f>'. Skipping node.`
  F. diff op, >1 match  `<t> Multiple matching nodes for path '<sel>' in patch file '<f>'. ...`
A/B/E/F identify a FILE (path); C/D identify a SCRIPT by NAME (resolved to a file by
the caller, via each mdscript/aiscript's `name=` attribute). The `'null' is not a
list` runtime error is shape C — hence why the file-path-only parse would miss it.

E/F are the **diff-op cardinality failures** — the exact class x4validate exists to
catch (RFC 5261: a `sel` must match exactly one node; the engine skips the op and
continues, so the patch SILENTLY does nothing). They were unparsed until 2026-07-26,
which made `--debug` blind to 453 of 2463 error lines in a real log. Three quirks,
each measured over that log — get any of them wrong and the shape silently drops:
  1. The engine prints the patch file **without its extension** (441 of 453):
     `'extensions\stars\libraries\material_library'`, not `...material_library.xml`.
     Use `xml_candidates()` to resolve against a real VFS.
  2. The `<sel>` itself contains single quotes (`@id='ore'`) in 413 of 453 lines, so
     the sel group MUST be greedy `.*` anchored on the literal `' in patch file '`.
     A `[^']*` group truncates 91% of real selectors.
  3. Unlike A–D these carry a `sel` and a cardinality, not just a location — which is
     what lets us compare the engine's verdict to ours op-for-op rather than by file.
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
# E/F. `sel` is greedy by necessity — see quirk 2 in the module docstring.
# The `extensions[\\/]` prefix is consumed here so `path` is <folder>\<rel>, matching
# what _RE_PARSE/_RE_ORIG hand to _split_path. (Forgetting it yields folder="extensions".)
_RE_DIFFOP = re.compile(
    r"(?P<kind>No matching node|Multiple matching nodes) for path "
    r"'(?P<sel>.*)' in patch file '(?:\.[\\/])?extensions[\\/](?P<path>[^']*)'")


@dataclass
class DebugError:
    ident_kind: str   # "path" (A/B/E/F) | "script" (C/D)
    folder: str       # A/B/E/F: the extensions\<folder> token; else ""
    vpath: str        # A/B/E/F: mod-relative posix path; else ""
    script_name: str  # C/D: the mdscript/aiscript name; else ""
    line: int         # 0 if unknown
    message: str
    severity: str     # "error" | "warn"
    # E/F only — the engine's own per-op verdict, for op-for-op comparison.
    sel: str = ""            # the XPath the op used
    cardinality: str = ""    # "" (not a diff op) | "none" (0 matches) | "multiple" (>1)


def xml_candidates(vpath: str) -> tuple[str, ...]:
    """Resolve shape E/F's extension-less patch path against a real file list.

    The engine drops the extension for these lines (quirk 1), so `libraries/factions`
    must be matched against `libraries/factions.xml`. Returns the forms to try, most
    literal first — the caller picks whichever exists in the mod's VFS.
    """
    if not vpath:
        return ()
    tail = vpath.rsplit("/", 1)[-1]
    if "." in tail:  # already carries an extension (12 of 453 in the reference log)
        return (vpath,)
    return (vpath, vpath + ".xml")


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

        m = _RE_DIFFOP.search(content)  # E/F — checked first: they carry the richest data
        if m:
            folder, vpath = _split_path(m.group("path"))
            out.append(DebugError("path", folder, vpath, "", 0, content, "error",
                                  sel=m.group("sel"),
                                  cardinality=("none" if m.group("kind").startswith("No")
                                               else "multiple")))
            continue
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

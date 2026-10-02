#!/usr/bin/env python3
"""The ONE shared apply_patch path parser (spec section 5.2): every adapter that has to judge a
patch asks this module which files it touches, and nothing else re-implements the grammar.

    parse_patch(text) -> [(op, path), ...]   op in add / update / delete / move_from / move_to
    shell_patch(cmd)  -> (patch_text, cd_dir) | None   an apply_patch run THROUGH the shell

Any grammar it does not know raises PatchParseError -- an unrecognised `*** ` header, a missing
Begin or End, an empty path, a Move without an Update, text after End, or a patch that touches
nothing. A caller must turn that into a refusal: a partial path list would be an allow for the
paths it missed. Paths are returned verbatim (surrounding whitespace stripped); resolving a
relative path is the caller's job, against the payload's cwd.

The grammar is Codex's apply_patch format, confirmed on 0.160.0 captures (Add, Update, Delete,
Update + Move to, multi-file). Inside a hunk every content line starts with `+`, `-`, ` ` or
`@@`, so a `+*** Delete File: x` line is CONTENT, never a header. Stdlib only; Python >= 3.10.
"""
from __future__ import annotations

import re

OPS = ("add", "update", "delete", "move_from", "move_to")
BEGIN, END = "*** Begin Patch", "*** End Patch"
_FILE_HEADERS = (("*** Add File:", "add"), ("*** Update File:", "update"), ("*** Delete File:", "delete"))
_MOVE = "*** Move to:"
_EOF = "*** End of File"

#: apply_patch at a command position, optionally after `cd <dir> &&` (or `;`). Codex intercepts
#: the shell form (MEASURED P3: `apply_patch <<'PATCH' ... PATCH` arrived as Bash and was applied).
_SHELL_FORM = re.compile(
    r"""^\s*(?:cd\s+(?P<dir>"[^"]*"|'[^']*'|[^\s;&|]+)\s*(?:&&|;)\s*)?(?:apply_patch|applypatch)(?=\s|$|<)""")
#: The same word at ANY command position (after ; && || | or a newline). Used to refuse a shell
#: patch this module cannot attribute to a directory, rather than to ignore it.
_ANY_POSITION = re.compile(r"(?:^|[;&|\n]|\$\()\s*(?:apply_patch|applypatch)(?=\s|$|<)")


class PatchParseError(ValueError):
    pass


def parse_patch(text: str) -> list[tuple[str, str]]:
    if not isinstance(text, str):
        raise PatchParseError("patch text is not a string")
    lines = text.replace("\r\n", "\n").split("\n")
    while lines and lines[-1].strip() == "":
        lines.pop()                                  # a trailing newline is not "text after End"
    while lines and lines[0].strip() == "":
        lines.pop(0)
    if not lines or lines[0].strip() != BEGIN:
        raise PatchParseError(f"patch does not start with '{BEGIN}'")
    if lines[-1].strip() != END:
        raise PatchParseError(f"patch does not end with '{END}'")
    ops: list[tuple[str, str]] = []
    last_header = None
    for i, line in enumerate(lines[1:-1], start=2):
        if not line.startswith("*** "):
            if last_header is None:
                raise PatchParseError(f"line {i}: content before any file header")
            continue                                 # hunk or added content, never a header
        head = line.rstrip()
        if head in (BEGIN, END):
            raise PatchParseError(f"line {i}: a second '{head}' inside the patch")
        if head == _EOF:
            last_header = last_header or "eof"
            continue
        if head.startswith(_MOVE):
            if last_header != "update" or not ops or ops[-1][0] != "update":
                raise PatchParseError(f"line {i}: '{_MOVE}' is valid only directly after an Update header")
            path = head[len(_MOVE):].strip()
            if not path:
                raise PatchParseError(f"line {i}: empty path")
            ops[-1] = ("move_from", ops[-1][1])
            ops.append(("move_to", path))
            last_header = "move"
            continue
        for prefix, op in _FILE_HEADERS:
            if head.startswith(prefix):
                path = head[len(prefix):].strip()
                if not path:
                    raise PatchParseError(f"line {i}: empty path")
                ops.append((op, path))
                last_header = op
                break
        else:
            raise PatchParseError(f"line {i}: unrecognised patch header {head[:80]!r}")
    if not ops:
        raise PatchParseError("the patch touches no file")
    return ops


def shell_patch(cmd: str) -> tuple[str, str | None] | None:
    """(patch text, cd dir or None) when the shell command runs apply_patch; None when it does not.
    When apply_patch is run but no Begin..End block can be found, the text returned is '' so the
    caller's parse_patch refuses: a shell patch that cannot be read is never an allow."""
    if not isinstance(cmd, str):
        return None
    m = _SHELL_FORM.match(cmd)
    cd = None
    if m:
        cd = m.group("dir")
        if cd and cd[0] in "'\"":
            cd = cd[1:-1]
    elif not _ANY_POSITION.search(cmd):
        return None
    start, end = cmd.find(BEGIN), cmd.rfind(END)
    if start < 0 or end < start:
        return "", cd
    if not m:
        return "", None                      # apply_patch somewhere we cannot attribute: refuse
    return cmd[start:end + len(END)], cd


def shell_patch_body(cmd: str) -> str | None:
    found = shell_patch(cmd)
    return None if found is None else found[0]

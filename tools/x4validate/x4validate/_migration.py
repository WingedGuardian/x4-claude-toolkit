"""Grep heuristic for 9.0 breakages that are RUNTIME-only (not in the XSD schemas).

Rule source = KNOWLEDGEBASE.md "Version Migration Map" Tier-2. These are dead
APIs / deprecated Lua that schema validation can't catch — only a debug.txt run
or a pattern match surfaces them. Grows as we learn more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# (compiled pattern, human note) — keep in sync with KB "Version Migration Map" Tier-2.
PATTERNS = [
    (re.compile(r"Lua_Loader\.Load"),
     "SirNukes Lua_Loader is DEAD on 9.0 — load UI Lua natively via ui.xml + call ModLua.init() yourself"),
    (re.compile(r"raise_lua_event\s+name=\s*['\"]?Lua_Loader"),
     "Lua_Loader event no longer fires on 9.0 — use the native ui.xml load path"),
    (re.compile(r"\.keys\.list\.clone"),
     "deprecated on 9.0 — use .keys.list (the .clone is gone)"),
    (re.compile(r"kuertee_hud(?![\w])"),
     "UIX 9.0 deleted the standalone kuertee_hud module; kHUD is now a GLOBAL in menu_toplevel.xpl"),
]

_EXTS = {".xml", ".lua"}


@dataclass
class MigrationFinding:
    file: str
    line: int
    note: str
    snippet: str


def scan_mod(mod_dir: Path) -> list[MigrationFinding]:
    out: list[MigrationFinding] = []
    for f in sorted(mod_dir.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in _EXTS:
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            for pat, note in PATTERNS:
                if pat.search(line):
                    out.append(MigrationFinding(str(f), i, note, line.strip()[:120]))
    return out

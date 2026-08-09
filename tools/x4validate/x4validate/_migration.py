"""Grep heuristic for 9.0 breakages that are RUNTIME-only (not in the XSD schemas).

Rule source = KNOWLEDGEBASE.md "Version Migration Map" Tier-2. These are dead
APIs / deprecated Lua that schema validation can't catch — only a debug.txt run
or a pattern match surfaces them. Grows as we learn more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import _scan

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
    packed: bool = False


def scan_mod(mod_dir: Path, unreadable: list[str] | None = None) -> list[MigrationFinding]:
    """Every 9.0 runtime-breakage pattern in a mod's XML and Lua, packed or loose.

    Goes through `_scan` rather than walking the loose tree itself. It used to do
    the latter, which made `--update` blind to any PACKED mod — it read only what
    `rglob` could see and then reported a clean port. That is a false clean on the
    majority of installed mods, and it is silent.
    """
    out: list[MigrationFinding] = []
    skipped: list[_scan.Unreadable] = []
    for vpath, text, packed in _scan.iter_mod_text(mod_dir, tuple(sorted(_EXTS)), skipped):
        for i, line in enumerate(text.splitlines(), 1):
            for pat, note in PATTERNS:
                if pat.search(line):
                    out.append(MigrationFinding(vpath, i, note, line.strip()[:120], packed))
    if unreadable is not None:
        unreadable.extend(str(u) for u in skipped)
    return out

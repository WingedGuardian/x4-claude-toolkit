"""Stamp the game-side mod's BUILD fingerprint from its own content.

WHY THIS EXISTS. A deployed file is not a loaded file. X4 keeps running whatever lua it
read at load time, and the live channel answers happily from that old code -- so a reply
proves the channel works, never that it is the code you just wrote. That cost two cycles
in one session: once believing a `/reloadui` had happened, and once with a staleness
check that fingerprinted on a single new field which had been added in the PREVIOUS
build, so its pass branch did not mean what it claimed.

A CONTENT HASH cannot fail that way. It moves whenever the file moves, including for
changes nobody enumerated in advance.

The hash is taken with the BUILD line itself MASKED, so stamping is a fixed point --
otherwise writing the value would change the value.

Used two ways:
  * `--check` (the test path): recompute and compare, non-zero if the stamp is stale.
  * bare (the dev path): rewrite the stamp in place.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys

_LINE = re.compile(r'^local BUILD = "([0-9a-f]{8})"$', re.M)


#: The extension ships at `mods/` in the public toolkit and at `dev/` in the private
#: workspace, so BOTH are searched, in that order.
#:
#: MEASURED 2026-09-01: this looked only at `parents[3]/"dev"`, which does not exist in
#: the public repo -- so `mod_lua()` returned None there, `--check` printed "nothing to
#: stamp" and exited 0, and the staleness gate passed by never running. The mod's BUILD
#: line sat at e1af07d7 while its content hashed to 539c405e. A deployed-but-not-loaded
#: mod is the exact failure this file was written to catch, and it was blind to it in
#: the only tree that ships.
#:
#: `tests/test_modlua_rearm.py::_find_mod_lua` is the same lookup; the two are pinned
#: equal by a test, because this defect IS that divergence.
_ROOTS_ORDER = ("mods", "dev")


def roots() -> list[pathlib.Path]:
    base = pathlib.Path(__file__).resolve().parents[3]
    return [base / n for n in _ROOTS_ORDER if (base / n).is_dir()]


def mod_lua_files() -> list[pathlib.Path]:
    """EVERY shipped game-side lua carrying a BUILD line.

    `mod_lua()` below returns only the primary file and is kept for its callers. It
    globbed `*live_query.lua` alone, so `engine_probe.lua` -- same extension, runs
    automatically at load, writes profile UI userdata -- was never stamped and never
    checked. A change to it shipped undetected.
    """
    out: list[pathlib.Path] = []
    for d in roots():
        found = sorted(d.glob("*/ui/*.lua"))
        if found:
            return [p for p in found if _LINE.search(p.read_text(encoding="utf-8"))]
    return out


def mod_lua() -> pathlib.Path | None:
    #: Located by GLOB, never by a spelled-out folder name -- this file ships, and the
    #: mod's folder carries a personal prefix the mirror's scanner would catch.
    for d in roots():
        found = sorted(d.glob("*/ui/*live_query.lua"))
        if found:
            return found[0]
    return None


def expected(text: str) -> str:
    """The fingerprint of *text* with the BUILD line masked out."""
    masked = _LINE.sub('local BUILD = "<STAMP>"', text)
    return hashlib.sha256(masked.encode("utf-8")).hexdigest()[:8]


def current(text: str) -> str | None:
    m = _LINE.search(text)
    return m.group(1) if m else None


def main(argv: list[str]) -> int:
    # ANNOUNCED, never silently skipped: a shipped lua with no BUILD line is outside
    # this gate entirely, and a stamper that reports success over a file it never
    # looked at is the defect this whole script exists to prevent.
    for d in roots():
        shipped = sorted(d.glob("*/ui/*.lua"))
        if shipped:
            bare = [q.name for q in shipped
                    if not _LINE.search(q.read_text(encoding="utf-8"))]
            if bare:
                print("NOT COVERED (no `local BUILD` line, so no staleness check): "
                      + ", ".join(bare))
            break

    p = mod_lua()
    if p is None:
        # "I could not look" is not "there is nothing to stamp". When a root EXISTS but
        # holds no mod the layout is broken, and returning 0 there is a green printed
        # over a check that never ran -- which is how the stale BUILD survived.
        found = roots()
        if found:
            print("searched %s and found no game-side mod lua -- a root exists but holds "
                  "no mod, which is a broken layout, not an absent one"
                  % ", ".join(str(d) for d in found))
            return 2
        print("no mods/ or dev/ root in this tree; nothing to stamp")
        return 0
    # Excluded by IDENTITY, not by position. `files[1:]` assumed the primary was
    # first; sorted() puts engine_probe.lua before live_query.lua, so the primary was
    # stamped twice and the OTHER file -- the whole point of this loop -- never at all.
    files = mod_lua_files() or [p]
    rc = 0
    for q in [f for f in files if f.resolve() != p.resolve()]:
        # Every covered file, not just the first. Reported per FILE, because "the stamp
        # is current" over a set is only true if it is true of each of them.
        t = q.read_text(encoding="utf-8")
        c, e = current(t), expected(t)
        if c == e:
            print(f"{q.name}: BUILD {c} is current")
            continue
        if "--check" in argv:
            print(f"{q.name}: BUILD is STALE -- stamped {c}, content says {e}")
            rc = 1
            continue
        q.write_bytes(_LINE.sub(f'local BUILD = "{e}"', t, count=1).encode("utf-8"))
        back = current(q.read_text(encoding="utf-8"))
        print(f"{q.name}: BUILD {c} -> {e}   (re-read confirms {back})")
        if back != e:
            print(f"{q.name}: RE-READ MISMATCH"); rc = 2

    text = p.read_text(encoding="utf-8")
    cur, exp = current(text), expected(text)
    if cur is None:
        print(f"{p.name}: no `local BUILD = \"...\"` line to stamp")
        return 2
    if "--check" in argv:
        if cur == exp:
            print(f"{p.name}: BUILD {cur} is current")
            return rc
        print(f"{p.name}: BUILD is STALE -- stamped {cur}, content says {exp}")
        print("run: uv run python scripts/stamp-mod-build.py")
        return 1
    if cur == exp:
        print(f"{p.name}: BUILD {cur} already current")
        return rc
    # Encode first, then write_bytes: a failed encode must not be able to truncate the
    # file it is halfway through replacing.
    data = _LINE.sub(f'local BUILD = "{exp}"', text, count=1).encode("utf-8")
    assert len(data) > 0, "refusing to write an empty file"
    p.write_bytes(data)
    back = current(p.read_text(encoding="utf-8"))
    print(f"{p.name}: BUILD {cur} -> {exp}   (re-read confirms {back})")
    return 0 if back == exp else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

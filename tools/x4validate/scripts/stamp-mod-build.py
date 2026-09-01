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

DEV = pathlib.Path(__file__).resolve().parents[3] / "dev"
_LINE = re.compile(r'^local BUILD = "([0-9a-f]{8})"$', re.M)


def mod_lua() -> pathlib.Path | None:
    #: Located by GLOB, never by a spelled-out folder name -- this file ships, and the
    #: mod's folder carries a personal prefix the mirror's scanner would catch.
    found = sorted(DEV.glob("*/ui/*live_query.lua")) if DEV.is_dir() else []
    return found[0] if found else None


def expected(text: str) -> str:
    """The fingerprint of *text* with the BUILD line masked out."""
    masked = _LINE.sub('local BUILD = "<STAMP>"', text)
    return hashlib.sha256(masked.encode("utf-8")).hexdigest()[:8]


def current(text: str) -> str | None:
    m = _LINE.search(text)
    return m.group(1) if m else None


def main(argv: list[str]) -> int:
    p = mod_lua()
    if p is None:
        print("no game-side mod lua found under dev/; nothing to stamp")
        return 0
    text = p.read_text(encoding="utf-8")
    cur, exp = current(text), expected(text)
    if cur is None:
        print(f"{p.name}: no `local BUILD = \"...\"` line to stamp")
        return 2
    if "--check" in argv:
        if cur == exp:
            print(f"{p.name}: BUILD {cur} is current")
            return 0
        print(f"{p.name}: BUILD is STALE -- stamped {cur}, content says {exp}")
        print("run: uv run python scripts/stamp-mod-build.py")
        return 1
    if cur == exp:
        print(f"{p.name}: BUILD {cur} already current")
        return 0
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

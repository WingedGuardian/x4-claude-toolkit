#!/usr/bin/env python
"""Determinism audit — the same question must get the same answer twice.

Nothing else in the gate set checks this, and it undermines everything that does:
if a tool's output varies between identical runs (dict/set iteration order, a
timestamp, a filesystem enumeration order, a random sample), then every recorded
baseline is noise, every "no change since last run" is luck, and a real
regression hides inside the jitter.

Two properties:
  * REPEATABLE — run the same command twice, compare byte-for-byte.
  * IDEMPOTENT — rebuilding a derived artifact from unchanged inputs produces the
    same content (checked by hashing the store's logical contents, not the file,
    since sqlite may legitimately differ in free-page layout).

Run:  uv run python gates/determinism_audit.py [--with-build]
Exit: 0 deterministic, 1 any variance.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402

WITH_BUILD = "--with-build" in sys.argv

#: Lines that are ALLOWED to differ between runs — wall-clock and elapsed times.
_VOLATILE = re.compile(r"\b\d+\.\d+s\b|\bcompleted in \d+s|\b\d{4}-\d\d-\d\d[ T]\d\d:\d\d")


def run(argv: list[str], timeout: int = 1800) -> str:
    p = subprocess.run(["uv", "run", "--project", str(ROOT), *argv], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    return (p.stdout or "") + (p.stderr or "")


def normalize(s: str) -> str:
    return _VOLATILE.sub("<t>", s)


CASES = [
    ("x4compat check --all", ["x4compat", "check", "--all"]),
    ("x4similar sweep", ["x4similar", "--threshold", "0.9"]),
    ("x4xref who-calls", ["x4xref", "who-calls", "find_station"]),
    ("x4xref who-listens", ["x4xref", "who-listens", "event_player_ejected"]),
    ("x4effective ls macro", ["x4effective", "ls", "macro", "--limit", "300"]),
    ("x4effective diff-mod", ["x4effective", "diff-mod", "base"]),
    ("x4effective dump", ["x4effective", "dump", "libraries/wares.xml"]),
    ("x4stats macro", ["x4stats", "macro", str(
        _env.reference() / "assets/props/SurfaceElements/macros"
        / "shield_arg_l_standard_01_mk1_macro.xml")]),
]


def store_fingerprint() -> str:
    """Hash the store's LOGICAL contents — order-independent, layout-independent."""
    import sqlite3
    con = sqlite3.connect(f"file:{_env.effective_db()}?mode=ro", uri=True)
    h = hashlib.sha256()
    for tbl, cols in (("entities", "kind,name,klass,vpath,origin"),
                      ("attrs", "prop,value,origin")):
        for row in con.execute(f"SELECT {cols} FROM {tbl} ORDER BY {cols}"):
            h.update(("\x1f".join("" if v is None else str(v) for v in row) + "\x1e").encode())
    con.close()
    return h.hexdigest()


def main() -> int:
    bad = []
    print("DETERMINISM AUDIT — identical inputs must give identical output")
    print("=" * 84)
    for label, argv in CASES:
        a, b = normalize(run(argv)), normalize(run(argv))
        if a == b:
            print(f"  ok    {label:<34} stable ({len(a)}B)")
            continue
        bad.append(label)
        # locate the first differing line so the report is actionable
        la, lb = a.splitlines(), b.splitlines()
        first = next((i for i, (x, y) in enumerate(zip(la, lb)) if x != y), min(len(la), len(lb)))
        print(f"  VARY  {label:<34} differs at line {first + 1}")
        print(f"        run1: {la[first][:110] if first < len(la) else '<eof>'}")
        print(f"        run2: {lb[first][:110] if first < len(lb) else '<eof>'}")

    if WITH_BUILD:
        print("\n  rebuilding the effective store twice (slow)...")
        run(["x4effective", "build"], timeout=3600)
        f1 = store_fingerprint()
        run(["x4effective", "build"], timeout=3600)
        f2 = store_fingerprint()
        if f1 == f2:
            print(f"  ok    {'x4effective build idempotent':<34} {f1[:16]}")
        else:
            bad.append("x4effective build")
            print(f"  VARY  x4effective build   {f1[:16]} != {f2[:16]}")

    print("=" * 84)
    print(f"non-deterministic outputs: {len(bad)}")
    for b in bad:
        print(f"   {b}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

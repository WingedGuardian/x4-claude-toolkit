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

A case is judged on its EXIT CODE as well as its text (AUDIT-2026-09-24 GT-2): the
same error printed twice is not a stable answer, it is no answer twice. Each case
names the exit codes that mean "answered" (x4compat legitimately returns 1 when it
finds collisions); an rc outside that set means the case was never really compared.

Run:  uv run python gates/determinism_audit.py [--with-build]
Exit: 0 every case answered, identically, twice (and, with --with-build, both
      builds succeeded and produced the same store)
      1 any variance -- in output OR exit code -- a traceback, or a failed build
        (a failed build leaves the OLD store in place, so fingerprinting it twice
        would score "idempotent" over a build that never happened)
      2 no variance, but some case never answered (rc outside its allowed set) --
        could not look, not "deterministic"
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


def run(argv: list[str], timeout: int = 1800) -> tuple[int, str]:
    """(returncode, stdout+stderr). The returncode is half the answer -- dropping it
    scored a tool that refused identically twice as 'stable' (GT-2)."""
    p = subprocess.run(["uv", "run", "--project", str(ROOT), *argv], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def normalize(s: str) -> str:
    return _VOLATILE.sub("<t>", s)


#: (label, argv, exit codes that mean the case ANSWERED). Anything else -- a refusal
#: (2), a degraded run (3), a crash -- means the output compared was not an answer.
#: x4compat: 1 = collisions found, which is an answer (see `_compat.main`).
#: `x4compat check` with no candidate is the whole ACTIVE set -- installed, enabled in
#: its manifest and in the profile (`--all` was removed, AUDIT-2026-09-24 AN-7).
CASES = [
    ("x4compat check (whole set)", ["x4compat", "check"], {0, 1}),
    ("x4similar sweep", ["x4similar", "--threshold", "0.9"], {0}),
    ("x4xref who-calls", ["x4xref", "who-calls", "find_station"], {0}),
    ("x4xref who-listens", ["x4xref", "who-listens", "event_player_ejected"], {0}),
    ("x4effective ls macro", ["x4effective", "ls", "macro", "--limit", "300"], {0}),
    ("x4effective diff-mod", ["x4effective", "diff-mod", "base"], {0}),
    ("x4effective dump", ["x4effective", "dump", "libraries/wares.xml"], {0}),
    ("x4stats macro", ["x4stats", "macro", str(
        _env.reference() / "assets/props/SurfaceElements/macros"
        / "shield_arg_l_standard_01_mk1_macro.xml")], {0}),
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
    bad, unanswered = [], []
    print("DETERMINISM AUDIT — identical inputs must give identical output")
    print("=" * 84)
    for label, argv, allowed in CASES:
        (rc1, a), (rc2, b) = run(argv), run(argv)
        a, b = normalize(a), normalize(b)
        if rc1 != rc2:
            bad.append(label)
            print(f"  VARY  {label:<34} exit code {rc1} then {rc2}")
            continue
        if "Traceback (most recent call last)" in a or "Traceback (most recent call last)" in b:
            bad.append(label)
            print(f"  CRASH {label:<34} rc {rc1}, a traceback both times is not stable output")
            continue
        if rc1 not in allowed:
            unanswered.append(label)
            print(f"  NOANS {label:<34} rc {rc1} twice (answers are {sorted(allowed)}) -- "
                  "never compared")
            tail = (a.strip().splitlines() or ["<no output>"])[-1]
            print(f"        {tail[:110]}")
            continue
        if a == b:
            print(f"  ok    {label:<34} stable, rc {rc1} ({len(a)}B)")
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
        builds, prints = [], []
        for _ in range(2):
            rc, out = run(["x4effective", "build"], timeout=3600)
            builds.append((rc, out))
            prints.append(store_fingerprint() if rc == 0 else None)
        failed = [(i + 1, rc, out) for i, (rc, out) in enumerate(builds) if rc != 0]
        f1, f2 = prints
        if failed:
            # A failed build leaves the previous store in place: fingerprinting it
            # would compare the OLD store with itself and score "idempotent".
            bad.append("x4effective build")
            for n, rc, out in failed:
                tail = (out.strip().splitlines() or ["<no output>"])[-1]
                print(f"  FAIL  x4effective build #{n}  rc {rc}: {tail[:100]}")
        elif f1 == f2:
            print(f"  ok    {'x4effective build idempotent':<34} {f1[:16]}")
        else:
            bad.append("x4effective build")
            print(f"  VARY  x4effective build   {f1[:16]} != {f2[:16]}")

    print("=" * 84)
    print(f"non-deterministic outputs: {len(bad)}")
    for b in bad:
        print(f"   {b}")
    print(f"never answered (not compared): {len(unanswered)}")
    for u in unanswered:
        print(f"   {u}")
    if bad:
        return 1
    if unanswered:
        print(f"NOT CHECKED: {len(unanswered)} of {len(CASES)} case(s) never answered, so "
              "their determinism is unknown. rc 2, not 0.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

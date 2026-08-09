#!/usr/bin/env python
"""Corpus sweep — run x4validate over EVERY installed mod, both tiers.

The widest robustness net available: ~120 real mods, every authoring style and
every malformed file anyone actually ships. A tool that survives this survives
the user's install. Looks for crashes and hangs, NOT for findings — a mod with
errors is the tool working.

Run:  uv run python gates/corpus_sweep.py [--tier=a|b|both] [--verbose]
Exit: 0 no crashes, 1 any traceback/hang.
"""
from __future__ import annotations

import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402

EXT = _env.extensions()
TIER = next((a.split("=")[1] for a in sys.argv if a.startswith("--tier=")), "both")
VERBOSE = "--verbose" in sys.argv


def main() -> int:
    mods = [d for d in sorted(EXT.iterdir())
            if d.is_dir() and not d.name.lower().startswith("ego_dlc_")]
    tiers = ["a", "b"] if TIER == "both" else [TIER]
    print(f"CORPUS SWEEP — {len(mods)} mods x {len(tiers)} tier(s) "
          f"= {len(mods) * len(tiers)} runs\n" + "=" * 84)
    crashes, slow = [], []
    codes = Counter()
    t_all = time.time()

    for tier in tiers:
        for mod in mods:
            t0 = time.time()
            try:
                p = subprocess.run(
                    ["uv", "run", "x4validate", str(mod), "--tier", tier],
                    cwd=ROOT, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=1200)
            except subprocess.TimeoutExpired:
                crashes.append((mod.name, tier, "HANG (>20min)", ""))
                print(f"  HANG  {mod.name} (tier {tier})")
                continue
            dt = time.time() - t0
            out = (p.stdout or "") + (p.stderr or "")
            codes[(tier, p.returncode)] += 1
            if "Traceback (most recent call last)" in out:
                tail = [ln for ln in out.strip().splitlines() if ln.strip()][-3:]
                crashes.append((mod.name, tier, "traceback", "\n      ".join(tail)))
                print(f"  CRASH {mod.name} (tier {tier})")
            elif dt > 120:
                slow.append((mod.name, tier, dt))
            if VERBOSE:
                print(f"    {mod.name:<44} tier {tier}  exit {p.returncode}  {dt:5.1f}s")

    print("=" * 84)
    print(f"completed in {time.time() - t_all:.0f}s")
    print("exit-code distribution (0 clean · 1 findings · 3 skipped-work):")
    for (tier, rc), n in sorted(codes.items()):
        print(f"   tier {tier}  exit {rc}: {n}")
    print(f"\nCRASHES/HANGS: {len(crashes)}")
    for name, tier, kind, detail in crashes:
        print(f"\n  {name} (tier {tier}) — {kind}")
        if detail:
            print(f"      {detail}")
    if slow:
        print(f"\nslow (>120s): {len(slow)}")
        for name, tier, dt in sorted(slow, key=lambda r: -r[2])[:10]:
            print(f"   {name:<44} tier {tier}  {dt:.0f}s")
    return 1 if crashes else 0


if __name__ == "__main__":
    raise SystemExit(main())

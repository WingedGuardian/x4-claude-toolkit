"""Regression sweep: Tier A + Tier B error/degraded counts per mod.

Sweeps every mod source folder under `$X4_MODS`, plus any INSTALLED extension
named on the command line (the deployed copy of a mod validates differently from
its dev copy — a mod that is not installed has no knowable load-order position, so
Tier B has to assume it loads last).
"""
from __future__ import annotations

import sys

import _env

from x4validate import _check, _merge

DEV = _env.mods_dir()
EXT = _env.extensions()

mods = [p for p in sorted(DEV.iterdir()) if p.is_dir() and p.name != "_registry"]
mods += [p for p in (EXT / n for n in sys.argv[1:]) if p.is_dir()]

for mod in mods:
    row = [f"{mod.name:38s}"]
    for tier in ("a", "b"):
        rep = _check.validate(mod, _merge.Config(), tier=tier)
        row.append(f"tier {tier}: {len(rep.errors):2d} err  {len(rep.degraded)} degr "
                   f"{len(rep.skipped)} skip")
    print("  |  ".join(row))
    for f in rep.errors:
        print(f"      [b] {f.category}: {f.message[:120]}  ({f.vpath}:{f.line})")

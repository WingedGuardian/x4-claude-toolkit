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

# Leading "_" marks a workspace folder, not a mod (_registry, _reports). They have
# no content.xml, so since 2026-08-01 they are correctly reported as degraded —
# which is the right verdict about the wrong input. Excluding the whole prefix
# rather than naming folders one at a time, which is how _reports slipped in.
mods = [p for p in sorted(DEV.iterdir()) if p.is_dir() and not p.name.startswith("_")]
mods += [p for p in (EXT / n for n in sys.argv[1:]) if p.is_dir()]

# ADVISORY, and it says so -- there is no baseline here to regress against, so per-mod
# error counts are a report rather than a verdict. What it must NOT do is sit in gates/
# and be scored `ok` for having examined nothing: `run-gates.sh` judges purely on the
# exit code, and this file previously ended on a print. Examining zero mods is its one
# real failure mode, and it is a NON-ANSWER (rc 2), never a pass.
if not mods:
    print(f"REFUSING: no mods to check under {DEV} (and none named on the command "
          f"line).\n  Zero mods examined is a NON-ANSWER, not a clean run.",
          file=sys.stderr)
    raise SystemExit(2)
print(f"advisory report over {len(mods)} mod(s); there is no baseline to regress "
      f"against, so a clean run here is not a verdict.")

for mod in mods:
    row = [f"{mod.name:38s}"]
    for tier in ("a", "b"):
        rep = _check.validate(mod, _merge.Config(), tier=tier)
        row.append(f"tier {tier}: {len(rep.errors):2d} err  {len(rep.degraded)} degr "
                   f"{len(rep.skipped)} skip")
    print("  |  ".join(row))
    for f in rep.errors:
        print(f"      [b] {f.category}: {f.message[:120]}  ({f.vpath}:{f.line})")

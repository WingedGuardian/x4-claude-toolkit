r"""Gate: the effective-schema check must keep agreeing with its own measurement.

W3.1 was measured across the whole installed modlist BEFORE it was written, and
the implementation was then required to reproduce that number. This gate freezes
the result so a later "optimisation" cannot quietly change what the check reports.

The bars, all measured 2026-07-29 over the 102 installed non-DLC mods:

  * 127 (mod,file) pairs validated
  * 105 findings introduced == 45 gating + 57 advisory + 3 suppressed
  * 10 of 102 mods flagged
  * the four KNOWN-REAL defects all still reported

Why the totals are pinned and not just the four defects: a check that reports the
right four while inventing 200 others is not usable, and a check that reports the
right four because it reports everything is not a check. The composition is the
claim, so the composition is what is frozen.

Why the four are pinned SEPARATELY: totals can be met by accident after a tuning
change that silences a real finding and adds a spurious one. These are the ones
with independent evidence behind them, so silencing any of them is a regression
no matter what the totals say.

Run: `uv run python gates/schema_sweep.py`
"""

from __future__ import annotations

import re

import _env

from x4validate import _check, _merge

EXPECT_PAIRS = 127
EXPECT_ERR = 45
EXPECT_INFO = 57
EXPECT_SUPPRESSED = 3
EXPECT_MODS_FLAGGED = 10

#: Independently evidenced against `reference\`, not just "the tool said so".
#: Each entry: mod -> (gating, advisory, what makes it real).
KNOWN_REAL = {
    "mlog_deadair_eco_no_da_wares": (30, 0,
        "removes <production>, orphaning the <limits> sibling — structural damage "
        "caused BY a diff, which no other check in this package can see"),
    "cpsdo_faction": (7, 8,
        "race='central' x7 — the effective race list (base+DLC+all 102 mods) has 10 "
        "entries and 'central' is not one of them"),
    "xspvro": (2, 9,
        "job ids containing a SPACE ('xenon_carrier_defense xl_EP') against the id "
        "pattern facet"),
    "escape_pod": (1, 0,
        "<filter> placed directly under <sound>; all 309 vanilla <filter> elements "
        "sit under <effects>, and <sound>'s content model has no filter child"),
}

_RE_SUP = re.compile(r"; (\d+) enumeration failure")


def main() -> int:
    ext = _env.extensions()
    mods = [d for d in sorted(ext.iterdir())
            if d.is_dir() and not d.name.lower().startswith("ego_dlc_")]
    cfg = _merge.Config()

    pairs = err = info = sup = 0
    per_mod: dict[str, tuple[int, int]] = {}
    for d in mods:
        report = _check.Report()
        _check.check_effective_schema(d, cfg, report)
        e = sum(1 for f in report.findings if f.severity == "error")
        i = sum(1 for f in report.findings if f.severity == "info")
        for note in report.notes:
            if note.startswith("effective-schema:"):
                pairs += int(note.split()[1])
            m = _RE_SUP.search(note)
            if m:
                sup += int(m.group(1))
        err += e
        info += i
        if e or i:
            per_mod[d.name] = (e, i)

    print(f"{len(mods)} non-DLC mods | {pairs} (mod,file) pairs validated")
    print(f"{err} gating + {info} advisory + {sup} suppressed = "
          f"{err + info + sup} introduced | {len(per_mod)} mods flagged\n")
    for name, (e, i) in sorted(per_mod.items(), key=lambda kv: -sum(kv[1])):
        mark = "*" if name in KNOWN_REAL else " "
        print(f" {mark} {name:36} {e:>3} gating  {i:>3} advisory")

    fail: list[str] = []
    for label, got, want in (("pairs", pairs, EXPECT_PAIRS),
                             ("gating", err, EXPECT_ERR),
                             ("advisory", info, EXPECT_INFO),
                             ("suppressed", sup, EXPECT_SUPPRESSED),
                             ("mods flagged", len(per_mod), EXPECT_MODS_FLAGGED)):
        if got != want:
            fail.append(f"{label}: got {got}, measured baseline is {want}")

    for name, (we, wi, why) in KNOWN_REAL.items():
        got = per_mod.get(name)
        if got is None:
            fail.append(f"{name}: REPORTS NOTHING — this defect is real ({why})")
        elif got != (we, wi):
            fail.append(f"{name}: {got[0]} gating/{got[1]} advisory, expected {we}/{wi} ({why})")

    print()
    if fail:
        print("FAIL — the check no longer matches its own measurement:")
        for f in fail:
            print(f"  ! {f}")
        print("\nInvestigate before re-baselining. A moved number means either the modlist "
              "changed (re-measure and update the constants, saying so) or the check did "
              "(that is the regression this gate exists to catch).")
        return 1
    print("OK — matches the pre-implementation sweep exactly, and all four "
          "independently-evidenced defects are still reported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

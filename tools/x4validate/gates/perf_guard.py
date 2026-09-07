#!/usr/bin/env python
r"""Per-mod runtime guard for `--update`, against a machine-local baseline.

Why per-mod, never a total
--------------------------
Round 7 measured this exact scenario: total wall-clock over 115 mods went
594.4s -> 595.7s, a ratio of **1.00x**. Clean by any aggregate reading. Per item,
two mods had gone **2.8s -> 112s (39x)** and **2.4s -> 121s (51x)**, hidden
because a third mod happened to get faster and cancelled them out. An aggregate
is the shape a real regression hides in, so this compares items and quotes the
total only as context.

Why the baseline is LOCAL
-------------------------
Wall-clock is machine-specific; a committed baseline would be wrong for every
other user and would fail their first run. So `--record` writes a gitignored
file, exactly like `nexus_fixture`'s record/replay. Re-record deliberately after
an intended performance change, never to silence a failure.

Thresholds
----------
FAIL requires BOTH a large ratio AND a material absolute delta: 0.001s -> 0.004s
is 4x and means nothing. Bug #10 (a >900s hang) and the Round 7 regression both
clear these comfortably; noise does not.

Run:  uv run python gates/perf_guard.py [--record] [--limit=N]
Exit: 0 within tolerance (or recorded), 1 any regression (including a mod that
      went from timing to CRASHING), 2 no baseline, 3 DEGRADED — nothing
      regressed among the mods that COULD be timed, but the population was
      not whole (a crash in a mod the baseline never covered, or --record
      over one). NB `scripts/run-gates.sh` buckets 3 as a FAILURE, which is
      the conservative reading and deliberate; the runner's OWN rc 3 means
      "could not run", so the two scales collide on that number by
      coincidence rather than by design.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402
from x4validate import _check, _merge  # noqa: E402

BASELINE = ROOT / ".perf-baseline.json"
RECORD = "--record" in sys.argv
LIMIT = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), 0)

#: Both must be exceeded to fail. Ratio alone flags noise; absolute alone flags
#: any mod that is simply big.
RATIO_FAIL = 3.0
DELTA_FAIL = 2.0


def is_regression(base: float, curr: float,
                  ratio_fail: float = RATIO_FAIL,
                  delta_fail: float = DELTA_FAIL) -> bool:
    """BOTH conditions, never either alone.

    Ratio alone fires on noise (0.001s -> 0.004s is 4x). Absolute alone fires on
    any mod that is simply large. Verified against the real cases: Round 7's
    39x/51x and bug #10's >900s hang trip it; a 17.6s -> 6.1s speedup and a
    16.24s -> 16.36s drift do not.
    """
    ratio = (curr / base) if base > 0.001 else float("inf")
    return ratio > ratio_fail and (curr - base) > delta_fail


def measure() -> "tuple[dict[str, float], dict[str, str]]":
    """(timings, crashes). TWO channels, because they are two different answers.

    This used to return timings alone and `continue` past an exception, with the
    comment "a crash is a finding, not a timing" sitting directly above the line
    that made it neither. The crashed mod simply left `curr`, so `set(base) &
    set(curr)` no longer contained it, and the run printed "No per-mod regression
    beyond tolerance" and returned 0 — a step that narrows the data and
    reports success anyway, in the gate whose whole job is to notice a change for
    the worse.

    A validate() that RAISES where it used to complete is the harshest regression
    there is: not slower, but unbounded. It has to reach the verdict.
    """
    ext = _env.extensions()
    mods = [d for d in sorted(ext.iterdir())
            if d.is_dir() and not d.name.lower().startswith("ego_dlc_")]
    if LIMIT:
        mods = mods[:LIMIT]
    cfg = _merge.Config()
    # Warm the schema cache first so its ~100s one-off is not charged to whichever
    # mod happens to sort first — that alone would look like a 40x regression.
    if mods:
        _check.validate(mods[0], cfg, update=True)
    out: dict[str, float] = {}
    crashed: dict[str, str] = {}
    for d in mods:
        t = time.perf_counter()
        try:
            _check.validate(d, cfg, update=True)
        except Exception as exc:                      # a crash is a finding, not a timing
            crashed[d.name] = f"{type(exc).__name__}: {exc}"
            print(f"  ERROR {d.name}: {crashed[d.name]}", file=sys.stderr)
            continue
        out[d.name] = round(time.perf_counter() - t, 3)
        print(f"  {d.name}: {out[d.name]}s", file=sys.stderr)
    return out, crashed


def retime(mod_name: str, cfg) -> float | None:
    """Time ONE mod again. None means it could not be measured at all."""
    d = _env.extensions() / mod_name
    if not d.is_dir():
        print(f"  re-time {mod_name}: no such mod directory — cannot confirm",
              file=sys.stderr)
        return None
    t = time.perf_counter()
    try:
        _check.validate(d, cfg, update=True)
    except Exception as exc:
        # Say so. A re-time that could not run is the UNCONFIRMED path, and the
        # caller escalates it rather than clearing it -- but a reader still has
        # to be able to see WHY it could not be confirmed. (Caught by
        # tests/test_no_silent_swallow.py on the first draft of this function,
        # which returned None with no word to anyone.)
        print(f"  re-time {mod_name}: {type(exc).__name__}: {exc} — cannot confirm",
              file=sys.stderr)
        return None
    return round(time.perf_counter() - t, 3)


def confirm_regressions(bad, retime_fn):
    """Re-time each suspected regression once; keep only those that REPRODUCE.

    WHY (MEASURED 2026-08-24). `time.perf_counter()` on Windows advances while
    the machine is SUSPENDED, so a gate run left overnight charges the whole
    sleep to whichever mod happened to be timing when the lid closed. A real
    run reported:

        bh_shader   2.71s -> 2210.88s  (814.9x)   PERF REGRESSION

    and the same mod re-timed at **3.47s** minutes later. The suspend was
    confirmed independently in the Windows event log (Kernel-Power 131,
    ResumeCount: 3, across an 18-hour wall-clock window for a sweep that used
    well under an hour of CPU).

    A timing that spans a suspend is a NON-ANSWER, and this register's founding
    rule is that a non-answer must never be rendered as a finding. Re-timing is
    platform-independent -- it assumes nothing about whether a given clock
    advances across sleep -- and costs nothing on the normal path, because it
    only runs for items already flagged.

    A re-time that FAILS is reported as UNCONFIRMED and still fails the gate:
    "could not check" is not "not a regression".
    """
    confirmed, spurious = [], []
    for row in bad:
        _d, _ratio, b, _c, mod = row
        again = retime_fn(mod)
        if again is None or is_regression(b, again):
            confirmed.append((row, again))
        else:
            spurious.append((row, again))
    return confirmed, spurious


def main() -> int:
    if RECORD:
        data, crashed = measure()
        BASELINE.write_text(json.dumps(data, indent=1), encoding="utf-8")
        print(f"recorded {len(data)} mod timings -> {BASELINE.name} "
              f"(local only; not committed)")
        if crashed:
            # A baseline recorded over a partially-crashing population puts those
            # mods OUTSIDE the comparison permanently, and nothing downstream can
            # tell that from "this mod does not exist". Say it at record time, and
            # in the rc, or the omission is inherited silently by every later run.
            print(f"\n  DEGRADED: {len(crashed)} mod(s) could not be timed at all, "
                  f"so the baseline does not cover them:", file=sys.stderr)
            for name, why in sorted(crashed.items()):
                print(f"    {name}: {why}", file=sys.stderr)
            return 3
        return 0

    if not BASELINE.is_file():
        print(f"no baseline at {BASELINE.name} — run `perf_guard.py --record` first "
              f"(it is machine-local by design)", file=sys.stderr)
        return 2

    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    curr, crashed = measure()
    shared = sorted(set(base) & set(curr))

    rows = []
    for mod in shared:
        b, c = base[mod], curr[mod]
        ratio = (c / b) if b > 0.001 else float("inf")
        rows.append((c - b, ratio, b, c, mod))

    tb = sum(base[m] for m in shared)
    tc = sum(curr[m] for m in shared)
    print("=" * 88)
    print(f"PERF GUARD — {len(shared)} mods vs local baseline")
    print("=" * 88)
    print(f"  total (context only, NOT the verdict): {tb:.1f}s -> {tc:.1f}s "
          f"({tc - tb:+.1f}s, {tc / tb if tb else 1:.2f}x)")

    print("\n  largest absolute changes:")
    for d, ratio, b, c, mod in sorted(rows, reverse=True)[:6]:
        r = "inf" if ratio == float("inf") else f"{ratio:.1f}x"
        print(f"    {mod:<34} {b:>7.2f}s -> {c:>7.2f}s  {d:+7.2f}s  {r}")

    suspected = [r for r in rows if is_regression(r[2], r[3])]
    if suspected:
        print(f"\n  {len(suspected)} suspected — re-timing each once before reporting "
              f"(a timing that spans a machine SUSPEND is a non-answer, not a finding)")
    # `cfg` was never bound in THIS scope: measure() builds its own Config and keeps
    # it local, so the lambda below closed over a name that does not exist here.
    # Python resolves a closed-over name when the lambda is CALLED, and
    # confirm_regressions calls it once per suspected regression -- so this raised
    # NameError exactly when the gate had something to say, and never when it did
    # not. Built only when there is something to re-time.
    cfg = _merge.Config() if suspected else None
    confirmed, spurious = confirm_regressions(suspected, lambda m: retime(m, cfg))
    for (d, ratio, b, c, mod), again in sorted(spurious, reverse=True):
        print(f"    DISCARDED {mod:<28} {b:.2f}s -> {c:.2f}s ({ratio:.1f}x) "
              f"did NOT reproduce: {again:.2f}s on re-timing")

    bad = [row for row, _again in confirmed]
    print(f"\n  REGRESSIONS (>{RATIO_FAIL}x AND >{DELTA_FAIL}s, CONFIRMED): {len(bad)}")
    for (d, ratio, b, c, mod), again in sorted(confirmed, reverse=True):
        note = "could NOT be re-timed — reported UNCONFIRMED" if again is None \
            else f"reproduced at {again:.2f}s"
        print(f"    {mod:<34} {b:.2f}s -> {c:.2f}s  ({d:+.2f}s, {ratio:.1f}x)  [{note}]")
    # TWO CAUSES, ONE OLD BUCKET. `set(base) - set(curr)` used to collapse "the mod
    # folder is gone" (benign modlist drift) with "validate() RAISED on it" (the
    # worst regression this gate can encounter), and printed both as an
    # excluded-from-the-comparison note underneath a rc 0.
    regressed_to_crash = sorted(n for n in crashed if n in base)
    new_crash = sorted(n for n in crashed if n not in base)
    # NOT MEASURED = NOT UNINSTALLED. This bucket used to assert "are no longer
    # installed", which is a claim about the FILESYSTEM that nothing here checks:
    # under the documented `--limit=N`, every baselined mod past the limit lands here
    # while sitting on disk untouched. MEASURED with a 5-mod baseline and --limit=2:
    # "3 baselined mod(s) are no longer installed" over 3 mods that all exist. The
    # PRE-ARC wording, "not measured this run", was accurate; this arc replaced a true
    # statement with a false one. `retime()` already does the `is_dir()` check, so the
    # two states are separable -- and now are.
    gone = sorted(set(base) - set(curr) - set(crashed))
    if gone:
        try:
            _ext = _env.extensions()
            absent = [m for m in gone if not (_ext / m).is_dir()]
        except SystemExit:
            absent = []          # cannot resolve the root: claim nothing about disk
        still = [m for m in gone if m not in absent]
        if absent:
            print("\n  note: %d baselined mod(s) are no longer installed (e.g. %s) — "
                  "excluded from the comparison" % (len(absent), absent[:2]))
        if still:
            print("\n  note: %d baselined mod(s) were NOT MEASURED this run but are "
                  "still installed\n        (e.g. %s) — excluded from the comparison. "
                  "Expected under --limit; unexplained otherwise."
                  % (len(still), still[:2]))
    if regressed_to_crash:
        print(f"\n  CRASHED, and the baseline TIMED them — validate() went from "
              f"completing to raising: {len(regressed_to_crash)}")
        for n in regressed_to_crash:
            print(f"    {n:<34} baseline {base[n]:.2f}s -> {crashed[n]}")
    if new_crash:
        print(f"\n  NOT CHECKED: {len(new_crash)} mod(s) crashed and are absent from "
              f"the baseline, so no comparison is possible for them:")
        for n in new_crash:
            print(f"    {n}: {crashed[n]}")

    print("\n" + "=" * 88)
    if bad or regressed_to_crash:
        print("PERF REGRESSION — investigate before shipping.")
        return 1
    if new_crash:
        print("DEGRADED: no regression among the mods that COULD be timed, but the "
              "population was not whole.")
        return 3
    print("No per-mod regression beyond tolerance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

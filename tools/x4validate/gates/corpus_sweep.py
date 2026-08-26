#!/usr/bin/env python
"""Corpus sweep — run x4validate over EVERY installed mod, both tiers.

The widest robustness net available: ~120 real mods, every authoring style and
every malformed file anyone actually ships. A tool that survives this survives
the user's install. Looks for crashes and hangs, NOT for findings — a mod with
errors is the tool working.

Run:  uv run python gates/corpus_sweep.py [--tier=a|b|both] [--verbose]
Exit: 0 no crashes, 1 any traceback, CONFIRMED hang, or undocumented exit code.
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


#: The only exit codes x4validate is documented to produce. ANYTHING else means the
#: process did not run to a decision, and "did not reach a verdict" is not "passed".
EXPECTED_CODES = frozenset({0, 1, 3})


def crash_reason(returncode: int, out: str) -> str | None:
    """Why this run counts as a crash, or None if it reached a verdict.

    WHY THE RETURN CODE AND NOT JUST THE TRACEBACK (F55, MEASURED 2026-08-25).
    Detection used to be `"Traceback (most recent call last)" in out` plus a
    subprocess timeout. A process killed by the Windows LOADER never starts
    Python, so it emits no traceback and no output whatsoever -- neither test can
    fire. A real run of this gate recorded:

        tier a  exit 3221225794: 52
        tier b  exit 3221225794: 121
        CRASHES/HANGS: 0            <-- and this gate returned 0

    3221225794 is 0xC0000142 (STATUS_DLL_INIT_FAILED). 173 of 242 invocations
    never started and the sweep passed. The exit codes were already printed in the
    distribution block below; only the VERDICT failed to consult them -- the
    register's founding shape, but printing the evidence rather than hiding it.
    """
    if "Traceback (most recent call last)" in out:
        return "traceback"
    if returncode not in EXPECTED_CODES:
        return (f"exit {returncode} (0x{returncode & 0xFFFFFFFF:08X}) -- not a documented "
                f"exit code, so the process did not run to a decision")
    return None


def run_one(mod, tier: str):
    """Run x4validate once. None means it TIMED OUT."""
    try:
        return subprocess.run(
            ["uv", "run", "x4validate", str(mod), "--tier", tier],
            cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=1200)
    except subprocess.TimeoutExpired:  # silent-ok: None IS the channel -- the
        # caller reads it as "timed out" and escalates. Nothing is discarded.
        return None


def confirm_hang(mod, tier: str, run=run_one) -> tuple[bool, str]:
    """Re-run once before calling a timeout a hang. (still_hung, why).

    WHY (MEASURED 2026-08-26). This gate reported
    `xenon_backup (tier b) HANG (>20min)`. The same mod re-ran in **13 s**. The
    machine had SUSPENDED mid-sweep -- Windows event log, resume from S3 at
    16:49:29, with the sweep finishing 82 s later and total elapsed 13,879 s
    against a healthy 1,228 s. `subprocess.run(timeout=...)` counts WALL CLOCK,
    so a suspend fires it while no CPU time passed at all.

    This is F50 in a second gate: `perf_guard` already re-times a suspected
    regression before reporting it, and this one did not. A timing that spans a
    suspend is a NON-ANSWER, and a non-answer must never be rendered as a finding.

    ⚠ It WILL recur on this machine: the sleep timer counts USER inactivity, not
    CPU, so any long unattended sweep can be interrupted by it.

    A re-run that cannot be performed leaves the hang UNCONFIRMED and still
    reported -- "could not check" is never "not a hang".
    """
    try:
        again = run(mod, tier)
    except Exception as exc:  # silent-ok: NOT silent -- the reason is returned to
        # the caller and printed beside the mod, and the hang is still REPORTED.
        # A re-check that could not run must escalate, never clear: "could not
        # check" is never "not a hang" (same rule as perf_guard's retime).
        return True, f"UNCONFIRMED - could not re-check ({type(exc).__name__}: {exc})"
    if again is None:
        return True, "HANG reproduced on a second run"
    return False, "did NOT reproduce on a second run (suspect a machine suspend)"


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
                # Confirm before reporting -- same rule as perf_guard (F50).
                still, why = confirm_hang(mod, tier)
                if still:
                    crashes.append((mod.name, tier, f"HANG (>20min) - {why}", ""))
                    print(f"  HANG  {mod.name} (tier {tier}) - {why}")
                else:
                    print(f"  DISCARDED {mod.name} (tier {tier}) - {why}")
                continue
            dt = time.time() - t0
            out = (p.stdout or "") + (p.stderr or "")
            codes[(tier, p.returncode)] += 1
            reason = crash_reason(p.returncode, out)
            if reason:
                tail = [ln for ln in out.strip().splitlines() if ln.strip()][-3:]
                crashes.append((mod.name, tier, reason, "\n      ".join(tail)))
                print(f"  CRASH {mod.name} (tier {tier}) -- {reason}")
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

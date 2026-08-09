#!/usr/bin/env python
"""Mutation probe — does the suite actually KILL a broken merge, or just pass?

334 passing tests is a count, not a quality. The only honest measure is: break
the code deliberately and see whether anything notices. A mutant that SURVIVES
is a line the suite does not really check — which is exactly how a `continue`
that discarded 858 mod operations sat in `_do_replace` for months with a green
suite above it.

Scoped to the diff-application core rather than the whole package: that is the
code every other tool trusts, and a scoped run finishes in minutes instead of
hours (a mutation run nobody waits for is a mutation run nobody does).

Each mutation is a small, plausible edit. For each: patch the file, run the
targeted tests, restore. Survivors are reported with the exact edit and what
their survival would mean.

Run:  uv run python gates/mutation_probe.py [--verbose]
Exit: 0 if every mutant is killed, 1 if any survives.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "x4validate" / "_merge.py"
TESTS = ["tests/test_merge.py", "tests/test_check.py", "tests/test_provenance.py"]
VERBOSE = "--verbose" in sys.argv


@dataclass
class Mutant:
    name: str
    old: str
    new: str
    why: str          # what a SURVIVOR would mean


#: Each anchor must be UNIQUE in the file, or the probe would mutate the wrong
#: site and report a meaningless result — so a non-unique anchor is itself a fail.
MUTANTS = [
    Mutant("root-replace payload guard disabled",
           "if len(new_children) != 1:",
           "if len(new_children) != 1 and False:",
           "the multi-payload guard on a root replace is unchecked"),
    Mutant("ok always True (THE ORIGINAL BUG)",
           "applied.append(AppliedOp(op.tag, sel, line, reason is None,",
           "applied.append(AppliedOp(op.tag, sel, line, True,",
           "a no-op reported as applied and nothing notices"),
    Mutant("ambiguous-sel guard removed",
           "if len(targets) > 1:",
           "if len(targets) > 99999:",
           "RFC-5261 single-node rule unenforced; ops apply where the engine skips"),
    Mutant("empty-target guard removed",
           "if not targets:",
           "if not targets and False:",
           "a sel matching nothing would be reported as applied"),
    Mutant("provenance dropped on root replace",
           'recorder.full_override(Origin(origin.source, "replace-root", origin.line))',
           "pass  # mutant: provenance dropped",
           "values land but origin stays base — the subtle half of the defect"),
    Mutant("add pos=prepend never taken",
           'if pos == "prepend":',
           'if pos == "__never__":',
           "prepend ordering is unverified"),
]


def run_tests() -> bool:
    """True if the suite PASSES (i.e. the mutant survived undetected)."""
    p = subprocess.run(["uv", "run", "--project", str(ROOT), "pytest", "-q", *TESTS],
                       cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=1800)
    return p.returncode == 0


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    if not run_tests():
        print("BASELINE IS RED — fix the suite before measuring mutants.")
        return 1
    print(f"MUTATION PROBE — {len(MUTANTS)} mutants against {TARGET.name}")
    print("=" * 88)
    survivors = []
    try:
        for m in MUTANTS:
            n = original.count(m.old)
            if n != 1:
                print(f"  SKIP   {m.name:<40} anchor appears {n}x (need exactly 1)")
                survivors.append((m, f"anchor not unique ({n}) — probe cannot aim"))
                continue
            TARGET.write_text(original.replace(m.old, m.new, 1), encoding="utf-8")
            survived = run_tests()
            TARGET.write_text(original, encoding="utf-8")
            if survived:
                print(f"  LIVED  {m.name:<40} {m.why}")
                survivors.append((m, m.why))
            else:
                print(f"  killed {m.name:<40}")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    killed = len(MUTANTS) - len(survivors)
    print("=" * 88)
    print(f"killed {killed}/{len(MUTANTS)}   survivors: {len(survivors)}")
    for m, why in survivors:
        print(f"\n  SURVIVOR: {m.name}")
        print(f"    edit:  {m.old[:66]}")
        print(f"      ->   {m.new[:66]}")
        print(f"    means: {why}")
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())

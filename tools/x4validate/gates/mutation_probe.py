#!/usr/bin/env python
"""Mutation probe — does the suite actually KILL a broken detector, or just pass?

A passing test count is a count, not a quality. The only honest measure is: break
the code deliberately and see whether anything notices. A mutant that SURVIVES is
a line the suite does not really check — which is exactly how a `continue` that
discarded 858 mod operations sat in `_do_replace` for months with a green suite
above it.

WHY THIS COVERS MORE THAN `_merge.py` NOW (F54 mitigation 2). F54 records that a
mutation window can turn a sound assertion VACUOUS: with the ambiguous-`sel`
guard disabled, an assertion that it did NOT fire cannot go red. The general form
of that worry is "which of our detectors would nobody notice losing?", and a
mutant is the only positive control that cannot itself go vacuous. MEASURED
2026-08-25: 6/6 killed on `_merge.py` — those detectors are provably checked, and
nothing else had that proof.

Each mutation is a small, plausible edit against a guard whose failure has a
MEASURED cost in docs/BLIND-SPOTS.md or CLAUDE.md. That selection rule is
load-bearing: a contrived mutant that nothing kills is noise, not a finding.

⚠ THIS GATE DELIBERATELY BREAKS THE WORKING TREE WHILE IT RUNS. The mutated file
is a TRACKED file, so the tree looks normal — that is gotcha #27's actual lesson,
and it is why `.mutation-probe-active` exists and why you should tell anyone
sharing the tree before starting.

Run:  uv run python gates/mutation_probe.py [--verbose] [--recover]
Exit: 0 every mutant killed · 1 survivors or hangs · 2 cannot run (see --recover)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "x4validate"
VERBOSE = "--verbose" in sys.argv
RECOVER = "--recover" in sys.argv

#: Written before the first mutation, removed after the last restore. Its presence
#: means the tree may be mutated RIGHT NOW.
MARKER = ROOT / ".mutation-probe-active"
#: Byte-for-byte copies taken before any mutation, so recovery never depends on
#: `finally` having run. `finally` does NOT run on SIGKILL, and a killed probe
#: leaving a mutated source on disk is how v2.5.0 nearly shipped a disabled
#: ambiguous-sel check in a public release.
PRISTINE = ROOT / ".mutation-probe-pristine"

#: A mutant that has not failed in this long is not "slow", it is a finding about
#: the suite. The whole suite runs in ~20s. The previous 1800s meant one hanging
#: mutant cost half an hour, which made widening this gate unaffordable.
TEST_TIMEOUT = 120

#: target filename -> the tests that should notice it breaking.
#: Scoped for speed; a survivor is re-checked against the FULL suite before being
#: reported, so scoping can never manufacture a false survivor.
TARGETS: dict[str, list[str]] = {
    "_merge.py": ["tests/test_merge.py", "tests/test_check.py", "tests/test_provenance.py"],
    "_registry.py": ["tests/test_registries.py", "tests/test_registry_unconfigured.py",
                     "tests/test_mod_scope_is_explicit.py",
                     "tests/test_profile_is_a_decision_log.py"],
    "_compat.py": ["tests/test_compat.py", "tests/test_compat_dropped.py"],
    "_check.py": ["tests/test_check.py", "tests/test_tierb.py",
                  "tests/test_reference_scope.py"],
    "_effective.py": ["tests/test_effective.py", "tests/test_prop_depth.py",
                      "tests/test_effective_scope.py", "tests/test_provenance.py"],
    "_scan.py": ["tests/test_scan.py", "tests/test_corpus_scan.py",
                 "tests/test_no_packed_only_scan.py"],
}


@dataclass
class Mutant:
    target: str       # filename within x4validate/
    name: str
    old: str
    new: str
    why: str          # what a SURVIVOR would mean


#: Each anchor must be UNIQUE in its file, or the probe would mutate the wrong
#: site and report a meaningless result — so a non-unique anchor is itself a fail.
MUTANTS = [
    # --- _merge.py: the diff-application core every other tool trusts ----------
    Mutant("_merge.py", "root-replace payload guard disabled",
           "if len(new_children) != 1:",
           "if len(new_children) != 1 and False:",
           "the multi-payload guard on a root replace is unchecked"),
    Mutant("_merge.py", "ok always True (THE ORIGINAL BUG)",
           "applied.append(AppliedOp(op.tag, sel, line, reason is None,",
           "applied.append(AppliedOp(op.tag, sel, line, True,",
           "a no-op reported as applied and nothing notices"),
    Mutant("_merge.py", "ambiguous-sel guard removed",
           "if len(targets) > 1:",
           "if len(targets) > 99999:",
           "RFC-5261 single-node rule unenforced; ops apply where the engine skips"),
    Mutant("_merge.py", "empty-target guard removed",
           "if not targets:",
           "if not targets and False:",
           "a sel matching nothing would be reported as applied"),
    Mutant("_merge.py", "provenance dropped on root replace",
           'recorder.full_override(Origin(origin.source, "replace-root", origin.line))',
           "pass  # mutant: provenance dropped",
           "values land but origin stays base — the subtle half of the defect"),
    Mutant("_merge.py", "add pos=prepend never taken",
           'if pos == "prepend":',
           'if pos == "__never__":',
           "prepend ordering is unverified"),

    # --- _registry.py: which mods count (CLAUDE.md #24, #30a) ------------------
    Mutant("_registry.py", "profile default inverted (absent means disabled)",
           'return [m for m in installed if m["enabled"] and prof.get(m["id"], True)]',
           'return [m for m in installed if m["enabled"] and prof.get(m["id"], False)]',
           "MEASURED #30a: 54 of 115 installed mods silently vanish from Tier B, "
           "x4compat, x4effective and x4eff at once, and nothing raises"),
    Mutant("_registry.py", "manifest-disabled mods treated as active",
           'return [m for m in installed if m["enabled"] and prof.get(m["id"], True)]',
           'return [m for m in installed if prof.get(m["id"], True)]',
           "a mod disabled in its OWN manifest would be modelled as loaded"),
    Mutant("_registry.py", "scope validation removed",
           "if scope not in MOD_SCOPES:",
           "if scope not in MOD_SCOPES and False:",
           "a mistyped scope would silently choose a behaviour instead of raising"),

    # --- _compat.py: collision semantics (CLAUDE.md #18, F25) -----------------
    Mutant("_compat.py", "live_value_owner names a winner it cannot know",
           'if self.kind in ("SUBTREE", "NAME-CLASH", "SOFT"):',
           'if self.kind in ("SOFT",):',
           "SUBTREE names the WIPER as owner and NAME-CLASH invents one — the "
           "exact conflation CLAUDE.md #18 exists to prevent"),
    Mutant("_compat.py", "NAME-CLASH claims a load-order winner",
           'kind="NAME-CLASH", target=name, mods=folders, winner="",',
           'kind="NAME-CLASH", target=name, mods=folders, winner=folders[0],',
           "index/macros.xml decides a name clash, not load order; naming one is "
           "a guess wearing the grammar of a measurement"),
    # --- _check.py: the bare-vs-nested door (gotcha #6, F19) -------------------
    Mutant("_check.py", "nested-path rewrite disabled",
           "nested = _merge._nested_target(vpath, config.packed_dlc_names())",
           "nested = None  # mutant: mod-on-mod patches lose their target",
           "a cross-mod patch silently no-ops; the engine never opens the bare form"),

    # --- _effective.py: load order and property depth --------------------------
    Mutant("_effective.py", "load order replaced by ALPHABETICAL (gotcha #13)",
           "order = _compat.compute_load_order(mods)",
           'order = sorted(m["folder"] for m in mods)  # mutant: alphabetical',
           "the wrong mod wins: people.capacity reads 0 alphabetically, 200 in true order"),
    Mutant("_effective.py", "property recursion truncated at depth 1",
           "if depth >= MAX_PROP_DEPTH:",
           "if depth >= 1:  # mutant: the whole flight model disappears",
           "9,197 of 13,291 ship attributes vanish and the store still reports success"),

    # --- _scan.py: loose THEN packed (F1, written 7 times) ---------------------
    Mutant("_scan.py", "packed half of iter_mod_xml never entered",
           '    for vpath, member in sorted(_cat.mod_vfs(mod_dir, packed_only=True).items()):\n        if not vpath.lower().endswith(".xml") or vpath.lower() in yielded:\n            continue\n        if predicate is not None and not predicate(vpath):\n            continue\n        try:\n            root = _merge.parse_bytes(_cat.read_member(member))',
           '    for vpath, member in []:  # mutant: packed half never entered\n        if not vpath.lower().endswith(".xml") or vpath.lower() in yielded:\n            continue\n        if predicate is not None and not predicate(vpath):\n            continue\n        try:\n            root = _merge.parse_bytes(_cat.read_member(member))',
           "62% of mod XML invisible; a negative becomes a confident false absence"),
]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def targets_in_play() -> list[str]:
    return sorted({m.target for m in MUTANTS})


def take_pristine() -> None:
    """Copy every target aside BEFORE any mutation, and record that we did."""
    PRISTINE.mkdir(exist_ok=True)
    state = {"pid": os.getpid(), "targets": {}}
    for name in targets_in_play():
        src = PKG / name
        shutil.copy2(src, PRISTINE / name)
        state["targets"][name] = _sha(src)
    MARKER.write_text(json.dumps(state, indent=1), encoding="utf-8")


def restore_all(verify: bool = True) -> list[str]:
    """Put every target back from its pristine copy. Returns what actually differed."""
    changed = []
    for name in targets_in_play():
        src, dst = PRISTINE / name, PKG / name
        if not src.is_file():
            continue
        if not dst.is_file() or _sha(dst) != _sha(src):
            changed.append(name)
        shutil.copy2(src, dst)
        if verify and _sha(dst) != _sha(src):
            raise RuntimeError(f"RESTORE FAILED for {name} - tree is left MUTATED")
    return changed


def clear_marker() -> None:
    MARKER.unlink(missing_ok=True)
    shutil.rmtree(PRISTINE, ignore_errors=True)


def recover() -> int:
    """Explicit recovery. Deliberately NOT automatic.

    Auto-restoring would mean deciding whether the recorded pid is still alive,
    and on Windows `os.kill(pid, 0)` does not mean "probe liveness" - it maps to
    TerminateProcess. Guessing wrong in that direction would either kill a running
    probe or overwrite files underneath it. An explicit flag cannot make that
    mistake, and it forces a human to read what happened rather than skip past it.
    """
    if not MARKER.is_file():
        print("nothing to recover: no .mutation-probe-active marker.")
        return 0
    state = json.loads(MARKER.read_text(encoding="utf-8"))
    print(f"recovering from a probe that did not finish (pid {state.get('pid')}):")
    changed = restore_all()
    for name in targets_in_play():
        mark = "RESTORED (was mutated)" if name in changed else "already clean"
        print(f"  {name:<16} {mark}")
    clear_marker()
    print("tree is clean. Re-run the probe when ready.")
    return 0


#: Verdicts that make the GATE fail. `fail` is absent on purpose: it means the
#: MUTANT died, which is the outcome this gate exists to confirm.
FAILING_VERDICTS = frozenset({"pass", "hang", "noscope"})


def run_tests(tests: list[str]) -> str:
    """'pass' = mutant survived | 'fail' = killed | 'hang' = did not finish
    | 'noscope' = there were no tests to run, which is a NON-ANSWER.

    A missing path is filtered out rather than handed to pytest, which is the
    right thing to DO and was the wrong thing to do SILENTLY (F62): the public
    copy of this gate ran 3 of the 4 `_registry` test files -- the fourth was
    never ported -- and printed the same `killed` line as a full scope.
    """
    present = [t for t in tests if (ROOT / t).exists()]
    missing = [t for t in tests if t not in present]
    if missing:
        print(f"    scope narrowed: {len(present)} of {len(tests)} test file(s) "
              f"present; MISSING {', '.join(missing)}")
    if not present:
        # NOT "hang". Reporting an absence as a timeout asserts a measurement
        # that was never taken -- and the caller then re-runs it as though it
        # were confirming a hang, which cannot resolve a file that is not there.
        return "noscope"
    try:
        p = subprocess.run(["uv", "run", "--project", str(ROOT), "pytest", "-q", *present],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        return "hang"
    return "pass" if p.returncode == 0 else "fail"


def full_suite() -> str:
    return run_tests(["tests"])


def main() -> int:
    if RECOVER:
        return recover()

    if MARKER.is_file():
        print("REFUSING: .mutation-probe-active exists, so either another probe is "
              "running or a previous one died mid-mutation.", file=sys.stderr)
        print("  If no probe is running, the tree may be MUTATED right now. Recover with:",
              file=sys.stderr)
        print("      uv run python gates/mutation_probe.py --recover", file=sys.stderr)
        return 2

    baseline = run_tests(sorted({t for ts in TARGETS.values() for t in ts}))
    if baseline == "noscope":
        print("BASELINE has NO TEST FILES in scope - every path in TARGETS is "
              "missing, so this gate cannot measure anything.", file=sys.stderr)
        return 2
    if baseline == "hang":
        print(f"BASELINE did not finish within {TEST_TIMEOUT}s - fix that first.",
              file=sys.stderr)
        return 2
    if baseline == "fail":
        print("BASELINE IS RED - fix the suite before measuring mutants.", file=sys.stderr)
        return 1

    by_target: dict[str, list] = {}
    for m in MUTANTS:
        by_target.setdefault(m.target, []).append(m)
    print(f"MUTATION PROBE - {len(MUTANTS)} mutants across {len(by_target)} file(s)")
    print("=" * 88)

    survivors, hangs, noscopes = [], [], []
    take_pristine()
    try:
        for target, group in by_target.items():
            path = PKG / target
            original = path.read_text(encoding="utf-8")
            print(f"\n  {target}")
            for m in group:
                n = original.count(m.old)
                if n != 1:
                    print(f"    SKIP   {m.name:<44} anchor appears {n}x (need exactly 1)")
                    survivors.append((m, f"anchor not unique ({n}) - probe cannot aim"))
                    continue
                path.write_text(original.replace(m.old, m.new, 1), encoding="utf-8")
                verdict = run_tests(TARGETS[target])
                if verdict == "hang":
                    # Confirm before reporting. `subprocess.run(timeout=)` counts
                    # WALL CLOCK, so a machine suspend fires it while no CPU time
                    # passed -- MEASURED 2026-08-26 in corpus_sweep, which reported
                    # a 20-minute HANG for a mod that re-ran in 13s. On this machine
                    # the sleep timer counts USER inactivity, and neither the agent's
                    # commands nor CPU load reset it, so any long unattended run can
                    # be interrupted. Same rule as perf_guard (F50) and now
                    # corpus_sweep: a timing that spans a suspend is a NON-ANSWER.
                    verdict = run_tests(TARGETS[target])
                if verdict == "pass":
                    # Scoped tests missed it. Before calling it a survivor, ask the
                    # WHOLE suite - scoping must never manufacture a false survivor.
                    # Same shape as perf_guard's confirm-before-reporting (F50).
                    verdict = full_suite()
                path.write_text(original, encoding="utf-8")
                if verdict == "noscope":
                    # Never challenged, so not a kill. F62 in one line: the public
                    # copy of this gate ran 3 of 4 _registry test files and still
                    # printed `killed`.
                    print(f"    NOSCOPE {m.name:<43} no test file in scope exists")
                    noscopes.append((m, "no test file in this target's scope exists"))
                elif verdict == "hang":
                    print(f"    HUNG   {m.name:<44} exceeded {TEST_TIMEOUT}s")
                    hangs.append((m, f"tests did not finish within {TEST_TIMEOUT}s"))
                elif verdict == "pass":
                    print(f"    LIVED  {m.name:<44} {m.why[:40]}")
                    survivors.append((m, m.why))
                else:
                    print(f"    killed {m.name:<44}")
    finally:
        restore_all()
        clear_marker()

    killed = len(MUTANTS) - len(survivors) - len(hangs) - len(noscopes)
    print("\n" + "=" * 88)
    print(f"killed {killed}/{len(MUTANTS)}   survivors: {len(survivors)}   "
          f"hangs: {len(hangs)}   unmeasured: {len(noscopes)}")
    for m, why in survivors:
        print(f"\n  SURVIVOR: {m.target} - {m.name}")
        print(f"    edit:  {m.old[:66]}")
        print(f"      ->   {m.new[:66]}")
        print(f"    means: {why}")
    for m, why in hangs:
        print(f"\n  HUNG: {m.target} - {m.name}")
        print(f"    means: {why} (a mutant that hangs is a finding, not a pass)")
    for m, why in noscopes:
        print(f"    UNMEASURED: {m.target} - {m.name}")
        print(f"    means: {why}. Nothing was asked of this mutant, so nothing "
              f"was learned - 'could not check' is never 'nothing wrong'.")
    return 1 if (survivors or hangs or noscopes) else 0


if __name__ == "__main__":
    raise SystemExit(main())

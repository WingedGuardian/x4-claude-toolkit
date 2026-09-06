#!/usr/bin/env python3
"""Derive the Track 2 audit population, and REFUSE if a ledger disagrees with it.

The population is derived from `git ls-files` at a named commit -- never typed out, never
recalled. Two figures this repository has already disagreed with itself about:

    all source   217 files / 66,476 lines
    non-test     102 files / 37,894 lines

The second is the one that drifts, because "is this a test?" is a judgement. It is pinned
here: a file is a TEST if it lives under a tests/ directory, or its basename begins
`test_`/`test-`, or it is `verify-hook-tests.py`. `fuzz-guard.py` is NOT a test -- it is an
instrument that ships, and REVIEW-SCOPE.md ranks it under Tier 2.

Usage:
    audit-coverage.py population [--rev REV]        # print the derived population
    audit-coverage.py check LEDGER.tsv [--rev REV]  # refuse unless the ledger reproduces it

Ledger schema, tab-separated:
    path  lines  reviewed_lines  round  method  report
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SOURCE_SUFFIXES = (".py", ".sh", ".lua", ".ps1")
NOT_A_TEST = {"fuzz-guard.py"}
TEST_BASENAMES = {"verify-hook-tests.py"}


def is_test(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    if base in NOT_A_TEST:
        return False
    if path.startswith("tests/") or "/tests/" in path:
        return True
    if base in TEST_BASENAMES:
        return True
    return base.startswith(("test_", "test-"))


def line_count(repo: Path, rev: str, path: str) -> int:
    """Count lines in the COMMITTED blob, not the working tree.

    A working-tree read would silently measure another session's edit. `git show` is the
    only spelling that is about the commit the audit is pinned to.
    """
    blob = subprocess.run(
        ["git", "-C", str(repo), "show", f"{rev}:{path}"],
        capture_output=True,
    )
    if blob.returncode != 0:
        raise SystemExit(f"REFUSING: cannot read {rev}:{path} -- {blob.stderr.decode(errors='replace').strip()}")
    data = blob.stdout
    if not data:
        return 0
    n = data.count(b"\n")
    return n if data.endswith(b"\n") else n + 1


def population(repo: Path, rev: str) -> dict[str, int]:
    listing = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "-z", rev],
        capture_output=True,
        check=True,
    ).stdout
    paths = [p for p in listing.decode("utf-8").split("\0") if p.endswith(SOURCE_SUFFIXES)]
    if not paths:
        raise SystemExit(f"REFUSING: no source files found at {rev} -- an empty population is a non-answer, not a zero")
    return {p: line_count(repo, rev, p) for p in sorted(paths)}


def totals(pop: dict[str, int]) -> dict[str, tuple[int, int]]:
    src = [(p, n) for p, n in pop.items()]
    nt = [(p, n) for p, n in src if not is_test(p)]
    ts = [(p, n) for p, n in src if is_test(p)]
    return {
        "all": (len(src), sum(n for _, n in src)),
        "non-test": (len(nt), sum(n for _, n in nt)),
        "tests": (len(ts), sum(n for _, n in ts)),
    }


METHODS = {"FULL-READ", "PARTIAL", "DIFF-SCOPED", "BEHAVIOURAL", "SWEPT", "NOT-READ"}
COUNTS_AS_READ = {"FULL-READ"}

# A file read in full on 2026-09-02 is not read in full today if it has grown since.
# MEASURED at ed4c24d: 6 of the 11 files a prior report declared read-in-full had
# drifted -- live_query.lua 2,501 -> 2,595, _merge.py 836 -> 974, search-scope.sh
# 79 -> 134. Coverage decays silently, which is the whole reason this column exists.


#: The ledger declares the commit it describes, on a comment line the row reader
#: already skips:  `# pinned-rev: v3.0.0`
#:
#: Without it `check` defaults to HEAD and refuses -- correctly, because the audit
#: has since edited 20 of the files it audited, but for a reason the operator
#: cannot guess from the output. A ledger that cannot say WHEN it was true is an
#: artifact with no freshness fingerprint, which is the defect class this toolkit
#: exists to refuse -- here in its own instrument.
_PINNED = re.compile(r"^#\s*pinned-rev:\s*(\S+)\s*$", re.M)


def pinned_rev(path: Path) -> str | None:
    """The rev this ledger describes, or None if it does not say."""
    m = _PINNED.search(path.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def load_ledger(path: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) != 6:
            raise SystemExit(f"REFUSING: {path}:{lineno} has {len(parts)} fields, expected 6")
        p, lines, reviewed, rnd, method, report = (x.strip() for x in parts)
        if p == "path":
            continue
        if method not in METHODS:
            raise SystemExit(f"REFUSING: {path}:{lineno} method {method!r} is not one of {sorted(METHODS)}")
        if p in rows:
            raise SystemExit(f"REFUSING: {path}:{lineno} duplicate row for {p}")
        if method in COUNTS_AS_READ and reviewed != lines:
            raise SystemExit(
                f"REFUSING: {path}:{lineno} {p} is FULL-READ but {reviewed} of {lines} lines "
                f"were reviewed -- a file that grew after its review is PARTIAL, not read")
        rows[p] = {"lines": lines, "reviewed": reviewed, "round": rnd,
                   "method": method, "report": report}
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["population", "check"])
    ap.add_argument("ledger", nargs="?")
    # No default here: it is resolved below, so an explicit --rev can be told apart
    # from an absent one and the ledger's own pin can win over HEAD.
    ap.add_argument("--rev", default=None)
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()

    repo = Path(args.repo)
    rev = args.rev
    if rev is None and args.ledger:
        rev = pinned_rev(Path(args.ledger))
        if rev:
            print(f"# using the ledger's own pinned rev: {rev}")
    rev = rev or "HEAD"
    pop = population(repo, rev)
    tot = totals(pop)

    if args.command == "population":
        for p, n in pop.items():
            print(f"{n}\t{'TEST' if is_test(p) else 'SRC '}\t{p}")
        print()
        for k, (f, l) in tot.items():
            print(f"{k:10} {f:>4} files {l:>7} lines")
        return 0

    if not args.ledger:
        raise SystemExit("REFUSING: check needs a ledger path")
    rows = load_ledger(Path(args.ledger))

    missing = sorted(set(pop) - set(rows))
    extra = sorted(set(rows) - set(pop))
    if missing:
        print(f"REFUSING: {len(missing)} file(s) in the population are absent from the ledger:")
        for p in missing[:20]:
            print(f"   {p}")
        return 2
    if extra:
        print(f"REFUSING: {len(extra)} ledger row(s) name a file not in the population at {rev}:")
        for p in extra[:20]:
            print(f"   {p}")
        return 2

    drift = [(p, pop[p], rows[p]["lines"]) for p in pop if str(pop[p]) != rows[p]["lines"]]
    if drift:
        print(f"REFUSING: {len(drift)} row(s) carry a line count that is not the one at {rev}:")
        for p, real, claimed in drift[:20]:
            print(f"   {p}: ledger {claimed}, actual {real}")
        return 2

    nt = {p: n for p, n in pop.items() if not is_test(p)}
    read_f = [p for p in nt if rows[p]["method"] in COUNTS_AS_READ]
    read_l = sum(nt[p] for p in read_f)
    part = [p for p in nt if rows[p]["method"] == "PARTIAL"]
    part_l = sum(int(rows[p]["reviewed"] or 0) for p in part)
    ntf, ntl = tot["non-test"]
    print(f"OK  ledger reproduces the population at {rev}")
    print(f"    all source      {tot['all'][0]:>4} files {tot['all'][1]:>7} lines")
    print(f"    non-test        {ntf:>4} files {ntl:>7} lines")
    print(f"    FULL-READ       {len(read_f):>4} files {read_l:>7} lines"
          f"  = {100*len(read_f)//max(ntf,1)}% of files, {100*read_l//max(ntl,1)}% of lines")
    print(f"    PARTIAL         {len(part):>4} files {part_l:>7} lines reviewed (file has since grown, or only a range was read)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

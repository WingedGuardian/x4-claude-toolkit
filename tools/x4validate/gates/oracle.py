"""ORACLE v4 — every mod the engine rejected ops from, packed included.

Uses the tool's OWN iterator (_check.iter_diff_files) so it exercises the same code
path x4validate does. Denominator is the full 453 cardinality failures in the log.
"""
from collections import Counter, defaultdict

import sys

import _env

from x4validate import _check, _debuglog, _merge

EXT = _env.extensions()
LOG = _env.oracle_log()

entries = [e for e in _debuglog.parse_debug(LOG) if e.cardinality]
by_mod = defaultdict(list)
for e in entries:
    by_mod[e.folder].append(e)
print(f"cardinality failures in log: {len(entries)} across {len(by_mod)} mod(s)\n")

tot = Counter()
rows = []
for folder in sorted(by_mod, key=lambda f: -len(by_mod[f])):
    mod_dir = EXT / folder
    if not mod_dir.is_dir():
        rows.append((folder, len(by_mod[folder]), "-", "-", "-", "NOT INSTALLED"))
        continue

    # engine verdicts, keyed (vpath, sel) with the extension resolved via the VFS
    try:
        vfs = {k.lower() for k in _cat_keys(mod_dir)} if False else None
    except Exception:
        vfs = None
    engine = {}
    for e in by_mod[folder]:
        vpath = e.vpath
        for cand in _debuglog.xml_candidates(e.vpath):
            if (mod_dir / cand).is_file():
                vpath = cand
                break
        else:
            # packed: resolve against the catalog VFS
            from x4validate import _cat
            keys = {k.lower(): k for k in _cat.mod_vfs(mod_dir, packed_only=True)}  # packed-ok: loose checked first
            for cand in _debuglog.xml_candidates(e.vpath):
                if cand.lower() in keys:
                    vpath = keys[cand.lower()]
                    break
        engine[(vpath, e.sel)] = e.cardinality

    overlays, _notes = _check.tier_b_overlays(mod_dir)
    cfg = _merge.Config(overlays=tuple(overlays))
    ours = {}
    for vpath, diff_root in _check.iter_diff_files(mod_dir):
        res = _merge.build_effective(vpath, cfg)
        if not res.base_found:
            for op in diff_root:
                if isinstance(op.tag, str) and op.get("sel"):
                    ours[(vpath, op.get("sel"))] = "no-base"
            continue
        for a in _merge.apply_diff(res.tree, diff_root):
            if a.sel:
                ours[(vpath, a.sel)] = ("ambiguous" if a.ambiguous
                                        else "ok" if a.ok else "nomatch")

    agree = sum(1 for k in engine if ours.get(k) not in ("ok", None))
    fok = sum(1 for k in engine if ours.get(k) == "ok")
    unseen = sum(1 for k in engine if k not in ours)
    packed = any(mod_dir.glob("*.cat"))
    rows.append((folder, len(by_mod[folder]), len(engine), agree, fok, unseen,
                 "packed" if packed else "loose"))
    tot["lines"] += len(by_mod[folder])
    tot["ops"] += len(engine)
    tot["agree"] += agree
    tot["false_ok"] += fok
    tot["unseen"] += unseen

print(f"{'mod':<32}{'lines':>6}{'ops':>6}{'agree':>7}{'FALSE OK':>10}{'unseen':>8}  kind")
print("-" * 78)
for r in rows:
    if len(r) == 6:
        print(f"{r[0]:<32}{r[1]:>6}{'':>6}{'':>7}{'':>10}{'':>8}  {r[5]}")
        continue
    f, lines, ops, agree, fok, unseen, kind = r
    flag = "  <== " if fok else ""
    print(f"{f:<32}{lines:>6}{ops:>6}{agree:>7}{fok:>10}{unseen:>8}  {kind}{flag}")

print("-" * 78)
print(f"{'TOTAL':<32}{tot['lines']:>6}{tot['ops']:>6}{tot['agree']:>7}"
      f"{tot['false_ok']:>10}{tot['unseen']:>8}")
# A VERDICT, not just a table. This script computed `false_ok`, printed it with a
# `<==` marker beside the offending row, and ended -- and `run-gates.sh` judges a gate
# purely on its exit code, so it printed `ok oracle` whatever the oracle found. The
# README meanwhile states the gate enforces "234/234 ops agree, 0 FALSE OK".
#
# NOTHING EXAMINED IS REFUSED, NOT PASSED. Over an empty log this printed a table of
# zeroes and exited 0, which reads identically to a clean run. That is the
# could-not-check-reported-as-checked-and-clean shape this toolkit exists to refuse:
# rc 2 is the NON-ANSWER, rc 1 is "there are findings".
if not tot["ops"]:
    print("\nREFUSING: no ops were examined, so there is nothing to agree or disagree "
          "with.\n  This is a NON-ANSWER, not a clean run. Point X4_ORACLE_LOG at a "
          "real engine log.", file=sys.stderr)
    raise SystemExit(2)

print(f"\nagreement: {tot['agree']}/{tot['ops']} = "
      f"{100*tot['agree']//tot['ops']}%   FALSE OK: {tot['false_ok']}   "
      f"unclassified: {tot['unseen']}")
if tot["false_ok"]:
    print(f"\nFAIL: {tot['false_ok']} op(s) the validator called OK and the ENGINE "
          f"did not.\n  A false OK is the one error class this project has no other "
          f"detector for.", file=sys.stderr)
    raise SystemExit(1)

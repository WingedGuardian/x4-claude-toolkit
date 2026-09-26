#!/usr/bin/env python
"""Stress sweep — UNSEEN mods, chained tools, and pathological XML.

The other gates prove the tools survive the corpus they were built against. That
is the happy path wearing a lab coat: same mods, same authoring styles, one tool
at a time. Bugs live where none of that holds.

Three axes, none covered elsewhere:

  1. UNSEEN CORPUS   — point every tool at a directory of mods the toolkit has
     never processed (e.g. an archive of older-era mods). Different authoring
     conventions and an older game version are exactly what a real user's
     download folder looks like.
  2. MULTI-HOP       — chain tools so one's output is the next one's input, and
     run the same mod through several tools. Single-tool tests never exercise
     the seams.
  3. PATHOLOGICAL    — synthesized XML built to break a parser or a merge:
     enormous files, deep nesting, cyclic cross-mod patches, unicode, huge
     selectors, XXE, billion-laughs, zip-bomb-ish payloads.

Every cell is judged against a per-case table of EXPECTED EXIT CODES, not only for
tracebacks (AUDIT-2026-09-24 GT-4, design default): a billion-laughs file that
exits 0 "clean" is as wrong as one that crashes. The table was MEASURED
2026-09-25 (30 cells) and then judged; each set names what counts as an honest
answer for that input. 0 = clean, 1 = findings, 2 = refused, 3 = DEGRADED.

Run:  uv run python gates/stress_sweep.py --corpus=<dir> [--limit=N] [--verbose]
Exit: 0 every cell exited within its expected set, 1 a crash, hang, or an exit
      code outside the set, 2 `--corpus` was given but is not a directory or
      holds no mod (the unseen-corpus axis was ASKED for and cannot run -- it is
      named, never silently dropped).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

VERBOSE = "--verbose" in sys.argv
LIMIT = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), 0)
CORPUS = next((Path(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--corpus=")), None)


def run(argv: list[str], timeout: int = 900, cwd: Path | None = None):
    p = subprocess.run(["uv", "run", "--project", str(ROOT), *argv],
                       cwd=str(cwd or ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def judge(label: str, argv: list[str], expect: frozenset,
          timeout: int = 900) -> tuple[str, str]:
    t0 = time.time()
    try:
        rc, out = run(argv, timeout)
    except subprocess.TimeoutExpired:
        return "FAIL", f"HANG (>{timeout}s)"
    dt = time.time() - t0
    if "Traceback (most recent call last)" in out:
        tail = [ln for ln in out.strip().splitlines() if ln.strip()][-1:]
        return "FAIL", f"traceback: {tail[0][:100] if tail else '?'}"
    if rc not in expect:
        return "FAIL", f"exit {rc}, expected one of {sorted(expect)}, {len(out)}B, {dt:.0f}s"
    return "ok", f"exit {rc}, {len(out)}B, {dt:.0f}s"


_f = frozenset
#: Expected exit codes per pathological mod (both the tier-A and tier-B cell).
#: Unparseable / hostile documents must be REPORTED (1) or DEGRADED (3) -- never a
#: clean 0 over a file nobody could read, and never a refusal (2) of the whole mod.
#: If a parser change makes deep nesting readable, 0 becomes right: change the
#: table deliberately, do not widen it pre-emptively.
PATHOLOGICAL_EXPECT = {
    "path_billion_laughs": _f({1, 3}),
    "path_xxe": _f({1, 3}),
    "path_many_ops": _f({0}),
    "path_deep_nesting": _f({1, 3}),
    "path_evil_selector": _f({1}),            # matches nothing -> a reported error
    "path_unicode": _f({0}),
    "path_empty_file": _f({1, 3}),
    "path_ws_only": _f({1, 3}),
    # MEASURED 0 ("OK: no issues found") for a <diff> element added under <wares>.
    # Not pinned to 1: whether the engine rejects it is unmeasured. Open question.
    "path_nested_diff": _f({0, 1}),
    # A patch at extensions/<not installed>/... is a designed no-op (INFO), clean.
    "path_cycle_a": _f({0}),
    "path_cycle_b": _f({0}),
    "path_large (4x worst real)": _f({0}),
}
#: An unseen real mod: findings and degradation are the tool working; a refusal of a
#: folder that has a content.xml is not.
UNSEEN_EXPECT = _f({0, 1, 3})


# --------------------------------------------------------------------------
# 3. pathological inputs
# --------------------------------------------------------------------------
def build_pathological(tmp: Path) -> list[tuple[str, Path]]:
    """Mods engineered to break a parser or a merge. Each is a real mod dir."""
    made = []

    def mod(name: str, files: dict[str, str]) -> Path:
        d = tmp / name
        (d / "libraries").mkdir(parents=True, exist_ok=True)
        (d / "content.xml").write_text(
            f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<content id="{name}" name="{name}" version="1" />\n', encoding="utf-8")
        for rel, text in files.items():
            f = d / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
        made.append((name, d))
        return d

    # billion laughs — the classic XML entity bomb
    mod("path_billion_laughs", {"libraries/wares.xml":
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        + "".join(f'<!ENTITY lol{i} "&lol{i-1};&lol{i-1};&lol{i-1};">' for i in range(1, 10))
        + ']><diff><add sel="//wares">&lol9;</add></diff>'})

    # XXE — external entity pointing at a local file
    mod("path_xxe", {"libraries/wares.xml":
        '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY xxe SYSTEM "file:///c:/windows/win.ini">]>'
        '<diff><add sel="//wares"><ware id="x" name="&xxe;"/></add></diff>'})

    # 5k sibling ops in one file
    mod("path_many_ops", {"libraries/wares.xml":
        "<diff>" + "".join(
            f'<add sel="//wares"><ware id="stress_{i}" transport="container"/></add>'
            for i in range(5000)) + "</diff>"})

    # 400-deep nesting
    deep = "".join(f"<n{i}>" for i in range(400)) + "".join(f"</n{i}>" for i in reversed(range(400)))
    mod("path_deep_nesting", {"libraries/wares.xml":
        f'<diff><add sel="//wares"><ware id="deep">{deep}</ware></add></diff>'})

    # a selector that is pathological to evaluate
    mod("path_evil_selector", {"libraries/wares.xml":
        '<diff><replace sel="' + "//" * 200 + 'ware/@id">x</replace></diff>'})

    # unicode, RTL overrides, NUL-ish escapes, emoji in ids and values
    mod("path_unicode", {"libraries/wares.xml":
        '<diff><add sel="//wares">'
        '<ware id="\u202eevil\u202d" name="\U0001f600\u0416\u4e2d\u6587" transport="container"/>'
        '</add></diff>'})

    # empty and whitespace-only documents
    mod("path_empty_file", {"libraries/wares.xml": ""})
    mod("path_ws_only", {"libraries/wares.xml": "   \n\t  \n"})

    # a diff whose payload is itself a diff
    mod("path_nested_diff", {"libraries/wares.xml":
        '<diff><add sel="//wares"><diff><replace sel="//x">y</replace></diff></add></diff>'})

    # cyclic cross-mod patches: A patches B, B patches A
    mod("path_cycle_a", {"extensions/path_cycle_b/libraries/wares.xml":
        '<diff><replace sel="//wares/ware[@id=\'ore\']/@transport">liquid</replace></diff>'})
    mod("path_cycle_b", {"extensions/path_cycle_a/libraries/wares.xml":
        '<diff><replace sel="//wares/ware[@id=\'ore\']/@transport">solid</replace></diff>'})

    # A large single file. Sized DELIBERATELY at 4x the worst real file rather
    # than "as big as possible":
    #
    #   apply_diff is O(n^2) in ops-per-file — each op re-evaluates its selector
    #   against a tree the previous ops just grew. Measured 2026-08-08, doubling
    #   the op count multiplies time by 2.8 -> 3.1 -> 3.5 -> 3.7 (linear would be
    #   2.0). At 32k ops in one file it exceeds 900s.
    #
    #   Severity is LOW and that is a measurement, not a hope: the worst file in
    #   a real ~120-mod install is 1,443 ops (~0.03s), so there is ~22x headroom.
    #   A 200k-op file therefore proves nothing except that quadratic is
    #   quadratic, while costing the gate 20 minutes — so this cell characterises
    #   the curve near reality instead of hanging past it.
    big = tmp / "path_large"
    (big / "libraries").mkdir(parents=True, exist_ok=True)
    (big / "content.xml").write_text('<content id="path_large" name="h" version="1"/>',
                                     encoding="utf-8")
    with open(big / "libraries" / "wares.xml", "w", encoding="utf-8") as fh:
        fh.write("<diff>")
        for i in range(6_000):          # ~4x the worst real file
            fh.write(f'<add sel="//wares"><ware id="h{i}" transport="container"/></add>')
        fh.write("</diff>")
    made.append(("path_large (4x worst real)", big))

    return made


def main() -> int:
    fails, cells = [], 0
    tmp = Path(tempfile.mkdtemp(prefix="x4stress_"))
    try:
        # ---- 1. unseen corpus -------------------------------------------
        if CORPUS is not None:
            mods = [d for d in sorted(CORPUS.iterdir())
                    if d.is_dir() and (d / "content.xml").is_file()] if CORPUS.is_dir() else []
            if not mods:
                # Asked for and impossible: say so and stop, rather than running the
                # other two axes and printing a result that never mentions axis 1.
                why = "is not a directory" if not CORPUS.is_dir() else "holds no mod folder"
                print(f"REFUSING: --corpus={CORPUS} {why} (a mod folder has a content.xml), "
                      "so the UNSEEN-CORPUS axis you asked for cannot run.", file=sys.stderr)
                return 2
            if LIMIT:
                mods = mods[:LIMIT]
            print(f"UNSEEN CORPUS — {len(mods)} mods from {CORPUS}\n" + "=" * 84)
            for m in mods:
                for label, argv in (
                    ("validate a", ["x4validate", str(m), "--tier", "a"]),
                    ("validate b", ["x4validate", str(m), "--tier", "b"]),
                    ("stats wares", ["x4stats", "wares", str(m)]),
                    ("compat", ["x4compat", "check", str(m)]),
                ):
                    cells += 1
                    st, detail = judge(f"{m.name} {label}", argv, UNSEEN_EXPECT)
                    if st == "FAIL":
                        fails.append((f"{m.name} :: {label}", detail))
                        print(f"  FAIL {m.name:<38}{label:<12}{detail}")
                    elif VERBOSE:
                        print(f"  ok   {m.name:<38}{label:<12}{detail}")
            print(f"  ...{cells} cells, {len(fails)} failures\n")

        # ---- 3. pathological --------------------------------------------
        print("PATHOLOGICAL INPUTS\n" + "=" * 84)
        for name, d in build_pathological(tmp):
            for label, argv in (("validate", ["x4validate", str(d)]),
                                ("tier b", ["x4validate", str(d), "--tier", "b"])):
                cells += 1
                st, detail = judge(f"{name} {label}", argv, PATHOLOGICAL_EXPECT[name],
                                   timeout=600)
                mark = "FAIL" if st == "FAIL" else "ok  "
                if st == "FAIL":
                    fails.append((f"{name} :: {label}", detail))
                print(f"  {mark} {name:<26}{label:<10}{detail}")

        # ---- 2. multi-hop ------------------------------------------------
        print("\nMULTI-HOP CHAINS\n" + "=" * 84)
        a = tmp / "path_cycle_a"
        b = tmp / "path_cycle_b"
        # (label, argv, expected exit codes) -- MEASURED 2026-09-25, then judged.
        chains = [
            ("diff(unseen pair) -> validate",
             ["x4diff", str(a), str(b)], _f({0, 1})),
            # MEASURED 1 here, while the whole-mod run of the same file is 0 + INFO
            # ("designed no-op"). The two disagree; recorded, not resolved here.
            ("validate --file on a pathological patch",
             ["x4validate", str(a), "--file",
              str(a / "extensions/path_cycle_b/libraries/wares.xml")], _f({0, 1})),
            ("stats macro on a diff (wrong shape on purpose)",
             ["x4stats", "macro", str(a / "extensions/path_cycle_b/libraries/wares.xml")],
             _f({1, 2})),
            ("similar over synthesized mods",
             ["x4similar", "--ext-dir", str(tmp), "--threshold", "0.5"], _f({0})),
            # No candidate = the whole set (`--all` was removed, AUDIT-2026-09-24 AN-7).
            ("compat over the synthesized set",
             ["x4compat", "check", "--ext-dir", str(tmp)], _f({0, 1})),
            ("xref who-calls after a foreign corpus",
             ["x4xref", "who-calls", "find_station"], _f({0})),
        ]
        for label, argv, expect in chains:
            cells += 1
            st, detail = judge(label, argv, expect, timeout=900)
            mark = "FAIL" if st == "FAIL" else "ok  "
            if st == "FAIL":
                fails.append((label, detail))
            print(f"  {mark} {label:<48}{detail}")

        print("=" * 84)
        print(f"{cells} cells   FAILURES: {len(fails)}")
        for label, detail in fails:
            print(f"\n  FAIL {label}\n       {detail}")
        return 1 if fails else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

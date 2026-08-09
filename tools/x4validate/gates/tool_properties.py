#!/usr/bin/env python
r"""Correctness PROPERTIES for the three tools with the thinnest coverage.

Gate coverage was uneven. x4validate had six gates, x4effective three, x4compat
determinism, x4modlist two. `x4diff`, `x4xref` and `x4stats` had only `qa_sweep`
cells — which assert a tool RUNS and prints something, not that what it prints
is TRUE. "Exits 0 with output" is precisely the bar a confidently-wrong tool
clears.

So this gate checks properties that must hold regardless of input, each one
falsifiable and checked against ground truth derived INDEPENDENTLY of the tool
being tested (a fresh lxml parse of the same file, not the tool's own index):

  x4diff   identity      diff(A,A) is empty for every A.
           antisymmetry  diff(A,B).added == diff(B,A).removed, and vice versa.
                         A tool can look right on one direction and still have
                         old/new swapped; only the pair catches that.
  x4xref   citations     every "defined at file:line" it prints must really
                         have that cue at that line. A wrong line silently
                         sends the user to the wrong place.
           completeness  cues found by an independent parse must be in the index
                         — reported WITH a denominator, never as a bare count.
  x4stats  fidelity      every numeric it reports for a macro must equal the
                         value in the file, re-parsed from scratch.

Targets are discovered from the local install; nothing is named.

Run:  uv run python gates/tool_properties.py [--samples=N]
Exit: 0 all properties hold, 1 any violation.
"""
from __future__ import annotations

import random
import re
import subprocess
import sys
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402
from x4validate import _stats, _xref  # noqa: E402

SAMPLES = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--samples=")), 12)
EXT = _env.extensions()
REF = _env.reference()
failures: list[str] = []


def run(tool: str, *argv: str) -> str:
    p = subprocess.run(["uv", "run", tool, *argv], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=1800)
    return (p.stdout or "") + (p.stderr or "")


def note(ok: bool, label: str, detail: str = "") -> None:
    print(f"  {'  ok ' if ok else ' FAIL'}  {label}{('  ' + detail) if detail else ''}")
    if not ok:
        failures.append(f"{label}: {detail}")


def mods(n: int) -> list[Path]:
    """Loose mods with XML, discovered from the install."""
    out = []
    for d in sorted(EXT.iterdir()):
        if not d.is_dir() or d.name.lower().startswith("ego_dlc_"):
            continue
        if any(d.rglob("*.xml")):
            out.append(d)
        if len(out) >= n:
            break
    return out


_COUNTS = re.compile(r"changed files:\s*(\d+)\s+added:\s*(\d+)\s+removed:\s*(\d+)")


def diff_counts(a: Path, b: Path) -> tuple[int, int, int] | None:
    m = _COUNTS.search(run("x4diff", str(a), str(b)))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def check_x4diff() -> None:
    print("\nx4diff")
    targets = mods(SAMPLES)
    for d in targets[:SAMPLES]:
        got = diff_counts(d, d)
        note(got == (0, 0, 0), f"identity  diff({d.name}, itself)", f"counts={got}")
    # antisymmetry over consecutive pairs
    for a, b in zip(targets, targets[1:]):
        fwd, rev = diff_counts(a, b), diff_counts(b, a)
        if fwd is None or rev is None:
            note(False, f"antisymmetry  {a.name} <-> {b.name}", "unparseable output")
            continue
        ok = fwd[1] == rev[2] and fwd[2] == rev[1] and fwd[0] == rev[0]
        note(ok, f"antisymmetry  {a.name} <-> {b.name}", f"{fwd} vs {rev}")


def check_x4xref() -> None:
    print("\nx4xref")
    rows = _xref.read_tsv(_xref._default_tsv())
    # kind is "cuedef" and the path field is `file` — checked against the real
    # vocabulary, not guessed. The first cut guessed both and reported an empty
    # sample; it FAILED rather than passing vacuously, which is the point.
    defined = [r for r in rows if r.kind == "cuedef" and r.file and r.line]
    if not defined:
        note(False, "index has cue definitions", "none found — build the index first")
        return
    print(f"  (index holds {len(rows)} rows, {len(defined)} cue definitions)")

    # -- citations: the file:line it reports must really hold that cue --------
    random.seed(20260809)
    checked = bad = unresolved = 0
    for r in random.sample(defined, min(60, len(defined))):
        base = REF if r.source == "base" else EXT / r.source
        path = base / r.file
        if not path.is_file():
            unresolved += 1          # packed or DLC-owned; not a citation error
            continue
        try:
            tree = etree.parse(str(path))
        except (etree.XMLSyntaxError, OSError):
            unresolved += 1
            continue
        hit = any(el.get("name") == r.name and el.sourceline == r.line
                  for el in tree.iter("cue"))
        checked += 1
        if not hit:
            bad += 1
            if bad <= 3:
                print(f"          mis-cited: {r.name} claimed at {r.file}:{r.line}")
    note(bad == 0, "citations resolve to the exact line",
         f"{checked - bad}/{checked} exact ({unresolved} not loose-resolvable)")

    # -- completeness, WITH a denominator ------------------------------------
    indexed = {(r.name, r.file) for r in defined}
    truth, missing = 0, []
    for vpath in ("md/encounters.xml", "md/npc_missions.xml", "md/signal_leaks.xml"):
        path = REF / vpath
        if not path.is_file():
            continue
        for el in etree.parse(str(path)).iter("cue"):
            name = el.get("name")
            if not name:
                continue
            truth += 1
            if (name, vpath) not in indexed:
                missing.append(f"{vpath}:{name}")
    note(not missing, "independently-parsed cues are all indexed",
         f"{truth - len(missing)}/{truth} found"
         + (f"; missing e.g. {missing[:2]}" if missing else ""))


def check_x4stats() -> None:
    print("\nx4stats")
    macros = []
    for sub in ("assets/props/SurfaceElements/macros", "assets/props/engines/macros"):
        d = REF / sub
        if d.is_dir():
            macros += sorted(d.glob("*_macro.xml"))[:SAMPLES]
    if not macros:
        note(False, "found macros to sample", "none under reference/")
        return

    total = mismatched = 0
    for path in macros[:SAMPLES]:
        reported = _stats.macro_stats(path)
        if not reported:
            continue
        # Ground truth: re-parse from scratch, walking the properties tree
        # ourselves rather than reusing the tool's own flattener.
        root = etree.parse(str(path)).getroot()
        macro = next(iter(root.iter("macro")), None)
        if macro is None:
            continue
        truth: dict[str, str] = {}
        for el in macro.iter():
            if el is macro or not isinstance(el.tag, str):
                continue
            for k, v in el.attrib.items():
                truth.setdefault(f"{el.tag}.{k}", v)
        for prop, value in reported.items():
            if prop == "class" or prop not in truth:
                continue
            total += 1
            want = truth[prop]
            try:
                same = abs(float(value) - float(want)) < 1e-9
            except (TypeError, ValueError):
                same = str(value) == want
            if not same:
                mismatched += 1
                if mismatched <= 3:
                    print(f"          {path.name} {prop}: reported {value!r}, file says {want!r}")
    note(mismatched == 0, "reported numbers match a fresh parse of the file",
         f"{total - mismatched}/{total} values agree")


def main() -> int:
    print("=" * 88)
    print("TOOL PROPERTIES — x4diff / x4xref / x4stats, checked against independent truth")
    print("=" * 88)
    check_x4diff()
    check_x4xref()
    check_x4stats()
    print("\n" + "=" * 88)
    if failures:
        print(f"PROPERTY VIOLATIONS: {len(failures)}")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All properties hold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

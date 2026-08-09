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
  x4compat soundness     every mod named in a collision must really ship that
                         vpath, and the winner must be one of them. A conflict
                         detector that invents a conflict is as bad as one that
                         misses it.
           completeness  a shared FULL-FILE path is either reported or a known
                         non-override class (per-mod manifest, union-merged
                         registry). NOT "any shared vpath must collide" -- two
                         diffs on disjoint nodes legitimately do not.
  x4similar monotonicity results at a LOWER threshold must be a superset of
                         those at a higher one. A scoring bug breaks this even
                         when every individual run looks plausible.

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
from x4validate import _cat, _compat, _merge, _stats, _xref  # noqa: E402

SAMPLES = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--samples=")), 12)
EXT = _env.extensions()
REF = _env.reference()
failures: list[str] = []
#: Files `_is_full_file` could not read. Reported, never silently dropped.
_UNREADABLE: list[str] = []


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


def _ships_vpath(mod: Path) -> set[str]:
    """Every XML vpath a mod ships, loose or packed — computed WITHOUT using
    x4compat's own path helper, so it is genuinely independent evidence."""
    out = {p.relative_to(mod).as_posix().lower()
           for p in mod.rglob("*.xml") if p.is_file()}
    try:
        out |= {v.lower() for v in _cat.mod_vfs(mod)}
    except OSError:
        pass  # silent-ok: an unreadable archive shrinks this mod's evidence set;
              # the soundness check below reports any vpath it then cannot back up
    return out


def _is_full_file(mod: Path, vpath: str) -> bool:
    """True when the mod ships *vpath* as a whole-file override, not a <diff>.

    Read independently of x4compat (fresh parse / raw catalog read).
    """
    p = mod / vpath
    try:
        if p.is_file():
            return etree.parse(str(p)).getroot().tag != "diff"
        data = _cat.read_path(mod, vpath)
        if data is None:
            return False
        return etree.fromstring(data).tag != "diff"
    except (etree.XMLSyntaxError, OSError, ValueError) as exc:
        # Counted, not swallowed. Returning False quietly would shrink the
        # completeness denominator with nothing said — the shape that turns a
        # missed override into "all clear". The count is printed with the result.
        _UNREADABLE.append(f"{mod.name}/{vpath}: {exc}")
        return False


def check_x4compat() -> None:
    print("\nx4compat")
    report = _compat.analyze(EXT, config=_merge.Config())
    if not report.collisions:
        note(False, "produced collisions to check", "none found on this install")
        return
    print(f"  ({report.mods_scanned} mods scanned, {len(report.collisions)} collisions)")

    owns: dict[str, set[str]] = {}
    unsound = winnerless = 0
    for c in report.collisions:
        for folder in c.mods:
            d = EXT / folder
            if folder not in owns:
                owns[folder] = _ships_vpath(d) if d.is_dir() else set()
            v = c.vpath.lower()
            # A cross-mod patch's vpath is the TARGET's path, `extensions/<target>/<rel>`.
            # The target itself ships plain `<rel>`; only the patching mod ships the
            # nested form. Comparing literally called that unsound -- the property was
            # wrong, not the tool. Accept either spelling for this mod.
            nested = f"extensions/{folder.lower()}/"
            candidates = {v, v[len(nested):]} if v.startswith(nested) else {v}
            if not (candidates & owns[folder]):
                unsound += 1
                if unsound <= 3:
                    print(f"          unsound: {folder} named for {c.vpath}, but does not ship it")
        if c.winner not in c.mods:
            winnerless += 1
            if winnerless <= 3:
                print(f"          winner {c.winner!r} not among {c.mods}")
    note(unsound == 0, "every named mod really ships the colliding vpath",
         f"{len(report.collisions)} collisions checked")
    note(winnerless == 0, "winner is always one of the involved mods",
         f"{len(report.collisions)} checked")

    # Completeness -- stated as something actually TRUE, after three attempts at
    # it were each too strong and each blamed the tool for being RIGHT:
    #
    #   1. "two mods ship the same vpath => must collide" is false: two <diff>s
    #      touching disjoint nodes do not conflict (107 of 392 shared paths here).
    #   2. "...as a full file => must collide" is false for MANIFESTS: content.xml
    #      and ui.xml are per-mod declarations, not game content, and neither
    #      exists in reference/.
    #   3. ...and false for UNION-MERGED registries: shipping a whole
    #      libraries/loadouts.xml is a CONTRIBUTION, not an override. Only a
    #      same-id clash is a conflict, which is what x4compat's UNION-KEY kind
    #      already models.
    #
    # So the check is: a shared full-file path must be either REPORTED or a
    # known non-override class. A path in neither bucket fails, which keeps this
    # falsifiable -- a genuinely missed override still trips it.
    manifests = {"content.xml", "ui.xml"}
    union_merged = {"libraries/camerasettings.xml", "libraries/loadouts.xml",
                    "libraries/region_definitions.xml", "libraries/wares.xml",
                    "libraries/jobs.xml"}
    full: dict[str, list[str]] = {}
    for d in sorted(EXT.iterdir()):
        if not d.is_dir() or d.name.lower().startswith("ego_dlc_"):
            continue
        for v in _ships_vpath(d):
            if v.endswith(".xml") and not v.startswith("extensions/") and _is_full_file(d, v):
                full.setdefault(v, []).append(d.name)
    shared_full = {v for v, m in full.items() if len(m) > 1}
    reported = {c.vpath.lower() for c in report.collisions}
    unexplained = sorted(shared_full - reported - manifests - union_merged)
    note(not unexplained, "shared full-file paths are reported or a known non-override class",
         f"{len(shared_full)} shared; {len(shared_full & reported)} reported, "
         f"{len(shared_full & (manifests | union_merged))} manifest/union-merged, "
         f"{len(unexplained)} unexplained"
         + (f"; e.g. {unexplained[:2]}" if unexplained else ""))
    if _UNREADABLE:
        print(f"          note: {len(_UNREADABLE)} file(s) unreadable, excluded from the "
              f"denominator — e.g. {_UNREADABLE[0][:90]}")


_SIM_PAIR = re.compile(r"^\s*([\w./-]+)\s+.*?([\w./-]+)\s*$")


def check_x4similar() -> None:
    print("\nx4similar")
    loose = run("x4similar", "--threshold", "0.80")
    tight = run("x4similar", "--threshold", "0.95")

    def pairs(text: str) -> set[str]:
        # Identity-bearing lines only; the exact render is not the property.
        return {ln.strip() for ln in text.splitlines()
                if "_macro" in ln and "<->" in ln or " vs " in ln}

    lo, hi = pairs(loose), pairs(tight)
    note(hi <= lo, "0.95 results are a subset of 0.80 results",
         f"loose={len(lo)} tight={len(hi)} extra_in_tight={len(hi - lo)}")
    note("Traceback" not in loose and "Traceback" not in tight,
         "no crash at either threshold")


def main() -> int:
    print("=" * 88)
    print("TOOL PROPERTIES — x4diff / x4xref / x4stats, checked against independent truth")
    print("=" * 88)
    check_x4diff()
    check_x4xref()
    check_x4stats()
    check_x4compat()
    check_x4similar()
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

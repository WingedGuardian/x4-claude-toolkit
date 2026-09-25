r"""LOAD ORDER ORACLE — does `compute_load_order` agree with the order the ENGINE used?

WHY THIS EXISTS. `_loadorder.compute_load_order` decides the winner of every collision
between mods (x4compat, x4effective, x4stats, Tier B). Until 2026-09-24 nothing ever
compared it with the engine: every test and the #13 mutant compared the code with
itself. MEASURED that day on a 125-mod install, the order the code produced agreed with
the engine at 0 of 23 first-pass positions (AUDIT-2026-09-24 LO-1).

THE EVIDENCE IT READS. At startup and while loading, the engine checks the signature of
every extension file it opens, and an unsigned mod file logs

    [FileIO ] 0.00 File I/O: Failed to verify the file signature for file
              '.\extensions\<folder>\<relative path>' (error: 14)

For every relative path (a "file class" -- `libraries/wares.xml`, `t/0001-l044.xml`, ...)
the ORDER in which different mods' copies are checked is the order the engine walked the
extensions for that file. Each class shipped by two or more mods yields ordered pairs;
this gate counts the pairs the computed order INVERTS. It does not assume which rule the
engine uses -- it scores whatever `compute_load_order` returns.

SCOPE, stated so a pass is not read as more than it is:
  * Only mods that ship at least one unsigned file appear (in practice: every mod).
  * Only the relative order of mods that SHARE a file class is tested; two mods that
    never ship the same path are never compared. The denominator (pairs, classes,
    mods covered) is printed on every run.
  * The log describes the modlist AT THAT LAUNCH. If a mod was added, removed or had its
    dependencies changed since, an inversion may be the log's age rather than the code;
    the gate then refuses (rc 2) instead of blaming the code.

INPUT: `$X4_ORACLE_LOG` (a pinned capture) if set, else the live profile debug.txt.

Exit: 0 no inversions over >= 1 comparable class · 1 inversions · 2 cannot judge
(no log, nothing comparable, or a log older than the modlist it would be judged against).
"""
from __future__ import annotations

import collections
import sys
from dataclasses import dataclass, field
from pathlib import Path

import _env  # noqa: F401  (puts the package on sys.path)

from x4validate import _loadorder, _paths, _registry

BS = "\\"
MARKER = "Failed to verify the file signature for file"
PREFIX = "." + BS + "extensions" + BS


def parse_sequences(lines) -> dict[str, list[str]]:
    r"""{relative path (lowercase, '/') : [folder (lowercase), in first-checked order]}.

    Nested paths (`extensions\a\extensions\b\...`) are a mod patching another mod's
    file; the folder that OWNS the checked copy is `a`, and the class key keeps the
    nested remainder, so they never mix with the plain class of the same name.
    """
    seqs: dict[str, list[str]] = collections.defaultdict(list)
    for line in lines:
        if MARKER not in line:
            continue
        a = line.find(PREFIX)
        if a < 0:
            continue
        rest = line[a + len(PREFIX):]
        q = rest.find("'")
        if q >= 0:
            rest = rest[:q]
        folder, sep, rel = rest.partition(BS)
        if not sep or not folder or not rel:
            continue
        folder = folder.lower()
        rel = rel.lower().replace(BS, "/")
        if folder not in seqs[rel]:
            seqs[rel].append(folder)
    return dict(seqs)


@dataclass
class Score:
    classes: int = 0                  # classes with >= 2 comparable mods
    pairs: int = 0                    # ordered pairs compared
    inversions: int = 0
    mods_covered: set = field(default_factory=set)
    unknown_folders: set = field(default_factory=set)   # in the log, not in the order
    bad: list = field(default_factory=list)             # (class, n, inversions, seq)


def score(order: list[str], seqs: dict[str, list[str]]) -> Score:
    pos = {f.lower(): i for i, f in enumerate(order)}
    s = Score()
    for rel, seq in seqs.items():
        s.unknown_folders.update(f for f in seq if f not in pos)
        known = [f for f in seq if f in pos]
        if len(known) < 2:
            continue
        s.classes += 1
        s.mods_covered.update(known)
        inv = 0
        for i in range(len(known)):
            for j in range(i + 1, len(known)):
                s.pairs += 1
                if pos[known[i]] > pos[known[j]]:
                    inv += 1
        if inv:
            s.inversions += inv
            s.bad.append((rel, len(known), inv, known))
    s.bad.sort(key=lambda b: -b[2])
    return s


def _log_path() -> Path | None:
    raw = _paths._resolve(lambda layer: _paths._pick(layer, "X4_ORACLE_LOG"))
    if raw:
        return Path(raw)
    return _paths.debug_log()


def _newest_manifest(mods: list[dict]) -> tuple[float, str]:
    newest, who = 0.0, ""
    for m in mods:
        cx = Path(m["path"]) / "content.xml"
        try:
            t = cx.stat().st_mtime
        except OSError:
            continue
        if t > newest:
            newest, who = t, m["folder"]
    return newest, who


def main() -> int:
    log = _log_path()
    if log is None or not log.is_file():
        print(f"SKIP: no debug log to judge against (resolved to {log or 'nothing'})\n"
              "      launch X4 once with the modlist active, or set $X4_ORACLE_LOG",
              file=sys.stderr)
        return 2
    mods = _registry.mods("active")
    if not mods:
        print("SKIP: the active mod set is empty -- nothing to order", file=sys.stderr)
        return 2
    order = _loadorder.compute_load_order(mods)
    with log.open(encoding="utf-8", errors="replace") as fh:
        seqs = parse_sequences(fh)
    s = score(order, seqs)

    print(f"log: {log}")
    print(f"active mods: {len(order)}   in the log: {len(s.mods_covered)} compared "
          f"(+{len(s.unknown_folders)} logged folder(s) not in the active set)")
    print(f"file classes compared: {s.classes}   ordered pairs: {s.pairs}   "
          f"inverted by compute_load_order: {s.inversions}")
    if s.classes == 0:
        print("SKIP: no file class is shipped by two or more active mods in this log, so "
              "nothing about the order can be judged", file=sys.stderr)
        return 2
    if s.inversions == 0:
        print("PASS: the computed order agrees with every engine-checked pair above")
        return 0
    for rel, n, inv, seq in s.bad[:10]:
        print(f"  {rel}  mods={n}  inverted pairs={inv}  engine order: {', '.join(seq[:8])}"
              + (" ..." if len(seq) > 8 else ""))
    # A log that describes a DIFFERENT modlist cannot convict the code. Two signals,
    # because either alone misses a case: a manifest mtime is preserved when a mod is
    # copied in, so a mod added after the launch can look older than the log; and the
    # membership difference misses a dependency edit inside an unchanged folder set.
    newest, who = _newest_manifest(mods)
    logged = {f for seq in seqs.values() for f in seq}
    active = {f.lower() for f in order}
    drift = sorted(logged - active) + sorted(active - logged)
    if newest > log.stat().st_mtime or s.unknown_folders:
        why = (f"a manifest changed after the log was written ({who})"
               if newest > log.stat().st_mtime else
               f"{len(s.unknown_folders)} logged folder(s) are not active now "
               f"(e.g. {', '.join(sorted(s.unknown_folders)[:3])})")
        print(f"CANNOT JUDGE: {why}, so these inversions may be the log's age, not the "
              "code. Launch the game once with the current modlist and re-run.",
              file=sys.stderr)
        return 2
    if drift:
        print(f"note: {len(active - logged)} active mod(s) never appear in the log "
              "(nothing unsigned was checked for them); they are simply not compared")
    print(f"FAIL: {s.inversions} of {s.pairs} engine-ordered pairs are inverted by "
          "compute_load_order -- every collision winner between those mods is suspect")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

r"""x4stats similar-ships: fuzzy same-entity detection across ships.

D2 (`x4compat`) already catches the case where two mods define the SAME registry
key (e.g. two mods both shipping a macro named ``ship_vro_argon_heavy``) — that's a
UNION-KEY collision, unambiguous. This module catches the harder, fuzzier case: two
DIFFERENT ids/macro names that describe essentially the same ship (VRO adds a
rebalanced ship; an unrelated "independent" mod adds a stat-alike ship under its own
name). There is no bright line here — this is advisory, threshold-tuned, and meant to
flag candidates for a human look, not to assert equivalence.

Comparison is scoped HARD by macro ``class`` (ship_xs/s/m/l/xl) and ``purpose.primary``
(fight/trade/mine/...) — an S fighter is never "similar" to an XL destroyer regardless
of how the numbers line up, so cross-class/purpose pairs are never scored.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from x4validate import _paths, _cat, _merge, _scan, _stats, _input
from x4validate import __version__

# Numeric keys compared, with weights (a rough "how much does this stat define the
# ship's role/tier" prior) — hull/cargo/crew dominate; handling stats are secondary.
_WEIGHTS = {
    "hull.max": 2.0,
    "people.capacity": 1.5,
    "storage.missile": 0.5,
    "storage.unit": 1.0,
    "cargo.max": 1.5,
    "rotationspeed.max": 0.75,
    "rotationacceleration.max": 0.5,
    "secrecy.level": 0.25,
}


@dataclass
class ShipVector:
    macro_name: str
    source: str        # base | dlc:<name> | <mod folder>
    vpath: str
    ship_class: str     # ship_s / ship_m / ...
    purpose: str
    #: The SCORED subset — keys in `_WEIGHTS` only. Changing this changes scores.
    stats: dict[str, float] = field(default_factory=dict)
    #: EVERY numeric axis the macro exposes, a superset of `stats`. Reporting
    #: only; never fed to `similarity()`. MEASURED: a ship macro exposes 34
    #: numeric axes and only 5 are scored — the unscored remainder is the whole
    #: flight model (physics.drag.*, physics.inertia.*, jerk.*, steeringcurve.*),
    #: which was 0 rows anywhere until the depth-1 flatten was fixed 2026-08-12.
    all_stats: dict[str, float] = field(default_factory=dict)


@dataclass
class SimilarPair:
    a: ShipVector
    b: ShipVector
    score: float           # 0..1, 1 = identical on every compared key
    compared_keys: list[str]


@dataclass
class AxisDifference:
    key: str
    a_value: float
    b_value: float
    rel_diff: float        # |a-b| / max(|a|,|b|), so 0.5 = "one is half the other"


@dataclass
class DifferenceProfile:
    """HOW two near-duplicate ships differ, across EVERY numeric axis.

    The score answers *"are these the same ship?"* on 8 weighted keys. This
    answers the follow-up — *"if not, where?"* — and deliberately covers axes the
    score ignores, because that is where near-duplicates actually diverge.

    MEASURED over the 816 pairs the tool reports at its default threshold: only
    **35** are identical on every shared axis. The rest differ, most often on
    `physics.drag.forward` (624 pairs), `physics.mass` (514) and
    `physics.inertia.pitch`/`yaw` (497 each) — none of which are scored.
    """
    identical: list[str] = field(default_factory=list)
    differing: list[AxisDifference] = field(default_factory=list)
    #: Axes one ship has and the other does not. This IS a difference; dropping
    #: it by intersecting the key sets would be the narrowing shape again.
    only_in_a: list[str] = field(default_factory=list)
    only_in_b: list[str] = field(default_factory=list)


def difference_profile(a: ShipVector, b: ShipVector,
                       epsilon: float = 1e-9) -> DifferenceProfile:
    """Per-axis comparison of two ships over the union of their numeric axes."""
    prof = DifferenceProfile()
    for key in sorted(set(a.all_stats) | set(b.all_stats)):
        in_a, in_b = key in a.all_stats, key in b.all_stats
        if not in_b:
            prof.only_in_a.append(key)
            continue
        if not in_a:
            prof.only_in_b.append(key)
            continue
        va, vb = a.all_stats[key], b.all_stats[key]
        rel = abs(va - vb) / max(abs(va), abs(vb), epsilon)
        if rel <= epsilon:
            prof.identical.append(key)
        else:
            prof.differing.append(AxisDifference(key, va, vb, rel))
    prof.differing.sort(key=lambda d: (-d.rel_diff, d.key))
    return prof


def extract_ship_vector(root: etree._Element, source: str, vpath: str) -> ShipVector | None:
    macro = root.find("macro") if root.tag != "macro" else root
    if macro is None or not (macro.get("class") or "").startswith("ship_"):
        return None
    props = macro.find("properties")
    if props is None:
        return None
    flat = _stats.flatten_macro_props(root)
    purpose_el = props.find("purpose")
    purpose = purpose_el.get("primary", "") if purpose_el is not None else ""
    numeric = {k: v for k, v in flat.items() if isinstance(v, float)}
    stats = {k: v for k, v in numeric.items() if k in _WEIGHTS}
    return ShipVector(
        macro_name=macro.get("name", ""), source=source, vpath=vpath,
        ship_class=macro.get("class", ""), purpose=purpose, stats=stats,
        all_stats=numeric,
    )


def _iter_ship_macros(base: Path, source: str, script_dirs=("assets/units/",),
                      unreadable: list | None = None):
    """Yield (vpath, root) for every *_macro.xml under assets/units/ (loose + packed)."""
    yield from _scan.iter_mod_xml(
        base, _scan.all_of(_scan.under(*script_dirs), _scan.ending("_macro.xml")), unreadable)


def collect_ship_vectors(base: Path, source: str,
                         unreadable: list | None = None) -> list[ShipVector]:
    out = []
    for vpath, root in _iter_ship_macros(base, source, unreadable=unreadable):
        v = extract_ship_vector(root, source, vpath)
        if v is not None:
            out.append(v)
    return out


def similarity(a: ShipVector, b: ShipVector) -> SimilarPair | None:
    """Weighted normalized similarity in [0,1], or None if not comparable.

    Not comparable: different class, different purpose, or fewer than 4 shared
    numeric keys. (Empirically, 3-key matches on this stat set are frequently
    coincidental — e.g. a combat drone and a scout can share hull/crew=0/secrecy
    purely by chance; 4+ keys covers ~98% of real matches and drops that noise.)
    Score = 1 - weighted mean of per-key relative differences (each capped at 1.0,
    so one wildly-off stat can't push the score negative).
    """
    if a.ship_class != b.ship_class or a.purpose != b.purpose:
        return None
    shared = sorted(set(a.stats) & set(b.stats))
    if len(shared) < 4:
        return None
    total_w = 0.0
    total_diff = 0.0
    for k in shared:
        w = _WEIGHTS.get(k, 1.0)
        va, vb = a.stats[k], b.stats[k]
        denom = max(abs(va), abs(vb), 1e-9)
        rel_diff = min(abs(va - vb) / denom, 1.0)
        total_diff += w * rel_diff
        total_w += w
    score = 1.0 - (total_diff / total_w if total_w else 1.0)
    return SimilarPair(a=a, b=b, score=score, compared_keys=shared)


def find_similar(vectors: list[ShipVector], threshold: float = 0.85,
                 exclude_same_source: bool = False) -> list[SimilarPair]:
    """All pairs scoring >= threshold, sorted highest-first.

    *exclude_same_source* drops pairs from the same mod/source (e.g. a_mod's own
    01_a/01_b paint variants) — useful when hunting for CROSS-mod redundancy only.
    """
    pairs = []
    for i, a in enumerate(vectors):
        for b in vectors[i + 1:]:
            if a.macro_name == b.macro_name:
                continue  # identical id -> D2's UNION-KEY territory, not this tool's job
            if exclude_same_source and a.source == b.source:
                continue
            pair = similarity(a, b)
            if pair is not None and pair.score >= threshold:
                pairs.append(pair)
    return sorted(pairs, key=lambda p: -p.score)


# --- CLI ----------------------------------------------------------------------

def _collect_all(reference: Path, ext_dir: Path,
                 unreadable: list | None = None,
                 dlc_dirs: list[Path] | None = None) -> list[ShipVector]:
    from x4validate import _merge, _registry
    vectors = collect_ship_vectors(reference, "base", unreadable)
    # Ask Config rather than walking `reference / "extensions"`: the packed
    # mini-DLC are not unpacked there, and skipping them hid 3 real ships --
    # the Hyperion (ship_par_l_expeditionary_01_a_macro) and 2 Envoy corvettes --
    # from a tool whose whole question is "is this a duplicate of one I own?".
    if dlc_dirs is None:
        dlc_dirs = _merge.Config(reference=reference).dlc_dirs()
    for dlc in sorted(dlc_dirs, key=lambda p: p.name):
        vectors += collect_ship_vectors(dlc, f"dlc:{dlc.name}", unreadable)
    if ext_dir.is_dir():
        # INSTALLED: "is this ship a near-duplicate of one I own?" is about
        # ownership, not load state -- a disabled ship pack is still a duplicate.
        for m in _registry.mods("installed", [ext_dir]):
            vectors += collect_ship_vectors(Path(m["path"]), m["folder"], unreadable)
    return vectors


def render(pairs: list[SimilarPair]) -> str:
    if not pairs:
        return "no near-duplicate ships found at this threshold."
    lines = [f"{len(pairs)} possibly-redundant ship pair(s) "
             "(advisory — same class+purpose, close stats; verify by eye):\n"]
    for p in pairs:
        lines.append(f"  {p.score*100:.0f}%  ({len(p.compared_keys)} stats compared)  "
                     f"{p.a.macro_name} [{p.a.source}]  <->  {p.b.macro_name} [{p.b.source}]")
        lines.append(f"        class={p.a.ship_class} purpose={p.a.purpose} "
                     f"compared={','.join(p.compared_keys)}")
        # A THIRD line, deliberately. `gates/similar_audit.py` matches the score
        # row and then reads the NEXT line for class/purpose/compared; appending
        # rather than altering keeps that exhaustive audit resolving every pair.
        lines.append("        " + summarise_profile(difference_profile(p.a, p.b)))
    return "\n".join(lines)


#: How many differing axes to name inline. The full list is available from
#: `difference_profile`; the renderer is a summary, and a pair can differ on
#: dozens of axes (34 numeric axes exist on a ship macro).
PROFILE_TOP_N = 4


def summarise_profile(prof: DifferenceProfile, top_n: int = PROFILE_TOP_N) -> str:
    """One-line answer to 'is it different, and if so how?'."""
    if not prof.differing and not prof.only_in_a and not prof.only_in_b:
        return f"IDENTICAL on all {len(prof.identical)} shared numeric axes"
    parts = [f"same on {len(prof.identical)}",
             f"differs on {len(prof.differing)}"]
    if prof.only_in_a or prof.only_in_b:
        parts.append(f"{len(prof.only_in_a) + len(prof.only_in_b)} axis/axes on one ship only")
    head = "; ".join(parts)
    if not prof.differing:
        return head
    # `:.3g`, not `:.0f`: a real 0.5% difference printed as "(0%)" next to the
    # word "differs" reads as a contradiction, and an output the reader learns to
    # distrust is worse than no output.
    top = ", ".join(f"{d.key} {d.a_value:g}->{d.b_value:g} ({d.rel_diff*100:.3g}%)"
                    for d in prof.differing[:top_n])
    more = "" if len(prof.differing) <= top_n else f", +{len(prof.differing) - top_n} more"
    return f"{head} — biggest: {top}{more}"


def _threshold(raw: str) -> float:
    """A similarity score is a ratio; anything outside 0-1 is a typo, not a setting.

    Unvalidated, `--threshold -1` matched every pair against every other and
    emitted 1.7 MB of "findings" that mean nothing.
    """
    import argparse
    try:
        val = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {raw!r}")
    if not 0.0 <= val <= 1.0:
        raise argparse.ArgumentTypeError(
            f"similarity is a ratio: expected 0-1, got {val:g}")
    return val


@_paths.refuses_unconfigured
def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # silent-ok: console encoding shim. Failure means the default codec
        # stays; it affects how output LOOKS, never what was examined.

    from x4validate import _registry

    p = argparse.ArgumentParser(
        prog="x4similar",
        description="Advisory fuzzy same-ship detection across base+DLC+installed mods.")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    p.add_argument("--reference", help="unpacked base+DLC tree ($X4_REFERENCE)")
    p.add_argument("--ext-dir", help="extensions dir (default: game-root from _registry)")
    p.add_argument("--threshold", type=_threshold, default=0.85,
                  help="minimum similarity 0-1 to report (default 0.85)")
    p.add_argument("--cross-mod-only", action="store_true",
                  help="only report pairs from DIFFERENT sources (skip a mod's own paint variants)")
    p.add_argument("--candidate", help="restrict to pairs involving this mod folder")

    args = p.parse_args(argv)
    ref = Path(args.reference) if args.reference else _merge.Config().reference
    ext = Path(args.ext_dir) if args.ext_dir else _registry.require(
        _registry.GAME_EXTENSIONS, "the game extensions dir",
        "set X4_GAME (or X4_EXTENSIONS), or pass --ext-dir")

    unreadable: list = []
    vectors = _collect_all(ref, ext, unreadable)
    pairs = find_similar(vectors, threshold=args.threshold,
                         exclude_same_source=args.cross_mod_only)
    if args.candidate:
        # --candidate is a SOURCE NAME (mod folder), not a path. A value that
        # matches no scanned source used to filter every pair away and print
        # "no near-duplicate ships found" — a clean negative produced by a typo.
        # Accept a path too, and refuse to answer if it names nothing we scanned.
        cand = Path(args.candidate).name if ("/" in args.candidate or "\\" in args.candidate) \
            else args.candidate
        sources = {v.source for v in vectors}
        if cand not in sources:
            print(f"error: --candidate '{args.candidate}' matches none of the "
                  f"{len(sources)} scanned sources.", file=sys.stderr)
            print("       (a 'no near-duplicates' answer here would be about an "
                  "empty filter, not about your mod)", file=sys.stderr)
            return 2
        pairs = [p for p in pairs if cand in (p.a.source, p.b.source)]
    print(f"scanned {len(vectors)} ship macros.\n")
    print(render(pairs))
    if unreadable:
        # "No near-duplicates" is a negative, and a negative needs its denominator.
        print(f"\n  NOT COMPARED — {len(unreadable)} macro file(s) would not parse:",
              file=sys.stderr)
        for u in unreadable:
            print(f"   - {u}", file=sys.stderr)
    return 0

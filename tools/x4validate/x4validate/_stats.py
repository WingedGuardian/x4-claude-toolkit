r"""x4stats: advisory numeric comparison of a mod's content against the effective game.

The hardest interaction question — "is this mod BALANCED for my game (e.g. a VRO
overhaul)?" — is a judgment call, not a computation: VRO rescales values without
producing any file/node collision, so a vanilla-balanced weapon mod applies cleanly
yet may be numerically off. This tool does NOT return a verdict; it makes the delta
VISIBLE so Claude (and you) can reason over real numbers instead of guessing:

- ``wares`` — each ware a candidate mod adds/changes, shown against the distribution
  of same-``group`` wares in the EFFECTIVE tree (base+DLC+all installed mods, so
  VRO's rescaled prices are the baseline you're actually compared against).
- ``macro`` — the flattened numeric property vector of a single macro file, so a
  candidate weapon/ship can be lined up against a named vanilla/VRO peer.

Explicitly advisory: it grounds a balance discussion, it does not settle it. Weapon
DPS spans the weapon+bullet macro pair; `macro` reports one file's own numbers (plus
its `<bullet class=>` ref) — resolve the peer yourself for a full DPS comparison.
"""

from __future__ import annotations

import statistics
import sys
from dataclasses import dataclass, field
import copy
from pathlib import Path

from lxml import etree

from x4validate import _paths, _cat, _compat, _merge, _registry, _input, _effective
from x4validate import __version__


# --- ware extraction ----------------------------------------------------------

@dataclass
class Ware:
    id: str
    group: str
    transport: str
    volume: float
    price_min: float
    price_avg: float
    price_max: float
    tags: str = ""


def _ware_from_el(el: etree._Element) -> Ware | None:
    wid = el.get("id")
    if not wid:
        return None
    price = el.find("price")
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            # silent-ok: a missing or non-numeric price attribute; 0.0 is the
            # documented neutral value for an unpriced ware, not a read failure.
            return 0.0
    return Ware(
        id=wid,
        group=el.get("group", ""),
        transport=el.get("transport", ""),
        volume=num(el.get("volume", "0")),
        price_min=num(price.get("min")) if price is not None else 0.0,
        price_avg=num(price.get("average")) if price is not None else 0.0,
        price_max=num(price.get("max")) if price is not None else 0.0,
        tags=el.get("tags", ""),
    )


def effective_wares(ext_dir: Path, config: _merge.Config,
                    exclude: Path | None = None
                    ) -> "tuple[dict[str, Ware], etree._Element | None]":
    """Every ware in the effective tree = base + DLC + all installed mods (load order).

    Returns the TREE as well, because `candidate_wares` needs something to resolve a
    `sel=` against and rebuilding it there would merge the whole corpus twice.

    *exclude* drops the mod under test, by FOLDER NAME and by content.xml ID, exactly
    as Tier B does (`_check.py`: *"merging its own copy would pre-apply its ops and
    mask exactly the misses we look for"*). MEASURED 2026-09-06 by getting this wrong
    first: against a tree that already contained the candidate, 1,297 of one mod's
    1,443 ops reported `sel matched nothing` and the attribution gained NOTHING. The
    reason is gotcha #17 -- X4_Customizer chains selectors that predicate on a value
    an earlier op just wrote (`price[@min='432']` then `price[@min='516']`), so
    against a tree where they are ALREADY applied every one of them misses.
    """
    # INSTALLED: x4stats is advisory comparison across everything you have.
    mods = _registry.mods("installed", [ext_dir])
    order = _compat.compute_load_order(mods)
    by_folder = {m["folder"]: Path(m["path"]) for m in mods}
    if exclude is not None:
        drop_folder = exclude.resolve().name
        drop_id = ""
        cx = exclude / "content.xml"
        if cx.is_file():
            root = _merge.parse_file(cx)
            drop_id = (root.get("id") or "") if root is not None else ""
        keep = {}
        for m in mods:
            if m["folder"] == drop_folder or (drop_id and m.get("id") == drop_id):
                continue
            keep[m["folder"]] = Path(m["path"])
        by_folder = keep
    overlays = [by_folder[f] for f in order if f in by_folder]
    tree = _merge.build_effective("libraries/wares.xml", config, extra_overlays=overlays).tree
    out: dict[str, Ware] = {}
    if tree is not None:
        for el in tree.findall("ware"):
            w = _ware_from_el(el)
            if w is not None:
                out[w.id] = w
    return out, tree


def unattributed_ware_ops(candidate: Path,
                          base_tree: "etree._Element | None" = None) -> int:
    r"""Ops on libraries/wares.xml that `candidate_wares` cannot attribute.

    `candidate_wares` finds a ware only when a <ware> ELEMENT is present as an op
    payload. It therefore sees nothing for `<replace sel=...>`, `<remove sel=...>`,
    or an `<add>` whose payload is a child of a ware -- which is the DEFAULT X4
    patch idiom, and literally the example in the project's own CLAUDE.md:
    `<replace sel="//ware[@id='ore']/@price_average">500</replace>`.

    MEASURED over the live install, packed-inclusive: 125 mods scanned, 37 supply
    libraries/wares.xml, and 5 reported "introduces/changes no wares" -- all 5 of
    those zeros wrong. The largest hid 1,443 ops (1,067 replace, 132 add, 244
    remove), a whole-economy price and production rewrite; the others 594 adds, 51
    <price> replaces, 23 whole-ware removes, and 4 ops on @tags.

    ✅ SINCE 2026-09-06, GIVEN *base_tree*, THOSE WARES DO APPEAR. The paragraph that
    stood here said attribution "does NOT make those wares appear ... a feature rather
    than a bug fix"; that feature landed, and the count below now falls to the honest
    residue. Zeros went 5 -> 1 and unattributed ops 3,414 -> 190 across the corpus.

    WITHOUT a *base_tree* the old behaviour is unchanged and deliberate: resolving a
    selector needs something to resolve it against, and a caller that has none still
    gets an honest partial answer rather than a wrong one. Stopping an ABSENCE and a
    NON-ANSWER from printing the same sentence was always the point -- two skills
    route the balance question here, and "changes no wares" over a 1,443-op economy
    overhaul is a confidently wrong fact where "N ops I could not attribute" is not.

    WHAT REMAINS UNATTRIBUTABLE IS NOT A GAP. MEASURED over the five mods that still
    carry any: of 192 residual ops, 189 are ops THE ENGINE ITSELF WOULD NOT APPLY --
    116 ambiguous selectors (RFC 5261; X4 logs "Multiple matching nodes ... Skipping
    node") and 73 matching nothing. Attributing those would claim a change the game
    never makes.
    """
    root = _merge.overlay_root(candidate, "libraries/wares.xml")
    if root is None or root.tag != "diff":
        return 0
    total = attributed = 0
    resolved: set[int] = set()
    if base_tree is not None:
        work = copy.deepcopy(base_tree)
        for i, op in enumerate(_merge.apply_diff(work, root, want_targets=True)):
            if op.ok and any(tag == "ware" for tag, _ in op.target_keys):
                resolved.add(i)
    i = -1
    for op in root:
        if not isinstance(op.tag, str):
            continue                      # a comment or PI is not an op
        i += 1
        total += 1
        if op.tag == "ware":
            attributed += 1
        elif op.tag == "add" and any(
                isinstance(c.tag, str) and c.tag == "ware" for c in op):
            attributed += 1
        elif i in resolved:
            attributed += 1
    return total - attributed


def candidate_wares(candidate: Path,
                    base_tree: "etree._Element | None" = None) -> dict[str, Ware]:
    """Wares a candidate mod introduces, replaces OR MODIFIES in libraries/wares.xml.

    Handles a full-file wares.xml, a <diff> that <add>s <ware> nodes, and -- since
    2026-09-06, given *base_tree* -- a <diff> whose ops carry no <ware> element at all.

    THE THIRD CASE IS THE COMMON ONE, and reading the op PAYLOAD can never see it:

        <replace sel="//ware[@id='ore']/@price_average">500</replace>

    names its ware only in the SELECTOR. That is the default X4 patch idiom and
    literally the example in this project's own CLAUDE.md. MEASURED over the live
    install, packed-inclusive: of 125 mods, 37 supply libraries/wares.xml and 5
    reported "introduces/changes no wares" -- all five of those zeros wrong. The
    largest hid 1,443 ops (1,067 replace, 132 add, 244 remove), a whole-economy price
    and production rewrite.

    Resolving a selector needs a tree to resolve it AGAINST, which is why *base_tree*
    is required for this case and why it was a FEATURE rather than a bug fix. Without
    one, behaviour is exactly as before -- an honest partial answer, not a wrong one.

    The ops are applied IN ORDER to a DEEP COPY (gotcha #17: a diff's ops apply to a
    tree the earlier ops have already changed, and X4_Customizer emits selectors that
    predicate on a value an earlier op just wrote, chained 1,443 deep in one real
    file). The copy is why this is safe to hand the caller's effective tree.

    Reading the wares back out of the MUTATED copy is deliberate: it yields each ware
    as the candidate LEAVES it, which is the value the price comparison is about.
    """
    root = _merge.overlay_root(candidate, "libraries/wares.xml")
    if root is None:
        return {}
    out: dict[str, Ware] = {}

    if root.tag != "diff":
        for el in root.findall("ware"):
            w = _ware_from_el(el)
            if w is not None:
                out[w.id] = w
        return out

    # A payload <ware> is attributable with no tree at all; keep that path so a
    # caller without a base_tree loses nothing it used to have.
    for el in root.iter("ware"):
        w = _ware_from_el(el)
        if w is not None:
            out[w.id] = w

    if base_tree is None:
        return out

    work = copy.deepcopy(base_tree)
    touched: set[str] = set()
    for op in _merge.apply_diff(work, root, want_targets=True):
        if not op.ok:
            continue
        for tag, ident in op.target_keys:
            if tag == "ware":
                touched.add(ident)
    for el in work.findall("ware"):
        if el.get("id") in touched:
            w = _ware_from_el(el)
            if w is not None:
                out.setdefault(w.id, w)
    return out


# --- comparison ---------------------------------------------------------------

@dataclass
class WareComparison:
    ware: Ware
    peer_group: str
    peer_count: int
    peer_price_min: float = 0.0
    peer_price_median: float = 0.0
    peer_price_max: float = 0.0
    percentile: float = 0.0   # where the candidate's avg price falls in the peer set
    note: str = ""


def compare_wares(candidate: dict[str, Ware], effective: dict[str, Ware]) -> list[WareComparison]:
    """Place each candidate ware against the effective same-group price distribution.

    A ware with no `group=` attribute is not "in the empty group" — it has no
    grouping information at all. Before 2026-07-26 `group=""` was used as a real
    dict key, so every ungrouped ware in the game (1386 of them: paint mods,
    cosmetics, misc props) was bucketed together and compared as peers. A paint mod
    priced 1 was reported "~0th percentile" against a 1386-ware pool with a median
    of 51,696 — a comparison as meaningless as it looks. Ungrouped wares are now
    always reported NOT COMPARABLE rather than measured against an arbitrary bucket.
    """
    # Peer prices by group (exclude the candidate's own ids so it doesn't skew itself).
    cand_ids = set(candidate)
    prices_by_group: dict[str, list[float]] = {}
    for w in effective.values():
        if w.id in cand_ids or w.price_avg <= 0 or not w.group:
            continue
        prices_by_group.setdefault(w.group, []).append(w.price_avg)

    out: list[WareComparison] = []
    for w in sorted(candidate.values(), key=lambda x: x.id):
        if not w.group:
            out.append(WareComparison(ware=w, peer_group="", peer_count=0,
                                      note="not comparable: this ware has no group= "
                                           "attribute (e.g. a paint mod or cosmetic prop)"))
            continue
        peers = sorted(prices_by_group.get(w.group, []))
        cmp = WareComparison(ware=w, peer_group=w.group, peer_count=len(peers))
        if peers:
            cmp.peer_price_min = peers[0]
            cmp.peer_price_median = statistics.median(peers)
            cmp.peer_price_max = peers[-1]
            below = sum(1 for p in peers if p < w.price_avg)
            cmp.percentile = 100.0 * below / len(peers)
            if w.price_avg < cmp.peer_price_min:
                cmp.note = "CHEAPER than every same-group peer"
            elif w.price_avg > cmp.peer_price_max:
                cmp.note = "PRICIER than every same-group peer"
            else:
                cmp.note = f"~{cmp.percentile:.0f}th percentile of its group"
        else:
            cmp.note = f"no same-group ('{w.group}') peers to compare against"
        out.append(cmp)
    return out


# --- macro numeric vector -----------------------------------------------------

#: IMPORTED, not mirrored. This was a SECOND literal with the same name and no test
#: pinning the two equal, so raising one silently diverged the tools -- and unlike
#: `_effective`, this walk has no `truncated_props` analogue, so it truncated in
#: SILENCE. One definition, and the guard below now records what it dropped.
MAX_PROP_DEPTH = _effective.MAX_PROP_DEPTH

#: Property paths this module abandoned at the depth guard, most recent walk.
truncated_props: list[str] = []


def _walk(scope: etree._Element, out: dict[str, float | str], prefix: str,
          depth: int) -> None:
    """Recursively add ``<prefix><tag>.attr`` entries for *scope*'s children.

    Repeated sibling tags still collapse last-wins, exactly as the depth-1
    version did -- this is a flat comparison vector, not the provenance store,
    and keeping the key space stable matters more here than completeness of
    duplicates. (`_effective.flatten_with_prov` DOES disambiguate.)
    """
    for el in scope:
        if not isinstance(el.tag, str):
            continue
        key = f"{prefix}{el.tag}"
        for attr, val in el.attrib.items():
            try:
                out[f"{key}.{attr}"] = float(val)
            except ValueError:
                out[f"{key}.{attr}"] = val
        if len(el):
            if depth >= MAX_PROP_DEPTH:
                # NOT SILENT. `_effective` records what it abandons at this guard and
                # the build prints it; this walk dropped the same subtrees and said
                # nothing, so the two tools disagreed about a macro's properties with
                # only one of them able to explain why.
                truncated_props.append(f"{key}.")
                continue
            _walk(el, out, f"{key}.", depth + 1)


def flatten_props_of(macro: etree._Element) -> dict[str, float | str]:
    """Flatten ONE macro element's <properties> into ``{element.attr: value}``,
    at every depth.

    Numeric attrs become floats; the ``<bullet class=>`` ref (weapon DPS lives in the
    referenced bullet macro) is kept as a string so a peer lookup can chase it.

    Depth-recursive since 2026-08-12: the previous one-level walk made the entire
    flight model (`physics/drag`, `physics/inertia`, `jerk`, `steeringcurve`)
    invisible, so two ships differing ONLY in handling flattened to identical
    vectors -- an actively wrong answer for x4similar, not just a missing one.
    """
    out: dict[str, float | str] = {}
    if macro.get("class"):
        out["class"] = macro.get("class")
    props = macro.find("properties")
    if props is None:
        return out
    _walk(props, out, "", 1)
    return out


def iter_macros(root: etree._Element) -> list[etree._Element]:
    """Every named macro in a parsed macro file.

    Was `root.find("macro")` -- FIRST only -- while `_effective` and `_compat`
    read them all via `iter`. Two tools disagreeing about what a file contains is
    how the 2026-08-11 nested-door defect started, so they now agree. MEASURED:
    2,221 macros sit in multi-macro files, though 0 of them are `ship_*`, so the
    corrected reading changes no current answer (docs/BLIND-SPOTS.md F6).
    """
    if root.tag == "macro":
        return [root]
    return [m for m in root.iter("macro") if m.get("name")]


def flatten_macro_props(root: etree._Element) -> dict[str, float | str]:
    """Flatten the FIRST macro in *root*. Kept for callers that assume one macro
    per file; use `iter_macros` + `flatten_props_of` to see them all."""
    macros = iter_macros(root)
    if not macros:
        return {}
    return flatten_props_of(macros[0])


def macro_stats(path: Path) -> dict[str, float | str] | None:
    """Flattened numeric vector for a single macro file, or None if unreadable.

    None, not `{}`: an empty dict is a real answer ("this file is valid XML with
    no macro properties"), and the CLI prints exactly that. Returning it for an
    unreadable file blamed the mod author for a problem on our side of the read.
    """
    try:
        root = _merge.parse_file(path)
    except (OSError, etree.XMLSyntaxError) as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return None
    return flatten_macro_props(root)


# --- CLI ----------------------------------------------------------------------

def _fmt_price(v: float) -> str:
    return f"{v:,.0f}"


def render_wares(comparisons: list[WareComparison], unattributed: int = 0) -> str:
    if not comparisons:
        # AN ABSENCE AND A NON-ANSWER MUST NOT PRINT THE SAME SENTENCE.
        # `candidate_wares` reads a ware only from a <ware> ELEMENT, so a mod that
        # changes wares the ordinary way -- <replace sel=...>, <remove sel=...> --
        # came back empty and was reported as changing nothing at all. MEASURED:
        # 5 of the 37 mods supplying libraries/wares.xml, all 5 wrong, one of them
        # hiding 1,443 ops. Two skills route the balance question through this.
        if unattributed:
            return (
                "NOT CHECKED: %d op(s) on libraries/wares.xml could not be "
                "attributed to a ware.\n"
                "  This tool reads a ware only from an <add>ed <ware> element, so "
                "<replace sel=...> and\n"
                "  <remove sel=...> -- the default X4 patch idiom -- are invisible "
                "to it.\n"
                "  This is NOT 'no wares changed', and must not be read as one."
                % unattributed)
        return "candidate introduces/changes no wares."
    lines = ["ADVISORY ware comparison (candidate vs effective same-group peers):",
             "  — grounds a balance discussion; NOT a verdict. Peers include VRO's "
             "rescaled prices.\n"]
    for c in comparisons:
        w = c.ware
        lines.append(f"  {w.id}  [group={w.group or '-'}]")
        lines.append(f"     candidate avg price : {_fmt_price(w.price_avg)}  "
                     f"(min {_fmt_price(w.price_min)} / max {_fmt_price(w.price_max)}, "
                     f"vol {w.volume:g})")
        if c.peer_count:
            lines.append(f"     peer group ({c.peer_count}) : "
                         f"min {_fmt_price(c.peer_price_min)} / "
                         f"median {_fmt_price(c.peer_price_median)} / "
                         f"max {_fmt_price(c.peer_price_max)}")
        lines.append(f"     -> {c.note}")
    return "\n".join(lines)


@_paths.refuses_unconfigured
def main(argv: list[str] | None = None) -> int:
    import argparse

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # silent-ok: console encoding shim. Failure means the default codec
        # stays; it affects how output LOOKS, never what was examined.

    p = argparse.ArgumentParser(
        prog="x4stats",
        description="Advisory numeric comparison of mod content vs the effective game.")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pw = sub.add_parser("wares", help="compare a candidate mod's wares to same-group peers")
    pw.add_argument("candidate", help="candidate mod folder")
    pw.add_argument("--ext-dir", help="extensions dir (default: game-root from _registry)")
    pw.add_argument("--reference", help="unpacked base+DLC tree ($X4_REFERENCE)")

    pm = sub.add_parser("macro", help="flatten a macro file's numeric property vector")
    pm.add_argument("file", help="path to a *_macro.xml file")

    args = p.parse_args(argv)

    if args.cmd == "macro":
        stats = macro_stats(Path(args.file))
        if stats is None:
            return 2          # unreadable — already explained on stderr
        if not stats:
            print("no macro properties found (not a macro file?).", file=sys.stderr)
            return 2
        for k in sorted(stats):
            print(f"  {k} = {stats[k]}")
        return 0

    ext_dir = Path(args.ext_dir) if args.ext_dir else _registry.require(
        _registry.GAME_EXTENSIONS, "the game extensions dir",
        "set X4_GAME (or X4_EXTENSIONS), or pass --ext-dir")
    config = _merge.Config(reference=Path(args.reference)) if args.reference else _merge.Config()
    candidate = Path(args.candidate)
    _input.require_mod_dir(candidate, "candidate mod folder")
    # The comparison POOL is everything installed; the tree the candidate's
    # selectors resolve against must NOT contain the candidate.
    eff, _ = effective_wares(ext_dir, config)
    _, eff_tree = effective_wares(ext_dir, config, exclude=candidate)
    cand = candidate_wares(candidate, eff_tree)
    print(render_wares(compare_wares(cand, eff),
                       unattributed_ware_ops(candidate, eff_tree)))
    return 0

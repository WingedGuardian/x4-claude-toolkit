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
from pathlib import Path

from lxml import etree

from x4validate import _cat, _compat, _merge, _registry, _input
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


def effective_wares(ext_dir: Path, config: _merge.Config) -> dict[str, Ware]:
    """Every ware in the effective tree = base + DLC + all installed mods (load order)."""
    mods = _registry.scan_installed([ext_dir])
    order = _compat.compute_load_order(mods)
    by_folder = {m["folder"]: Path(m["path"]) for m in mods}
    overlays = [by_folder[f] for f in order if f in by_folder]
    tree = _merge.build_effective("libraries/wares.xml", config, extra_overlays=overlays).tree
    out: dict[str, Ware] = {}
    if tree is not None:
        for el in tree.findall("ware"):
            w = _ware_from_el(el)
            if w is not None:
                out[w.id] = w
    return out


def candidate_wares(candidate: Path) -> dict[str, Ware]:
    """Wares a candidate mod introduces or replaces in libraries/wares.xml.

    Handles both a full-file wares.xml and a <diff> that <add>s <ware> nodes.
    """
    root = _merge.overlay_root(candidate, "libraries/wares.xml")
    if root is None:
        return {}
    out: dict[str, Ware] = {}
    wares = root.iter("ware") if root.tag == "diff" else root.findall("ware")
    for el in wares:
        w = _ware_from_el(el)
        if w is not None:
            out[w.id] = w
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

def flatten_macro_props(root: etree._Element) -> dict[str, float | str]:
    """Flatten a macro's <properties> into ``{element.attr: value}``.

    Numeric attrs become floats; the ``<bullet class=>`` ref (weapon DPS lives in the
    referenced bullet macro) is kept as a string so a peer lookup can chase it.
    """
    macro = root.find("macro") if root.tag != "macro" else root
    if macro is None:
        return {}
    out: dict[str, float | str] = {}
    if macro.get("class"):
        out["class"] = macro.get("class")
    props = macro.find("properties")
    if props is None:
        return out
    for el in props:
        if not isinstance(el.tag, str):
            continue
        for attr, val in el.attrib.items():
            key = f"{el.tag}.{attr}"
            try:
                out[key] = float(val)
            except ValueError:
                out[key] = val
    return out


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


def render_wares(comparisons: list[WareComparison]) -> str:
    if not comparisons:
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
    eff = effective_wares(ext_dir, config)
    cand = candidate_wares(candidate)
    print(render_wares(compare_wares(cand, eff)))
    return 0

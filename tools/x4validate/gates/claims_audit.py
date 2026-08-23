"""Re-verify every numeric claim a design doc makes, at the TIER the claim is about.

WHY THIS EXISTS. Axis 1 of the design roadmap was written 2026-08-02 while the
merge was dropping root-`<replace>` ops and reporting them applied (fixed 08-08),
so VRO's overrides never landed and vanilla values could be written down as VRO's.
The numbers sat in permanent record for eleven days and were re-quoted as fact.
Prose cannot be tested. A claim written as `kind/entity/prop/expected` can be.

WHY THERE IS A TIER COLUMN (added 2026-08-13). The first version evaluated EVERY
claim against the effective store. That is only correct for claims about the LIVE
tree. `DESIGN-THREADS.md` deliberately compares two columns -- "Vanilla 9.0" vs
"VRO 5.01" -- so its vanilla-side numbers are CORRECT and were being reported as
FAIL purely because they were measured against a VRO-inclusive store:

    engine_par_s_travel_01_mk1_macro.travel.thrust   doc 22.2  vanilla 22.16  live 20
    engine_par_l_travel_01_mk1_macro.travel.thrust   doc 45.2  vanilla 45.2   live 34.5
    missile_gen_l_torpedo_01_mk1_macro.missile.range doc 12000 vanilla 12000  live 30000

All three are the vanilla column of a two-column table. The doc was right; the
gate was asking the wrong tier. This is CLAUDE.md gotcha #14 -- "a claim about
VANILLA must be checked against vanilla, not the effective tree" -- mechanised.

An untiered claim is not evaluable, so the tier column is REQUIRED and a
malformed row counts as UNRESOLVED rather than being skipped: a silent skip here
is exactly the "we did not look rendered as nothing was wrong" defect.

Four outcomes, and the last is the point:
  PASS        the tier agrees with the doc
  FAIL        the tier disagrees -- the doc is wrong, or the world moved
  UNRESOLVED  the entity/prop is absent, or the row cannot be read
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402

from x4validate import _effective, _merge, _paths, _provenance, _registry  # noqa: E402


def _registry_dir() -> Path:
    """Where the registry lives, or REFUSE.

    These were module CONSTANTS: `Path(_registry.DEFAULT_REGISTRY).parent / ...`
    evaluated at import, and `DEFAULT_REGISTRY` is None on an unconfigured
    machine — so merely importing this module raised `TypeError: argument should
    be a str or os.PathLike, not NoneType`. `tests/test_claims_tier.py` imports
    it only for the TSV row parser, which reads nothing from disk, so on a fresh
    clone all **9** of its tests were silently uncollected and reported as ONE
    skip (F42).

    Plain functions, deliberately — NOT a module `__getattr__`. That was tried
    and is a trap twice over: PEP 562 does not serve a module's own global reads
    (every internal use became `NameError`), and `monkeypatch.setattr` calls
    `getattr(target, name, sentinel)` to save the original, which swallows only
    `AttributeError` — so a lazy attribute that refuses with anything else makes
    the test's own fixture seam explode before it can be installed. A function is
    boring, and boring is the point.
    """
    registry = _registry.DEFAULT_REGISTRY
    if registry is None:
        raise _paths.Unconfigured(
            "no registry is configured, so the claims file and effective store "
            "cannot be located. Set $X4_REGISTRY or $X4_MODS, or see "
            ".claude/x4-paths.env.")
    return Path(registry).parent


def _claims() -> Path:
    return _registry_dir() / "CLAIMS.tsv"


def _store() -> Path:
    return _registry_dir() / "effective.sqlite"

TIERS = {"vanilla", "effective"}
#: Kinds the vanilla path can rebuild. Anything else is declared UNRESOLVED with a
#: reason rather than quietly passed -- the store's other kinds come from registry
#: documents that would each need their own extractor.
VANILLA_KINDS = {"macro"}

_vanilla_cache: dict[str, dict] = {}


def rows():
    """Yield (line_no, kind, entity, prop, expected, tol, source, tier, error)."""
    for n, line in enumerate(_claims().read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        p = line.split("\t")
        if len(p) < 7:
            yield (n, None, None, None, None, None, line.strip()[:60], None,
                   f"expected 7 tab-separated fields (kind/entity/prop/expected/tol/"
                   f"source/tier), got {len(p)}")
            continue
        kind, entity, prop, expected, tol, source, tier = p[0], p[1], p[2], p[3], p[4], p[5], p[6].strip()
        if tier not in TIERS:
            yield (n, kind, entity, prop, expected, None, source, tier,
                   f"tier must be one of {sorted(TIERS)}, got {tier!r}")
            continue
        try:
            tolf = float(tol)
        except ValueError:
            yield (n, kind, entity, prop, expected, None, source, tier,
                   f"tolerance {tol!r} is not numeric")
            continue
        yield n, kind, entity, prop, expected, tolf, source, tier, None


def _store_vpath(con, kind: str, entity: str) -> str | None:
    r = con.execute("select vpath from entities where kind=? and name=?",
                    (kind, entity)).fetchone()
    return r[0] if r else None


def vanilla_rows(vpath: str) -> dict[str, str]:
    """{prop: value} for every macro in *vpath* as base+DLC alone define it.

    Reuses `_effective.extract_macros`, so the prop-key grammar is byte-identical
    to the store's. Re-deriving it here would be a second implementation of the
    same question -- the defect shape this register exists to kill.
    """
    if vpath in _vanilla_cache:
        return _vanilla_cache[vpath]
    rec = _provenance.Recorder()
    res = _merge.build_effective(vpath, _merge.Config(), recorder=rec)
    out: dict[str, str] = {}
    if res.tree is not None:
        for ent in _effective.extract_macros(res.tree, vpath, rec):
            for prop, val, _num, _chain in ent.attrs:
                out[f"{ent.name}\t{prop}"] = val
    _vanilla_cache[vpath] = out
    return out


def main() -> int:
    if not _claims().is_file():
        print(f"no claims file at {_claims()} — nothing to verify.")
        return 0
    con = sqlite3.connect(f"file:{_store()}?mode=ro", uri=True)

    # A claim verified against a STALE store is worth nothing: that is precisely
    # how the axis-1 numbers became wrong in the first place.
    stale = _effective.store_freshness(con)
    if not stale.fresh:
        print(stale.banner("the effective store"), file=sys.stderr)
        print("REFUSING to verify claims against a stale store.", file=sys.stderr)
        return 5

    npass = nfail = nunres = 0
    per_tier = {"vanilla": [0, 0, 0], "effective": [0, 0, 0]}  # pass, fail, unresolved

    for n, kind, entity, prop, expected, tol, source, tier, err in rows():
        if err:
            nunres += 1
            print(f"  UNRESOLVED  line {n}")
            print(f"              {err}  [{source}]")
            continue

        actual_raw = reason = None
        if tier == "effective":
            got = con.execute(
                "select a.value from attrs a join entities e on e.id=a.entity_id "
                "where e.kind=? and e.name=? and a.prop=?", (kind, entity, prop)).fetchone()
            if got is None:
                reason = "not in the effective store"
            else:
                actual_raw = got[0]
        else:  # vanilla
            if kind not in VANILLA_KINDS:
                reason = (f"vanilla evaluation supports {sorted(VANILLA_KINDS)}, "
                          f"not kind {kind!r}")
            else:
                vpath = _store_vpath(con, kind, entity)
                if vpath is None:
                    reason = "entity unknown to the store, so its vpath cannot be resolved"
                else:
                    vr = vanilla_rows(vpath)
                    actual_raw = vr.get(f"{entity}\t{prop}")
                    if actual_raw is None:
                        reason = (f"absent from VANILLA {vpath} — mod-added content has no "
                                  f"vanilla value, so a vanilla claim is not meaningful")

        if actual_raw is None:
            nunres += 1
            per_tier[tier][2] += 1
            print(f"  UNRESOLVED  {entity}.{prop}  [{tier}]")
            print(f"              {reason}  [{source}]")
            continue
        try:
            actual, want = float(actual_raw), float(expected)
        except ValueError:
            nunres += 1
            per_tier[tier][2] += 1
            print(f"  UNRESOLVED  {entity}.{prop} = {actual_raw!r} (non-numeric)  [{source}]")
            continue
        if abs(actual - want) <= tol:
            npass += 1
            per_tier[tier][0] += 1
        else:
            nfail += 1
            per_tier[tier][1] += 1
            print(f"  FAIL        {entity}.{prop}  [{tier}]")
            print(f"              doc says {want:g}, {tier} says {actual:g}   [{source}]")

    total = npass + nfail + nunres
    print(f"\n{'=' * 72}")
    for t in ("vanilla", "effective"):
        p, f, u = per_tier[t]
        if p or f or u:
            print(f"  {t:10s} PASS {p:3d}   FAIL {f:3d}   UNRESOLVED {u:3d}")
    print(f"claims checked: {total}   PASS {npass}   FAIL {nfail}   UNRESOLVED {nunres}")
    if nfail or nunres:
        print("A FAIL means the doc is wrong or the world moved. An UNRESOLVED means")
        print("the claim was never evaluated — neither may be read as agreement.")
        return 1
    print("Every recorded claim still holds, at the tier it is about.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

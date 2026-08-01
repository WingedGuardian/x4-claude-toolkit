"""L9 — the patch-time and runtime trees are different trees, and both are needed.

`overlays` is truncated at the mod's own load-order position. That is RIGHT for
`sel=` (a node a later mod adds genuinely is not there when the engine applies this
mod's diffs) and WRONG for existence questions (does macro X resolve?), which the
engine answers only once every extension has loaded.

Confirmed against the real modlist 2026-07-28 with `X4CapturableXenonXL` (position
79) and `xspvro` (position 92), which demonstrates BOTH directions at once:

  - 3 `<remove sel="//connections/connection[@ref='connection_cockpit']">` ops match
    at patch time and vanish from the final tree -> using `final` for `sel=` invents
    3 false alarms.
  - `xspvro` re-points `ship_xen_xl_carrier_01_a_macro` at `ship_pla_xl_battleship`,
    which lacks `connection_shieldgen_external03` that the mod's loadout asks for ->
    using `patch_time` for references hides 1 real runtime defect.

These tests are hermetic (synthetic dirs); the real-modlist measurement lives in
`gates/oracle_index.py`.
"""

from __future__ import annotations

from pathlib import Path

from x4validate import _check, _merge


def _cfg(patch, final):
    return _merge.Config(overlays=tuple(patch), final_overlays=tuple(final))


def test_for_runtime_swaps_in_the_final_tree():
    a, b = Path("a"), Path("b")
    cfg = _cfg([a], [a, b])
    assert cfg.overlays == (a,)
    assert cfg.for_runtime().overlays == (a, b), \
        "runtime lookups must see extensions that load AFTER the mod under test"


def test_for_runtime_is_identity_without_a_separate_tree():
    """Tier A and every pre-split caller must be untouched."""
    cfg = _merge.Config(overlays=(Path("a"),))
    assert cfg.for_runtime() is cfg
    tier_a = _merge.Config()
    assert tier_a.for_runtime() is tier_a
    same = _merge.Config(overlays=(Path("a"),), final_overlays=(Path("a"),))
    assert same.for_runtime() is same, "an identical runtime tree must not copy"


def test_for_runtime_preserves_the_rest_of_the_config(tmp_path):
    cfg = _merge.Config(reference=tmp_path, overlays=(Path("a"),),
                        final_overlays=(Path("a"), Path("b")),
                        include_packed_dlc=False)
    run = cfg.for_runtime()
    assert run.reference == tmp_path and run.include_packed_dlc is False, \
        "for_runtime must swap ONLY the overlay tree"


def test_patch_time_is_a_prefix_of_final():
    """The runtime tree extends the patch-time one; it never reorders or drops.

    If this ever fails, load order is being computed twice and inconsistently —
    which would make the two trees incomparable rather than nested.
    """
    dirs = [Path(str(i)) for i in range(5)]
    t = _check.TierB(patch_time=tuple(dirs[:2]), final=tuple(dirs))
    assert t.final[:len(t.patch_time)] == t.patch_time


def test_fallback_yields_two_empty_trees():
    """A Tier B that could not be built must not silently look like a runtime tree."""
    t = _check.TierB()
    assert t.patch_time == () and t.final == ()
    assert _merge.Config(overlays=t.patch_time, final_overlays=t.final).for_runtime().overlays == ()


def test_tier_b_overlays_wrapper_still_returns_the_patch_time_tree(monkeypatch):
    """The diff oracle and ad-hoc scripts call the old 2-tuple API.

    Mutation-pinned: returning `final` here would silently regress the 234/234 diff
    oracle, because `sel=` resolution would start seeing later-loading mods.
    """
    sentinel = _check.TierB(patch_time=(Path("early"),),
                            final=(Path("early"), Path("late")),
                            notes=["n"])
    monkeypatch.setattr(_check, "tier_b_trees", lambda *a, **k: sentinel)
    overlays, notes = _check.tier_b_overlays(Path("whatever"))
    assert overlays == (Path("early"),), "the wrapper must NOT hand back the runtime tree"
    assert notes == ["n"]

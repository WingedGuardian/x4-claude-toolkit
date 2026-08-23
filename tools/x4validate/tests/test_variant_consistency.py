r"""F22: the variant-sibling check enumerated LOOSE FILES ON DISK, three times over.

`check_variant_consistency` warns when a mod patches `ship_x_a_macro.xml` but not
its sibling `ship_x_b_macro.xml` -- per-variant props (hull, cargo, loadout) then
silently keep their old values on the untouched variants. Every one of its three
enumerations was a plain filesystem walk:

 1. THE MOD UNDER TEST -- `mod_dir.rglob("*.xml")`, so a PACKED mod contributed
    nothing at all. MEASURED across 115 installed mods: of 378 variant macro
    files, **14 were reachable and 364 (96.3%) were invisible**, including VRO,
    both ship_variation_expansion mods and all four lc4hunter packs. This is the
    same defect `iter_diff_files` was repaired for on 2026-07-26 -- the function
    directly below it in the same file -- never carried across.
 2. THE BASE TREE -- `config.reference / vdir`, blind to the two packed mini-DLC.
 3. A CROSS-MOD PATH -- `extensions/<other mod>/...`, whose siblings live inside
    THAT mod and never in `reference/` at all.

The ranking matters, and getting it wrong nearly shipped a no-op: axes 2 and 3
account for 2 files each, and all four sit INSIDE the 364 that axis 1 already
made unreachable. Fixing 2 and 3 alone would have changed nothing observable.

After the fix, MEASURED over the same 115 mods: 378 examined, **3 warnings, all
in `vro`** (ship_ter_l_flagship_01, ship_ter_m_corvette_02, ship_ter_s_fighter_04
-- each patched in variant `a` only), 0 unresolved. Small enough to gate on
rather than merely inform.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from x4validate import _check, _merge


def _write_cat(mod_dir: Path, members):
    mod_dir.mkdir(parents=True, exist_ok=True)
    lines, blob = [], bytearray()
    for vpath, data in members:
        lines.append(f"{vpath} {len(data)} 1700000000 {hashlib.md5(data).hexdigest()}")
        blob += data
    (mod_dir / "ext_01.cat").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (mod_dir / "ext_01.dat").write_bytes(bytes(blob))


def _ref_with_variants(tmp_path: Path, *, dlc: str | None = None) -> Path:
    """A reference tree holding ship_ter_x_a/_b macros, optionally inside a DLC."""
    rel = "assets/units/size_l/macros"
    root = tmp_path / "reference"
    d = root / (f"extensions/{dlc}/{rel}" if dlc else rel)
    d.mkdir(parents=True)
    for v in ("a", "b"):
        (d / f"ship_ter_x_{v}_macro.xml").write_text("<macros/>", encoding="utf-8")
    return root


def _findings(report):
    return [f for f in report.findings if f.category == "variant"]


def test_a_PACKED_mod_is_examined_at_all(tmp_path, monkeypatch):
    """AXIS 1, the 96.3%. Before the fix this mod yielded zero variant files and
    the check returned clean -- a whole-mod false pass."""
    ref = _ref_with_variants(tmp_path)
    cfg = _merge.Config(reference=ref)
    mod = tmp_path / "packedmod"
    _write_cat(mod, [("assets/units/size_l/macros/ship_ter_x_a_macro.xml",
                      b"<diff><replace sel='//macro/@name'>x</replace></diff>")])

    report = _check.Report()
    _check.check_variant_consistency(mod, cfg, report)
    found = _findings(report)
    assert len(found) == 1, f"packed mod not examined: {report.findings}"
    assert "ship_ter_x_b_macro.xml" in found[0].message


def test_patching_every_sibling_is_silent(tmp_path, monkeypatch):
    """The control. A check that fires on a correctly-complete mod is noise, and
    noise is how a real warning gets skimmed past."""
    ref = _ref_with_variants(tmp_path)
    cfg = _merge.Config(reference=ref)
    mod = tmp_path / "packedmod"
    _write_cat(mod, [(f"assets/units/size_l/macros/ship_ter_x_{v}_macro.xml", b"<diff/>")
                     for v in ("a", "b")])
    report = _check.Report()
    _check.check_variant_consistency(mod, cfg, report)
    assert _findings(report) == []


def test_an_UNPACKED_DLC_path_falls_through_to_the_base_tree(tmp_path, monkeypatch):
    """REGRESSION GUARD, and it caught a real one.

    A vpath under `extensions/ego_dlc_timelines/` names neither a packed DLC nor
    an installed MOD (`scan_installed` excludes `ego_dlc_*`). The first cut of
    `_sibling_pool` treated that as unresolvable and bailed -- which silently took
    VRO's 3 genuine findings, all of them under `extensions/ego_dlc_timelines/`,
    back to ZERO. It was caught only because a read-only prototype had been
    measured first and said 3, so 0 was visibly wrong.
    """
    ref = _ref_with_variants(tmp_path, dlc="ego_dlc_timelines")
    cfg = _merge.Config(reference=ref)
    mod = tmp_path / "amod"
    d = mod / "extensions/ego_dlc_timelines/assets/units/size_l/macros"
    d.mkdir(parents=True)
    (d / "ship_ter_x_a_macro.xml").write_text("<diff/>", encoding="utf-8")

    report = _check.Report()
    _check.check_variant_consistency(mod, cfg, report)
    found = _findings(report)
    assert len(found) == 1, "a DLC-owned sibling set was not resolved"
    assert "ship_ter_x_b_macro.xml" in found[0].message


def test_a_directory_whose_owner_supplies_nothing_is_SKIPPED_not_silent(tmp_path):
    """The narrowing-step contract. "We could not look" must never render as
    "we looked and it was fine" -- that is this register's founding defect."""
    ref = tmp_path / "reference"
    (ref / "assets").mkdir(parents=True)
    cfg = _merge.Config(reference=ref)
    mod = tmp_path / "amod"
    d = mod / "assets/units/nowhere/macros"
    d.mkdir(parents=True)
    (d / "ship_ter_x_a_macro.xml").write_text("<diff/>", encoding="utf-8")

    report = _check.Report()
    _check.check_variant_consistency(mod, cfg, report)
    assert _findings(report) == []
    assert report.skipped, "an unresolvable owner returned silently"
    assert "NOT checked" in report.skipped[0].why


def test_a_lone_variant_with_no_sibling_does_not_warn(tmp_path):
    """`len(siblings) < 2` -- a ship that simply has one variant is not a defect."""
    rel = "assets/units/size_l/macros"
    ref = tmp_path / "reference"
    (ref / rel).mkdir(parents=True)
    (ref / rel / "ship_ter_x_a_macro.xml").write_text("<macros/>", encoding="utf-8")
    cfg = _merge.Config(reference=ref)
    mod = tmp_path / "amod"
    (mod / rel).mkdir(parents=True)
    (mod / rel / "ship_ter_x_a_macro.xml").write_text("<diff/>", encoding="utf-8")

    report = _check.Report()
    _check.check_variant_consistency(mod, cfg, report)
    assert _findings(report) == []
    assert not report.skipped

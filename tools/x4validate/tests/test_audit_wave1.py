"""Regression pins for the 2026-08-01 audit, wave 1.

Every test here corresponds to a finding in AUDIT-2026-08.md and was
mutation-verified: the fix was reverted and the test confirmed to FAIL.

The theme running through F4/F13 is one bug wearing three hats: work that was
NOT done rendering as a pass. `report.add("warn", "skipped", ...)` was the decoy
— it carries the *category string* "skipped" but creates a Finding, so it never
reaches `report.skipped`, `report.degraded` stays empty, and the CLI exits 0.
"""
from __future__ import annotations

from pathlib import Path

from lxml import etree

from x4validate import _check, _merge, _refs, _xsd


def _mod(tmp_path: Path, files: dict[str, str], name: str = "mod") -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    files = {"content.xml": '<content id="m"/>', **files}
    for rel, text in files.items():
        f = d / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return d


def _ref(tmp_path: Path) -> _merge.Config:
    r = tmp_path / "reference"
    (r / "libraries").mkdir(parents=True, exist_ok=True)
    (r / "libraries" / "wares.xml").write_text("<wares/>", encoding="utf-8")
    return _merge.Config(reference=r)


# --- F4: nothing sel-checked must not read as a pass --------------------------

def test_a_manifest_only_folder_is_degraded_not_clean(tmp_path):
    """The headline false pass: nothing to check, reported OK, exit 0."""
    mod = _mod(tmp_path, {})
    report = _check.Report()
    _check.check_sel_resolution(mod, _ref(tmp_path), report)
    assert report.degraded, "a folder with no payload at all must gate"
    assert not report.errors


def test_additive_only_mod_is_NOT_degraded(tmp_path):
    """The other half, and the reason the naive fix would have been wrong.

    Measured on the real modlist before this was written: 16 of 102 installed
    mods ship payload XML and no <diff> at all. Marking "0 diffs" degraded would
    have produced 16 false exit-3s on a healthy setup.
    """
    mod = _mod(tmp_path, {"md/new_script.xml": "<mdscript/>"})
    report = _check.Report()
    _check.check_sel_resolution(mod, _ref(tmp_path), report)
    assert not report.degraded
    assert any("additive-only" in n for n in report.notes)


def test_asset_only_loose_mod_is_NOT_degraded(tmp_path):
    mod = _mod(tmp_path, {})
    (mod / "textures").mkdir()
    (mod / "textures" / "skin.dds").write_bytes(b"\x00\x01")
    report = _check.Report()
    _check.check_sel_resolution(mod, _ref(tmp_path), report)
    assert not report.degraded
    assert any("loose assets" in n for n in report.notes)


def test_degraded_uses_the_real_skip_channel(tmp_path):
    """Pins the decoy specifically: a Finding whose category is "skipped" is NOT
    a skip. This is what made the JSON say {"skipped": [], "degraded": false}."""
    mod = _mod(tmp_path, {})
    report = _check.Report()
    _check.check_sel_resolution(mod, _ref(tmp_path), report)
    assert report.skipped, "must populate Report.skipped, not fake it with a Finding"
    assert not [f for f in report.findings if f.category == "skipped"], \
        "the decoy report.add(..., 'skipped', ...) must not come back"


# --- F3: the core check must state its denominator ----------------------------

def test_sel_resolution_always_reports_its_denominator(tmp_path):
    """A 14-file mod and a 1-file mod printed identically before 2026-08-01."""
    mod = _mod(tmp_path, {
        "libraries/wares.xml": '<diff><add sel="/wares"><ware id="x"/></add></diff>',
        "md/extra.xml": "<mdscript/>",
    })
    report = _check.Report()
    _check.check_sel_resolution(mod, _ref(tmp_path), report)
    note = next(n for n in report.notes if n.startswith("sel-resolution:"))
    assert "1 diff file(s) checked" in note
    assert "2 payload XML file(s)" in note, "content.xml must not count as payload"


# --- F13: a folder with no manifest is not an extension -----------------------

def test_missing_manifest_gates(tmp_path):
    d = tmp_path / "nomanifest"
    (d / "libraries").mkdir(parents=True)
    (d / "libraries" / "wares.xml").write_text("<diff/>", encoding="utf-8")
    report = _check.Report()
    _check.check_readability(d, _ref(tmp_path), report)
    assert report.degraded and "content.xml" in report.degraded[0].why


def test_present_manifest_does_not_gate(tmp_path):
    """Both sides asserted — a check that flagged everything would also pass the
    test above."""
    mod = _mod(tmp_path, {"md/fine.xml": "<mdscript/>"})
    report = _check.Report()
    _check.check_readability(mod, _ref(tmp_path), report)
    assert not report.degraded


# --- F11: macro refs are carried by <container> too ---------------------------

def _tree(xml: str):
    return etree.fromstring(xml.encode())


def test_container_ref_is_checked_like_component_ref():
    """T4 in the trap fixture. Vanilla libraries/wares.xml carries @ref on exactly
    two elements — component (734) and container (183) — and all 917 resolve
    against the same index/macros.xml, so covering both cannot flood."""
    tree = _tree('<wares><ware id="w"><container ref="no_such_macro"/></ware></wares>')
    out = _refs.find_dangling(tree, ware_def_set=set(), text_def_set=set(),
                              macro_def_set={"real_macro"})
    assert [d.kind for d in out] == ["macro"]
    assert out[0].ref == "no_such_macro"


def test_container_ref_that_resolves_is_not_flagged():
    tree = _tree('<wares><ware id="w"><container ref="real_macro"/></ware></wares>')
    out = _refs.find_dangling(tree, ware_def_set=set(), text_def_set=set(),
                              macro_def_set={"real_macro"})
    assert out == []


def test_component_ref_still_checked():
    """Guards against 'fixing' container by replacing component."""
    tree = _tree('<x><component ref="nope"/></x>')
    out = _refs.find_dangling(tree, ware_def_set=set(), text_def_set=set(),
                              macro_def_set={"real_macro"})
    assert [d.ref for d in out] == ["nope"]


def test_unbuilt_macro_index_still_skips_both_elements():
    """macro_def_set=None means the index could not be built (reported as a
    degraded skip by the caller). An EMPTY set is a different thing. Extending
    the xpath must not collapse that distinction."""
    tree = _tree('<wares><ware id="w"><container ref="anything"/></ware></wares>')
    assert _refs.find_dangling(tree, set(), set(), macro_def_set=None) == []


# --- F1: a declared schema is a path RELATIVE TO THE DOCUMENT ------------------
#
# Taking only the basename and looking only in reference/libraries skipped 31
# documents as "not bundled" when the schema was bundled. The false REASON is the
# worse half — it is what stops the next person checking.

def _decl(location: str):
    return etree.fromstring(
        '<x xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'xsi:noNamespaceSchemaLocation="{location}"/>'.encode())


def _tree_with(tmp_path: Path, *rel_xsds: str) -> Path:
    ref = tmp_path / "reference"
    for r in rel_xsds:
        p = ref / r
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("<xs:schema xmlns:xs='http://www.w3.org/2001/XMLSchema'/>",
                     encoding="utf-8")
    (ref / "libraries").mkdir(parents=True, exist_ok=True)
    return ref / "libraries"


def test_schema_next_to_its_document_resolves(tmp_path):
    lib = _tree_with(tmp_path, "cutscenes/cutscenes.xsd")
    path, why = _xsd.schema_of(_decl("cutscenes.xsd"), lib, "cutscenes/foo.xml")
    assert why is None and path.name == "cutscenes.xsd"
    assert path.parent.name == "cutscenes"


def test_dotdot_from_an_extension_root_reaches_the_game_root(tmp_path):
    """The live case: a mod's ui.xml sits at extensions/<mod>/ui.xml, so its
    '../../ui/core/addon.xsd' is written to climb out to the game root."""
    lib = _tree_with(tmp_path, "ui/core/addon.xsd")
    path, why = _xsd.schema_of(_decl("../../ui/core/addon.xsd"), lib, "ui.xml")
    assert why is None and path.parent.name == "core"


def test_resolution_is_layer_aware(tmp_path):
    """cutscenes.xsd exists in SIX layers (base + 5 DLC). A DLC document must get
    its OWN layer's copy, not whichever the filesystem yields first."""
    lib = _tree_with(tmp_path, "cutscenes/cutscenes.xsd",
                     "extensions/ego_dlc_boron/cutscenes/cutscenes.xsd")
    path, _ = _xsd.schema_of(_decl("cutscenes.xsd"), lib,
                             "extensions/ego_dlc_boron/cutscenes/x.xml")
    assert "ego_dlc_boron" in str(path)


def test_backslash_declarations_resolve(tmp_path):
    r"""Vanilla ships '..\..\..\libraries\classcatalog.xsd' — 5 occurrences."""
    lib = _tree_with(tmp_path, "libraries/classcatalog.xsd")
    path, why = _xsd.schema_of(_decl(r"..\..\libraries\classcatalog.xsd"),
                               lib, "a/b/c.xml")
    assert why is None and path.name == "classcatalog.xsd"


def test_a_genuinely_absent_schema_still_reports_why(tmp_path):
    """The channel must survive the fix: unresolvable is still a stated skip."""
    lib = _tree_with(tmp_path)
    path, why = _xsd.schema_of(_decl("really_absent.xsd"), lib, "libraries/x.xml")
    assert path is None and why and "really_absent.xsd" in why


def test_traversal_outside_reference_is_refused(tmp_path):
    """Enough '../' must not turn into a probe of the developer's filesystem."""
    lib = _tree_with(tmp_path)
    path, why = _xsd.schema_of(_decl("../../../../../../etc/passwd"), lib, "a.xml")
    assert path is None and why

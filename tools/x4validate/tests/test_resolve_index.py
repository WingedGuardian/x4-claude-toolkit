"""L1 — the macro/component index must see the same world every other check sees.

`_resolve.build_index` had two independent blind spots that both rendered as a
clean pass:

  L1a  it read `extra_overlays` but never `config.overlays`, so under `--tier b`
       the file-existence and connection checks ran against a base+DLC-only index
       while every other check saw the merged tree. Measured before the fix: Tier
       A and Tier B both returned 4,488 entries — *identical*.

  L1b  it read index files with `.is_file()` only, so a PACKED mod contributed
       nothing at all — 26 (mod, index) pairs contributed 0 of their own entries.

The trap that makes this one test file rather than two: fixing L1b in the index
ALONE is worse than not fixing it. Registering a macro whose file then cannot be
found turns a missed check into a false "registered but file missing" ERROR. That
is not hypothetical — the half-fix was measured against the installed set on
2026-07-28 and produced 11 false errors across `code_vgr_battlecruiser` and
`ebi_timelines_faction_use_ship`, both of which ship the macro inside their own
`.cat`. So the payload reads are packed-aware too, and the last test here pins
exactly that pairing.

Every test is mutation-verified: with the fix reverted it fails.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace

from x4validate import _check, _merge, _resolve

MACRO = "ship_test_01_macro"


def _write_cat(mod_dir, cat_name, members):
    mod_dir.mkdir(parents=True, exist_ok=True)
    cat = mod_dir / cat_name
    lines, blob = [], bytearray()
    for vpath, data in members:
        lines.append(f"{vpath} {len(data)} 1700000000 {hashlib.md5(data).hexdigest()}")
        blob += data
    cat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cat.with_suffix(".dat").write_bytes(bytes(blob))


def _reference(tmp_path):
    ref = tmp_path / "reference"
    (ref / "index").mkdir(parents=True)
    (ref / "index" / "macros.xml").write_text(
        '<index><entry name="ship_vanilla_macro" value="assets\\vanilla"/></index>',
        encoding="utf-8")
    (ref / "assets").mkdir(parents=True)
    (ref / "assets" / "vanilla.xml").write_text("<macros/>", encoding="utf-8")
    return _merge.Config(reference=ref)


def _index_xml(name: str, value: str) -> str:
    return f'<index><entry name="{name}" value="{value}"/></index>'


# --- L1a: config.overlays must be merged into the index ----------------------

def test_build_index_merges_config_overlays(tmp_path):
    """A Tier B overlay's index entries must be registered.

    Asserts BOTH sides: the same call with no overlays must NOT see the entry,
    so the test cannot pass against a build_index that registers everything.
    """
    cfg = _reference(tmp_path)
    other = tmp_path / "other_mod"
    (other / "index").mkdir(parents=True)
    (other / "index" / "macros.xml").write_text(
        _index_xml(MACRO, "extensions\\other_mod\\assets\\ship"), encoding="utf-8")

    tier_a = _resolve.build_index(cfg, [], _resolve.MACRO_INDEX)
    assert MACRO not in tier_a, "Tier A must not see another mod's macro"

    tier_b = _resolve.build_index(replace(cfg, overlays=(other,)), [], _resolve.MACRO_INDEX)
    assert MACRO in tier_b, "config.overlays was ignored — Tier B index is base+DLC only"
    assert tier_b[MACRO] == (other, "assets/ship")


def test_extra_overlays_still_win_over_config_overlays(tmp_path):
    """Load order: the mod under test is applied AFTER the installed set."""
    cfg = _reference(tmp_path)
    other, under_test = tmp_path / "other_mod", tmp_path / "mine"
    for d, value in ((other, "extensions\\other_mod\\assets\\theirs"),
                     (under_test, "extensions\\mine\\assets\\mine")):
        (d / "index").mkdir(parents=True)
        (d / "index" / "macros.xml").write_text(_index_xml(MACRO, value), encoding="utf-8")

    index = _resolve.build_index(replace(cfg, overlays=(other,)), [under_test],
                                 _resolve.MACRO_INDEX)
    assert index[MACRO] == (under_test, "assets/mine")


# --- L1b: a packed mod's own index must be read ------------------------------

def test_build_index_reads_a_packed_index(tmp_path):
    """A packed mod has zero loose XML; `.is_file()` alone registers none of it."""
    cfg = _reference(tmp_path)
    packed = tmp_path / "packed_mod"
    _write_cat(packed, "ext_01.cat", [
        ("index/macros.xml",
         _index_xml(MACRO, "extensions\\packed_mod\\assets\\ship").encode()),
    ])
    index = _resolve.build_index(cfg, [packed], _resolve.MACRO_INDEX)
    assert MACRO in index, "packed index/macros.xml was not read"


def test_unparseable_overlay_index_is_reported_not_swallowed(tmp_path):
    cfg = _reference(tmp_path)
    bad = tmp_path / "bad_mod"
    (bad / "index").mkdir(parents=True)
    (bad / "index" / "macros.xml").write_text("<index><entry", encoding="utf-8")

    report = _check.Report()
    _resolve.build_index(cfg, [bad], _resolve.MACRO_INDEX, report)
    assert any("bad_mod" in s.why for s in report.skipped), \
        "an index that will not parse must be reported, not dropped"


# --- The pairing: a packed index needs packed payload reads -------------------

def test_packed_macro_file_is_not_reported_missing(tmp_path):
    """The half-fix regression test.

    Index entry AND macro file both live inside the .cat. Registering the macro
    without reading the payload from the same place yields a false
    "registered but file missing" — 11 of those were measured on real mods.
    """
    cfg = _reference(tmp_path)
    packed = tmp_path / "packed_mod"
    _write_cat(packed, "ext_01.cat", [
        ("index/macros.xml",
         _index_xml(MACRO, "extensions\\packed_mod\\assets\\ship").encode()),
        ("assets/ship.xml", f'<macros><macro name="{MACRO}"/></macros>'.encode()),
    ])
    index = _resolve.build_index(cfg, [packed], _resolve.MACRO_INDEX)

    located = _resolve.read_indexed(index, MACRO)
    assert located is not None and located.packed, "packed macro file was not found"
    assert _resolve.macro_component_links(MACRO, index, {}) == [], \
        "a macro shipped inside the mod's own .cat was reported missing"


def test_a_genuinely_missing_macro_file_is_still_an_error(tmp_path):
    """The other side of the same coin — packed-awareness must not blanket-excuse."""
    cfg = _reference(tmp_path)
    packed = tmp_path / "packed_mod"
    _write_cat(packed, "ext_01.cat", [
        ("index/macros.xml",
         _index_xml(MACRO, "extensions\\packed_mod\\assets\\nowhere").encode()),
    ])
    index = _resolve.build_index(cfg, [packed], _resolve.MACRO_INDEX)
    msgs = _resolve.macro_component_links(MACRO, index, {})
    assert msgs and "file missing" in msgs[0]


def test_connections_of_distinguishes_unparseable_from_empty():
    assert _resolve.connections_of(b"<components><connection name='a'/></components>") == {"a"}
    assert _resolve.connections_of(b"<components/>") == set()
    assert _resolve.connections_of(b"<compo") is None, \
        "un-evaluable must not read as 'this component has zero connections'"

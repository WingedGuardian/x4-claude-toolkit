"""AUDIT-2026-09-24 -- merge / resolve / diff findings, pinned as strict xfails.

Every test here asserts the CORRECT behaviour and runs the real subject on a
tmp_path fixture. Each is `xfail(strict=True)`: it must fail today, and the day a
fix lands it XPASSes, which strict mode turns into a failure -- so whoever fixes
the finding must also delete the marker, and cannot do so silently.

IDs and verdicts live in `AUDIT-2026-09-24.md`. MG-6 was WITHDRAWN and has no
test; the Tier-B "uninstalled mod loads LAST" half of LO-6 is NEEDS-DESIGN and has
no test either.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from lxml import etree

from x4validate import _diff, _diffcli, _merge, _resolve


def _xf(id_: str, why: str):
    return pytest.mark.xfail(strict=True, reason=f"AUDIT-2026-09-24 {id_}: {why}")


def _apply(base: str, diff: str):
    tree = _merge.parse_bytes(base.encode("utf-8"))
    ops = _merge.apply_diff(tree, _merge.parse_bytes(diff.encode("utf-8")))
    return tree, ops


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def _mod(root: Path, name: str, files: dict[str, str]) -> Path:
    d = root / name
    _write(d / "content.xml", f'<content id="{name}" version="100"/>')
    for vpath, text in files.items():
        _write(d / vpath, text)
    return d


def _write_cat(mod_dir: Path, cat_name: str, members) -> None:
    mod_dir.mkdir(parents=True, exist_ok=True)
    lines, blob = [], bytearray()
    for vpath, data in members:
        lines.append(f"{vpath} {len(data)} 1700000000 {hashlib.md5(data).hexdigest()}")
        blob += data
    (mod_dir / cat_name).write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    (mod_dir / cat_name).with_suffix(".dat").write_bytes(bytes(blob))


# --- MG-1: text() selectors ---------------------------------------------------

_TEXT_BASE = '<wares><ware id="a">hello<x/></ware></wares>'


@pytest.mark.parametrize("op", [
    "<replace sel=\"//ware[@id='a']/text()\">bye</replace>",
    "<remove sel=\"//ware[@id='a']/text()\"/>",
    "<add sel=\"//ware[@id='a']/text()\"><y/></add>",
], ids=["replace", "remove", "add"])
def test_text_node_selector_is_reported_not_raised(op):
    tree, ops = _apply(_TEXT_BASE, f"<diff>{op}</diff>")
    assert len(ops) == 1
    if ops[0].ok:
        # If the engine model claims it applied, the tree must show it.
        assert etree.tostring(tree) != _TEXT_BASE.encode("utf-8")
    else:
        assert ops[0].detail, "a refused op must say why"


# --- MG-2: <add> payload shapes that change nothing ----------------------------

def test_add_with_text_only_payload_is_not_a_silent_ok():
    base = '<wares><ware id="b"/></wares>'
    tree, ops = _apply(base, "<diff><add sel=\"//ware[@id='b']\">sometext</add></diff>")
    changed = etree.tostring(tree) != etree.tostring(_merge.parse_bytes(base.encode()))
    assert changed or not ops[0].ok, (
        "reported applied, yet the tree is byte-identical: " + ops[0].detail)


def test_attribute_add_with_element_payload_is_refused_not_blanked():
    tree, ops = _apply('<wares><ware id="a" q="1"/></wares>',
                       "<diff><add sel=\"//ware[@id='a']\" type=\"@q\"><z/></add></diff>")
    assert not ops[0].ok, "an attribute takes text; the element payload was discarded"
    assert tree.find("ware").get("q") == "1", "the existing value was blanked"


# --- MG-3: packed-only DLC index ----------------------------------------------

@_xf("MG-3", "build_index reads base/DLC indexes loose-only; a packed-only DLC registers nothing")
def test_packed_only_dlc_index_entries_are_registered_and_readable(tmp_path, monkeypatch):
    ref = tmp_path / "reference"
    _write(ref / "index" / "macros.xml", "<index/>")
    game = tmp_path / "game"
    macro_bytes = b"<macros><macro name='ship_dlc_macro'/></macros>"
    _write_cat(game / "extensions" / "ego_dlc_mini_01", "ext_01.cat", [
        ("index/macros.xml",
         b'<index><entry name="ship_dlc_macro" '
         b'value="extensions\\ego_dlc_mini_01\\assets\\units\\ship_dlc_macro"/></index>'),
        ("assets/units/ship_dlc_macro.xml", macro_bytes),
    ])
    monkeypatch.setattr(_merge, "GAME_ROOT", game)
    monkeypatch.setattr(_merge, "REFERENCE", ref)
    cfg = _merge.Config(reference=ref)
    assert [p.name for p in cfg.dlc_dirs()] == ["ego_dlc_mini_01"], "precondition"

    index = _resolve.build_index(cfg, [], _resolve.MACRO_INDEX)
    assert "ship_dlc_macro" in index, "packed-only DLC index was never read"
    located = _resolve.read_indexed(index, "ship_dlc_macro")
    assert located is not None and located.data == macro_bytes


# --- MG-4: foreign extensions/<X>/ prefix ------------------------------------

@_xf("MG-4", "_strip_mod_index_prefix strips ANOTHER mod's extensions/<X>/ prefix")
def test_mod_index_value_naming_another_mod_resolves_into_that_mod(tmp_path):
    ref = tmp_path / "reference"
    _write(ref / "index" / "macros.xml", "<index/>")
    cfg = _merge.Config(reference=ref)
    ext = tmp_path / "extensions"
    theirs = b"<macros><macro name='m' owner='other_mod'/></macros>"
    other = _mod(ext, "other_mod", {})
    (other / "assets").mkdir()
    (other / "assets" / "ship.xml").write_bytes(theirs)
    mine = _mod(ext, "mine", {
        "index/macros.xml":
            '<index><entry name="m" value="extensions\\other_mod\\assets\\ship"/></index>',
        # A same-named file in the registering mod must NOT be what resolves: the
        # engine reads the value game-root-relative, i.e. inside other_mod.
        "assets/ship.xml": "<macros><macro name='m' owner='mine'/></macros>",
    })
    index = _resolve.build_index(cfg, [mine], _resolve.MACRO_INDEX)
    located = _resolve.read_indexed(index, "m")
    assert located is not None and located.data == theirs


# --- MG-5: tail text ---------------------------------------------------------

@pytest.mark.parametrize("op,want", [
    ('<remove sel="//a"/>', b"<r>TAIL<b/></r>"),
    ('<replace sel="//a"><c/></replace>', b"<r><c/>TAIL<b/></r>"),
], ids=["remove", "replace"])
def test_sibling_text_survives_remove_and_replace(op, want):
    tree, ops = _apply("<r><a/>TAIL<b/></r>", f"<diff>{op}</diff>")
    assert ops[0].ok
    assert etree.tostring(tree) == want


# --- LO-6: DLC order ---------------------------------------------------------

def test_dlc_dirs_orders_packed_and_unpacked_dlc_by_one_rule(tmp_path, monkeypatch):
    ref = tmp_path / "reference"
    (ref / "extensions" / "ego_dlc_zed").mkdir(parents=True)
    game = tmp_path / "game"
    _write_cat(game / "extensions" / "ego_dlc_abc", "ext_01.cat",
               [("libraries/god.xml", b"<diff/>")])
    monkeypatch.setattr(_merge, "GAME_ROOT", game)
    monkeypatch.setattr(_merge, "REFERENCE", ref)
    names = [p.name for p in _merge.Config(reference=ref).dlc_dirs()]
    assert set(names) == {"ego_dlc_abc", "ego_dlc_zed"}, "precondition"
    # abc sorts first under ASCII AND under the engine's case-insensitive rule
    # (LO-1), so this pins only "one sort across both kinds", not which sort.
    assert names == ["ego_dlc_abc", "ego_dlc_zed"]


# --- DF-1: text-valued ops ----------------------------------------------------

@_xf("DF-1", "_diff._index compares attributes only; an op's TEXT value change is invisible")
def test_a_changed_op_text_value_is_a_changed_file(tmp_path):
    sel = "//ware[@id='x']/price/@min"
    a = _mod(tmp_path, "a", {"libraries/wares.xml": f'<diff><replace sel="{sel}">5</replace></diff>'})
    b = _mod(tmp_path, "b", {"libraries/wares.xml": f'<diff><replace sel="{sel}">999</replace></diff>'})
    md = _diff.diff_mods(a, b)
    assert not md.unreadable
    assert [f.vpath for f in md.changed()] == ["libraries/wares.xml"]


# --- DF-2: stacked baseline over diff documents --------------------------------

@_xf("DF-2", "read_merged returns None when the first supplying layer ships a <diff>")
def test_stacked_baseline_compares_a_file_the_core_ships_as_a_diff(tmp_path):
    core = _mod(tmp_path, "core", {
        "libraries/wares.xml": "<diff><add sel=\"/wares\"><ware id=\"q\"/></add></diff>"})
    sub = _mod(tmp_path, "sub", {"md/unrelated.xml": "<mdscript name='u'/>"})
    new = _mod(tmp_path, "new", {
        "libraries/wares.xml":
            "<diff><add sel=\"/wares\"><ware id=\"q\"/><ware id=\"r\"/></add></diff>"})
    md = _diff.diff_mods([core, sub], new)
    # Today: "the OLD copy would not parse" -- a false statement about a
    # well-formed file, and the edit (ware r) is never reported.
    assert md.unreadable == []
    assert [f.vpath for f in md.changed()] == ["libraries/wares.xml"]


# --- DF-3: node identity -------------------------------------------------------

@_xf("DF-3", "name-before-id keys + positional suffix: one inserted ware rewrites untouched ones")
def test_inserting_one_ware_changes_no_untouched_ware(tmp_path):
    # Vanilla wares.xml: 1,397 wares, every one carries @name, 101 of them in 49
    # duplicated-name groups (MEASURED 2026-09-24) -- so this is the real shape.
    old = _mod(tmp_path, "old", {"libraries/wares.xml":
        '<wares><ware id="a" name="{1,1}" price="1"/>'
        '<ware id="b" name="{1,1}" price="2"/></wares>'})
    new = _mod(tmp_path, "new", {"libraries/wares.xml":
        '<wares><ware id="new" name="{1,1}" price="9"/>'
        '<ware id="a" name="{1,1}" price="1"/><ware id="b" name="{1,1}" price="2"/></wares>'})
    (fd,) = _diff.diff_mods(old, new).changed()
    assert fd.attr_changes == [], f"phantom edits on untouched wares: {fd.attr_changes}"
    assert len(fd.nodes_added) == 1 and not fd.nodes_removed


# --- DF-4: CLI rendering ---------------------------------------------------------

def _df4_mods(tmp_path):
    old = _mod(tmp_path, "old", {"libraries/a.xml": '<wares><ware id="a" p="1"/></wares>'})
    new = _mod(tmp_path, "new", {
        "libraries/a.xml": '<wares><ware id="a" p="1"/><ware id="z"/></wares>',
        "libraries/added.xml": '<wares><ware id="k"/></wares>'})
    return old, new


@_xf("DF-4", "--file on an ADDED file prints nothing about that file")
def test_file_flag_on_an_added_file_says_it_was_added(tmp_path, capsys):
    old, new = _df4_mods(tmp_path)
    _diffcli.main([str(old), str(new), "--file", "libraries/added.xml"])
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if "libraries/added.xml" in ln]
    assert lines and any("add" in ln.lower() for ln in lines), out


@_xf("DF-4", "'total attr changes' also counts node adds/removes")
def test_attr_change_total_does_not_count_node_additions(tmp_path, capsys):
    old, new = _df4_mods(tmp_path)
    _diffcli.main([str(old), str(new)])
    out = capsys.readouterr().out
    # The only change to a.xml is one added NODE; no attribute changed.
    m = re.search(r"total attr changes:\s*(\d+)", out)
    assert m is None or m.group(1) == "0", out

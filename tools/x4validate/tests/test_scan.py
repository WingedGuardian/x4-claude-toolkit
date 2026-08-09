"""`_scan.iter_mod_xml` — the one loop the six hand-rolled copies collapsed into.

The contract it has that none of the copies did: **a file it cannot parse is
reported, not dropped.** Measured before the fix, `_check.iter_mod_xml_roots`
silently discarded 12 files across 3 installed mods.

Mutation-verified: with the `unreadable.append(...)` reverted to a bare
`continue`, the reporting tests here fail.
"""

from __future__ import annotations

import hashlib

from x4validate import _check, _merge, _scan


def _write_cat(mod_dir, cat_name, members):
    mod_dir.mkdir(parents=True, exist_ok=True)
    cat = mod_dir / cat_name
    lines, blob = [], bytearray()
    for vpath, data in members:
        lines.append(f"{vpath} {len(data)} 1700000000 {hashlib.md5(data).hexdigest()}")
        blob += data
    cat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cat.with_suffix(".dat").write_bytes(bytes(blob))


def _mod(tmp_path, files: dict[str, str]):
    mod = tmp_path / "mod"
    mod.mkdir(parents=True, exist_ok=True)
    # A real extension always has a manifest — X4 discovers mods by it, and
    # check_readability now gates on its absence. Fixtures that omitted it were
    # describing a folder the engine would never load.
    files = {"content.xml": '<content id="mod"/>', **files}
    for rel, text in files.items():
        f = mod / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return mod


def test_unparseable_loose_file_is_recorded_not_dropped(tmp_path):
    mod = _mod(tmp_path, {"md/good.xml": "<mdscript/>", "md/bad.xml": "<mdscript"})
    bad: list = []
    seen = [v for v, _ in _scan.iter_mod_xml(mod, unreadable=bad)]
    # content.xml is real XML the scanner genuinely yields; the point of this test
    # is that the good file survives and the bad one is RECORDED, not dropped.
    assert seen == ["content.xml", "md/good.xml"]
    assert len(bad) == 1 and bad[0].vpath == "md/bad.xml" and not bad[0].packed


def test_unparseable_packed_file_is_recorded(tmp_path):
    mod = tmp_path / "packed"
    _write_cat(mod, "ext_01.cat", [("md/ok.xml", b"<mdscript/>"),
                                   ("md/broken.xml", b"<mdscript")])
    bad: list = []
    seen = [v for v, _ in _scan.iter_mod_xml(mod, unreadable=bad)]
    assert seen == ["md/ok.xml"]
    assert len(bad) == 1 and bad[0].packed


def test_a_malformed_loose_file_shadows_its_packed_twin(tmp_path):
    """The engine does not fall through to the packed copy, so neither do we.

    Silently using the packed twin would model a file the game never reads —
    a wrong answer that looks like a clean one.
    """
    mod = tmp_path / "both"
    _write_cat(mod, "ext_01.cat", [("md/x.xml", b"<mdscript name='packed'/>")])
    (mod / "md").mkdir(parents=True, exist_ok=True)
    (mod / "md" / "x.xml").write_text("<mdscript", encoding="utf-8")
    bad: list = []
    assert [v for v, _ in _scan.iter_mod_xml(mod, unreadable=bad)] == []
    assert len(bad) == 1 and not bad[0].packed


def test_predicate_narrows_the_walk_without_losing_files(tmp_path):
    mod = _mod(tmp_path, {"md/a.xml": "<mdscript/>", "libraries/b.xml": "<wares/>",
                          "aiscripts/c.xml": "<aiscript/>"})
    got = {v for v, _ in _scan.iter_mod_xml(mod, _scan.under("md/", "aiscripts/"))}
    assert got == {"md/a.xml", "aiscripts/c.xml"}


def test_count_line_states_its_bound():
    assert _scan.count_line(5, 5, "thing(s)") == "5 thing(s)"
    assert "TRUNCATED" in _scan.count_line(200, 2431, "ware(s)")
    assert "--top" in _scan.count_line(30, 90, "file(s)", "--top")


# --- check_readability: the mod-facing half ----------------------------------

def _ref(tmp_path):
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_text("<wares/>", encoding="utf-8")
    return _merge.Config(reference=ref)


def test_malformed_file_at_a_content_path_warns_and_is_skipped(tmp_path):
    mod = _mod(tmp_path, {"t/0001-l088.xml": "<diff><add><t/></t></add></diff>"})
    report = _check.Report()
    _check.check_readability(mod, _ref(tmp_path), report)
    assert any("t/0001-l088.xml" in s.why for s in report.skipped)
    assert [f.category for f in report.findings] == ["parse"]


def test_malformed_file_in_a_scratch_dir_is_skipped_but_not_warned(tmp_path):
    """VRO ships 10 broken files under tmp/, backup/ and md_debug/.

    The engine never loads those paths, so warning about them would make the
    check 83% noise on the real modlist — but it still did not examine them,
    so the skip stays.
    """
    mod = _mod(tmp_path, {"assets/macros/tmp/x_macro.xml": "<macros"})
    report = _check.Report()
    _check.check_readability(mod, _ref(tmp_path), report)
    assert any("tmp/x_macro.xml" in s.why for s in report.skipped)
    assert report.findings == []


def test_a_clean_mod_produces_neither(tmp_path):
    """Both sides asserted: a test that only pins the new behaviour would pass
    against a check that flags everything."""
    mod = _mod(tmp_path, {"md/fine.xml": "<mdscript/>"})
    report = _check.Report()
    _check.check_readability(mod, _ref(tmp_path), report)
    assert report.skipped == [] and report.findings == []


# --------------------------------------------------------------------------
# iter_mod_text — the packed-aware TEXT walk.
#
# Real incident (2026-08-09): `_migration.scan_mod` walked `mod_dir.rglob`
# alone, so `--update` scanned nothing at all on a PACKED mod and reported a
# clean 9.0 port. Measured on `sn_mod_support_apis` — the very mod whose
# `Lua_Loader` the check exists to flag — which ships ONE loose file
# (content.xml) and 4 `Lua_Loader.Load` hits inside `ext_01.cat`: the tool
# reported 0. Also the only route to `.lua`, which `iter_mod_xml` can never
# yield because it is not XML.
# --------------------------------------------------------------------------

def _write_cat(mod_dir, cat_name, members):
    """Write a .cat/.dat pair. *members* = list of (vpath, bytes)."""
    mod_dir.mkdir(parents=True, exist_ok=True)
    cat = mod_dir / cat_name
    lines, blob = [], bytearray()
    for vpath, data in members:
        lines.append(f"{vpath} {len(data)} 1700000000 {hashlib.md5(data).hexdigest()}")
        blob += data
    cat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cat.with_suffix(".dat").write_bytes(bytes(blob))


def test_iter_mod_text_reads_lua_inside_the_catalog(tmp_path):
    mod = tmp_path / "packedmod"
    _write_cat(mod, "ext_01.cat", [
        ("ui/lua_loader.lua", b'RegisterEvent("Lua_Loader.Load", f)\n'),
        ("md/thing.xml", b"<mdscript/>\n"),
    ])
    got = {v: (t, packed) for v, t, packed in
           _scan.iter_mod_text(mod, (".xml", ".lua"))}
    assert set(got) == {"ui/lua_loader.lua", "md/thing.xml"}
    assert "Lua_Loader.Load" in got["ui/lua_loader.lua"][0]
    assert got["ui/lua_loader.lua"][1] is True          # reported as packed


def test_iter_mod_text_loose_file_shadows_its_packed_twin(tmp_path):
    """Same ordering contract as iter_mod_xml — the engine prefers loose."""
    mod = tmp_path / "mod"
    _write_cat(mod, "ext_01.cat", [("ui/x.lua", b"PACKED\n")])
    (mod / "ui").mkdir(parents=True, exist_ok=True)
    (mod / "ui/x.lua").write_text("LOOSE\n", encoding="utf-8")
    got = [(v, t.strip(), p) for v, t, p in _scan.iter_mod_text(mod, (".lua",))]
    assert got == [("ui/x.lua", "LOOSE", False)]


def test_migration_scan_sees_a_packed_mod(tmp_path):
    from x4validate import _migration
    mod = tmp_path / "packedmod"
    _write_cat(mod, "ext_01.cat", [
        ("ui/lua_loader.lua", b'RegisterEvent("Lua_Loader.Load", on_Load)\n'),
    ])
    found = _migration.scan_mod(mod)
    assert len(found) == 1, [f.note for f in found]
    assert found[0].file == "ui/lua_loader.lua"
    assert found[0].line == 1
    assert found[0].packed is True


def test_migration_scan_still_sees_a_loose_mod(tmp_path):
    """Both sides asserted — the packed fix must not cost the loose path."""
    from x4validate import _migration
    mod = tmp_path / "loosemod"
    (mod / "ui").mkdir(parents=True)
    (mod / "ui/boot.lua").write_text('x = "Lua_Loader.Load"\n', encoding="utf-8")
    found = _migration.scan_mod(mod)
    assert len(found) == 1 and found[0].packed is False
    assert found[0].file == "ui/boot.lua"


def test_migration_scan_clean_mod_reports_nothing(tmp_path):
    from x4validate import _migration
    mod = tmp_path / "cleanmod"
    _write_cat(mod, "ext_01.cat", [("md/ok.xml", b"<mdscript/>\n")])
    assert _migration.scan_mod(mod) == []

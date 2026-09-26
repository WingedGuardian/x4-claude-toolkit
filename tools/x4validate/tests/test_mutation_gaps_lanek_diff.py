"""Mutation-campaign gaps in `_diff` / `_threeway`, lane K (2026-09-26). Each test names the
surviving mutant it was written to kill and was verified to FAIL with it applied and PASS
without. The .xsd cases need a PACKED member: the loose enumerator only globs *.xml, while
the catalog reader admits .xml AND .xsd -- so a packed schema is the only way one arrives."""
from __future__ import annotations

import hashlib
from pathlib import Path

from x4validate import _diff, _threeway


def _write_cat(mod_dir: Path, cat_name: str, members) -> None:
    mod_dir.mkdir(parents=True, exist_ok=True)
    lines, blob = [], bytearray()
    for vpath, data in members:
        lines.append(f"{vpath} {len(data)} 1700000000 {hashlib.md5(data).hexdigest()}")
        blob += data
    (mod_dir / cat_name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    (mod_dir / cat_name).with_suffix(".dat").write_bytes(bytes(blob))


def _loose(mod_dir: Path, vpath: str, text: str) -> None:
    p = mod_dir / vpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_diff_mods_ignores_a_packed_xsd(tmp_path):
    """D8: a schema shipped only by the NEW side is not reported as an added file."""
    old = tmp_path / "old"
    new = tmp_path / "new"
    _loose(old, "libraries/w.xml", "<wares/>")
    _loose(new, "libraries/w.xml", "<wares/>")
    _write_cat(new, "ext_01.cat", [("libraries/s.xsd", b'<schema v="1"/>')])
    md = _diff.diff_mods(old, new)
    assert [f.vpath for f in md.files] == []


def test_three_way_does_not_compare_a_shared_packed_xsd(tmp_path):
    """T8: a schema both base and archive ship, edited by the author, is skipped --
    neither counted as compared nor reported as an author edit."""
    base, arch, cur = tmp_path / "base", tmp_path / "arch", tmp_path / "cur"
    _write_cat(base, "ext_01.cat", [("libraries/s.xsd", b'<schema v="1"/>')])
    _write_cat(arch, "ext_01.cat", [("libraries/s.xsd", b'<schema v="2"/>')])
    cur.mkdir()
    r = _threeway.three_way(base, arch, cur)
    assert r.documents_compared == 0
    assert r.author_edits == []


def test_three_way_records_two_paths_collapsing_onto_one_key(tmp_path):
    """T9: an archive shipping both the plain path and the nested alias of the SAME
    document collapses them onto one key; that must be recorded as a collision,
    not silently resolved by letting the later path overwrite the first."""
    base, arch, cur = tmp_path / "base", tmp_path / "arch", tmp_path / "cur"
    _loose(base, "libraries/w.xml", '<wares><ware id="a" v="1"/></wares>')
    _loose(arch, "libraries/w.xml", '<wares><ware id="a" v="2"/></wares>')
    _loose(arch, "extensions/base/libraries/w.xml", '<wares><ware id="a" v="3"/></wares>')
    cur.mkdir()
    r = _threeway.three_way(base, arch, cur)
    assert len(r.key_collisions) == 1, r.key_collisions
    assert "libraries/w.xml" in r.key_collisions[0]

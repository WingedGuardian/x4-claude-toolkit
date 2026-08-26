r"""The fingerprint must say WHAT moved, and must MOVE when a mod's files move.

Two defects are pinned here, and they are different in kind.

**F56 - the digest says THAT, never WHAT.** `hash_content` folds 129 folders into
one 16-char digest and discards the per-folder inputs. MEASURED 2026-08-25:
localising a single changed mod (`distances`, v160 -> v170) took nine
investigative steps and three false leads. It was solved only because that mod
happened to bump its `version`; a content-identical rewrite with a new mtime
would have been undiagnosable from our artifacts.

**The larger one, found while planning the F56 fix: the content axis could not
see a mod's FILES change at all.** It stats only each folder's `content.xml`.
MEASURED 2026-08-25: **72 of 121 non-DLC mods (59.5%)** have at least one file
newer than their own manifest, because editing an overlay file and redeploying
does not touch the manifest. Every artifact therefore reported **FRESH** while
describing a different tree - a false FRESH, which fails in the UNSAFE direction,
unlike F53's false STALE.

**F43 - the axis could not see an enable/disable either**, because toggling a mod
in-game rewrites only the PROFILE manifest. MEASURED on two archived logs 9 h
apart: identical content fingerprint `01639715767615e2`, engine loaded 66 vs 67
mods.

WHY THE FILTER IS CORRECTNESS, NOT SPEED. Only `.xml/.cat/.dat/.lua` count.
MEASURED: 8 mods would otherwise move the fingerprint purely from README/CHANGES/
LICENCE/live_editor_log.json churn - manufactured staleness, which trains the
reader to ignore the banner. Each "does not move" assertion below is therefore
PAIRED with a positive twin that does move (F54 mitigation 2: a detector that has
been disabled must show up as a failure, not as a pass).
"""

import os
import shutil
import sqlite3

import pytest

from x4validate import _freshness, _merge


def _touch(p, when):
    os.utime(p, (when, when))


def _world(tmp_path, profile_pairs=()):
    """A reference tree, two mods, and a profile content.xml."""
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_bytes(b"<wares/>")
    ext = tmp_path / "extensions"
    for name, mid in (("mod_a", "id_a"), ("amphitrite", "ws_3616342050")):
        d = ext / name
        (d / "libraries").mkdir(parents=True)
        (d / "content.xml").write_bytes(
            ('<content id="' + mid + '" version="100"/>').encode())
        (d / "libraries" / "god.xml").write_bytes(b"<god/>")
        (d / "README.md").write_bytes(b"hello")
    prof = tmp_path / "profile_content.xml"
    rows = "".join('<extension id="' + i + '" enabled="' + str(e).lower() + '"/>'
                   for i, e in profile_pairs)
    prof.write_bytes(("<content>" + rows + "</content>").encode())
    return _merge.Config(reference=ref, overlays=()), ext, prof


def _h(cfg, ext, prof):
    return _freshness.hash_content(cfg.reference, ext, profile=prof)


def _by_folder(cfg, ext, prof):
    return {r["folder"]: r for r in
            _freshness.content_detail(cfg.reference, ext, profile=prof)}


# --- the file-level blind spot, and its falsification twin --------------------

def test_a_file_only_edit_MOVES_the_content_axis(tmp_path):
    """THE new defect. Editing an overlay file and redeploying must not read FRESH.

    RED against the pre-fix code, which stats only content.xml."""
    cfg, ext, prof = _world(tmp_path)
    before = _h(cfg, ext, prof)
    (ext / "mod_a" / "libraries" / "god.xml").write_bytes(b"<god changed='1'/>")
    assert _h(cfg, ext, prof) != before, (
        "a changed mod FILE must move the content axis; stating only content.xml "
        "reports FRESH for 72 of 121 real mods")


def test_a_README_touch_does_NOT_move_the_content_axis(tmp_path):
    """The twin. Non-engine churn must stay silent, or we manufacture staleness.

    Meaningless alone -- it also passes when nothing is detected at all. It is
    load-bearing only PAIRED with the test above, which proves the detector is on."""
    cfg, ext, prof = _world(tmp_path)
    before = _h(cfg, ext, prof)
    (ext / "mod_a" / "README.md").write_bytes(b"a much longer readme, rewritten")
    assert _h(cfg, ext, prof) == before, (
        "README/CHANGES/LICENCE churn must NOT move the hash -- MEASURED, 8 real "
        "mods would otherwise report stale for nothing")


def test_a_NEW_engine_file_moves_the_axis_and_a_new_readme_does_not(tmp_path):
    cfg, ext, prof = _world(tmp_path)
    before = _h(cfg, ext, prof)
    (ext / "mod_a" / "NOTES.txt").write_bytes(b"notes")
    assert _h(cfg, ext, prof) == before
    (ext / "mod_a" / "libraries" / "new.xml").write_bytes(b"<new/>")
    assert _h(cfg, ext, prof) != before


def test_back_dated_files_are_STILL_detected(tmp_path):
    """The `distances` shape: 26 files rewritten and back-dated to two days prior.

    A max(mtime) signal is exactly what back-dating defeats -- `find -newermt`
    already failed on this for that reason. The vector hashes sorted
    (relpath, mtime, size) triples, so a mtime moving BACKWARD still moves it."""
    cfg, ext, prof = _world(tmp_path)
    god = ext / "mod_a" / "libraries" / "god.xml"
    _touch(god, 1_700_000_000)
    before = _h(cfg, ext, prof)
    _touch(god, 1_600_000_000)          # strictly OLDER
    assert _h(cfg, ext, prof) != before, "a backward mtime move must still register"


# --- localisation: the vector -------------------------------------------------

def test_content_detail_NAMES_the_changed_mod(tmp_path):
    cfg, ext, prof = _world(tmp_path)
    before = _by_folder(cfg, ext, prof)
    (ext / "mod_a" / "libraries" / "god.xml").write_bytes(b"<god changed='1'/>")
    after = _by_folder(cfg, ext, prof)
    assert before["mod_a"]["tree_sha"] != after["mod_a"]["tree_sha"]
    assert before["amphitrite"]["tree_sha"] == after["amphitrite"]["tree_sha"], (
        "only the mod that actually changed may move")


def test_an_MTIME_ONLY_manifest_rewrite_is_localised(tmp_path):
    """The case that defeated us: identical bytes, new mtime, no version bump."""
    cfg, ext, prof = _world(tmp_path)
    man = ext / "mod_a" / "content.xml"
    body = man.read_bytes()
    before = _by_folder(cfg, ext, prof)
    man.write_bytes(body)                       # byte-identical
    _touch(man, 1_800_000_000)
    after = _by_folder(cfg, ext, prof)
    assert before["mod_a"]["manifest_mtime"] != after["mod_a"]["manifest_mtime"]
    assert before["mod_a"]["manifest_sha"] == after["mod_a"]["manifest_sha"], (
        "manifest_sha separates TOUCHED from actually CHANGED -- that distinction "
        "is the whole point of storing it beside the mtime")


def test_detail_records_every_mod_with_a_stable_order(tmp_path):
    cfg, ext, prof = _world(tmp_path)
    d = _freshness.content_detail(cfg.reference, ext, profile=prof)
    assert [r["folder"] for r in d] == sorted(r["folder"] for r in d)
    assert {r["folder"] for r in d} == {"mod_a", "amphitrite"}


def test_a_folder_with_NO_manifest_stays_in_the_denominator(tmp_path):
    cfg, ext, prof = _world(tmp_path)
    (ext / "orphan").mkdir()
    (ext / "orphan" / "libraries").mkdir()
    (ext / "orphan" / "libraries" / "x.xml").write_bytes(b"<x/>")
    rec = _by_folder(cfg, ext, prof)["orphan"]
    assert rec["no_manifest"] is True
    assert rec["manifest_sha"] is None
    assert rec["files"] == 1, "its files still count -- it must not vanish"


# --- F43: the profile enable-list ---------------------------------------------

def test_a_profile_ENABLE_TOGGLE_moves_the_content_axis(tmp_path):
    """F43. Toggling in-game rewrites only the PROFILE manifest."""
    cfg, ext, prof_on = _world(tmp_path, [("id_a", True)])
    prof_off = tmp_path / "profile_off.xml"
    prof_off.write_bytes(
        b'<content><extension id="id_a" enabled="false"/></content>')
    on = _freshness.hash_content(cfg.reference, ext, profile=prof_on)
    off = _freshness.hash_content(cfg.reference, ext, profile=prof_off)
    assert on != off, "disabling a mod changes what the engine loads; the axis must move"


def test_the_profile_join_is_by_MANIFEST_ID_not_FOLDER_NAME(tmp_path):
    """gotcha #30b. `amphitrite` is the FOLDER, `ws_3616342050` the manifest id.

    A profile entry naming the FOLDER must not be able to disable it."""
    cfg, ext, by_folder = _world(tmp_path, [("amphitrite", False)])
    by_id = tmp_path / "p2.xml"
    by_id.write_bytes(
        b'<content><extension id="ws_3616342050" enabled="false"/></content>')
    base = _freshness.hash_content(cfg.reference, ext, profile=None)
    assert _freshness.hash_content(cfg.reference, ext, profile=by_folder) == base, (
        "matching by folder name must be inert -- that is the xspvro trap")
    assert _freshness.hash_content(cfg.reference, ext, profile=by_id) != base, (
        "...and the correctly-spelled manifest id must take effect")


def test_a_mod_ABSENT_from_the_profile_defaults_to_ENABLED(tmp_path):
    """gotcha #30a. X4 adds an unseen folder as ENABLED; 54 of 115 are absent."""
    cfg, ext, empty = _world(tmp_path, [])
    recs = _by_folder(cfg, ext, empty)
    assert all(r["enabled_in_profile"] for r in recs.values())


# --- every installed ROOT, not just one ---------------------------------------

def test_all_installed_roots_are_covered(tmp_path):
    """`hash_content` walked ONE dir, so profile/Workshop roots were invisible."""
    cfg, ext, prof = _world(tmp_path)
    other = tmp_path / "profile_extensions"
    (other / "mod_z" / "libraries").mkdir(parents=True)
    (other / "mod_z" / "content.xml").write_bytes(b'<content id="id_z"/>')
    (other / "mod_z" / "libraries" / "g.xml").write_bytes(b"<g/>")
    one = _freshness.hash_content(cfg.reference, [ext], profile=prof)
    two = _freshness.hash_content(cfg.reference, [ext, other], profile=prof)
    assert one != two
    folders = {r["folder"] for r in
               _freshness.content_detail(cfg.reference, [ext, other], profile=prof)}
    assert folders == {"mod_a", "amphitrite", "mod_z"}


def test_a_single_path_is_still_accepted(tmp_path):
    """Backwards compatibility: 4 production call sites and 15 tests pass one Path."""
    cfg, ext, prof = _world(tmp_path)
    assert (_freshness.hash_content(cfg.reference, ext, profile=prof)
            == _freshness.hash_content(cfg.reference, [ext], profile=prof))


# --- persistence: additive, and never flip an old artifact to UNKNOWN ---------

def test_a_VECTORLESS_artifact_is_still_FRESH_or_STALE_never_unknown(tmp_path):
    """The riskiest part of the change. Every artifact on disk today lacks a
    vector; none of them may become UNKNOWN because of that alone."""
    con = sqlite3.connect(tmp_path / "s.sqlite")
    con.execute("create table meta (key text primary key, value text)")
    con.execute("insert into meta values ('fingerprint_content','abc')")
    con.execute("insert into meta values ('fingerprint_engine','def')")
    con.commit()
    stored = _freshness.read_sqlite(con)
    assert stored is not None, "a pre-vector artifact must still READ"
    assert stored.get("detail") is None
    assert _freshness.compare(stored, {"content": "abc", "engine": "def"},
                              engine_dependent=True).fresh
    assert not _freshness.compare(stored, {"content": "zzz", "engine": "def"},
                                  engine_dependent=True).fresh


def test_the_detail_roundtrips_through_sqlite_and_the_sidecar(tmp_path):
    cfg, ext, prof = _world(tmp_path)
    fp = _freshness.fingerprint(cfg, ext, profile=prof)
    assert fp.get("detail"), "fingerprint must carry the vector"

    con = sqlite3.connect(tmp_path / "s.sqlite")
    con.execute("create table meta (key text primary key, value text)")
    con.execute("insert into meta values ('active_mods','2')")
    _freshness.stamp_sqlite(con, fp)
    con.commit()
    back = _freshness.read_sqlite(con)
    assert back["detail"] == fp["detail"]
    assert dict(con.execute("select * from meta"))["active_mods"] == "2", "additive"

    tsv = tmp_path / "md_xref.tsv"
    tsv.write_text("a\tb\n", encoding="utf-8")
    _freshness.stamp_sidecar(tsv, fp)
    assert _freshness.read_sidecar(tsv)["detail"] == fp["detail"]
    assert tsv.read_text(encoding="utf-8") == "a\tb\n", "payload untouched"


# --- the localiser itself -----------------------------------------------------

def test_diff_detail_classifies_every_kind_of_change(tmp_path):
    cfg, ext, prof = _world(tmp_path)
    before = _freshness.content_detail(cfg.reference, ext, profile=prof)

    (ext / "mod_a" / "libraries" / "god.xml").write_bytes(b"<god changed='1'/>")
    man = ext / "amphitrite" / "content.xml"
    man.write_bytes(man.read_bytes())
    _touch(man, 1_900_000_000)
    (ext / "mod_new" / "libraries").mkdir(parents=True)
    (ext / "mod_new" / "content.xml").write_bytes(b'<content id="id_new"/>')

    after = _freshness.content_detail(cfg.reference, ext, profile=prof)
    changes = {c["folder"]: c for c in _freshness.diff_detail(before, after)}
    assert changes["mod_a"]["kind"] == "content"
    assert changes["amphitrite"]["kind"] == "touched"
    assert changes["mod_new"]["kind"] == "added"
    assert len(changes) == 3


def test_diff_detail_reports_REMOVED_and_names_the_files(tmp_path):
    cfg, ext, prof = _world(tmp_path)
    before = _freshness.content_detail(cfg.reference, ext, profile=prof)
    shutil.rmtree(ext / "amphitrite")
    (ext / "mod_a" / "libraries" / "god.xml").write_bytes(b"<god changed='1'/>")
    after = _freshness.content_detail(cfg.reference, ext, profile=prof)
    changes = {c["folder"]: c for c in _freshness.diff_detail(before, after)}
    assert changes["amphitrite"]["kind"] == "removed"
    assert changes["mod_a"]["files_changed"] == ["libraries/god.xml"], (
        "--files must name the exact file, with no BaseX or _cat dependency")


def test_the_SAME_folder_name_in_TWO_roots_does_not_collapse(tmp_path):
    """Checker-bug #47's shape, refused up front.

    A change-detector keyed by FOLDER once met a mod shipping two manifests,
    collapsed them last-write-wins, and reported a phantom identity change --
    the most alarming shape it could have invented. The same folder name CAN
    exist in two install roots, so the vector is keyed by (root, folder).
    """
    cfg, ext, prof = _world(tmp_path)
    other = tmp_path / "profile_extensions"
    (other / "mod_a" / "libraries").mkdir(parents=True)
    (other / "mod_a" / "content.xml").write_bytes(b'<content id="id_a2"/>')
    (other / "mod_a" / "libraries" / "g.xml").write_bytes(b"<g/>")

    roots = [ext, other]
    before = _freshness.content_detail(cfg.reference, roots, profile=prof)
    assert sum(1 for r in before if r["folder"] == "mod_a") == 2, (
        "both roots' mod_a must survive into the vector")

    # Change ONLY the FIRST root's copy. This choice is the whole test: records
    # sort by (folder, root), so a folder-keyed dict keeps the SECOND root's
    # entry and would compare `other` against `other` -- seeing nothing at all.
    # Changing the second root's copy instead would pass either way, i.e. be
    # vacuous.
    (ext / "mod_a" / "libraries" / "god.xml").write_bytes(b"<god changed='1'/>")
    after = _freshness.content_detail(cfg.reference, roots, profile=prof)
    changes = _freshness.diff_detail(before, after)

    assert len(changes) == 1, (
        f"the first root's change must be seen, not masked by the second root's "
        f"same-named folder; got {changes}")
    assert changes[0]["folder"] == "mod_a"
    assert changes[0]["kind"] == "content"
    assert changes[0]["files_changed"] == ["libraries/god.xml"]
    assert str(ext) in changes[0].get("root", ""), (
        "the change must be attributed to the root it actually happened in")


def test_diff_detail_against_a_VECTORLESS_baseline_is_a_NON_ANSWER(tmp_path):
    """A tool that returns nothing must say whether that is an absence or a
    non-answer. An old artifact has no vector, and 'nothing changed' would be a
    wrong answer rather than an honest one."""
    cfg, ext, prof = _world(tmp_path)
    after = _freshness.content_detail(cfg.reference, ext, profile=prof)
    with pytest.raises(_freshness.NoBaseline):
        _freshness.diff_detail(None, after)

"""Every artifact that PERSISTS derived state must say when it was true.

Coverage/oracle checks answer "how much was indexed". None of them answered "as
of when", so a derived artifact that no longer describes the world reported
success indefinitely — a third case beside absence and non-answer.

THE CASE. BaseX's x4eff was built 2026-08-02; the merge engine was then fixed on
08-08 (root-`<replace>`: 858 ops dropped while reported applied) and 08-11
(nested patches). NEITHER DATE CHANGED AN INPUT FILE, so a check watching only
inputs would have called it fresh. MEASURED after rebuilding: 140 of 194 (72%)
engine thrust rows changed, and a design decision recorded on 08-02 had quoted
VANILLA engine values as if they were VRO's.

The same exposure exists for the sqlite store (x4effective) and the x4xref index,
which are exactly the tools a modlist decision leans on. This module is the one
implementation all of them share — the DLC-enumeration bug was written five times
because each caller rolled its own.
"""

from pathlib import Path

import pytest

from x4validate import _freshness, _merge


def _world(tmp_path):
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_bytes(b"<wares/>")
    ext = tmp_path / "extensions"
    for name in ("mod_a", "mod_b"):
        (ext / name).mkdir(parents=True)
        (ext / name / "content.xml").write_bytes(f'<content id="{name}"/>'.encode())
    return _merge.Config(reference=ref, overlays=()), ext


def test_fingerprint_is_deterministic(tmp_path):
    cfg, ext = _world(tmp_path)
    assert _freshness.fingerprint(cfg, ext) == _freshness.fingerprint(cfg, ext)


def test_adding_a_mod_moves_the_content_axis(tmp_path):
    cfg, ext = _world(tmp_path)
    before = _freshness.fingerprint(cfg, ext)
    (ext / "mod_c").mkdir()
    (ext / "mod_c" / "content.xml").write_bytes(b'<content id="mod_c"/>')
    after = _freshness.fingerprint(cfg, ext)
    assert before["content"] != after["content"]
    assert before["engine"] == after["engine"]


def test_engine_axis_moves_when_merge_code_changes(tmp_path, monkeypatch):
    """The axis a file-watcher cannot see, and the one that actually bit us."""
    cfg, ext = _world(tmp_path)
    fake = tmp_path / "engine"
    fake.mkdir()
    for name in _freshness.ENGINE_SOURCES:
        (fake / name).write_bytes(b"v1")
    before = _freshness.fingerprint(cfg, ext, engine_dir=fake)
    (fake / "_merge.py").write_bytes(b"v2 - root <replace> fix")
    after = _freshness.fingerprint(cfg, ext, engine_dir=fake)
    assert before["engine"] != after["engine"]
    assert before["content"] == after["content"]


def test_absent_fingerprint_is_UNKNOWN_not_fresh(tmp_path):
    """Every artifact built before today lacks the field, and those are exactly
    the ones whose staleness prompted this."""
    cfg, ext = _world(tmp_path)
    v = _freshness.compare(None, _freshness.fingerprint(cfg, ext), engine_dependent=True)
    assert not v.fresh
    assert any("no fingerprint" in r.lower() for r in v.reasons)


def test_compare_names_WHICH_axis_moved(tmp_path):
    cfg, ext = _world(tmp_path)
    now = _freshness.fingerprint(cfg, ext)
    stored = {"content": "deadbeef", "engine": "cafebabe"}
    v = _freshness.compare(stored, now, engine_dependent=True)
    joined = " ".join(v.reasons).lower()
    assert "content" in joined and "engine" in joined


def test_engine_change_is_ignored_for_a_non_engine_artifact(tmp_path):
    """x4raw / a raw file index is not a product of the merge, so a merge fix
    does not invalidate it. Flagging it anyway would train the reader to ignore
    the warning — the failure mode a noisy check always ends in."""
    stored = {"content": "same", "engine": "old"}
    now = {"content": "same", "engine": "new"}
    assert _freshness.compare(stored, now, engine_dependent=False).fresh
    assert not _freshness.compare(stored, now, engine_dependent=True).fresh


def test_store_roundtrip_through_sqlite_meta(tmp_path):
    """The store keeps its fingerprint in `meta`, beside the load order it
    already records — no sidecar file to lose."""
    import sqlite3
    db = tmp_path / "s.sqlite"
    con = sqlite3.connect(db)
    con.execute("create table meta (key text primary key, value text)")
    con.execute("insert into meta values ('active_mods','2')")
    con.commit()
    cfg, ext = _world(tmp_path)
    fp = _freshness.fingerprint(cfg, ext)
    _freshness.stamp_sqlite(con, fp)
    con.commit()
    assert _freshness.read_sqlite(con) == fp
    assert dict(con.execute("select * from meta"))["active_mods"] == "2", "must be additive"


def test_sidecar_roundtrip(tmp_path):
    """For artifacts that are not databases (the x4xref TSV)."""
    cfg, ext = _world(tmp_path)
    fp = _freshness.fingerprint(cfg, ext)
    target = tmp_path / "md_xref.tsv"
    target.write_text("a\tb\n", encoding="utf-8")
    _freshness.stamp_sidecar(target, fp)
    assert _freshness.read_sidecar(target) == fp
    assert target.read_text(encoding="utf-8") == "a\tb\n", "payload untouched"


def test_missing_sidecar_reads_as_none_not_empty(tmp_path):
    assert _freshness.read_sidecar(tmp_path / "nothing.tsv") is None


# --- the wiring must not silently regress -------------------------------------

def test_every_persisted_artifact_module_is_wired_to_freshness():
    """Forward guard, in the spirit of the DLC-enumeration lesson.

    The tools that PERSIST derived state are the ones that can go stale silently:
    `_effective` (the sqlite store) and `_xref` (its TSV index). `_stats`,
    `_compat`, `_similarity` and `x4validate` all recompute live and are exempt
    BY MEASUREMENT, not by assumption -- checked 2026-08-13.

    If a future tool starts persisting an index, it belongs in this list AND must
    stamp/read a fingerprint. A persisted artifact that cannot say when it was
    true is the defect this module exists to prevent.

    `_changed.py` writes snapshots and is deliberately NOT listed. A snapshot does
    not DERIVE anything from the world -- it *is* a fingerprint plus the vector it
    was folded from, so it cannot disagree with the world it describes the way an
    index can. Stamping a fingerprint onto a fingerprint would be circular. What
    it must do instead is refuse to answer from a baseline that lacks a vector,
    and that is pinned in `tests/test_changed_cli.py`.
    """
    from pathlib import Path as P
    pkg = P(__file__).resolve().parent.parent / "x4validate"
    for module in ("_effective.py", "_xref.py"):
        text = (pkg / module).read_text(encoding="utf-8")
        assert "_freshness" in text, f"{module} persists state but never stamps freshness"
        assert "stamp_s" in text, f"{module} never WRITES a fingerprint"
        assert ("store_freshness" in text or "compare(" in text), \
            f"{module} never CHECKS the fingerprint it writes"


def test_store_stamp_and_check_roundtrip(tmp_path):
    """build -> stamp -> read must report FRESH; a changed world must not."""
    import sqlite3
    cfg, ext = _world(tmp_path)
    con = sqlite3.connect(tmp_path / "s.sqlite")
    con.execute("create table meta (key text primary key, value text)")
    _freshness.stamp_sqlite(con, _freshness.fingerprint(cfg, ext))
    con.commit()

    fresh = _freshness.compare(_freshness.read_sqlite(con),
                              _freshness.fingerprint(cfg, ext), engine_dependent=True)
    assert fresh.fresh

    (ext / "mod_new").mkdir()
    (ext / "mod_new" / "content.xml").write_bytes(b'<content id="mod_new"/>')
    after = _freshness.compare(_freshness.read_sqlite(con),
                               _freshness.fingerprint(cfg, ext), engine_dependent=True)
    assert not after.fresh and "content changed" in " ".join(after.reasons)


def test_a_stale_verdict_names_the_hashes_it_compared():
    """"Moved how far, and by whose change?" is the first question a consumer asks
    on hitting a stale artifact, and without the two hashes answering it needs a
    hand-written script against fingerprint(). Raised by a downstream session that
    hit this for real while its published numbers were stamped with the old hash."""
    v = _freshness.compare({"content": "aaaaaaaaaaaaaaaa", "engine": "bbbbbbbbbbbbbbbb"},
                           {"content": "cccccccccccccccc", "engine": "dddddddddddddddd"},
                           engine_dependent=True)
    joined = " ".join(v.reasons)
    assert not v.fresh
    for h in ("aaaaaaaaaaaaaaaa", "cccccccccccccccc", "bbbbbbbbbbbbbbbb", "dddddddddddddddd"):
        assert h in joined, f"{h} missing: the reader cannot tell how far it moved"


def test_a_FRESH_verdict_says_nothing_extra():
    """Falsification twin: the hashes must appear only when something moved."""
    fp = {"content": "aaaaaaaaaaaaaaaa", "engine": "bbbbbbbbbbbbbbbb"}
    v = _freshness.compare(fp, dict(fp), engine_dependent=True)
    assert v.fresh and v.reasons == []


# --- "there is no extensions root" is not the same as "you forgot to pass one" ---
#
# MEASURED 2026-08-26: public CI was RED for two runs and five tests failed on any
# machine with no X4 installed. `_effective._ext_root()` returns
# `_registry.GAME_EXTENSIONS`, which is None when nothing is configured -- its
# `except AttributeError` guard never fires, because the attribute EXISTS and is
# None. fingerprint() then refused, correctly, because it cannot tell that None
# from a caller who simply forgot. Both readings need to exist.

def test_OMITTING_extensions_with_no_overlays_still_REFUSES(tmp_path):
    """F46's guard must survive this change. A caller who forgot is still a bug:
    falling back to Path("") hashes whatever directory you are standing in."""
    cfg, _ = _world(tmp_path)
    with pytest.raises(ValueError, match="cannot infer the extensions root"):
        _freshness.fingerprint(cfg)


def test_an_EXPLICIT_None_means_there_is_no_root_and_is_recorded_as_UNKNOWN(tmp_path):
    """The caller HAS decided -- there is no installed world to hash. That is an
    answer, and it must not be a crash."""
    cfg, _ = _world(tmp_path)
    fp = _freshness.fingerprint(cfg, extensions=None)
    assert fp["content"] is None, "an unknowable content axis must not carry a digest"
    assert fp["engine"], "the engine axis is still knowable and must still be hashed"


def test_two_UNKNOWN_content_axes_do_NOT_compare_equal_into_a_false_FRESH():
    """The trap this design has to avoid. `None == None`, so a naive equality
    check would call two unknowns a match and report FRESH -- an artifact that
    cannot say what world it describes, declaring it still describes it."""
    unknown = {"content": None, "engine": "e"}
    v = _freshness.compare(unknown, dict(unknown), engine_dependent=True)
    assert not v.fresh, "UNKNOWN must never read as fresh"
    assert any("establish" in r or "unknown" in r.lower() for r in v.reasons), v.reasons


# --- F63 symptom 2: a store must not be stamped with a world it was not built from ---
#
# Warm, `_effective._ext_root()` returned `_registry.GAME_EXTENSIONS` unconditionally
# -- so a store built over throwaway test directories was stamped with a fingerprint
# describing the REAL installed game. An artifact claiming provenance it does not
# have, which is the failure "a tool that cannot distinguish a GUESS from a
# MEASUREMENT is a defect" exists to prevent.
#
# Population RE-DERIVED 2026-08-27 rather than trusted (gotcha #23, a recorded cost
# of zero is where a wrong denominator hides): 2 call sites (`_effective.py:813`
# stamp, `:872` store_freshness), **4** test functions across 2 files -- the register
# said 5 -- and 3 production consumers of `store_freshness`, ALL of which pass
# `config=None` and therefore describe the real world. Cost today genuinely zero;
# the defect is that the stamp cannot be trusted to mean what it says.

def test_ext_root_returns_None_for_a_config_describing_a_DIFFERENT_world(tmp_path):
    """The symptom-2 defect. A test-built store's config points at a throwaway
    reference tree, so the real extensions root is NOT what it was built over."""
    from x4validate import _effective
    cfg = _merge.Config(reference=tmp_path / "ref")
    assert _effective._ext_root(cfg) is None, (
        "a config describing a throwaway world must not be handed the REAL "
        "extensions root -- that stamps the store with provenance it lacks")


def test_ext_root_still_returns_the_REAL_root_for_the_REAL_world():
    """The other direction, which is what makes the test above mean something.
    Skipped rather than faked when nothing is configured -- a cold machine cannot
    answer this question, and pretending otherwise is the defect under test."""
    from x4validate import _effective, _paths
    real = _paths.reference()
    if real is None or _paths.game_extensions() is None:
        pytest.skip("no configured game install -- cannot exercise the warm path")
    assert _effective._ext_root(_merge.Config()) == _paths.game_extensions()


def test_ext_root_does_NOT_guess_a_root_from_overlays(tmp_path):
    """Preserves the reason the original code existed, stated in its own docstring:
    guessing from `config.overlays` would fingerprint "no mods" for an empty list
    and read as FRESH FOREVER. UNKNOWN is the honest answer, never an inferred root."""
    from x4validate import _effective
    (tmp_path / "ext" / "modA").mkdir(parents=True)
    cfg = _merge.Config(reference=tmp_path / "ref",
                        overlays=(tmp_path / "ext" / "modA",))
    assert _effective._ext_root(cfg) is None, "must not infer a root from overlays"


def test_a_store_stamped_UNKNOWN_reads_NOT_fresh_through_the_real_path(tmp_path):
    """End of the chain: symptom 2's fix feeds `fingerprint(config, None)`, and the
    resulting UNKNOWN content axis must not compare equal into a false FRESH. This
    is symptom 1's trap arriving through symptom 2's door."""
    from x4validate import _effective
    cfg = _merge.Config(reference=tmp_path / "ref")
    fp = _freshness.fingerprint(cfg, _effective._ext_root(cfg))
    assert fp["content"] is None
    v = _freshness.compare(fp, dict(fp), engine_dependent=True)
    assert not v.fresh, "two UNKNOWN content axes must never read as fresh"

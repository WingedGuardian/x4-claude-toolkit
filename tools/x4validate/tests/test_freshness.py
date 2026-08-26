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

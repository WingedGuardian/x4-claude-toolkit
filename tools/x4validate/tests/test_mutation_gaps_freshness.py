"""Mutation-campaign gaps in `_freshness` (campaign 2, 2026-09-26): the FR-4
reference-vs-mods split in `compare`, and FR-1's root normalisation in `_fold`.

Each test names the surviving mutant(s) it was written to kill and was verified to FAIL
with them applied and PASS without. `compare` is exercised with synthetic stamps: what
is under test is the DECISION over two stamps, not how a stamp is taken.
"""
from __future__ import annotations

from x4validate import _freshness


def _rec(folder="modA", size=10):
    return {"folder": folder, "root": "/ext", "files": 1, "entries": [["a.xml", 1, size]],
            "enabled_in_profile": True, "manifest_version": "100", "manifest_sha": "s",
            "manifest_mtime": 1, "manifest_size": 5, "no_manifest": False, "tree_sha": "t"}


def _stamp(content, reference, detail):
    return {"content": content, "engine": "e", "reference": reference, "detail": detail}


def _kinds(verdict):
    return sorted(r.split(":", 1)[0] for r in verdict.reasons)


def test_content_move_with_unchanged_reference_names_the_mods_only():
    """FN6 (reference reason without the digests differing) and FN7b (the mods reason
    dropped whenever the vectors agree, even with the reference unchanged)."""
    v = _freshness.compare(_stamp("c1", "R", [_rec()]), _stamp("c2", "R", [_rec()]), False)
    assert _kinds(v) == ["content changed"]


def test_reference_move_that_explains_everything_names_only_the_reference():
    """FN7c (mods always named): identical per-mod vectors and a moved reference digest
    PROVE the move was the base game, so the mods are not blamed."""
    v = _freshness.compare(_stamp("c1", "R1", [_rec()]), _stamp("c2", "R2", [_rec()]), False)
    assert _kinds(v) == ["reference changed"]


def test_reference_move_plus_a_mod_change_names_both():
    """FN7 (the only-reference clause dropped) and FN8 (`_only_reference_moved` always
    True): a mod's file changed too, so the mods must still be named."""
    v = _freshness.compare(_stamp("c1", "R1", [_rec(size=10)]),
                           _stamp("c2", "R2", [_rec(size=11)]), False)
    assert _kinds(v) == ["content changed", "reference changed"]


def test_one_sided_reference_digest_is_no_split():
    """FN5 (split always) and FN5b (split needs only the STORED digest): with no
    current reference digest there is nothing to compare, so no reference reason --
    the move is attributed to the mods exactly as before FR-4."""
    v = _freshness.compare(_stamp("c1", "R1", [_rec()]), _stamp("c2", None, [_rec()]), False)
    assert _kinds(v) == ["content changed"]


def test_missing_vector_cannot_prove_only_the_reference_moved():
    """FN8b: a stamp without the per-mod vector cannot localise, so 'only the reference
    moved' is unproven and the mods are named too (the conservative verdict)."""
    v = _freshness.compare(_stamp("c1", "R1", None), _stamp("c2", "R2", [_rec()]), False)
    assert _kinds(v) == ["content changed", "reference changed"]


def test_fold_normalises_two_spellings_of_one_root(tmp_path):
    """FN2: FR-1 folds the ROOT into the digest, normalised, so two callers spelling the
    same root differently (here a `..` segment) do not cry wolf."""
    ref = tmp_path / "reference"
    ref.mkdir()
    (tmp_path / "sub").mkdir()
    a = dict(_rec(), root=str(tmp_path / "ext"))
    b = dict(_rec(), root=str(tmp_path) + "/sub/../ext")
    assert _freshness._fold([a], ref) == _freshness._fold([b], ref)
    c = dict(_rec(), root=str(tmp_path / "other"))
    assert _freshness._fold([a], ref) != _freshness._fold([c], ref)   # control: root counts


def test_fold_ignores_folder_CASE_but_not_manifest_bytes(tmp_path):
    """F1 (folder case folded -- Windows resolves either spelling to one folder) and
    F3 (the manifest's sha is part of the digest: same size and mtime, different
    bytes, is a different world)."""
    ref = tmp_path / "reference"
    ref.mkdir()
    a = _rec(folder="ModA")
    assert _freshness._fold([a], ref) == _freshness._fold([dict(a, folder="moda")], ref)
    assert _freshness._fold([a], ref) != _freshness._fold([dict(a, manifest_sha="t")], ref)


def test_an_unknown_content_axis_on_EITHER_side_is_reported_as_unknown():
    """F4 (stored side) and F5 (current side): absent is UNKNOWN, and says so --
    never reported as an ordinary 'content changed'."""
    for stored, current in ((None, "c2"), ("c1", None)):
        v = _freshness.compare(_stamp(stored, "R", [_rec()]), _stamp(current, "R", [_rec()]),
                               False)
        assert not v.fresh
        assert _kinds(v) == ["content axis UNKNOWN"], (stored, current, v.reasons)

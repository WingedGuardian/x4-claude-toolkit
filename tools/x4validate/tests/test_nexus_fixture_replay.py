"""`gates/nexus_fixture.py` replay -- the update verdict is asserted, not only exercised.

Release review 2026-09-26: the committed fixture carried no `files` key, so every
files.json reply the replay served was DERIVED from the REST record (one synthetic MAIN
file), and nothing asserted the update verdict `x4modlist refresh` computes from it. A
refresh that got the verdict wrong -- judged an OPTIONAL upload as the newest release,
say -- replayed green.
"""
from __future__ import annotations

import json

from conftest import import_gate

nf = import_gate("nexus_fixture")


def _fixture() -> dict:
    return json.loads(nf.FIXTURE.read_text(encoding="utf-8"))


def test_the_committed_fixture_carries_a_recorded_file_list_for_every_mod():
    fx = _fixture()
    files = fx.get("files") or {}
    assert set(files) == set(fx["rest"]), "every REST mod needs its files.json record"
    for mod_id, body in files.items():
        cats = {f["category_name"] for f in body["files"]}
        assert "MAIN" in cats, f"{mod_id}: no MAIN file -- the verdict has nothing to judge"
        for f in body["files"]:
            # The fields `_nexus.fetch_file_listing` reads, in the live API's shapes.
            assert isinstance(f["file_id"], int)
            assert f["uploaded_time"][4] == "-" and "T" in f["uploaded_time"]


def test_the_committed_fixture_is_key_free_and_anonymized():
    blob = nf.FIXTURE.read_text(encoding="utf-8")
    fx = json.loads(blob)
    for body in (fx.get("files") or {}).values():
        for f in body["files"]:
            assert f["name"].startswith("Example File "), f["name"]
    assert "apikey" not in blob.lower()


def test_replay_passes_and_serves_no_derived_file_list(capsys):
    assert nf.replay() == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "DERIVED" not in out
    assert "update verdict" in out


def test_replay_goes_RED_when_the_update_verdict_is_wrong(monkeypatch, capsys):
    """The planted defect: refresh judges every row 'none'. It used to replay green."""
    monkeypatch.setattr(nf._modlist, "_update_verdict",
                        lambda installed, upstream, trusted: ("none", "planted"))
    assert nf.replay() == 1, capsys.readouterr().out


def test_replay_goes_RED_when_a_newer_OPTIONAL_file_is_taken_for_the_release(
        monkeypatch, capsys):
    """The planted defect: the newest upload of ANY category is judged the release."""
    real = nf._modlist._upstream_newest

    def any_category(nid, fmeta):
        files = nf._nexus.fetch_files(nid)
        newest = max((f for f in files if f.uploaded), key=lambda f: f.uploaded)
        return newest.uploaded, f"MAIN file {newest.file_id} {newest.name!r} v{newest.version}"
    monkeypatch.setattr(nf._modlist, "_upstream_newest", any_category)
    assert real is not any_category
    assert nf.replay() == 1, capsys.readouterr().out

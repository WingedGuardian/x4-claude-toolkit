"""`x4modlist refresh` says which installed mods HAVE AN UPDATE (AUDIT-2026-09-24 RG-3).

Docs promised update detection and nothing compared installed against upstream. The rule,
decided by the user 2026-09-25: a mod has an update when upstream's newest MAIN file was
UPLOADED AFTER the installed copy's manifest date, with both dates printed. Version strings
are not compared -- Nexus uses several shapes and manifests carry integers.

No network: `urlopen` is stubbed; everything else runs for real.
"""
from __future__ import annotations

import io
import json
import types
from datetime import date, datetime, timezone

import pytest

from x4validate import _modlist, _nexus, _registry


# --- the verdict -----------------------------------------------------------------------

def test_an_upload_after_the_manifest_date_is_an_update_and_both_dates_are_stated():
    v, basis = _modlist._update_verdict("2026-06-01", "2026-07-01", trusted=True)
    assert v == "available"
    assert "2026-06-01" in basis and "2026-07-01" in basis


@pytest.mark.parametrize("upstream", ["2026-06-01", "2026-05-01"])
def test_an_upload_on_or_before_the_manifest_date_is_not_an_update(upstream):
    assert _modlist._update_verdict("2026-06-01", upstream, trusted=True)[0] == "none"


@pytest.mark.parametrize("installed, upstream", [(None, "2026-07-01"), ("2026-06-01", None),
                                                 ("sometime", "2026-07-01")])
def test_a_missing_or_unparseable_date_is_UNKNOWN_never_no_update(installed, upstream):
    v, basis = _modlist._update_verdict(installed, upstream, trusted=True)
    assert v == "unknown", (v, basis)


def test_a_guessed_identity_never_claims_an_update():
    """The upstream may be another mod entirely; same rule as cap_classification."""
    assert _modlist._update_verdict("2026-06-01", "2026-07-01", trusted=False)[0] == "unconfirmed"


@pytest.mark.parametrize("text, want", [
    ("2026-06-17", date(2026, 6, 17)),          # 123 of 156 installed manifests
    ("2026-07-8", date(2026, 7, 8)),            # 1 of 156
    ("25 December 2024", date(2024, 12, 25)),   # 1 of 156
    ("2024-03-11T12:00:00.000+00:00", date(2024, 3, 11)),   # the API's uploaded_time
    ("", None), (None, None), ("13/13/2026", None),
])
def test_parse_date_covers_the_measured_shapes_and_refuses_the_rest(text, want):
    assert _modlist._parse_date(text) == want


# --- which upstream file ----------------------------------------------------------------

def _files(*rows):
    return [_nexus.FileMeta(i, 7, n, v, up, cat) for i, (n, v, up, cat) in enumerate(rows, 1)]


def test_the_newest_MAIN_file_is_the_one_judged_not_a_newer_optional(monkeypatch):
    monkeypatch.setattr(_nexus, "fetch_files", lambda nid: _files(
        ("old main", "1.0", "2026-05-01", "MAIN"),
        ("new main", "2.0", "2026-06-20", "MAIN"),
        ("optional", "2.1", "2026-08-01", "OPTIONAL"),
        ("archived", "0.9", "2026-09-01", "OLD_VERSION")))
    up, what = _modlist._upstream_newest(7, None)
    assert up == "2026-06-20" and "new main" in what


def test_no_MAIN_file_is_unknown_with_the_denominator(monkeypatch):
    monkeypatch.setattr(_nexus, "fetch_files",
                        lambda nid: _files(("opt", "1", "2026-06-01", "OPTIONAL")))
    up, what = _modlist._upstream_newest(7, None)
    assert up is None and "among 1" in what


def test_a_row_pinned_to_a_FILE_is_judged_against_that_file(monkeypatch):
    monkeypatch.setattr(_nexus, "fetch_files", lambda nid: pytest.fail("no file list needed"))
    f = _files(("addon", "3", "2026-07-02", "OPTIONAL"))[0]
    assert _modlist._upstream_newest(7, f)[0] == "2026-07-02"


# --- end to end through refresh ---------------------------------------------------------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_refresh_records_and_prints_the_update_with_both_dates(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("X4_NEXUS_KEY", "test-key-not-real")
    ts = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp())
    meta = {"name": "Cool Mod", "version": "2.0", "updated_timestamp": ts,
            "status": "published", "author": "a"}
    files = {"files": [{"file_id": 11, "name": "Cool Mod main", "version": "2.0",
                        "uploaded_time": "2026-07-01T10:00:00.000+00:00",
                        "category_name": "MAIN"}]}

    def urlopen(req, timeout=None):
        body = files if req.full_url.endswith("/files.json") else meta
        return _Resp(json.dumps(body).encode())
    monkeypatch.setattr(_nexus.urllib.request, "urlopen", urlopen)

    regp = tmp_path / "r.yaml"
    reg = _registry._new_registry()
    e = _registry._new_entry("cool_mod", True)
    e["auto"].update(installed=True, installed_date="2026-06-01", installed_name="Cool Mod")
    e["human"]["nexus_id"] = 7                     # pinned: a trusted identity
    reg["mods"].append(e)
    _registry.save_registry(reg, regp)

    rc = _modlist.cmd_refresh(types.SimpleNamespace(
        registry=str(regp), ids=None, seeded=False, limit=None, force=True, no_resolve=True))
    assert rc == 0
    a = _registry.load_registry(regp)["mods"][0]["auto"]
    assert a["update"] == "available", dict(a)
    assert a["upstream_newest_uploaded"] == "2026-07-01"
    out = capsys.readouterr().out
    assert "UPDATE  cool_mod" in out and "2026-06-01" in out and "2026-07-01" in out, out
    dash = (tmp_path / "WORKLIST.md").read_text(encoding="utf-8")
    assert "UPDATE AVAILABLE  (1)" in dash and "2026-06-01" in dash, dash


def _one_pinned_row(tmp_path, installed_date="2026-06-01"):
    regp = tmp_path / "r.yaml"
    reg = _registry._new_registry()
    e = _registry._new_entry("cool_mod", True)
    e["auto"].update(installed=True, installed_date=installed_date, installed_name="Cool Mod")
    e["human"]["nexus_id"] = 7
    reg["mods"].append(e)
    _registry.save_registry(reg, regp)
    return regp


def _refresh(regp, force=True):
    return _modlist.cmd_refresh(types.SimpleNamespace(
        registry=str(regp), ids=None, seeded=False, limit=None, force=force, no_resolve=True))


_META_BODY = {"name": "Cool Mod", "version": "2.0", "updated_timestamp": 1782900000,
              "status": "published", "author": "a"}


def test_a_fatal_stop_while_judging_the_update_leaves_the_row_UNCHECKED(tmp_path, monkeypatch):
    """Review item 1: checked_at was written before the update verdict, so a fatal stop
    fetching files.json saved the row as checked today with `update: unknown`, and the
    re-run the tool itself recommends skipped it all day (TTL)."""
    monkeypatch.setenv("X4_NEXUS_KEY", "test-key-not-real")
    import urllib.error

    def urlopen(req, timeout=None):
        if req.full_url.endswith("/files.json"):
            raise urllib.error.URLError("network is unreachable")
        return _Resp(json.dumps(_META_BODY).encode())
    monkeypatch.setattr(_nexus.urllib.request, "urlopen", urlopen)
    regp = _one_pinned_row(tmp_path)
    assert _refresh(regp) == 2
    a = _registry.load_registry(regp)["mods"][0]["auto"]
    assert a["name"] == "Cool Mod", "what WAS fetched must be kept"
    assert a.get("checked_at") != datetime.now(timezone.utc).date().isoformat(), dict(a)


def _stale_available(regp, **auto):
    reg = _registry.load_registry(regp)
    a = reg["mods"][0]["auto"]
    a.update(update="available", update_basis="upstream uploaded 2026-07-01 vs installed "
             "manifest dated 2026-06-01", upstream_newest="MAIN file 1",
             upstream_newest_uploaded="2026-07-01", **auto)
    _registry.save_registry(reg, regp)


def test_a_row_that_ends_in_ERROR_does_not_keep_a_stale_update_verdict(tmp_path, monkeypatch):
    """Review item 5: the verdict belongs to the fetch that produced it."""
    monkeypatch.setenv("X4_NEXUS_KEY", "test-key-not-real")
    import urllib.error

    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
    monkeypatch.setattr(_nexus.urllib.request, "urlopen", urlopen)
    regp = _one_pinned_row(tmp_path)
    _stale_available(regp)
    _refresh(regp)
    a = _registry.load_registry(regp)["mods"][0]["auto"]
    assert a["classification"] == "error"
    assert a.get("update") != "available", dict(a)


def test_a_row_that_ends_UNTRIAGED_does_not_keep_a_stale_update_verdict(tmp_path):
    regp = tmp_path / "r.yaml"
    reg = _registry._new_registry()
    e = _registry._new_entry("no_id_mod", True)
    e["auto"].update(installed=True, update="available")
    reg["mods"].append(e)
    _registry.save_registry(reg, regp)
    _refresh(regp)                                   # no id, --no-resolve: untriaged
    a = _registry.load_registry(regp)["mods"][0]["auto"]
    assert a["classification"] == "untriaged"
    assert a.get("update") != "available", dict(a)


def test_a_verdict_NOT_rechecked_this_run_is_labelled_carried_over(tmp_path, monkeypatch, capsys):
    """A TTL-skipped row's verdict is from an earlier run; printing it as a plain UPDATE
    line read as 'just checked'."""
    monkeypatch.setattr(_nexus.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("a TTL-skipped row makes no call"))
    regp = _one_pinned_row(tmp_path)
    _stale_available(regp, checked_at=datetime.now(timezone.utc).date().isoformat())
    assert _refresh(regp, force=False) == 0
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if "cool_mod" in ln)
    assert "carried over" in line, out

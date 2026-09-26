"""Mutation-campaign gaps in the analysis tools (campaigns 1+2, 2026-09-26):
`_resolve` index precedence, `_modlist` classification/provenance, `_nexus` date
format, `_similarity` scoring edges. Each test names the surviving mutant it was written
to kill and was verified to FAIL with it applied and PASS without it."""
from __future__ import annotations

import types
from datetime import date, datetime, timezone

import pytest

from x4validate import _merge, _modlist, _nexus, _registry, _resolve, _similarity
from x4validate._nexus import FileMeta, ModMeta


# --------------------------------------------------------------------------- _resolve
def test_a_dlc_index_entry_overrides_the_base_entry_of_the_same_name(tmp_path):
    """R6r: base, then each DLC, then mods -- LATER sources win. First-wins would keep
    the base's value for a macro a DLC re-registers."""
    ref = tmp_path / "reference"
    dlc = ref / "extensions" / "ego_dlc_test"
    for root, value in ((ref, "assets\\base\\m"), (dlc, "assets\\dlc\\m")):
        (root / "index").mkdir(parents=True)
        (root / "index" / "macros.xml").write_text(
            f'<index><entry name="m_macro" value="{value}"/></index>', encoding="utf-8")
    index = _resolve.build_index(_merge.Config(reference=ref), [], _resolve.MACRO_INDEX)
    assert index["m_macro"][1] == "assets\\dlc\\m"


# --------------------------------------------------------------------------- _modlist
def _meta(updated, nid=5):
    return ModMeta(nid, "Page", "1.0", updated, "published", "auth")


def test_update_on_the_9_0_release_day_counts_as_post_9_0():
    """L3: an upload ON the 9.0 release date is post-9.0 (>=)."""
    today = _modlist.NINE_ZERO.replace(year=_modlist.NINE_ZERO.year + 1)
    assert _modlist._classify(_meta(_modlist.NINE_ZERO.isoformat()), today)[0] == "ready"


def test_an_update_exactly_CHURN_DAYS_old_is_still_churning():
    """L4: the churn window is inclusive (<= CHURN_DAYS)."""
    upd = date(2026, 7, 1)
    today = date.fromordinal(upd.toordinal() + _modlist.CHURN_DAYS)
    assert _modlist._classify(_meta(upd.isoformat()), today)[0] == "churning"


def _refresh_one(monkeypatch, auto, page_updated, file_uploaded=None, file_id=None):
    monkeypatch.setattr(_modlist._nexus, "fetch_mod", lambda nid: _meta(page_updated, nid))
    monkeypatch.setattr(_modlist._nexus, "fetch_file",
                        lambda nid, fid: FileMeta(fid, nid, "Addon", "2.0", file_uploaded,
                                                  "MAIN"))
    m = _registry._new_entry("x", True)
    m["auto"].update(auto)
    if file_id is not None:
        m["human"]["nexus_id"] = auto["nexus_id"]
        m["human"]["nexus_file_id"] = file_id
    args = types.SimpleNamespace(force=True, no_resolve=True)
    fatal, *_ = _modlist._refresh_rows([m], args, date(2027, 1, 1), set())
    assert fatal is None
    return m["auto"]


def test_refresh_records_an_unconfirmed_identity_as_its_state_not_exact(monkeypatch):
    """L6r: `upstream_from` says how far the fetched data can be trusted. From a GUESSED
    id it must say 'guess', never 'exact'."""
    a = _refresh_one(monkeypatch, {"nexus_id": 5, "id_state": "guess"}, "2026-08-01")
    assert a["upstream_from"] == "guess"


def test_refresh_classifies_a_file_on_someone_elses_page_by_the_FILES_date(monkeypatch):
    """L7: the page predates 9.0 but the pinned FILE was uploaded after it; the lane is
    decided by the file, not the page."""
    a = _refresh_one(monkeypatch, {"nexus_id": 5}, "2025-01-01",
                     file_uploaded="2026-08-01", file_id=77)
    assert a["classification"] == "ready"


# --------------------------------------------------------------------------- _nexus
def test_fetch_mod_formats_the_update_date_as_ISO(monkeypatch):
    """N6: `updated` is YYYY-MM-DD; everything downstream parses it with
    `date.fromisoformat`. A swapped day/month still parses for days <= 12."""
    ts = int(datetime(2026, 6, 21, 12, tzinfo=timezone.utc).timestamp())
    monkeypatch.setattr(_nexus, "nexus_key", lambda: "k")
    monkeypatch.setattr(_nexus, "_get_json",
                        lambda url, h: {"name": "n", "version": "1",
                                        "updated_timestamp": ts, "status": "published",
                                        "author": "a"})
    assert _nexus.fetch_mod(1).updated == "2026-06-21"


# --------------------------------------------------------------------------- _similarity
def _ship(name, stats, source="base", cls="ship_s"):
    return _similarity.ShipVector(macro_name=name, source=source, vpath=f"{name}.xml",
                                  ship_class=cls, purpose="fight", stats=dict(stats),
                                  all_stats=dict(stats))


_FOUR = {"hull.max": 100.0, "people.capacity": 10.0, "storage.unit": 2.0,
         "secrecy.level": 1.0}


def test_three_shared_keys_are_not_comparable():
    """M3r: below MIN_SHARED_KEYS (4) a pair is not scored at all."""
    three = {k: v for k, v in list(_FOUR.items())[:3]}
    assert _similarity.similarity(_ship("a", three), _ship("b", three)) is None
    assert _similarity.similarity(_ship("a", _FOUR), _ship("b", _FOUR)) is not None


def test_per_key_difference_is_capped_so_the_score_never_goes_negative():
    """M4: opposite-sign values differ by 2x their magnitude; the cap holds each key
    at 1.0, so the worst score is 0, not negative."""
    neg = {k: -v for k, v in _FOUR.items()}
    assert _similarity.similarity(_ship("a", _FOUR), _ship("b", neg)).score == 0.0


def test_relative_difference_is_taken_over_the_LARGER_value():
    """M9: 50 vs 100 is a 0.5 difference (over max), not 1.0 (over min)."""
    b = dict(_FOUR, **{"hull.max": 50.0})
    w = sum(_similarity._WEIGHTS[k] for k in _FOUR)
    got = _similarity.similarity(_ship("a", _FOUR), _ship("b", b)).score
    assert got == pytest.approx(1 - _similarity._WEIGHTS["hull.max"] * 0.5 / w)


def test_find_similar_threshold_is_inclusive_and_sorts_highest_first():
    """M6 (threshold >=) and M8 (highest first)."""
    near = dict(_FOUR, **{"hull.max": 90.0})
    pairs = _similarity.find_similar(
        [_ship("a", _FOUR), _ship("b", _FOUR), _ship("c", near)], threshold=0.9)
    scores = [p.score for p in pairs]
    assert scores == sorted(scores, reverse=True) and scores[0] == 1.0
    assert len(_similarity.find_similar([_ship("a", _FOUR), _ship("b", _FOUR)],
                                        threshold=1.0)) == 1


def test_exclude_same_source_keeps_cross_source_pairs():
    """M7: excluding same-source pairs must not exclude EVERY pair."""
    pairs = _similarity.find_similar([_ship("a", _FOUR, "base"), _ship("b", _FOUR, "mod1"),
                                      _ship("c", _FOUR, "mod1")],
                                     exclude_same_source=True)
    assert sorted((p.a.macro_name, p.b.macro_name) for p in pairs) == [("a", "b"), ("a", "c")]


def test_difference_profile_epsilon_is_inclusive():
    """M10: a relative difference EXACTLY equal to epsilon counts as identical."""
    a = _ship("a", {"x": 1e9})
    b = _ship("b", {"x": 1e9 - 1})
    prof = _similarity.difference_profile(a, b, epsilon=1e-9)
    assert prof.identical == ["x"] and prof.differing == []

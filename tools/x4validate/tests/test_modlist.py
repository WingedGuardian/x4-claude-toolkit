"""Deterministic logic for the modlist registry tool (ingest/merge/classify/dashboard).

The live API paths (fetch/search/steam) are integration-validated by the slice runs;
these cover the pure, mockable logic.
"""

import types
from datetime import date
from pathlib import Path

from x4validate import _modlist, _registry
from x4validate._nexus import ModMeta


def _installed_entry(mod_id, **auto_overrides):
    """A registry entry marked installed=True (the active-set gate) with any
    extra auto: fields set."""
    e = _registry._new_entry(mod_id, True)
    e["auto"]["installed"] = True
    e["auto"].update(auto_overrides)
    return e


def _args(**kw):
    return types.SimpleNamespace(**kw)


def test_ingest_parses_enabled_flag(tmp_path):
    c = tmp_path / "content.xml"
    c.write_text('<content><extension id="a" enabled="true"/>'
                 '<extension id="ws_1" enabled="false"/></content>', encoding="utf-8")
    ids = _registry.ingest_content_xml(c)
    assert ("a", True) in ids and ("ws_1", False) in ids


def test_merge_adds_new_and_preserves_human():
    reg = _registry._new_registry()
    reg["mods"].append(_registry._new_entry("existing", True))
    reg["mods"][0]["human"]["notes"] = "MINE"
    reg["mods"][0]["human"]["done"] = True
    added, existing = _registry.merge(reg, [("existing", True), ("new", True), ("off", False)])
    assert added == 1 and existing == 1
    by_id = {m["id"]: m for m in reg["mods"]}
    assert by_id["existing"]["human"]["notes"] == "MINE"  # preserved
    assert by_id["existing"]["human"]["done"] is True
    assert "new" in by_id and "off" not in by_id  # disabled skipped by default


def test_strip_author_label():
    assert _modlist._strip_author_label("kuertee: Ship scanner") == "Ship scanner"
    assert _modlist._strip_author_label("kuertee UI: Boarding operation notifications") \
        == "Boarding operation notifications"
    assert _modlist._strip_author_label("No colon here") == "No colon here"


def test_manifest_name_variants():
    assert _modlist._manifest_name_variants("Vibrant Engine Plumes - Divinity Edition") == \
        ["Vibrant Engine Plumes - Divinity Edition", "Vibrant Engine Plumes"]
    assert _modlist._manifest_name_variants("Terran Beam Weapons VRO") == \
        ["Terran Beam Weapons VRO", "Terran Beam Weapons"]
    assert _modlist._manifest_name_variants("Plain Title") == ["Plain Title"]


def test_resolve_identity_prefers_installed_name(monkeypatch):
    calls = []

    def fake_search(name, count=5):
        calls.append(name)
        return [(999, "Ship Scanner Mod")] if name == "Ship scanner" else []

    monkeypatch.setattr(_modlist._nexus, "search_mods", fake_search)
    auto = {"installed_name": "kuertee: Ship scanner"}
    nid, state = _modlist._resolve_identity("kuerteeShipScanner", auto)
    assert nid == 999
    assert state == "exact"  # single strong match ("scanner" is distinctive)
    assert calls[0] == "Ship scanner"  # tried the manifest name FIRST, not a humanized guess
    assert auto["resolve"] == "auto (strong match)"


def test_humanize_splits_camel_and_underscore():
    assert _modlist._humanize("kuerteeSocialStandingsAndCitizenships") == \
        "kuertee Social Standings And Citizenships"
    assert _modlist._humanize("station_combat_rebalance_vro") == "station combat rebalance vro"


def _meta(updated, status="published"):
    return ModMeta(1, "n", "1.0", updated, status, "auth")


def test_classify_removed_and_hidden_drop():
    today = date(2026, 6, 22)
    assert _modlist._classify(_meta("2026-06-20", "removed"), today)[0] == "drop"
    assert _modlist._classify(_meta("2026-06-20", "hidden"), today)[0] == "drop"


def test_classify_hidden_custom_edited_is_not_dropped():
    # A mod the user is actively maintaining a local fork of should NOT be told
    # to "drop" just because the author temporarily hid the upstream page.
    today = date(2026, 6, 22)
    cls, settled = _modlist._classify(_meta("2026-06-20", "hidden"), today, is_custom=True)
    assert cls == "custom-local"
    cls2, _ = _modlist._classify(_meta("2026-06-20", "removed"), today, is_custom=True)
    assert cls2 == "custom-local"


def test_classify_churning_ready_predates():
    # Use a later 'today' so the post-9.0 settled ("ready") lane is reachable.
    today = date(2026, 8, 1)
    assert _modlist._classify(_meta("2026-07-25"), today)[0] == "churning"   # <14d
    assert _modlist._classify(_meta("2026-06-20"), today)[0] == "ready"      # post-9.0, >14d
    assert _modlist._classify(_meta("2024-02-16"), today)[0] == "predates-9.0"
    assert _modlist._classify(_meta(""), today)[0] == "untriaged"            # unparseable date


def test_needs_review_filters():
    """Keyed on IDENTITY provenance: an unconfirmed id stays visible however
    healthy the mod it fetched looks."""
    reg = _registry._new_registry()
    e_untri = _installed_entry("u")                                   # unsearched -> review
    e_guess = _installed_entry("a", classification="churning", nexus_id=5,
                               id_state="guess")                      # -> review
    e_clean = _installed_entry("m", classification="ready", nexus_id=7,
                               id_state="pinned")                     # confirmed -> NOT
    e_exact = _installed_entry("e", classification="ready", nexus_id=8,
                               id_state="exact")                      # confirmed -> NOT
    e_ign = _installed_entry("ig")
    e_ign["human"]["ignored"] = True                                  # ignored -> NOT
    e_off = _installed_entry("off")
    e_off["human"]["source"] = "steam:123"                            # answered -> NOT
    e_not_installed = _registry._new_entry("ni", True)                 # installed=False -> NOT
    reg["mods"].extend([e_untri, e_guess, e_clean, e_exact, e_ign, e_off, e_not_installed])
    assert {m["id"] for m in _registry.needs_review(reg)} == {"u", "a"}


def test_not_installed_diff_view():
    reg = _registry._new_registry()
    reg["mods"].append(_installed_entry("live"))
    old = _registry._new_entry("gone", True)  # tracked historically, not on disk -> installed=False
    old["auto"]["classification"] = "predates-9.0"
    reg["mods"].append(old)
    ids = {m["id"] for m in _registry.not_installed(reg)}
    assert ids == {"gone"}


def test_ignore_and_mark_persist(tmp_path):
    regp = tmp_path / "r.yaml"
    reg = _registry._new_registry()
    reg["mods"].append(_registry._new_entry("x", True))
    _registry.save_registry(reg, regp)
    _modlist.cmd_ignore(_args(registry=str(regp), id="x", reason="junk"))
    _modlist.cmd_mark(_args(registry=str(regp), id="x", custom=True, notes="edited"))
    h = _registry.load_registry(regp)["mods"][0]["human"]
    assert h["ignored"] is True and h["custom_edited"] is True and h["notes"] == "edited"


def test_resolve_sets_manual_and_fetches(tmp_path, monkeypatch):
    monkeypatch.setattr(_modlist._nexus, "fetch_mod",
                        lambda nid: ModMeta(nid, "Cool Mod", "2.0", "2026-06-21", "published", "a"))
    regp = tmp_path / "r.yaml"
    reg = _registry._new_registry()
    reg["mods"].append(_registry._new_entry("x", True))
    _registry.save_registry(reg, regp)
    assert _modlist.cmd_resolve(_args(registry=str(regp), id="x", nexus_id=999)) == 0
    a = _registry.load_registry(regp)["mods"][0]["auto"]
    assert a["nexus_id"] == 999 and a["resolve"] == "manual" and a["name"] == "Cool Mod"
    assert a["classification"] in ("churning", "ready", "predates-9.0")


# --- identity provenance -----------------------------------------------------
#
# The defect these pin: a fuzzy name match was stored in the same field as a
# verified id, so a guess read as a fact and was promoted to `settled: stable`.
# One real row pointed at an unrelated author's mod for weeks.

def test_match_strength_three_way():
    # distinctive shared token -> strong
    assert _modlist._match_strength("CPSDO Faction Pack 9.0+", "CPSDO Modpack") == "strong"
    # whole name contained (punctuation-insensitive) -> strong
    assert _modlist._match_strength("MoreAtmosphericShield", "More Atmospheric Shield") == "strong"
    # shares only a SHORT identity token -> weak, never a verdict on its own
    assert _modlist._match_strength("Beam Weapons VRO", "Beam Effects") == "weak"
    # nothing in common -> none
    assert _modlist._match_strength("CPSDO Faction Pack", "Larger Fleets and Xenon") == "none"


def test_resolve_refuses_to_pick_between_weak_candidates(monkeypatch):
    """The measured failure: 'CPSDO Faction Pack' shares one filler-ish token with
    several unrelated mods. Picking the first was a coin flip presented as an id."""
    monkeypatch.setattr(_modlist._nexus, "search_mods",
                        lambda name, count=5: [(2202, "Faction Filter for Ships"),
                                               (2189, "Apus Treaty - New Faction Sectors")])
    auto = {"installed_name": "Zzz Faction Thing"}
    nid, state = _modlist._resolve_identity("zzz_faction_thing", auto)
    assert nid is None, "no id may be stored when the evidence does not single one out"
    assert state == "ambiguous"
    assert auto["candidates"], "the alternatives are kept so a human can settle it"


def test_guess_cannot_reach_a_confident_lane():
    """The load-bearing invariant: everything downstream of an id is only as good
    as the id, so a guess is capped no matter how healthy the fetch looked."""
    assert _registry.cap_classification("guess", "ready", "stable") \
        == (_registry.UNCONFIRMED_LANE, "unconfirmed identity (guess)")
    assert _registry.cap_classification("ambiguous", "ready", "stable")[0] \
        == _registry.UNCONFIRMED_LANE
    # ...and a confirmed identity passes through untouched
    assert _registry.cap_classification("pinned", "ready", "stable") == ("ready", "stable")
    assert _registry.cap_classification("exact", "churning", "churning") == ("churning", "churning")


def test_human_pin_wins_and_survives_refresh_fields():
    m = _registry._new_entry("x", True)
    m["auto"].update(nexus_id=999, id_state="guess")     # a wrong auto guess
    m["human"]["nexus_id"] = 1330                         # the human's correction
    m["human"]["nexus_file_id"] = 13671
    assert _registry.identity(m) == (1330, 13671, "pinned")


def test_human_none_and_source_stop_the_search():
    m = _registry._new_entry("x", True)
    m["human"]["nexus_id"] = "none"
    assert _registry.identity(m) == (None, None, "off-nexus")
    m2 = _registry._new_entry("y", True)
    m2["human"]["source"] = "steam:3272713594"
    assert _registry.identity(m2)[2] == "off-nexus"


def test_malformed_pin_degrades_to_unconfirmed_not_silently_dropped():
    m = _registry._new_entry("x", True)
    m["auto"].update(nexus_id=42, id_state="guess")
    m["human"]["nexus_id"] = "1330 maybe?"        # not parseable
    nid, _, state = _registry.identity(m)
    assert state == "guess" and nid == 42, "falls through, stays visibly unconfirmed"


def test_migration_promotes_nothing():
    """Legacy rows carry no provenance. Every historical auto-match becomes a
    GUESS — downgrading a real match costs one spot-check; upgrading a bad one
    re-creates the defect."""
    legacy = _registry._new_entry("old", True)
    del legacy["auto"]["id_state"]
    legacy["auto"].update(nexus_id=2215, resolve="auto (spot-check)")
    assert _registry.migrate_entry(legacy) is True
    assert legacy["auto"]["id_state"] == "guess"
    assert _registry.migrate_entry(legacy) is False, "idempotent"

    manual = _registry._new_entry("m", True)
    del manual["auto"]["id_state"]
    manual["auto"].update(nexus_id=7, resolve="manual")
    _registry.migrate_entry(manual)
    assert manual["auto"]["id_state"] == "pinned"

    # An id with NO provenance at all is a guess, never `exact`.
    bare = _registry._new_entry("b", True)
    del bare["auto"]["id_state"]
    bare["auto"]["nexus_id"] = 3
    _registry.migrate_entry(bare)
    assert bare["auto"]["id_state"] == "guess"


def test_unknown_id_state_is_never_trusted():
    m = _registry._new_entry("x", True)
    m["auto"].update(nexus_id=5, id_state="totally-fine-honest")
    assert _registry.identity(m)[2] == "guess"


def test_resolve_pins_into_human_and_records_file(tmp_path, monkeypatch):
    from x4validate._nexus import FileMeta
    monkeypatch.setattr(_modlist._nexus, "fetch_mod",
                        lambda nid: ModMeta(nid, "CPSDO Modpack", "9.00", "2026-06-10",
                                            "published", "HYLT2233"))
    monkeypatch.setattr(_modlist._nexus, "fetch_file",
                        lambda nid, fid: FileMeta(fid, nid, "CPSDO Faction 9.00", "9.00",
                                                  "2026-06-22", "MAIN"))
    regp = tmp_path / "r.yaml"
    reg = _registry._new_registry()
    reg["mods"].append(_registry._new_entry("cpsdo_faction", True))
    _registry.save_registry(reg, regp)
    assert _modlist.cmd_resolve(_args(registry=str(regp), id="cpsdo_faction",
                                      nexus_id="1330", file=13671)) == 0
    m = _registry.load_registry(regp)["mods"][0]
    assert m["human"]["nexus_id"] == 1330 and m["human"]["nexus_file_id"] == 13671
    assert _registry.identity(m)[2] == "pinned"
    # the FILE's date drives the verdict, not the page's
    assert m["auto"]["updated"] == "2026-06-22"
    assert "13671" in m["auto"]["upstream_file"]


def test_resolve_none_records_no_page(tmp_path):
    regp = tmp_path / "r.yaml"
    reg = _registry._new_registry()
    reg["mods"].append(_registry._new_entry("my_own_overlay", True))
    _registry.save_registry(reg, regp)
    assert _modlist.cmd_resolve(_args(registry=str(regp), id="my_own_overlay",
                                      nexus_id="none", file=None)) == 0
    m = _registry.load_registry(regp)["mods"][0]
    assert _registry.identity(m)[2] == "off-nexus"
    assert m["auto"]["classification"] == "off-nexus"


def test_source_command_marks_off_nexus(tmp_path):
    regp = tmp_path / "r.yaml"
    reg = _registry._new_registry()
    reg["mods"].append(_registry._new_entry("ws_123", True))
    _registry.save_registry(reg, regp)
    assert _modlist.cmd_source(_args(registry=str(regp), id="ws_123",
                                     source="steam:123")) == 0
    m = _registry.load_registry(regp)["mods"][0]
    assert m["human"]["source"] == "steam:123"
    assert _registry.identity(m)[2] == "off-nexus"


def test_rescore_promotes_only_on_identical_names():
    """Containment is NOT enough. The real counter-example: a row whose stored
    upstream title merely CONTAINS the mod's name is a different mod."""
    reg = _registry._new_registry()
    same = _installed_entry("MoreAtmosphericShield", nexus_id=2158, id_state="guess",
                            installed_name="MoreAtmosphericShield",
                            name="More Atmospheric Shield")
    contained = _installed_entry("Ventures", nexus_id=292, id_state="guess",
                                 installed_name="Ventures",
                                 name="Savegame for Ventures")
    pinned = _installed_entry("p", nexus_id=1, id_state="pinned",
                              installed_name="X", name="X")
    reg["mods"].extend([same, contained, pinned])
    promoted, left = _modlist._rescore(reg)
    assert (promoted, left) == (1, 1)
    assert same["auto"]["id_state"] == "exact"
    assert contained["auto"]["id_state"] == "guess", "containment must not promote"
    assert pinned["auto"]["id_state"] == "pinned", "a pin is never rewritten"


def test_dashboard_labels_guesses(tmp_path):
    reg = _registry._new_registry()
    reg["mods"].append(_installed_entry("g", name="Something", nexus_id=1,
                                        id_state="guess",
                                        classification=_registry.UNCONFIRMED_LANE))
    out = _registry.generate_dashboard(reg)
    assert "UNCONFIRMED IDENTITY" in out
    assert "guess" in out
    assert "Identity provenance:" in out


def test_dashboard_groups_by_lane():
    reg = _registry._new_registry()
    reg["mods"].append(_installed_entry(
        "m1", name="VRO", classification="churning", version="5.0", status="published"))
    out = _registry.generate_dashboard(reg)
    assert "CHURNING" in out and "VRO" in out and "1/1" not in out  # 0 done of 1


def test_merge_installed_matches_by_id_and_flags_missing():
    reg = _registry._new_registry()
    # Pre-existing research on a mod (e.g. from an old content.xml ingest).
    old = _registry._new_entry("ws_1696862840", True)
    old["auto"].update(nexus_id=305, classification="churning")
    old["human"]["notes"] = "keep me"
    reg["mods"].append(old)

    installed = [{"id": "ws_1696862840", "folder": "vro", "path": "C:/x/vro",
                  "name": "Variety and Rebalance Overhaul", "version": "501",
                  "date": "2026-06-25", "author": "Shuul", "enabled": True}]
    new, matched, gone = _registry.merge_installed(reg, installed)
    assert (new, matched) == (0, 1)
    m = reg["mods"][0]
    assert m["auto"]["installed"] is True
    assert m["auto"]["installed_version"] == "501"
    assert m["auto"]["nexus_id"] == 305          # prior research preserved
    assert m["human"]["notes"] == "keep me"      # human: untouched

    # A second merge with an EMPTY installed list -> the mod flips to installed=False
    # (uninstalled) rather than being deleted.
    new2, matched2, gone2 = _registry.merge_installed(reg, [])
    assert gone2 == 1
    assert reg["mods"][0]["auto"]["installed"] is False
    assert reg["mods"][0]["auto"]["nexus_id"] == 305  # still preserved


# --------------------------------------------------------------------------
# Identity plausibility. Fixtures are the REAL misresolutions found on
# 2026-07-26 by auditing a live registry: 7 of 69 resolved mods pointed at an
# unrelated Nexus page, most of them marked `settled: stable, ready`, because
# _resolve_identity took the top search hit on faith.
# --------------------------------------------------------------------------

WRONG = [
    # (installed name, the Nexus title the tool actually chose)
    ("CPSDO VRO Adaptation Pack 8.0+", "Firefly (Serenity) VRO and standard versions"),
    ("CPSDO Faction Pack 9.0+",        "Larger Fleets Factions and Xenon - 9.00 Port"),
    ("Vaygr Battlecruiser",            "Dreadnaughts and Battlecruisers for SWI"),
    ("AM7OU VRO Patch",                "new bor ship (Boron Hammerhead) - VRO patch"),
    ("Immersive Sounds",               "X4 Sound Experience"),
    ("Realspace - STARS",              "X4 Star Trek Starfleet Command shippack"),
]

RIGHT = [
    ("CPSDO Modpack 9.0+",       "CPSDO Modpack"),
    ("CPSDO VRO Adaptation Pack", "CPSDO Modpack VRO"),
    # squashed folder-style name vs the spaced Nexus title — no shared token, same mod
    ("MoreAtmosphericShield",    "More Atmospheric Shield"),
    ("Higher Dimensional Space", "Higher Dimensional Space"),
]


def test_plausible_match_rejects_the_real_misresolutions():
    for own, nexus in WRONG:
        assert not _modlist._plausible_match(own, nexus), (
            f"{own!r} must NOT auto-resolve to {nexus!r} — a wrong id silently "
            "tracks another mod's version while the row reads 'settled: stable'")


def test_plausible_match_accepts_genuine_pages():
    for own, nexus in RIGHT:
        assert _modlist._plausible_match(own, nexus), f"{own!r} should match {nexus!r}"


def test_plausible_match_ignores_filler_only_overlap():
    """Sharing only generic words ('VRO', 'patch', 'ship') is not evidence."""
    assert not _modlist._plausible_match("Terran Beam Weapons VRO patch",
                                         "Boron Hammerhead ship VRO patch")


def test_plausible_match_abstains_when_there_is_nothing_to_judge():
    """No identity tokens on either side -> don't invent a rejection."""
    assert _modlist._plausible_match("VRO patch", "mod pack")

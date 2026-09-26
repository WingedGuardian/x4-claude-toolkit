"""AUDIT-2026-09-24 Phase 1 -- analysis CLIs (AN-*) and freshness (FR-*).

Every test marked ``xfail(strict=True)`` reproduces a VERIFIED finding against the
code as it stood at the audit, through the REAL function or CLI on a minimal
hermetic fixture. When a fix lands, its test XPASSes, strict turns that into a
failure, and the fixer removes the marker -- so a fix cannot land silently and a
test cannot rot into decoration.

FR-5 is the exception, stated rather than hidden: its defect is a MISSING TEST
(two case-folds survive mutation), so its tests PASS on current code and exist to
kill the mutant. Each was proved to go red under that mutant before it was kept.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest
from lxml import etree

from x4validate import (_changed, _compat, _effective, _effectivecli, _freshness,
                        _merge, _registry, _similarity, _stats, _xref)


# --- helpers ------------------------------------------------------------------

def _w(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _mod(ext: Path, folder: str, files: dict[str, str], mod_id: str | None = None) -> Path:
    root = ext / folder
    _w(root / "content.xml",
       f'<content id="{mod_id or folder}" name="{folder}" version="1"/>')
    for vpath, text in files.items():
        _w(root / vpath, text)
    return root


def _ref(tmp_path: Path) -> Path:
    ref = tmp_path / "reference"
    _w(ref / "libraries" / "wares.xml",
       '<wares><ware id="ore" group="minerals"><price min="1" average="100" max="200"/></ware>'
       '<ware id="ice" group="minerals"><price min="1" average="50" max="90"/></ware></wares>')
    return ref


def _cfg(ref: Path) -> _merge.Config:
    return _merge.Config(reference=ref, include_packed_dlc=False)


@pytest.fixture
def hermetic(monkeypatch):
    """No real profile: every tmp mod counts as enabled, whatever this machine has."""
    monkeypatch.setattr(_registry, "ingest_content_xml", lambda *a, **k: [])
    monkeypatch.setattr(_registry, "PROFILE_CONTENT", None)


ORE_PRICE = "<diff><replace sel=\"//ware[@id='ore']/price/@average\">{v}</replace></diff>"
ICE_PRICE = "<diff><replace sel=\"//ware[@id='ice']/price/@average\">{v}</replace></diff>"


# =============================================================================
# AN-1  x4compat check <path> analyses the INSTALLED same-named copy
# =============================================================================

def _an1_world(tmp_path):
    ref = _ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"libraries/wares.xml": ORE_PRICE.format(v=1)})
    # the INSTALLED x_mod touches ice only -> no collision with a_mod
    _mod(ext, "x_mod", {"libraries/wares.xml": ICE_PRICE.format(v=1)})
    # the STAGED x_mod (a newer copy, outside the install) touches ore -> collides
    stage = _mod(tmp_path / "staging", "x_mod", {"libraries/wares.xml": ORE_PRICE.format(v=9)})
    return ref, ext, stage


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 AN-1: an existing candidate "
                   "path is replaced by the installed same-named copy")
def test_AN1_an_existing_candidate_path_is_the_copy_analysed(tmp_path, hermetic):
    ref, ext, stage = _an1_world(tmp_path)
    rep = _compat.analyze(ext, candidate=stage, config=_cfg(ref))
    assert rep.files_examined == 1          # precondition: the file WAS compared
    assert any(set(c.mods) == {"a_mod", "x_mod"} for c in rep.by_kind("HARD")), (
        "the staged x_mod replaces ore's price exactly as a_mod does; analysing the "
        f"installed copy instead found {[(c.kind, c.mods) for c in rep.collisions]}")


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 AN-1: output does not name "
                   "which copy of the candidate was analysed")
def test_AN1_output_names_the_copy_analysed(tmp_path, hermetic, capsys):
    ref, ext, stage = _an1_world(tmp_path)
    _compat.main(["check", str(stage), "--ext-dir", str(ext), "--reference", str(ref)])
    out = capsys.readouterr().out
    assert str(stage) in out or str(stage.resolve()) in out, out


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 AN-1: a bare installed name is "
                   "refused instead of resolving to the installed copy")
def test_AN1_a_bare_name_resolves_to_the_installed_copy(tmp_path, hermetic, capsys,
                                                        monkeypatch):
    ref, ext, _stage = _an1_world(tmp_path)
    empty = tmp_path / "elsewhere"
    empty.mkdir()
    monkeypatch.chdir(empty)            # no ./x_mod here: only the install has one
    try:
        _compat.main(["check", "x_mod", "--ext-dir", str(ext), "--reference", str(ref)])
    except SystemExit as exc:
        pytest.fail(f"bare installed name refused with SystemExit({exc.code})")


# =============================================================================
# AN-2  x4stats wares on a mod that <remove>s a ware -> "changes no wares", rc 0
# =============================================================================

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 AN-2: a ware <remove> reports "
                   "'introduces/changes no wares' at rc 0")
def test_AN2_a_removed_ware_is_not_reported_as_no_change(tmp_path, hermetic, capsys):
    ref = _ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "other", {})
    cand = _mod(tmp_path / "staging", "rm_mod",
                {"libraries/wares.xml": "<diff><remove sel=\"//ware[@id='ore']\"/></diff>"})
    _stats.main(["wares", str(cand), "--ext-dir", str(ext), "--reference", str(ref)])
    out = capsys.readouterr().out
    assert "introduces/changes no wares" not in out, out
    assert "ore" in out, out


# =============================================================================
# AN-3 / AN-4  effective store: --modified-only keyed on the entity chain;
#              who-sets 'WON, not introduced' on a genuinely added entity
# =============================================================================

def _store(tmp_path, monkeypatch):
    ref = _ref(tmp_path)
    _w(ref / "extensions" / "ego_dlc_split" / "libraries" / "wares.xml",
       '<wares><ware id="spice" group="minerals"><price min="5" average="9" max="12"/>'
       '</ware></wares>')
    ext = tmp_path / "extensions"
    _mod(ext, "aaa_price", {"libraries/wares.xml": ORE_PRICE.format(v=5000)})
    _mod(ext, "bbb_new", {"libraries/wares.xml":
         '<diff><add sel="/wares"><ware id="newware" group="minerals">'
         '<price min="1" average="2" max="3"/></ware></add></diff>'})
    monkeypatch.setattr(_merge, "REFERENCE", ref)
    db = tmp_path / "eff.sqlite"
    _effective.build(_cfg(ref), db, dirs=[ext], kinds=("ware",))
    con = sqlite3.connect(db)
    # preconditions the tests below lean on, read from the store itself
    ore = con.execute("SELECT a.value, a.origin FROM attrs a JOIN entities e ON "
                      "e.id=a.entity_id WHERE e.name='ore' AND a.prop='price.average'"
                      ).fetchone()
    assert ore == ("5000", "aaa_price"), ore
    con.close()
    return db


def _ls_names(capsys) -> set[str]:
    out = capsys.readouterr().out
    return {ln.split()[0] for ln in out.splitlines()
            if ln.strip() and not ln.startswith(" ") and "ware(s)" not in ln}


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 AN-3: --modified-only hides an "
                   "entity a mod changed only an attribute of")
def test_AN3_modified_only_lists_an_attribute_only_change(tmp_path, hermetic,
                                                          monkeypatch, capsys):
    db = _store(tmp_path, monkeypatch)
    capsys.readouterr()
    assert _effectivecli.main(["--db", str(db), "ls", "ware", "--modified-only"]) == 0
    assert "ore" in _ls_names(capsys)


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 AN-3: --modified-only lists a "
                   "DLC-only entity no mod touched")
def test_AN3_modified_only_does_not_list_a_DLC_only_entity(tmp_path, hermetic,
                                                          monkeypatch, capsys):
    db = _store(tmp_path, monkeypatch)
    capsys.readouterr()
    assert _effectivecli.main(["--db", str(db), "ls", "ware", "--modified-only"]) == 0
    names = _ls_names(capsys)
    assert "newware" in names, names          # control: a real mod change IS listed
    assert "spice" not in names, names


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 AN-3: plain `ls` puts no mod "
                   "marker on an attribute-only change")
def test_AN3_plain_ls_marks_an_attribute_only_change(tmp_path, hermetic,
                                                     monkeypatch, capsys):
    db = _store(tmp_path, monkeypatch)
    capsys.readouterr()
    assert _effectivecli.main(["--db", str(db), "ls", "ware"]) == 0
    ore = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("ore ")]
    assert len(ore) == 1 and "aaa_price" in ore[0], ore


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 AN-4: 'WON, not introduced' "
                   "fires on a registry entity the mod genuinely added")
def test_AN4_who_sets_does_not_disclaim_a_genuinely_added_entity(tmp_path, hermetic,
                                                                 monkeypatch, capsys):
    db = _store(tmp_path, monkeypatch)
    capsys.readouterr()
    assert _effectivecli.main(["--db", str(db), "who-sets", "ware", "newware"]) == 0
    out = capsys.readouterr().out
    assert "bbb_new add" in out, out          # control: the chain names the adder
    assert "not which introduced" not in out, out


# =============================================================================
# AN-5  x4compat: earlier mod REMOVES a node a later mod REPLACES
# =============================================================================

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 AN-5: the later replace is a "
                   "no-op after the earlier remove, but is named the winner")
def test_AN5_a_replace_after_a_remove_does_not_win(tmp_path, hermetic):
    ref = _ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "a_mod", {"libraries/wares.xml":
         "<diff><remove sel=\"//ware[@id='ore']\"/></diff>"})
    _mod(ext, "b_mod", {"libraries/wares.xml":
         "<diff><replace sel=\"//ware[@id='ore']\"><ware id=\"ore\"><price average=\"7\"/>"
         "</ware></replace></diff>"})
    cfg = _cfg(ref)
    # The toolkit's OWN merge engine: a removes ore, b's replace then matches nothing.
    merged = _merge.build_effective(
        "libraries/wares.xml",
        _merge.replace(cfg, overlays=(ext / "a_mod", ext / "b_mod"))).tree
    assert merged.find("ware[@id='ore']") is None
    hard = [c for c in _compat.analyze(ext, config=cfg).by_kind("HARD")
            if set(c.mods) == {"a_mod", "b_mod"}]
    assert len(hard) == 1, hard
    assert hard[0].live_value_owner() != "b_mod", hard[0]


# =============================================================================
# AN-6  x4similar reads raw files: a <diff> ship patch is invisible
# =============================================================================

_SHIP = ('<macros><macro name="ship_a_macro" class="ship_s"><properties>'
         '<purpose primary="fight"/><hull max="1000"/><people capacity="2"/>'
         '<storage missile="10" unit="0"/><secrecy level="1"/>'
         '</properties></macro></macros>')


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 AN-6: a <diff> ship patch is "
                   "skipped; the ship scores at its vanilla value")
def test_AN6_a_diff_patched_ship_is_scored_at_its_patched_value(tmp_path, hermetic):
    ref = tmp_path / "reference"
    _w(ref / "assets" / "units" / "size_s" / "macros" / "ship_a_macro.xml", _SHIP)
    ext = tmp_path / "extensions"
    _mod(ext, "hull_mod", {"assets/units/size_s/macros/ship_a_macro.xml":
         '<diff><replace sel="//macro[@name=\'ship_a_macro\']/properties/hull/@max">'
         '5000</replace></diff>'})
    vecs = [v for v in _similarity._collect_all(ref, ext, [], dlc_dirs=[])
            if v.macro_name == "ship_a_macro"]
    assert vecs, "precondition: the base ship was scanned"
    assert all(v.stats.get("hull.max") == 5000 for v in vecs), \
        [(v.source, v.stats.get("hull.max")) for v in vecs]


# =============================================================================
# AN-7  x4compat help says 'installed' (scans active); x4stats resolves a
#       candidate's selectors against mods that load AFTER it
# =============================================================================

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 AN-7: x4compat help promises "
                   "the INSTALLED set; analyze() scans the ACTIVE set")
def test_AN7_x4compat_help_names_the_scope_it_scans(capsys):
    texts = []
    for argv in (["-h"], ["check", "-h"]):
        with pytest.raises(SystemExit):
            _compat.main(argv)
        texts.append(capsys.readouterr().out)
    assert "installed" not in " ".join(texts).lower(), texts


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 AN-7: x4stats resolves the "
                   "candidate against mods that load after it")
def test_AN7_x4stats_does_not_resolve_against_later_mods(tmp_path, hermetic, capsys):
    ref = _ref(tmp_path)
    ext = tmp_path / "extensions"
    # c_mod loads BEFORE z_mod, so its sel on zware matches nothing in the engine
    cand = _mod(ext, "c_mod", {"libraries/wares.xml":
                "<diff><replace sel=\"//ware[@id='zware']/price/@average\">5</replace></diff>"})
    _mod(ext, "z_mod", {"libraries/wares.xml":
         '<diff><add sel="/wares"><ware id="zware" group="minerals">'
         '<price min="1" average="100" max="200"/></ware></add></diff>'})
    # control: the toolkit's own merge in load order leaves zware at 100
    live = _merge.build_effective("libraries/wares.xml", _merge.replace(
        _cfg(ref), overlays=(ext / "c_mod", ext / "z_mod"))).tree
    assert live.find("ware[@id='zware']/price").get("average") == "100"
    _stats.main(["wares", str(cand), "--ext-dir", str(ext), "--reference", str(ref)])
    out = capsys.readouterr().out
    assert "candidate avg price : 5 " not in out, out


# =============================================================================
# AN-8  x4xref: cue-edge tags unqueryable, the hint loops, check_* docstring
# =============================================================================

_MD = (b'<mdscript name="S"><cues><cue name="A"><conditions>'
       b'<check_object object="player.ship"/></conditions>'
       b'<actions><signal_cue cue="B"/></actions></cue><cue name="B"/></cues></mdscript>')


def _xref_tsv(tmp_path) -> Path:
    rows: list = []
    _xref._walk(etree.fromstring(_MD), "base", "md/s.xml", rows)
    return _xref.write_tsv(rows, tmp_path / "x.tsv")


def test_AN8_a_cue_edge_tag_is_queryable(tmp_path, capsys):
    tsv = _xref_tsv(tmp_path)
    _xref.main(["who-calls", "signal_cue", "--tsv", str(tsv)])
    out = capsys.readouterr().out
    # The hit list, not the hint: the hint also prints "1 occurrence(s)".
    assert "occurrence(s) across" in out, out


def test_AN8_the_hint_never_suggests_the_command_just_run(tmp_path, capsys):
    tsv = _xref_tsv(tmp_path)
    _xref.main(["cue", "signal_cue", "--tsv", str(tsv)])
    out = capsys.readouterr().out
    assert "no references to cue 'signal_cue'" in out, out   # precondition
    assert "x4xref cue signal_cue" not in out, out


def test_AN8_docstring_exclusion_claim_matches_the_walker():
    rows: list = []
    _xref._walk(etree.fromstring(_MD), "base", "md/s.xml", rows)
    indexed = {r.name for r in rows if r.kind == "action"}
    claims_check_excluded = "check_*" in (_xref.__doc__ or "")
    assert not (claims_check_excluded and "check_object" in indexed), indexed


# =============================================================================
# FR-1  _fold hashes the folder NAME, not its install ROOT
# =============================================================================

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 FR-1: moving a mod between "
                   "install roots leaves the content digest unchanged")
def test_FR1_moving_a_mod_between_roots_moves_the_content_digest(tmp_path):
    ref = _ref(tmp_path)
    game, prof = tmp_path / "game_ext", tmp_path / "profile_ext"
    prof.mkdir()
    _mod(game, "m", {"libraries/wares.xml": ORE_PRICE.format(v=1)})
    before = _freshness.content_detail(ref, [game, prof], profile=None)
    h_before = _freshness.hash_content(ref, [game, prof], profile=None)
    os.rename(game / "m", prof / "m")          # rename keeps every file's mtime
    after = _freshness.content_detail(ref, [game, prof], profile=None)
    kinds = sorted(c["kind"] for c in _freshness.diff_detail(before, after))
    assert kinds == ["added", "removed"], kinds  # the localiser DOES see the move
    assert _freshness.hash_content(ref, [game, prof], profile=None) != h_before


# =============================================================================
# FR-2  ENGINE_SOURCES vs the modules that actually run on the store build
# =============================================================================

#: Modules that run during a build but cannot change the store's BYTES: the stamp
#: itself (F53), the mutation refusal, and path configuration (captured by the
#: CONTENT axis's reference survey, not by code).
_NOT_BYTES = {"_freshness.py", "_mutation.py", "_paths.py"}


def _traced_store_build(tmp_path, monkeypatch) -> set[str]:
    ref = _ref(tmp_path)
    _w(ref / "assets" / "props" / "engines" / "macros" / "engine_a_macro.xml",
       '<macros><macro name="engine_a_macro" class="engine"><properties>'
       '<thrust forward="100"/></properties></macro></macros>')
    _w(ref / "extensions" / "ego_dlc_split" / "libraries" / "wares.xml",
       '<wares><ware id="spice"/></wares>')
    ext = tmp_path / "extensions"
    _mod(ext, "aaa", {
        "libraries/wares.xml": ORE_PRICE.format(v=5),
        "assets/props/engines/macros/engine_a_macro.xml":
            '<diff><replace sel="//macro/properties/thrust/@forward">9</replace></diff>'})
    _mod(ext, "bbb", {"libraries/wares.xml": '<wares><ware id="x"/></wares>'})
    pkg = str(Path(_effective.__file__).resolve().parent)
    ran: set[str] = set()

    def prof(frame, event, arg):
        if event == "call" and frame.f_code.co_filename.startswith(pkg):
            ran.add(os.path.basename(frame.f_code.co_filename))

    sys.setprofile(prof)
    try:
        _effective.build(_cfg(ref), tmp_path / "eff.sqlite", dirs=[ext])
    finally:
        sys.setprofile(None)
    assert "_merge.py" in ran and "_effective.py" in ran, ran   # the trace works
    return ran - _NOT_BYTES


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 FR-2: code that shapes the "
                   "store runs outside ENGINE_SOURCES (_provenance, _compat)")
def test_FR2_every_module_that_shapes_the_store_is_an_engine_source(
        tmp_path, hermetic, monkeypatch):
    ran = _traced_store_build(tmp_path, monkeypatch)
    assert ran <= set(_freshness.ENGINE_SOURCES), sorted(ran - set(_freshness.ENGINE_SOURCES))


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 FR-2: ENGINE_SOURCES names "
                   "modules the store build never runs (_diff, _xpath, _scan)")
def test_FR2_every_engine_source_runs_on_the_store_build(tmp_path, hermetic, monkeypatch):
    ran = _traced_store_build(tmp_path, monkeypatch)
    assert set(_freshness.ENGINE_SOURCES) <= ran, sorted(set(_freshness.ENGINE_SOURCES) - ran)


# =============================================================================
# FR-3  x4xref indexes every install root but stamps only one
# =============================================================================

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 FR-3: a change in a root the "
                   "index covers does not mark it STALE")
def test_FR3_a_change_in_an_indexed_root_marks_the_index_stale(tmp_path, hermetic,
                                                               monkeypatch, capsys):
    ref = _ref(tmp_path)
    game, prof = tmp_path / "game_ext", tmp_path / "profile_ext"
    _mod(game, "g", {"md/g.xml": '<mdscript name="G"><cues/></mdscript>'})
    _mod(prof, "p", {"md/p.xml": '<mdscript name="P"><cues><cue name="PC"/></cues></mdscript>'})
    monkeypatch.setattr(_registry, "default_installed_dirs", lambda: [game, prof])
    monkeypatch.setattr(_registry, "GAME_EXTENSIONS", game)
    monkeypatch.setattr(_merge, "REFERENCE", ref)
    monkeypatch.setattr(_merge.Config, "dlc_dirs", lambda self: [])
    tsv = tmp_path / "xref.tsv"
    assert _xref.main(["build", "--reference", str(ref), "--ext-dir", str(game),
                       "--out", str(tsv)]) == 0
    assert "PC" in tsv.read_text(encoding="utf-8")   # the PROFILE root was indexed
    capsys.readouterr()
    _mod(prof, "p2", {"md/p2.xml": '<mdscript name="P2"><cues/></mdscript>'})
    _xref.main(["cue", "PC", "--tsv", str(tsv)])
    assert "STALE" in capsys.readouterr().err


# =============================================================================
# FR-4  a reference (game) change is blamed on mods; `changed` says "no change"
# =============================================================================

def _fr4(tmp_path):
    ref = _ref(tmp_path)
    ext = tmp_path / "extensions"
    _mod(ext, "m", {"libraries/wares.xml": ORE_PRICE.format(v=1)})
    before = _freshness.fingerprint(_cfg(ref), [ext], profile=None)
    (ref / "newdir").mkdir()                      # a game update reshapes reference\
    _w(ref / "newdir" / "x.xml", "<x/>")
    after = _freshness.fingerprint(_cfg(ref), [ext], profile=None)
    assert before["content"] != after["content"]  # precondition: the axis moved
    return ref, ext, before, after


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 FR-4: a reference-only move is "
                   "reported as a MOD change")
def test_FR4_the_banner_attributes_a_reference_move_to_the_reference(tmp_path):
    _ref_, _ext, before, after = _fr4(tmp_path)
    reasons = " ".join(_freshness.compare(before, after, engine_dependent=False).reasons)
    assert "reference" in reasons.lower(), reasons


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 FR-4: `x4modlist changed` says "
                   "'no change' for the move the banner sent you to it for")
def test_FR4_changed_does_not_say_no_change_after_a_reference_move(tmp_path, hermetic,
                                                                   monkeypatch, capsys):
    ref, ext, before, _after = _fr4(tmp_path)
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(before), encoding="utf-8")
    monkeypatch.setattr(_changed, "_dirs", lambda: [ext])
    monkeypatch.setattr(_merge, "REFERENCE", ref)
    rc = _changed.cmd_changed(argparse.Namespace(since=str(snap), files=False, usn=False))
    out = capsys.readouterr().out
    assert not (rc == 0 and "no change" in out), (rc, out)


# =============================================================================
# FR-5  case-folds with no test (PASS by design; each kills its mutant)
# =============================================================================

def test_FR5_an_uppercase_XML_suffix_is_an_engine_file(tmp_path):
    ref = _ref(tmp_path)
    ext = tmp_path / "extensions"
    mod = _mod(ext, "m", {})
    f = _w(mod / "libraries" / "WARES.XML", "<diff/>")
    h1 = _freshness.hash_content(ref, [ext], profile=None)
    f.write_text("<diff><!-- longer --></diff>", encoding="utf-8")
    assert _freshness.hash_content(ref, [ext], profile=None) != h1, \
        "an edit to a .XML file must move the content axis"


@pytest.mark.parametrize("value", ["True", "TRUE"])
def test_FR5_profile_enabled_is_case_insensitive(tmp_path, value):
    prof = _w(tmp_path / "content.xml",
              f'<content><extension id="m" enabled="{value}"/></content>')
    assert _freshness._profile_decisions(prof) == {"m": True}
    assert _registry.ingest_content_xml(prof) == [("m", True)]

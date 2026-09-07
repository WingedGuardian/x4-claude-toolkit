"""B2/B3: x4effective must state its scope instead of returning a bare miss.

`_reject_unknown_kind` already does this for an unknown KIND ("stored kinds
are: ..."). A miss on a name that is simply outside the indexed slice -- a sector,
a zone, a character macro -- printed `no macro named 'x'` and exited 1, which
reads exactly like "no mod changes it" while the truth is "this tool never looked".

MEASURED scope at the time of writing: 3,349 of 7,995 corpus macros are outside
the store (galaxy map ~1,371, characters/npc ~1,810), while balance classes are
99.0% covered.
"""

import pytest
import sqlite3

from x4validate import _effective, _effectivecli, _merge


def _store(tmp_path):
    db = tmp_path / "eff.sqlite"
    con = sqlite3.connect(db)
    con.executescript(_effective._SCHEMA)
    con.execute("INSERT INTO meta VALUES ('schema_version','1')")
    con.execute("INSERT INTO meta VALUES ('active_mods','112')")
    con.execute("INSERT INTO entities VALUES (1,'macro','ship_x_macro','ship_s','a.xml','base',NULL)")
    con.execute("INSERT INTO entities VALUES (2,'ware','ore','minerals','w.xml','base',NULL)")
    con.execute("INSERT INTO attrs VALUES (1,'hull.max','100',100.0,'base',NULL)")
    con.commit()
    con.row_factory = sqlite3.Row
    return con


def test_scope_note_names_indexed_kinds_and_exclusions():
    note = _effectivecli.scope_note()
    assert "ware" in note and "macro" in note and "job" in note
    assert "BLIND-SPOTS" in note


def test_scope_note_names_the_documented_exclusions():
    note = _effectivecli.scope_note()
    low = note.lower()
    assert "galaxy" in low or "map" in low, "map macros are out of scope and must say so"
    assert "character" in low
    assert "lua" in low


def test_a_missing_entity_states_scope_rather_than_implying_absence(tmp_path, capsys):
    con = _store(tmp_path)
    args = type("A", (), {"kind": "macro", "name": "cluster_01_sector001_macro"})()
    rc = _effectivecli._cmd_show(con, args)
    err = capsys.readouterr().err
    assert rc == 1
    assert "BLIND-SPOTS" in err, (
        "a miss must distinguish 'nothing changed it' from 'never indexed'")


def test_coverage_command_reports_kinds_sources_and_counts(tmp_path, capsys):
    con = _store(tmp_path)
    rc = _effectivecli._cmd_coverage(con, type("A", (), {})())
    out = capsys.readouterr().out
    assert rc == 0
    assert "macro" in out and "ware" in out
    assert "2" in out                       # entity count
    assert "BLIND-SPOTS" in out


# --- B4: the runtime claim and the register must not drift apart --------------

def test_scope_note_lists_exactly_the_kinds_the_store_can_build():
    """If a kind is added to BUILDABLE_KINDS and not to the scope note, the tool
    starts understating what it holds -- and the understatement is invisible."""
    note = _effectivecli.scope_note()
    for kind in _effective.BUILDABLE_KINDS:
        assert kind in note, f"BUILDABLE_KINDS has {kind!r} but the scope note omits it"


def test_scope_note_and_the_register_agree_on_exclusions():
    """Doc drift is the failure mode this whole change exists to prevent: a
    register that says one thing while the tool says another is worse than either
    alone, because both look authoritative.
    """
    from pathlib import Path as P
    reg = P(__file__).resolve().parent.parent / "docs" / "BLIND-SPOTS.md"
    if not reg.is_file():
        # SKIP, not `return`: a bare return is counted as a PASS, so this would report
        # green on a checkout without the register while asserting nothing -- and
        # X4_MAX_SKIPS, which exists to catch tests going dormant, cannot see it.
        pytest.skip("docs/BLIND-SPOTS.md is not present in this checkout")
    text = reg.read_text(encoding="utf-8").lower()
    note = _effectivecli.scope_note().lower()
    for term in ("galaxy", "character", "lua"):
        assert term in note and term in text, (
            f"{term!r} must appear in BOTH the runtime scope note and BLIND-SPOTS.md")


# --- base_has: a BARE FILENAME was a false POSITIVE (v3.1.0 review round 2) --------


def _mini_tree(tmp_path):
    """base + one DLC, the shape the suffix fallback exists for."""
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_text("<wares/>", encoding="utf-8")
    dlc = ref / "extensions" / "ego_dlc_test" / "libraries"
    dlc.mkdir(parents=True)
    (dlc / "wares.xml").write_text("<diff/>", encoding="utf-8")
    return _merge.Config(reference=ref)


def test_a_BARE_FILENAME_is_not_reported_as_shipped_by_base(tmp_path):
    """The final fallback matched any DLC path ENDING in the string, so a bare
    filename came back True. A false POSITIVE in a helper whose whole docstring is
    about preventing false NEGATIVES.

    MEASURED on the live tree before the fix: `wares.xml`, `macros.xml` and
    `components.xml` all returned True, matching `extensions/ego_dlc_*/libraries/...`.
    None of them is a vpath in any tree. The documented consumer is the
    plain-vs-nested decision (gotcha #6), where a wrong True points at the PLAIN form
    and produces an inert patch.
    """
    cfg = _mini_tree(tmp_path)
    assert _effective.base_has(cfg, "wares.xml") is False


def test_the_DLC_SUFFIX_fallback_still_works_for_a_real_vpath(tmp_path):
    """The twin, and the reason the guard is one separator rather than deleting the
    fallback: a caller holding `libraries/wares.xml` must still match the DLC's
    `extensions/ego_dlc_test/libraries/wares.xml`. That case needs a separator, so
    requiring one costs nothing."""
    cfg = _mini_tree(tmp_path)
    assert _effective.base_has(cfg, "libraries/wares.xml") is True
    assert _effective.base_has(cfg, "no/such/thing.xml") is False

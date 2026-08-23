"""B2/B3: x4effective must state its scope instead of returning a bare miss.

`_reject_unknown_kind` already does this for an unknown KIND ("stored kinds
are: ..."). A miss on a name that is simply outside the indexed slice -- a sector,
a zone, a character macro -- printed `no macro named 'x'` and exited 1, which
reads exactly like "no mod changes it" while the truth is "this tool never looked".

MEASURED scope at the time of writing: 3,349 of 7,995 corpus macros are outside
the store (galaxy map ~1,371, characters/npc ~1,810), while balance classes are
99.0% covered.
"""

import sqlite3

from x4validate import _effective


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
    note = _effective.scope_note()
    assert "ware" in note and "macro" in note and "job" in note
    assert "BLIND-SPOTS" in note


def test_scope_note_names_the_documented_exclusions():
    note = _effective.scope_note()
    low = note.lower()
    assert "galaxy" in low or "map" in low, "map macros are out of scope and must say so"
    assert "character" in low
    assert "lua" in low


def test_a_missing_entity_states_scope_rather_than_implying_absence(tmp_path, capsys):
    con = _store(tmp_path)
    args = type("A", (), {"kind": "macro", "name": "cluster_01_sector001_macro"})()
    rc = _effective._cmd_show(con, args)
    err = capsys.readouterr().err
    assert rc == 1
    assert "BLIND-SPOTS" in err, (
        "a miss must distinguish 'nothing changed it' from 'never indexed'")


def test_coverage_command_reports_kinds_sources_and_counts(tmp_path, capsys):
    con = _store(tmp_path)
    rc = _effective._cmd_coverage(con, type("A", (), {})())
    out = capsys.readouterr().out
    assert rc == 0
    assert "macro" in out and "ware" in out
    assert "2" in out                       # entity count
    assert "BLIND-SPOTS" in out


# --- B4: the runtime claim and the register must not drift apart --------------

def test_scope_note_lists_exactly_the_kinds_the_store_can_build():
    """If a kind is added to BUILDABLE_KINDS and not to the scope note, the tool
    starts understating what it holds -- and the understatement is invisible."""
    note = _effective.scope_note()
    for kind in _effective.BUILDABLE_KINDS:
        assert kind in note, f"BUILDABLE_KINDS has {kind!r} but the scope note omits it"


def test_scope_note_and_the_register_agree_on_exclusions():
    """Doc drift is the failure mode this whole change exists to prevent: a
    register that says one thing while the tool says another is worse than either
    alone, because both look authoritative.
    """
    from pathlib import Path as P
    reg = P(__file__).resolve().parent.parent / "docs" / "BLIND-SPOTS.md"
    if not reg.is_file():          # the register ships with the toolkit; skip if absent
        return
    text = reg.read_text(encoding="utf-8").lower()
    note = _effective.scope_note().lower()
    for term in ("galaxy", "character", "lua"):
        assert term in note and term in text, (
            f"{term!r} must appear in BOTH the runtime scope note and BLIND-SPOTS.md")

"""End-to-end: enumerate -> merge -> extract -> store -> query, with provenance."""

import os
import sqlite3

from x4validate import _effective, _merge


def _world(tmp_path):
    """A mini game: reference (wares + one base engine macro), one DLC, two mods:
    modA diffs the base engine thrust; modB adds a brand-new macro file."""
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_bytes(
        b'<wares><ware id="ore" group="minerals"><price min="1" average="2" max="3"/></ware></wares>')
    eng = ref / "assets" / "props" / "engines" / "macros"
    eng.mkdir(parents=True)
    (eng / "engine_arg_s_01_macro.xml").write_bytes(
        b'<macros><macro name="engine_arg_s_01_macro" class="engine">'
        b'<properties><thrust forward="100" reverse="30"/></properties></macro></macros>')
    # a DLC that unions in another ware
    dlc = ref / "extensions" / "ego_dlc_split" / "libraries"
    dlc.mkdir(parents=True)
    (dlc.parent / "libraries" / "wares.xml").write_bytes(
        b'<wares><ware id="spice" group="minerals"><price min="5" average="9" max="12"/></ware></wares>')

    exts = tmp_path / "extensions"
    # modA: diff the base engine thrust
    a = exts / "aaa_thrust" / "assets" / "props" / "engines" / "macros"
    a.mkdir(parents=True)
    (a / "engine_arg_s_01_macro.xml").write_bytes(
        b'<diff><replace sel="//macro[@name=\'engine_arg_s_01_macro\']/properties/thrust/@forward">'
        b'250</replace></diff>')
    (exts / "aaa_thrust" / "content.xml").write_bytes(
        b'<content id="aaa_thrust" name="A" version="1"/>')
    # modB: add a new engine macro file of its own
    b = exts / "bbb_newengine" / "assets" / "props" / "engines" / "macros"
    b.mkdir(parents=True)
    (b / "engine_new_01_macro.xml").write_bytes(
        b'<macros><macro name="engine_new_01_macro" class="engine">'
        b'<properties><thrust forward="900"/></properties></macro></macros>')
    (exts / "bbb_newengine" / "content.xml").write_bytes(
        b'<content id="bbb_newengine" name="B" version="1"/>')
    return ref, exts


def _build(tmp_path, monkeypatch):
    ref, exts = _world(tmp_path)
    # active_mods() reads a profile content.xml; force "no profile" -> all enabled.
    monkeypatch.setattr(_effective._registry, "ingest_content_xml",
                        lambda *a, **k: [])
    db = tmp_path / "eff.sqlite"
    _effective.build(_merge.Config(reference=ref), db, dirs=[exts],
                     kinds=("ware", "macro"))
    return db


def test_build_and_provenance(tmp_path, monkeypatch):
    db = _build(tmp_path, monkeypatch)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    # base engine thrust was overridden by modA
    row = con.execute(
        "SELECT a.value, a.origin, a.chain FROM attrs a JOIN entities e ON e.id=a.entity_id "
        "WHERE e.name='engine_arg_s_01_macro' AND a.prop='thrust.forward'").fetchone()
    assert row["value"] == "250"
    assert row["origin"] == "aaa_thrust"
    assert row["chain"] is not None  # modified -> chain recorded

    # untouched sibling attr stays base (no chain)
    rev = con.execute(
        "SELECT a.chain AS chain FROM attrs a JOIN entities e ON e.id=a.entity_id "
        "WHERE e.name='engine_arg_s_01_macro' AND a.prop='thrust.reverse'").fetchone()
    assert rev["chain"] is None

    # modB's new macro is present and attributed to modB
    nb = con.execute("SELECT origin FROM entities WHERE name='engine_new_01_macro'").fetchone()
    assert nb["origin"] == "bbb_newengine"

    # DLC-unioned ware coexists with base ware
    wares = {r[0] for r in con.execute("SELECT name FROM entities WHERE kind='ware'")}
    assert {"ore", "spice"} <= wares


def test_cli_queries(tmp_path, monkeypatch, capsys):
    db = _build(tmp_path, monkeypatch)
    monkeypatch.setattr(_effective._registry, "ingest_content_xml", lambda *a, **k: [])

    assert _effective.main(["--db", str(db), "ls", "macro", "--class", "engine"]) == 0
    out = capsys.readouterr().out
    assert "engine_arg_s_01_macro" in out and "engine_new_01_macro" in out

    assert _effective.main(["--db", str(db), "attr", "macro", "thrust.forward",
                            "--class", "engine", "--sort", "num"]) == 0
    out = capsys.readouterr().out
    assert "250" in out and "900" in out

    assert _effective.main(["--db", str(db), "who-sets", "macro",
                            "engine_arg_s_01_macro", "thrust.forward"]) == 0
    assert "aaa_thrust" in capsys.readouterr().out

    assert _effective.main(["--db", str(db), "diff-mod", "aaa_thrust"]) == 0
    assert "thrust.forward" in capsys.readouterr().out


def test_sql_rejects_writes(tmp_path, monkeypatch, capsys):
    db = _build(tmp_path, monkeypatch)
    assert _effective.main(["--db", str(db), "sql", "DELETE FROM entities"]) == 2


# --------------------------------------------------------------------------
# build-time guards, both found 2026-08-09 by racing builders in a concurrency
# probe (the probe's own first version silently stopped testing the race
# because it passed the newly-rejected kind -- which is how #2 surfaced).
# --------------------------------------------------------------------------

def test_build_rejects_an_unknown_kind(tmp_path, monkeypatch):
    """`--kinds shieldgenerator` (a CLASS, not a kind) used to write an empty
    store and exit 0, so every later query answered from an empty database and
    nothing ever said the name was wrong. The read side already refuses this."""
    import pytest
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    monkeypatch.setattr(_effective._registry, "ingest_content_xml", lambda *a, **k: [])
    with pytest.raises(ValueError) as exc:
        _effective.build(_merge.Config(reference=ref), tmp_path / "x.sqlite",
                         dirs=[], kinds=("shieldgenerator",))
    msg = str(exc.value)
    assert "shieldgenerator" in msg
    for kind in _effective.BUILDABLE_KINDS:
        assert kind in msg          # tells the user what IS buildable


def test_build_accepts_every_advertised_kind(tmp_path, monkeypatch):
    """Both sides asserted: a guard that rejected everything would pass the test
    above. BUILDABLE_KINDS must be exactly what build() will accept."""
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_bytes(b"<wares/>")
    (ref / "libraries" / "jobs.xml").write_bytes(b"<jobs/>")
    monkeypatch.setattr(_effective._registry, "ingest_content_xml", lambda *a, **k: [])
    db = _effective.build(_merge.Config(reference=ref), tmp_path / "all.sqlite",
                          dirs=[], kinds=_effective.BUILDABLE_KINDS)
    assert db.is_file()


def test_build_temp_file_is_unique_per_process(tmp_path, monkeypatch):
    """Two concurrent builds picked the SAME `<db>.tmp` and raced on os.replace,
    so BOTH died with a raw PermissionError (WinError 32) and no store was
    installed at all. Measured after the fix: 3 racers, all rc=0, store intact."""
    ref = tmp_path / "reference"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "jobs.xml").write_bytes(b"<jobs/>")
    monkeypatch.setattr(_effective._registry, "ingest_content_xml", lambda *a, **k: [])

    seen = []
    real_replace = _effective.os.replace

    def spy(src, dst):
        seen.append(str(src))
        return real_replace(src, dst)

    monkeypatch.setattr(_effective.os, "replace", spy)
    db = tmp_path / "eff.sqlite"
    _effective.build(_merge.Config(reference=ref), db, dirs=[], kinds=("job",))
    assert seen, "build never installed a temp file"
    assert str(os.getpid()) in seen[0], f"temp path not process-unique: {seen[0]}"
    assert not list(tmp_path.glob("*.tmp")), "temp file left behind"

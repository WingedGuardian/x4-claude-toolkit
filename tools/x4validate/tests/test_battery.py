"""Block-3 tool battery: the same "nothing examined must never render as OK"
rule, applied to the SIX tools that had only ever been run, never stress-tested.

The battery found one systemic defect and two local ones. All were reachable by
the cheapest possible adversarial input: point the tool at something that isn't
there and see whether it says so.
"""

from __future__ import annotations

import pytest

from x4validate import _input, _xref


# --- systemic: a nonexistent input must never yield a clean result ------------

def test_require_mod_dir_rejects_missing(tmp_path, capsys):
    """x4stats / x4similar / x4compat / x4diff each returned a confident EXIT-0
    clean bill of health for a directory that does not exist:
        "candidate introduces/changes no wares."
        "no near-duplicate ships found at this threshold."
        "0 hard-ish (HARD+FULL-OVERRIDE), 0 union-key"
        "## removed files (present only in OLD):"   (i.e. "it deleted everything")
    Only x4validate checked its input. A typo read as good news.
    """
    with pytest.raises(SystemExit) as exc:
        _input.require_mod_dir(tmp_path / "nope", "candidate mod folder")
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "does not exist" in err
    assert "never examined" in err


def test_require_mod_dir_rejects_a_file(tmp_path):
    f = tmp_path / "afile.xml"
    f.write_text("<x/>", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        _input.require_mod_dir(f)
    assert exc.value.code == 2


def test_require_mod_dir_accepts_a_real_mod(tmp_path):
    mod = tmp_path / "mymod"
    (mod / "libraries").mkdir(parents=True)
    (mod / "libraries" / "wares.xml").write_text("<diff/>", encoding="utf-8")
    _input.require_mod_dir(mod)          # must not raise


def test_empty_dir_warns_but_proceeds(tmp_path, capsys):
    """An existing-but-empty folder is the same trap in a different hat, but it
    can be legitimate (assets-only), so it warns rather than exiting."""
    mod = tmp_path / "emptymod"
    mod.mkdir()
    _input.require_mod_dir(mod)          # must not raise
    assert "contains no XML" in capsys.readouterr().err


def test_packed_only_mod_is_not_called_empty(tmp_path, capsys):
    """A packed mod has ZERO loose *.xml. A naive rglob check would call every
    packed mod empty — the blind spot that made x4validate pass packed mods."""
    import hashlib
    mod = tmp_path / "packedmod"
    mod.mkdir()
    data = b"<diff/>"
    (mod / "ext_01.cat").write_text(
        f"libraries/wares.xml {len(data)} 1700000000 {hashlib.md5(data).hexdigest()}\n",
        encoding="utf-8")
    (mod / "ext_01.dat").write_bytes(data)
    assert _input.has_any_xml(mod) is True
    _input.require_mod_dir(mod)
    assert "contains no XML" not in capsys.readouterr().err


# --- x4xref: wrong kind must not look like a real negative --------------------

def _rows():
    return [
        _xref.XrefRow("event", "event_player_ejected", "base", "md/n.xml", "PlayerEjected", 766, ""),
        _xref.XrefRow("action", "set_object_min_hull", "base", "md/o.xml", "SomeCue", 12, ""),
    ]


def test_wrong_kind_points_at_the_right_command(capsys):
    """`who-calls event_player_ejected` printed EXACTLY the same line as
    `who-calls a_name_that_does_not_exist` — while the first is in the index 5
    times as an event. That was also the example CLAUDE.md advertises."""
    _xref._hint_other_kinds(_rows(), "event_player_ejected", "action")
    out = capsys.readouterr().out
    assert "IS in the index under other kind(s)" in out
    assert "who-listens event_player_ejected" in out


def test_truly_absent_name_is_reported_as_a_real_negative(capsys):
    _xref._hint_other_kinds(_rows(), "no_such_thing_anywhere", "action")
    out = capsys.readouterr().out
    assert "does not appear under ANY kind" in out
    assert "real negative" in out
    assert "other kind" not in out


# --- x4effective: a capped count must not read as a total ---------------------

def test_truncated_count_says_so():
    """`--limit` defaults to 200 and the footer printed a bare "200 ware(s)"
    while the store holds 2,431. The cap made the count WRONG, not just short."""
    from x4validate._effective import _count_line
    line = _count_line(200, 2431, "ware(s)")
    assert "200 of 2431" in line and "TRUNCATED" in line


def test_untruncated_count_stays_clean():
    from x4validate._effective import _count_line
    assert _count_line(2431, 2431, "ware(s)") == "2431 ware(s)"

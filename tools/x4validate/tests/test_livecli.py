"""`x4live`'s EXIT CODES are the contract, and each one must be reachable.

The tool exists to stop "I could not ask" from looking like "there is no disagreement",
so the mapping is the feature: **2** = non-answer, **3** = degraded/malformed, **1** =
a real finding, **0** = clean. A test suite that only proves the happy path would leave
the entire point of the tool unverified.

`extensions` and `oracle` read the registry and the effective store, so they are covered
by `gates/qa_sweep.py` against the real installation rather than mocked here. What is
tested here is everything that can be decided from a dump alone.
"""
from __future__ import annotations

import pytest

from x4validate import _livecli as C
from x4validate import _livedump as L
from test_livedump import good_rows, uidata


def write(tmp_path, text, name="uidata.xml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# ------------------------------------------------------------ exit-code contract

def test_missing_file_is_rc2_not_rc0(tmp_path):
    assert C.main(["--file", str(tmp_path / "absent.xml"), "dump"]) == 2


def test_a_file_that_is_not_uidata_is_rc2(tmp_path):
    assert C.main(["--file", write(tmp_path, "[project]\n"), "dump"]) == 2


def test_the_running_game_stub_is_rc2_never_an_empty_report(tmp_path):
    """The single most dangerous input: valid XML that parses to zero of everything."""
    stub = '<?xml version="1.0" encoding="UTF-8"?>\n<uidata version="1"/>\n'
    assert C.main(["--file", write(tmp_path, stub), "dump"]) == 2


def test_a_malformed_dump_is_rc3_not_rc2(tmp_path):
    """Degraded and unavailable are different states and get different codes."""
    bad = uidata([["HDR", "schema=2"], ["EXT", "m"], ["END", "999"]])
    assert C.main(["--file", write(tmp_path, bad), "dump"]) == 3


def test_a_valid_dump_is_rc0(tmp_path):
    assert C.main(["--file", write(tmp_path, uidata(good_rows(2))), "dump"]) == 0


@pytest.mark.parametrize("cmd", ["dump", "errors"])
def test_every_subcommand_maps_a_bad_dump_to_rc3(tmp_path, cmd):
    """The mapping lives in main(), so it must hold for each subcommand, not just one."""
    bad = uidata([["HDR", "s=1"], ["EXT", "m"], ["END", "42"]])
    assert C.main(["--file", write(tmp_path, bad), cmd]) == 3


# --------------------------------------------------------------- what it discloses

def test_dump_prints_the_kind_census_and_states_no_remainder(tmp_path, capsys):
    rc = C.main(["--file", write(tmp_path, uidata(good_rows(3))), "dump"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "TOTAL" in out and "every row is accounted for" in out
    assert "SCOPE" in out, "must say what it did NOT capture"


def test_errors_without_an_ERR_STATUS_row_is_rc3_not_an_empty_log(tmp_path):
    """No ERR_STATUS means the probe never asked. That is not 'zero errors'."""
    rows = [["HDR", "s=1"], ["EXT", "m"], ["END", "3"]]
    assert C.main(["--file", write(tmp_path, uidata(rows)), "errors"]) == 3


def test_errors_discloses_the_cap_and_the_true_total(tmp_path, capsys):
    """A capped list that hides its denominator is the narrowing step we refuse."""
    rows = [["HDR", "s=1"],
            ["ERR_STATUS", "OK", "5524", "cap=400", "emitting=400"],
            ["ERR", "5524", "2", "1787876497", "something went wrong"],
            ["END", "4"]]
    rc = C.main(["--file", write(tmp_path, uidata(rows)), "errors"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "5524" in out and "cap=400" in out
    assert "SAMPLE" in out, "a capped list must say it is a sample"


def test_a_probe_that_could_not_read_the_log_is_rc3(tmp_path):
    rows = [["HDR", "s=1"], ["ERR_STATUS", "ABSENT"], ["END", "3"]]
    assert C.main(["--file", write(tmp_path, uidata(rows)), "errors"]) == 3


# ------------------------------------------------------- the float32 comparison rule

@pytest.mark.parametrize("engine, store, same", [
    ("4.8000001907349", "4.8", True),      # float32 widened to double
    ("3.9000000953674", "3.9", True),
    ("2500", "2500", True),
    ("2500", "99999", False),
    ("fight", "fight", True),
    ("fight", "trade", False),
    ("6.3429999351501", "6.343", True),
])
def test_values_compare_at_float32_precision_not_as_strings(engine, store, same):
    """A string compare would flag EVERY float and bury a real disagreement."""
    assert C._agree(engine, store) is same


def test_the_mapping_table_is_not_empty():
    """Guard the guard: an empty table would make `oracle` compare nothing and pass."""
    assert len(C._BY_TYPE) >= 5
    assert all(m for m in C._BY_TYPE.values()), "a library type maps nothing"
    assert C._mapping_for("shiptypes_s", "hull") == ("hull.max", "identity")


def test_a_field_name_does_not_determine_its_meaning():
    """The reason the table is keyed by LIBRARY TYPE and not by field alone.

    `shield` on a shield generator is that generator's own capacity. `shield` on a
    SHIP is the loadout-derived total, which our store does not model. A flat map
    would apply one meaning to the other -- #18's category error in a lookup table.
    """
    assert C._mapping_for("shieldgentypes", "shield") == ("recharge.max", "identity")
    assert C._mapping_for("shiptypes_s", "shield") is None, (
        "a ship's `shield` must NOT map to a generator's recharge.max")
    # and `hull` is only ship-like; equipment reports a flat 1000 matching nothing
    assert C._mapping_for("shiptypes_s", "hull") is not None
    assert C._mapping_for("shieldgentypes", "hull") is None
    assert C._mapping_for("enginetypes", "hull") is None


def test_an_unknown_library_type_maps_nothing_rather_than_guessing():
    assert C._mapping_for("no_such_type", "hull") is None


def test_rotational_thrust_declares_the_radians_transform():
    """MEASURED: engine 3.8397243022919 rad == store 220 deg, on three axes."""
    for f in ("thrust_pitch", "thrust_yaw", "thrust_roll"):
        prop, tname = C._mapping_for("thrustertypes", f)
        assert tname == "degrees", f"{f} must declare the unit transform"
    assert C._TRANSFORMS["degrees"](3.8397243022919) == pytest.approx(220.0, abs=1e-4)
    assert C._TRANSFORMS["degrees"](4.1887903213501) == pytest.approx(240.0, abs=1e-4)
    assert C._TRANSFORMS["identity"](7.5) == 7.5


def test_derived_fields_are_named_not_folded_into_unmapped():
    """A known modelling gap must not hide inside a generic bucket (F72)."""
    # `storagecapacity` was in this list until 2026-08-30. It now has a MEASURED
    # traversal (_DERIVE, 5 of 5 exact across the fixture), so asserting it is
    # uncomputable would assert something false. `shipstoragecapacity` replaces it and
    # is still genuinely underived -- see P5.
    for f in ("dps", "shipstoragecapacity", "docks_m", "launchtubes_s", "sustaineddps"):
        assert f in C._DERIVED
    # and a derived field must never also carry a direct mapping
    for ltype, m in C._BY_TYPE.items():
        clash = set(m) & C._DERIVED
        assert not clash, f"{ltype} maps {clash}, which is also declared DERIVED"


@pytest.mark.parametrize("value, props, degenerate", [
    ("0", {"a": "0"}, True),                       # zero matches any zero
    ("1", {"a": "1"}, True),                       # so does one
    ("", {"a": ""}, True),
    ("2500", {"a": "2500"}, False),                # informative
    ("2500", {"a": "2500", "b": "2500", "c": "2500"}, True),  # shared by 3+ props
])
def test_degeneracy_rule(value, props, degenerate):
    """Value-matching alone invents mappings; this is what stops it."""
    assert C._is_degenerate(value, props) is degenerate


def test_a_wrong_unit_transform_is_CAUGHT_and_NAMED(tmp_path, capsys, monkeypatch):
    r"""The falsification twin for 5a: a declared transform must be able to go RED.

    If the transform were inferred at comparison time -- picking whichever of
    identity/degrees makes the values agree -- this check could never fail, which
    is the shape CLAUDE.md #26 exists to refuse. So we plant a RAW radian value
    against a degrees-mapped field and require BOTH that it is reported as a
    disagreement AND that it is labelled TRANSFORM-SUSPECT, because the raw value
    would have agreed.
    """
    rows = [["HDR", "schema=2"],
            # engine reports radians; the store holds 220 degrees. 220 raw would
            # only agree if the transform were being skipped.
            ["LIB_ENTRY_VAL", "thrustertypes", "m_fake", "thrust_pitch", "220"],
            ["END", "3"]]
    monkeypatch.setattr(C, "_store_props", lambda con, macro: {"thrust.pitch": "220"})
    monkeypatch.setattr(C, "_load", lambda p: L.parse(uidata(rows)))

    class _Fresh:
        fresh = True
    monkeypatch.setattr("x4validate._effective.store_freshness", lambda con: _Fresh())
    monkeypatch.setattr("x4validate._effective._connect", lambda db: object())
    monkeypatch.setattr("x4validate._effective.effective_db",
                        lambda: __import__("pathlib").Path(__file__))

    rc = C.cmd_oracle(None)
    out = capsys.readouterr().out
    assert rc == 1, "a wrong transform must be a FINDING, not a pass"
    assert "1 DISAGREE" in out
    assert "TRANSFORM-SUSPECT" in out, (
        "the raw value agreed, so the output must name the transform as the likely "
        "cause instead of silently correcting it")


def _fake_store(monkeypatch, props):
    """Point cmd_oracle at an in-memory store that is unconditionally FRESH."""
    import pathlib

    class _Fresh:
        fresh = True
    monkeypatch.setattr(C, "_store_props", lambda con, macro: props)
    monkeypatch.setattr("x4validate._effective.store_freshness", lambda con: _Fresh())
    monkeypatch.setattr("x4validate._effective._connect", lambda db: object())
    monkeypatch.setattr("x4validate._effective.effective_db",
                        lambda: pathlib.Path(__file__))


def test_engine_DERIVED_fields_are_counted_and_listed_separately(capsys, monkeypatch):
    """F72's gap must be NAMED, not folded into a generic "unmapped" bucket.

    Folding them together makes a known modelling gap look like a lookup table
    that merely needs more entries -- which is how a real gap stays invisible.
    """
    rows = [["HDR", "schema=2"],
            ["LIB_ENTRY_VAL", "weapons_lasers", "w", "dps", "290.9"],
            ["LIB_ENTRY_VAL", "weapons_lasers", "w", "zzz_not_a_field", "1"],
            ["END", "4"]]
    monkeypatch.setattr(C, "_load", lambda p: L.parse(uidata(rows)))
    _fake_store(monkeypatch, {"heat.coolrate": "2000"})

    rc = C.cmd_oracle(None, show_derived=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "engine-DERIVED (F72)    1" in out, "dps must land in the DERIVED bucket"
    assert "not mapped yet          1" in out, "an unknown field is NOT 'derived'"
    assert "290.9" in out, "--show-derived must print the engine's ground-truth value"


def test_show_derived_is_off_by_default(capsys, monkeypatch):
    rows = [["HDR", "schema=2"],
            ["LIB_ENTRY_VAL", "weapons_lasers", "w", "dps", "290.9"],
            ["END", "3"]]
    monkeypatch.setattr(C, "_load", lambda p: L.parse(uidata(rows)))
    _fake_store(monkeypatch, {"heat.coolrate": "2000"})
    C.cmd_oracle(None)
    assert "ground truth" not in capsys.readouterr().out


def test_module_exposes_no_argparse_at_import_time():
    """F69: the CLI must stay out of the freshness-hashed engine sources.

    `_livecli` is the CLI and `_livedump` is the library; the split only means
    something if the library half never grows a main().
    """
    assert not hasattr(L, "main")
    assert "argparse" not in dir(L)


# --------------------------------------------------------------------------- #
# the live half: a refusal must not look like an empty result
# --------------------------------------------------------------------------- #

def test_a_ramp_that_never_connects_prints_NO_TABLE_HEADER():
    """A header above zero rows reads as "zero results"; the truth is "never ran".

    That is the same narrowing-step-reports-success shape the whole toolkit is built
    against, so the header is printed only after the game connects. Without this test
    the ordering is a comment, not a contract.
    """
    import io

    from x4validate import _livecli, _livepipe

    def refuse(pipe, timeout):
        raise _livepipe.LiveQueryUnavailable("nothing connected")

    buf = io.StringIO()
    orig = _livecli._live_open
    _livecli._live_open = refuse
    try:
        with pytest.raises(_livepipe.LiveQueryUnavailable):
            _livecli.cmd_ramp(None, 1.0, out=buf)
    finally:
        _livecli._live_open = orig
    assert buf.getvalue() == "", f"printed a header with no table: {buf.getvalue()!r}"


def test_the_ramp_spans_BOTH_candidate_size_limits():
    """The cap is unknown: an unsourced 2047 from the winpipe DLL, and python's
    64 KB buffer. A ramp that stopped below either would report its OWN limit as the
    finding -- so it must straddle both, with a step either side.
    """
    from x4validate._livecli import RAMP_SIZES

    assert min(RAMP_SIZES) < 2047 < max(RAMP_SIZES)
    assert any(n < 2047 for n in RAMP_SIZES) and any(n > 2047 for n in RAMP_SIZES)
    # Was `>= 65536` until 2026-08-29. That premise was WRONG: our own read buffer is
    # 64 KiB, so a 65536-byte payload cannot round-trip through this module at all and
    # the ramp reported its OWN limit as the transport's cap. The honest requirement is
    # that it reaches the 64 KiB neighbourhood -- see
    # test_the_ramp_cannot_probe_past_our_own_buffer for the hard bound.
    assert max(RAMP_SIZES) >= 60000


def test_the_ramp_cannot_probe_past_our_own_buffer():
    """A ramp size at or above our own read buffer measures US, not the game.

    MEASURED 2026-08-29: with a top size of 65536 and a ~24-byte frame header, the
    message is 65560 bytes against a 65536-byte buffer, so the largest size always
    "failed" and the ramp reported `the ceiling lies in (60000, 65536]`. That is this
    module's buffer presented as the transport's cap -- and it was one live run away
    from being written into F74 as an engine measurement.
    """
    from x4validate._livecli import RAMP_SIZES
    from x4validate._livepipe import _BUF

    assert max(RAMP_SIZES) + 64 < _BUF, (
        f"ramp top {max(RAMP_SIZES)} + header is not safely below our {_BUF}-byte "
        f"buffer; the ramp would measure itself")


# --- F72: the groundtruth TSV as an oracle/mappings input --------------------- #
#
# The whole reason F72 sat open for three days: `cmd_mappings` AND `cmd_oracle` both read
# a uidata dump, which needs the engine-probe mod deployed and the game CLOSED. With that
# mod removed, `x4live oracle` exits 2 with "the probe did not run" and NO comparison can
# be made at all. `groundtruth` writes the identical data over the live pipe. It was a
# file-format mismatch, not modelling work.

TAB, NL = chr(9), chr(10)


def _gt(tmp_path, rows):
    p = tmp_path / "gt.tsv"
    p.write_text("# header comment" + NL + "librarytype\tmacro\tfield\tengine_value" + NL
                 + NL.join(rows) + NL, encoding="utf-8")
    return p


def test_groundtruth_reader_takes_BOTH_row_shapes(tmp_path):
    """A per-field row carries one field; a `*` row carries the engine's ALL-FIELDS reply
    tab-joined inside column 4. A naive 4-way split drops every `*` row -- it dropped 15
    of 15 while this was being written."""
    star = "shiptypes_s\tm1\t*\thull=2500" + TAB + "mass=6.34"
    per = "shiptypes_s\tm1\tspeed\t120"
    entries, st = C._entries_from_groundtruth(_gt(tmp_path, [star, per]))
    assert entries[("shiptypes_s", "m1")] == {"hull": "2500", "mass": "6.34",
                                              "speed": "120"}
    assert st["star_rows"] == 1 and st["field_rows"] == 1 and st["unparseable"] == 0


def test_a_PER_FIELD_row_WINS_over_the_same_cell_in_a_star_row(tmp_path):
    """The all-fields reply is one flattened string, so a value containing `=` or a tab is
    ambiguous inside it. The dedicated row is the more precise record of the same cell."""
    rows = ["shiptypes_s\tm1\t*\thull=1", "shiptypes_s\tm1\thull\t2500"]
    entries, _ = C._entries_from_groundtruth(_gt(tmp_path, rows))
    assert entries[("shiptypes_s", "m1")]["hull"] == "2500"


def test_unparseable_lines_are_COUNTED_not_silently_dropped(tmp_path):
    """A fixture that quietly loses rows reads downstream as 'the engine does not report
    that field'. Older fixtures predate the escaping fix and DO contain such lines --
    MEASURED: 4 of 104 in groundtruth-20260829."""
    rows = ["shiptypes_s\tm1\thull\t2500", "this line has no tabs at all"]
    entries, st = C._entries_from_groundtruth(_gt(tmp_path, rows))
    assert st["unparseable"] == 1 and st["parsed"] == 1
    assert entries[("shiptypes_s", "m1")]["hull"] == "2500"


def test_the_groundtruth_WRITER_escapes_tabs_and_newlines(tmp_path):
    """The writer joined rows with tabs and values could CONTAIN tabs -- a description
    does, and a `*` payload is itself tab-joined. Unescaped, the row structure breaks.
    Same defect `harvest` had; this is the second location."""
    nasty = "a" + TAB + "b" + NL + "c"
    escaped = (nasty.replace(chr(92), chr(92) * 2)
                    .replace(TAB, chr(92) + "t")
                    .replace(NL, chr(92) + "n"))
    assert TAB not in escaped and NL not in escaped
    assert C._unescape(escaped) == nasty, "the round trip must be lossless"


def test_unescape_is_a_NO_OP_on_a_fixture_written_before_the_fix():
    """Older fixtures contain no escapes, so reversing them must not corrupt anything."""
    assert C._unescape("hull=2500") == "hull=2500"


def test_a_DERIVED_field_never_also_carries_a_direct_mapping():
    """The invariant that forced a real decision: `unitcapacity` was declared DERIVED and
    then measured to be stored DIRECTLY (engine 25 == store `storage.unit` 25). A field
    cannot be both 'we cannot compute this' and 'here is how'. The measurement won and the
    _DERIVED entry was removed."""
    assert "unitcapacity" not in C._DERIVED
    prop, tname = C._mapping_for("shiptypes_l", "unitcapacity")
    assert prop == "storage.unit" and tname == "identity"
    # ...and NOT generalised past the evidence: it was proposed for l/xl only.
    assert C._mapping_for("shiptypes_s", "unitcapacity") is None


def test_coolingrate_is_NOT_mapped_for_turrets():
    """A coincidence the tool proposed and a human must reject: on the one sampled turret
    engine coolingrate=200 and rotationspeed.max=200, while the real prop `heat.coolrate`
    was ABSENT so nothing else could match. Cooling rate is not a rotation speed. Two
    engine fields claiming one prop is the tell, and nd=1 is why it survived."""
    assert C._mapping_for("weapons_turrets", "coolingrate") is None
    prop, _ = C._mapping_for("weapons_turrets", "rotation")
    assert prop == "rotationspeed.max"


# --- F72 P4: the connection traversal ----------------------------------------- #


def test_connected_macros_reads_the_refs_out_of_the_flattened_subtree():
    """F72 called this traversal unmodelled. The data was always in the store -- the
    flatten keeps the whole connection subtree, so the refs are plain attrs."""
    props = {
        "connections.connection[con_storage01].ref": "con_storage01",
        "connections.connection[con_storage01].macro.ref": "storage_x_macro",
        "connections.connection[con_dock_xs].macro.ref": "dock_y_macro",
        "connections.connection[con_dock_xs].macro.connection": "Connection_component",
        "hull.max": "2500",
    }
    got = C._connected_macros(props)
    assert sorted(got) == ["dock_y_macro", "storage_x_macro"]
    assert "con_storage01" not in got, "the .ref key is not a macro ref"


def test_storagecapacity_sums_cargo_max_over_connected_macros():
    """MEASURED 5 of 5 exact across the fixture (540, 700, 2300, 8200, 38000)."""
    store = {
        "ship": {"connections.connection[a].macro.ref": "s1",
                 "connections.connection[b].macro.ref": "s2"},
        "s1": {"cargo.max": "500"},
        "s2": {"cargo.max": "40"},
    }

    class _Con:
        pass

    import x4validate._livecli as M
    orig = M._store_props
    M._store_props = lambda con, m: store.get(m)
    try:
        assert M._derive_storagecapacity(_Con(), store["ship"]) == "540"
    finally:
        M._store_props = orig


def test_storagecapacity_returns_NONE_not_ZERO_when_nothing_carries_cargo():
    """⚠ The distinction the whole toolkit turns on. A fabricated 0 would be compared
    against the engine and could AGREE by accident, recording a computation we never
    made. An absence must stay an absence."""
    store = {"ship": {"connections.connection[a].macro.ref": "d1"},
             "d1": {"dock.capacity": "10"}}

    class _Con:
        pass

    import x4validate._livecli as M
    orig = M._store_props
    M._store_props = lambda con, m: store.get(m)
    try:
        assert M._derive_storagecapacity(_Con(), store["ship"]) is None
    finally:
        M._store_props = orig


def test_a_field_with_a_TRAVERSAL_is_no_longer_declared_uncomputable():
    """Same invariant that forced the unitcapacity decision: a field cannot be both
    'we cannot compute this' (_DERIVED) and 'here is how' (_DERIVE)."""
    assert "storagecapacity" in C._DERIVE
    assert "storagecapacity" not in C._DERIVED
    assert not (set(C._DERIVE) & C._DERIVED), "a field is both computed and uncomputable"


def test_shipstoragecapacity_is_still_DERIVED_because_no_traversal_reproduces_it():
    """P5, recorded rather than guessed. MEASURED: the scout reports engine
    shipstoragecapacity=0 while carrying a connected shipstorage macro with
    dock.capacity=10 -- so it is NOT a sum of connected capacities. Inventing a formula
    to close the row would be picking one of several defensible definitions and calling
    it modelled."""
    assert "shipstoragecapacity" in C._DERIVED
    assert "shipstoragecapacity" not in C._DERIVE


# --- unitcapacity: mapped where the evidence reaches, and no further ---------- #


def test_unitcapacity_is_mapped_for_M_because_the_POSITIVE_case_was_verified():
    """MEASURED in game 2026-08-31: `ship_arg_m_frigate_01_a_macro` returns engine 15
    and the store holds storage.unit 15.

    That matters because until then every M/S observation had been the NULL case
    (engine 0, store absent). A mapping verified only on nulls is one you have never
    seen discriminate -- it agrees whenever both sides are empty, which proves nothing
    about whether it reads the right property."""
    assert C._mapping_for("shiptypes_m", "unitcapacity") == ("storage.unit", "identity")
    assert C._mapping_for("shiptypes_l", "unitcapacity") == ("storage.unit", "identity")
    assert C._mapping_for("shiptypes_xl", "unitcapacity") == ("storage.unit", "identity")


def test_unitcapacity_is_NOT_mapped_for_S_and_the_reason_is_MEASURED():
    """Not caution -- arithmetic. MEASURED over the effective store: exactly TWO
    S-class macros carry `storage.unit` in the whole corpus
    (ship_kha_s_fighter_01_a_macro and _02_a_) and BOTH ARE ZERO.

    So there is no positive case to verify and none to get wrong: the mapping could
    never discriminate. M has 16 carriers, 12 nonzero. Mapping S would add a
    comparison that agrees vacuously forever, which is worse than an honest gap
    because it LOOKS like coverage."""
    assert C._mapping_for("shiptypes_s", "unitcapacity") is None
    assert C._mapping_for("shiptypes_xs", "unitcapacity") is None


def test_unitcapacity_is_not_both_mapped_and_conceded():
    """The invariant that forced the original decision: a field cannot be both
    'we cannot compute this' and 'here is how'."""
    assert "unitcapacity" not in C._DERIVED


# --- the star row: split on the ESCAPE, not on a real tab --------------------- #


def test_a_star_row_written_by_the_CURRENT_writer_yields_every_field(tmp_path):
    """★ The defect this pins, and it was self-inflicted.

    The `*` payload is the engine's all-fields reply, tab-joined INTERNALLY. The
    writer's escaping (added 2026-08-30 to stop a description's tab breaking the row
    structure) turns every one of those separators into a two-character escape. The
    reader still split on a REAL tab, found none, and parsed only the FIRST key=value.

    MEASURED: it cut `ship_arg_s_scout_01_a_macro` from 37 fields to 10, and the 27 it
    dropped were hull, mass, all six drag axes and all three inertia axes -- exactly
    the DIRECTLY COMPARABLE ones. The oracle then reported 0 comparable on that fixture
    and it read as "this capture is equipment-heavy" rather than "this capture is
    gutted". A fix for one silent-loss defect created another.
    """
    esc = chr(92) + "t"
    p = tmp_path / "gt.tsv"
    p.write_text(
        "librarytype\tmacro\tfield\tengine_value\n"
        "shiptypes_s\tm1\t*\thull=2500" + esc + "mass=6.34" + esc + "drag_forward=1.5\n",
        encoding="utf-8")
    got, st = C._entries_from_groundtruth(p)
    assert got[("shiptypes_s", "m1")] == {
        "hull": "2500", "mass": "6.34", "drag_forward": "1.5"}, (
        "only the first key=value survived -- the reader is splitting on a real tab")
    assert st["star_rows"] == 1


def test_a_star_row_from_a_PRE_ESCAPING_fixture_still_parses(tmp_path):
    """The twin, and it is why the reader picks the separator that is PRESENT rather
    than assuming a vintage. Fixtures written before 2026-08-30 carry REAL tabs inside
    the payload; they are the evidence base for F72 and must keep parsing."""
    p = tmp_path / "gt.tsv"
    p.write_text(
        "librarytype\tmacro\tfield\tengine_value\n"
        "shiptypes_s\tm1\t*\thull=2500\tmass=6.34\n", encoding="utf-8")
    got, _ = C._entries_from_groundtruth(p)
    assert got[("shiptypes_s", "m1")] == {"hull": "2500", "mass": "6.34"}


def test_the_real_fixtures_BOTH_yield_the_scouts_full_field_set():
    """End to end over the actual artifacts, both vintages. A unit fixture cannot
    catch a writer/reader disagreement that only shows up on real captures."""
    import pathlib
    base = pathlib.Path(__file__).resolve().parents[3] / "dev" / "_reports"
    key = ("shiptypes_s", "ship_arg_s_scout_01_a_macro")
    seen = 0
    for name in ("groundtruth-20260829-175342.tsv", "groundtruth-20260831-122748.tsv"):
        f = base / name
        if not f.is_file():
            continue
        seen += 1
        got, _ = C._entries_from_groundtruth(f)
        assert len(got.get(key, {})) == 37, (
            f"{name}: scout has {len(got.get(key, {}))} fields, expected 37")
    if seen == 0:
        pytest.skip("no groundtruth fixtures present in dev/_reports")

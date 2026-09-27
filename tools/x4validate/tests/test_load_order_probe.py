"""scripts/load-order-probe.py -- the experiment must be able to FAIL, and read real log lines.

The probe is only evidence if (a) its log reader recognises the engine's actual line shapes,
(b) a wrong order or a wrong apply outcome makes `score` return 1, and (c) the prediction is
derived from the rule and never from the result. Deployment and removal touch the game
install and are exercised by hand, not here.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "load_order_probe", Path(__file__).resolve().parents[1] / "scripts" / "load-order-probe.py")
lop = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lop)

BS = "\\"


def _sig(folder):
    return (f"[FileIO ] 0.00 File I/O: Failed to verify the file signature for file "
            f"'.{BS}extensions{BS}{folder}{BS}libraries{BS}wares.xml' (error: 14)\n")


def _nomatch(folder):
    # Shape copied from a real debug.txt line (material_library / sound_library errors).
    return (f"[=ERROR=] 0.00 No matching node for path '//ware[@id='energycells']/@lopd' in "
            f"patch file 'extensions{BS}{folder}{BS}libraries{BS}wares'. Skipping node.\n")


def test_read_log_orders_probes_and_counts_apply_errors():
    lines = [_sig("lo_probe_ca_add"), _sig("some_real_mod"), _sig("lo_probe_cb_use"),
             _sig("lo_probe_ca_add"), _nomatch("lo_probe_cc_use"), _nomatch("lo_probe_cc_use")]
    order, errors = lop.read_log(lines)
    assert order == ["lo_probe_ca_add", "lo_probe_cb_use"]      # real mods and repeats ignored
    assert errors == {"lo_probe_cc_use": 2}


def test_prediction_is_derived_from_the_rule_not_from_a_result():
    pred = lop.predict()
    order = pred["relative_order"]
    assert order.index("lo_probe_k_qa") < order.index("lo_probe_k_q_x")   # '_' after letters
    assert order.index("lo_probe_k_ya") < order.index("lo_probe_k_Zc")    # case-insensitive
    assert order[-1] == "lo_probe_ce_dep"                                  # waits for pass 2
    assert order.index("a_lo_probe_dlc") == 0
    for unknown in ("lo_probe_d_reqmiss", "lo_probe_d_cyc1", "lo_probe_d_dup1",
                    "lo_probe_d_disabled", "lo_probe_d_disdep", "lo_probe_d_profon",
                    "lo_probe_d_profnoattr", "lo_probe_k_ßa"):
        assert unknown not in order, f"{unknown} was never measured; it must stay UNKNOWN"


def test_sort_key_keeps_sharp_s_one_character():
    assert lop._rule_key("ßa") == "ßA"      # str.upper() would give 'SSA'


def _scored(tmp_path, lines):
    lop.build(tmp_path / "b")
    log = tmp_path / "debug.txt"
    log.write_text("".join(lines), encoding="utf-8")
    return lop.score(tmp_path / "b", log)


def _engine_as_predicted():
    pred = lop.predict()
    return [_sig(p) for p in pred["relative_order"]] + [_nomatch("lo_probe_cc_use")]


def test_score_passes_when_the_engine_matches(tmp_path):
    assert _scored(tmp_path, _engine_as_predicted()) == 0


def test_score_fails_on_a_wrong_order(tmp_path):
    lines = _engine_as_predicted()
    lines[1], lines[2] = lines[2], lines[1]
    assert _scored(tmp_path, lines) == 1


def test_score_fails_when_an_apply_outcome_differs(tmp_path):
    lines = [l for l in _engine_as_predicted() if "No matching node" not in l]
    assert _scored(tmp_path, lines) == 1        # cc_use predicted NO_MATCH, engine said OK


def test_score_refuses_a_log_without_probes(tmp_path):
    assert _scored(tmp_path, [_sig("some_real_mod")]) == 2


def test_build_writes_marker_and_prediction(tmp_path):
    lop.build(tmp_path)
    for folder in lop.PROBES:
        assert (tmp_path / folder / lop.MARKER).is_file()
        assert (tmp_path / folder / "libraries" / "wares.xml").is_file()
    assert json.loads((tmp_path / "PREDICTION.json").read_text(encoding="utf-8"))["applies"]


# --- round 2 (2026-09-26): optional dependency on a DISABLED mod, and a second root -------

PROFILE_PROBES = ("lo_probe_x_b", "lo_probe_x_d", "lo_probe_x_e")


def _sig_abs(folder):
    # A profile-root file cannot be './extensions/...'; its logged form is unmeasured, so
    # the reader must accept any path that ends in extensions/<folder>/libraries/wares.xml.
    return (f"[FileIO ] 0.00 File I/O: Failed to verify the file signature for file "
            f"'C:{BS}Users{BS}u{BS}Documents{BS}Egosoft{BS}X4{BS}1{BS}extensions{BS}{folder}"
            f"{BS}libraries{BS}wares.xml' (error: 14)\n")


def _nomatch_abs(folder):
    return (f"[=ERROR=] 0.00 No matching node for path '//ware[@id='energycells']/@x' in "
            f"patch file 'C:{BS}Users{BS}u{BS}Documents{BS}Egosoft{BS}X4{BS}1{BS}extensions"
            f"{BS}{folder}{BS}libraries{BS}wares'. Skipping node.\n")


def test_round2_probes_exist_with_their_roots():
    for p in ("lo_probe_d_optdis", "lo_probe_d_profoff", "lo_probe_d_optprofoff",
              "lo_probe_d_reqprofoff", "lo_probe_x_a", "lo_probe_x_c", "lo_probe_x_f",
              *PROFILE_PROBES):
        assert p in lop.PROBES, p
    assert {p for p in lop.PROBES if lop.root_of(p) == "profile"} == set(PROFILE_PROBES)
    # the optional-on-disabled probes really declare OPTIONAL deps; the control a REQUIRED one
    assert lop.PROBES["lo_probe_d_optdis"][1] == [("lo_probe_d_disabled", True)]
    assert lop.PROBES["lo_probe_d_optprofoff"][1] == [("lo_probe_d_profoff", True)]
    assert lop.PROBES["lo_probe_d_reqprofoff"][1] == [("lo_probe_d_profoff", False)]


def test_read_log_accepts_a_profile_root_path():
    order, errors = lop.read_log([_sig_abs("lo_probe_x_b"), _nomatch_abs("lo_probe_x_d")])
    assert order == ["lo_probe_x_b"]
    assert errors == {"lo_probe_x_d": 1}


def test_round2_unknowns_stay_out_of_the_prediction():
    order = lop.predict()["relative_order"]
    for unknown in ("lo_probe_d_optdis", "lo_probe_d_profoff", "lo_probe_d_optprofoff",
                    "lo_probe_d_reqprofoff", "lo_probe_x_f", *PROFILE_PROBES):
        assert unknown not in order, f"{unknown} was never measured; it must stay UNKNOWN"
    assert order.index("lo_probe_x_a") < order.index("lo_probe_x_c")


@pytest.mark.parametrize("nomatch,expect", [
    ((), "INTERLEAVED"),                                   # one walk over both roots, by name
    (("lo_probe_x_c",), "GAME_ROOT_FIRST"),                # a, c, then b, d
    (("lo_probe_x_b", "lo_probe_x_d"), "PROFILE_FIRST"),   # b, d, then a, c
    (("lo_probe_x_b",), "INCONSISTENT"),                   # no single layout explains it
])
def test_cross_root_layout_is_classified_from_the_apply_chain(nomatch, expect):
    loaded = {"lo_probe_x_a", "lo_probe_x_b", "lo_probe_x_c", "lo_probe_x_d"}
    assert lop.classify_roots(loaded, {p: 1 for p in nomatch}) == expect


def test_cross_root_layout_refuses_when_a_chain_probe_did_not_load():
    # a profile probe that never loaded makes NO error line -- that must not read as "OK"
    assert lop.classify_roots({"lo_probe_x_a", "lo_probe_x_c"}, {}) == "CANNOT_TELL"


def test_profile_writer_creates_only_new_marked_folders(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "Egosoft" / "X4" / "1" / "extensions"
    lop.build(src)
    dst.mkdir(parents=True)
    (dst / "lo_probe_x_b").mkdir()                          # someone else's folder, same name
    with pytest.raises(lop.ProbeRefused):
        lop.write_profile_probes(src, dst, apply=True)
    assert not any((dst / p).exists() for p in ("lo_probe_x_d", "lo_probe_x_e")), \
        "every guard must run before any write"
    (dst / "lo_probe_x_b").rmdir()
    lop.write_profile_probes(src, dst, apply=True)
    for p in PROFILE_PROBES:
        for f in (src / p).rglob("*"):
            if f.is_file():
                assert (dst / p / f.relative_to(src / p)).read_bytes() == f.read_bytes()
    assert sorted(d.name for d in dst.iterdir()) == sorted(PROFILE_PROBES)


def test_profile_writer_dry_run_writes_nothing(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "ext"
    lop.build(src)
    dst.mkdir()
    lop.write_profile_probes(src, dst, apply=False)
    assert list(dst.iterdir()) == []


def test_remove_covers_the_profile_root_and_only_probe_folders(tmp_path, monkeypatch):
    src, game, prof = tmp_path / "src", tmp_path / "game", tmp_path / "prof"
    lop.build(src)
    game.mkdir()
    prof.mkdir()
    lop.write_profile_probes(src, prof, apply=True)
    keep = prof / "real_mod"
    keep.mkdir()
    (keep / lop.MARKER).write_bytes(b"x")                  # marker but NOT an lo_probe id
    (keep / "content.xml").write_text('<content id="real_mod"/>', encoding="utf-8")
    monkeypatch.setattr(lop, "_ext_root", lambda: game)
    monkeypatch.setattr(lop, "_profile_root", lambda: prof)
    assert lop.remove(apply=True) == 0
    assert sorted(d.name for d in prof.iterdir()) == ["real_mod"]


def test_profile_entries_include_the_profile_disabled_probe(capsys):
    lop.main(["profile-entries"])
    out = capsys.readouterr().out
    assert '<extension id="lo_probe_d_profoff" enabled="false"/>' in out
    assert '<extension id="lo_probe_d_profon" enabled="true"/>' in out


# --- round 3 (2026-09-26): prove a profile-root file was APPLIED, and read the apply order ---
# Round 2 showed the engine LISTS profile-root mods (Extensions dialog) but the log never names
# that folder, so "not in the signature sequence" could not tell "not applied" from "applied,
# unsigned-and-unlogged". Every chain probe now carries a patch that can NEVER match: if its
# file is applied at all, the engine logs No-matching-node naming it, in apply order.

def _proof_line(folder, root="profile"):
    base = (f"C:{BS}Users{BS}user{BS}Documents{BS}Egosoft{BS}X4{BS}1{BS}extensions"
            if root == "profile" else "extensions")
    tag = folder.rsplit("_", 1)[-1]
    return (f"[=ERROR=] 0.00 No matching node for path '//ware[@id='energycells']/@loproof_{tag}'"
            f" in patch file '{base}{BS}{folder}{BS}libraries{BS}wares'. Skipping node." + chr(10))


def test_every_chain_probe_carries_a_proof_op():
    for p in lop.CHAIN:
        assert "@loproof_" in lop.PROBES[p][3], p


def test_a_proof_line_is_evidence_of_application_not_a_chain_error():
    lines = [_proof_line("lo_probe_x_b"), _nomatch_abs("lo_probe_x_d"), _proof_line("lo_probe_x_d")]
    _order, errors = lop.read_log(lines)
    assert errors == {"lo_probe_x_d": 1}, "a proof line must never read as a chain miss"
    assert lop.read_proofs(lines) == ["lo_probe_x_b", "lo_probe_x_d"]   # apply order, deduped


def test_proofs_make_the_chain_classifiable_without_signature_lines(tmp_path):
    lop.build(tmp_path / "b", only="lo_probe_x_")
    lines = [_sig(p) for p in ("lo_probe_x_a", "lo_probe_x_c")]
    lines += [_proof_line(p, "game") for p in ("lo_probe_x_a", "lo_probe_x_c")]
    lines += [_nomatch("lo_probe_x_c")]
    lines += [_proof_line(p) for p in ("lo_probe_x_b", "lo_probe_x_d")]
    log = tmp_path / "debug.txt"
    log.write_text("".join(lines), encoding="utf-8")
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = lop.score(tmp_path / "b", log)
    out = buf.getvalue()
    assert "cross-root layout: GAME_ROOT_FIRST" in out, out
    assert "apply order (proof lines): lo_probe_x_a, lo_probe_x_c, lo_probe_x_b, lo_probe_x_d" in out, out
    assert rc == 0, out


def test_build_only_writes_the_selected_subset_and_its_prediction(tmp_path):
    lop.build(tmp_path, only="lo_probe_x_")
    built = sorted(d.name for d in tmp_path.iterdir() if d.is_dir())
    assert built == sorted(p for p in lop.PROBES if p.startswith("lo_probe_x_"))
    pred = json.loads((tmp_path / "PREDICTION.json").read_text(encoding="utf-8"))
    assert set(pred["relative_order"]) <= set(built)
    assert lop.built_probes(tmp_path) == built

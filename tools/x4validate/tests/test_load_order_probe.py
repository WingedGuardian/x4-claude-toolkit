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

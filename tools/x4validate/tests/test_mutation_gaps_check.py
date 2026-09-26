"""Mutation-campaign gaps in `_check` / the x4validate CLI verdict (campaign 2,
2026-09-26). Each test names the surviving mutant it was written to kill and was
verified to FAIL with it applied and PASS without it.

`_merge.build_effective` is stubbed where the question is how `_check` COUNTS and
REPORTS a merge outcome, not how the merge is built; the counting logic runs for real.
"""
from __future__ import annotations

import json
from pathlib import Path

from lxml import etree

from x4validate import _check, _cli, _merge


def _w(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _config(tmp_path: Path) -> _merge.Config:
    ref = tmp_path / "reference"
    _w(ref / "libraries/wares.xml", "<wares/>")
    return _merge.Config(reference=ref)


def _mod_with_diffs(tmp_path: Path, n: int) -> Path:
    mod = tmp_path / "mymod"
    _w(mod / "content.xml", '<content id="mymod" version="100"/>')
    for i in range(n):
        _w(mod / f"libraries/other{i}.xml",
           "<diff><add sel=\"/root\"><x/></add></diff>")
    return mod


# --------------------------------------------------------------------------- C1
def test_warn_only_report_has_no_errors_and_the_cli_exits_zero(tmp_path, monkeypatch, capsys):
    """C1: a WARN is not an ERROR. `Report.errors` feeds the exit code and the JSON
    `error_count`; counting warnings there turns every advisory into a gating failure."""
    rep = _check.Report()
    rep.add("warn", "sel", "advisory only", "libraries/wares.xml")
    rep.add("info", "path", "fyi", "libraries/wares.xml")
    assert rep.errors == []

    mod = _mod_with_diffs(tmp_path, 0)
    ref = tmp_path / "reference"
    ref.mkdir()
    monkeypatch.setattr(_check, "validate", lambda *a, **k: rep)
    rc = _cli.main([str(mod), "--reference", str(ref), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["error_count"] == 0


# --------------------------------------------------------------------------- CS5 / CS7
def _mod_supplied_not_game(vpath, config):
    """A tree some MOD supplies but the GAME does not: the inert bare-path case."""
    return _merge.MergeResult(tree=etree.fromstring("<root/>"), sources=["owner:full"],
                              base_found=True, base_from_game=False)


def test_inert_bare_path_diff_is_found_but_not_counted_as_checked(tmp_path, monkeypatch):
    """CS5 (counted as checked) and CS7 (the note stops naming the unevaluated files):
    VA-11a -- an inert bare-path diff is FOUND, its ops are NOT evaluated, and the
    denominator line must say so."""
    monkeypatch.setattr(_merge, "build_effective", _mod_supplied_not_game)
    report = _check.Report()
    _check.check_sel_resolution(_mod_with_diffs(tmp_path, 1), _config(tmp_path), report)
    note = [n for n in report.notes if n.startswith("sel-resolution:")]
    assert len(note) == 1
    assert "0 diff file(s) checked" in note[0]
    assert "1 more diff file(s) found whose ops were NOT evaluated" in note[0]
    assert [f.severity for f in report.findings if f.category == "path"] == ["error"]


# --------------------------------------------------------------------------- CS1
def test_one_dropped_overlay_is_one_skip_line_across_many_diff_files(tmp_path, monkeypatch):
    """CS1: the same unparseable overlay reaches several diff files' merges; one cause
    must read as ONE degraded skip, not one per file."""
    def merged(vpath, config):
        return _merge.MergeResult(tree=etree.fromstring("<root/>"), sources=[],
                                  base_found=True, base_from_game=True,
                                  skipped=["ov_broken/libraries/x.xml: malformed XML"])
    monkeypatch.setattr(_merge, "build_effective", merged)
    report = _check.Report()
    _check.check_sel_resolution(_mod_with_diffs(tmp_path, 3), _config(tmp_path), report)
    assert len(report.skipped) == 1
    assert report.skipped[0].degraded

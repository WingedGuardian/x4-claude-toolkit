"""Mutation-campaign gaps in `gates/load_order_oracle.py` and `gates/_env.py`
(campaign 2, 2026-09-26). Each test names the surviving mutant it was written to kill
and was verified to FAIL with it applied and PASS without it."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gates"))
import _env  # noqa: E402
import load_order_oracle as g  # noqa: E402

BS = "\\"


def _line(folder: str, rel: str) -> str:
    return ("[FileIO ] 0.00 File I/O: Failed to verify the file signature for file "
            f"'.{BS}extensions{BS}{folder}{BS}{rel.replace('/', BS)}' (error: 14)\n")


# --------------------------------------------------------------------------- score
def test_score_matches_mixed_case_folders_against_the_lowercased_log():
    """LO1: the log is lowercased by parse_sequences; the computed order keeps the
    folder's real casing. Comparing them case-sensitively drops 'Alpha' as unknown
    and the class stops being comparable."""
    s = g.score(["Alpha", "beta"], {"x.xml": ["alpha", "beta"]})
    assert (s.classes, s.pairs, s.inversions) == (1, 1, 0)
    assert s.unknown_folders == set()


def test_score_sums_inversions_across_every_class():
    """LO5: inversions are a TOTAL over classes, not the last class's count."""
    s = g.score(["b", "a", "e", "d", "c"],
                {"one.xml": ["a", "b"], "two.xml": ["c", "d", "e"]})
    assert s.inversions == 1 + 3
    assert len(s.bad) == 2


# --------------------------------------------------------------------------- main
def _setup(tmp_path, monkeypatch, folders, log_lines, log_older_than_manifests):
    mods = []
    for f in folders:
        d = tmp_path / "ext" / f
        d.mkdir(parents=True)
        (d / "content.xml").write_text(f'<content id="{f}" version="1"/>', encoding="utf-8")
        mods.append({"folder": f, "path": str(d)})
    log = tmp_path / "debug.txt"
    log.write_text("".join(log_lines), encoding="utf-8")
    t_manifest = os.stat(mods[0]["path"] + "/content.xml").st_mtime
    t_log = t_manifest - 1000 if log_older_than_manifests else t_manifest + 1000
    os.utime(log, (t_log, t_log))
    monkeypatch.setattr(g, "_log_path", lambda: log)
    monkeypatch.setattr(g._registry, "mods", lambda scope, *a, **k: list(mods))
    return mods


def test_main_refuses_when_no_class_is_comparable(tmp_path, monkeypatch):
    """LO8: zero comparable classes (every class shipped by one mod) is rc 2, never a
    PASS -- 0 inverted of 0 compared is a non-answer."""
    _setup(tmp_path, monkeypatch, ["a", "b"],
           [_line("a", "one.xml"), _line("b", "two.xml")], log_older_than_manifests=False)
    assert g.main() == 2


def test_main_convicts_on_a_fresh_log(tmp_path, monkeypatch):
    """Control for the stale-log test below: the same inversion, with a log NEWER than
    every manifest and no unknown folders, is a real FAIL (rc 1)."""
    _setup(tmp_path, monkeypatch, ["a", "b"],
           [_line("b", "x.xml"), _line("a", "x.xml")], log_older_than_manifests=False)
    assert g.main() == 1


def test_main_refuses_to_convict_on_a_log_older_than_a_manifest(tmp_path, monkeypatch):
    """LO9: an inversion judged against a log that predates a manifest may be the log's
    age, not the code -- rc 2 (CANNOT JUDGE), never rc 1."""
    _setup(tmp_path, monkeypatch, ["a", "b"],
           [_line("b", "x.xml"), _line("a", "x.xml")], log_older_than_manifests=True)
    assert g.main() == 2


def test_main_refuses_to_convict_when_the_log_names_an_inactive_folder(tmp_path, monkeypatch):
    """LO9 (second signal): a logged folder that is not active now means the log
    describes a different modlist -- rc 2 even though the log is newer."""
    _setup(tmp_path, monkeypatch, ["a", "b"],
           [_line("b", "x.xml"), _line("a", "x.xml"), _line("ghost", "x.xml")],
           log_older_than_manifests=False)
    assert g.main() == 2


# --------------------------------------------------------------------------- _env
def test_stale_store_refusal_refuses_a_store_that_cannot_be_opened(tmp_path):
    """GE2: an effective store that sqlite cannot open is rc 2 (CANNOT), never None
    (which every caller reads as 'fresh, go ahead')."""
    assert _env.stale_store_refusal(tmp_path / "no-such.db", "test") == 2

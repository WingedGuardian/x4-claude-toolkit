"""`gates/qa_sweep.py` feeds "the newest groundtruth fixture" to its oracle and mappings cells.

It found that file with the glob `groundtruth-*.tsv`, which also matches a file that is not a
fixture. MEASURED 2026-09-14: a macro LIST saved beside the fixtures as
`groundtruth-macros-discriminating-20260914.tsv` sorted after every real fixture ("m" > "2"),
the sweep handed it to `x4live mappings`, and that cell went RED -- rc 3, all 55 lines
unparseable -- over a gate run whose tools were fine. `x4live groundtruth` only ever writes
`groundtruth-YYYYMMDD-HHMMSS.tsv`, so only that name is a fixture.
"""
from __future__ import annotations


def _sweep(monkeypatch, tmp_path):
    from conftest import import_gate
    qa_sweep = import_gate("qa_sweep", module_level=False)
    monkeypatch.setattr(qa_sweep._env, "mods_dir", lambda: tmp_path)
    (tmp_path / "_reports").mkdir()
    return qa_sweep


def _touch(tmp_path, name):
    (tmp_path / "_reports" / name).write_text("x", encoding="utf-8")


def test_a_LOOKALIKE_file_is_not_taken_for_the_newest_fixture(tmp_path, monkeypatch):
    qa_sweep = _sweep(monkeypatch, tmp_path)
    for name in ("groundtruth-20260831-122748.tsv", "groundtruth-20260913-115336.tsv",
                 "groundtruth-macros-discriminating-20260914.tsv"):
        _touch(tmp_path, name)
    assert qa_sweep._newest_groundtruth().endswith("groundtruth-20260913-115336.tsv")


def test_ONLY_a_lookalike_present_means_NO_fixture(tmp_path, monkeypatch):
    """The twin: with no real fixture, the cell must run against the missing-fixture path and
    answer rc 2 -- not against whatever else happens to share the prefix."""
    qa_sweep = _sweep(monkeypatch, tmp_path)
    _touch(tmp_path, "groundtruth-macros-discriminating-20260914.tsv")
    assert qa_sweep._newest_groundtruth().endswith("__no_groundtruth_fixture__.tsv")


def test_the_newest_REAL_fixture_still_wins(tmp_path, monkeypatch):
    """The control: the filter must not stop the newest timestamped fixture being chosen."""
    qa_sweep = _sweep(monkeypatch, tmp_path)
    for name in ("groundtruth-20260829-175342.tsv", "groundtruth-20260913-115336.tsv"):
        _touch(tmp_path, name)
    assert qa_sweep._newest_groundtruth().endswith("groundtruth-20260913-115336.tsv")

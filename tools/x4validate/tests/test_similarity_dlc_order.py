"""x4similar orders DLC by the ENGINE's folder key, not a plain sort (final review item 4).

`_merge.Config.dlc_dirs()` orders DLC by `_loadorder.sort_key` (case-insensitive,
compared in UPPERCASE, so `_` sorts AFTER the letters). `_similarity._collect_all`
re-sorted whatever it was given by plain `p.name`, where `_` sorts BEFORE lowercase
letters -- a second ordering rule beside the load order. The two disagree on
`ego_dlc_a_b` vs `ego_dlc_ab`, which is the pair used here.
"""
from __future__ import annotations

from pathlib import Path

from x4validate import _loadorder, _similarity


def test_collect_all_orders_dlc_by_the_engine_folder_key(tmp_path, monkeypatch):
    ref = tmp_path / "reference"
    ref.mkdir()
    a_b = tmp_path / "ego_dlc_a_b"
    ab = tmp_path / "ego_dlc_ab"
    a_b.mkdir()
    ab.mkdir()
    assert sorted(["ego_dlc_a_b", "ego_dlc_ab"]) != sorted(
        ["ego_dlc_a_b", "ego_dlc_ab"], key=_loadorder.sort_key), "fixture lost its point"
    seen: list[tuple] = []
    real = _similarity._FixedDlcConfig

    def spy(*a, **k):
        seen.append(tuple(p.name for p in k.get("fixed_dlc", ())))
        return real(*a, **k)
    monkeypatch.setattr(_similarity, "_FixedDlcConfig", spy)
    _similarity._collect_all(ref, tmp_path / "no_ext", dlc_dirs=[a_b, ab])
    assert seen == [("ego_dlc_ab", "ego_dlc_a_b")], seen

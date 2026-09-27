"""`Config.dlc_dirs` orders DLC by the ENGINE's folder key on EVERY return path.

v3.3.0 release review (lane roots), finding 9. The full path sorted with
`_loadorder.sort_key` (AUDIT-2026-09-24 LO-6), but the two early returns -- an ad-hoc
--reference, and include_packed_dlc=False -- used a plain `sorted()`, whose order puts
`_` (0x5F) BEFORE the letters. The engine's key compares in UPPERCASE, where `_` sorts
AFTER them. Names chosen so the two orders DISAGREE: `ego_dlc_x_z` vs `ego_dlc_xa`.
"""
from __future__ import annotations

from pathlib import Path

from x4validate import _loadorder, _merge

NAMES = ("ego_dlc_x_z", "ego_dlc_xa")


def _ref(tmp_path: Path) -> Path:
    ref = tmp_path / "ref"
    for n in NAMES:
        (ref / "extensions" / n).mkdir(parents=True)
    return ref


def _engine_order() -> list[str]:
    return sorted(NAMES, key=_loadorder.sort_key)


def test_the_fixture_can_tell_the_two_orders_apart():
    assert sorted(NAMES) != _engine_order()


def test_include_packed_dlc_False_uses_the_engine_key(tmp_path):
    cfg = _merge.Config(reference=_ref(tmp_path), include_packed_dlc=False)
    assert [p.name for p in cfg.dlc_dirs()] == _engine_order()


def test_an_ad_hoc_reference_uses_the_engine_key(tmp_path):
    # not the configured workspace reference -> the early return that skips packed DLC
    cfg = _merge.Config(reference=_ref(tmp_path))
    assert not _merge.is_configured_reference(cfg.reference)
    assert [p.name for p in cfg.dlc_dirs()] == _engine_order()

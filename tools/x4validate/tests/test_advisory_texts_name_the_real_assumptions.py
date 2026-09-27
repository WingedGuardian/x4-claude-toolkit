"""The advisory lines must name what is ACTUALLY assumed -- not what has been measured.

v3.3.0 release review (lane roots), finding 4. x4effective's advisory said "cycles and
missing dependencies are assumptions" and x4compat's SUBTREE row said "apply order
inferred". Both were measured on 2026-09-26 (the load-order probe: a cycle or a
missing REQUIRED dependency means the mod does not load; profile-root mods apply after
every game-root mod). What stays UNMEASURED is the Steam Workshop root, dependency ids
that differ only in case, and a game-root mod that waits a pass while profile-root mods
are present -- and those are what the lines must name.
"""
from __future__ import annotations

from pathlib import Path

from x4validate import _compat, _effective, _merge

STALE = ("cycles and missing dependencies are assumptions", "apply order inferred")
REAL = ("Workshop", "case", "pass")


def test_x4effective_advisory_names_the_unmeasured_parts():
    text = _effective._ADVISORY
    assert not any(s in text for s in STALE), text
    assert all(r in text for r in REAL), text


def _subtree_detail(tmp_path: Path) -> str:
    ref = tmp_path / "ref"
    (ref / "libraries").mkdir(parents=True)
    (ref / "libraries" / "x.xml").write_text(
        "<r><a><b v='1'/></a></r>", encoding="utf-8")
    ext = tmp_path / "ext"
    for folder, body in (
            ("a_first", "<diff><replace sel=\"/r/a/b/@v\">2</replace></diff>"),
            ("b_later", "<diff><replace sel=\"/r/a\"><a/></replace></diff>")):
        d = ext / folder
        (d / "libraries").mkdir(parents=True)
        (d / "content.xml").write_text(
            f'<content id="{folder}" version="1" name="{folder}"/>', encoding="utf-8")
        (d / "libraries" / "x.xml").write_text(body, encoding="utf-8")
    cfg = _merge.Config(reference=ref, include_packed_dlc=False)
    found = _compat._analyze_vpath(
        "libraries/x.xml", ["a_first", "b_later"],
        {"a_first": ext / "a_first", "b_later": ext / "b_later"},
        {"a_first": 0, "b_later": 1}, cfg)
    rows = found[0] if isinstance(found, tuple) else found
    sub = [c for c in rows if getattr(c, "kind", "") == "SUBTREE"]
    assert sub, rows
    return sub[0].detail


def test_x4compat_subtree_row_does_not_call_the_measured_order_inferred(tmp_path):
    detail = _subtree_detail(tmp_path)
    assert not any(s in detail for s in STALE), detail

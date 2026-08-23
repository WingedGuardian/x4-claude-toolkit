"""CLAIMS.tsv row parsing and the tier contract.

Background: the gate checked every claim against the effective store, so
DESIGN-THREADS.md's *vanilla* column -- which is CORRECT -- reported 3 FAILs.
The doc was right and the gate was asking the wrong tier (CLAUDE.md gotcha #14).

These pin the parsing rules. The end-to-end tier evaluation is exercised by
`gates/claims_audit.py` against the real store.
"""

import sys
from pathlib import Path

import pytest

GATES = Path(__file__).resolve().parent.parent / "gates"
from conftest import import_gate  # noqa: E402

from x4validate import _paths  # noqa: E402

# Module-scope import of a gate exits the whole pytest session on a machine
# with no X4 install -- see tests/conftest.py. Skip, do not abort.
claims_audit = import_gate("claims_audit")


def _rows(tmp_path, text: str, monkeypatch):
    f = tmp_path / "CLAIMS.tsv"
    f.write_text(text, encoding="utf-8")
    # Patch the FUNCTION. It used to patch a module constant, which stopped
    # working the moment resolution became lazy -- monkeypatch saves the old
    # value with getattr() first, and that itself refused on an unconfigured
    # machine, so the fixture seam blew up before it was installed.
    monkeypatch.setattr(claims_audit, "_claims", lambda: f)
    return list(claims_audit.rows())


def test_a_well_formed_tiered_row_parses(tmp_path, monkeypatch):
    r = _rows(tmp_path, "macro\tm\tp\t1.5\t0.1\tsrc\tvanilla\n", monkeypatch)
    assert len(r) == 1
    n, kind, entity, prop, expected, tol, source, tier, err = r[0]
    assert (kind, entity, prop, expected, tol, tier, err) == (
        "macro", "m", "p", "1.5", 0.1, "vanilla", None)


@pytest.mark.parametrize("tier", ["vanilla", "effective"])
def test_both_tiers_are_accepted(tmp_path, monkeypatch, tier):
    r = _rows(tmp_path, f"macro\tm\tp\t1\t0\tsrc\t{tier}\n", monkeypatch)
    assert r[0][-1] is None and r[0][7] == tier


def test_a_MISSING_tier_is_an_error_not_a_default(tmp_path, monkeypatch):
    """The old 6-field format must NOT silently mean 'effective'.

    Defaulting is exactly how a vanilla claim got checked against a VRO store.
    """
    r = _rows(tmp_path, "macro\tm\tp\t1\t0\tsrc\n", monkeypatch)
    assert r[0][-1] is not None, "an untiered row must carry an error"
    assert "7 tab-separated" in r[0][-1]


def test_an_unknown_tier_is_rejected_by_name(tmp_path, monkeypatch):
    r = _rows(tmp_path, "macro\tm\tp\t1\t0\tsrc\tlive\n", monkeypatch)
    assert "tier must be one of" in r[0][-1]


def test_a_bad_tolerance_is_reported_not_crashed(tmp_path, monkeypatch):
    r = _rows(tmp_path, "macro\tm\tp\t1\tzero\tsrc\tvanilla\n", monkeypatch)
    assert "not numeric" in r[0][-1]


def test_malformed_rows_are_YIELDED_so_they_count_as_unresolved(tmp_path, monkeypatch):
    """A malformed row must reach the caller. Dropping it here would hide work
    not done -- the founding defect of the skipped-channel contract."""
    r = _rows(tmp_path, "macro\tm\tp\t1\t0\tsrc\n"          # no tier
                        "macro\tm2\tp\t2\t0\tsrc\teffective\n", monkeypatch)
    assert len(r) == 2, "the malformed row must not vanish"
    assert r[0][-1] and r[1][-1] is None


def test_comments_and_blank_lines_are_ignored(tmp_path, monkeypatch):
    r = _rows(tmp_path, "# a comment\n\n   \nmacro\tm\tp\t1\t0\tsrc\tvanilla\n", monkeypatch)
    assert len(r) == 1


def test_the_real_claims_file_is_fully_tiered():
    """Guards the shipped registry: every row carries a valid tier."""
    try:
        real = claims_audit._claims()
    except _paths.Unconfigured:
        pytest.skip("no registry configured, so there is no CLAIMS.tsv to guard")
    if not real.is_file():
        pytest.skip("no CLAIMS.tsv on this machine")
    bad = []
    for i, line in enumerate(real.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7 or parts[6].strip() not in claims_audit.TIERS:
            bad.append(i)
    assert not bad, f"rows missing a valid tier: {bad}"

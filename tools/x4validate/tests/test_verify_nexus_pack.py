"""scripts/verify-nexus-pack.py must REPORT, never crash, and its usage line must be one.

Release review 2026-09-26: a changelog of only blank lines passed the size check and then
raised ValueError from `max()` over an empty list -- a traceback where a FAIL row belongs,
from the one script whose whole job is to refuse cleanly. And a wrong argument count
printed a BLANK line as its usage message, because the docstring's third-from-last line
is the blank one above "Usage:".
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "verify-nexus-pack.py"


def _mod():
    spec = importlib.util.spec_from_file_location("verify_nexus_pack", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pack(tmp_path: Path, changelog: bytes) -> Path:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "NEXUS-DESCRIPTION-v9.txt").write_bytes(b"A description.\n")
    (pack / "NEXUS-CHANGELOG-v9.txt").write_bytes(changelog)
    (pack / "toolkit-v9.zip").write_bytes(b"PK-not-really")
    return pack


def test_a_changelog_of_only_BLANK_lines_FAILS_cleanly(tmp_path, capsys):
    rc = _mod().main([str(_pack(tmp_path, b"\n\n   \n"))])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "FAIL  non-empty" in out, out


def test_TWIN_a_well_formed_pack_PASSES(tmp_path, capsys):
    """Without this the test above passes for a script that fails everything."""
    rc = _mod().main([str(_pack(tmp_path, b"Fixed one thing\nAdded another thing\n"))])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "longest 19" in out, out


@pytest.mark.parametrize("argv", [[], ["a", "b"]])
def test_the_usage_message_IS_the_usage_line(argv, capsys):
    rc = _mod().main(argv)
    err = capsys.readouterr().err.strip()
    assert rc == 2
    assert err.startswith("Usage:"), repr(err)
    assert "verify-nexus-pack.py" in err, repr(err)

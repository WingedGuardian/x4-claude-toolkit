"""AUDIT-2026-09-24 AN-11: an empty name is refused, never certified as a negative."""
import pytest

from x4validate import _xref


@pytest.mark.parametrize("cmd", ["who-calls", "who-listens", "cue"])
@pytest.mark.parametrize("name", ["", "   "])
def test_an_empty_name_is_refused_before_any_search(cmd, name, capsys, tmp_path):
    # --tsv points at nothing: the refusal must come BEFORE the index is even opened,
    # so this also proves no search ran.
    rc = _xref.main([cmd, name, "--tsv", str(tmp_path / "absent.tsv")])
    assert rc == 2
    assert "empty name" in capsys.readouterr().err

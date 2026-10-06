"""Both config loaders refuse a line carrying NON-ASCII whitespace, the same way (FX-G2 item 8).

v4.0.0 delta review, MEASURED by reviewer A's fuzzer: `X4_K0<NBSP>=v` -- a non-breaking space
before the `=` -- was a configuration to the Python loader (`\\s` and str.isspace() are Unicode)
and a refused line to the bash one (`[:space:]` is ASCII in the C locale, and locale-dependent
otherwise). A split tree: the guards and the tools read different roots from one file, with
nothing saying so. Python's whitespace beyond ASCII is \\x1c-\\x1f, U+0085, U+00A0, U+1680,
U+2000-U+200A, U+2028, U+2029, U+202F, U+205F, U+3000; a line holding any of them (that is not
a comment) is now refused as `shape` and REPORTED by both, and configures nothing.

Kept in its own file so it reuses the grammar harness of test_config_precedence_agrees.py
without editing it.
"""
from __future__ import annotations

import pytest

from test_config_precedence_agrees import PARSE_KEYS, _bash_parse, _parse_box, _py_parse

ODD = ["\x1c", "\x1f", "\x85", "\xa0", " ", " ", " ", " ", " ",
       " ", " ", " ", "　"]


def _both(tmp_path, lines):
    tk, env = _parse_box(tmp_path, lines)
    bvals, _bexp, bign, _path = _bash_parse(tk, env)
    pvals, pign = _py_parse(tk, env)
    return bvals, {k: v for k, v in pvals.items() if k in PARSE_KEYS}, bign, pign


@pytest.mark.parametrize("sp", ODD, ids=[f"U+{ord(c):04X}" for c in ODD])
@pytest.mark.parametrize("where", ["before_eq", "after_eq", "indent", "in_value", "after_export"])
def test_a_line_with_non_ascii_whitespace_is_refused_by_BOTH(tmp_path, sp, where):
    line = {"before_eq": f"X4_GAME{sp}=/g", "after_eq": f"X4_GAME={sp}/g",
            "indent": f"{sp}X4_GAME=/g", "in_value": f"X4_GAME=/a{sp}b",
            "after_export": f"export{sp}X4_GAME=/g"}[where]
    bvals, pvals, bign, pign = _both(tmp_path, [line, "X4_MODS=/m"])
    assert bvals == pvals == {"X4_MODS": "/m"}, (bvals, pvals)
    assert bign == pign == [(1, "shape")], (bign, pign)


def test_TWIN_ascii_whitespace_is_still_a_configuration(tmp_path):
    """Clause: the space is NON-ASCII. Tabs and blanks around `=` keep working in both."""
    bvals, pvals, bign, pign = _both(tmp_path, ["\tX4_GAME =\t/g", "export X4_MODS = /m"])
    assert bvals == pvals == {"X4_GAME": "/g", "X4_MODS": "/m"}, (bvals, pvals)
    assert bign == pign == []


def test_TWIN_a_comment_or_blank_line_is_not_reported(tmp_path):
    """Clause: the line is not a comment. A comment may say anything."""
    bvals, pvals, bign, pign = _both(tmp_path, ["# a note\xa0with a no-break space", "", "X4_GAME=/g"])
    assert bvals == pvals == {"X4_GAME": "/g"}
    assert bign == pign == []

"""The recovery an installer prints must be a command that works.

Both installers refuse when x4lock has locked a file they would write, and both then
printed:

    python scripts/x4lock.py unlock

That form exits 2 -- "unlock needs a path, or --all. One file at a time is the point:
that is the moment a human decides." So the remedy offered to a user who has just been
refused fails immediately, at the exact moment they are least able to tell a broken
instruction from a broken tool.

Grounded in the REAL exit code rather than a style rule: the first test runs the bare
form and requires it to fail, so if x4lock ever grows a sensible default this pin
retires itself instead of ossifying.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "scripts" / "x4lock.py"


def test_the_bare_unlock_form_really_does_fail():
    """The premise. If this ever passes, the pin below is obsolete and should go."""
    if not LOCK.is_file():
        pytest.skip("x4lock.py not in this tree")
    p = subprocess.run([sys.executable, str(LOCK), "unlock"],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode != 0, (
        "bare `unlock` now succeeds -- delete this file's sibling test, it pins "
        "nothing any more")


@pytest.mark.parametrize("script", ["install.sh", "install.ps1"])
def test_no_installer_offers_a_recovery_that_exits_nonzero(script):
    """Every `x4lock.py unlock` an installer PRINTS must carry a path or --all."""
    p = ROOT / script
    if not p.is_file():
        pytest.skip(f"{script} not in this tree")
    bad = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if "x4lock.py unlock" not in line:
            continue
        tail = line.split("x4lock.py unlock", 1)[1]
        # strip the shell/PowerShell quoting and redirection that ends the echo
        tail = re.sub(r"""["']\s*(>&2)?\s*$""", "", tail).strip()
        if not tail:
            bad.append(f"{script}:{i}")
    assert not bad, (
        "these print a bare `unlock`, which exits 2, as the documented recovery from "
        "a refused install: " + ", ".join(bad))

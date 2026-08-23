r"""Every shipped CLI must be exercised by the QA sweep.

`gates/qa_sweep.py` is the "every CLI x subcommand" gate, and its cell list is
hand-written. A hand-written list of things to check has exactly one failure
mode, and it is this register's only failure mode: a new entry point is added,
nobody remembers the list, and the gate keeps reporting success over a smaller
population than it claims to cover.

That is not hypothetical here — `x4debug` shipped as the 9th console script on
2026-08-13 and qa_sweep could not see it, which is the third occurrence of this
shape in one day (the first two were inside the tool `x4debug` itself).

So the list is checked against `pyproject.toml`'s `[project.scripts]` rather than
against memory. Adding a CLI without a cell now fails here instead of silently
shrinking what the gate measures.
"""

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _declared_clis() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return set(data["project"]["scripts"])


def test_every_console_script_has_at_least_one_qa_cell():
    from gates import qa_sweep

    covered = {c.tool for c in qa_sweep.CELLS}
    missing = _declared_clis() - covered
    assert not missing, (
        f"these CLIs ship but qa_sweep never runs them: {sorted(missing)}. "
        "The gate would report success over a population smaller than it claims.")


def test_no_qa_cell_names_a_cli_that_does_not_exist():
    """The mirror: a renamed CLI must not leave a cell silently testing nothing."""
    from gates import qa_sweep

    stale = {c.tool for c in qa_sweep.CELLS} - _declared_clis()
    assert not stale, f"qa_sweep has cells for CLIs that are not shipped: {sorted(stale)}"


def test_no_cli_module_declares_its_own_version():
    """One version, one source of truth.

    Every CLI reports `--version`. If a module defines its own `__version__`
    instead of importing the package's, the toolkit ships two answers to "what
    version is this?" — and the one the user sees depends on which command they
    happened to run. `x4debug` shipped saying 2.3.0 while the other eight said
    2.2.1, from the same working tree.

    Same shape as every other finding in the register: a second implementation of
    a fact that already had one.
    """
    import re

    pkg = ROOT / "x4validate"
    offenders = []
    for mod in sorted(pkg.glob("*.py")):
        if mod.name == "__init__.py":
            continue
        src = mod.read_text(encoding="utf-8")
        if re.search(r"^__version__\s*=\s*[\"']", src, re.M):
            offenders.append(mod.name)
    assert not offenders, (
        f"these modules declare their own __version__ instead of importing the "
        f"package's: {offenders}")

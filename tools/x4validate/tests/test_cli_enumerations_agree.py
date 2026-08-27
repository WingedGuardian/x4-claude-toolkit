"""Every hand-maintained list of "the CLIs" must agree with `[project.scripts]`.

THE CLASS, NOT THE INSTANCE. `[project.scripts]` is the source of truth, and on
2026-08-26 FOUR consumers enumerated it independently. Adding a tenth CLI found
three of them wrong or stale at once:

  - `tests/test_unconfigured_refusal.py` asserted `len(entries) >= 9` -- it caught a
    VANISHING entry point and silently accepted a new one, so adding a CLI passed a
    guard written to notice exactly that.
  - `scripts/verify-cold.sh` printed "all 8 configuration-dependent CLIs" as a
    LITERAL. Correct when written, stale the moment a CLI was added -- and the count
    is the sentence a reader trusts.
  - `gates/edge_sweep.py::TOOLS` listed 9 of 10 (it was missing `x4debug`), so the
    hostile-input sweep covered a subset AND REPORTED SUCCESS. That is this
    workspace's founding defect shape, sitting inside a gate.

Each was fixed individually first. That is the instance, and it drifts again on the
next CLI. This test is the class: it fails the moment any enumerator disagrees.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def declared_clis() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return set(data["project"]["scripts"])


def test_the_source_of_truth_is_not_empty():
    """Guard the guard: an empty set would make every assertion below vacuous."""
    assert len(declared_clis()) >= 9, "pyproject declares almost no CLIs — did parsing break?"


def test_edge_sweep_TOOLS_covers_every_declared_cli():
    from gates import edge_sweep

    missing = declared_clis() - set(edge_sweep.TOOLS)
    assert not missing, (
        f"gates/edge_sweep.py::TOOLS does not exercise {sorted(missing)}. A sweep that "
        "covers a subset and prints success is the exact shape BLIND-SPOTS exists for.")


def test_edge_sweep_TOOLS_names_nothing_that_does_not_ship():
    from gates import edge_sweep

    extra = set(edge_sweep.TOOLS) - declared_clis()
    assert not extra, f"edge_sweep names {sorted(extra)}, which pyproject does not ship"


def test_verify_cold_matrix_covers_every_declared_cli():
    """The cold matrix is shell, so read it as text -- but read the CASES, not the prose."""
    src = (ROOT / "scripts" / "verify-cold.sh").read_text(encoding="utf-8")
    exercised = set(re.findall(r"(?m)^cli_case\s+_(\w+)", src))
    # the matrix names MODULES; map them back through pyproject's targets
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    modules = {t.split(":")[0].split(".")[-1].lstrip("_"): n
               for n, t in data["project"]["scripts"].items()}
    covered = {modules[m] for m in exercised if m in modules}
    #: x4diff is deliberately excluded -- it needs no configuration, and asserting
    #: exit 2 for it was a bug in the script itself (recorded in verify-cold.sh).
    missing = declared_clis() - covered - {"x4diff"}
    assert not missing, (
        f"scripts/verify-cold.sh never proves {sorted(missing)} refuses when unconfigured")


def test_verify_cold_does_not_hardcode_the_count():
    """The printed count must be DERIVED. It was a literal, and it went stale."""
    src = (ROOT / "scripts" / "verify-cold.sh").read_text(encoding="utf-8")
    assert not re.search(r"all \d+ configuration-dependent", src), (
        "the summary line hardcodes a number again — it drifts silently, which is "
        "how it was wrong before. Print the counter you incremented.")
    assert "DRIFT:" in src, "the matrix no longer reconciles itself against pyproject"


def test_unconfigured_refusal_pins_an_exact_count():
    """`>=` accepts a new CLI silently; the whole point is to notice one."""
    src = (ROOT / "tests" / "test_unconfigured_refusal.py").read_text(encoding="utf-8")
    assert "len(entries) >= " not in src, (
        "a `>=` bound catches a vanishing entry point but not an added one — that is "
        "the bug this file documents")
    m = re.search(r"len\(entries\) == (\d+)", src)
    assert m, "expected an exact-count assertion"
    assert int(m.group(1)) == len(declared_clis()), (
        f"pinned count {m.group(1)} != {len(declared_clis())} declared CLIs")


@pytest.mark.parametrize("consumer", ["edge_sweep", "verify-cold", "unconfigured_refusal"])
def test_every_consumer_is_actually_reachable(consumer):
    """A test that silently skips its subject proves nothing (the whole register's theme)."""
    if consumer == "edge_sweep":
        from gates import edge_sweep
        assert edge_sweep.TOOLS, "TOOLS is empty — the assertions above would be vacuous"
    elif consumer == "verify-cold":
        assert (ROOT / "scripts" / "verify-cold.sh").exists()
    else:
        assert (ROOT / "tests" / "test_unconfigured_refusal.py").exists()

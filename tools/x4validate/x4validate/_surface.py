"""The toolkit's own CLI surface: which programs exist, and what each can be asked.

ASKED OF THE PROGRAMS, NEVER PARSED OUT OF THEIR SOURCE. A static scan for
`add_parser("...")` misses any subcommand whose name is not a string literal at
that call site. MEASURED 2026-09-12 across the 11 CLIs: an AST scan finds 39 of
the 43 real subcommands -- it misses `x4xref who-calls`/`who-listens`, built in a
loop so the name is a variable, and `x4modlist changed`/`snapshot`. An inventory
of capabilities that is itself missing capabilities is the F58 shape, so the
surface comes from `--help` plus argparse's own invalid-choice listing, and the
roster from pyproject's `[project.scripts]` rather than a hand-kept tuple.

WHY THIS IS LIBRARY CODE AND NOT PART OF THE GATE THAT NEEDS IT. The enumeration
was written inside `gates/toolkit_usage.py`, which is DEV-ONLY and absent from
this tree, so a gate here cannot import it. Moving it verbatim would have carried
`_env.skip()` -- which `raise SystemExit(2)`s -- into the shipped package. Gotcha
#26 records the cost: `gates/` modules resolved paths at import, and a SystemExit
during pytest collection is an INTERNALERROR that aborts the whole session on a
fresh clone while being invisible on a configured machine.

**So the split is: this module RAISES, and the caller decides the exit code.**
A gate catches `SurfaceUnavailable` and translates it to its own rc 2.

⚠ Dev's `gates/toolkit_usage.py` keeps its own copy of these functions. That is
duplication across a deliberate tree boundary (dev owns 22 files by policy), not
an oversight -- the two trees cannot import from each other.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

#: This package's repo root -- `<root>/x4validate/_surface.py` -> `<root>`.
ROOT = Path(__file__).resolve().parent.parent


class SurfaceUnavailable(Exception):
    """The surface could not be determined, so no answer about it is admissible.

    Deliberately NOT a SystemExit subclass: one would satisfy a `pytest.raises`
    check while still aborting collection, which is the defect this module exists
    to avoid.
    """

    def __init__(self, what: str, how: str = "") -> None:
        super().__init__(f"{what}\n      {how}" if how else what)
        self.what = what
        self.how = how


def cli_roster(root: Path | None = None) -> list[str]:
    """Every console script the package installs, read from pyproject itself.

    Raises SurfaceUnavailable rather than returning an empty list: a roster of
    zero would make every coverage check over it vacuously true.
    """
    base = Path(root) if root is not None else ROOT
    pj = base / "pyproject.toml"
    if not pj.is_file():
        raise SurfaceUnavailable(
            f"no pyproject.toml at {pj}",
            "the CLI roster is read from [project.scripts]; without it the "
            "surface would be a hand-kept guess")
    data = tomllib.loads(pj.read_text(encoding="utf-8"))
    scripts = sorted((data.get("project") or {}).get("scripts") or {})
    if not scripts:
        raise SurfaceUnavailable(
            f"[project.scripts] is empty in {pj}",
            "nothing to enumerate; refusing rather than reporting a clean zero")
    return scripts


def _run(argv: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=180,
                           cwd=str(cwd or ROOT))
    except (subprocess.TimeoutExpired, OSError) as exc:
        return -1, f"{type(exc).__name__}: {exc}"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


_CHOOSE = re.compile(r"choose from\s+(.*?)\)", re.S)
_SUBS_IN_HELP = re.compile(r"^\s*\{[^}]+\}", re.M)


def subcommands(cli: str, cwd: Path | None = None) -> tuple[list[str] | None, str]:
    """(subcommands, note). None means the surface could NOT be enumerated.

    An empty list is a real answer -- a single-command CLI. None is a REFUSAL, and
    the caller must not fold it into "covers nothing".
    """
    rc, out = _run(["uv", "run", cli, "--help"], cwd)
    if rc < 0:
        # The subprocess never ran (uv absent, timeout, OSError). `out` holds the
        # error text, which is non-empty and has no {...} block -- so without this
        # check it would fall through to "single-command CLI", rendering a failure
        # as a real answer. MEASURED by the review that found it.
        return None, f"`{cli}` could not be run: {out.strip()}"
    if not out.strip():
        return None, f"`{cli} --help` produced no output (rc {rc})"
    if not _SUBS_IN_HELP.search(out):
        return [], "single-command CLI (no subparser block in --help)"
    # argparse's invalid-choice error carries the authoritative COMPLETE list;
    # --help truncates a long metavar with an ellipsis.
    _rc, err = _run(["uv", "run", cli, "__no_such_subcommand__"], cwd)
    m = _CHOOSE.search(err)
    if not m:
        return None, (f"`{cli}` advertises subcommands in --help but its "
                      "invalid-choice error did not list them")
    subs = [s.strip().strip("'\"") for s in m.group(1).split(",")]
    subs = [s for s in subs if s]
    return (subs, "") if subs else (None, f"`{cli}` listed an empty choice set")

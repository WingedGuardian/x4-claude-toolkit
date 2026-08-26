"""Is a mutating gate breaking this tree RIGHT NOW?

`gates/mutation_probe.py` edits `_merge.py`, `_registry.py` and `_compat.py` in
place while it runs, so during that window every tool built on them answers from
deliberately-broken code. The tree looks completely normal, because the mutated
file is a TRACKED file — that is gotcha #27's actual lesson, and it is how v2.5.0
once shipped with its ambiguous-`sel` guard silently disabled.

Telling the other person is not a control. The parallel session that verified the
first window from outside put it better than I did, and the sentence is theirs:

    "A control only one side can see is still an assurance."

It also has a use I did not design for and they found: the marker is not only
PROSPECTIVE ("should I read now?") but RETROSPECTIVE ("is the measurement I
already took admissible?"). Checking it before and after a command lets a result
be QUALIFIED rather than merely asserted.

TWO SEVERITIES, deliberately not the same response:

  READS  -> banner. A wrong answer can be re-taken once the window closes (a probe
            run is ~70s), and refusing outright would break an unrelated session's
            work for the sake of a value they can simply ask for again.
  WRITES -> refuse. A poisoned ARTIFACT outlives the window and is trusted by
            everything downstream afterwards, with nothing to say it was born
            during one. There are exactly two stamping sites and both call
            `refuse_if_mutating`.

Stdlib only, and it imports nothing from this package: a diagnostic that needs the
world to be healthy cannot diagnose an unhealthy world. (Same rule as
`tools/basex/preflight.py`.)
"""
from __future__ import annotations

from pathlib import Path

#: Written by gates/mutation_probe.py before its first mutation, removed after its
#: last restore. Kept as a bare name so both sides agree by construction; a test
#: pins this module's resolved path against the probe's own constant.
MARKER_NAME = ".mutation-probe-active"


class TreeMutating(RuntimeError):
    """A durable artifact was about to be written from a deliberately-broken tree."""


def marker_path() -> Path:
    """Resolve from the PACKAGE ROOT, never the current directory.

    ⚠ THE TRAP THIS EXISTS TO AVOID. The marker lives beside `gates/` and
    `x4validate/`, but the normal way these tools get used is from the game
    directory — nowhere near it. A CWD-relative lookup would find nothing and
    report all-clear from the one place it matters most, which is F46's
    `Path("")` fallback wearing new clothes: a confident, uniform, entirely
    false negative.
    """
    return Path(__file__).resolve().parent.parent / MARKER_NAME


def active() -> Path | None:
    """The marker file if a mutating gate is running (or died mid-run), else None."""
    p = marker_path()
    return p if p.is_file() else None


def banner() -> str:
    """A loud warning for stderr, or '' when the tree is trustworthy."""
    p = active()
    if p is None:
        return ""
    return (
        "!" * 78 + "\n"
        "!! A MUTATING GATE IS RUNNING (or died mid-run): the source tree is\n"
        "!! DELIBERATELY BROKEN right now, so this answer may be wrong.\n"
        f"!!   {p}\n"
        "!! The mutated file is a TRACKED file, so `git status` looks normal.\n"
        "!! Re-take this measurement once the marker is gone. If no probe is\n"
        "!! running, recover with:\n"
        "!!   uv run python gates/mutation_probe.py --recover\n"
        + "!" * 78
    )


def refuse_if_mutating(what: str) -> None:
    """Raise rather than persist *what* while the tree is mutated.

    Called at the STAMPING sites rather than at argument parsing, so no other
    entry path can slip past it — the durable damage happens where the bytes are
    written, not where the command line is read.
    """
    p = active()
    if p is None:
        return
    raise TreeMutating(
        f"refusing to {what}: a mutating gate is running and the source tree is "
        f"deliberately broken ({p}). An artifact written now would outlive the "
        f"window and be trusted afterwards with nothing to say it was born during "
        f"one. Wait for the marker to clear, or run "
        f"`gates/mutation_probe.py --recover` if no probe is running."
    )

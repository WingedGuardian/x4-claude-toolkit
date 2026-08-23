"""Shared test helpers.

`import_gate` exists because of a real CI failure on the v2.4.0 push: a gate
module imported at test-module scope KILLED THE WHOLE RUN on a machine with no X4
installed.

Every module under `gates/` resolves its paths at IMPORT time (`EXT = _env.extensions()`
and friends — MEASURED: 13 of them do), and `gates/_env.py::skip` reports a missing
install by `raise SystemExit(2)`. That is correct for a gate, which is a script.
But a `SystemExit` during pytest COLLECTION is an INTERNALERROR: pytest aborts the
entire session with exit 3 rather than failing one module. Three test files import
gate modules, so all three were affected; only the first showed up, because
collection stops at the first internal error.

It was invisible locally because unsetting `$X4_*` is NOT the same as having no
game installed — `_paths` still resolved through `.claude/x4-paths.env` and the
real install. Only a genuinely clean machine (CI) could surface it.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

GATES = Path(__file__).resolve().parent.parent / "gates"


def import_gate(name: str, *, module_level: bool = True):
    """Import a module from `gates/`, or SKIP.

    At module scope::

        cross_tool = import_gate("cross_tool")

    Inside a test, where only that test depends on the gate::

        qa_sweep = import_gate("qa_sweep", module_level=False)

    `module_level` must be False inside a function -- `allow_module_level=True` is
    only legal during collection. Importing inside the test body does NOT avoid the
    problem, it just moves it: the SystemExit becomes a test FAILURE instead of a
    collection abort, and a machine with no X4 install is not a broken toolkit.

    A skip, never a silent pass: pytest reports it distinctly, so "this machine has
    no X4 install" can never read as "the invariants hold".
    """
    if str(GATES) not in sys.path:
        sys.path.insert(0, str(GATES))
    try:
        return importlib.import_module(name)
    except (SystemExit, TypeError, OSError) as exc:
        # A gate can fail to import for TWO reasons on an unconfigured machine, and
        # only one of them is a SystemExit:
        #   gates/_env.py::skip          -> SystemExit(2)      (the documented path)
        #   Path(_paths.<thing>())       -> TypeError          (None is not a PathLike)
        # `gates/claims_audit.py` does the latter at module scope, and CI caught it
        # one push after the SystemExit case was fixed.
        #
        # The skip is CONDITIONED on the environment actually being unresolvable, not
        # on the exception type. A blanket catch would silently swallow a real
        # TypeError in a gate on a properly configured machine -- turning a defect
        # into a green skip, which is the exact inversion this suite exists to stop.
        if not _environment_is_unresolvable():
            raise
        reason = (f"gates/{name}.py needs a configured X4 install "
                  f"({type(exc).__name__} at import: {exc}). "
                  f"Set $X4_GAME / $X4_EXTENSIONS, or see .claude/x4-paths.env.")
        if module_level:
            pytest.skip(reason, allow_module_level=True)
        pytest.skip(reason)


def _environment_is_unresolvable() -> bool:
    """True when this machine has no usable X4 configuration.

    Deliberately checks the THREE things the gates actually need, rather than
    trusting any single one: a machine can have a reference tree but no registry,
    and the failure mode differs per gate.
    """
    try:
        from x4validate import _paths
    except ImportError:
        return True
    return (_paths.registry() is None
            or _paths.game_extensions() is None
            or _paths.reference() is None)

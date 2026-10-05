"""Which LAYOUT is this suite running in: the git checkout, or an INSTALLED toolkit?

R2-B1 (second install red-team, 2026-10-04): SETUP_PROMPT.txt tells the user the installed
toolkit's suite "should pass", and in an installed tree `uv run pytest -q` died in collection
(FileNotFoundError on agent/rules/codex-rules.yaml), because an install is runtime-only by
design: the `agent/` source the generator reads, the root `docs/`, and the git history are not
copied (README, "An installed toolkit is runtime-only").

A test that needs repo-only content calls `require_repo(...)`. It SKIPS -- counted, with a
reason naming what is absent -- only when BOTH hold:
  * the tree is an installed layout: no `agent/` directory at the toolkit root (every
    checkout and every release zip carries it; no installer copies it), and
  * the content the test needs is actually absent.
In a checkout a missing file is NOT skipped: the test then fails, as it should, because a
checkout that lost `agent/rules/codex-rules.yaml` is broken, not "installed".
"""
from __future__ import annotations

from pathlib import Path

import pytest

#: The toolkit root (tests/ -> x4validate/ -> tools/ -> root).
ROOT = Path(__file__).resolve().parents[3]

#: The reason prefix every such skip carries, so a reader of `-rs` can count them.
REASON = "REPO-ONLY (installed toolkit, not a checkout)"


def installed_layout(root: Path = ROOT) -> bool:
    """True for an installed toolkit: no `agent/` source directory at the root."""
    return not (Path(root) / "agent").is_dir()


def reference_unpacked() -> bool:
    """A reference tree is configured AND unpacked (it holds libraries/wares.xml).

    R2-B1: three markers asked only `_paths.reference() is None`. An install configures
    X4_REFERENCE before anything is unpacked -- SETUP_PROMPT has the suite run BEFORE the
    unpack step -- so on every fresh install those tests ran against a folder that did not
    exist yet, and failed. Configured is not unpacked."""
    from x4validate import _paths
    p = _paths.reference()
    return p is not None and (Path(p) / "libraries" / "wares.xml").is_file()


#: The reason every needs-a-reference skip carries.
NEEDS_REFERENCE = ("needs an UNPACKED reference tree (none configured, or not unpacked yet: "
                   "bash bin/unpack-reference.sh)")


def require_repo(*rel: str, why: str = "", module_level: bool = False, root: Path = ROOT) -> None:
    """Skip when this is an installed layout and any of `rel` (paths relative to the toolkit
    root, e.g. "agent/rules/codex-rules.yaml" or ".git") is absent; otherwise return.

    `module_level=True` for a call at import time (the whole module is counted as skipped)."""
    if not installed_layout(root):
        return
    missing = [r for r in rel if not (Path(root) / r).exists()]
    if not missing:
        return
    reason = "%s: needs %s, which an install does not ship%s" % (
        REASON, ", ".join(missing), (" -- " + why) if why else "")
    pytest.skip(reason, allow_module_level=module_level)

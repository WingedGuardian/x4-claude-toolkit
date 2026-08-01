r"""Shared input validation for every CLI entry point.

Why this module exists
----------------------
A tool battery over the whole suite (2026-07-27) found the same defect in four
separate tools: point them at a directory that does not exist and they return a
confident, reassuring, EXIT-0 clean bill of health.

    x4stats wares  <typo>   ->  "candidate introduces/changes no wares."
    x4similar      <typo>   ->  "no near-duplicate ships found at this threshold."
    x4compat check <typo>   ->  "0 hard-ish (HARD+FULL-OVERRIDE), 0 union-key"
    x4diff old <typo>       ->  "## removed files (present only in OLD):" (i.e.
                                 "the new version deleted everything")

Only x4validate checked. This is the same bug class as `Report.skipped` one level
up: **the tools could not distinguish "I examined this and found nothing" from
"there was nothing to examine."** A mistyped path read as good news, which is the
single most dangerous shape an answer can take.

An EMPTY-but-existing directory is the same trap wearing a different hat, so it
is reported too — as a warning, since an XML-less folder can be legitimate
(assets-only, or a mod mid-construction).
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import _cat


def mod_dir_problem(path: Path) -> str | None:
    """Why *path* is not a usable mod directory, or None if it is fine."""
    if not path.exists():
        return "does not exist"
    if not path.is_dir():
        return "is not a directory"
    return None


def has_any_xml(path: Path) -> bool:
    """True if the folder holds XML either loose or inside a .cat catalog.

    Packed mods have no loose *.xml at all, so a naive rglob check would call
    every packed mod empty — the exact blind spot that made x4validate report
    packed mods as clean before 2026-07-26.
    """
    if any(path.rglob("*.xml")):
        return True
    try:
        return bool(_cat.mod_vfs(path))
    except Exception:  # noqa: BLE001 - unreadable catalog is not "no xml"
        return True


def require_mod_dir(path: Path, label: str = "mod folder", *,
                    warn_if_empty: bool = True) -> None:
    """Exit(2) unless *path* is a real directory. Warn if it holds no XML.

    Call this in EVERY entry point that takes a directory, before any analysis.
    Exit 2 (not 1) marks a usage error, distinct from 1 = findings and
    3 = degraded, so a gate can tell "you typed the path wrong" from "your mod
    has problems".
    """
    problem = mod_dir_problem(path)
    if problem is not None:
        print(f"error: {label} {problem}: {path}", file=sys.stderr)
        print("       (refusing to report a clean result for a folder that was "
              "never examined)", file=sys.stderr)
        raise SystemExit(2)
    if warn_if_empty and not has_any_xml(path):
        print(f"warning: {label} contains no XML, loose or packed: {path}\n"
              "         any 'nothing found' result below is about an EMPTY input.",
              file=sys.stderr)

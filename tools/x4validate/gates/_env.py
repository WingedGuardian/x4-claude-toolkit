r"""Inputs the gates need, resolved rather than hardcoded.

Until 2026-07-29 three of the four gates opened with a developer's own absolute
paths — the game install and a personal mod-workspace directory, hostname and
username included. That is how a personal path survives into a public repo, and
this docstring deliberately does not quote them, so the pre-push grep for such
paths stays clean rather than learning to ignore a known hit. The note in
`gates/README.md` claiming they had already been parameterised was simply wrong,
which is worse, because a false "this is clean" is what stops the next check.

Everything here resolves through `x4validate._paths` (the same layered
env → `.claude/x4-paths.env` → fallback chain the CLI uses), with one addition:

**`$X4_ORACLE_LOG`** — a *captured* `debug.txt` snapshot to measure against. It has
to be pinned rather than live, or the denominator moves between game sessions and
the 234/234 result stops meaning anything. It is deliberately NOT committed and
never will be: a real `debug.txt` names the mods you run, your filesystem layout
and your play session. Anyone reproducing these numbers supplies their own.

A missing input is a **SKIP (exit 2)**, never an empty run that prints like a pass.
That is the same contract `Report.skipped` enforces one level down.
"""

from __future__ import annotations


import sys
from pathlib import Path
from typing import NoReturn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from x4validate import _paths  # noqa: E402


def skip(what: str, how: str) -> NoReturn:
    print(f"SKIP: {what}\n      {how}", file=sys.stderr)
    raise SystemExit(2)


def extensions() -> Path:
    """The installed extension set — the population every gate measures over."""
    p = _paths.game_extensions()
    if p is None or not p.is_dir():
        skip(f"no installed extension set (resolved to {p or 'nothing'})",
             "set $X4_GAME or $X4_EXTENSIONS (see .claude/x4-paths.env), "
             "then check with `x4validate --paths`")
    return p


def mods_dir() -> Path:
    """Where the mod source folders live, one per mod."""
    p = _paths.mods()
    if p is None or not p.is_dir():
        skip(f"no mod source directory (resolved to {p or 'nothing'})",
             "set $X4_MODS (see .claude/x4-paths.env)")
    return p


def reference() -> Path:
    """The unpacked base+DLC tree the audits compare mod patches against."""
    p = _paths.reference()
    if p is None or not p.is_dir():
        skip(f"no reference tree (resolved to {p or 'nothing'})",
             "set $X4_REFERENCE (see .claude/x4-paths.env), then check with "
             "`x4validate --paths`")
    return p


def effective_db() -> Path:
    """The x4effective store. Built, not shipped — a missing one is a SKIP."""
    from x4validate import _effective
    p = _paths._resolve(lambda layer: _paths._pick(layer, "X4_EFFECTIVE_DB"))
    path = Path(p) if p else _effective.DB_PATH
    if path is None or not Path(path).is_file():
        skip(f"no effective store (resolved to {path or 'nothing'})",
             "run `x4effective build` first, or set $X4_EFFECTIVE_DB")
    return Path(path)


def oracle_log() -> Path:
    """A pinned debug.txt capture. Never committed — see the module docstring.

    Resolved through `_paths`' own layers, not `os.environ` alone: the config file
    is where a user would naturally put this, and a gate that only honoured a real
    exported variable would silently ignore it and report SKIP with the setting
    sitting right there in `x4-paths.env`.
    """
    raw = _paths._resolve(lambda layer: _paths._pick(layer, "X4_ORACLE_LOG"))
    if not raw:
        skip("no captured engine log ($X4_ORACLE_LOG is unset)",
             "point it at a debug.txt saved AFTER a full game load with your modlist "
             "active, e.g. X4_ORACLE_LOG=/path/to/debug-YYYY-MM-DD.txt. Use a copy, not "
             "the live file — the log must not change between runs or the denominator "
             "moves. It is never committed: a real debug.txt names your mods and paths.")
    p = Path(raw)
    if not p.is_file():
        skip(f"$X4_ORACLE_LOG points at nothing readable: {p}",
             "check the path; a captured log, not the live debug.txt")
    return p


def registry_file() -> Path:
    """The mod registry (`modlist.yaml`), resolved the way the package does.

    Exists so a gate that needs the registry copies the REAL one into a sandbox
    rather than either hardcoding a path or writing to the live file. `qa_sweep`
    used to run `x4modlist dashboard` against the live registry, regenerating
    the user's WORKLIST.md on every sweep.
    """
    from x4validate import _registry
    p = _registry.DEFAULT_REGISTRY
    if p is None:
        skip("no registry configured", "set $X4_MODS or $X4_REGISTRY")
    p = _registry._registry_file(Path(p))
    if not p.is_file():
        skip(f"no registry file at {p}", "run `x4modlist ingest` first")
    return p

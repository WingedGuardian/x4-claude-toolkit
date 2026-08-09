#!/usr/bin/env python
"""QA sweep — exercise EVERY tool x EVERY subcommand against the real install.

Written 2026-08-08 after a defect (root-<replace> silently dropped, reported as
applied) survived three sessions because nothing ever exercised that path. The
point is to find bugs here, not while using the tools.

Each cell records: exit code, stdout size, and whether it crashed. A cell is
RED on an unhandled traceback or an unexpected exit code; YELLOW when it runs
but returns nothing useful (a possible unfinished feature); GREEN otherwise.

Run:  uv run python gates/qa_sweep.py [--verbose]
Exit: 0 all green, 1 any red, 3 only yellows.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402

EXT = _env.extensions()
REF = _env.reference()
try:
    DEV = _env.mods_dir()
except SystemExit:      # mod-source dir is optional here; extensions are enough
    DEV = EXT

VERBOSE = "--verbose" in sys.argv


@dataclass
class Cell:
    tool: str
    label: str
    argv: list[str]
    expect: tuple[int, ...] = (0,)
    #: substring that must appear in stdout for the cell to count as doing work
    wants: str | None = None
    #: True when a non-zero exit is a legitimate finding, not a tool failure
    findings_ok: bool = False
    status: str = ""
    detail: str = ""
    out: str = field(default="", repr=False)


def _pick_mod(*, patching: bool = False) -> str:
    """An installed mod to exercise the CLIs against.

    Chosen from whatever is installed rather than named, so this runs on anyone's
    setup. `patching=True` prefers a mod that actually ships diff patches, which
    is what makes the sel-resolution paths do real work.
    """
    mods = [d for d in sorted(EXT.iterdir())
            if d.is_dir() and not d.name.lower().startswith("ego_dlc_")]
    if patching:
        for d in mods:
            for f in list(d.rglob("*.xml"))[:60]:
                try:
                    if b"<diff" in f.read_bytes()[:2000]:
                        return str(d)
                except OSError:
                    continue  # silent-ok: only picking a sample mod; try the next file
    return str(mods[0]) if mods else str(EXT)


def _owning_mod() -> str:
    """A mod that wins at least one value in the effective store, or a fallback.

    Read from the store so the cell exercises a real `diff-mod` result on any
    install, instead of naming one machine's overhaul.
    """
    import sqlite3
    try:
        db = _env.effective_db()
    except SystemExit:
        return Path(_pick_mod()).name
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        row = con.execute(
            "SELECT origin, COUNT(*) c FROM entities WHERE origin != 'base' "
            "GROUP BY origin ORDER BY c DESC LIMIT 1").fetchone()
        con.close()
        return row[0] if row else Path(_pick_mod()).name
    except sqlite3.Error:
        return Path(_pick_mod()).name


_MOD = _pick_mod(patching=True)
_MOD2 = _pick_mod()

_SANDBOX: str | None = None


def _sandbox_registry() -> str:
    """A throwaway copy of the real registry, made once per sweep.

    Copied rather than synthesized so the cells still exercise real data with
    real shape; written to a temp dir so the WRITING commands (`dashboard`)
    cannot touch the user's triage state.
    """
    global _SANDBOX
    if _SANDBOX is None:
        import shutil
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="x4qa_registry_"))
        dest = tmp / "modlist.yaml"
        try:
            src = _env.registry_file()
        except (SystemExit, AttributeError):
            src = None
        if src and Path(src).is_file():
            shutil.copy2(src, dest)
        else:
            dest.write_text("meta: {}\nmods: []\n", encoding="utf-8")
        _SANDBOX = str(dest)
    return _SANDBOX


CELLS: list[Cell] = [
    # ---- x4validate -----------------------------------------------------
    Cell("x4validate", "--paths", ["--paths"], wants="reference"),
    Cell("x4validate", "tier a (overlay mod)", [_MOD, "--tier", "a"],
         expect=(0, 1, 3), findings_ok=True),
    Cell("x4validate", "tier b (overlay mod)", [_MOD, "--tier", "b"],
         expect=(0, 1, 3), findings_ok=True),
    Cell("x4validate", "--json", [_MOD, "--json"],
         expect=(0, 1, 3), wants="{", findings_ok=True),
    Cell("x4validate", "--sel-only", [_MOD, "--sel-only"],
         expect=(0, 1, 3), findings_ok=True),
    Cell("x4validate", "--entity/--like", [_MOD,
                                           "--entity", "ware:ore", "--like", "ware:silicon"],
         expect=(0, 1, 3), findings_ok=True),
    Cell("x4validate", "--update", [_MOD, "--update"],
         expect=(0, 1, 3), findings_ok=True),
    Cell("x4validate", "--debug", [_MOD, "--debug"],
         expect=(0, 1, 3), findings_ok=True),
    Cell("x4validate", "nonexistent mod dir", [str(DEV / "__no_such_mod__")],
         expect=(1, 2, 3), findings_ok=True),

    # ---- x4effective ----------------------------------------------------
    Cell("x4effective", "ls macro", ["ls", "macro", "--limit", "20"], expect=(0,), wants="_macro"),
    Cell("x4effective", "ls ware", ["ls", "ware", "--limit", "20"], expect=(0,), wants="tech"),
    Cell("x4effective", "ls --modified-only", ["ls", "macro", "--modified-only", "--limit", "10"],
         expect=(0,)),
    Cell("x4effective", "ls --filter", ["ls", "macro", "--filter", "shield", "--limit", "5"],
         expect=(0,), wants="shield"),
    Cell("x4effective", "ls unknown kind", ["ls", "__no_such_kind__"], expect=(0, 1, 2),
         findings_ok=True),
    Cell("x4effective", "show", ["show", "macro", "shield_arg_l_standard_01_mk1_macro"],
         expect=(0,), wants="recharge"),
    Cell("x4effective", "attr", ["attr", "macro", "recharge.delay",
                                 "--class", "shieldgenerator"], expect=(0,)),
    Cell("x4effective", "who-sets", ["who-sets", "macro", "shield_arg_l_standard_01_mk1_macro",
                                     "recharge.delay"], expect=(0,), wants="recharge.delay"),
    # diff-mod needs a mod that actually WINS something, discovered from the
    # store rather than named — otherwise this cell only passes on one machine.
    Cell("x4effective", "diff-mod", ["diff-mod", _owning_mod()], expect=(0,)),
    Cell("x4effective", "dump", ["dump", "libraries/wares.xml"], expect=(0,), wants="<"),
    Cell("x4effective", "dump md/ path", ["dump", "md/encounters.xml"], expect=(0, 1),
         findings_ok=True),
    Cell("x4effective", "dump unknown vpath", ["dump", "no/such/file.xml"], expect=(0, 1, 2),
         findings_ok=True),
    Cell("x4effective", "sql", ["sql", "SELECT COUNT(*) FROM entities"], expect=(0,)),
    Cell("x4effective", "sql rejects write", ["sql", "DELETE FROM entities"],
         expect=(1, 2), findings_ok=True),
    Cell("x4effective", "show unknown entity", ["show", "macro", "__no_such_entity__"],
         expect=(0, 1), findings_ok=True),

    # ---- x4compat -------------------------------------------------------
    Cell("x4compat", "check", ["check"], expect=(0, 1, 3), findings_ok=True),

    # ---- x4xref ---------------------------------------------------------
    Cell("x4xref", "who-calls", ["who-calls", "find_station"], expect=(0, 1), findings_ok=True),
    Cell("x4xref", "who-listens", ["who-listens", "event_player_ejected"],
         expect=(0, 1), findings_ok=True),
    Cell("x4xref", "cue", ["cue", "Manager"], expect=(0, 1), findings_ok=True),
    Cell("x4xref", "who-calls unknown", ["who-calls", "__no_such_action__"],
         expect=(0, 1), findings_ok=True),

    # ---- x4stats --------------------------------------------------------
    Cell("x4stats", "wares", ["wares", _MOD],
         expect=(0, 1, 3), findings_ok=True),
    Cell("x4stats", "macro", ["macro", str(REF / "assets/props/SurfaceElements/macros/"
                                           "shield_arg_l_standard_01_mk1_macro.xml")],
         expect=(0, 1), findings_ok=True),

    # ---- x4similar ------------------------------------------------------
    Cell("x4similar", "default sweep", ["--threshold", "0.95"], expect=(0, 1, 3),
         findings_ok=True),
    Cell("x4similar", "--cross-mod-only", ["--threshold", "0.95", "--cross-mod-only"],
         expect=(0, 1, 3), findings_ok=True),

    # ---- x4modlist ------------------------------------------------------
    # --registry points at a THROWAWAY COPY: `dashboard` WRITES WORKLIST.md, and
    # this cell was regenerating the user's real one on every sweep. It is a pure
    # function of modlist.yaml so nothing was corrupted, but a gate must not
    # mutate the state it is inspecting — that is how a sweep turns into an edit.
    Cell("x4modlist", "dashboard", ["--registry", _sandbox_registry(), "dashboard"],
         expect=(0, 1), findings_ok=True),
    Cell("x4modlist", "needs-review", ["--registry", _sandbox_registry(), "needs-review"],
         expect=(0, 1), findings_ok=True),

    # ---- x4diff ---------------------------------------------------------
    Cell("x4diff", "two mod versions",
         [_MOD, _MOD2],
         expect=(0, 1), findings_ok=True),
    Cell("x4diff", "--detail",
         [_MOD, _MOD2, "--detail"],
         expect=(0, 1), findings_ok=True),
    Cell("x4diff", "same dir (no-op diff)",
         [_MOD, _MOD],
         expect=(0, 1), findings_ok=True),
]


def run(cell: Cell) -> Cell:
    # encoding= is load-bearing: the tools print U+2190 ("<-") in provenance
    # columns, and Windows' default cp1252 raises UnicodeDecodeError mid-read,
    # silently yielding an empty capture that looks like "the tool printed
    # nothing". Anyone piping these tools on Windows hits the same thing.
    proc = subprocess.run(["uv", "run", cell.tool, *cell.argv], cwd=ROOT,
                          capture_output=True, text=True, timeout=1800,
                          encoding="utf-8", errors="replace")
    out = (proc.stdout or "") + (proc.stderr or "")
    cell.out = out
    tb = "Traceback (most recent call last)" in out
    if tb:
        cell.status, cell.detail = "RED", "unhandled traceback"
    elif proc.returncode not in cell.expect:
        cell.status = "RED"
        cell.detail = f"exit {proc.returncode}, expected {cell.expect}"
    elif cell.wants and cell.wants not in out:
        cell.status, cell.detail = "YELLOW", f"no {cell.wants!r} in output ({len(out)}B)"
    elif len(out.strip()) == 0:
        cell.status, cell.detail = "YELLOW", "no output at all"
    else:
        cell.status, cell.detail = "GREEN", f"exit {proc.returncode}, {len(out)}B"
    return cell


def main() -> int:
    print(f"QA sweep — {len(CELLS)} cells across "
          f"{len({c.tool for c in CELLS})} tools\n" + "=" * 78)
    reds, yellows = [], []
    for cell in CELLS:
        try:
            run(cell)
        except subprocess.TimeoutExpired:
            cell.status, cell.detail = "RED", "TIMEOUT (>30min)"
        except Exception as exc:                       # harness must never mask a tool bug
            cell.status, cell.detail = "RED", f"harness error: {exc!r}"
        mark = {"GREEN": "  ok ", "YELLOW": " WARN", "RED": " FAIL"}[cell.status]
        print(f"{mark}  {cell.tool:<13} {cell.label:<26} {cell.detail}")
        if cell.status == "RED":
            reds.append(cell)
        elif cell.status == "YELLOW":
            yellows.append(cell)
        if VERBOSE and cell.status != "GREEN":
            for line in cell.out.splitlines()[-12:]:
                print(f"          | {line}")

    print("=" * 78)
    print(f"GREEN {len(CELLS) - len(reds) - len(yellows)}   YELLOW {len(yellows)}   RED {len(reds)}")
    for c in reds:
        print(f"\nRED  {c.tool} {c.label}: {c.detail}")
        for line in c.out.splitlines()[-14:]:
            print(f"     | {line}")
    for c in yellows:
        print(f"\nWARN {c.tool} {c.label}: {c.detail}")
    return 1 if reds else (3 if yellows else 0)


if __name__ == "__main__":
    raise SystemExit(main())

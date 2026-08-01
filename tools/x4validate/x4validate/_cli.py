"""x4validate command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import _check, _merge, _paths

_SEV_ORDER = {"error": 0, "warn": 1, "info": 2}
_SEV_LABEL = {"error": "ERROR", "warn": "WARN ", "info": "INFO "}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="x4validate",
        description="Validate X4 mod diff patches against the effective merged game tree.",
    )
    # Optional ONLY so `--paths` can run without one; still required otherwise (see below).
    p.add_argument("mod_dir", nargs="?", help="path to the mod's dev folder")
    p.add_argument("--paths", action="store_true",
                   help="show where the tool resolves the game, reference, profile and registry "
                        "(and which config file it read), then exit")
    p.add_argument("--reference", default=str(_merge.REFERENCE),
                   help="path to the unpacked base-game reference tree")
    p.add_argument("--tier", choices=["a", "b"], default="a",
                   help="a = base+DLC only (default, deterministic); "
                        "b = also merge the INSTALLED extensions in load order, so cross-mod "
                        "patches resolve and removed-by-another-mod content is caught "
                        "(ordering is community-reported: advisory)")
    p.add_argument("--profile", metavar="ID",
                   help="user profile id (the numeric folder under the X4 profile dir) — only "
                        "needed to locate debug.txt when $X4_PROFILE / $X4_DEBUGLOG are unset")
    p.add_argument("--entity", help="completeness target, e.g. ware:my_new_ware")
    p.add_argument("--like", help="vanilla analogue, e.g. ware:ore")
    p.add_argument("--json", action="store_true", help="emit findings as JSON")
    p.add_argument("--file", help="fast mode: sel-resolution for this ONE file only "
                   "(for the per-edit hook); mod_dir is its mod root")
    p.add_argument("--sel-only", action="store_true",
                   help="(implied by --file) run only sel-resolution, skip ref/completeness")
    p.add_argument("--update", action="store_true",
                   help="add 9.0 mechanical-port checks: XSD schema validation of MD/aiscript "
                   "files (~100s warmup) + the runtime-only migration-map heuristic")
    p.add_argument("--debug", nargs="?", const="\0", metavar="DEBUG_TXT",
                   help="correlate the engine's own debug.txt errors for this mod (authoritative; "
                   "GATES on engine errors). Bare --debug uses the active profile's debug.txt")
    args = p.parse_args(argv)
    try:  # Windows consoles default to cp1252; mod content may not be ASCII.
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # silent-ok: console encoding shim. Failure means the default codec
        # stays; it affects how output LOOKS, never what was examined.

    if args.paths:
        # Silent misconfiguration is this tool's worst failure mode — every location is
        # overridable and most are derived, so there has to be one command that answers
        # "where do you think everything is, and which config file did you read?".
        print("\n".join(_paths.describe()))
        return 0

    if not args.mod_dir:
        print("error: mod_dir is required (or use --paths)", file=sys.stderr)
        return 2
    mod_dir = Path(args.mod_dir)
    if not mod_dir.is_dir():
        print(f"error: mod folder not found: {mod_dir}", file=sys.stderr)
        return 2

    config = _merge.Config(reference=Path(args.reference))
    if args.tier == "b":
        print("note: Tier B merges the INSTALLED extension set in load order so cross-mod "
              "patches resolve. Inter-mod load order is community-reported, not documented "
              "by Egosoft — treat ordering-dependent results as advisory.", file=sys.stderr)

    debug_path = args.debug
    if debug_path == "\0":  # bare --debug -> the active profile's debug.txt
        # Ask _paths first ($X4_DEBUGLOG, else $X4_PROFILE/debug.txt). This used to be
        # `Path.home()/"Documents"/"Egosoft"/"X4"/<id>/"debug.txt"` — the WINDOWS layout,
        # hardcoded, so bare --debug could never work on Linux (~/.config/EgoSoft/X4/<id>)
        # or macOS, both of which the toolkit documents and supports.
        resolved = _paths.debug_log()
        if resolved is None and args.profile:
            resolved = Path.home() / "Documents" / "Egosoft" / "X4" / args.profile / "debug.txt"
        if resolved is None:
            print("error: --debug needs a log to read. Configure $X4_PROFILE or $X4_DEBUGLOG "
                  "(see .claude/x4-paths.env), pass --profile <id>, or give the path: "
                  "--debug <path/to/debug.txt>", file=sys.stderr)
            return 2
        debug_path = str(resolved)

    report = _check.validate(mod_dir, config, entity=args.entity, like=args.like,
                             only_file=args.file, update=args.update, debug=debug_path,
                             tier=args.tier)

    if args.json:
        print(json.dumps({
            "findings": [asdict(f) for f in report.findings],
            "notes": report.notes,
            "error_count": len(report.errors),
            "skipped": [asdict(s) for s in report.skipped],
            "degraded": bool(report.degraded),
        }, indent=2))
    else:
        _print_human(mod_dir, report)
        # Process nudge: exprlint is a heuristic; the engine (via --debug) is the authority.
        if debug_path is None and any(f.category == "exprlint" for f in report.findings):
            print("\n  note: expression-grammar findings above are heuristic — confirm against a "
                  "real load with  --debug <profile>/debug.txt  after an in-game test.")

    # Exit codes: 0 clean · 1 errors found · 3 DEGRADED (a requested check could
    # not run, so a clean result proves nothing). 3 is separate from 1 so a gate
    # can tell "your mod is broken" from "the validator was blindfolded" — the
    # second used to exit 0 and read as a pass.
    if report.errors:
        return 1
    return 3 if report.degraded else 0


def _print_skipped(report: _check.Report) -> None:
    """Print work that was NOT done. Never let this be silent: a check that could
    not run must not be indistinguishable from a check that found nothing."""
    if not report.skipped:
        return
    print("\n  NOT CHECKED:")
    for s in report.skipped:
        mark = "!!" if s.degraded else " -"
        print(f"  {mark} {s.what}: {s.why}")
    if report.degraded:
        print("  ** a check you asked for did not run — this result is NOT a pass **")


def _print_human(mod_dir: Path, report: _check.Report) -> None:
    print(f"x4validate -- {mod_dir}")
    for note in report.notes:
        print(f"  - {note}")
    if not report.findings:
        # "no findings" is only OK if everything was actually examined.
        print("  OK: no issues found" if not report.skipped
              else "  no issues found in what could be checked")
        _print_skipped(report)
        return
    ordered = sorted(report.findings, key=lambda f: (_SEV_ORDER[f.severity], f.vpath, f.line))
    for f in ordered:
        loc = f.vpath + (f":{f.line}" if f.line else "")
        print(f"  [{_SEV_LABEL[f.severity]}] {f.category:13} {loc}\n          {f.message}")
    n_info = sum(1 for f in report.findings if f.severity == "info")
    print(f"\n  {len(report.errors)} error(s), "
          f"{sum(1 for f in report.findings if f.severity == 'warn')} warning(s)"
          + (f", {n_info} info" if n_info else "")
          + (f", {len(report.skipped)} not checked" if report.skipped else ""))
    _print_skipped(report)


if __name__ == "__main__":
    raise SystemExit(main())

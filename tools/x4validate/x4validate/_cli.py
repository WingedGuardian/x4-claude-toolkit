"""x4validate command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import _check, _merge

_SEV_ORDER = {"error": 0, "warn": 1, "info": 2}
_SEV_LABEL = {"error": "ERROR", "warn": "WARN ", "info": "INFO "}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="x4validate",
        description="Validate X4 mod diff patches against the effective merged game tree.",
    )
    p.add_argument("mod_dir", help="path to the mod's dev folder")
    p.add_argument("--reference", default=str(_merge.REFERENCE),
                   help="path to the unpacked base-game reference tree")
    p.add_argument("--tier", choices=["a", "b"], default="a",
                   help="a = base+DLC (default, deterministic); b = +enabled mods (warns on order)")
    p.add_argument("--profile", default=None, help="active user profile id (Tier B)")
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
    args = p.parse_args(argv)
    try:  # Windows consoles default to cp1252; mod content may not be ASCII.
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    mod_dir = Path(args.mod_dir)
    if not mod_dir.is_dir():
        print(f"error: mod folder not found: {mod_dir}", file=sys.stderr)
        return 2

    config = _merge.Config(reference=Path(args.reference))
    if args.tier == "b":
        print("warning: Tier B inter-mod load order is undocumented; "
              "results assume a fixed order — treat as advisory.", file=sys.stderr)

    report = _check.validate(mod_dir, config, entity=args.entity, like=args.like,
                             only_file=args.file, update=args.update)

    if args.json:
        print(json.dumps({
            "findings": [asdict(f) for f in report.findings],
            "notes": report.notes,
            "error_count": len(report.errors),
        }, indent=2))
    else:
        _print_human(mod_dir, report)

    return 1 if report.errors else 0


def _print_human(mod_dir: Path, report: _check.Report) -> None:
    print(f"x4validate -- {mod_dir}")
    for note in report.notes:
        print(f"  - {note}")
    if not report.findings:
        print("  OK: no issues found")
        return
    ordered = sorted(report.findings, key=lambda f: (_SEV_ORDER[f.severity], f.vpath, f.line))
    for f in ordered:
        loc = f.vpath + (f":{f.line}" if f.line else "")
        print(f"  [{_SEV_LABEL[f.severity]}] {f.category:13} {loc}\n          {f.message}")
    print(f"\n  {len(report.errors)} error(s), "
          f"{sum(1 for f in report.findings if f.severity == 'warn')} warning(s)")


if __name__ == "__main__":
    raise SystemExit(main())

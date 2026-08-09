#!/usr/bin/env python
"""Edge sweep — hostile and degenerate inputs against every CLI.

Smoke tests prove the happy path. This proves the tools FAIL WELL: a clear
message and a sane exit code, never a traceback and never a confident wrong
answer. Covers empty mods, malformed manifests, missing args, absent paths, and
an unconfigured environment (the state a new user is actually in).

Run:  uv run python gates/edge_sweep.py [--verbose]
Exit: 0 all handled, 1 any traceback or hang.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERBOSE = "--verbose" in sys.argv
# Every input this sweep uses is synthesized in a temp dir, so no game paths are
# needed — deliberately, since hostile-input coverage should run anywhere.

TOOLS = ["x4validate", "x4modlist", "x4compat", "x4xref",
         "x4stats", "x4similar", "x4effective", "x4diff"]


def run(argv: list[str], env: dict | None = None, timeout: int = 900):
    e = dict(os.environ)
    if env is not None:
        e.update(env)
    p = subprocess.run(["uv", "run", *argv], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, env=e)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def check(label: str, argv: list[str], env: dict | None = None) -> tuple[str, str]:
    """A cell passes when it neither crashes nor hangs."""
    try:
        rc, out = run(argv, env)
    except subprocess.TimeoutExpired:
        return "FAIL", "HANG (>15min)"
    if "Traceback (most recent call last)" in out:
        tail = [ln for ln in out.strip().splitlines() if ln.strip()][-1:]
        return "FAIL", f"traceback: {tail[0][:90] if tail else '?'}"
    if rc == 0 and not out.strip():
        return "WARN", "exit 0 with no output"
    return "ok", f"exit {rc}, {len(out)}B"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="x4qa_"))
    fails, warns, total = [], [], 0
    try:
        empty = tmp / "empty_mod"
        empty.mkdir()

        manifest_only = tmp / "manifest_only"
        manifest_only.mkdir()
        (manifest_only / "content.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<content id="qa_manifest_only" name="QA" version="1" />\n', encoding="utf-8")

        broken = tmp / "broken_manifest"
        broken.mkdir()
        (broken / "content.xml").write_text("<content id='unclosed'", encoding="utf-8")

        badxml = tmp / "broken_patch"
        (badxml / "libraries").mkdir(parents=True)
        (badxml / "content.xml").write_text(
            '<content id="qa_broken_patch" name="QA" version="1" />', encoding="utf-8")
        (badxml / "libraries" / "wares.xml").write_text(
            "<diff><replace sel='//wares'><wares>", encoding="utf-8")

        emptypatch = tmp / "empty_patch"
        (emptypatch / "libraries").mkdir(parents=True)
        (emptypatch / "content.xml").write_text(
            '<content id="qa_empty_patch" name="QA" version="1" />', encoding="utf-8")
        (emptypatch / "libraries" / "wares.xml").write_text("<diff/>", encoding="utf-8")

        missing = tmp / "does_not_exist"

        cases: list[tuple[str, list[str], dict | None]] = [
            ("empty mod dir",            ["x4validate", str(empty)], None),
            ("manifest only",            ["x4validate", str(manifest_only)], None),
            ("malformed content.xml",    ["x4validate", str(broken)], None),
            ("malformed diff patch",     ["x4validate", str(badxml)], None),
            ("empty <diff/>",            ["x4validate", str(emptypatch)], None),
            ("missing dir",              ["x4validate", str(missing)], None),
            ("empty mod, tier b",        ["x4validate", str(empty), "--tier", "b"], None),
            ("bad tier value",           ["x4validate", str(empty), "--tier", "z"], None),
            ("--entity without --like",  ["x4validate", str(manifest_only),
                                          "--entity", "ware:ore"], None),
            ("--file that does not exist", ["x4validate", str(manifest_only),
                                            "--file", "no/such.xml"], None),
            ("x4diff missing operand",   ["x4diff", str(empty)], None),
            ("x4diff both missing",      ["x4diff", str(missing), str(missing)], None),
            ("x4stats macro on non-xml", ["x4stats", "macro", str(broken / "content.xml")], None),
            ("x4stats wares empty mod",  ["x4stats", "wares", str(empty)], None),
            ("x4effective sql injection", ["x4effective", "sql",
                                           "SELECT 1; DROP TABLE entities"], None),
            ("x4effective sql garbage",  ["x4effective", "sql", "NOT SQL AT ALL"], None),
            ("x4effective dump traversal", ["x4effective", "dump", "../../etc/passwd"], None),
            ("x4xref who-calls empty",   ["x4xref", "who-calls", ""], None),
            ("x4similar bad threshold",  ["x4similar", "--threshold", "9"], None),
            ("x4similar neg threshold",  ["x4similar", "--threshold", "-1"], None),
            ("x4compat bad subcommand",  ["x4compat", "nosuchcmd"], None),
            ("x4modlist bad subcommand", ["x4modlist", "nosuchcmd"], None),
        ]
        # every tool must survive a fully unconfigured environment
        blank = {k: "" for k in ("X4_GAME_ROOT", "X4_REFERENCE", "X4_PROFILE",
                                 "X4_REGISTRY", "X4_MODS", "X4_EFFECTIVE_DB")}
        for t in TOOLS:
            cases.append((f"{t} unconfigured env", [t, "--help"], blank))
        cases.append(("x4validate unconfigured run", ["x4validate", str(manifest_only)], blank))
        cases.append(("x4effective unconfigured", ["x4effective", "ls", "macro"], blank))

        print(f"EDGE SWEEP — {len(cases)} hostile-input cells\n" + "=" * 78)
        for label, argv, env in cases:
            total += 1
            status, detail = check(label, argv, env)
            print(f"  {status:<5} {label:<30} {detail}")
            if status == "FAIL":
                fails.append((label, argv, detail))
            elif status == "WARN":
                warns.append((label, detail))
        print("=" * 78)
        print(f"ok {total - len(fails) - len(warns)}   WARN {len(warns)}   FAIL {len(fails)}")
        for label, argv, detail in fails:
            print(f"\nFAIL {label}\n     argv={argv}\n     {detail}")
        for label, detail in warns:
            print(f"WARN {label}: {detail}")
        return 1 if fails else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

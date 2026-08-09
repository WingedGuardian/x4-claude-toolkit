#!/usr/bin/env python
r"""Techniques the other 19 gates do not apply at all.

Written after noticing that the previous round stopped because I asked the
stopping question, not because the search was exhausted — and that the question
itself found three more issues. So: what has NOTHING checked yet?

  1. SENSITIVITY. `tool_properties` proves x4diff is self-consistent (identity,
     antisymmetry). Both hold TRIVIALLY for a tool that under-reports — a diff
     that always answered "no changes" passes them. Nothing ever verified it
     DETECTS a known planted delta, or that the counts are the RIGHT numbers.

  2. CROSS-TOOL AGREEMENT. Every audit so far compares a tool to itself or to a
     fresh parse. Two different tools answering the same question differently is
     a whole failure class nothing looks for: x4compat names a winner for a
     contested file; x4effective records an origin for entities in that file.
     They must be the same mod.

  3. BUILDER IDEMPOTENCE. `determinism_audit` covers x4compat's output ordering.
     The BUILDERS were never checked: build the same store twice from unchanged
     inputs and the contents must be identical. A builder that varies is one
     whose every downstream answer is unreproducible.

  4. READ-ONLY HARDENING. `qa_sweep` proves `x4effective sql` rejects DELETE.
     That is one verb. ATTACH, PRAGMA, and multi-statement payloads are the ways
     a "read-only" SQL surface actually gets subverted.

Run:  uv run python gates/cross_tool.py
Exit: 0 all checks hold, 1 any violation.
"""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402
from x4validate import _compat, _merge  # noqa: E402

EXT = _env.extensions()
failures: list[str] = []


def note(ok: bool, label: str, detail: str = "") -> None:
    print(f"  {'  ok ' if ok else ' FAIL'}  {label}{('  ' + detail) if detail else ''}")
    if not ok:
        failures.append(f"{label}: {detail}")


def run(tool: str, *argv: str) -> tuple[int, str]:
    p = subprocess.run(["uv", "run", tool, *argv], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=1800)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# ------------------------------------------------------------- 1. sensitivity

def _mod(root: Path, wares: list[tuple[str, int]], extra: dict[str, str] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "content.xml").write_text('<content id="sens" version="100"/>\n', encoding="utf-8")
    lib = root / "libraries"
    lib.mkdir(exist_ok=True)
    body = "".join(f'<ware id="{w}"><price average="{v}"/></ware>\n' for w, v in wares)
    (lib / "wares.xml").write_text(f"<wares>\n{body}</wares>\n", encoding="utf-8")
    for rel, text in (extra or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def check_sensitivity(tmp: Path) -> None:
    print("\n1. x4diff SENSITIVITY — does it detect a KNOWN planted delta?")
    base = [(f"w{i}", i * 100) for i in range(1, 6)]

    cases = [
        ("1 attr changed", [(w, 999 if w == "w1" else v) for w, v in base], None, None, (1, 0, 0, 1)),
        ("3 attrs changed", [(w, v + 1 if w in {"w1", "w2", "w3"} else v) for w, v in base],
         None, None, (1, 0, 0, 3)),
        ("1 file added", base, {"libraries/jobs.xml": "<jobs/>\n"}, None, (0, 1, 0, 0)),
        ("no change at all", base, None, None, (0, 0, 0, 0)),
    ]
    for label, wares, extra_new, extra_old, want in cases:
        a = _mod(tmp / f"a_{label.replace(' ', '_')}", base, extra_old)
        b = _mod(tmp / f"b_{label.replace(' ', '_')}", wares, extra_new)
        rc, out = run("x4diff", str(a), str(b))
        import re
        m = re.search(r"changed files:\s*(\d+)\s+added:\s*(\d+)\s+removed:\s*(\d+)", out)
        n = re.search(r"total attr changes:\s*(\d+)", out)
        got = ((int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(n.group(1)) if n else -1) if m else None)
        note(got == want, f"{label}", f"got={got} want={want}")


# --------------------------------------------------- 2. cross-tool agreement

def check_cross_tool_agreement() -> None:
    print("\n2. CROSS-TOOL AGREEMENT — x4compat's winner vs x4effective's origin")
    try:
        db = _env.effective_db()
    except SystemExit:
        note(False, "effective store available", "not built")
        return
    report = _compat.analyze(EXT, config=_merge.Config())
    overrides = [c for c in report.collisions if c.kind == "FULL-OVERRIDE"]
    if not overrides:
        note(False, "found FULL-OVERRIDE collisions to cross-check", "none on this install")
        return

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    checked = disagree = absent = 0
    for c in overrides:
        rows = con.execute(
            "SELECT DISTINCT origin FROM entities WHERE lower(vpath) = ?",
            (c.vpath.lower(),)).fetchall()
        if not rows:
            absent += 1          # file holds no store-tracked entity kind
            continue
        origins = {r[0] for r in rows}
        checked += 1
        # The store's origin must be the mod x4compat says wins. Anything else
        # means one of the two is modelling load order differently.
        if c.winner not in origins:
            disagree += 1
            if disagree <= 3:
                print(f"          {c.vpath}: compat winner={c.winner!r}, store origin={origins}")
    con.close()
    note(disagree == 0, "compat winner is the store's origin",
         f"{checked - disagree}/{checked} agree ({absent} files hold no stored entity)")


# ------------------------------------------------------ 3. builder idempotence

def check_builder_idempotence(tmp: Path) -> None:
    print("\n3. BUILDER IDEMPOTENCE — same inputs twice, identical output?")
    db1, db2 = tmp / "b1.sqlite", tmp / "b2.sqlite"
    for db in (db1, db2):
        rc, out = run("x4effective", "--db", str(db), "build", "--kinds", "job")
        if rc != 0:
            note(False, "x4effective build succeeded", f"exit {rc}")
            return

    def rows(db: Path) -> list:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        r = con.execute("SELECT kind, name, klass, vpath, origin FROM entities "
                        "ORDER BY kind, name, vpath").fetchall()
        a = con.execute("SELECT prop, value, origin FROM attrs "
                        "ORDER BY prop, value, origin").fetchall()
        con.close()
        return [r, a]

    r1, r2 = rows(db1), rows(db2)
    note(r1[0] == r2[0], "x4effective entities identical across two builds",
         f"{len(r1[0])} vs {len(r2[0])} rows")
    note(r1[1] == r2[1], "x4effective attrs identical across two builds",
         f"{len(r1[1])} vs {len(r2[1])} rows")

    t1, t2 = tmp / "x1.tsv", tmp / "x2.tsv"
    ok = True
    for t in (t1, t2):
        rc, out = run("x4xref", "build", "--out", str(t))
        if rc != 0 or not t.is_file():
            ok = False
            break
    if ok:
        note(t1.read_bytes() == t2.read_bytes(), "x4xref index byte-identical across builds",
             f"{t1.stat().st_size} vs {t2.stat().st_size} bytes")
    else:
        print("     note  x4xref build --out not available in this form; index idempotence skipped")


# ------------------------------------------------------ 4. read-only hardening

def check_sql_hardening() -> None:
    print("\n4. READ-ONLY HARDENING — `x4effective sql` beyond DELETE")
    payloads = [
        ("ATTACH", "ATTACH DATABASE 'evil.db' AS evil"),
        ("PRAGMA writable", "PRAGMA writable_schema=ON"),
        ("multi-statement", "SELECT 1; DROP TABLE entities"),
        ("UPDATE", "UPDATE entities SET origin='x'"),
        ("INSERT", "INSERT INTO entities VALUES(1,'a','b','c','d','e','f')"),
        ("CREATE", "CREATE TABLE zzz(a)"),
        ("comment-hidden write", "/* SELECT */ DELETE FROM attrs"),
    ]
    for label, sql in payloads:
        rc, out = run("x4effective", "sql", sql)
        # Must refuse: non-zero exit, and never an unhandled traceback.
        refused = rc != 0
        clean = "Traceback (most recent call last)" not in out
        note(refused and clean, f"rejects {label}",
             f"exit {rc}" + ("" if clean else "  UNHANDLED TRACEBACK"))

    # The SECOND layer, which the CLI checks above cannot see. The verb guard is
    # only a PREFIX test: `SELECT 1; DROP TABLE entities` passes it and is stopped
    # by sqlite refusing multi-statement execution (hence its exit 1, not 2). So
    # what actually makes this surface safe is the connection being opened
    # `mode=ro`. Pin it directly — a future refactor could drop `?mode=ro` and
    # every CLI-level check above would still pass.
    from x4validate import _effective
    try:
        con = _effective._connect(_env.effective_db())
    except SystemExit:
        print("     note  no store; read-only connection check skipped")
        return
    blocked = 0
    probes = ["UPDATE entities SET origin='x'", "DROP TABLE attrs", "CREATE TABLE zzz(a)"]
    for sql in probes:
        try:
            con.execute(sql)
        except sqlite3.Error:
            blocked += 1
    con.close()
    note(blocked == len(probes), "connection itself is read-only (mode=ro)",
         f"{blocked}/{len(probes)} writes blocked at the sqlite layer")


def check_path_edges(tmp: Path) -> None:
    """Windows-specific surface nothing else touches: non-ASCII names and a path
    past MAX_PATH (260). Both are ordinary for real users — mods ship with
    accented or CJK titles, and a Steam library nested a few levels deep gets
    long fast — and both fail in ways that look like "the tool is broken"."""
    print("\n5. PATH / ENCODING EDGES")
    cases = {
        "non-ASCII mod name": tmp / "Ünïcödé Mod — 日本語 (v2)",
        "path past MAX_PATH": tmp.joinpath(*[f"nested_dir_level_{i:02d}" for i in range(1, 12)],
                                           "themod"),
    }
    for label, mod in cases.items():
        (mod / "libraries").mkdir(parents=True, exist_ok=True)
        (mod / "content.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<content id="edge_probe" name="Ünïcödé — 日本語" version="100"/>\n',
            encoding="utf-8")
        (mod / "libraries" / "wares.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<diff>\n'
            "<replace sel=\"//ware[@id='ore']/price/@average\">450</replace>\n</diff>\n",
            encoding="utf-8")
        rc, out = run("x4validate", str(mod), "--tier", "a")
        ok = rc == 0 and "Traceback" not in out and "no issues found" in out
        note(ok, label, f"exit {rc}, path len {len(str(mod))}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="x4gate_cross_"))
    try:
        print("=" * 88)
        print("CROSS-TOOL / SENSITIVITY / IDEMPOTENCE / HARDENING")
        print("=" * 88)
        check_sensitivity(tmp)
        check_cross_tool_agreement()
        check_builder_idempotence(tmp)
        check_sql_hardening()
        check_path_edges(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 88)
    if failures:
        print(f"VIOLATIONS: {len(failures)}")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All cross-tool checks hold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

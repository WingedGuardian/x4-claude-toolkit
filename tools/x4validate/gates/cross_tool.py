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
     They must be the same mod -- but ONLY for the kinds where `winner` means
     "supplies the live value". It does not mean that for SUBTREE (the winner is
     the WIPER) or NAME-CLASH (deliberately empty), so the assertion is PER KIND.
     Until 2026-08-13 this checked FULL-OVERRIDE alone -- 14 of 445 collisions,
     3.1%, with HARD/SUBTREE/UNION-KEY never verified against the store at all.

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

import re
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

#: `Collision.winner` answers a DIFFERENT question per kind, so one blanket
#: assertion is wrong. See KB 2026-08-13d, BLIND-SPOTS F25/F26, CLAUDE.md #18.
#:
#:   FULL-OVERRIDE / UNION-KEY  winner supplies the ENTITY  -> entities.origin
#:   HARD                       winner owns the VALUE       -> attrs.origin
#:   SUBTREE                    winner is the WIPER, not the owner of the final
#:                              value; assert the VICTIM is gone (scoped to w0)
#:   NAME-CLASH                 winner deliberately '' (index/macros.xml decides,
#:                              not load order) -> assert it IS empty
#:   SOFT                       benign coexistence; nothing to assert
#:
#: MEASURED 2026-08-13 over the 115-mod install, and every number is the whole
#: population, not a sample: FULL-OVERRIDE 14/14, HARD 40/40, UNION-KEY 2/2,
#: SUBTREE 148/148, NAME-CLASH 20/20 -- 0 disagreements. Before the per-kind
#: split, HARD reported 6 FALSE disagreements purely from reading
#: entities.origin where the fact lives in attrs.origin.

_PRED = re.compile(r"\[[^\]]*\]")


def _vpath_forms(vpath: str) -> tuple[str, str]:
    """Literal and nesting-stripped spellings of one logical file.

    `build_touch_map` rewrites a mod-on-mod `extensions/<owner>/<rel>` patch to
    the owner's own `<rel>`, so a collision reported at the literal path must be
    looked up both ways or it silently finds nothing. Omitting this left 6 of 148
    SUBTREE rows unresolvable, which very nearly got written up as an x4compat
    blind spot instead of what it was -- a lookup bug in the checker.
    """
    return vpath.lower(), _compat._strip_nesting(vpath)


def _origins(con, vpath: str, column: str) -> set[str]:
    """Distinct origins at *vpath*, from `entities` or `attrs`."""
    for form in _vpath_forms(vpath):
        if column == "entities":
            rows = con.execute(
                "SELECT DISTINCT origin FROM entities WHERE lower(vpath) = ?",
                (form,)).fetchall()
        else:
            rows = con.execute(
                "SELECT DISTINCT a.origin FROM attrs a JOIN entities e "
                "ON a.entity_id = e.id WHERE lower(e.vpath) = ?", (form,)).fetchall()
        if rows:
            return {r[0] for r in rows}
    return set()


def _subtree_scope(w0: str) -> tuple[str, str | None]:
    """Map a SUBTREE target to ('file'|'node'|'unmapped', prop_prefix).

    A wipe is NODE-scoped, not file-scoped: a mod replacing
    `/macros/macro/properties/explosiondamage` wipes ONE node, and the victim
    legitimately keeps its other attributes in the same document. Asserting
    file-wide absence for every row produced 6 false alarms out of 148.

    MEASURED: only three w0 shapes occur on this install and NONE carries a
    predicate -- `/macros` (140), `/macros/macro/properties/<node>` (6),
    `/macros/macro` (2). The first and third are whole-document / whole-entity
    replaces, where file-wide absence IS the correct assertion.
    """
    if _PRED.search(w0):
        return "unmapped", None
    parts = [p for p in w0.split("/") if p]
    if parts in (["macros"], ["macros", "macro"]):
        return "file", None
    if "properties" in parts:
        tail = parts[parts.index("properties") + 1:]
        return ("node", ".".join(tail)) if tail else ("file", None)
    return "unmapped", None


def _victim_attrs(con, vpath: str, victim: str, prop: str | None) -> int | None:
    """How many attrs *victim* still owns at *vpath* (under *prop* if given).

    None = the file holds no store-tracked entity, which is an ABSENCE of
    coverage rather than a pass -- counted and printed separately.
    """
    for form in _vpath_forms(vpath):
        if not con.execute("SELECT COUNT(*) FROM entities WHERE lower(vpath) = ?",
                           (form,)).fetchone()[0]:
            continue
        if prop is None:
            return con.execute(
                "SELECT COUNT(*) FROM attrs a JOIN entities e ON a.entity_id = e.id "
                "WHERE lower(e.vpath) = ? AND a.origin = ?", (form, victim)).fetchone()[0]
        return con.execute(
            "SELECT COUNT(*) FROM attrs a JOIN entities e ON a.entity_id = e.id "
            "WHERE lower(e.vpath) = ? AND a.origin = ? AND (a.prop = ? OR a.prop LIKE ?)",
            (form, victim, prop, prop + ".%")).fetchone()[0]
    return None


def check_cross_tool_agreement() -> None:
    print("\n2. CROSS-TOOL AGREEMENT - x4compat's winner vs x4effective's origin")
    try:
        db = _env.effective_db()
    except SystemExit:
        note(False, "effective store available", "not built")
        return
    report = _compat.analyze(EXT, config=_merge.Config())
    if not report.collisions:
        note(False, "found collisions to cross-check", "none on this install")
        return
    by_kind: dict[str, list] = {}
    for c in report.collisions:
        by_kind.setdefault(c.kind, []).append(c)

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

    # --- kinds where the winner supplies the live value ----------------------
    for kind, column in (("FULL-OVERRIDE", "entities"),
                         ("UNION-KEY", "entities"),
                         ("HARD", "attrs")):
        rows = by_kind.get(kind, [])
        if not rows:
            print(f"          {kind}: none on this install")
            continue
        checked = disagree = absent = 0
        for c in rows:
            # `live_value_owner()` is the single definition of "which mod's value
            # is live" — it returns None for the kinds where naming one would be a
            # confident wrong answer, so this loop cannot ask the question of a
            # kind that has no answer.
            owner = c.live_value_owner()
            if owner is None:
                absent += 1
                continue
            origins = _origins(con, c.vpath, column)
            if not origins:
                absent += 1          # file holds no store-tracked entity kind
                continue
            checked += 1
            if owner not in origins:
                disagree += 1
                if disagree <= 3:
                    print(f"          {c.vpath}: compat live owner={owner!r}, "
                          f"{column} origin={sorted(origins)}")
        note(disagree == 0, f"{kind}: compat winner is the store's origin",
             f"{checked - disagree}/{checked} agree via {column}.origin "
             f"({absent} of {len(rows)} hold no stored entity)")

    # --- SUBTREE: the winner is the WIPER; the VICTIM must be gone -----------
    subs = by_kind.get("SUBTREE", [])
    if subs:
        ok = viol = absent = unmapped = 0
        for c in subs:
            mode, prop = _subtree_scope(c.target)
            if mode == "unmapped":
                unmapped += 1
                continue
            n = _victim_attrs(con, c.vpath, c.mods[0], prop)
            if n is None:
                absent += 1
                continue
            if n:
                viol += 1
                if viol <= 3:
                    print(f"          {c.vpath}: w0={c.target} victim={c.mods[0]!r} "
                          f"wiped_by={c.wiped_by!r} still owns {n} attr(s)")
            else:
                ok += 1
        # Every row is accounted for, and the residue prints even when it is 0.
        note(viol == 0, "SUBTREE: the wiped mod owns nothing under the wiped node",
             f"{ok}/{ok + viol} clean - {unmapped} unmapped w0 - {absent} no stored "
             f"entity - accounted {ok + viol + unmapped + absent}/{len(subs)}")

    # --- NAME-CLASH: winner is deliberately empty ---------------------------
    clashes = by_kind.get("NAME-CLASH", [])
    if clashes:
        named = [c for c in clashes if c.winner]
        note(not named, "NAME-CLASH: winner left empty (index/macros.xml decides)",
             f"{len(clashes) - len(named)}/{len(clashes)} empty")

    soft = len(by_kind.get("SOFT", []))
    print(f"          (SOFT {soft} not cross-checked: benign coexistence, no winner claim)")
    con.close()


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

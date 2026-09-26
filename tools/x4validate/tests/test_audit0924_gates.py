"""AUDIT-2026-09-24 Phase 1 -- BaseX (BX-*) and gates (GT-*).

Every test here is `xfail(strict=True)`: it FAILS on the audited code for the reason named in
its `reason=`, and turns into an XPASS -> hard failure the moment a fix lands, so the marker
must be removed together with the fix.

Only DEPENDENCIES are stubbed: BaseX (`run_xq` / `basex_query`), subprocess launches of the
CLIs, the effective store (a synthetic sqlite of the real two-table schema), the registry
loader, and `_env` path resolution. The unit under test -- the gate's or the tool's own
decision logic -- always runs for real. No test here starts a JVM, runs a CLI, reads the real
corpus, or writes outside `tmp_path`.
"""
from __future__ import annotations

import importlib
import importlib.util
import io
import json
import re
import runpy
import sqlite3
import sys
import types
from pathlib import Path

import pytest

from conftest import import_gate

PKG = Path(__file__).resolve().parent.parent            # tools/x4validate
BASEX = PKG.parent / "basex"                           # tools/basex
GATES = PKG / "gates"


def _basex(name: str):
    """Import a tools/basex module the way tools/basex/test_*.py do (bare import, dir on path)."""
    if not (BASEX / f"{name}.py").is_file():
        pytest.skip(f"no BaseX tooling at {BASEX}")
    if str(BASEX) not in sys.path:
        sys.path.insert(0, str(BASEX))
    return importlib.import_module(name)


# ============================================================================ BX-1 / BX-5 (ask.py)

@pytest.fixture
def ask(monkeypatch):
    """ask.py with BaseX, the preflight and freshness stubbed; coverage reads COMPLETE 100/100."""
    mod = _basex("ask")
    staleness = _basex("staleness")
    monkeypatch.setattr(mod.preflight, "check", lambda *a, **k: [])
    for k in ("MSYSTEM", "MSYS_NO_PATHCONV", "MSYS2_ARG_CONV_EXCL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(mod, "load_coverage", lambda db: {
        "db": db, "status": "complete", "supports_negative_claim": True,
        "indexed": {"total": 100}, "expected": {"total": 100}, "unparseable": []})
    monkeypatch.setattr(mod, "staleness_verdict", lambda db: staleness.Verdict(True, [], db))

    def fake_basex(items):
        def run_xq(q):
            if mod._SEP in q:
                return f"{len(items)}\n{mod._SEP}\n" + "\n".join(items)
            return "\n".join(items)
        monkeypatch.setattr(mod, "run_xq", run_xq)
    mod._fake = fake_basex
    return mod


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 BX-1: a zero from db:get(<db>, <typo'd path>) "
                   "is certified NEGATIVE CONFIRMED over the WHOLE database's denominator")
def test_bx1_a_zero_from_ONE_addressed_document_is_not_a_negative_over_the_database(ask, capsys):
    ask._fake([])
    rc = ask.main(["xq", "db:get('x4eff','no/such/typo.xml')//ware", "--db", "x4eff"])
    out = capsys.readouterr().out
    assert "NEGATIVE CONFIRMED" not in out and rc != 0, (
        f"rc={rc}: 100 of 100 documents describes the database, not the one path the query "
        f"addressed (which does not exist)\n{out}")


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 BX-1: two-arg db:get and a variable db name "
                   "escape the foreign-database scope guard (ask.py regex requires `('name')`)")
@pytest.mark.parametrize("query", [
    "db:get('x4eff','libraries/wares.xml')//nosuch",
    "let $d := 'x4eff' return collection($d)//nosuch",
])
def test_bx1_a_query_reaching_x4eff_is_not_scored_against_x4raw(ask, capsys, query):
    ask._fake([])
    rc = ask.main(["xq", query])                          # --db defaults to x4raw
    out = capsys.readouterr().out
    assert "NEGATIVE CONFIRMED" not in out, (
        f"rc={rc}: a query that searched (or may have searched) x4eff was certified against "
        f"x4raw's coverage and freshness\n{out}")


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 BX-5: a boolean `false` result is counted "
                   "as 1 item and printed as a positive answer, rc 0")
def test_bx5_a_false_result_is_not_a_hit(ask, capsys):
    ask._fake(["false"])
    rc = ask.main(["xq", "exists(collection('x4raw')//nosuch)"])
    assert rc != 0, f"'false' read as one hit, rc {rc}:\n{capsys.readouterr().out}"


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 BX-5: an empty-string result is counted as "
                   "1 item and printed as a positive answer, rc 0")
def test_bx5_an_empty_string_result_is_not_a_hit(ask, capsys):
    ask._fake([""])
    rc = ask.main(["xq", "string(collection('x4raw')//nosuch)"])
    assert rc != 0, f"'' read as one hit, rc {rc}:\n{capsys.readouterr().out}"


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 BX-5: the scope refusal advises "
                   "`--db x4eff/libraries`, which argparse's choices reject")
def test_bx5_the_scope_refusal_only_advises_a_db_argparse_accepts(ask, capsys):
    ask._fake([])
    rc = ask.main(["xq", "collection('x4eff/libraries')//ware", "--db", "x4eff"])
    err = capsys.readouterr().err
    advised = re.findall(r"--db (\S+?)\.?$", err, re.M)
    assert rc == 2 and advised, err
    assert all(a in ("x4raw", "x4eff") for a in advised), (
        f"advice names {advised}; following it is an argparse error\n{err}")


# ============================================================================ BX-2 (stage.py)

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 BX-2: stage.py:82 `names or (mini pair)` "
                   "treats Config's correct EMPTY answer as a failure and stages both mini-DLC")
def test_bx2_an_empty_packed_dlc_answer_is_honoured(monkeypatch):
    stage = _basex("stage")
    from x4validate import _merge
    monkeypatch.setattr(_merge.Config, "packed_dlc_names", lambda self: set())
    got = stage.packed_dlc_names()
    assert got == (), (f"Config said no DLC is packed-only (all unpacked into reference\\), yet "
                       f"{got} would be staged into /base/extensions ON TOP of the reference copies")


# ============================================================================ BX-3 (build scripts)

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 BX-3: the build drops the DB before "
                   "invalidating coverage-<db>.json, so a failed rebuild leaves the old licence")
@pytest.mark.parametrize("script", ["build-corpus.sh", "build-effective.sh"])
def test_bx3_the_old_coverage_licence_is_revoked_before_the_db_is_dropped(script):
    text = (BASEX / script).read_text(encoding="utf-8")
    drop = text.find("DROP DB")
    assert drop > 0, f"{script}: no DROP DB found -- the fixture premise moved"
    revoke = re.search(r"rm -f[^\n]*coverage-", text[:drop])
    assert revoke, (f"{script}: nothing removes coverage-$DB.json before DROP DB; an "
                    f"interrupted or failed rebuild (exit at the 'not found' grep) leaves the "
                    f"previous build's supports_negative_claim=true beside a partial database")


# ============================================================================ BX-4 (coverage.py)

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 BX-4: coverage.py judges 'accounted' on "
                   "the AGGREGATE deficit, so +5 base / -5 mods nets to 0 and licenses negatives")
def test_bx4_offsetting_per_root_errors_do_not_license_a_negative(tmp_path, monkeypatch, capsys):
    # By FILE, never by the bare name: `coverage` is also the PyPI package, and a bare import
    # can hand back that one (test_coverage_reporting.py loads it the same way).
    if not (BASEX / "coverage.py").is_file():
        pytest.skip(f"no BaseX tooling at {BASEX}")
    spec = importlib.util.spec_from_file_location("basex_coverage_audit0924", BASEX / "coverage.py")
    cov = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cov)
    ref, ext, stage = tmp_path / "ref", tmp_path / "ext", tmp_path / "stage"
    for d in (ref, ext, stage):
        d.mkdir()
    counts = {str(ref): 50, str(ext): 50}
    monkeypatch.setattr(cov, "count_disk_xml", lambda root: counts.get(str(root), 0))
    monkeypatch.setattr(cov, "basex_query", lambda db, xq: "total=100\nbase=55\nmods=45\n")
    out = tmp_path / "coverage-x4raw.json"
    rc = cov.main(["--db", "x4raw", "--stage", str(stage), "--manifest", str(tmp_path / "none.json"),
                   "--reference", str(ref), "--extensions", str(ext), "--out", str(out)])
    data = json.loads(out.read_text(encoding="utf-8"))
    assert not data["supports_negative_claim"], (
        f"rc={rc} status={data['status']}: base is +5 EXTRA and mods -5 MISSING, and the "
        f"verdict came from their sum\n{capsys.readouterr().out}")


# ============================================================================ GT-1 noop_audit

def test_gt1_an_unreadable_catalog_is_not_a_clean_noop_audit(tmp_path, monkeypatch, capsys):
    na = import_gate("noop_audit", module_level=False)
    ext, ref = tmp_path / "ext", tmp_path / "ref"
    (ext / "somemod").mkdir(parents=True)
    ref.mkdir()
    monkeypatch.setattr(na, "EXT", ext)
    monkeypatch.setattr(na, "REF", ref)
    monkeypatch.setattr(na, "UNREADABLE", [])

    def boom(*a, **k):
        raise OSError("simulated unreadable catalog")
    monkeypatch.setattr(na._cat, "mod_vfs", boom)
    rc = na.main()
    assert rc != 0, f"somemod was never audited, yet rc 0:\n{capsys.readouterr().out}"


def test_gt1_unreadable_is_named_and_rc_2_and_a_false_ok_outranks_it(tmp_path, monkeypatch, capsys):
    """The UNREADABLE list reaches the verdict: printed by name, rc 2 when nothing else was
    found -- and a real FALSE OK beside it is still rc 1 (a finding outranks a refusal)."""
    na = import_gate("noop_audit", module_level=False)
    ext, ref = tmp_path / "ext", tmp_path / "ref"
    (ext / "somemod").mkdir(parents=True)
    ref.mkdir()
    monkeypatch.setattr(na, "EXT", ext)
    monkeypatch.setattr(na, "REF", ref)
    monkeypatch.setattr(na, "UNREADABLE", [])

    def boom(*a, **k):
        raise OSError("simulated unreadable catalog")
    monkeypatch.setattr(na._cat, "mod_vfs", boom)
    assert na.main() == 2
    assert "somemod: catalog unreadable" in capsys.readouterr().out

    # A false OK in a readable mod beside the unreadable one: rc 1, not 2.
    (ref / "libraries").mkdir()
    (ref / "libraries" / "x.xml").write_bytes(b"<root><a/></root>")
    (ext / "goodmod" / "libraries").mkdir(parents=True)
    (ext / "goodmod" / "libraries" / "x.xml").write_bytes(
        b'<diff><add sel="/root/a"><b/></add></diff>')
    monkeypatch.setattr(na, "UNREADABLE", [])

    def mod_vfs(mod, packed_only=True):
        if mod.name == "somemod":
            raise OSError("simulated unreadable catalog")
        return {}
    monkeypatch.setattr(na._cat, "mod_vfs", mod_vfs)
    real_apply = na._merge.apply_diff

    def lying_apply(tree, diff):                     # reports applied, changes nothing
        import copy
        return real_apply(copy.deepcopy(tree), diff)
    monkeypatch.setattr(na._merge, "apply_diff", lying_apply)
    assert na.main() == 1, capsys.readouterr().out


# ============================================================================ GT-2 determinism_audit

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 GT-2: determinism_audit.run drops the "
                   "returncode, so a tool that refuses/crashes identically twice is 'stable'")
def test_gt2_a_command_that_fails_twice_is_not_deterministic_output(monkeypatch, capsys):
    da = import_gate("determinism_audit", module_level=False)
    monkeypatch.setattr(da, "WITH_BUILD", False)
    monkeypatch.setattr(da.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=2, stdout="error: cannot resolve the game's extensions directory\n", stderr=""))
    rc = da.main()
    assert rc != 0, f"every CASE exited 2 and was scored stable:\n{capsys.readouterr().out}"


# ============================================================================ GT-3 floors

def test_gt3_similar_audit_over_zero_pairs_is_not_a_pass(tmp_path, monkeypatch, capsys):
    _env = import_gate("_env", module_level=False)
    (tmp_path / "ref").mkdir()
    (tmp_path / "ext").mkdir()
    monkeypatch.setattr(_env, "reference", lambda: tmp_path / "ref")
    monkeypatch.setattr(_env, "extensions", lambda: tmp_path / "ext")
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=1, stdout="", stderr="Traceback (most recent call last): ...\n"))
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(GATES / "similar_audit.py"), run_name="__main__")
    assert exc.value.code not in (0, None), (
        f"x4similar produced nothing and the audit passed:\n{capsys.readouterr().out}")


def _store(path: Path, rows: list[tuple] = ()) -> Path:
    """A synthetic effective store: (entity name, vpath, prop, value, origin) per row."""
    con = sqlite3.connect(path)
    con.execute("create table entities (id integer primary key, kind, name, klass, vpath, origin)")
    con.execute("create table attrs (entity_id, prop, value, origin)")
    for i, (name, vpath, prop, value, origin) in enumerate(rows, 1):
        con.execute("insert into entities values (?,?,?,?,?,?)", (i, "macro", name, "k", vpath, "base"))
        con.execute("insert into attrs values (?,?,?,?)", (i, prop, value, origin))
    con.commit()
    con.close()
    return path


def test_gt3_provenance_audit_over_an_empty_store_is_not_a_pass(tmp_path, monkeypatch, capsys):
    pa = import_gate("provenance_audit", module_level=False)
    monkeypatch.setattr(pa, "DB", _store(tmp_path / "e.sqlite"))
    monkeypatch.setattr(pa, "REF", tmp_path)
    rc = pa.main()
    assert rc != 0, f"0 values compared, rc 0:\n{capsys.readouterr().out}"


def test_gt3_registry_provenance_over_zero_rows_is_not_a_pass(tmp_path, monkeypatch, capsys):
    rp = import_gate("registry_provenance", module_level=False)
    live = tmp_path / "modlist.yaml"
    live.write_text("mods: []\n", encoding="utf-8")
    monkeypatch.setattr(rp._env, "registry_file", lambda: live)
    monkeypatch.setattr(rp._registry, "load_registry", lambda p: {"mods": []})
    monkeypatch.setattr(rp._registry, "save_registry",
                        lambda reg, p: Path(p).write_text("mods: []\n", encoding="utf-8"))
    rc = rp.main()
    assert rc != 0, f"0 active rows audited, rc 0:\n{capsys.readouterr().out}"


def test_gt3_xsd_parity_over_files_with_no_schema_is_not_parity(tmp_path, monkeypatch, capsys):
    xfp = import_gate("xsd_fast_parity", module_level=False)
    ext, ref = tmp_path / "ext", tmp_path / "ref"
    (ext / "m" / "md").mkdir(parents=True)
    (ext / "m" / "md" / "probe.xml").write_text('<mdscript name="p"><cues/></mdscript>',
                                                encoding="utf-8")
    ref.mkdir()                                            # no libraries/ -> no schema anywhere
    monkeypatch.setattr(xfp, "EXT", ext)
    monkeypatch.setattr(xfp, "LIMIT", 0)
    monkeypatch.setattr(xfp._merge, "Config", lambda *a, **k: types.SimpleNamespace(reference=ref))
    rc = xfp.main()
    out = capsys.readouterr().out
    # The premise is that the ONE file reached the gate and had no schema. Before the fix
    # it was counted as "compared : 1"; a file the full path never validated is not a
    # comparison, so it is now reported as skipped and the denominator is 0.
    assert "full validation skipped: 1" in out, f"fixture premise moved:\n{out}"
    assert rc == 2, f"the only file had no schema to compare against, and it read as parity:\n{out}"


# ============================================================================ GT-4 rc handling

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 GT-4: edge_sweep judges only tracebacks; rc 0 "
                   "on a missing dir / bad tier / unconfigured run is scored ok")
def test_gt4_edge_sweep_does_not_pass_hostile_inputs_that_all_exit_0(monkeypatch, capsys):
    es = import_gate("edge_sweep", module_level=False)
    monkeypatch.setattr(es, "run", lambda argv, env=None, timeout=900, cwd=None:
                        (0, "OK: no issues found\n"))
    rc = es.main()
    assert rc != 0, ("`x4validate <missing dir>` exiting 0 with 'OK' is the confident wrong "
                     "answer the docstring promises to catch:\n" + capsys.readouterr().out[-800:])


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 GT-4: stress_sweep --corpus=<not a dir> "
                   "silently drops the whole unseen-corpus axis")
def test_gt4_stress_sweep_names_a_corpus_it_could_not_read(tmp_path, monkeypatch, capsys):
    ss = import_gate("stress_sweep", module_level=False)
    missing = tmp_path / "no_such_corpus"
    monkeypatch.setattr(ss, "CORPUS", missing)
    monkeypatch.setattr(ss, "run", lambda argv, timeout=900, cwd=None: (0, "ok\n"))
    rc = ss.main()
    out = capsys.readouterr()
    assert rc == 2 or missing.name in (out.out + out.err), (
        f"rc={rc}: axis 1 was asked for and skipped without a word")


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 GT-4: control_bytes returns 2 (CANNOT) over "
                   "real hits when any path is unreadable -- the refusal outranks the finding")
def test_gt4_control_bytes_hits_outrank_an_unreadable_path(tmp_path, monkeypatch):
    cb = import_gate("control_bytes", module_level=False)
    monkeypatch.setattr(cb, "tracked_text_files", lambda: [])
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"collapsed" + bytes([8]) + b"escape\n")
    rc = cb.main([str(bad), str(tmp_path / "gone.md")])
    assert rc == 1, f"a live 0x08 was found and run-gates.sh would bucket rc {rc} as CANNOT"


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 GT-4: oracle_index exits via SystemExit(str) "
                   "= rc 1 (FAIL) when the log has no ground truth, which is a CANNOT (2)")
def test_gt4_oracle_index_without_ground_truth_is_cannot_not_fail(tmp_path, monkeypatch):
    _env = import_gate("_env", module_level=False)
    log = tmp_path / "debug.txt"
    log.write_text("", encoding="utf-8")
    monkeypatch.setattr(_env, "oracle_log", lambda: log)
    sys.modules.pop("oracle_index", None)
    oi = import_gate("oracle_index", module_level=False)
    monkeypatch.setattr(oi._debuglog, "parse_debug", lambda p: [])
    with pytest.raises(SystemExit) as exc:
        oi.main()
    sys.modules.pop("oracle_index", None)
    code = exc.value.code
    rc = code if isinstance(code, int) else 1                # what the interpreter would exit with
    assert rc == 2, f"no ground truth read as a FAILED gate (rc {rc}): {code!r}"


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 GT-4: toolkit_usage turns its own REFUSAL "
                   "(qa_sweep not evaluable) into a finding, rc 1, where its docstring says 2")
def test_gt4_toolkit_usage_refusal_is_rc_2(tmp_path, monkeypatch, capsys):
    tu = import_gate("toolkit_usage", module_level=False)
    cap = {"cli": "x4validate", "sub": "", "invoked": 3, "named": 3,
           "first": "2026-09-01", "last": "2026-09-20", "last_named": "2026-09-20"}
    monkeypatch.setattr(tu, "audit", lambda: {"caps": {"x4validate": cap}, "unenumerable": [],
                                              "subs_by_cli": {"x4validate": []}})
    monkeypatch.setattr(tu, "qa_sweep_coverage",
                        lambda subs: (None, "could not import qa_sweep (SystemExit: 2)"))
    monkeypatch.setattr(tu, "RECORD", False)
    monkeypatch.setattr(tu, "BASELINE", tmp_path / "no-baseline.json")
    rc = tu.main()
    assert rc == 2, f"'could not evaluate' was reported as a finding, rc {rc}"


# ============================================================================ GT-5 aggregate / file-wide

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 GT-5: cross_tool compares the HARD winner "
                   "against every origin in the FILE, not the collided attribute's origin")
def test_gt5_cross_tool_hard_winner_is_checked_on_the_collided_attr(tmp_path, monkeypatch, capsys):
    ct = import_gate("cross_tool", module_level=False)
    from x4validate import _compat
    vp = "assets/units/size_s/macros/ship_x_macro.xml"
    db = _store(tmp_path / "e.sqlite", [("ship_a_macro", vp, "hull.max", "900", "modB"),
                                        ("ship_b_macro", vp, "hull.max", "100", "modA")])
    c = _compat.Collision(vpath=vp, kind="HARD",
                          target="/macros/macro[@name='ship_a_macro']/properties/hull/@max",
                          mods=["modB", "modA"], winner="modA")
    monkeypatch.setattr(ct, "failures", [])
    monkeypatch.setattr(ct._env, "effective_db", lambda: db)
    monkeypatch.setattr(ct._env, "extensions", lambda: tmp_path)
    monkeypatch.setattr(ct._merge, "Config", lambda *a, **k: None)
    monkeypatch.setattr(ct._compat, "analyze", lambda *a, **k: types.SimpleNamespace(collisions=[c]))
    ct.check_cross_tool_agreement()
    assert ct.failures, ("modA is the live winner on ship_a_macro hull.max, the store says modB "
                         "owns it, and the check agreed because modA owns SOMETHING in the file:\n"
                         + capsys.readouterr().out)


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 GT-5: update_corpus matches `wants` against "
                   "ANY finding of the category, not one in the case's own file")
def test_gt5_update_corpus_credits_a_detection_only_to_its_own_file(tmp_path, monkeypatch):
    uc = import_gate("update_corpus", module_level=False)
    from x4validate import _check
    F = _check.Finding
    one_file = [
        F("error", "xsd", "attribute 'space' is required but missing", vpath="md/probe_lua.xml"),
        F("warn", "migration", "Lua_Loader .keys.list kuertee_hud", vpath="md/probe_lua.xml"),
        F("warn", "exprlint", "random '.' [...] .keys.count", vpath="md/probe_list.xml"),
    ]
    monkeypatch.setattr(uc._check, "validate", lambda *a, **k: types.SimpleNamespace(findings=one_file))
    failures: list[str] = []
    uc.check("LOOSE  mod", tmp_path, failures)
    assert failures, ("3 findings in 2 files were credited as detecting all 8 planted breaks "
                      "across 8 files")


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 GT-5: register_rederivation accepts the bare "
                   "WORD 'selftest' anywhere in an entry as a named check")
def test_gt5_the_word_selftest_in_prose_is_not_a_check(tmp_path):
    rr = import_gate("register_rederivation", module_level=False)
    body = " FIXED 2026-09-01\n\nThere is no selftest for this, and no test either.\n"
    assert rr.names_a_check(body, tmp_path) is None


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 GT-5: register_rederivation ignores a cited "
                   "check FILE that does not exist when another cited file does (dead citation)")
def test_gt5_a_dead_path_citation_is_not_covered_by_a_live_one(tmp_path):
    rr = import_gate("register_rederivation", module_level=False)
    (tmp_path / "gates").mkdir()
    (tmp_path / "gates" / "unrelated.py").write_text("", encoding="utf-8")
    body = (" FIXED\n\nRe-derived by tests/test_deleted_long_ago.py; see also "
            "gates/unrelated.py for context.\n")
    assert rr.names_a_check(body, tmp_path) is None, (
        "the check that re-derives this fix was deleted, and the entry still reads as covered")


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 GT-5: register_rederivation exempts any entry "
                   "that merely QUOTES the 'NO RE-DERIVATION' marker")
def test_gt5_a_quoted_exemption_marker_is_not_an_exemption(tmp_path):
    rr = import_gate("register_rederivation", module_level=False)
    text = ('## F999 -- something FIXED\n\nWe chose not to write "NO RE-DERIVATION" here; '
            "the check is still owed.\n")
    ok, missing = rr.audit(text, tmp_path)
    assert "F999" in missing, f"ok={ok} missing={missing}"


# ============================================================================ GT-6

def test_gt6_provenance_audit_refuses_a_stale_store(tmp_path, monkeypatch, capsys):
    pa = import_gate("provenance_audit", module_level=False)
    from x4validate import _effective
    vp = "assets/x_macro.xml"
    (tmp_path / "assets").mkdir()
    (tmp_path / vp).write_text('<macros><macro name="m"><properties><hull max="100"/>'
                               '</properties></macro></macros>', encoding="utf-8")
    monkeypatch.setattr(pa, "DB", _store(tmp_path / "e.sqlite", [("m", vp, "hull.max", "200", "modA")]))
    monkeypatch.setattr(pa, "REF", tmp_path)
    monkeypatch.setattr(_effective, "store_freshness", lambda con, config=None: types.SimpleNamespace(
        fresh=False, determinable=True, reasons=["content axis moved"],
        banner=lambda *a, **k: "STALE"))
    rc = pa.main()
    assert rc == 2, f"a STALE store was audited as current, rc {rc}:\n{capsys.readouterr().out}"


def test_gt6_cross_tool_refuses_a_stale_store(tmp_path, monkeypatch, capsys):
    ct = import_gate("cross_tool", module_level=False)
    from x4validate import _compat, _effective
    vp = "assets/x_macro.xml"
    db = _store(tmp_path / "e.sqlite", [("m", vp, "hull.max", "200", "modA")])
    c = _compat.Collision(vpath=vp, kind="HARD", target="/macros/macro[@name='m']/properties/hull/@max",
                          mods=["modB", "modA"], winner="modA")
    monkeypatch.setattr(ct, "failures", [])
    monkeypatch.setattr(ct._env, "effective_db", lambda: db)
    monkeypatch.setattr(ct._env, "extensions", lambda: tmp_path)
    monkeypatch.setattr(ct._merge, "Config", lambda *a, **k: None)
    monkeypatch.setattr(ct._compat, "analyze", lambda *a, **k: types.SimpleNamespace(collisions=[c]))
    monkeypatch.setattr(_effective, "store_freshness", lambda con, config=None: types.SimpleNamespace(
        fresh=False, determinable=True, reasons=["content axis moved"],
        banner=lambda *a, **k: "STALE"))
    ct.check_cross_tool_agreement()
    out = capsys.readouterr().out
    assert ct.failures or "stale" in out.lower(), f"scored against a STALE store as if current:\n{out}"


@pytest.mark.parametrize("tol", ["inf", "-1"])
def test_gt6_claims_audit_rejects_a_meaningless_tolerance(tmp_path, monkeypatch, tol):
    ca = import_gate("claims_audit", module_level=False)
    tsv = tmp_path / "CLAIMS.tsv"
    tsv.write_text("\t".join(["macro", "m", "hull.max", "100", tol, "doc.md:1", "effective"]) + "\n",
                   encoding="utf-8")
    monkeypatch.setattr(ca, "_claims", lambda: tsv)
    [row] = list(ca.rows())
    assert row[-1] is not None, f"tolerance {tol!r} parsed as {row[5]!r} with no error"


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 GT-6: claude_md_budget never lowers its floor, "
                   "so shrink-then-regrow is invisible (a ceiling, not a ratchet)")
def test_gt6_claude_md_budget_ratchet_tightens(tmp_path, monkeypatch, capsys):
    cmb = import_gate("claude_md_budget", module_level=False)
    md = tmp_path / "CLAUDE.md"
    base = tmp_path / "baseline.json"
    base.write_bytes(json.dumps({"_counting": cmb.COUNTING, "shipped": 1000}).encode("utf-8"))
    monkeypatch.setattr(cmb, "BASELINE", base)
    monkeypatch.setattr(cmb, "budget_files", lambda: [("shipped", md)])
    md.write_bytes(b"x" * 900)
    assert cmb.main() == 0
    md.write_bytes(b"x" * 950)                              # +50 over what the file just was
    rc = cmb.main()
    assert rc == 1, (f"the file shrank to 900 and grew back to 950 with rc {rc}; the floor "
                     f"stayed at 1000\n{capsys.readouterr().err}")

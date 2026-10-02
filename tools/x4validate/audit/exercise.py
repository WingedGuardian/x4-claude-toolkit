"""Real-data and controlled CLI exercises for the October tool audit.

Predictions are stated in check() rows. Unexpected results are preserved, never
converted into passing tests. No tool implementation is patched by this harness.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import gzip
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

import driver as D


def check(name, expected, actual):
    row = dict(check=name, expected=expected, actual=actual, okay=expected == actual)
    with (D.OUT / "assertions.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{'MATCH' if row['okay'] else 'DISCREPANCY'} {name}: expected={expected!r}, actual={actual!r}", flush=True)
    if not row["okay"]:
        D.ISSUES.append(name)
    return row["okay"]


def fixtures():
    from lxml import etree
    env = D.environment(False)
    f = D.OUT / "fixture"
    ref = f / "reference"
    ext = f / "game/extensions"
    profile = f / "profile.xml"
    D.write(profile, "<content/>")
    env["X4_PROFILE_CONTENT"] = str(profile)
    env["X4_EFFECTIVE_DB"] = str(f / "effective.sqlite")
    env["X4_REGISTRY"] = str(f / "modlist.yaml")
    D.write(f / "modlist.yaml", "meta: {}\nmods: []\n")
    D.write(ref / "libraries/wares.xml", '<wares><ware id="ore" name="Ore" group="solid" volume="1"><price min="5" average="10" max="15"/></ware></wares>')
    D.write(ref / "md/base.xml", '<mdscript name="Audit"><cues><cue name="AuditCue"><conditions><event_player_ejected/></conditions><actions><find_station name="$s"/><signal_cue cue="AuditCue"/></actions></cue></cues></mdscript>')
    D.write(ref / "assets/ship_macro.xml", '<macros><macro name="audit_ship_macro" class="ship_s"><properties><hull max="1000"/><people capacity="2"/><storage unit="volume" capacity="10"/><purpose primary="fight"/><physics mass="100"/></properties></macro></macros>')
    D.write(ref / "index/macros.xml", '<index><entry name="audit_ship_macro" value="assets/ship_macro"/></index>')
    for folder, payload, enabled in [
        ("aaa_first", '<diff><replace sel="/wares/ware[@id=\'ore\']/price/@average">20</replace><add sel="/wares"><ware id="audit_new" name="New" group="solid" volume="1"><price min="40" average="50" max="60"/></ware></add></diff>', True),
        ("bbb_last", '<diff><replace sel="/wares/ware[@id=\'ore\']/price/@average">30</replace></diff>', True),
        ("ccc_disabled", '<diff><replace sel="/wares/ware[@id=\'ore\']/price/@average">999</replace></diff>', False),
    ]:
        D.write(ext / folder / "content.xml", f'<content id="{folder}" name="Audit {folder}" version="1" save="false" enabled="{str(enabled).lower()}"/>')
        D.write(ext / folder / "libraries/wares.xml", payload)
    good = ext / "aaa_first"
    D.inside(good / "assets/units/audit/macros/audit_clone_macro.xml").unlink(missing_ok=True)
    bad = f / "bad patch Ω"
    D.write(bad / "content.xml", '<content id="audit_bad" name="Audit bad" version="1"/>')
    D.write(bad / "libraries/wares.xml", '<diff><replace sel="/wares/ware[@id=\'missing\']/@name">bad</replace></diff>')
    r = D.cli("x4validate", [good, "--json"], "fixture-validator-good", env=env, expect=(0,3))
    data = json.loads(r["stdout"])
    check("valid diff has no selector errors", [], [x["sel"] for x in data["findings"] if x["severity"] == "error" and x["category"] == "sel"])
    r = D.cli("x4validate", [bad, "--json"], "fixture-validator-bad", (1,), env=env)
    check("missing selector is caught", True, any(x["severity"] == "error" and x["category"] == "sel" for x in json.loads(r["stdout"])["findings"]))
    D.cli("x4validate", [good, "--sel-only", "--update"], "fixture-requested-check-not-run", (3,), env=env)
    D.cli("x4validate", [good, "--file", good / "libraries/wares.xml", "--json"], "fixture-file-mode", env=env)
    D.cli("x4validate", [good, "--entity", "ware:audit_new", "--like", "ware:ore"], "fixture-completeness", (0,1,3), env=env)
    r = D.cli("x4effective", ["dump", "libraries/wares.xml"], "fixture-effective-dump", env=env)
    tree = etree.fromstring(r["stdout"].encode())
    check("effective winner ignores disabled mod", "30", tree.xpath("string(/wares/ware[@id='ore']/price/@average)"))
    check("earlier mod's added ware survives", "50", tree.xpath("string(/wares/ware[@id='audit_new']/price/@average)"))
    D.cli("x4effective", ["build", "--kinds", "ware,macro"], "fixture-store-build", env=env)
    for cmd in (["ls", "ware", "--limit", "1"], ["show", "ware", "ore"], ["attr", "ware", "price.average"], ["who-sets", "ware", "ore"], ["diff-mod", "bbb_last"], ["coverage"]):
        D.cli("x4effective", cmd, "fixture-effective-"+cmd[0], env=env)
    D.cli("x4effective", ["sql", "SELECT COUNT(*) FROM entities"], "fixture-sql-read", env=env)
    before = (f / "effective.sqlite").read_bytes()
    D.cli("x4effective", ["sql", "WITH x AS (SELECT 1) DELETE FROM entities"], "fixture-sql-write-refused", (1,2), env=env)
    check("read-only SQL left store bytes intact", True, before == (f / "effective.sqlite").read_bytes())
    r = D.cli("x4compat", ["check", "--json"], "fixture-collision", (1,), env=env)
    check("collision identifies both writers", True, "aaa_first" in r["stdout"] and "bbb_last" in r["stdout"])
    check("disabled writer excluded from collisions", False, "ccc_disabled" in r["stdout"])
    D.cli("x4stats", ["wares", good], "fixture-stats-wares", env=env)
    r = D.cli("x4stats", ["macro", ref / "assets/ship_macro.xml"], "fixture-stats-macro", env=env)
    check("numeric hull equals source XML", True, "hull.max = 1000" in r["stdout"])
    D.cli("x4similar", ["--threshold", "-1"], "fixture-similar-invalid-threshold", (2,), env=env)
    D.cli("x4similar", ["--candidate", good], "fixture-similar-no-ships", (2,), env=env)
    ship_xml = '<macros><macro name="audit_ship_macro" class="ship_s"><properties><hull max="1000"/><people capacity="2"/><storage missile="10" unit="4"/><purpose primary="fight"/><secrecy level="1"/></properties></macro></macros>'
    D.write(ref / "assets/units/audit/macros/audit_ship_macro.xml", ship_xml)
    D.write(good / "assets/units/audit/macros/audit_clone_macro.xml", ship_xml.replace('name="audit_ship_macro"', 'name="audit_clone_macro"').replace('max="1000"', 'max="1020"'))
    r = D.cli("x4similar", ["--candidate", good], "fixture-similar-positive", env=env)
    check("similarity identifies controlled near clone", True, "audit_clone_macro" in r["stdout"] and "audit_ship_macro" in r["stdout"])
    tsv = f / "xref.tsv"
    D.cli("x4xref", ["build", "--out", tsv], "fixture-xref-build", env=env)
    for cmd, name in [("who-calls", "find_station"), ("who-listens", "event_player_ejected"), ("cue", "AuditCue")]:
        r = D.cli("x4xref", [cmd, name, "--tsv", tsv], "fixture-xref-"+cmd, env=env)
        check("xref exact fixture "+cmd, True, "md/base.xml" in r["stdout"])
    truncated = f / "truncated-xref.tsv"
    lines = tsv.read_text(encoding="utf-8").splitlines()
    D.write(truncated, "\n".join(line.rstrip("\t") if "\tfind_station\t" in line else line for line in lines) + "\n")
    shutil.copyfile(str(tsv) + ".freshness.json", D.inside(Path(str(truncated) + ".freshness.json")))
    D.cli("x4xref", ["who-calls", "find_station", "--tsv", truncated], "fixture-truncated-xref-false-zero", (2,), env=env)
    newer = f / "newer"
    shutil.copytree(good, D.inside(newer), dirs_exist_ok=True)
    p = newer / "libraries/wares.xml"
    D.write(p, p.read_text(encoding="utf-8").replace(">20<", ">25<"))
    r = D.cli("x4diff", [good, newer, "--detail"], "fixture-semantic-diff", env=env)
    check("one text change is counted", True, "total attr changes: 1" in r["stdout"])
    D.cli("x4diff", [good, good], "fixture-noop-diff", env=env)
    D.cli("x4diff", [good, newer, "--base", good], "fixture-threeway-diff", env=env)
    for cmd in (["ingest", "--installed-only"], ["dashboard"], ["needs-review"], ["verify"], ["snapshot", "--label", "audit"]):
        D.cli("x4modlist", cmd, "fixture-registry-"+cmd[0], (0,1), env=env)
    for cmd in (["mark", "aaa_first"], ["source", "aaa_first", "local"], ["ignore", "ccc_disabled", "--reason", "audit fixture"]):
        D.cli("x4modlist", cmd, "fixture-registry-"+cmd[0], env=env)
    D.cli("x4modlist", ["resolve", "aaa_first", "none"], "fixture-registry-resolve-offline", env=env)
    D.cli("x4modlist", ["refresh", "--ids", "__missing__"], "fixture-refresh-no-matching-id", env=env)
    # Minimal valid gzip save and a gzip with an invalid DEFLATE block.
    save = f / "valid-save.xml.gz"
    D.inside(save).write_bytes(gzip.compress(b'<savegame><info><game version="900"/><patches><patch extension="audit" version="1"/></patches></info><component macro="audit_ship_macro"/><component macro="missing_macro"/><connection macro="not_a_macro"/></savegame>'))
    D.cli("x4save", ["info", save], "fixture-save-info", env=env)
    r = D.cli("x4save", ["check", save], "fixture-save-check", (1,), env=env)
    check("save checks two real macro references", True, "2 distinct macro references" in r["stdout"])
    check("save reports only actual missing macro", True, "missing_macro" in r["stdout"] and "not_a_macro" not in r["stdout"])
    broken = f / "invalid-deflate.xml.gz"
    D.inside(broken).write_bytes(bytes.fromhex("1f8b0800000000000003070000000000000000"))
    D.cli("x4save", ["info", broken], "fixture-save-invalid-deflate-info", (2,), env=env)
    D.cli("x4save", ["check", broken], "fixture-save-invalid-deflate-check", (2,), env=env)
    invaliddb = f / "not-sqlite.db"
    D.write(invaliddb, "not a sqlite database")
    D.cli("x4effective", ["--db", invaliddb, "ls", "ware"], "fixture-corrupt-effective-store", (2,), env=env)
    invalidtsv = f / "invalid-xref.tsv"
    D.write(invalidtsv, "kind\tname\tsource\tfile\tcue\tline\ttarget\naction\tfind_station\tbase\tmd/base.xml\tAuditCue\tnot-an-integer\t\n")
    D.cli("x4xref", ["who-calls", "find_station", "--tsv", invalidtsv], "fixture-corrupt-xref-index", (2,), env=env)
    log = f / "debug-errors.txt"
    D.write(log, "[=ERROR=] 1.00 Cannot find macro 'missing_macro'\n[=ERROR=] 2.00 audit unknown error shape\n")
    r = D.cli("x4debug", ["triage", log], "fixture-debug-triage", env=env)
    check("debug triage retains unclassified error", True, "unclassified" in r["stdout"].lower())
    D.cli("x4debug", ["crosscheck", good, log, "--tier", "a"], "fixture-debug-no-comparison-refused", (2,), env=env)
    D.cli("x4debug", ["baseline", log, "--dest", f / "archived-logs"], "fixture-debug-baseline", env=env)
    stub = f / "uidata.xml"
    D.write(stub, '<uidata version="1"/>')
    D.cli("x4live", ["--file", stub, "dump"], "fixture-live-stub-refused", (2,), env=env)


def corpus():
    audit_env = D.environment()
    os.environ.clear()
    os.environ.update(audit_env)
    sys.path.insert(0, str(D.PKG))
    from x4validate import _check, _merge, _registry
    # Independent folder census supplements, rather than merely trusts, registry enumeration.
    folders = sorted(p for p in (D.GAME / "extensions").iterdir()
                     if p.is_dir() and not p.name.lower().startswith("ego_dlc_") and (p / "content.xml").is_file())
    installed = _registry.mods("installed")
    active = _registry.mods("active")
    D.write(D.OUT / "population.json", json.dumps(dict(folders=[p.name for p in folders],
        installed=[dict(m) for m in installed], active=[dict(m) for m in active],
        exclusions=getattr(active, "not_loaded", [])), default=str, indent=2))
    cfg = _merge.Config()
    ledger = D.OUT / "corpus.jsonl"
    with ledger.open("w", encoding="utf-8") as stream:
        for i, mod in enumerate(folders, 1):
            for mode, kwargs in [("ordinary-a", {}), ("update-b", dict(update=True, tier="b"))]:
                t0 = time.monotonic()
                try:
                    report = _check.validate(mod, cfg, **kwargs)
                    row = dict(mod=mod.name, mode=mode, seconds=round(time.monotonic()-t0,3),
                               errors=len(report.errors), degraded=bool(report.degraded), report=asdict(report))
                except Exception as exc:
                    row = dict(mod=mod.name, mode=mode, seconds=round(time.monotonic()-t0,3),
                               crash=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                print(f"CORPUS {i}/{len(folders)} {mod.name} {mode}: {row.get('crash') or str(row.get('errors'))+' errors; degraded='+str(row.get('degraded'))} ({row['seconds']}s)", flush=True)


def real():
    audit_env = D.environment()
    os.environ.clear()
    os.environ.update(audit_env)
    sys.path.insert(0, str(D.PKG))
    from lxml import etree
    from x4validate import _registry
    mods = _registry.mods("installed")
    # Select content owners from this measured inventory; folders chosen by content.
    candidates = [Path(m["path"]) for m in mods if not str(m["folder"]).lower().startswith("ego_dlc_")]
    patcher = next(p for p in candidates if (p / "libraries/wares.xml").is_file())
    D.cli("x4effective", ["build"], "real-effective-build", timeout=1800)
    for cmd in (["ls", "ware", "--limit", "5"], ["show", "ware", "ore"], ["attr", "macro", "hull.max", "--limit", "5"], ["who-sets", "ware", "ore"], ["coverage"], ["sql", "SELECT kind,COUNT(*) FROM entities GROUP BY kind"]):
        D.cli("x4effective", cmd, "real-effective-"+cmd[0], (0,1,3))
    D.cli("x4effective", ["dump", "libraries/wares.xml", "--chain"], "real-effective-dump")
    D.cli("x4effective", ["diff-mod", patcher.name, "--limit", "5"], "real-effective-diffmod", (0,2))
    D.cli("x4compat", ["check", "--json", "--soft"], "real-collision-json", (0,1,3), timeout=1800)
    tsv = D.OUT / "registry/md_xref.tsv"
    D.cli("x4xref", ["build", "--out", tsv], "real-xref-build", timeout=900)
    for cmd, name in [("who-calls", "find_station"), ("who-listens", "event_player_ejected"), ("cue", "Init")]:
        D.cli("x4xref", [cmd, name, "--tsv", tsv], "real-xref-"+cmd)
    # Independent parsed XML check of one indexed vanilla action, ignoring comments.
    import csv
    with tsv.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    indexed = Counter((r["file"], int(r["line"])) for r in rows
                      if r["source"] == "base" and r["kind"] == "action" and r["name"] == "find_station")
    direct = Counter()
    for prefix in ("md", "aiscripts"):
        for p in (D.MODDING / "reference" / prefix).glob("*.xml"):
            tree = etree.parse(str(p))
            for node in tree.iter("find_station"):
                direct[(p.relative_to(D.MODDING / "reference").as_posix(), node.sourceline)] += 1
    check("xref vanilla find_station locations equal independent XML parse", sorted(direct.items()), sorted(indexed.items()))
    D.cli("x4stats", ["wares", patcher], "real-stats-wares", (0,1,3))
    macro = next((D.MODDING / "reference/assets").rglob("ship_arg_s_scout_01_a_macro.xml"))
    r = D.cli("x4stats", ["macro", macro], "real-stats-macro")
    expected = etree.parse(str(macro)).xpath("string(/macros/macro/properties/hull/@max)")
    check("real hull matches independent XML read", float(expected), float(next(s.split("=",1)[1] for s in r["stdout"].splitlines() if "hull.max =" in s)))
    ship_owner = next((p for p in candidates if (p / "assets/units").is_dir() and any((p / "assets/units").rglob("*_macro.xml"))), None)
    if ship_owner:
        D.cli("x4similar", ["--candidate", ship_owner], "real-similar-candidate", timeout=900)
    D.cli("x4modlist", ["ingest"], "real-registry-ingest-copy", (0,1))
    for cmd in (["verify"], ["needs-review"], ["dashboard"], ["snapshot", "--label", "audit"], ["changed"]):
        D.cli("x4modlist", cmd, "real-registry-"+cmd[0], (0,1,3))
    dev = D.MODDING / "dev"
    pair = next((p, dev / p.name) for p in candidates if (dev / p.name / "content.xml").is_file())
    D.cli("x4diff", [*pair, "--detail"], "real-deployed-vs-dev-diff", (0,1,3))
    D.cli("x4debug", ["triage"], "real-debug-triage", (0,2))
    D.cli("x4debug", ["crosscheck", patcher], "real-debug-crosscheck", (0,1,2,3,4))
    D.cli("x4debug", ["baseline", "--dest", D.OUT / "debug-baseline"], "real-debug-baseline", (0,2,3))
    saves = sorted((D.PROFILE / "save").glob("*.xml.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    if saves:
        D.cli("x4save", ["info", saves[0]], "real-save-info")
        D.cli("x4save", ["check", saves[0], "--limit", "5"], "real-save-check", (0,1,3), timeout=900)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["fixtures", "corpus", "real"])
    args = p.parse_args()
    globals()[args.mode]()
    raise SystemExit(bool(D.ISSUES))

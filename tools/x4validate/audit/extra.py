"""Additional isolated BaseX/archive exercises; see audit report for limitations."""
import argparse
import os
import shutil
import time
from pathlib import Path
import driver as D
from exercise import check


def basex():
    for db in ("x4raw", "x4eff"):
        for label, args, expect in [
            ("positive", ["refs", "ore"], (0, 3)),
            ("missing", ["refs", "__audit_absent_identifier_20261001__"], (0, 3, 4)),
            ("attribute", ["attr", "name"], (0, 3)),
            ("attribute-expression", ["attr", "name[false()]"], (2, 4)),
            ("scoped-zero", ["xq", f"collection('{db}')[1]//__audit_absent__"], (4,)),
            ("boolean-zero", ["xq", f"exists(collection('{db}')//__audit_absent__)"], (4,)),
            ("foreign", ["xq", "collection('x4eff' )//ware" if db == "x4raw" else "collection('x4raw')//ware"], (2,)),
        ]:
            r = D.run(f"basex-{db}-{label}", [D.PYTHON, D.BASEX / "ask.py", *args, "--db", db], expect, cwd=D.BASEX)
            if label == "positive":
                check(db + " finds known ore reference", True, "<ware>" in r["stdout"])


def basex_fixture():
    root = D.OUT / "basex-fixture"
    root.mkdir(exist_ok=True)
    for p in D.BASEX.iterdir():
        if p.is_file() and p.suffix in (".py", ".sh"):
            shutil.copyfile(p, D.inside(root / p.name))
    bx = root / "basex"
    bx.mkdir(exist_ok=True)
    for name in ("BaseX.jar", ".basexhome"):
        shutil.copyfile(D.BASEX / "basex" / name, D.inside(bx / name))
    for name in ("data", "repo", "webapp"):
        (bx / name).mkdir(exist_ok=True)
    D.write(bx / ".basex", f"DBPATH = {(bx / 'data').as_posix()}\nREPOPATH = {(bx / 'repo').as_posix()}\nWEBPATH = {(bx / 'webapp').as_posix()}\n")
    env = D.environment(False)
    env["X4_PROFILE_CONTENT"] = str(D.OUT / "fixture/profile.xml")
    env.pop("MSYS_NO_PATHCONV", None)
    env.pop("MSYS2_ARG_CONV_EXCL", None)
    D.run("basex-fixture-build", [D.BASH, root / "build-corpus.sh"], cwd=root, env=env, timeout=300)
    for label, mode, arg, expect in [
        ("positive", "attr", "name", (0,)),
        ("invalid-attribute", "attr", "name[false()]", (2,4)),
        ("cue-positive", "xq", "collection('x4raw')//cue[@name='AuditCue']", (0,)),
        ("positional-if", "xq", "collection('x4raw')[if (true()) then 1 else 2]//cue[@name='AuditCue']", (4,)),
        ("positional-simple", "xq", "collection('x4raw')[1]//__audit_absent__", (4,)),
        ("missing", "refs", "__audit_absent_identifier__", (0,)),
    ]:
        D.run("basex-fixture-" + label, [D.PYTHON, root / "ask.py", mode, arg, "--db", "x4raw"], expect, cwd=root, env=env)


def archives():
    original = D.MODDING / "tools/x4cat-spike"
    copied = D.OUT / "x4cat"
    if not copied.exists():
        shutil.copytree(original, D.inside(copied), ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache", "*.db", "*.sqlite"))
    if not (copied / "templates/extension_poc").is_dir():
        raise RuntimeError("Local template directory absent; refuse the old tool's network fallback during this offline audit")
    env = D.environment()
    env["PYTHONPATH"] = str(copied)
    D.run("x4cat-tests", [D.PYTHON, "-m", "pytest", "tests", "-q", "--tb=short", "--basetemp", D.OUT / "x4cat-pytest"], env=env, cwd=copied)
    D.run("x4cat-help", [D.PYTHON, "-m", "x4_catalog", "--help"], env=env, cwd=copied)
    exe = D.MODDING / "tools/XTools_1.11/XRCatTool.exe"
    D.run("xrcat-help", [exe, "-help"], (0,1), env=env, cwd=D.OUT)
    source = D.OUT / "archive-input"
    D.write(source / "libraries/audit.xml", '<audit><node value="42"/></audit>')
    cat = D.OUT / "roundtrip.cat"
    D.run("xrcat-pack", [exe, "-in", source, "-out", cat], env=env, cwd=D.OUT)
    dest = D.OUT / "archive-extracted"
    dest.mkdir(exist_ok=True)
    D.run("xrcat-unpack", [exe, "-in", cat, "-out", dest], env=env, cwd=D.OUT)
    check("official archive pack/unpack byte roundtrip", (source / "libraries/audit.xml").read_bytes().decode(), (dest / "libraries/audit.xml").read_bytes().decode())
    D.run("x4cat-real-list", [D.PYTHON, "-m", "x4_catalog", "list", D.GAME, "--glob", "libraries/wares.xml"], env=env, cwd=copied)
    catalog_dir = D.OUT / "catalog-extension"
    catalog_dir.mkdir(exist_ok=True)
    for suffix in (".cat", ".dat"):
        shutil.copyfile(cat.with_suffix(suffix), D.inside(catalog_dir / ("ext_01" + suffix)))
    r = D.run("x4cat-cross-reader", [D.PYTHON, "-m", "x4_catalog", "list", catalog_dir, "--prefix", "ext_", "--glob", "libraries/audit.xml"], env=env, cwd=copied)
    check("homegrown reader sees official packed XML", True, "libraries/audit.xml" in r["stdout"])
    target = D.OUT / ("empty-template-mod-" + str(time.time_ns()))
    if not target.exists():
        D.run("x4cat-init-empty-template", [D.PYTHON, "-m", "x4_catalog", "init", "audit_empty_template", "-o", target], (1,2), env=env, cwd=copied)
        check("scaffold success requires content.xml", True, (target / "content.xml").is_file())


def old_index():
    copied = D.OUT / "x4cat"
    env = D.environment()
    env["PYTHONPATH"] = str(copied)
    game = D.OUT / "old-index-game"
    game.mkdir(exist_ok=True)
    db = D.OUT / "old-index.sqlite"
    def cli(label, args):
        return D.run(label, [D.PYTHON, "-m", "x4_catalog", *args], env=env, cwd=copied)
    cli("x4cat-pack-fixture", ["pack", D.OUT / "fixture/reference", "-o", game / "01.cat"])
    cli("x4cat-index-fixture", ["index", game, "-o", db, "--refresh"])
    for cmd, name in (("search", "ore"), ("inspect", "ore"), ("inspect", "audit_ship_macro")):
        r = cli("x4cat-index-" + cmd + "-" + name, ["--db", db, cmd, name])
        expected = {("search", "ore"): "ware        ore  — solid avg:10", ("inspect", "ore"): "Price: 5 / 10 / 15", ("inspect", "audit_ship_macro"): "Macro: assets/ship_macro.xml"}[(cmd, name)]
        check("old indexed " + cmd + " " + name, True, expected in r["stdout"])
        if name == "audit_ship_macro":
            check("old indexed macro numeric hull", True, "hull.max: 1000" in r["stdout"])
    extracted = D.OUT / "old-macro-extracted"
    cli("x4cat-extract-indexed-macro", ["--db", db, "extract-macro", "audit_ship_macro", "-o", extracted])
    check("old indexed extraction bytes equal source", True, (extracted / "assets/ship_macro.xml").read_bytes() == (D.OUT / "fixture/reference/assets/ship_macro.xml").read_bytes())


def load_controls():
    from lxml import etree
    env = D.environment(False)
    env["X4_PROFILE_CONTENT"] = str(D.OUT / "fixture/profile.xml")
    root = D.OUT / "load-controls"
    game = root / "game"
    ext = game / "extensions"
    for name, value in (("aaa_dependent", "20"), ("bbb_required", "30")):
        dependency = '<dependency id="bbb_required" version="1"/>' if name == "aaa_dependent" else ""
        D.write(ext / name / "content.xml", f'<content id="{name}" version="1" enabled="true">{dependency}</content>')
        D.write(ext / name / "libraries/wares.xml", f'<diff><replace sel="/wares/ware[@id=\'ore\']/price/@average">{value}</replace></diff>')
    env["X4_GAME"], env["X4_EXTENSIONS"] = str(game), str(ext)
    r = D.cli("x4effective", ["dump", "libraries/wares.xml"], "fixture-dependency-winner", env=env)
    check("dependency overrides alphabetical precedence", "20", etree.fromstring(r["stdout"].encode()).xpath("string(/wares/ware[@id='ore']/price/@average)"))
    packed = root / "packed-game/extensions/audit_packed"
    D.write(packed / "content.xml", '<content id="audit_packed" version="1" enabled="true"/>')
    inputs = root / "packed-input"
    D.write(inputs / "libraries/wares.xml", '<diff><replace sel="/wares/ware[@id=\'ore\']/price/@average">35</replace></diff>')
    exe = D.MODDING / "tools/XTools_1.11/XRCatTool.exe"
    D.run("fixture-official-packed-overlay", [exe, "-in", inputs, "-out", packed / "ext_01.cat"], env=env, cwd=root)
    env["X4_GAME"], env["X4_EXTENSIONS"] = str(root / "packed-game"), str(packed.parent)
    r = D.cli("x4validate", [packed, "--json"], "fixture-packed-validator", env=env)
    import json
    report = json.loads(r["stdout"])
    check("validator counted packed diff and payload", True, "sel-resolution: 1 diff file(s) checked across 1 payload XML file(s)" in report["notes"] and report["error_count"] == 0)
    r = D.cli("x4effective", ["dump", "libraries/wares.xml"], "fixture-packed-effective", env=env)
    check("effective merger reads official packed diff", "35", etree.fromstring(r["stdout"].encode()).xpath("string(/wares/ware[@id='ore']/price/@average)"))
    D.write(inputs / "libraries/wares.xml", '<diff><replace sel="/wares/ware[@id=\'missing\']/price/@average">35</replace></diff>')
    D.run("fixture-official-packed-invalid-overlay", [exe, "-in", inputs, "-out", packed / "ext_01.cat"], env=env, cwd=root)
    r = D.cli("x4validate", [packed, "--json"], "fixture-packed-invalid-validator", (1,), env=env)
    check("validator catches bad selector from packed archive", True, any(x["category"] == "sel" and x["severity"] == "error" for x in json.loads(r["stdout"])["findings"]))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("basex", "archives", "basex_fixture", "old_index", "load_controls"))
    globals()[p.parse_args().mode]()
    raise SystemExit(bool(D.ISSUES))

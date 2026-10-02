"""Aggregate measured audit evidence without treating expected codes as proof."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import driver as D


def protected(name):
    roots = [D.GAME / "extensions", D.MODDING / "reference", D.PROFILE / "save",
             D.PROFILE / "extensions", D.SOURCE / "tools/basex/basex",
             D.GAME.parent.parent / "workshop/content/392160"]
    rows = {}
    for root in roots:
        if root.is_dir():
            for p in root.rglob("*"):
                if p.is_file():
                    s = p.stat()
                    rows[str(p)] = [s.st_size, s.st_mtime_ns]
    for p in list(D.GAME.glob("*.cat")) + list(D.GAME.glob("*.dat")) + list((D.MODDING / "dev/_registry").glob("*")) + list(D.PROFILE.glob("*")):
        if p.is_file():
            s = p.stat()
            rows[str(p)] = [s.st_size, s.st_mtime_ns]
    D.write(D.OUT / ("protected-" + name + ".json"), json.dumps(rows, indent=2))
    print(name, len(rows), "protected metadata records")


def summary():
    changed = subprocess.check_output(['git', 'diff', '--name-only', 'aa57efc', '--',
        'tools/basex/ask.py', 'tools/basex/content_query.py',
        'tools/x4validate/x4validate'], cwd=D.LANE, text=True).strip()
    if changed:
        raise SystemExit('Historical summary requires the audited tool implementation '
                         '(aa57efc). Use fix_verify.py after for repair verification; '
                         'the hardcoded baseline defect/suite labels do not describe fixes.')
    before = json.loads((D.OUT / "snapshot-before.json").read_text())
    after = json.loads((D.OUT / "snapshot-after.json").read_text())
    differences = {kind: sorted(k for k in set(before[kind]) | set(after[kind]) if before[kind].get(k) != after[kind].get(k)) for kind in before}
    corpus = [json.loads(line) for line in (D.OUT / "corpus.jsonl").read_text(encoding="utf-8").splitlines()]
    population = json.loads((D.OUT / "population.json").read_text())
    measured = Counter((r["mod"], r["mode"]) for r in corpus)
    missing = [(mod, mode) for mod in population["folders"] for mode in ("ordinary-a", "update-b") if measured[(mod, mode)] != 1]
    logs = [json.loads(p.read_text(encoding="utf-8")) for p in (D.OUT / "logs").glob("*.json")]
    assertions = {}
    for line in (D.OUT / "assertions.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        assertions[r["check"]] = r
    value = dict(tool_implementation_changed=False, confirmed_open_defects=8,
                 snapshot_differences=differences,
                 corpus=dict(folders_expected=len(population["folders"]), records=len(corpus), missing_or_duplicated=missing,
                             crashes=[r for r in corpus if "crash" in r],
                             per_mode={mode: dict(records=sum(r["mode"] == mode for r in corpus),
                                 mods_with_errors=sum(r["mode"] == mode and r.get("errors", 0) > 0 for r in corpus),
                                 errors=sum(r.get("errors", 0) for r in corpus if r["mode"] == mode),
                                 degraded=sum(r["mode"] == mode and r.get("degraded", False) for r in corpus)) for mode in ("ordinary-a", "update-b")}),
                 latest_command_records=len(logs), exit_agreements=sum(r["okay"] for r in logs),
                 latest_assertions=list(assertions.values()),
                 suite="2840 passed, 49 skipped; five installer-related files excluded",
                 older_suite="248 passed, 21 failed, 8 skipped: nineteen empty-template failures, two Windows symlink privilege failures",
                 limitations=["Accepted command exits are not independent functional proof", "Initial safety snapshots have bounded coverage", "No engine or Nexus E2E", "Implementation fixes were not authorized in audit-first scope"],
                 auxiliary_hash_collection="At final summary time; not a pre-run fingerprint",
                 auxiliary_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (D.MODDING / "dev/_tools/deploy.py", D.OUT / "x4cat/x4_catalog/_init.py")})
    pb, pa = D.OUT / "protected-before-final.json", D.OUT / "protected-after-final.json"
    if pb.exists() and pa.exists():
        a, b = json.loads(pb.read_text()), json.loads(pa.read_text())
        value["final_protected_metadata_count"] = len(a)
        value["final_protected_metadata_differences"] = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    D.write(D.OUT / "final-summary.json", json.dumps(value, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in value.items() if k in ("corpus", "snapshot_differences", "latest_command_records", "final_protected_metadata_count", "final_protected_metadata_differences")}, indent=2))
    if missing or value["corpus"]["crashes"] or any(differences.values()) or value.get("final_protected_metadata_differences"):
        raise SystemExit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        protected(sys.argv[1])
    else:
        summary()

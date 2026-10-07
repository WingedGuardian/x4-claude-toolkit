"""A faster runner must preserve individual outcomes and isolate mutation bytes."""
import importlib.util
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from _layout import require_repo
require_repo("scripts/verify-hook-tests.py", module_level=True, why="parallel mutation runner source")

ROOT=Path(__file__).resolve().parents[3]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod


batch=load("pytest_batches",ROOT/"tools/x4validate/scripts/run-pytest-batches.py")
vht=load("vht_parallel",ROOT/"scripts/verify-hook-tests.py")


def report(outcome="passed"):
    return {"fingerprint":"same","collected":["a"],"tests":{"a":{"call":{
            "outcome":outcome,"duration":1,"skip_reason":"","wasxfail":""}}}}


def test_comparison_is_per_item_and_ignores_only_duration():
    a=report();b=report();b["tests"]["a"]["call"]["duration"]=100
    assert batch.compare(a,b)==[]
    assert batch.compare(a,report("failed"))==["a"]
    b["tests"]["a"]["call"]["skip_reason"]="new exclusion"
    assert batch.compare(a,b)==["a"]


def test_comparison_refuses_changed_source_missing_or_duplicate_tests():
    for key,value in (("fingerprint","changed"),("collected",[]),("collected",["a","a"])):
        b=report();b[key]=value
        with pytest.raises(ValueError):batch.compare(report(),b)


def test_unreviewed_module_stays_exclusive_even_without_markers(tmp_path):
    p=tmp_path/"test_x.py";p.write_text("def test_x(): assert True\n",encoding="utf-8")
    r=batch.classify(p)
    assert r["mode"]=="exclusive" and not r["reviewed"]


def test_each_mutation_gets_its_own_directory_and_bytes(tmp_path,monkeypatch):
    (tmp_path/"hook_facts.py").write_text("pristine",encoding="utf-8")
    monkeypatch.setattr(vht,"HOOKS",tmp_path);monkeypatch.setattr(vht,"FILES",["hook_facts.py"])
    monkeypatch.setattr(vht,"wait_for_dispatch",lambda:None)
    seen=[]
    def run(work):
        seen.append((str(work),(work/"hook_facts.py").read_text(encoding="utf-8")))
        return 1,{"Target.test_x"},42
    monkeypatch.setattr(vht,"run",run)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(vht.evaluate_source,["A","B","C","D"]))
    assert len({p for p,_ in seen})==4
    assert {s for _,s in seen}=={"A","B","C","D"}
    assert (tmp_path/"hook_facts.py").read_text(encoding="utf-8")=="pristine"
    assert all(r["failed"]==["Target.test_x"] and r["ran"]==42 for r in rows)


def test_dispatch_refuses_stale_monitor(tmp_path,monkeypatch):
    p=tmp_path/"pressure.json";p.write_text(json.dumps({"updated":0,"blocked":False}),encoding="utf-8")
    monkeypatch.setenv("RB_PRESSURE_FILE",str(p))
    with pytest.raises(RuntimeError,match="stale"):vht.wait_for_dispatch()


def test_comparison_refuses_empty_and_tracks_collection_skips():
    empty={"fingerprint":"same","collected":[],"tests":{}}
    with pytest.raises(ValueError):batch.compare(empty,empty)
    a=report();b=report();b["collection_skips"]={"module":"dependency absent"}
    assert batch.compare(a,b)==["collection:module"]


def test_checkpoint_reuse_requires_every_evidence_file(tmp_path):
    from gate_support import evidence_digest, evidence_intact
    log=tmp_path/"log";log.write_text("passed")
    data=tmp_path/"report";data.write_text("details")
    row={"evidence":{"log":evidence_digest(log),"report":evidence_digest(data)}}
    assert evidence_intact(tmp_path,row)
    data.write_text("changed")
    assert not evidence_intact(tmp_path,row)
    assert not evidence_intact(tmp_path,{})


def test_reports_cannot_change_the_fingerprinted_tree(tmp_path):
    from gate_support import external_output
    with pytest.raises(ValueError):external_output(tmp_path/"reports",tmp_path)


def test_skip_ceiling_is_global_not_per_batch():
    tests={name:{"call":{"outcome":"skipped","wasxfail":""}} for name in ("a","b")}
    assert batch.skip_ceiling_errors(tests,{},"1")
    assert not batch.skip_ceiling_errors(tests,{},"2")
    assert batch.skip_ceiling_errors(tests,{"module":"missing"},"2")
    assert batch.skip_ceiling_errors(tests,{},"")

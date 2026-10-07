"""Pytest plugin: complete node inventory and all execution phases, no secret-bearing output."""
import json
import os
from pathlib import Path
import time

DATA={"collected":[],"tests":{},"collection_errors":[],"collection_skips":{},"started":time.time()}


def pytest_collection_finish(session):
    DATA["collected"]=[i.nodeid for i in session.items]


def pytest_collectreport(report):
    if report.failed:
        DATA["collection_errors"].append(report.nodeid)
    if report.skipped:
        DATA["collection_skips"][report.nodeid]=str(report.longrepr)


def pytest_runtest_logreport(report):
    DATA["tests"].setdefault(report.nodeid,{})[report.when]={
        "outcome":report.outcome,"duration":report.duration,
        "wasxfail":str(getattr(report,"wasxfail","")),
        "skip_reason":str(report.longrepr) if report.skipped else ""}


def pytest_sessionfinish(session, exitstatus):
    DATA.update(exit=int(exitstatus),seconds=time.time()-DATA["started"])
    path=os.environ.get("X4_BATCH_REPORT")
    if path:
        Path(path).write_bytes((json.dumps(DATA,indent=2)+"\n").encode("utf-8"))

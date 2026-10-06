"""scripts/verify-hook-tests.py's own lookups (FX-G5 / reviewer J2 item 8).

The silent? column credits a failing must-NOT-fire test to a predicate only when that TEST's
source names the predicate. Failures arrive qualified ("Class.method", FX-G3) and the target
index is qualified too, but the source table was keyed by the bare METHOD name, so two classes
sharing a method name pooled their sources: a red test in class B was credited with the
predicate class A's same-named test mentions.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("verify_hook_tests", ROOT / "scripts" / "verify-hook-tests.py")
vht = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vht)

SRC = '''
import unittest


class A(unittest.TestCase):
    KEYS = ("x",)

    def test_same(self):
        self.assertFalse(F("x")["rm_hits_game"])


class B(unittest.TestCase):
    def test_same(self):
        self.assertFalse(F("x")["writes_reference"])


def test_module_level():
    assert "git_add_all"
'''


def test_sources_are_keyed_by_the_QUALIFIED_name():
    srcs = vht.test_sources(SRC)
    assert vht.names_predicate(srcs["A.test_same"], "rm_hits_game")
    assert not vht.names_predicate(srcs["B.test_same"], "rm_hits_game")     # J2: was pooled
    assert vht.names_predicate(srcs["B.test_same"], "writes_reference")
    assert 'KEYS = ("x",)' in srcs["A.test_same"]                           # class attrs travel
    assert 'KEYS' not in srcs["B.test_same"]
    assert vht.names_predicate(srcs["test_module_level"], "git_add_all")


def test_a_failure_is_looked_up_by_the_name_failed_tests_reports():
    out = ("FAIL: test_same (__main__.B.test_same)\n"
           "ERROR: test_same (__main__.A)\n")
    failed = vht.failed_tests(out)
    assert failed == {"B.test_same", "A.test_same"}
    srcs = vht.test_sources(SRC)
    assert all(t in srcs for t in failed)
    # the column's own predicate: only A's test is ABOUT rm_hits_game
    assert vht.credited(failed, srcs, "rm_hits_game") == {"A.test_same"}
    assert vht.credited({"B.test_same"}, srcs, "rm_hits_game") == set()

"""The fuzzer's verdict map must cover every rule protect-bash.sh actually has.

It used to be two hand-written tuples and they had drifted. MEASURED 2026-09-01: the
hook maps 19 predicates, the tuples listed 14, so the fuzzer was blind to 5 rules (26%)
and mis-classified a 6th. A seed hitting an unmapped rule reads "already allow" and is
SKIPPED IN SILENCE -- which is how 2 of 12 seeds were dropped from every run, and why a
bypass in those five rules could never have been reported.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]


def _fz():
    spec = importlib.util.spec_from_file_location("fz_undertest", ROOT / "scripts" / "fuzz-guard.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["fz_undertest"] = m
    spec.loader.exec_module(m)
    return m


def _names(m):
    probe = m.load_facts(m.HOOKS / "hook_facts.py")
    return set(probe.facts({"tool_input": {"command": "true", "timeout": 0,
                                           "run_in_background": False}}, m.SYNTHETIC_ROOTS))


def test_every_rule_in_the_hook_carries_a_verdict():
    m = _fz()
    policy = m.policy_map(_names(m))
    assert len(policy) >= m.MIN_MAPPED_RULES, (
        "only %d rules parsed out of protect-bash.sh; the map is derived from that file "
        "and a short parse makes every seed read 'allow'" % len(policy))
    assert all(v in ("deny", "ask", "advise") for v in policy.values()), policy


def test_no_predicate_is_silently_unfuzzed():
    """Any fact hook_facts emits is either mapped to a verdict or is metadata. A new
    predicate that nobody wires into protect-bash.sh should be visible, not invisible."""
    m = _fz()
    names = _names(m)
    policy = m.policy_map(names)
    METADATA = {"command", "cwd", "timeout", "background"}
    unmapped = sorted(names - set(policy) - METADATA)
    assert not unmapped, (
        "these facts are computed but carry no verdict, so the fuzzer cannot test them "
        "and the hook does nothing with them: %s" % unmapped)


def test_the_map_refuses_rather_than_degrades(tmp_path, monkeypatch):
    """The branch that matters: an empty map would make every seed 'allow', every seed
    would be skipped as nothing-to-weaken, and the run would print 'no bypass found'
    over having exercised nothing at all."""
    m = _fz()
    names = _names(m)
    (tmp_path / "protect-bash.sh").write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
    monkeypatch.setattr(m, "HOOKS", tmp_path)
    assert len(m.policy_map(names)) < m.MIN_MAPPED_RULES

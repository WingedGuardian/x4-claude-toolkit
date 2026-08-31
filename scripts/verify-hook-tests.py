#!/usr/bin/env python3
"""Prove the hook tests can FAIL, and that every guard rule is probed in both directions.

    python scripts/verify-hook-tests.py

`test_hook_facts.py` passing tells you the code agrees with the tests. It does not tell
you the tests could ever have disagreed. This repository has shipped several guards that
were inert for entire releases while their suite was green, so a green result is only
evidence once the red result is reachable (CLAUDE.md "if you cannot make a check fail on
purpose, you have not verified anything").

Two passes, both on a COPY of the hooks -- never the working tree. A mutation gate that
edits real files makes them deliberately wrong for the duration, and a release port once
read a mutated file and shipped it.

  MUTATION  plant one specific defect; the NAMED test for it must go red. Requiring a
            named test, not merely "something failed", is what stops a mutation that
            breaks the import from counting as coverage for anything.

  COVERAGE  pin each predicate false -- a must-FIRE test must break; pin it true -- a
            must-NOT-fire test must break. This is how "every rule is probed both ways"
            becomes a measurement instead of a claim about the test file.

Exit 0 if both pass, 1 if either finds a hole, 2 if the baseline is not green (in which
case neither result means anything and no verdict is given).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOKS = REPO / ".claude" / "hooks"
FILES = ("hook_facts.py", "test_hook_facts.py")

# (label, exact source text, replacement, the test that MUST go red)
MUTANTS = [
    ("rg/ag recurse by default", '"rg": True, "ag": True, "ack": True',
     '"rg": False, "ag": False, "ack": False', "test_rg_is_recursive_BY_DEFAULT"),
    ("game-delete name backstop", 'or rm_named_game,\n        "rm_targets_reference"',
     'or False,\n        "rm_targets_reference"', "test_unconfigured_root_falls_back_to_the_NAME"),
    ("archive exclusion on the backstop", "and not ARCHIVE.search(res(p))", "and True",
     "test_an_archive_merely_NAMED_after_the_game_does_not_hit"),
    ("heredoc << must be OUTSIDE quotes",
     "if line[i] == chr(60) and line[i + 1] == chr(60) and not mask[i] and not mask[i + 1]:",
     "if line[i] == chr(60) and line[i + 1] == chr(60):",
     "test_marker_inside_quotes_does_NOT_open_a_skip"),
    ("the heredoc marker may itself be QUOTED", "        t = heredoc_marker(line)",
     "        t = heredoc_marker(blank_quoted(line))",
     "test_a_QUOTED_marker_still_opens_a_heredoc"),
    ("noclobber >| is a redirect", r'_REDIR = re.compile(r"(\d?)>(\|?)(>?)")',
     r'_REDIR = re.compile(r"(\d?)>()(>?)")', "test_noclobber_override_is_a_truncate"),
    ("cp/mv -t destination", 'if not quoted and t in ("-t", "--target-directory"):',
     "if False:", "test_dash_t_names_the_destination"),
    ("wrapper verbs are seen through", "if t in WRAPPERS:\n            continue",
     "if False:\n            continue", "test_sees_through_a_wrapper"),
    ("dot-segment canonicalisation", "s = posixpath.normpath(s)", "s = s",
     "test_dot_segment_is_canonicalised"),
    ("-e consumes its argument", 'if base in _ARG_FLAGS and "=" not in t:\n                skip = True',
     "if False:\n                skip = True",
     "test_dash_e_supplies_the_pattern_so_the_path_is_not_consumed"),
    ("tee writes EVERY file operand", 'return ops if v == "tee" else [ops[-1]]',
     "return [ops[-1]]", "test_tee_writes_EVERY_file_operand"),
    ("last assignment wins", "found[m.group(1)] = m.group(2)",
     "found.setdefault(m.group(1), m.group(2))", "test_last_assignment_wins"),
    ("bash -c is parsed too", "all_cmds = [cmd] + _inner_commands(cmd)", "all_cmds = [cmd]",
     "test_delete_inside_bash_c_is_seen"),
]

SHIM = '''

# --- coverage harness shim (appended to a COPY, never to the real file) ---
_ORIG_FACTS = facts
_PIN_KEY = "{key}"
_PIN_VAL = {val}


def facts(payload, roots):          # noqa: F811
    d = _ORIG_FACTS(payload, roots)
    if _PIN_KEY in d:
        d[_PIN_KEY] = _PIN_VAL
    return d
'''

# `background` is a passthrough of the caller's own flag -- an INPUT the long-job rule
# consumes, not a rule predicate. Excluded by name and printed, never quietly dropped.
NOT_A_RULE = {"background"}


def run(work: Path):
    p = subprocess.run([sys.executable, "test_hook_facts.py"], cwd=work,
                       capture_output=True, text=True, errors="replace")
    out = p.stdout + p.stderr
    failed = set(re.findall(r"(?:FAIL|ERROR): (\w+) ", out))
    ran = re.search(r"Ran (\d+) tests", out)
    return p.returncode, failed, int(ran.group(1)) if ran else -1


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        for f in FILES:
            src = HOOKS / f
            if not src.is_file():
                print(f"REFUSING: {src} not found", file=sys.stderr)
                return 2
            shutil.copy2(src, work / f)
        target = work / "hook_facts.py"
        pristine = target.read_text(encoding="utf-8")

        rc, failed, ran = run(work)
        if rc != 0 or ran < 20:
            print(f"REFUSING: baseline is not green (rc={rc}, ran={ran}, "
                  f"{len(failed)} failed). No mutation result would mean anything.",
                  file=sys.stderr)
            return 2
        print(f"baseline: {ran} tests green\n")

        bad = 0
        print(f"{'MUTATION':<42} {'target test':<12} verdict")
        print("-" * 78)
        for label, old, new, tgt in MUTANTS:
            if pristine.count(old) != 1:
                print(f"{label:<42} {'-':<12} *** DID NOT APPLY "
                      f"({pristine.count(old)} matches) -- the mutant is stale ***")
                bad += 1
                continue
            target.write_text(pristine.replace(old, new), encoding="utf-8", newline="")
            rc, failed, ran = run(work)
            if ran < 20:
                print(f"{label:<42} {'BROKE':<12} *** broke the suite, proves nothing ***")
                bad += 1
            elif tgt in failed:
                extra = len(failed) - 1
                print(f"{label:<42} {'RED':<12} correct"
                      + (f" (+{extra} other)" if extra else " (only this test)"))
            else:
                print(f"{label:<42} {'green':<12} *** NOT CAUGHT by its target test ***")
                bad += 1
        target.write_text(pristine, encoding="utf-8", newline="")

        sys.path.insert(0, str(work))
        import hook_facts as H
        keys = sorted(k for k, v in H.facts({"tool_input": {"command": "echo x"}}, {}).items()
                      if isinstance(v, bool) and k not in NOT_A_RULE)
        print(f"\nexcluded as not-a-rule: {sorted(NOT_A_RULE)}")
        print(f"\n{'PREDICATE':<42} {'fires?':<14} silent?")
        print("-" * 78)
        gaps = 0
        for k in keys:
            row = []
            for val in ("False", "True"):
                target.write_text(pristine + SHIM.format(key=k, val=val),
                                  encoding="utf-8", newline="")
                _rc, f, r = run(work)
                row.append("BROKE" if r < 20 else ("probed" if f else "*** NONE ***"))
            if "*** NONE ***" in row or "BROKE" in row:
                gaps += 1
            print(f"{k:<42} {row[0]:<14} {row[1]}")
        target.write_text(pristine, encoding="utf-8", newline="")

    print("-" * 78)
    print(f"mutations not caught by their target test: {bad} of {len(MUTANTS)}")
    print(f"predicates with a coverage gap:            {gaps} of {len(keys)}")
    print("  fires?   = predicate pinned FALSE, so a must-FIRE test must break")
    print("  silent?  = predicate pinned TRUE,  so a must-NOT-fire test must break")
    return 1 if (bad or gaps) else 0


if __name__ == "__main__":
    raise SystemExit(main())

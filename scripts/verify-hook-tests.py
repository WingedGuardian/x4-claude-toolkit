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
    # The hard block must stay scoped to the catastrophic cases. Widening it back to
    # "anything under the tree" hard-denies the documented deploy path -- measured over a
    # 1,000-command sample, all 4 hits were exactly that.
    ("hard block is ROOT-scoped, not under-scoped",
     'return n == g or n == g + "/extensions"', "return n.startswith(g)",
     "test_deleting_ONE_deployed_mod_is_NOT_a_hard_block"),
    ("extensions/ wholesale is still a hard block",
     'return n == g or n == g + "/extensions"', "return n == g",
     "test_deleting_extensions_WHOLESALE_is_a_hard_block"),
    ("the name backstop is ROOT-anchored",
     r'GAME_ROOTISH = re.compile(r"(x4 foundations|egosoft/x4)(/extensions)?$", re.I)',
     r'GAME_ROOTISH = re.compile(r"(x4 foundations|egosoft/x4)", re.I)',
     "test_unconfigured_backstop_does_not_catch_a_mod_folder"),
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
    # --- prose must not blind the guard (C1, 2026-09-01) --------------------------
    # One apostrophe in an English comment disabled EVERY rule after it. Four separate
    # clauses had to change; each gets its own mutant, because mutating the feature as a
    # whole cannot tell which clause a test is actually exercising.
    ("a backslash outside quotes escapes the next char",
     "        elif c == chr(92) and i + 1 < len(s):\n            yield c, False\n            i += 1\n            yield s[i], False          # escaped: never opens a quote",
     "        elif False:\n            yield c, False\n            i += 1\n            yield s[i], False",
     "test_an_escaped_apostrophe_does_not_blind_the_next_command"),
    ("comments are stripped before parsing",
     "    body = strip_comments(strip_heredocs(cmd))",
     "    body = strip_heredocs(cmd)",
     "test_comment_apostrophe_does_not_hide_a_game_delete"),
    ("the string rules read the CLEANED text, not the raw command",
     "    stripped = body", "    stripped = strip_heredocs(cmd)",
     "test_a_comment_apostrophe_does_not_hide_a_long_job"),
    # The parseability check moved OUT of hook_facts into protect-bash.sh, which asks
    # `bash -n`. It is covered E2E in scripts/test-hooks.sh -- a mutation of the real
    # shell parser is not something this gate can plant.
    ("a heredoc BODY is data for the operand rules too",
     "    all_cmds = [body] + _inner_commands(body)",
     "    all_cmds = [cmd] + _inner_commands(cmd)",
     "test_a_delete_inside_a_heredoc_body_is_not_a_delete"),
    ("a comment keeps its newline, which is a separator",
     "            while i < len(s) and s[i] != \"\\n\":      # keep the newline: it is a separator",
     "            while i < len(s) and s[i] != \"\\r\":",
     "test_a_comment_keeps_its_newline_which_is_a_separator"),

    # --- operands resolve against the command's own cwd (2026-09-01) ---------------
    # Each clause gets its OWN mutant. Mutating the whole feature to a no-op cannot
    # distinguish "the join is untested" from "some earlier guard covers it".
    ("a relative operand is joined to the cwd",
     'out.append((r if unres else join_cwd(c_cwd, r), unres, r))',
     'out.append((r if unres else r, unres, r))',
     "test_cd_then_relative_delete_of_extensions_is_the_game_delete"),
    # The NAME backstop is the opposite call from hits_game_root, and the difference is
    # load-bearing: it must NOT skip unresolved operands, because on an unconfigured
    # machine it is the only protection there is and the visible text is the evidence.
    # A `not u` filter added here on 2026-09-01 removed that defence; the 13,041-command
    # corpus could not see it (no historical command has the shape) and only this gate did.
    ("the NAME backstop does NOT skip unresolved operands",
     "rm_named_game = any(GAME_ROOTISH.search(norm(p)) for p, _u, _ in rm_t)",
     "rm_named_game = any(not _u and GAME_ROOTISH.search(norm(p)) for p, _u, _ in rm_t)",
     "test_the_NAME_backstop_still_fires_on_an_unresolvable_path"),
    #
    # NOT MUTATED, deliberately -- two guards whose removal is BEHAVIOURALLY EQUIVALENT
    # today, so a mutant for them would sit here permanently "not caught" and train
    # everyone to ignore this table:
    #   * join_cwd's `is_abs(cwd)` check. A relative cwd joined to a relative operand
    #     yields a relative path, which matches no root either way.
    #   * hits_game_root's `unres` check. An unresolved operand still contains `$`, so
    #     norm(path) can never equal the game root.
    # Both are kept as PROSPECTIVE guards: if resolve() ever learns to expand
    # environment variables, each becomes load-bearing immediately -- which is exactly
    # the F93 shape, a capability improvement widening a guard nobody re-scoped.
    ("pushd relocates as well as cd",
     'DIR_VERBS = {"cd", "pushd"}', 'DIR_VERBS = {"cd"}',
     "test_pushd_relocates_like_cd"),
    ("popd pops, rather than being ignored",
     'elif v == "popd" and stack:\n            cwd = stack.pop()',
     'elif v == "popd" and stack:\n            pass',
     "test_popd_returns_to_the_previous_directory"),
    ("subshell punctuation is stripped from a segment",
     "    return [_unwrap(p) for p in parts if p.strip()]",
     "    return [p for p in parts if p.strip()]",
     "test_subshell_cd_relocates"),
    ("command substitution counts as unresolved",
     "    return bool(_VAR.search(tok) or _SUBST.search(tok))",
     "    return bool(_VAR.search(tok))",
     "test_command_substitution_counts_as_unresolved"),
    ("a root named only by its ENV VAR is still that root",
     "                if conservative and key in root_vars_named(raw):\n                    return True",
     "                if False:\n                    return True",
     "test_delete_of_a_root_env_var_by_name"),
    ("bash -c is parsed too", "all_cmds = [body] + _inner_commands(body)", "all_cmds = [body]",
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

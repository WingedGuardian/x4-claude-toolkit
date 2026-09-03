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

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

#: A literal newline, built from its byte value. Multi-line mutant
#: anchors need one, and an escape written here would cross a tool
#: boundary that has collapsed one into a control byte before now.
NL = chr(10)

REPO = Path(__file__).resolve().parent.parent
HOOKS = REPO / ".claude" / "hooks"
FILES = ("hook_facts.py", "test_hook_facts.py")

# (label, exact source text, replacement, the test that MUST go red)
MUTANTS = [
    ("a leading ~ / $HOME is expanded",
     "    return expand_home(out)", "    return out",
     "test_all_home_spellings_reach_the_same_verdict_as_the_absolute_form"),
    ("only a LEADING home reference is expanded",
     'if tok == "~" or (tok[:1] == "~" and tok[1:2] in _SEPS):',
     'if "~" in tok:',
     "test_only_a_LEADING_home_reference_is_expanded"),
    # --- wrappers that carry a command as TEXT ---------------------------------
    ("a shell -c flag CLUSTER is unwrapped",
     r'_DASH_C = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")',
     r'_DASH_C = re.compile(r"^-c$")',
     "test_every_shell_c_spelling_is_unwrapped"),
    ("eval carries a command",
     '        elif v == "eval":', '        elif False:',
     "test_eval_is_unwrapped"),
    # --- reserved words, one mutant per clause ---------------------------------
    # The fuzzer found this class; these keep it found. Each clause is mutated on its
    # own: a single mutant of the whole helper cannot distinguish "this clause is
    # untested" from "an earlier clause returns before it".
    ("reserved words leave the segment",
     '        if head and head[0] in RESERVED:', '        if False:',
     "test_every_compound_form_still_shows_the_command"),
    ("`case WORD in` is consumed",
     '        if head and head[0] == "case":', '        if False and head:',
     "test_every_compound_form_still_shows_the_command"),
    ("a function header is consumed",
     '        m = _FUNC_HEAD.match(s)', '        m = None',
     "test_every_compound_form_still_shows_the_command"),
    # The regression the fix itself introduced: the ORIGINAL over-wide label regex,
    # which ate `rm -rf extensions)` out of a process substitution. If this mutant ever
    # stops being caught, that hole is open again.
    ("a case label carries no whitespace",
     r'_CASE_ARM = re.compile(r"^[^\s()&;]+\)\s")',
     r'_CASE_ARM = re.compile(r"^[^()|&;]*\)\s")',
     "test_a_process_substitution_tail_is_not_a_case_arm_label"),
    # --- the PARSER, one mutant per clause -------------------------------------
    # Added 2026-09-01. The gate reported "31 of 31 caught, 0 of 19 predicate gaps"
    # while three total-guard bypasses were live, because every mutant targeted a
    # PREDICATE and none targeted the parse pass that feeds them. `<<` opens a skip
    # region, so one wrong marker blanks the rest of the command and every rule below
    # goes silent. Each clause is mutated SEPARATELY: a single mutant of the whole
    # condition cannot tell "this clause is untested" from "an earlier clause shadows it".
    ("a here-string `<<<` is not a heredoc",
     'if i > 0 and line[i - 1] == chr(60):\n                continue',
     'if False:\n                continue',
     "test_a_here_string_opens_no_heredoc"),
    ("a `<<` in a COMMENT is not a heredoc",
     "stop = _comment_start(line, mask)", "stop = len(line)",
     "test_a_double_angle_in_a_COMMENT_opens_no_heredoc"),
    ("an arithmetic left-shift is not a heredoc",
     "line = _blank_arith(line, mask)", "line = line",
     "test_an_arithmetic_left_shift_opens_no_heredoc"),
    # ...and the other direction: the exclusions must not swallow REAL heredocs, or the
    # body stripping dies silently and heredoc text is read as commands.
    ("the exclusions must not kill real heredocs",
     "            m = _HD.match(line, i)", "            m = None",
     "test_a_real_heredoc_is_still_recognised"),
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
    # Anchored on strip_heredocs' own call: heredoc_bodies() added a SECOND
    # `t = heredoc_marker(line)` and the bare line now matches twice.
    ("the heredoc marker may itself be QUOTED",
     "        t = heredoc_marker(line)" + NL + "        if t:" + NL
     + "            term, skip = t, True",
     "        t = heredoc_marker(blank_quoted(line))" + NL + "        if t:" + NL
     + "            term, skip = t, True",
     "test_a_QUOTED_marker_still_opens_a_heredoc"),
    ("noclobber >| is a redirect", r'_REDIR = re.compile(r"(\d?)>(\|?)(>?)")',
     r'_REDIR = re.compile(r"(\d?)>()(>?)")', "test_noclobber_override_is_a_truncate"),
    ("cp/mv -t destination", 'if not quoted and t in ("-t", "--target-directory"):',
     "if False:", "test_dash_t_names_the_destination"),
    ("wrapper verbs are seen through",
     "        if _verb_name(t) in WRAPPERS:", "        if False:",
     "test_sees_through_a_wrapper"),
    ("dot-segment canonicalisation", "s = posixpath.normpath(s)", "s = s",
     "test_dot_segment_is_canonicalised"),
    ("-e consumes its argument", 'if base in _ARG_FLAGS and "=" not in t:\n                skip = True',
     "if False:\n                skip = True",
     "test_dash_e_supplies_the_pattern_so_the_path_is_not_consumed"),
    ("tee writes EVERY file operand", 'return ops if v == "tee" else [ops[-1]]',
     "return [ops[-1]]", "test_tee_writes_EVERY_file_operand"),
    ("last assignment wins", "found[m.group(1)] = m.group(2)",
     "found.setdefault(m.group(1), m.group(2))", "test_last_assignment_wins"),
    # --- delete verbs and timeout shapes (2026-09-01) -----------------------------
    ("find -delete is a delete", "    return find_deletes(seg)", "    return []",
     "test_find_delete_on_the_game_is_a_game_delete"),
    ("a FILTERED find is scoped, not a tree delete",
     "    if any(_narrows(toks, i) for i, t in enumerate(toks) if t in _FIND_FILTERS):",
     "    if False:",
     "test_a_FILTERED_find_is_scoped_and_does_not_fire"),
    ("a find WITHOUT -delete is not", 'deletes = "-delete" in toks', "deletes = True",
     "test_a_find_that_does_NOT_delete_is_not_a_delete"),
    ("a non-int timeout still counts", '"timeout_over_cap": _as_ms(timeout) > 600000,',
     '"timeout_over_cap": isinstance(timeout, int) and timeout > 600000,',
     "test_a_float_over_the_cap_fires"),
    # NOT MUTATED: the bool guard in _as_ms is BEHAVIOURALLY EQUIVALENT today --
    # float(True) is 1.0, which is under the cap either way, so removing it cannot
    # change a verdict. Kept as a guard because Python treats True as an int and a
    # future cap of 0 or 1 would make it load-bearing; not mutated, because a mutant
    # that can never be caught sits here permanently red and trains everyone to skim
    # this table.

    # --- prose must not blind the guard (C1, 2026-09-01) --------------------------
    # One apostrophe in an English comment disabled EVERY rule after it. Four separate
    # clauses had to change; each gets its own mutant, because mutating the feature as a
    # whole cannot tell which clause a test is actually exercising.
    ("a backslash outside quotes escapes the next char",
     "        elif c == chr(92) and i + 1 < len(s):\n            yield c, False\n            i += 1\n            yield s[i], False          # escaped: never opens a quote",
     "        elif False:\n            yield c, False\n            i += 1\n            yield s[i], False",
     "test_an_escaped_apostrophe_does_not_blind_the_next_command"),
    ("comments are stripped before parsing",
     "    body = strip_comments(strip_heredocs(spliced))",
     "    body = strip_heredocs(cmd)",
     "test_comment_apostrophe_does_not_hide_a_game_delete"),
    ("the string rules read the CLEANED text, not the raw command",
     "    stripped = body", "    stripped = strip_heredocs(cmd)",
     "test_a_comment_apostrophe_does_not_hide_a_long_job"),
    # The parseability check moved OUT of hook_facts into protect-bash.sh, which asks
    # `bash -n`. It is covered E2E in scripts/test-hooks.sh -- a mutation of the real
    # shell parser is not something this gate can plant.
    ("a heredoc BODY is data for the operand rules too",
     '    all_cmds, carriers_truncated = carried_commands(\n        body, [strip_comments(h) for h in heredoc_bodies(spliced)])',
     "    all_cmds, carriers_truncated = carried_commands(cmd, [])",
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
     "rm_named_game = any(GAME_ROOTISH.search(norm(p or raw)) for p, _u, raw in rm_t)",
     "rm_named_game = any(not _u and GAME_ROOTISH.search(norm(p or raw)) for p, _u, raw in rm_t)",
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
     "    return bool(_EXPANSION.search(tok) or _SUBST.search(tok))",
     "    return bool(_EXPANSION.search(tok))",
     "test_command_substitution_counts_as_unresolved"),
    ("a root named only by its ENV VAR is still that root",
     "                if conservative and key in root_vars_named(raw):\n                    return True",
     "                if False:\n                    return True",
     "test_delete_of_a_root_env_var_by_name"),
    ("bash -c is parsed too",
     '    all_cmds, carriers_truncated = carried_commands(\n        body, [strip_comments(h) for h in heredoc_bodies(spliced)])',
     "    all_cmds, carriers_truncated = [body], False",
     "test_delete_inside_bash_c_is_seen"),

    # --- COMMAND RESOLUTION (2026-09-02). Six total bypasses, one root cause: the
    # parse pass modelled shell GRAMMAR and not command RESOLUTION. Each mutant below
    # restores one half of the pre-fix behaviour.
    ("a verb token is resolved to a command NAME",
     "    n = posixpath.basename(norm(t))", "    n = t",
     "test_the_hard_block_survives_every_spelling"),
    ("a .exe suffix is dropped",
     '    if n.endswith(".exe"):', "    if False:",
     "test_a_dot_exe_suffix_is_the_same_command"),
    ("ANSI-C quoting is not part of the name",
     '            if buf and buf[-1] == "$":', "            if False:",
     "test_ansi_c_quoting_is_not_part_of_the_name"),
    ("a wrapper's VALUE argument is not the command",
     "        if seen_wrapper and _WRAPPER_ARG.match(t):", "        if False:",
     "test_a_duration_is_not_mistaken_for_the_command"),
    ("a substitution carries a command",
     "    return [o for o in out if o.strip()]", "    return []",
     "test_dollar_paren"),
    ("single-quoted text is NOT a substitution",
     "        if k == chr(39):                        # single-quoted: literal",
     "        if False:",
     "test_inside_SINGLE_quotes_nothing_runs"),
    ("trap carries a command",
     '        elif v == "trap":', "        elif False:",
     "test_trap_runs_its_first_operand"),
    ("eval is found wherever it sits",
     "            k = next((i for i, (t, _) in enumerate(toks)" + NL
     + '                      if _verb_name(t) == "eval"), 0)',
     "            k = 0",
     "test_a_wrapper_may_precede_eval"),
    ("only a SHELL runs its heredoc body",
     "                if any(verb(_unwrap(sg)) in _SHELL_SINKS for sg in segments(opener)):",
     "                if True:",
     "test_a_python_heredoc_does_NOT"),
    # ---- round 3: a command reaches the shell without being seen -------------
    ("a line continuation is spliced, not treated as a separator",
     "    spliced = join_continuations(cmd)", "    spliced = cmd",
     "test_the_game_root"),
    ("a continuation inside SINGLE quotes stays literal",
     '        if q == "' + "'" + '":' + NL
     + '            if c == "' + "'" + '":',
     '        if False:' + NL
     + '            if c == "' + "'" + '":',
     "test_inside_SINGLE_quotes_it_stays_literal"),
    ("a shell with no script operand reads its program from stdin",
     "    rest = _drop_redirects(toks[1:])",
     "    return False" + NL + "    rest = _drop_redirects(toks[1:])",
     "test_a_here_string"),
    ("a redirect is not an operand",
     "    out = []" + NL + "    i = 0" + NL + "    while i < len(toks):",
     "    return list(toks)" + NL + "    out = []" + NL + "    i = 0" + NL
     + "    while i < len(toks):",
     "test_separated_and_attached_here_strings"),
    ("ANY parameter expansion is unresolved, not just the two _VAR names",
     "    return bool(_EXPANSION.search(tok) or _SUBST.search(tok))",
     "    return bool(_VAR.search(tok) or _SUBST.search(tok))",
     "test_suffix_strip"),
    ("coproc is a reserved word",
     '"coproc", "[[", "]]"}', '"[[", "]]"}',
     "test_coproc_does_not_hide_a_delete"),
    # ---- round 3b: resolution, not just grammar ------------------------------
    ("an expansion carrying an operator is resolved",
     "        out = _VAR_OP.sub(sub_op, _VAR.sub(sub, out))",
     "        out = _VAR.sub(sub, out)",
     "test_default_when_unset"),
    ("a GLOB pattern is NOT guessed at",
     "        if set(pat) & _GLOB_CHARS or not pat:",
     "        if not pat:",
     "test_a_GLOB_pattern_is_left_unresolved"),
    ("an array keeps its quoting when captured",
     '        for m in re.finditer(r"(?:^|\\s)([A-Za-z_][A-Za-z0-9_]*)=\\(", seg):',
     '        for m in []:',
     "test_a_spaced_path_stays_ONE_element"),
    ("cd resolves its operand",
     "                    cwd = join_cwd(cwd, resolve(ops[0], assigns))",
     "                    cwd = join_cwd(cwd, ops[0])",
     "test_a_plain_variable"),
    ("carriers are followed more than one level",
     "    for _ in range(_MAX_CARRIER_DEPTH):", "    for _ in range(0):",
     "test_a_shell_inside_a_shell"),
    ("a filter must actually narrow",
     "    return arg not in _UNIVERSAL", "    return True",
     "test_a_universal_name_glob_is_not_a_narrowing"),
    ("the carrier walk ANNOUNCES its bound",
     "                        return out[:_MAX_CARRIED], True",
     "                        return out[:_MAX_CARRIED], False",
     "test_a_TANGLED_command_says_so_instead_of_passing_quietly"),
    ("no fact-stream value can carry a separator",
     '    return str(v).replace(chr(13), " ").replace(chr(10), " ").replace(chr(9), " ")',
     "    return str(v)",
     "test_no_value_can_carry_a_field_separator"),
    ("the name backstop sees a relative operand",
     "    rm_named_game = any(GAME_ROOTISH.search(norm(p or raw)) for p, _u, raw in rm_t)",
     "    rm_named_game = any(GAME_ROOTISH.search(norm(p)) for p, _u, raw in rm_t)",
     "test_a_named_operand_after_a_RELATIVE_cd_fires"),
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
    # PYTHONDONTWRITEBYTECODE, and it is not hygiene -- without it this gate returns
    # WRONG VERDICTS. CPython invalidates a cached .pyc on (source mtime in SECONDS,
    # source size). Successive mutants are written to the same path within the same
    # second, so whenever two of them leave the file the same size, the second run
    # imports the FIRST one's bytecode and the mutant is judged by the previous
    # mutant's failures.
    #
    # MEASURED 2026-09-02: 2 of 54 mutants reported "NOT CAUGHT by its target test"
    # while each, reproduced by hand, turned its target test red. The tell was that
    # the failing tests named in each case belonged to the mutant BEFORE it in the
    # list. With bytecode off: 0 of 54 uncaught.
    #
    # The false-alarm direction is the one that was observed; the silent direction is
    # worse and equally reachable -- a mutant reported CAUGHT because the previous
    # mutant's failures happened to include its target test.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for pyc in work.rglob("__pycache__"):
        shutil.rmtree(pyc, ignore_errors=True)
    p = subprocess.run([sys.executable, "test_hook_facts.py"], cwd=work,
                       capture_output=True, text=True, errors="replace", env=env)
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

        # A target test that does not exist reports "NOT CAUGHT" -- the same words as
        # a real coverage hole, and the message you would act on by writing a test that
        # is already there. MEASURED 2026-09-02: five mutants added that day named test
        # CLASSES, which unittest never prints in a `FAIL:` line, and all five read as
        # coverage holes. The direction is safe, so this is legibility, not a bypass.
        source = (HOOKS / "test_hook_facts.py").read_text(encoding="utf-8")
        missing = [t for _l, _o, _n, t in MUTANTS if ("def " + t + "(") not in source]
        if missing:
            print("REFUSING: %d mutant target(s) name no test in test_hook_facts.py: %s"
                  % (len(missing), ", ".join(sorted(set(missing)))), file=sys.stderr)
            print("  (a target must be a test METHOD name -- unittest prints no class "
                  "name in a FAIL: line)", file=sys.stderr)
            return 2

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

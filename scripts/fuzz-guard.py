#!/usr/bin/env python3
"""Find guard BYPASSES by mutating the syntax AROUND a dangerous operation.

    python scripts/fuzz-guard.py [--verbose]

WHY THIS EXISTS. Two parser defects shipped in one release, and NEITHER was found by
143 unit tests, 28 planted mutations, or a 13,193-command replay:

  * `_scan` opened a quote state on any apostrophe, so ONE apostrophe in an English
    comment masked the rest of the command as quoted text that no rule could see --
    5 of 5 refusals became a silent allow, two of them hard blocks. Found by a reviewer.
  * the FIX for it flagged 13 valid commands as unparseable, because command
    substitution inside double quotes resets the quoting context and a flat scanner
    cannot model that nesting. Found by comparing against `bash -n`.

Both were found by an EXTERNAL ORACLE. Tests written by whoever wrote the parser share
its blind spots by construction, and a corpus replay can only contain syntax that has
already occurred. This closes that gap:

    take a command the guard REFUSES, change only the SYNTAX AROUND the dangerous
    operation, and require the verdict not to weaken.

The dangerous operand is byte-identical in every mutant, so a drop from deny/ask to
allow is a bypass -- an observation, not a judgement call.

CONTROLS FIRST, because a fuzzer that cannot find a known hole cannot be trusted to
report the absence of one. Every run plants the pre-fix scanner and REQUIRES the
apostrophe bypass to be rediscovered before it will report anything.

Exit 0 clean / 1 bypass found / 2 refused (controls failed, or nothing exercised).
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOKS = REPO / ".claude" / "hooks"
# NOT plain "bash": on Windows that resolves to the WSL stub in System32, which has
# cost this workspace three separate debugging sessions.
#
# This line USED to read `which("bash.exe") or which("bash")`, with that same comment.
# MEASURED 2026-09-01 from PowerShell: `which("bash.exe")` returns
# `C:\Windows\system32ash.exe` -- the stub IS named bash.exe, so the defence named
# the right threat and did nothing about it, which is worse than none because it stops
# anyone looking again. `gitbash.find_bash()` excludes the stub directories by path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gitbash import find_bash            # noqa: E402

BASH = find_bash()

#: Paths that need not exist. Shaped like the real ones -- a drive letter, spaces, and
#: a nested extensions/ -- because those are the shapes the rules actually turn on.
SYNTHETIC_ROOTS = {
    "game": "C:/Games/Steam/steamapps/common/X4 Foundations",
    "reference": "C:/work/x4/reference",
    "toolkit": "C:/work/x4",
    "profile": "C:/Users/tester/Documents/Egosoft/X4/12345678",
    "mods": "C:/work/x4/dev",
    "documents": "C:/Users/tester/Documents",
    "saves": "C:/Users/tester/Documents/Egosoft/X4/12345678/save",
}

RANK = {"deny": 3, "ask": 2, "advise": 1, "allow": 0}

# Which fact carries which verdict is DERIVED from protect-bash.sh, never restated here.
#
# It used to be two hand-written tuples, and they had drifted. MEASURED 2026-09-01
# against the hook's own 19 mapped predicates: the tuples listed **14**, so the fuzzer
# was blind to 5 rules (26%) - `search_rooted_reference`, `search_rooted_workspace`,
# `copy_into_game_or_profile`, `redirect_truncate_into_game_or_profile` and
# `durable_truncating_redirect` - and mis-classified a 6th (`longjob_foreground` as ask;
# the hook denies it, confirmed E2E). A bypass in any of those five could never have been
# reported: the seed would read "already allow" and be skipped in silence, which is how
# two of the twelve seeds were being dropped every run.
#
# A second copy of a policy is a second thing to keep right. This one is read.
def policy_map(fact_names):
    """{fact: deny|ask|advise} parsed from protect-bash.sh.

    Comment lines are dropped first (the hook's prose says "on the", "on every", ...),
    and every candidate must be a REAL fact name emitted by hook_facts - which is what
    keeps English out of the map.
    """
    lines = (HOOKS / "protect-bash.sh").read_text(encoding="utf-8").splitlines()
    code = ["" if l.lstrip().startswith("#") else l.split("#")[0] for l in lines]
    out = {}
    for i, l in enumerate(code):
        m = re.search(r"(?:^|\s)on\s+([a-z0-9_]+)\b", l)
        if not m or m.group(1) not in fact_names:
            continue
        window = " ".join(code[i:i + 6])
        v = re.search(r"\b(deny|ask|advise)\s+\"", window)
        if v:
            out[m.group(1)] = v.group(1)
    return out


#: A parse that yields little or nothing must REFUSE, not degrade. An empty map makes
#: verdict() return "allow" for every seed, every seed is then skipped as "nothing to
#: weaken", and the run prints "no bypass found" over having tested nothing at all.
MIN_MAPPED_RULES = 15

NL = chr(10)
AP = chr(39)     # apostrophe
QU = chr(34)     # double quote
BSL = chr(92)    # backslash -- never a literal, it changes meaning per quoting context
BS = chr(92)     # backslash
BT = chr(96)     # backtick


def load_facts(path):
    spec = importlib.util.spec_from_file_location("hf_fuzz", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verdict(mod, cmd, roots, policy):
    f = mod.facts({"tool_input": {"command": cmd, "timeout": 0,
                                  "run_in_background": False}}, roots)
    best = "allow"
    for k, v in policy.items():
        if f.get(k) and RANK[v] > RANK[best]:
            best = v
    return best


def parses(cmd):
    """bash's own verdict. A mutant bash refuses to parse is not a bypass, because bash
    would not run it either."""
    return subprocess.run([BASH, "-n", "-c", cmd], capture_output=True).returncode == 0


# --------------------------------------------------------------------- mutators
# Each ADDS surrounding syntax and leaves the dangerous part byte-identical. That is
# what makes a weakened verdict a bypass rather than simply a different command.
def _m_comment_apostrophe(c):
    return "# it" + AP + "s a cleanup" + NL + c


def _m_comment_quote(c):
    return "# see " + QU + "notes" + NL + c


def _m_comment_backtick(c):
    return "# see " + BT + "notes" + NL + c


def _m_comment_paren(c):
    return "# cleanup (phase 1" + NL + c


def _m_trailing_comment(c):
    return c + "  # done"


def _m_echo_apostrophe(c):
    return "echo " + QU + "it" + AP + "s fine" + QU + " && " + c


def _m_heredoc_quoted(c):
    return "cat > /dev/null <<" + AP + "X" + AP + NL + "it" + AP + "s data" + NL + "X" + NL + c


def _m_heredoc_plain(c):
    return "cat > /dev/null <<X" + NL + "plain data" + NL + "X" + NL + c


def _m_cmdsubst(c):
    return "echo $(date) && " + c


def _m_backticks(c):
    return "echo " + BT + "date" + BT + " && " + c


def _m_nested_quotes(c):
    return ("echo " + QU + "a $(grep -o " + AP + "x|y" + AP + " f) b" + QU + " && " + c)


def _m_escaped_quote(c):
    return "echo " + QU + "a " + BS + QU + "b" + BS + QU + QU + " && " + c


def _m_ansi_c(c):
    return "printf $" + AP + BS + "n" + AP + " && " + c


def _m_subshell(c):
    return "( " + c + " )"


def _m_leading_blank(c):
    return NL + NL + c


def _m_assignment(c):
    return "FOO=bar" + NL + c


def _m_semicolon(c):
    return c + " ; echo done"


def _m_pipe(c):
    return c + " | head -3"


def _m_env_prefix(c):
    return "PYTHONIOENCODING=utf-8 " + c


# ---------------------------------------------------------------------------
# SYNTAX CLASSES
#
# Added 2026-09-01, after a here-string bypass reached a shipped guard while 151
# unit tests, 35 mutants and a 13,500-command replay were all green. The mutators
# above grew one at a time, each one a reaction to a bug already found; that is how
# `<<<` was missed -- nobody had been bitten by it yet.
#
# So these are chosen by CLASS from the shell grammar rather than from experience:
# every construct that can carry a quote, a `#`, a `<`, or a `>` past a naive
# scanner, plus the compound commands that can WRAP a dangerous operation instead
# of merely preceding it. The dangerous operation is untouched in every case, so
# the verdict must not move. `bash -n` asserts both sides stay parseable.
#
# MEASURED incidence in real history for the three shapes this batch was born from:
# `<<<` 40, `<<` after a `#` 15, `$(( .. <<` 8 -- 49 of 13,503 commands (0.36%).
# None of the 49 changed verdict, so the corpus could never have found this. That is
# the argument for a fuzzer: history only contains what has already happened.
# ---------------------------------------------------------------------------

# --- class: here-strings (`<<<` is not a heredoc) ---------------------------
def _m_herestring(c):
    return "cat <<< hello" + NL + c


def _m_herestring_marker_word(c):
    # the word after `<<<` looks exactly like a heredoc terminator
    return "cat <<<EOF" + NL + c


def _m_herestring_quoted(c):
    return "cat <<< " + AP + "it" + AP + AP + "s here" + AP + NL + c


# --- class: arithmetic expansion (`<<` / `>>` are SHIFTS) -------------------
def _m_arith_lshift(c):
    return "n=$((1 << 4))" + NL + c


def _m_arith_rshift(c):
    return "n=$((256 >> 2))" + NL + c


def _m_arith_nested(c):
    return "n=$(( (1 << 2) + $((3 >> 1)) ))" + NL + c


# --- class: comments carrying shell metacharacters --------------------------
def _m_comment_heredoc_marker(c):
    return "# example: cat <<EOF" + NL + c


def _m_comment_herestring(c):
    return "# a <<< b" + NL + c


def _m_comment_redirect(c):
    return "# writes with > and >> and 2>&1" + NL + c


# --- class: parameter expansion (a `#` that is NOT a comment) ---------------
def _m_param_strip(c):
    return "x=${PATH#/}" + NL + c


def _m_param_default_quote(c):
    return "x=" + QU + "${FOO:-it" + AP + "s}" + QU + NL + c


def _m_param_length(c):
    return "n=${#PATH}" + NL + c


# --- class: process substitution --------------------------------------------
def _m_procsub(c):
    return "diff <(echo a) <(echo b) >/dev/null 2>&1 || true" + NL + c


# --- class: redirection forms ------------------------------------------------
def _m_redirect_merge(c):
    return "echo probe 2>&1 >/dev/null" + NL + c


def _m_redirect_append(c):
    return "echo probe >> /dev/null" + NL + c


# --- class: brace expansion and globbing ------------------------------------
def _m_brace_expansion(c):
    return "echo {a,b}.txt >/dev/null" + NL + c


# --- class: line continuation -----------------------------------------------
def _m_line_continuation(c):
    return "echo one " + BSL + NL + "  two >/dev/null" + NL + c


# --- class: conditional expressions (`<` inside [[ ]] is not a redirect) -----
def _m_double_bracket(c):
    return "[[ " + QU + "a" + QU + " < " + QU + "b" + QU + " ]] && true" + NL + c


# --- class: compound commands that WRAP the dangerous operation -------------
# These matter more than the prefixes: the operation is nested, not merely preceded,
# so a scanner that only inspects the first simple command loses it entirely.
def _m_wrap_if(c):
    return "if true; then " + c + "; fi"


def _m_wrap_for(c):
    return "for i in 1; do " + c + "; done"


def _m_wrap_braces(c):
    return "{ " + c + "; }"


def _m_wrap_while(c):
    return "while false; do :; done; " + c


def _m_wrap_and_or(c):
    return "true && " + c + " || true"


# --- class: compound commands, the REST of the grammar ----------------------
# The first two of these (if/then, for/do) were found by the fuzzer on 2026-09-01 and
# turned out to be a TOTAL guard bypass: a reserved word prefixes the simple command
# inside a `;`-delimited segment, so verb() returned `then`/`do` and every verb-keyed
# rule missed -- hard blocks included. The rest are here so the fix is measured against
# the whole class rather than the two forms that happened to be tried first.
def _m_wrap_until(c):
    return "until true; do " + c + "; break; done"


def _m_wrap_else(c):
    return "if false; then :; else " + c + "; fi"


def _m_wrap_elif(c):
    return "if false; then :; elif true; then " + c + "; fi"


def _m_wrap_case(c):
    return "case x in x) " + c + " ;; *) :;; esac"


def _m_wrap_negation(c):
    return "! " + c


def _m_wrap_if_condition(c):
    # the dangerous command is the CONDITION, not the body
    return "if " + c + "; then :; fi"


def _m_wrap_function(c):
    return "f() { " + c + "; }; f"


def _m_wrap_nested(c):
    return "if true; then for i in 1; do " + c + "; done; fi"


# --- class: wrappers that carry a command as TEXT ---------------------------
# `bash -c`, its flag-cluster spellings and `eval` all run a STRING as a command, so
# whatever they carry is invisible to any rule that inspects segments. MEASURED
# 2026-09-01: `bash -lc` and `eval` were both total bypasses of a hard block while
# `sh -c` was caught -- the unwrapper matched the literal token `-c` only.
def _sq(c):
    """Embed arbitrary text in single quotes the way the shell requires."""
    return AP + c.replace(AP, AP + BSL + AP + AP) + AP


def _m_bash_c(c):
    return "bash -c " + _sq(c)


def _m_bash_lc(c):
    return "bash -lc " + _sq(c)


def _m_sh_ic(c):
    return "sh -ic " + _sq(c)


def _m_eval(c):
    return "eval " + _sq(c)


def _m_eval_in_if(c):
    return "if true; then eval " + _sq(c) + "; fi"


MUTATORS = [
    ("comment with an apostrophe", _m_comment_apostrophe),
    ("comment with a quote", _m_comment_quote),
    ("comment with a backtick", _m_comment_backtick),
    ("comment with a paren", _m_comment_paren),
    ("trailing comment", _m_trailing_comment),
    ("apostrophe in an echo before", _m_echo_apostrophe),
    ("quoted heredoc before", _m_heredoc_quoted),
    ("plain heredoc before", _m_heredoc_plain),
    ("command substitution before", _m_cmdsubst),
    ("backticks before", _m_backticks),
    ("nested quotes before", _m_nested_quotes),
    ("escaped quote before", _m_escaped_quote),
    ("ansi-c quoting before", _m_ansi_c),
    ("subshell wrap", _m_subshell),
    ("leading blank lines", _m_leading_blank),
    ("assignment prefix", _m_assignment),
    ("semicolon chain after", _m_semicolon),
    ("pipe after", _m_pipe),
    ("env prefix", _m_env_prefix),
    # --- syntax classes, chosen from the grammar rather than from past bugs -----
    ("here-string: bare", _m_herestring),
    ("here-string: word looks like a marker", _m_herestring_marker_word),
    ("here-string: quoted with an apostrophe", _m_herestring_quoted),
    ("arithmetic: left shift", _m_arith_lshift),
    ("arithmetic: right shift", _m_arith_rshift),
    ("arithmetic: nested shifts", _m_arith_nested),
    ("comment: contains a heredoc marker", _m_comment_heredoc_marker),
    ("comment: contains a here-string", _m_comment_herestring),
    ("comment: contains redirects", _m_comment_redirect),
    ("param expansion: # is not a comment", _m_param_strip),
    ("param expansion: default with an apostrophe", _m_param_default_quote),
    ("param expansion: length ${#x}", _m_param_length),
    ("process substitution", _m_procsub),
    ("redirect: 2>&1 merge", _m_redirect_merge),
    ("redirect: append", _m_redirect_append),
    ("brace expansion", _m_brace_expansion),
    ("line continuation", _m_line_continuation),
    ("conditional: < inside [[ ]]", _m_double_bracket),
    ("wrap: if/then", _m_wrap_if),
    ("wrap: for/do", _m_wrap_for),
    ("wrap: brace group", _m_wrap_braces),
    ("wrap: after a while loop", _m_wrap_while),
    ("wrap: && chain", _m_wrap_and_or),
    ("wrap: until/do", _m_wrap_until),
    ("wrap: else branch", _m_wrap_else),
    ("wrap: elif branch", _m_wrap_elif),
    ("wrap: case arm", _m_wrap_case),
    ("wrap: ! negation", _m_wrap_negation),
    ("wrap: as an if CONDITION", _m_wrap_if_condition),
    ("wrap: function body", _m_wrap_function),
    ("wrap: nested if+for", _m_wrap_nested),
    ("wrapper: bash -c", _m_bash_c),
    ("wrapper: bash -lc", _m_bash_lc),
    ("wrapper: sh -ic", _m_sh_ic),
    ("wrapper: eval", _m_eval),
    ("wrapper: eval inside if", _m_eval_in_if),
]


def seeds(roots):
    """Constructed, so this runs on any machine with no transcript corpus and no
    personal data. Every seed must ALREADY be refused; that is asserted before use."""
    g = roots["game"]
    ref = roots["reference"]
    saves = roots["saves"]
    prof = roots["profile"]
    docs = roots["documents"]
    d = "r" + "m"
    s = "s" + "ed"
    return [
        ("game delete", d + " -rf " + QU + g + QU),
        ("extensions wholesale", d + " -rf " + QU + g + "/extensions" + QU),
        ("reference delete", d + " -rf " + QU + ref + QU),
        ("one deployed mod", d + " -rf " + QU + g + "/extensions/amod" + QU),
        ("savegame delete", d + " -f " + QU + saves + "/save_001.xml.gz" + QU),
        ("write under documents", "echo x > " + QU + docs + "/n.txt" + QU),
        ("recursive search at reference", "grep -rn foo " + QU + ref + QU),
        ("rg at reference", "rg foo " + QU + ref + QU),
        ("git add -A", "git add -A"),
        ("sed -i in the game", s + " -i " + AP + "s/a/b/" + AP + " " + QU + g + "/f.xml" + QU),
        ("cd then relative delete", "cd " + QU + g + QU + " && " + d + " -rf extensions"),
        ("profile search by name", "grep -n foo " + QU + prof + "/content.xml" + QU),
    ]


def run(mod, roots, policy, verbose=False):
    """-> (findings, exercised, seeds_used)."""
    findings = []
    exercised = 0
    used = 0
    for name, cmd in seeds(roots):
        base = verdict(mod, cmd, roots, policy)
        if base == "allow":
            continue                       # not a seed: there is nothing to weaken
        used += 1
        for mname, fn in MUTATORS:
            mutant = fn(cmd)
            after = verdict(mod, mutant, roots, policy)
            exercised += 1
            if RANK[after] >= RANK[base]:
                continue
            if not parses(mutant):         # bash would not run it either
                continue
            findings.append((name, mname, base, after, mutant))
            if verbose:
                print("   BYPASS %s / %s : %s -> %s" % (name, mname, base, after))
    return findings, exercised, used


def resolve_roots():
    probe = ('HOOK_DIR="%s"; . "%s/_x4-env.sh" >/dev/null 2>&1; '
             'for v in X4_GAME X4_REFERENCE X4_TOOLKIT X4_PROFILE X4_MODS '
             'X4_DOCUMENTS X4_SAVES; do printf "%%s\\t%%s\\n" "$v" "${!v}"; done'
             % (HOOKS.as_posix(), HOOKS.as_posix()))
    out = subprocess.run([BASH, "-c", probe], capture_output=True, text=True).stdout
    env = dict(l.split("\t", 1) for l in out.splitlines() if "\t" in l)
    return {"game": env.get("X4_GAME", ""), "reference": env.get("X4_REFERENCE", ""),
            "toolkit": env.get("X4_TOOLKIT", ""), "profile": env.get("X4_PROFILE", ""),
            "mods": env.get("X4_MODS", ""), "documents": env.get("X4_DOCUMENTS", ""),
            "saves": env.get("X4_SAVES", "")}


def plant_known_hole(src):
    """Re-create the pre-fix scanner: no comment stripping, no escape handling, no
    unparseable report. Returns None if an anchor has moved -- in which case the control
    cannot be planted and no clean result below would mean anything."""
    holed = src.replace("    body = strip_comments(strip_heredocs(cmd))",
                        "    body = cmd")
    holed = holed.replace(
        "        elif c == chr(92) and i + 1 < len(s):" + NL
        + "            yield c, False" + NL
        + "            i += 1" + NL
        + "            yield s[i], False          # escaped: never opens a quote",
        "        elif False:" + NL
        + "            yield c, False" + NL
        + "            i += 1" + NL
        + "            yield s[i], False")
    holed = holed.replace('"unparseable_command": ends_open_quote(body),',
                          '"unparseable_command": False,')
    holed = holed.replace("    stripped = body", "    stripped = strip_heredocs(cmd)")
    return None if holed == src else holed


def main():
    if BASH is None:
        print("REFUSING: no bash found, and bash is the oracle here.", file=sys.stderr)
        return 2

    roots = resolve_roots()
    if not all(roots[k] for k in ("game", "reference", "saves")):
        # SYNTHETIC roots, not a skip. Nothing here touches the filesystem -- hook_facts
        # compares strings -- so invented paths exercise every rule exactly as real ones
        # do, and they make the run deterministic on a machine with no X4 installed
        # (every CI runner). A skip in CI is indistinguishable from a pass, which is the
        # failure this whole session has been about.
        roots = SYNTHETIC_ROOTS.copy()
        print("no X4 install detected -- using synthetic roots. Every rule is still "
              "exercised: this analysis is pure string comparison.")

    # The verdict map comes from protect-bash.sh. A short parse REFUSES: with an empty
    # map every seed reads "allow", every seed is skipped as nothing-to-weaken, and the
    # run prints "no bypass found" over having exercised nothing.
    probe = load_facts(HOOKS / "hook_facts.py")
    names = set(probe.facts({"tool_input": {"command": "true", "timeout": 0,
                                            "run_in_background": False}}, roots))
    policy = policy_map(names)
    if len(policy) < MIN_MAPPED_RULES:
        print("REFUSING: only %d rule(s) parsed out of protect-bash.sh (expected at least "
              "%d). The verdict map is derived from that file, and a short parse would "
              "make every seed read 'allow' and the run report success over nothing."
              % (len(policy), MIN_MAPPED_RULES), file=sys.stderr)
        return 2
    unmapped = sorted(n for n in names if n not in policy
                      and n not in ("command", "cwd", "timeout", "background"))
    if unmapped:
        print("note: %d fact(s) hook_facts emits carry no verdict in protect-bash.sh "
              "and are therefore NOT fuzzed: %s" % (len(unmapped), ", ".join(unmapped)))
    print("policy: %d rules derived from protect-bash.sh (%d deny, %d ask, %d advise)"
          % (len(policy), sum(v == "deny" for v in policy.values()),
             sum(v == "ask" for v in policy.values()),
             sum(v == "advise" for v in policy.values())))

    src = (HOOKS / "hook_facts.py").read_text(encoding="utf-8")
    holed = plant_known_hole(src)
    if holed is None:
        print("REFUSING: could not plant the control defect -- an anchor has moved, so a "
              "clean run below would prove nothing. Fix the anchors in "
              "plant_known_hole().", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "hook_facts.py"
        p.write_text(holed, encoding="utf-8")
        ctl, ctl_n, _ = run(load_facts(p), roots, policy)
    if not ctl:
        print("REFUSING: the known defect was planted and the fuzzer found NOTHING over "
              "%d mutants. It cannot detect a bypass, so a clean result from it is "
              "meaningless." % ctl_n, file=sys.stderr)
        return 2
    print("control: pre-fix scanner planted -> %d bypass(es) rediscovered over %d "
          "mutants. This fuzzer can fail." % (len(ctl), ctl_n))

    findings, exercised, used = run(load_facts(HOOKS / "hook_facts.py"), roots,
                                    policy, verbose="--verbose" in sys.argv)
    print("fuzzed %d mutants: %d seeds (of %d, the rest already allow) x %d mutators"
          % (exercised, used, len(seeds(roots)), len(MUTATORS)))
    if exercised == 0:
        print("REFUSING: nothing was exercised.", file=sys.stderr)
        return 2
    if not findings:
        print("no bypass found: every mutant kept its seed's verdict.")
        return 0
    print()
    print("*** %d BYPASS(ES) — the syntax changed, the dangerous operand did not ***"
          % len(findings))
    for seed, mut, before, after, cmd in findings:
        print("  %-30s via %-30s %s -> %s" % (seed, mut, before, after))
        print("      %s" % cmd.replace(NL, " <NL> ")[:150])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

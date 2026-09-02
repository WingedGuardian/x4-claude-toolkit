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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOKS = REPO / ".claude" / "hooks"
# NOT plain "bash": on Windows that resolves to the WSL stub in System32, which has
# cost this workspace three separate debugging sessions.
BASH = shutil.which("bash.exe") or shutil.which("bash")

RANK = {"deny": 3, "ask": 2, "advise": 1, "allow": 0}

# Which fact carries which verdict, read off protect-bash.sh. Policy lives there.
DENY = ("rm_targets_reference", "rm_hits_game", "sed_i_in_game_or_profile",
        "timeout_over_cap", "git_add_all", "dollarq_after_pipe", "write_to_tmp",
        "durable_python_open_w", "profile_search_by_name", "xrcat_reunpack")
ASK = ("rm_in_x4_dir", "rm_saves", "writes_documents", "longjob_foreground",
       "unparseable_command")

NL = chr(10)
AP = chr(39)     # apostrophe
QU = chr(34)     # double quote
BS = chr(92)     # backslash
BT = chr(96)     # backtick


def load_facts(path):
    spec = importlib.util.spec_from_file_location("hf_fuzz", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verdict(mod, cmd, roots):
    f = mod.facts({"tool_input": {"command": cmd, "timeout": 0,
                                  "run_in_background": False}}, roots)
    if any(f.get(k) for k in DENY):
        return "deny"
    if any(f.get(k) for k in ASK):
        return "ask"
    return "allow"


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


def run(mod, roots, verbose=False):
    """-> (findings, exercised, seeds_used)."""
    findings = []
    exercised = 0
    used = 0
    for name, cmd in seeds(roots):
        base = verdict(mod, cmd, roots)
        if base == "allow":
            continue                       # not a seed: there is nothing to weaken
        used += 1
        for mname, fn in MUTATORS:
            mutant = fn(cmd)
            after = verdict(mod, mutant, roots)
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
        print("REFUSING: roots did not resolve, so every seed would be 'allow' and this "
              "would report a vacuous clean sweep.", file=sys.stderr)
        return 2

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
        ctl, ctl_n, _ = run(load_facts(p), roots)
    if not ctl:
        print("REFUSING: the known defect was planted and the fuzzer found NOTHING over "
              "%d mutants. It cannot detect a bypass, so a clean result from it is "
              "meaningless." % ctl_n, file=sys.stderr)
        return 2
    print("control: pre-fix scanner planted -> %d bypass(es) rediscovered over %d "
          "mutants. This fuzzer can fail." % (len(ctl), ctl_n))

    findings, exercised, used = run(load_facts(HOOKS / "hook_facts.py"), roots,
                                    verbose="--verbose" in sys.argv)
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

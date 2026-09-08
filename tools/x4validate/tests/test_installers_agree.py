"""The two installers must copy the SAME set of items.

Nothing pinned them equal, and the drift was real: `mods` -- the game extension this
release ships -- was missing from BOTH lists, and the README's instruction to "copy that
folder into {game}/extensions/" pointed at a directory neither installer created. A
divergence here is invisible until a user on the other platform reports a missing file.

Both lists are PARSED from their files rather than restated here, so this test cannot
become a third copy of the same list, drifting independently of the two it guards.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent
SH = ROOT / "install.sh"
PS1 = ROOT / "install.ps1"

#: A lone backslash is a LINE CONTINUATION, not an item. Dropping it by name beats
#: stripping "backslash then newline": the first version of this parser did that, still
#: yielded a stray token, and reported a DIVERGENCE between the two installers when the
#: lists were in fact identical. A parser bug that looks like a finding is the worst kind.
NOT_AN_ITEM = {chr(92), ""}


def sh_items() -> list[str]:
    """The `X4_COPY_ITEMS=` list in install.sh.

    It used to be parsed out of `for item in ... ; do`. The list is now named ONCE
    and consumed by three callers -- the copy, the dry-run listing, and the
    locked-target precheck -- so the definition is what to read. Parsing a loop
    header would now find `$X4_COPY_ITEMS` and report an empty set as agreement.
    """
    text = SH.read_text(encoding="utf-8")
    m = re.search(r'^X4_COPY_ITEMS="([^"]*)"', text, re.M)
    assert m, "could not find X4_COPY_ITEMS in install.sh"
    return sorted(w for w in m.group(1).split() if w not in NOT_AN_ITEM)


def ps1_items() -> list[str]:
    """The `$X4CopyItems = @(...)` list in install.ps1."""
    text = PS1.read_text(encoding="utf-8")
    m = re.search(r"\$X4CopyItems\s*=\s*@\((.*?)\)", text, re.S)
    assert m, "could not find $X4CopyItems in install.ps1"
    return sorted(w for w in re.findall(r"'([^']+)'", m.group(1)) if w not in NOT_AN_ITEM)


def test_both_installers_copy_the_same_items():
    sh, ps = sh_items(), ps1_items()
    # A parser returning nothing -- or implausibly little -- must not be able to report
    # "the lists agree". Both installers ship well over a dozen items.
    assert len(sh) >= 12, f"install.sh parse looks broken: {sh}"
    assert len(ps) >= 12, f"install.ps1 parse looks broken: {ps}"
    only_sh = sorted(set(sh) - set(ps))
    only_ps = sorted(set(ps) - set(sh))
    assert not only_sh and not only_ps, (
        "the installers copy different item sets.\n"
        f"  only install.sh : {only_sh}\n"
        f"  only install.ps1: {only_ps}")


def test_the_shipped_game_extension_is_in_both():
    """The specific regression this file exists for: `mods/` carries the game extension
    x4live needs, and the README tells users to copy it into {game}/extensions/."""
    assert "mods" in sh_items(), "install.sh does not copy mods/"
    assert "mods" in ps1_items(), "install.ps1 does not copy mods/"


# --- the round-4 installer fixes, guarded in BOTH files -----------------------------
#
# Five of round 3's own fixes shipped guarded by nothing. These are source-level
# assertions rather than a full install, because the E2E harnesses live outside the
# repo -- but each names the exact construct whose absence was the defect, so
# reverting any one of them turns a named test red.

def test_neither_installer_compares_source_and_destination_as_STRINGS():
    """`$SRC` is MSYS-style under Git Bash; `--toolkit` is whatever the user pasted,
    and every documented path is Windows-style. Comparing the two spellings as text
    said COPY for a destination that IS the source, `cp -r` reported "are the same
    file", and `set -e` killed the script before the FAILED accounting existed -- no
    banner, no failed: line, no config. MEASURED in a sandbox: rc 1.
    """
    sh = SH.read_text(encoding="utf-8")
    ps = PS1.read_text(encoding="utf-8")
    assert '[ "$SRC" != "$TOOLKIT" ]' not in sh, (
        "install.sh is back to a string comparison of source vs destination")
    assert "($SRC -ne $Toolkit)" not in ps, (
        "install.ps1 is back to a string comparison of source vs destination")
    assert "same_dir()" in sh, "install.sh lost its canonical same-directory test"
    assert "function Test-SameDir" in ps, (
        "install.ps1 lost its canonical same-directory test")


def test_every_powershell_WRITER_consults_the_dry_run_flag():
    """`$DryRun` was consulted in exactly ONE place -- inside Show-Target, which the
    global arm never reaches. MEASURED in a sandbox: `-Method global -DryRun`
    overwrote x4-paths.env and printed "=== install complete (global) ===".

    The guard belongs in the WRITERS, as install.sh does it, so an arm added later
    cannot write without passing through one of them.
    """
    ps = PS1.read_text(encoding="utf-8")
    assert "function Refuse-IfDryRun" in ps, "install.ps1 lost its dry-run gate"
    assert ps.count("Refuse-IfDryRun '") >= 3, (
        f"only {ps.count(chr(82) + 'efuse-IfDryRun ' + chr(39))} writer(s) call the "
        "dry-run gate; Write-PathsEnv, Copy-Toolkit and Install-Global all must")


def test_both_installers_back_up_the_path_config_before_rewriting_it():
    """install.sh moved this backup INTO write_paths_env so a caller could not be
    added without one; PowerShell's Write-PathsEnv, which all three methods call,
    never got it. Fourth 'fixed in bash, absent in PowerShell' of the release."""
    sh = SH.read_text(encoding="utf-8")
    ps = PS1.read_text(encoding="utf-8")
    # THE BACKUP, not the reassurance. This asserted a literal that occurs exactly
    # once per file -- inside the echo/Write-Host that ANNOUNCES the backup, never
    # in the code that takes one. Mutants deleting the backup and keeping the
    # message stayed GREEN, which is precisely the failure the code's own comment
    # names: "a backup that silently did not happen is worse than none, because
    # the message above would have said it did".
    assert 'cp "$f" "$f.bak-' in sh, (
        "install.sh no longer COPIES the path config to a .bak (a message saying "
        "it did is not the same thing)")
    assert "Copy-Item -LiteralPath $f -Destination ($f + '.bak-'" in ps, (
        "install.ps1 no longer COPIES the path config to a .bak")


def test_neither_installer_copies_the_tree_WHOLESALE():
    """The virtualenv must be excluded at COPY time, not deleted on arrival.

    It used to be copied in full -- 1,407 files, 38 MB -- and pruned afterwards, while
    the CHANGELOG said "A virtualenv no longer travels." The waste was the small half:
    under `set -e` a failure among those copies aborts BEFORE both the prune and the
    config restore, so the most expensive thing copied was also the likeliest thing to
    break the install, and nothing wanted it copied.

    An end-state check cannot tell "never copied" from "copied then removed" -- the
    existing "the SOURCE venv did not travel" case passed before the fix too. So this
    pins the CONSTRUCT, and the stubbed-copy probes in the scratchpad pin the
    behaviour: 0 invocations naming .venv on either platform.
    """
    sh = SH.read_text(encoding="utf-8")
    ps = PS1.read_text(encoding="utf-8")
    assert 'cp -r "$SRC/$item"' not in sh, (
        "install.sh copies each item wholesale again; the prune list is not consulted "
        "until after the copy")
    assert "copy_item()" in sh, "install.sh lost its excluding copy walk"
    assert "Copy-Item -Recurse -Force -LiteralPath $s -Destination $dest" not in ps, (
        "install.ps1 copies each item wholesale again")
    assert "function Copy-Excluding" in ps, "install.ps1 lost its excluding copy walk"


def test_the_prune_list_is_named_ONCE_in_each_installer():
    """Both walks and both prunes read the same list, so an entry cannot be
    half-applied. Two hand-written copies is how the two passes drifted in the first
    place -- one of them was not running at all."""
    sh = SH.read_text(encoding="utf-8")
    ps = PS1.read_text(encoding="utf-8")
    assert sh.count("X4_COPY_PRUNE=") == 1, "install.sh defines the prune list twice"
    assert ps.count("$X4CopyPrune = @(") == 1, (
        "install.ps1 defines the prune list twice")


# --- the round-11 installer fixes (Track 2 audit), guarded in BOTH files -------------

def _ps_single_quoted(s: str) -> list[str]:
    """Every PowerShell single-quoted literal in `s`, with '' decoded to a quote.

    Hand-scanned rather than regexed: `''` is BOTH an empty string and the escape for
    one quote, and a regex that gets that wrong reports a defect where there is none --
    which this file's own parser note already warns about.
    """
    out, i, n = [], 0, len(s)
    while i < n:
        if s[i] != "'":
            i += 1
            continue
        i += 1
        buf = []
        while i < n:
            if s[i] == "'":
                if i + 1 < n and s[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                i += 1
                break
            buf.append(s[i])
            i += 1
        out.append("".join(buf))
    return out


def _trim_call_arguments(text: str) -> list[tuple[int, str]]:
    """(line number, argument text) for every .Trim/.TrimStart/.TrimEnd call."""
    calls = []
    for m in re.finditer(r"\.Trim(?:Start|End)?\(", text):
        depth, i = 0, m.end() - 1
        while i < len(text):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        calls.append((text.count("\n", 0, m.start()) + 1, text[m.end():i]))
    return calls


def test_no_powershell_char_argument_is_an_EMPTY_string():
    """`.TrimStart('', '/')` shipped in v3.0.0 and made `-Method global` throw on EVERY
    run, on Windows PowerShell 5.1 and pwsh 7 alike: an empty string is not convertible
    to [char], and $ErrorActionPreference='Stop' makes that fatal.

    It threw AFTER x4-paths.env had been rewritten and the first x4-* skill had been
    force-copied over the user's own, so it was a partial write, not a clean failure.

    The cause was a lone backslash collapsing to nothing at authoring time, which is why
    this pins the CLASS -- any Trim argument that is not exactly one character -- rather
    than the one line. Test-SameDir already used [char]92/[char]47 to dodge the same
    hazard; the empty literal is what that habit exists to prevent.
    """
    text = PS1.read_text(encoding="utf-8")
    calls = _trim_call_arguments(text)
    # A scanner that finds nothing must not be able to report "all arguments are fine".
    assert len(calls) >= 3, f"the Trim-call scanner looks broken: found {calls}"
    bad = []
    for lineno, args in calls:
        for lit in _ps_single_quoted(args):
            if len(lit) != 1:
                bad.append(f"install.ps1:{lineno}  .Trim*(...{args}...)  literal {lit!r} "
                           f"is {len(lit)} characters, not 1")
    assert not bad, (
        "a Trim/TrimStart/TrimEnd argument is not a single character, so it cannot "
        "convert to [char] and the call throws at runtime:\n  " + "\n  ".join(bad))


def test_both_installers_GATE_the_global_destination():
    r"""Fifth 'fixed in bash, absent in PowerShell' of this release.

    -OverExisting is consulted in exactly one place on the PowerShell side --
    Assert-Direction, on the copy-to-destination path -- which the global arm never
    reaches. So `-Method global` force-overwrote a user's own ~/.claude\skills\x4-*
    with no prompt and no backup of the skills, and rewrote their global settings.json.
    MEASURED in a sandbox: an edited x4-balance\SKILL.md was replaced by the shipped
    one; only the settings.json half was ever backed up.

    install.sh has refused this since its own global arm was gated. install.ps1 now does
    the same, and this pins BOTH so neither can lose it alone.
    """
    sh = SH.read_text(encoding="utf-8")
    ps = PS1.read_text(encoding="utf-8")
    # ⚠ THIS ASSERTION USED TO PIN THE DEFECT. It required the literal
    # `ls "$_hc/skills"/x4-*` -- the DESTINATION glob that named a user's own
    # `x4-mycustom/` as a file the install "would REPLACE". Correcting the gate to
    # enumerate from the toolkit therefore turned a NAMED parity test red, which
    # reads as a regression to whoever hits it. Inverted in the same commit as the
    # fix, and stated here so it cannot be quietly reverted to make a red go away.
    #
    # A substring is the wrong instrument for this either way (BLIND-SPOTS F109):
    # what matters is that BOTH gates enumerate the SOURCE, which
    # test_install_over_existing.py now asserts behaviourally on both installers.
    assert 'ls "$_hc/skills"/x4-*' not in sh, (
        "install.sh's global gate is enumerating the DESTINATION again; it must list "
        "only skills this toolkit ships, or a user's own x4-* is named as at risk")
    assert '"$TOOLKIT/.claude/skills/"x4-*' in sh, (
        "install.sh's global arm no longer checks for pre-existing x4-* skills")
    assert "function Assert-GlobalOverExisting" in ps, (
        "install.ps1 lost its global over-existing gate")
    # The FUNCTION BODY, not a fixed character window: the explanatory comment is long
    # enough that a magic slice cut the assertion off and reported a defect that was not
    # there -- the parser-bug-as-finding this file already warns about.
    body = ps.split("function Assert-GlobalOverExisting", 1)[1]
    body = body.split(chr(10) + "function ", 1)[0]   # no backslash escapes here
    assert "$OverExisting" in body, (
        "install.ps1's global gate no longer consults -OverExisting, so it either "
        "always refuses or never does")
    assert "exit 2" in body, (
        "install.ps1's global gate no longer refuses with rc 2, the toolkit-wide "
        "refusal code install.sh uses for the same gate")


def test_the_global_gate_runs_BEFORE_the_global_arm_writes_anything():
    """Position is the whole point. Refusing from inside Install-Global would leave
    x4-paths.env already rewritten -- a partial write, which is the shape of the bug
    rather than a fix. install.sh gates ahead of its own write_paths_env for the same
    reason. MEASURED in a sandbox: with the gate in place, a refused run creates no
    x4-paths.env at all.
    """
    ps = PS1.read_text(encoding="utf-8")
    m = re.search(r"'global'\s*\{(.*?)\n  \}", ps, re.S)
    assert m, "could not find the 'global' dispatch arm in install.ps1"
    arm = m.group(1)
    assert "Assert-GlobalOverExisting" in arm, (
        "the global arm does not call the over-existing gate")
    assert "Write-PathsEnv" in arm, "the global arm parse looks wrong: no Write-PathsEnv"
    assert arm.index("Assert-GlobalOverExisting") < arm.index("Write-PathsEnv"), (
        "the global gate runs AFTER Write-PathsEnv, so a refusal still leaves the "
        "user's path config rewritten")


def test_the_global_claude_dir_is_resolved_in_ONE_place():
    r"""Two copies of `CLAUDE_CONFIG_DIR else USERPROFILE\.claude` is how the gate and
    the installer would come to disagree about which directory they are talking about.
    This file's history is a list of things that drifted for exactly that reason."""
    ps = PS1.read_text(encoding="utf-8")
    assert ps.count("$env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR }") == 1, (
        "install.ps1 resolves the global Claude config directory in more than one "
        "place; use Get-GlobalClaudeDir")

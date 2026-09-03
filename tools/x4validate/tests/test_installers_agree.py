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
    """The `for item in ... ; do` list inside copy_toolkit()."""
    text = SH.read_text(encoding="utf-8")
    m = re.search(r"for item in\s+(.*?);\s*do", text, re.S)
    assert m, "could not find copy_toolkit's item list in install.sh"
    return sorted(w for w in m.group(1).split() if w not in NOT_AN_ITEM)


def ps1_items() -> list[str]:
    """The `$items = '...','...'` literal inside Copy-Toolkit."""
    text = PS1.read_text(encoding="utf-8")
    m = re.search(r"\$items\s*=", text)
    assert m, "could not find Copy-Toolkit's item list in install.ps1"
    out: list[str] = []
    for line in text[m.start():].splitlines():
        out += re.findall(r"'([^']+)'", line)
        if not line.rstrip().endswith(","):     # the literal ends here
            break
    return sorted(w for w in out if w not in NOT_AN_ITEM)


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
    assert "x4-paths.env.bak-" in sh, "install.sh no longer backs up the path config"
    assert "x4-paths.env.bak-" in ps, "install.ps1 no longer backs up the path config"

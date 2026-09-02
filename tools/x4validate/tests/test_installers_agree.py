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

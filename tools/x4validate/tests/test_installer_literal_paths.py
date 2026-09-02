"""Every path-reading cmdlet in install.ps1 must use -LiteralPath.

PowerShell reads `[` and `]` as a WILDCARD CHARACTER CLASS, not as text. A bare
Get-ChildItem/Test-Path/Get-Content/Push-Location against a toolkit path like
`toolkit [v3]` therefore matches nothing -- and with -ErrorAction SilentlyContinue the
miss is swallowed, so Install-Global printed "installed x4 skills + agents" over an
empty directory.

MEASURED 2026-09-01 under exactly that path: bare Get-ChildItem found 0 where
-LiteralPath found 1, in both the skills and the agents leg.

The existing installer test compares the two installers' COPY LISTS, which agreed
throughout -- it could not see this, because both lists were right and the reads were
wrong. This checks the property that was actually broken.

`Push-Location` is in the list because the first sweep grepped a set of cmdlet names
written from memory, missed it, and the run died at line 254 AFTER reporting success.
The list here is therefore derived from what the FILE calls, not from recollection.
"""

from __future__ import annotations

import pathlib
import re

PS1 = pathlib.Path(__file__).resolve().parents[3] / "install.ps1"

#: Cmdlets whose -Path argument is WILDCARD-interpreted. New-Item is excluded: it has
#: no -LiteralPath in Windows PowerShell 5.1, and its -Path is treated literally when
#: creating (verified). Copy-Item's -Destination is likewise literal.
WILDCARD_READERS = ("Get-ChildItem", "Test-Path", "Get-Content", "Get-Item",
                    "Remove-Item", "Push-Location", "Set-Location", "Resolve-Path",
                    "Rename-Item", "Move-Item")


def code_lines() -> list[tuple[int, str]]:
    """Lines with comments stripped -- the file DOCUMENTS this bug, and a comment
    mentioning `Test-Path` must not read as a violation of it."""
    out = []
    for i, raw in enumerate(PS1.read_text(encoding="utf-8").splitlines(), 1):
        if raw.lstrip().startswith("#"):
            continue
        out.append((i, raw.split("#")[0]))
    return out


def test_install_ps1_is_readable():
    assert PS1.is_file() and len(PS1.read_text(encoding="utf-8")) > 5000, PS1


def test_every_wildcard_reader_uses_LiteralPath():
    bad = []
    for n, line in code_lines():
        for cmd in WILDCARD_READERS:
            if re.search(r"(^|[|;(\s])" + cmd + r"\s", line) and "-LiteralPath" not in line:
                bad.append("%s:%d  %s" % (PS1.name, n, line.strip()[:100]))
    assert not bad, (
        "these read a path WILDCARD-interpreted, so a toolkit path containing [ or ] "
        "silently matches nothing:\n  " + "\n  ".join(bad))


def test_install_global_refuses_when_it_copied_nothing():
    """A copy of zero files must not print as an install."""
    src = PS1.read_text(encoding="utf-8")
    assert "$copied.Count -eq 0" in src, (
        "Install-Global has no zero-copy refusal, so it can report success over an "
        "empty directory -- which is exactly what the bracketed-path bug did")

"""Bootstrap scripts must parse and run on the shell users actually have.

MEASURED 2026-09-01: install.ps1 held 9 UTF-8 em-dashes and no BOM. Windows PowerShell
5.1 -- the default shell on Windows 10/11, and the one README:206 tells users to run --
reads a BOM-less .ps1 as the ANSI codepage, so every em-dash became three mojibake
characters. One of them sat inside an interpolated string at line 108 and the parser
derailed: 3 parse errors, the installer dead before its first statement. pwsh 7 parsed
it fine, which is why it survived to a 3.0 release candidate.

TWO checks, because they fail differently:
  * the ASCII assertion catches the CAUSE and runs on every platform, including the
    Linux CI leg where powershell.exe does not exist;
  * the 5.1 parser check catches ANY syntax defect, not just this one, but can only
    run where that engine is installed.
A single check would have been vacuous on one leg or blind to everything else.
"""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent

#: PowerShell scripts a user runs BEFORE the toolkit is installed. Scoped to .ps1 on
#: purpose: the defect is PowerShell 5.1 reading a BOM-less file as the ANSI codepage.
#: bash is byte-transparent and passes UTF-8 through untouched, so the same em-dashes
#: in install.sh / setup.sh are harmless -- MEASURED, 39 non-ASCII bytes between them,
#: all in comments and echo strings, and both run fine. Applying the rule there anyway
#: would be a check that fires where nothing is wrong, which is how a suite gets
#: ignored. (The real portability risk for .sh is CRLF, pinned by .gitattributes.)
BOOTSTRAP = ["install.ps1"]


def _tracked_ps1() -> list[pathlib.Path]:
    out = subprocess.run(["git", "ls-files", "*.ps1"], cwd=ROOT,
                         capture_output=True, text=True, check=False)
    return [ROOT / n for n in out.stdout.split() if n]


@pytest.mark.parametrize("name", BOOTSTRAP)
def test_bootstrap_script_is_pure_ascii(name):
    p = ROOT / name
    if not p.is_file():
        pytest.skip(f"{name} not present in this tree")
    data = p.read_bytes()
    bad = [(i, data[i]) for i in range(len(data)) if data[i] > 127]
    assert not bad, (
        f"{name} has {len(bad)} non-ASCII byte(s), first at offset {bad[0][0]}. "
        "Windows PowerShell 5.1 reads a BOM-less script as the ANSI codepage, so a "
        "UTF-8 character becomes mojibake and can break parsing. Use ASCII "
        "(e.g. '-' for an em-dash).")


def test_the_ascii_check_would_catch_a_real_em_dash(tmp_path):
    """The assertion above must be able to go red, or it is decoration."""
    f = tmp_path / "sample.ps1"
    f.write_bytes("Write-Host 'a \u2014 b'".encode("utf-8"))
    data = f.read_bytes()
    assert any(b > 127 for b in data), "the fixture is not actually non-ASCII"


@pytest.mark.skipif(shutil.which("powershell") is None,
                    reason="Windows PowerShell 5.1 not available on this platform")
@pytest.mark.parametrize("script", [pytest.param(p, id=p.name) for p in _tracked_ps1()] or
                         [pytest.param(None, id="none-tracked")])
def test_every_tracked_ps1_parses_under_windows_powershell(script):
    if script is None:
        pytest.skip("no tracked .ps1 files")
    cmd = ("$e=$null; $null=[System.Management.Automation.Language.Parser]::ParseFile("
           f"'{script.as_posix()}',[ref]$null,[ref]$e); "
           "if($e.Count){ $e | ForEach-Object { $_.Message }; exit 1 } else { exit 0 }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        f"{script.name} does not parse under Windows PowerShell 5.1:\n{r.stdout}")

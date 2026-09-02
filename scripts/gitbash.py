r"""Locate a REAL bash on Windows, never the WSL stub.

`shutil.which("bash")` on Windows returns `C:\Windows\System32\bash.exe` -- the WSL
launcher -- whenever Git Bash is not on PATH, which is the normal state in PowerShell
and in CI. That stub either fails outright or runs a Linux bash in a filesystem where
`C:/Users/...` does not exist, so every path-shaped assertion silently changes meaning.

MEASURED 2026-09-01 from PowerShell on this machine:
    shutil.which("bash")     -> C:\Windows\system32\bash.EXE
    shutil.which("bash.exe") -> C:\Windows\system32\bash.exe
The second is the important one: `scripts/fuzz-guard.py` carried
`which("bash.exe") or which("bash")` with a comment saying it avoided the WSL stub.
It did not -- the stub IS named bash.exe. A defence that names the right threat and
does not stop it is worse than none, because it stops anyone looking again.

Cost so far: three separate debugging sessions in this workspace, and one harness
written to falsify a guard that was itself running under WSL.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

#: Directories whose `bash.exe` is a stub, not a shell.
_STUB_DIRS = ("system32", "syswow64", "windowsapps")

#: Where Git for Windows actually installs. `usr/bin` first: it is the real binary,
#: `bin/bash.exe` being a wrapper.
_GIT_BASH = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
    r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
)


def _is_stub(p: str | os.PathLike) -> bool:
    parts = [q.lower() for q in Path(p).parts]
    return any(d in parts for d in _STUB_DIRS)


def find_bash() -> str | None:
    """A usable bash, or None. Never a WSL/Store stub on Windows."""
    override = os.environ.get("X4_BASH")
    if override and Path(override).is_file():
        return override

    if sys.platform != "win32":
        return shutil.which("bash")

    for c in _GIT_BASH:
        if Path(c).is_file():
            return c

    # Fall back to PATH, skipping the stubs. `which` returns only the first hit, so the
    # PATH is walked by hand -- otherwise a System32 hit masks a real Git Bash later on.
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        cand = Path(d) / "bash.exe"
        if cand.is_file() and not _is_stub(cand):
            return str(cand)
    return None

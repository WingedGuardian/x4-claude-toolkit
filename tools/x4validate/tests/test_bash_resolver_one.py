r"""B1 (install red-team, 2026-10-04): on a stock Windows machine the guards' bash resolver
found nothing usable, so `install.ps1 -Agent all` ended INCOMPLETE (the OpenCode renderer
needs bash) and x4doctor FAILED six rows.

WHY. Git for Windows puts only `<Git>\cmd` on PATH by default; `bash` on a stock PATH is the
WSL launcher in System32 (or the WindowsApps alias). `x4guard.resolve_bash()` asked only
X4_BASH and the FIRST `bash` on PATH, refused the stub, and stopped -- while
`scripts/gitbash.py` (used by the tools and tests) and install.ps1's Find-GitBash both knew
the Git for Windows locations. Three resolvers, two answers.

NOW ONE RESOLVER: `x4guard.resolve_bash()` -- it must live in the guard (a deployed guard copy
has no scripts/ to import) -- probes X4_BASH, then the Git for Windows locations, then PATH
past any stub; `scripts/gitbash.find_bash()` delegates to it. A failure names the exact
`setx X4_BASH "..."` line. install.ps1's PowerShell Find-GitBash runs before any Python is
known, so it stays PowerShell, pinned to the same locations below and exporting X4_BASH for
the rest of its run.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
XG = REPO / "agent" / "guards" / "claude-hooks" / "x4guard.py"

win = pytest.mark.skipif(sys.platform != "win32", reason="Windows path shapes and stubs")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def xg(monkeypatch, tmp_path):
    for k in ("X4_BASH", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "ProgramW6432"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    return _load(XG, "x4guard_b1")


def _fake_bash(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"MZ")
    return p


@win
def test_a_stock_PATH_still_finds_Git_for_Windows_by_its_install_location(xg, monkeypatch, tmp_path):
    pf = tmp_path / "PF"
    want = _fake_bash(pf / "Git" / "bin" / "bash.exe")
    monkeypatch.setenv("ProgramFiles", str(pf))
    monkeypatch.setenv("PATH", r"C:\Windows\System32;" + str(pf / "Git" / "cmd"))
    assert xg.resolve_bash() == (str(want), None)


@win
def test_LOCALAPPDATA_Programs_is_a_Git_location_too(xg, monkeypatch, tmp_path):
    la = tmp_path / "LA"
    want = _fake_bash(la / "Programs" / "Git" / "bin" / "bash.exe")
    monkeypatch.setenv("LOCALAPPDATA", str(la))
    assert xg.resolve_bash()[0] == str(want)


@win
def test_a_real_bash_on_PATH_past_the_stub_is_found(xg, monkeypatch, tmp_path):
    real = _fake_bash(tmp_path / "bin" / "bash.exe")
    monkeypatch.setenv("PATH", r"C:\Windows\System32;" + str(real.parent))
    assert xg.resolve_bash()[0] == str(real)


@win
@pytest.mark.parametrize("stub", [r"C:\Windows\System32\bash.exe", r"C:\Windows\SysWOW64\bash.exe",
                                  r"C:\Users\x\AppData\Local\Microsoft\WindowsApps\bash.exe"])
def test_every_stub_is_refused_even_named_by_X4_BASH(xg, monkeypatch, stub):
    monkeypatch.setenv("X4_BASH", stub)
    bash, why = xg.resolve_bash()
    assert bash is None and "stub" in why, (bash, why)


@win
def test_nothing_found_names_the_exact_setx_line(xg):
    bash, why = xg.resolve_bash()
    assert bash is None
    assert re.search(r'setx X4_BASH "[^"]+bash\.exe"', why), why


def test_X4_BASH_naming_a_real_file_wins(xg, tmp_path, monkeypatch):
    b = _fake_bash(tmp_path / "my" / "bash.exe")
    monkeypatch.setenv("X4_BASH", str(b))
    assert xg.resolve_bash() == (str(b), None)


def test_X4_BASH_naming_nothing_is_an_error_never_a_silent_fallback(xg, tmp_path, monkeypatch):
    monkeypatch.setenv("X4_BASH", str(tmp_path / "absent" / "bash.exe"))
    bash, why = xg.resolve_bash()
    assert bash is None and "X4_BASH" in why


def test_gitbash_DELEGATES_to_the_guards_resolver(monkeypatch, tmp_path):
    """ONE resolver: gitbash.find_bash() answers exactly what x4guard.resolve_bash() answers."""
    gb = _load(REPO / "scripts" / "gitbash.py", "gitbash_b1")
    b = _fake_bash(tmp_path / "x" / "bash.exe")
    monkeypatch.setenv("X4_BASH", str(b))
    assert gb.find_bash() == str(b)
    calls = []
    real = gb._resolver()
    monkeypatch.setattr(real, "resolve_bash", lambda: calls.append(1) or ("Z", None))
    assert gb.find_bash() == "Z" and calls, "gitbash.find_bash did not ask x4guard.resolve_bash"


def test_install_ps1_Find_GitBash_probes_the_same_locations():
    """Pinned, not shared: the PowerShell installer resolves bash before any Python is known."""
    ps = (REPO / "install.ps1").read_text(encoding="utf-8")
    fn = ps[ps.index("function Find-GitBash"):]
    fn = fn[:fn.index("\n}\n")]
    for base in ("$env:ProgramFiles", "${env:ProgramFiles(x86)}", "LOCALAPPDATA"):
        assert base in fn, base
    src = XG.read_text(encoding="utf-8")
    for base in ('"ProgramFiles"', '"ProgramFiles(x86)"', '"LOCALAPPDATA"'):
        assert base in src, base


def test_install_ps1_exports_the_found_bash_BEFORE_the_opencode_renderer_runs():
    ps = (REPO / "install.ps1").read_text(encoding="utf-8")
    export = ps.index("$env:X4_BASH = ")
    first_render = ps.index("Write-OpenCodeConfig $Toolkit")
    assert export < first_render, "X4_BASH is exported only after the renderer already ran"
    assert 'setx X4_BASH' in ps

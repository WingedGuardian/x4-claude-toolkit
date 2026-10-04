"""The toy agent (spec 7.10): an adapter written only from ADAPTING.md passes `x4guard conformance`,
and the conformance it passes can fail: each mutant of the adapter turns it red on a non-empty case
set whose unmutated control is green.

The adapter (fixtures/toy_agent/toy_adapter.py) was written by a cold subagent given only
ADAPTING.md, TOY-AGENT.md, toy_agent.py and payloads/ (2026-10-03, recorded in
docs/superpowers/measurements/2026-10-03-adapting-cold-test.md). It is committed UNEDITED; its
profile differs from the cold one only in the adapter's path ({TOOLKIT}-relative).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
X4GUARD = REPO / ".claude" / "hooks" / "x4guard.py"
TOY = REPO / "tools" / "x4validate" / "tests" / "fixtures" / "toy_agent"

pytestmark = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("jq")),
                                reason="needs Git Bash and jq -- toy conformance NOT checked here")


def _engine():
    spec = importlib.util.spec_from_file_location("x4conformance", REPO / "scripts" / "x4conformance.py")
    xc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(xc)
    return xc


def conformance(cases: Path, adapter: Path, *extra):
    return subprocess.run([sys.executable, str(X4GUARD), "conformance", "--profile", str(TOY / "profile.json"),
                           "--cases", str(cases), "--workers", "4", *extra, "--", sys.executable, str(adapter)],
                          capture_output=True, text=True, timeout=3600)


def _write(rows, path):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _recorded_inert(xc, row):
    """True when the row's RECORDED guard verdict says the guards could not check it."""
    try:
        hso = json.loads(row.get("out") or "{}").get("hookSpecificOutput") or {}
    except ValueError:
        return False
    return bool(xc.NOT_CHECKED.search(hso.get("permissionDecisionReason") or ""))


def test_the_toy_adapter_passes_full_conformance(conformance_dump, tmp_path):
    rows, _ = conformance_dump
    r = conformance(_write(rows, tmp_path / "all.jsonl"), TOY / "toy_adapter.py")
    assert r.returncode == 0, r.stdout[-4000:]
    assert "GAP" not in r.stdout                       # the toy maps all four kinds
    assert "extras: 6" in r.stdout                     # the neutral PowerShell/space/drive cases ran too


#: name -> ([(exact source text, replacement), ...], row selector). Each `old` is the COLD adapter's
#: real text and must occur exactly once; a mutant needing a fault to express (a crash) injects it.
MUTANTS = {
    "always_allow": ([("    deny(reason)\n", "    return\n")],
                     lambda r: r.get("got") == "deny"),
    "ask_as_plain_deny": ([("NEEDS YOUR APPROVAL: ", "")],
                          lambda r: r.get("got") == "ask"),
    "powershell_as_bash": ([('"--shell", sh,', '"--shell", "bash",')],
                           lambda r: r.get("kind") == "shell-powershell"),
    "ignores_workdir": ([('cwd = payload.get("workdir") or os.getcwd()', "cwd = os.getcwd()")],
                        lambda r: r.get("relative")),
    "crash_exits_nonzero": ([('    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))',
                              '    payload = json.loads(sys.stdin.buffer.read().decode("utf-8")); 1 / 0'),
                             ('deny("X4 GUARD INERT: toy adapter error (%s)" % type(e).__name__)', "raise")],
                            lambda r: r.get("got") == "deny"),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_each_adapter_mutant_turns_conformance_red(name, conformance_dump, tmp_path):
    xc = _engine()
    edits, pick = MUTANTS[name]
    rows, _ = conformance_dump
    pool = rows + xc.extra_rows(REPO, rows)
    # Only rows the GUARDS can check: a row whose recorded verdict is "could not check"
    # (e.g. the guards-off untranslatable-PowerShell case) is inert by design, the engine
    # rightly refuses to count it (R2-F3), and it cannot express any mutant. Judged with the
    # engine's own NOT_CHECKED pattern, never a copy of it.
    chosen = [r for r in pool if pick(r) and not _recorded_inert(xc, r)][:12]
    assert chosen, f"{name}: no case can express this defect -- add one, never drop the mutant"
    cases = _write(chosen, tmp_path / "c.jsonl")
    src = (TOY / "toy_adapter.py").read_text(encoding="utf-8")
    mutated = src
    for old, new in edits:
        assert src.count(old) == 1, f"{name}: anchor {old!r} matches {src.count(old)} times"
        mutated = mutated.replace(old, new)
    mutant = tmp_path / "toy_adapter.py"; mutant.write_text(mutated, encoding="utf-8")
    floor = ("--no-extras", "--min-cases", str(len(chosen)))   # `chosen` already holds any extras it needs
    control = conformance(cases, TOY / "toy_adapter.py", *floor)
    assert control.returncode == 0, control.stdout[-3000:]          # control first
    red = conformance(cases, mutant, *floor)
    assert red.returncode == 1, (name, red.returncode, red.stdout[-3000:])


def test_live_canary_through_the_toy_agent_blocks_and_its_control_writes(conformance_dump, tmp_path):
    """ADAPTING.md 5(b): the agent itself, not the adapter alone, refuses the decoy write. The
    sandbox layout with the toolkit OUTSIDE the game folder: inside it, dev/ is game install too."""
    rows, _ = conformance_dump
    env_row = next(r for r in rows if r["env"].get("X4_TOOLKIT") and r["env"].get("X4_GAME")
                   and not Path(r["env"]["X4_TOOLKIT"]).resolve().is_relative_to(Path(r["env"]["X4_GAME"]).resolve()))
    tk = Path(env_row["env"]["X4_TOOLKIT"])
    script = tmp_path / "calls.jsonl"
    decoy, ctrl = tk / "reference" / "canary-decoy.xml", tk / "dev" / "mymod" / "canary-ok.xml"
    _write([{"tool": "write_file", "args": {"target": str(decoy), "text": "x"}, "workdir": str(tk)},
            {"tool": "write_file", "args": {"target": str(ctrl), "text": "x"}, "workdir": str(tk)}], script)
    env = {k: v for k, v in os.environ.items() if not k.startswith("X4_") or "KEY" in k}
    env.update(env_row["env"], X4_GUARD_PY=str(X4GUARD))
    r = subprocess.run([sys.executable, str(TOY / "toy_agent.py"), "--root", str(tk), "--script", str(script),
                        "--hook", f'"{sys.executable}" "{TOY / "toy_adapter.py"}"'],
                       capture_output=True, text=True, env=env, timeout=600)
    try:
        assert not decoy.exists() and "TOY-BLOCK" in r.stdout, r.stdout
        assert ctrl.exists(), r.stdout                               # the control: writes do happen
    finally:
        ctrl.unlink(missing_ok=True)
        decoy.unlink(missing_ok=True)


def test_the_fail_mode_measurement_reproduces_the_toys_fail_open(tmp_path):
    """ADAPTING.md 1: the procedure finds what TOY-AGENT.md says -- exit 2 does NOT block the toy."""
    hook = tmp_path / "exit2.py"; hook.write_text("import sys; sys.exit(2)\n", encoding="utf-8")
    deny = tmp_path / "deny.py"; deny.write_text("print('TOY-BLOCK control')\n", encoding="utf-8")
    target = tmp_path / "decoy.txt"
    script = _write([{"tool": "write_file", "args": {"target": str(target), "text": "x"}, "workdir": str(tmp_path)}],
                    tmp_path / "s.jsonl")

    def go(h):
        target.unlink(missing_ok=True)
        subprocess.run([sys.executable, str(TOY / "toy_agent.py"), "--root", str(tmp_path), "--script", str(script),
                        "--hook", f'"{sys.executable}" "{h}"'], capture_output=True, timeout=60)
        return target.exists()
    assert go(deny) is False          # deny control blocks
    assert go(hook) is True           # exit 2 runs the call: fails open, as documented

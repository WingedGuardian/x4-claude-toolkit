"""`x4guard conformance` -- the CLI wrapper's exit codes; every refusal has a passing twin."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
X4GUARD = REPO / ".claude" / "hooks" / "x4guard.py"


def run(*args, env=None, cwd=None):
    return subprocess.run([sys.executable, str(X4GUARD), *args], capture_output=True, text=True,
                          env=env, cwd=cwd, timeout=1800)


def test_help_lists_conformance():
    r = run("--help")
    assert r.returncode == 0 and "conformance" in r.stdout


def test_conformance_help_is_the_engines():
    r = run("conformance", "--help")
    assert r.returncode == 0 and "--profile" in r.stdout and "--min-cases" in r.stdout


def test_an_empty_case_file_refuses_with_3(tmp_path):
    (tmp_path / "c.jsonl").write_text("", encoding="utf-8")
    r = run("conformance", "--profile", "claude", "--cases", str(tmp_path / "c.jsonl"), "--min-cases", "1")
    assert r.returncode == 3, (r.stdout, r.stderr)
    assert "0 replayed" in r.stdout


def _rows(tmp_path, commands, env):
    return "".join(json.dumps({"label": f"probe{i}", "hook": "protect-bash.sh",
                               "payload": {"tool_name": "Bash", "tool_input": {"command": c}, "cwd": str(tmp_path)},
                               "cwd": str(tmp_path), "env": env}) + "\n" for i, c in enumerate(commands))


@pytest.mark.skipif(not (shutil.which("bash") and shutil.which("jq")), reason="needs Git Bash and jq")
def test_extras_that_could_not_be_built_are_2_not_a_silent_skip(tmp_path):
    """R2-F3 (v4.0.0 review): no case row names a sandbox X4_TOOLKIT, so the neutral extras
    (PowerShell, spaces, drive paths) were dropped with a note and the run still passed."""
    f = tmp_path / "c.jsonl"; f.write_text(_rows(tmp_path, ["echo hi"], {}), encoding="utf-8")
    r = run("conformance", "--profile", "claude", "--cases", str(f), "--min-cases", "1")
    assert r.returncode == 2 and "extras" in r.stdout, (r.returncode, r.stdout)
    r = run("conformance", "--profile", "claude", "--cases", str(f), "--min-cases", "1", "--no-extras")
    assert r.returncode == 0, (r.returncode, r.stdout)                          # twin: asked for none


@pytest.mark.skipif(not (shutil.which("bash") and shutil.which("jq")), reason="needs Git Bash and jq")
def test_every_case_inert_on_both_sides_is_3(tmp_path):
    """R2-F3: a broken X4_PYTHON made every guard and the adapter say "checked nothing"; the run
    reported 3 of 3 agree, exit 0 (MEASURED by the reviewer, review/scratch-R2/inert_cases.jsonl)."""
    f = tmp_path / "c.jsonl"
    f.write_text(_rows(tmp_path, ["echo hi", "git add -A"], {"X4_PYTHON": "no-such-python-x4"}), encoding="utf-8")
    r = run("conformance", "--profile", "claude", "--cases", str(f), "--min-cases", "1", "--no-extras")
    assert r.returncode == 3 and "inert" in r.stdout.lower(), (r.returncode, r.stdout)


def test_a_missing_profile_is_2(tmp_path):
    r = run("conformance", "--profile", str(tmp_path / "nope.json"))
    # The message too: argparse's own usage error is ALSO exit 2, and the bare code passed
    # before the subcommand existed (MEASURED, lane G RED run).
    assert r.returncode == 2 and "profile not found" in r.stdout, (r.stdout, r.stderr)


def test_no_adapter_command_anywhere_is_2(tmp_path):
    p = json.loads((REPO / "scripts" / "conformance-profiles" / "claude.json").read_text(encoding="utf-8"))
    del p["command"]
    f = tmp_path / "p.json"; f.write_text(json.dumps(p), encoding="utf-8")
    r = run("conformance", "--profile", str(f))
    assert r.returncode == 2 and "command" in (r.stdout + r.stderr)


def test_a_copy_that_cannot_find_its_toolkit_is_2(tmp_path):
    lone = tmp_path / "x4guard.py"; shutil.copy(X4GUARD, lone)
    env = {k: v for k, v in os.environ.items() if k != "X4_TOOLKIT"}
    r = subprocess.run([sys.executable, str(lone), "conformance", "--profile", "claude"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 2 and "x4conformance.py" in r.stderr


def test_TWIN_the_same_copy_with_X4_TOOLKIT_finds_the_engine(tmp_path):
    lone = tmp_path / "x4guard.py"; shutil.copy(X4GUARD, lone)
    env = dict(os.environ, X4_TOOLKIT=str(REPO))
    r = subprocess.run([sys.executable, str(lone), "conformance", "--help"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0 and "--profile" in r.stdout


@pytest.mark.skipif(not (shutil.which("bash") and shutil.which("jq")), reason="needs Git Bash and jq")
def test_below_the_floor_is_3_and_the_twin_with_the_floor_lowered_is_0(conformance_dump, tmp_path):
    rows, _ = conformance_dump
    few = [r for r in rows if r["payload"].get("tool_name") == "Bash"][:3]
    f = tmp_path / "few.jsonl"; f.write_text("".join(json.dumps(r) + "\n" for r in few), encoding="utf-8")
    assert run("conformance", "--profile", "claude", "--cases", str(f), "--no-extras").returncode == 3
    assert run("conformance", "--profile", "claude", "--cases", str(f), "--no-extras",
               "--min-cases", "3").returncode == 0


@pytest.mark.skipif(not (shutil.which("bash") and shutil.which("jq")), reason="needs Git Bash and jq")
def test_a_disagreeing_adapter_is_1_and_names_the_case(conformance_dump, tmp_path):
    """The red twin of the floor test above: the SAME three cases through an adapter that always
    allows. Without it nothing shows the CLI can return 1 at all."""
    rows, _ = conformance_dump
    few = [r for r in rows if r["payload"].get("tool_name") == "Bash" and r["got"] == "deny"][:3]
    assert few
    f = tmp_path / "few.jsonl"; f.write_text("".join(json.dumps(r) + "\n" for r in few), encoding="utf-8")
    r = run("conformance", "--profile", "claude", "--cases", str(f), "--no-extras", "--min-cases", "1",
            "--", sys.executable, "-c", "pass")
    assert r.returncode == 1, r.stdout
    assert few[0]["label"] in r.stdout


def test_the_double_dash_adapter_argv_overrides_the_profile_and_is_stripped(tmp_path):
    (tmp_path / "c.jsonl").write_text("", encoding="utf-8")
    r = run("check", "--kind", "write", "--path", "x")  # sanity: check still works unchanged
    assert r.returncode == 0 and json.loads(r.stdout)["v"] == 1
    r = run("conformance", "--profile", "claude", "--cases", str(tmp_path / "c.jsonl"),
            "--min-cases", "1", "--", sys.executable, "-c", "pass")
    assert r.returncode == 3 and "adapter: " in r.stdout and " -- " not in r.stdout.split("adapter: ")[1].splitlines()[0]

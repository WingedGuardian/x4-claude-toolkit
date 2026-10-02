r"""`scripts/x4doctor.py` -- per-agent guard health that can never say OK about nothing.

WHY. Codex skips a hook it has not reviewed SILENTLY, a WSL bash stub makes a guard fail
open, and a Store `python` stub resolves and then cannot run -- each of these leaves an
install that LOOKS guarded. x4doctor answers "are the guards live HERE?" per agent target,
and its contract is the point of this file: every row is OK, FAIL, UNKNOWN or N/A; a run
in which nothing answered is exit 2, never 0; a check that raises is UNKNOWN with the
exception named, never a dropped row.

Every FAIL clause has a twin that must be OK, so a check that denies everything cannot
read as a working check (CLAUDE.md #26).
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
DOCTOR = REPO / "scripts" / "x4doctor.py"
_spec = importlib.util.spec_from_file_location("x4doctor", DOCTOR)
doc = importlib.util.module_from_spec(_spec)
sys.modules["x4doctor"] = doc
_spec.loader.exec_module(doc)


def _run(*args, env=None, cwd=None):
    return subprocess.run([sys.executable, str(DOCTOR), *args], capture_output=True, text=True,
                          timeout=300, env=env, cwd=cwd)


# --- Task 5: the result model and the exit contract ----------------------------------- #

def test_no_agent_target_at_root_is_exit_2_never_ok(tmp_path):
    r = _run("--root", str(tmp_path))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "OK" not in r.stdout.split()


def test_summarise_all_UNKNOWN_is_not_ok():
    assert doc.exit_code([doc.Check("a", "claude", doc.UNKNOWN, "x")]) == 2
    rows = [doc.Check("a", "claude", doc.OK, ""), doc.Check("b", "claude", doc.UNKNOWN, "x")]
    assert doc.exit_code(rows) == 3


def test_summarise_zero_answered_is_2():
    assert doc.exit_code([]) == 2
    assert doc.exit_code([doc.Check("a", "codex", doc.NA, "not installed")]) == 2


def test_any_FAIL_wins_over_OK():
    rows = [doc.Check("a", "claude", doc.OK, ""), doc.Check("b", "claude", doc.FAIL, "")]
    assert doc.exit_code(rows) == 1


def test_TWIN_all_OK_is_0():
    assert doc.exit_code([doc.Check("a", "claude", doc.OK, ""), doc.Check("b", "codex", doc.NA, "")]) == 0


def test_a_check_that_RAISES_becomes_UNKNOWN_with_the_exception_named():
    def boom(ctx):
        raise RuntimeError("kaput")
    row = doc.run_check("boom", "claude", boom, ctx=None)
    assert row.status == doc.UNKNOWN and "kaput" in row.detail and "RuntimeError" in row.detail


def test_a_check_returning_an_unknown_STATUS_is_UNKNOWN_not_trusted():
    row = doc.run_check("odd", "claude", lambda ctx: ("GREEN", "looks fine"), ctx=None)
    assert row.status == doc.UNKNOWN and "GREEN" in row.detail


def test_json_output_is_one_parseable_document(tmp_path):
    r = _run("--root", str(tmp_path), "--json")
    d = json.loads(r.stdout)
    assert d["v"] == 1 and isinstance(d["checks"], list) and d["root"]
    assert set(d["targets"]) == {"claude", "codex", "generic"}
    assert d["exit"] == r.returncode == 2


def test_detect_targets(tmp_path):
    assert doc.detect_targets(tmp_path) == {"claude": False, "codex": False, "generic": False}
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".codex" / "hooks").mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("a", encoding="utf-8")
    assert doc.detect_targets(tmp_path) == {"claude": True, "codex": True, "generic": True}


def test_TWIN_a_bare_claude_dir_holding_only_the_path_config_is_NOT_the_claude_target(tmp_path):
    """Every install writes .claude/x4-paths.env -- a Codex-only install included."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "x4-paths.env").write_text("X4_TOOLKIT=x\n", encoding="utf-8")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text("#\n", encoding="utf-8")
    assert doc.detect_targets(tmp_path) == {"claude": False, "codex": False, "generic": False}


def test_the_verdict_line_comes_FIRST(tmp_path):
    """CLAUDE.md #38: a truncated report keeps its head, so the verdict goes there."""
    r = _run("--root", str(tmp_path))
    assert r.stdout.splitlines()[0].startswith("x4doctor:"), r.stdout[:300]


def test_an_unknown_agent_filter_is_a_usage_error(tmp_path):
    assert _run("--root", str(tmp_path), "--agent", "opencode").returncode == 2


def test_the_doctor_is_stdlib_only():
    """It must run when uv or the venv is the thing that is broken."""
    import ast
    tree = ast.parse(DOCTOR.read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module.split(".")[0])
    stdlib = set(sys.stdlib_module_names)
    assert mods <= stdlib, sorted(mods - stdlib)

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


# --- Task 6: toolchain and roots, as the GUARDS resolve them ------------------------- #
#
# The fixture copies the repo's generated .claude/hooks into a sandbox root so the REAL
# _x4-env.sh and x4guard.py run, with a path config pointing at sandbox dirs.

_LEAKY = ("X4_TOOLKIT", "X4_GAME", "X4_REFERENCE", "X4_PROFILE", "X4_MODS", "X4_PYTHON",
          "X4_CONFIG", "X4_BASH", "CLAUDE_PROJECT_DIR", "X4_GUARD", "JQ", "CODEX_HOME")


class Sandbox:
    def __init__(self, root, game, ref, codex_home):
        self.root, self.game, self.ref, self.codex_home = root, game, ref, codex_home

    def ctx(self, **kw):
        return doc.Ctx(root=self.root, **kw)

    def rows(self, fn):
        return {r.id: r for r in fn(self.ctx())}


def _env_file(path: Path, **kv):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join('%s="%s"\n' % (k, Path(v).as_posix()) for k, v in kv.items()),
                    encoding="utf-8")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    for name in _LEAKY:
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "root"
    game = tmp_path / "game"
    ref = root / "reference"
    for d in (game / "extensions", ref / "libraries"):
        d.mkdir(parents=True)
    (ref / "libraries" / "wares.xml").write_text("<wares/>\n", encoding="utf-8")
    shutil.copytree(REPO / ".claude" / "hooks", root / ".claude" / "hooks",
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    shutil.copy2(REPO / ".claude" / "settings.json", root / ".claude" / "settings.json")
    _env_file(root / ".claude" / "x4-paths.env", X4_TOOLKIT=root, X4_GAME=game, X4_REFERENCE=ref)
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    return Sandbox(root, game, ref, codex_home)


def _write_failing_exe(path: Path) -> None:
    """Resolves (bash `command -v` finds it) and cannot run: exits 9, prints nothing --
    the Store-stub shape."""
    path.write_bytes(b"#!/bin/sh\nexit 9\n")
    path.chmod(0o755)


@pytest.mark.skipif(os.name != "nt", reason="the WSL-stub trap is Windows-only")
def test_a_WSL_stub_first_on_PATH_is_a_FAIL_naming_it(sandbox, tmp_path, monkeypatch):
    stub = tmp_path / "Windows" / "System32"
    stub.mkdir(parents=True)
    (stub / "bash.exe").write_bytes(b"MZ")              # resolves; cannot run anything
    monkeypatch.setenv("PATH", str(stub) + os.pathsep + os.environ["PATH"])
    rows = sandbox.rows(doc.check_toolchain)
    assert rows["bash.path"].status == doc.FAIL, rows["bash.path"]
    assert "System32" in rows["bash.path"].detail


def test_TWIN_the_real_bash_is_OK(sandbox):
    rows = sandbox.rows(doc.check_toolchain)
    assert rows["bash.guards"].status == doc.OK, rows["bash.guards"]
    if os.name == "nt":
        assert rows["bash.path"].status in (doc.OK, doc.FAIL)   # the developer's PATH decides
    else:
        assert rows["bash.path"].status == doc.NA


def test_a_python_that_RESOLVES_but_FAILS_is_FAIL_not_OK(sandbox, tmp_path, monkeypatch):
    bad = tmp_path / "badpy"
    bad.mkdir()
    _write_failing_exe(bad / "python")
    monkeypatch.setenv("X4_PYTHON", (bad / "python").as_posix())
    rows = sandbox.rows(doc.check_toolchain)
    assert rows["python.guards"].status == doc.FAIL, rows["python.guards"]
    assert "does not run" in rows["python.guards"].detail


def test_an_UNRESOLVABLE_X4_PYTHON_is_FAIL_naming_the_variable(sandbox, tmp_path, monkeypatch):
    monkeypatch.setenv("X4_PYTHON", (tmp_path / "no-such-python").as_posix())
    rows = sandbox.rows(doc.check_toolchain)
    assert rows["python.guards"].status == doc.FAIL and "X4_PYTHON" in rows["python.guards"].detail


def test_TWIN_a_working_python_is_OK(sandbox):
    rows = sandbox.rows(doc.check_toolchain)
    assert rows["python.guards"].status == doc.OK, rows["python.guards"]


def test_a_MISSING_jq_with_python_is_OK_degraded_and_says_so(sandbox, tmp_path, monkeypatch):
    monkeypatch.setenv("JQ", (tmp_path / "no-such-jq").as_posix())
    rows = sandbox.rows(doc.check_toolchain)
    assert rows["jq"].status == doc.OK and "fall back" in rows["jq"].detail, rows["jq"]


def test_a_MISSING_jq_AND_python_is_FAIL(sandbox, tmp_path, monkeypatch):
    monkeypatch.setenv("JQ", (tmp_path / "no-such-jq").as_posix())
    monkeypatch.setenv("X4_PYTHON", (tmp_path / "no-such-python").as_posix())
    rows = sandbox.rows(doc.check_toolchain)
    assert rows["jq"].status == doc.FAIL, rows["jq"]


def test_bash_and_python_DISAGREEING_on_reference_is_FAIL(sandbox, tmp_path, monkeypatch):
    """X4_CONFIG is honoured by the guards' _x4-env.sh and ignored by the tools'
    _paths: the two then protect and read different trees."""
    other = tmp_path / "other-ref"
    other.mkdir()
    _env_file(tmp_path / "elsewhere.env", X4_TOOLKIT=sandbox.root, X4_GAME=sandbox.game,
              X4_REFERENCE=other)
    monkeypatch.setenv("X4_CONFIG", (tmp_path / "elsewhere.env").as_posix())
    rows = sandbox.rows(doc.check_roots)
    r = rows["roots.agree"]
    assert r.status == doc.FAIL, r
    assert "other-ref" in r.detail and "reference" in r.detail


def test_TWIN_agreeing_roots_are_OK(sandbox):
    rows = sandbox.rows(doc.check_roots)
    assert rows["roots.agree"].status == doc.OK, rows["roots.agree"]
    assert rows["roots.reference"].status == doc.OK, rows["roots.reference"]
    assert rows["roots.game"].status == doc.OK, rows["roots.game"]


def test_an_UNSET_game_root_is_FAIL(sandbox):
    _env_file(sandbox.root / ".claude" / "x4-paths.env", X4_TOOLKIT=sandbox.root,
              X4_REFERENCE=sandbox.ref)
    rows = sandbox.rows(doc.check_roots)
    assert rows["roots.game"].status == doc.FAIL, rows["roots.game"]


def test_a_reference_not_unpacked_YET_is_UNKNOWN_not_FAIL_nor_OK(sandbox, tmp_path):
    _env_file(sandbox.root / ".claude" / "x4-paths.env", X4_TOOLKIT=sandbox.root,
              X4_GAME=sandbox.game, X4_REFERENCE=tmp_path / "not-yet")
    rows = sandbox.rows(doc.check_roots)
    assert rows["roots.reference"].status == doc.UNKNOWN, rows["roots.reference"]


def test_the_roots_rows_NAME_the_config_file_each_side_read(sandbox):
    rows = sandbox.rows(doc.check_roots)
    assert "x4-paths.env" in rows["roots.agree"].detail


def test_the_guards_config_variable_still_exists():
    """x4doctor reads `_x4_cfg` (an internal name) to say which config the guards read.
    If _x4-env.sh renames it, this goes red instead of the doctor going quiet."""
    src = (REPO / "agent" / "guards" / "claude-hooks" / "_x4-env.sh").read_text(encoding="utf-8")
    assert "_x4_cfg=" in src and "x4_resolve_python()" in src and "X4_PY=" in src


def test_a_GENERIC_only_root_has_no_guard_toolchain_and_says_so(tmp_path, monkeypatch):
    for name in _LEAKY:
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "AGENTS.md").write_text("a\n", encoding="utf-8")
    rows = {r.id: r for r in doc.check_toolchain(doc.Ctx(root=tmp_path))}
    assert {r.status for r in rows.values()} == {doc.NA}, rows


def test_two_spellings_of_ONE_git_install_agree():
    """MEASURED on the author's machine: x4guard resolves Git/usr/bin/bash.exe (PATH),
    scripts/gitbash.py resolves Git/bin/bash.exe (its launcher). One install, one bash."""
    assert doc.same_bash("C:/Program Files/Git/usr/bin/bash.exe", "C:/Program Files/Git/bin/bash.exe")
    assert doc.same_bash("/usr/bin/bash", "/usr/bin/bash")


def test_TWIN_two_DIFFERENT_git_installs_do_not_agree():
    assert not doc.same_bash("C:/Program Files/Git/usr/bin/bash.exe", "D:/PortableGit/bin/bash.exe")
    assert not doc.same_bash("/usr/bin/bash", "/opt/homebrew/bin/bash")

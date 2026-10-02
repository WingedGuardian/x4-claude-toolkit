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
    (tmp_path / ".agents" / "skills").mkdir(parents=True)
    assert doc.detect_targets(tmp_path) == {"claude": True, "codex": True, "generic": True}


def test_TWIN_a_users_own_AGENTS_md_alone_is_NOT_the_generic_target(tmp_path):
    """MEASURED on the author's game root: a hand-written AGENTS.md read as 'generic
    installed'. The toolkit's generic target is its skills payload; the file is reported
    by the instructions row instead."""
    (tmp_path / "AGENTS.md").write_text("my notes\n", encoding="utf-8")
    assert doc.detect_targets(tmp_path)["generic"] is False


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
    (tmp_path / ".agents" / "skills").mkdir(parents=True)
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


# --- Task 7: deployed-vs-source parity per agent target ------------------------------- #

GEN_BANNER = "<!-- GENERATED from agent/ -->"


def _tree(base: Path, files: dict) -> Path:
    for rel, content in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return base


def _pair(tmp_path, monkeypatch, src: dict, dst: dict) -> doc.Ctx:
    for name in _LEAKY:
        monkeypatch.delenv(name, raising=False)
    tk = _tree(tmp_path / "tk", src)
    root = _tree(tmp_path / "root", dst)
    monkeypatch.setenv("X4_TOOLKIT", str(tk))
    return doc.Ctx(root=root)


_CLAUDE = {".claude/settings.json": "{}\n", ".claude/hooks/a.sh": "echo a\n",
           "CLAUDE.md": "# C\n" + GEN_BANNER + "\n"}


def _prow(ctx, cid):
    rows = {r.id: r for r in doc.check_parity(ctx)}
    return rows[cid]


def test_parity_identical_is_OK_with_a_count(tmp_path, monkeypatch):
    r = _prow(_pair(tmp_path, monkeypatch, _CLAUDE, _CLAUDE), "parity.claude")
    assert r.status == doc.OK and "2 file" in r.detail, r


def test_parity_DRIFT_is_FAIL_naming_the_file(tmp_path, monkeypatch):
    dst = dict(_CLAUDE, **{".claude/hooks/a.sh": "echo EDITED\n"})
    r = _prow(_pair(tmp_path, monkeypatch, _CLAUDE, dst), "parity.claude")
    assert r.status == doc.FAIL and "hooks/a.sh" in r.detail, r


def test_parity_a_CRLF_only_difference_is_not_drift(tmp_path, monkeypatch):
    dst = dict(_CLAUDE, **{".claude/hooks/a.sh": b"echo a\r\n"})
    r = _prow(_pair(tmp_path, monkeypatch, _CLAUDE, dst), "parity.claude")
    assert r.status == doc.OK, r


def test_parity_with_NO_source_is_UNKNOWN(tmp_path, monkeypatch):
    ctx = _pair(tmp_path, monkeypatch, _CLAUDE, _CLAUDE)
    monkeypatch.delenv("X4_TOOLKIT")
    ctx = doc.Ctx(root=ctx.root)
    r = _prow(ctx, "parity.claude")
    assert r.status == doc.UNKNOWN and "X4_TOOLKIT" in r.detail, r


def test_same_tree_without_source_is_UNKNOWN_not_OK(tmp_path, monkeypatch):
    """An in-game install IS the toolkit, and runtime-only (decision #9): no agent/ source
    to regenerate from, so parity cannot be checked there -- and must say so."""
    ctx = _pair(tmp_path, monkeypatch, _CLAUDE, _CLAUDE)
    monkeypatch.setenv("X4_TOOLKIT", str(ctx.root))
    r = _prow(doc.Ctx(root=ctx.root), "parity.claude")
    assert r.status == doc.UNKNOWN and "agent/" in r.detail, r


def test_a_target_with_no_TargetSpec_is_UNKNOWN_never_NA(tmp_path, monkeypatch):
    files = dict(_CLAUDE, **{".codex/hooks/x.sh": "#\n", "AGENTS.md": GEN_BANNER + "\n"})
    ctx = _pair(tmp_path, monkeypatch, files, files)
    monkeypatch.setattr(doc, "_parity_targets", lambda mod: {"claude": mod.TARGETS["claude"]})
    r = _prow(ctx, "parity.codex")
    assert r.status == doc.UNKNOWN and "TargetSpec" in r.detail, r


def test_an_absent_target_is_NA(tmp_path, monkeypatch):
    r = _prow(_pair(tmp_path, monkeypatch, _CLAUDE, _CLAUDE), "parity.codex")
    assert r.status == doc.NA, r


def test_a_claude_target_WITHOUT_CLAUDE_md_is_FAIL(tmp_path, monkeypatch):
    """Claude Code reads AGENTS.md only when there is no CLAUDE.md (MEASURED, lane A):
    the Claude target without its file runs on the wrong instructions."""
    dst = {k: v for k, v in _CLAUDE.items() if k != "CLAUDE.md"}
    r = _prow(_pair(tmp_path, monkeypatch, _CLAUDE, dst), "instructions.claude")
    assert r.status == doc.FAIL, r


def test_TWIN_a_claude_target_WITH_CLAUDE_md_is_OK(tmp_path, monkeypatch):
    r = _prow(_pair(tmp_path, monkeypatch, _CLAUDE, _CLAUDE), "instructions.claude")
    assert r.status == doc.OK, r


def test_a_codex_target_reading_a_HAND_WRITTEN_AGENTS_md_is_FAIL(tmp_path, monkeypatch):
    files = dict(_CLAUDE, **{".codex/hooks/x.sh": "#\n", "AGENTS.md": "# my own notes\n"})
    r = _prow(_pair(tmp_path, monkeypatch, files, files), "instructions.codex")
    assert r.status == doc.FAIL and "GENERATED" in r.detail, r


def test_TWIN_a_codex_target_reading_the_GENERATED_AGENTS_md_is_OK(tmp_path, monkeypatch):
    files = dict(_CLAUDE, **{".codex/hooks/x.sh": "#\n", "AGENTS.md": "# A\n" + GEN_BANNER + "\n"})
    r = _prow(_pair(tmp_path, monkeypatch, files, files), "instructions.codex")
    assert r.status == doc.OK, r


def test_a_hand_written_AGENTS_md_with_NO_codex_target_is_NOTED_not_failed(tmp_path, monkeypatch):
    """The author's game root today: a personal AGENTS.md, Codex not installed. Any Codex
    session there reads it, so it is NAMED -- but it is the user's file, not a failure."""
    dst = dict(_CLAUDE, **{"AGENTS.md": "# my own notes\n"})
    r = _prow(_pair(tmp_path, monkeypatch, _CLAUDE, dst), "instructions.agents_md")
    assert r.status == doc.OK and "hand-written" in r.detail, r


def test_a_source_whose_comparer_PREDATES_TargetSpec_falls_back_to_the_doctors_own(tmp_path, monkeypatch):
    """MEASURED 2026-10-02: X4_TOOLKIT named a checkout whose deploy_parity.py had no
    TARGETS yet, and every row read 'no TargetSpec for claude' -- true of that file, false
    of the question. The comparer is code; the SOURCE tree is still X4_TOOLKIT's."""
    files = dict(_CLAUDE, **{"tools/x4validate/gates/deploy_parity.py": "# an old gate, no TARGETS\n"})
    ctx = _pair(tmp_path, monkeypatch, files, _CLAUDE)
    r = _prow(ctx, "parity.claude")
    assert r.status == doc.OK and "2 file" in r.detail, r


# --- roots.config: the guards read NO config file -------------------------------------- #

def test_the_guards_reading_NO_config_file_is_FAIL(sandbox):
    """MEASURED 2026-10-02 on the author's machine, check-only: with X4_TOOLKIT unset, the
    game root's guards derive the toolkit from CLAUDE_PROJECT_DIR, find no x4-paths.env
    there, default the reference to <game>/reference -- and ALLOW a write and a delete
    into the configured reference (4 of 4 deny controls became allow)."""
    (sandbox.root / ".claude" / "x4-paths.env").unlink()
    rows = sandbox.rows(doc.check_roots)
    assert rows["roots.config"].status == doc.FAIL, rows["roots.config"]
    assert "x4-paths.env" in rows["roots.config"].detail


def test_TWIN_the_guards_reading_their_config_is_OK(sandbox):
    rows = sandbox.rows(doc.check_roots)
    assert rows["roots.config"].status == doc.OK, rows["roots.config"]


# --- Task 8: guard self-test -- controls that MUST deny and controls that MUST allow -- #

def _sel(sandbox, target="claude"):
    rows = {r.id: r for r in doc.check_guards(sandbox.ctx())}
    return rows["guards.selftest." + target]


def _replace_guard(sandbox, name: str, body: str) -> None:
    (sandbox.root / ".claude" / "hooks" / name).write_bytes(body.encode("utf-8"))


def test_selftest_all_controls_hold_is_OK(sandbox):
    r = _sel(sandbox)
    assert r.status == doc.OK, r
    assert "6 control" in r.detail


def test_a_guard_that_ALLOWS_the_reference_write_is_FAIL(sandbox):
    _replace_guard(sandbox, "protect-files.sh", "#!/bin/bash\nexit 0\n")      # allows everything
    r = _sel(sandbox)
    assert r.status == doc.FAIL and "deny.write.ref" in r.detail, r
    assert "LET THROUGH" in r.detail


def test_a_guard_that_DENIES_everything_is_FAIL(sandbox):
    _replace_guard(sandbox, "protect-bash.sh",
                   "#!/bin/bash\nprintf '%s' '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\","
                   "\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"x\"}}'\n")
    r = _sel(sandbox)
    assert r.status == doc.FAIL and "allow.bash.echo" in r.detail, r


def test_an_INERT_guard_is_FAIL_not_ok(sandbox, monkeypatch, tmp_path):
    monkeypatch.setenv("X4_PYTHON", (tmp_path / "no-such-python").as_posix())
    r = _sel(sandbox)
    assert r.status == doc.FAIL and "inert" in r.detail.lower(), r


def test_no_reference_resolved_makes_the_deny_controls_UNKNOWN(sandbox, monkeypatch):
    real = doc.guard_probe

    def no_ref(ctx):
        vals, why = real(ctx)
        return (dict(vals, REFERENCE=""), why) if vals else (vals, why)
    monkeypatch.setattr(doc, "guard_probe", no_ref)
    r = _sel(sandbox)
    assert r.status == doc.UNKNOWN and "deny" in r.detail, r


def test_the_selftest_never_CREATES_the_probe_path(sandbox):
    _sel(sandbox)
    assert not (sandbox.ref / doc.PROBE_NAME).exists()


def test_a_codex_guard_copy_is_tested_with_its_OWN_x4guard(sandbox):
    shutil.copytree(sandbox.root / ".claude" / "hooks", sandbox.root / ".codex" / "hooks")
    rows = {r.id: r for r in doc.check_guards(sandbox.ctx())}
    assert "guards.selftest.codex" in rows
    assert ".codex" in rows["guards.selftest.codex"].detail.replace(chr(92), "/")


# --- Task 9: per-agent liveness ------------------------------------------------------- #

_HOOKS_JSON = {"hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "timeout": 30, "command": "bash s.sh"}]}],
    "PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "timeout": 60, "command": "bash p.sh",
                                                "commandWindows": "pwsh -File p.ps1"}]}],
}}


@pytest.fixture
def codex_root(tmp_path, monkeypatch):
    for name in _LEAKY:
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "proj"
    (root / ".codex" / "hooks").mkdir(parents=True)
    (root / ".codex" / "rules").mkdir()
    (root / ".codex" / "rules" / "x4.rules").write_text("# rules\n", encoding="utf-8")
    (root / ".codex" / "hooks.json").write_text(json.dumps(_HOOKS_JSON), encoding="utf-8")
    (root / "AGENTS.md").write_text(GEN_BANNER + "\n", encoding="utf-8")
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(doc, "_codex_cmd", lambda: None)
    return root


def _codex(root):
    return {r.id: r for r in doc.check_codex(doc.Ctx(root=root))}


def _cfg(root: Path, *, trusted=True, entries=None, extra="") -> None:
    exp = doc.expected_hooks(root / ".codex" / "hooks.json")
    lines = []
    if trusted:
        lines += ["[projects.'%s']" % str(root.resolve()).lower(), 'trust_level = "trusted"', ""]
    for key, val in (entries if entries is not None else exp).items():
        lines += ["[hooks.state.'%s']" % key]
        if val == "disabled":
            lines += ['trusted_hash = "%s"' % exp[key], "enabled = false"]
        else:
            lines += ['trusted_hash = "%s"' % val]
        lines += [""]
    home = Path(os.environ["CODEX_HOME"])
    (home / "config.toml").write_text("\n".join(lines) + extra, encoding="utf-8")


def test_no_codex_config_is_UNKNOWN_never_ok(codex_root):
    rows = _codex(codex_root)
    assert rows["codex.config"].status == doc.UNKNOWN
    assert rows["codex.trusted"].status == doc.UNKNOWN and rows["codex.reviewed"].status == doc.UNKNOWN


def test_untrusted_project_is_FAIL(codex_root):
    _cfg(codex_root, trusted=False)
    assert _codex(codex_root)["codex.trusted"].status == doc.FAIL


def test_TWIN_trusted_lowercased_key_is_OK(codex_root):
    _cfg(codex_root)
    assert _codex(codex_root)["codex.trusted"].status == doc.OK


def test_trust_inherited_from_an_ANCESTOR_is_UNKNOWN(codex_root):
    home = Path(os.environ["CODEX_HOME"])
    (home / "config.toml").write_text(
        "[projects.'%s']\ntrust_level = \"trusted\"\n" % str(codex_root.parent.resolve()).lower(), encoding="utf-8")
    assert _codex(codex_root)["codex.trusted"].status == doc.UNKNOWN


def test_all_hooks_reviewed_is_OK(codex_root):
    _cfg(codex_root)
    r = _codex(codex_root)["codex.reviewed"]
    assert r.status == doc.OK and "2 of 2" in r.detail, r


def test_an_UNREVIEWED_hook_is_FAIL_naming_the_silent_skip(codex_root):
    exp = doc.expected_hooks(codex_root / ".codex" / "hooks.json")
    first = sorted(exp)[0]
    _cfg(codex_root, entries={first: exp[first]})
    r = _codex(codex_root)["codex.reviewed"]
    assert r.status == doc.FAIL and "SILENTLY" in r.detail and "/hooks" in r.detail, r


def test_a_DISABLED_hook_is_FAIL(codex_root):
    exp = doc.expected_hooks(codex_root / ".codex" / "hooks.json")
    k = sorted(exp)
    _cfg(codex_root, entries={k[0]: exp[k[0]], k[1]: "disabled"})
    r = _codex(codex_root)["codex.reviewed"]
    assert r.status == doc.FAIL and "disabled" in r.detail, r


def test_a_definition_CHANGED_since_review_is_FAIL_when_the_scheme_is_confirmed(codex_root):
    exp = doc.expected_hooks(codex_root / ".codex" / "hooks.json")
    k = sorted(exp)
    _cfg(codex_root, entries={k[0]: exp[k[0]], k[1]: "sha256:" + "0" * 64})
    r = _codex(codex_root)["codex.reviewed"]
    assert r.status == doc.FAIL and "changed" in r.detail, r


def test_hash_unverifiable_is_UNKNOWN_not_OK_nor_FAIL(codex_root):
    """No entry matches our hash at all: the likelier story is a Codex that changed its
    scheme, not every definition changing at once -- so UNKNOWN, never 'modified'."""
    exp = doc.expected_hooks(codex_root / ".codex" / "hooks.json")
    _cfg(codex_root, entries={k: "sha256:" + "1" * 64 for k in exp})
    r = _codex(codex_root)["codex.reviewed"]
    assert r.status == doc.UNKNOWN and "scheme" in r.detail, r


def test_the_hash_moves_with_every_field_codex_hashes():
    base = {"type": "command", "command": "bash x.sh", "timeout": 30}
    h0 = doc.codex_hook_hash("pre_tool_use", {"matcher": ".*"}, base, windows=False)
    for k, v in (("command", "bash y.sh"), ("timeout", 31), ("async", True), ("statusMessage", "s"),
                 ("additionalContextLimit", 100)):
        assert doc.codex_hook_hash("pre_tool_use", {"matcher": ".*"}, dict(base, **{k: v}), windows=False) != h0, k
    assert doc.codex_hook_hash("pre_tool_use", {"matcher": "Bash"}, base, windows=False) != h0
    assert doc.codex_hook_hash("post_tool_use", {"matcher": ".*"}, base, windows=False) != h0
    # normalised defaults do NOT move it
    assert doc.codex_hook_hash("pre_tool_use", {"matcher": ".*"}, dict(base, timeout=None), windows=False) == \
        doc.codex_hook_hash("pre_tool_use", {"matcher": ".*"}, dict(base, timeout=600), windows=False)
    assert doc.codex_hook_hash("pre_tool_use", {"matcher": ".*"}, dict(base, additionalContextLimit=2500),
                               windows=False) == h0
    # Windows hashes commandWindows when present
    w = dict(base, commandWindows="pwsh -File x.ps1")
    assert doc.codex_hook_hash("pre_tool_use", {"matcher": ".*"}, w, windows=True) != \
        doc.codex_hook_hash("pre_tool_use", {"matcher": ".*"}, w, windows=False)


def test_the_310_reader_and_tomllib_AGREE(codex_root, monkeypatch):
    pytest.importorskip("tomllib")
    _cfg(codex_root, extra='\n[plugins."x@y"]\nenabled = true\n[features]\nfoo = 1\n')
    text = (Path(os.environ["CODEX_HOME"]) / "config.toml").read_text(encoding="utf-8")
    full = doc._toml_tables(text)
    monkeypatch.setitem(sys.modules, "tomllib", None)
    narrow = doc._toml_tables(text)
    assert full == narrow and len(narrow) == 3, (full, narrow)


def test_the_310_reader_REFUSES_a_line_it_does_not_understand(monkeypatch):
    monkeypatch.setitem(sys.modules, "tomllib", None)
    with pytest.raises(doc.TomlUnreadable):
        doc._toml_tables("[hooks.state.'k']\ntrusted_hash = \"sha256:1\"\nweird = [1, 2]\n")


def test_a_codex_target_with_NO_hooks_json_is_FAIL(codex_root):
    (codex_root / ".codex" / "hooks.json").unlink()
    _cfg_path = Path(os.environ["CODEX_HOME"]) / "config.toml"
    _cfg_path.write_text("", encoding="utf-8")
    r = _codex(codex_root)["codex.hooks"]
    assert r.status == doc.FAIL and "hooks.json" in r.detail


def test_codex_rules_that_FAIL_to_parse_are_FAIL(codex_root, monkeypatch, tmp_path):
    fake = tmp_path / "fake_codex.py"
    fake.write_text("import sys\nprint('failed to parse policy', file=sys.stderr)\nsys.exit(1)\n", encoding="utf-8")
    monkeypatch.setattr(doc, "_codex_cmd", lambda: [sys.executable, str(fake)])
    assert _codex(codex_root)["codex.rules"].status == doc.FAIL


def test_TWIN_codex_rules_that_parse_are_OK(codex_root, monkeypatch, tmp_path):
    fake = tmp_path / "fake_codex.py"
    fake.write_text("print('{\"decision\": \"allow\"}')\n", encoding="utf-8")
    monkeypatch.setattr(doc, "_codex_cmd", lambda: [sys.executable, str(fake)])
    assert _codex(codex_root)["codex.rules"].status == doc.OK


def test_codex_rules_without_codex_on_PATH_are_UNKNOWN(codex_root):
    assert _codex(codex_root)["codex.rules"].status == doc.UNKNOWN


def test_the_codex_rows_are_NA_when_codex_is_not_installed(sandbox):
    assert {r.status for r in doc.check_codex(sandbox.ctx())} == {doc.NA}


# claude
def test_TWIN_the_shipped_claude_wiring_is_OK(sandbox):
    rows = {r.id: r for r in doc.check_claude(sandbox.ctx())}
    assert rows["claude.wiring"].status == doc.OK, rows["claude.wiring"]
    assert rows["claude.enabled"].status == doc.OK, rows["claude.enabled"]


def test_a_missing_PowerShell_matcher_is_FAIL(sandbox):
    p = sandbox.root / ".claude" / "settings.json"
    s = json.loads(p.read_text(encoding="utf-8"))
    s["hooks"]["PreToolUse"] = [g for g in s["hooks"]["PreToolUse"] if g.get("matcher") != "PowerShell"]
    p.write_text(json.dumps(s), encoding="utf-8")
    r = {r.id: r for r in doc.check_claude(sandbox.ctx())}["claude.wiring"]
    assert r.status == doc.FAIL and "PowerShell" in r.detail, r


def test_a_wired_script_that_is_MISSING_is_FAIL(sandbox):
    (sandbox.root / ".claude" / "hooks" / "protect-files.sh").unlink()
    r = {r.id: r for r in doc.check_claude(sandbox.ctx())}["claude.wiring"]
    assert r.status == doc.FAIL and "protect-files.sh" in r.detail, r


def test_disableAllHooks_in_the_LOCAL_settings_is_FAIL(sandbox):
    """READ (code.claude.com hooks-guide): `"disableAllHooks": true` switches every hook off,
    in user, project, local or managed settings."""
    (sandbox.root / ".claude" / "settings.local.json").write_text('{"disableAllHooks": true}', encoding="utf-8")
    r = {r.id: r for r in doc.check_claude(sandbox.ctx())}["claude.enabled"]
    assert r.status == doc.FAIL and "disableAllHooks" in r.detail, r


def test_disableAllHooks_in_the_USER_settings_is_FAIL(sandbox, tmp_path, monkeypatch):
    home = tmp_path / "claude-home"
    home.mkdir()
    (home / "settings.json").write_text('{"disableAllHooks": true}', encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    r = {r.id: r for r in doc.check_claude(sandbox.ctx())}["claude.enabled"]
    assert r.status == doc.FAIL, r


def test_TWIN_a_project_false_OVERRIDES_a_user_true(sandbox, tmp_path, monkeypatch):
    home = tmp_path / "claude-home"
    home.mkdir()
    (home / "settings.json").write_text('{"disableAllHooks": true}', encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    (sandbox.root / ".claude" / "settings.local.json").write_text('{"disableAllHooks": false}', encoding="utf-8")
    r = {r.id: r for r in doc.check_claude(sandbox.ctx())}["claude.enabled"]
    assert r.status == doc.OK, r


# all targets
def test_X4_GUARD_off_is_FAIL(sandbox, monkeypatch):
    monkeypatch.setenv("X4_GUARD", "off")
    r = {r.id: r for r in doc.check_common(sandbox.ctx())}["guard.escape"]
    assert r.status == doc.FAIL and "OFF" in r.detail, r


def test_TWIN_X4_GUARD_unset_is_OK(sandbox):
    r = {r.id: r for r in doc.check_common(sandbox.ctx())}["guard.escape"]
    assert r.status == doc.OK, r


def test_layer2_without_the_query_is_UNKNOWN(sandbox, monkeypatch):
    monkeypatch.setattr(doc, "_x4lock_module", lambda ctx: type("M", (), {})())
    r = {r.id: r for r in doc.check_common(sandbox.ctx())}["layer2.reference"]
    assert r.status == doc.UNKNOWN, r


@pytest.mark.parametrize("state,codex,want", [("present", False, "OK"), ("absent", False, "OK"),
                                              ("absent", True, "FAIL"), ("unknown", True, "UNKNOWN"),
                                              ("present", True, "OK")])
def test_layer2_states(sandbox, monkeypatch, state, codex, want):
    mod = type("M", (), {"deny_delete_state": staticmethod(lambda p: state)})()
    monkeypatch.setattr(doc, "_x4lock_module", lambda ctx: mod)
    if codex:
        shutil.copytree(sandbox.root / ".claude" / "hooks", sandbox.root / ".codex" / "hooks")
    r = {r.id: r for r in doc.check_common(sandbox.ctx())}["layer2.reference"]
    assert r.status == want, r


def test_x4lock_unlocked_files_are_UNKNOWN_informational_not_FAIL(sandbox, monkeypatch, tmp_path):
    f = tmp_path / "f.md"
    f.write_text("x", encoding="utf-8")
    mod = type("M", (), {"manifest": staticmethod(lambda: [f]), "missing": staticmethod(lambda: []),
                         "state": staticmethod(lambda p: "unlocked"), "Unresolvable": RuntimeError})()
    monkeypatch.setattr(doc, "_x4lock_module", lambda ctx: mod)
    r = {r.id: r for r in doc.check_common(sandbox.ctx())}["x4lock"]
    assert r.status == doc.UNKNOWN and "1 unlocked" in r.detail, r


def test_TWIN_x4lock_all_locked_is_OK(sandbox, monkeypatch, tmp_path):
    f = tmp_path / "f.md"
    f.write_text("x", encoding="utf-8")
    mod = type("M", (), {"manifest": staticmethod(lambda: [f]), "missing": staticmethod(lambda: []),
                         "state": staticmethod(lambda p: "locked"), "Unresolvable": RuntimeError})()
    monkeypatch.setattr(doc, "_x4lock_module", lambda ctx: mod)
    r = {r.id: r for r in doc.check_common(sandbox.ctx())}["x4lock"]
    assert r.status == doc.OK, r


def test_the_doctor_never_WRITES_the_codex_config(codex_root):
    _cfg(codex_root)
    p = Path(os.environ["CODEX_HOME"]) / "config.toml"
    before = (p.read_bytes(), p.stat().st_mtime_ns)
    doc.collect(doc.Ctx(root=codex_root))
    assert (p.read_bytes(), p.stat().st_mtime_ns) == before


# --- one trust model: the doctor's must equal lane B's and Codex's own ------------------ #

_HASH_CASES = [
    ("pre_tool_use", {"matcher": ".*"}, {"type": "command", "command": "bash a.sh", "timeout": 60}),
    ("pre_tool_use", {"matcher": ".*"}, {"type": "command", "command": "bash a.sh", "timeout": 60,
                                         "commandWindows": "pwsh -File a.ps1"}),
    ("session_start", {}, {"type": "command", "command": "bash s.sh", "timeout": 30}),
    ("post_tool_use", {"matcher": "apply_patch"}, {"type": "command", "command": "bash p.sh"}),
]


def test_the_doctor_and_lane_Bs_codex_trust_compute_the_SAME_hash():
    src = REPO / "agent" / "guards" / "adapters" / "codex_trust.py"
    if not src.is_file():
        pytest.skip("lane B's codex_trust.py has not landed")
    spec = importlib.util.spec_from_file_location("codex_trust_for_doctor", src)
    ct = importlib.util.module_from_spec(spec)
    sys.modules["codex_trust_for_doctor"] = ct
    spec.loader.exec_module(ct)
    for event, group, handler in _HASH_CASES:
        assert doc.codex_hook_hash(event, group, handler) == ct.hook_hash(event, group, handler), (event, handler)


def test_the_doctor_reproduces_CODEXS_OWN_hash_vectors():
    """The oracle is Codex (lane B Task 3 records `hooks/list` current_hash values for
    neutral definitions), never another reimplementation (#14)."""
    vec = Path(__file__).parent / "fixtures" / "codex" / "0.160.0" / "trust_vectors.json"
    if not vec.is_file():
        pytest.skip("lane B's Codex-produced trust vectors have not landed")
    vectors = json.loads(vec.read_text(encoding="utf-8"))
    assert len(vectors) >= 4
    for v in vectors:
        assert doc.codex_hook_hash(v["event_key"], v["group"], v["handler"],
                                   windows=v.get("windows")) == v["codex_hash"], v.get("label")

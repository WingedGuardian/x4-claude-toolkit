"""gen-agent-trees.py, OpenCode target (Plan 3 lane L Task 2): .opencode/hooks carries every guard
byte for byte plus the adapters, skills render like the Codex/generic ones, and the OpenCode
addendum .opencode/X4-OPENCODE.md is generated, neutral and bannered.

OpenCode support is BEST EFFORT, from docs and source, not measured against a running OpenCode.
"""
import importlib.util
import subprocess
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1]
REPO = PKG.parents[1]
SRC = PKG / "scripts" / "gen-agent-trees.py"


def load():
    spec = importlib.util.spec_from_file_location("gen_agent_trees_opencode_under_test", SRC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(autouse=True)
def _source_checkout():
    if not (REPO / "agent").is_dir():
        pytest.skip("not a source checkout (no agent/) -- OpenCode generation NOT checked here")


def test_opencode_hooks_carry_every_guard_byte_for_byte():
    out = load().generate(REPO)
    guards = {k[len(".claude/hooks/"):]: v for k, v in out.items() if k.startswith(".claude/hooks/")}
    oc = {k[len(".opencode/hooks/"):]: v for k, v in out.items() if k.startswith(".opencode/hooks/")}
    assert guards
    for rel, text in guards.items():
        assert oc.get(rel) == text, rel
    assert {"patch_paths.py", "codex_adapter.py"} <= set(oc)


def test_TWIN_no_codex_only_file_leaks_into_the_opencode_hooks():
    """The Codex entry wrappers and trust tool are Codex mechanisms; OpenCode never runs them."""
    out = load().generate(REPO)
    oc = {k[len(".opencode/hooks/"):] for k in out if k.startswith(".opencode/hooks/")}
    assert not oc & {"codex-entry.ps1", "codex-entry.sh", "codex_trust.py"}


def test_opencode_skills_render_the_same_toolkit_token_as_codex():
    out = load().generate(REPO)
    oc = [k for k in out if k.startswith(".opencode/skills/")]
    assert oc and len(oc) == len([k for k in out if k.startswith(".agents/skills/")])
    for k in oc:
        assert out[k] == out[".agents/skills/" + k[len(".opencode/skills/"):]], k


def test_opencode_addendum_is_generated_with_a_banner_and_no_claude_mechanism():
    g = load()
    text = g.generate(REPO)[".opencode/X4-OPENCODE.md"]
    assert text.startswith("# ")
    assert g.BANNER_MD in text and "desktop app" in text.lower()
    assert ".opencode/hooks/x4guard.py" in text and "best effort" in text.lower()
    g.check_neutral(text, "agent/instructions/opencode.md")   # the neutrality list applies here too


def test_TWIN_a_claude_mechanism_in_the_opencode_addendum_REFUSES(tmp_path):
    g = load()
    with pytest.raises(g.GenerationError, match="opencode.md"):
        g.check_neutral("# T\nuse CLAUDE.md\n", "agent/instructions/opencode.md")


def test_opencode_paths_are_owned_so_a_stray_file_is_a_GHOST(tmp_path):
    g = load()
    exp = g.generate(REPO)
    for rel, text in exp.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    (tmp_path / ".opencode/hooks/stray.py").write_bytes(b"x\n")
    (tmp_path / ".opencode/skills/stray/SKILL.md").parent.mkdir(parents=True)
    (tmp_path / ".opencode/skills/stray/SKILL.md").write_bytes(b"x\n")
    assert g.problems(exp, tmp_path) == ["GHOST    .opencode/hooks/stray.py",
                                         "GHOST    .opencode/skills/stray/SKILL.md"]


def test_a_user_plugin_or_opencode_file_beside_ours_is_NOT_owned(tmp_path):
    """OpenCode writes .opencode/.gitignore itself, and a user's own plugin is not ours."""
    g = load()
    assert ".opencode/" not in g.OWNED and ".opencode/plugins/" not in g.OWNED
    assert ".opencode/plugins/x4guard.js" in g.OWNED
    exp = g.generate(REPO)
    for rel, text in exp.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    (tmp_path / ".opencode/plugins").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".opencode/plugins/mine.js").write_bytes(b"x\n")
    (tmp_path / ".opencode/.gitignore").write_bytes(b"x\n")
    (tmp_path / ".opencode/opencode.jsonc").write_bytes(b"x\n")
    assert g.problems(exp, tmp_path) == []


def test_opencode_tree_is_fresh_in_the_checkout():
    g = load()
    stale = [p for p in g.problems(g.generate(REPO), REPO) if ".opencode/" in p]
    assert stale == [], "run: uv run python scripts/gen-agent-trees.py"


def test_opencode_hook_modes_match_the_claude_copy():
    """Byte identity includes the executable bit (git's index is the only record on Windows)."""
    r = subprocess.run(["git", "-C", str(REPO), "ls-files", "-s", "--", ".claude/hooks", ".opencode/hooks"],
                       capture_output=True, text=True)
    if r.returncode != 0 or ".opencode/hooks/" not in r.stdout:
        pytest.skip("the OpenCode hooks are not tracked here -- modes NOT checked")
    modes = {}
    for line in r.stdout.splitlines():
        meta, path = line.split("\t", 1)
        modes[path] = meta.split()[0]
    pairs = {p[len(".opencode/hooks/"):]: m for p, m in modes.items() if p.startswith(".opencode/hooks/")}
    diff = {n: (modes.get(".claude/hooks/" + n), m) for n, m in pairs.items()
            if ".claude/hooks/" + n in modes and modes[".claude/hooks/" + n] != m}
    assert diff == {}

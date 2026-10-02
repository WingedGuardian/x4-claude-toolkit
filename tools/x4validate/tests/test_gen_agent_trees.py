"""gen-agent-trees.py: every agent-facing file is generated from agent/ and must stay fresh."""
import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1]
REPO = PKG.parents[1]
SRC = PKG / "scripts" / "gen-agent-trees.py"


def load():
    spec = importlib.util.spec_from_file_location("gen_agent_trees_under_test", SRC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(autouse=True)
def _source_checkout(request):
    # An installed copy has no agent/ (installers do not ship it): the freshness tests have
    # nothing to compare there. The tmp-tree tests do not need it, so they opt out by name.
    if "fresh_copy" in request.fixturenames or request.node.name.startswith("test_missing_source"):
        return
    if not (REPO / "agent").is_dir():
        pytest.skip("not a source checkout (no agent/) -- generated-file freshness NOT checked here")


def test_generation_has_a_denominator():
    out = load().generate(REPO)
    assert "CLAUDE.md" in out
    assert sorted(p for p in out if p.startswith(".claude/agents/")) == [
        ".claude/agents/cross-file-impact.md", ".claude/agents/mod-research.md"]


def test_committed_trees_are_fresh():
    g = load()
    assert g.problems(g.generate(REPO), REPO) == [], \
        "stale generated files -- run: uv run python scripts/gen-agent-trees.py"


def test_generation_is_deterministic():
    g = load()
    assert g.generate(REPO) == g.generate(REPO)


def test_no_personal_path_reaches_generated_output():
    # A home directory in either slash dialect, or an 8-digit X4 profile id. A bare drive letter
    # is NOT personal (CLAUDE.md explains Wine's `Z:\`); scan-identifiers.py stays the
    # authoritative check on contributor identifiers.
    pat = re.compile(r"[\\/]Users[\\/]|/home/|\b\d{8}\b")
    # Rendered prose only. The guards under .claude/hooks/ are copied verbatim and legitimately
    # carry generic path fixtures (/Users/tester, /home/user) and Steam build ids; they are
    # covered by scan-identifiers.py, which knows placeholders from real identifiers.
    hits = [rel for rel, text in load().generate(REPO).items()
            if not rel.startswith(".claude/hooks/") and pat.search(text)]
    assert hits == []


def test_agent_frontmatter_matches_the_claude_contract():
    out = load().generate(REPO)
    head = out[".claude/agents/cross-file-impact.md"].split("\n")
    assert head[:6] == ["---", "name: cross-file-impact", head[2], "tools: Glob, Grep, Read, Bash",
                        "model: sonnet", "---"]
    assert head[2].startswith("description: Use BEFORE implementing a multi-file X4 change.")


def test_every_skill_and_settings_is_generated():
    out = load().generate(REPO)
    skills = sorted(p for p in out if p.startswith(".claude/skills/") and p.endswith("/SKILL.md"))
    assert len(skills) == 10, skills
    assert ".claude/settings.json" in out
    assert sum(p.startswith(".claude/skills/x4-cli-reference/reference/") for p in out) == 11


def test_tokens_are_rendered_everywhere():
    leaks = [rel for rel, text in load().generate(REPO).items() if "{{" in text]
    assert leaks == []


def test_no_double_banner_on_the_cli_reference():
    text = load().generate(REPO)[".claude/skills/x4-cli-reference/SKILL.md"]
    assert text.count("<!-- GENERATED") == 1


def test_hooks_are_generated_byte_identical():
    out = load().generate(REPO)
    src = REPO / "agent" / "guards" / "claude-hooks"
    srcs = sorted(f.relative_to(src).as_posix() for f in src.rglob("*")
                  if f.is_file() and "__pycache__" not in f.parts and ".pytest_cache" not in f.parts)
    gen = sorted(p[len(".claude/hooks/"):] for p in out if p.startswith(".claude/hooks/"))
    assert gen == srcs and len(gen) >= 13      # MEASURED: 13 tracked hook files at 2f8e913
    for name in srcs:
        assert out[".claude/hooks/" + name] == (src / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


def test_hook_modes_match_their_source():
    """Byte identity includes the executable bit. On Windows (core.filemode=false) a regenerated
    file re-added to the index defaults to 100644 -- MEASURED when the hooks moved: 5 scripts
    lost 100755. Compared in git's index, the only place Windows records the bit."""
    r = subprocess.run(["git", "-C", str(REPO), "ls-files", "-s", "--", ".claude/hooks", "agent/guards/claude-hooks"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        pytest.skip("not a git checkout with tracked hooks -- modes NOT checked here")
    modes = {}
    for line in r.stdout.splitlines():
        meta, path = line.split("\t", 1)
        modes[path] = meta.split()[0]
    gen = {p[len(".claude/hooks/"):]: m for p, m in modes.items() if p.startswith(".claude/hooks/")}
    src = {p[len("agent/guards/claude-hooks/"):]: m for p, m in modes.items() if p.startswith("agent/guards/")}
    assert gen and src
    assert {n: (src.get(n), m) for n, m in gen.items() if src.get(n) != m} == {}


def test_hooks_get_no_banner_and_no_token_rewrite():
    out = load().generate(REPO)
    assert not any("<!-- GENERATED" in t for p, t in out.items() if p.startswith(".claude/hooks/"))
    assert "CLAUDE_PROJECT_DIR" in out[".claude/hooks/_x4-env.sh"]   # its fallback root stays literal


def test_agents_md_is_generated_within_codex_limit():
    """Stopgap AGENTS.md (until the phase-3 split): Codex silently drops AGENTS.md text past
    32,768 BYTES (MEASURED 2026-09-30, codex-spike doc), so the budget is in bytes."""
    text = load().generate(REPO)["AGENTS.md"]
    assert len(text.encode("utf-8")) <= 32768
    assert text.startswith("# ") and "<!-- GENERATED from agent/ -->" in text


def test_TWIN_an_oversized_agents_md_refuses(tmp_path):
    import shutil
    g = load()
    shutil.copytree(REPO / "agent", tmp_path / "agent")
    p = tmp_path / "agent" / "instructions" / "codex.md"
    p.write_bytes(p.read_bytes() + b"filler line for the size limit\n" * 1200)   # ~37 KB
    with pytest.raises(g.GenerationError, match="silently drops"):
        g.generate(tmp_path)


def test_agents_md_carries_the_rules_codex_cannot_get_elsewhere():
    text = load().generate(REPO)["AGENTS.md"]
    for must in ("CLAUDE.md", "agent/", "gen-agent-trees.py", "fail open", "reference/",
                 ".cat", "git add -A"):
        assert must in text, must


def test_missing_source_refuses_rather_than_skipping(tmp_path):
    g = load()
    with pytest.raises(g.GenerationError):
        g.generate(tmp_path)          # no agent/ at all: refuse, never a partial result


@pytest.fixture
def fresh_copy(tmp_path):
    g = load()
    exp = g.generate(REPO)
    for rel, text in exp.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    return g, exp, tmp_path


def test_TWIN_a_hand_edit_is_STALE(fresh_copy):
    g, exp, root = fresh_copy
    (root / "CLAUDE.md").write_bytes(b"hand edit\n")
    assert g.problems(exp, root) == ["STALE    CLAUDE.md"]


def test_TWIN_a_stray_agent_is_a_GHOST(fresh_copy):
    g, exp, root = fresh_copy
    (root / ".claude/agents/stray.md").write_bytes(b"x\n")
    assert g.problems(exp, root) == ["GHOST    .claude/agents/stray.md"]


def test_TWIN_a_deleted_file_is_MISSING(fresh_copy):
    g, exp, root = fresh_copy
    (root / ".claude/agents/mod-research.md").unlink()
    assert g.problems(exp, root) == ["MISSING  .claude/agents/mod-research.md"]


def test_TWIN_a_hand_edited_skill_is_STALE(fresh_copy):
    g, exp, root = fresh_copy
    p = root / ".claude/skills/x4-debug/SKILL.md"
    p.write_bytes(p.read_bytes() + b"\nextra\n")
    assert g.problems(exp, root) == ["STALE    .claude/skills/x4-debug/SKILL.md"]


def test_gitignored_files_are_never_ghosts(fresh_copy):
    g, exp, root = fresh_copy
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_bytes(b".pytest_cache/\n")
    cache = root / ".claude/agents/.pytest_cache/x"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"x\n")
    assert g.problems(exp, root) == []          # ignored by git -> not a ghost


def test_crlf_checkout_is_not_stale(fresh_copy):
    g, exp, root = fresh_copy
    p = root / "CLAUDE.md"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    assert g.problems(exp, root) == []

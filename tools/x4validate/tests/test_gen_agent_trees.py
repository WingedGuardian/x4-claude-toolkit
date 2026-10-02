"""gen-agent-trees.py: every agent-facing file is generated from agent/ and must stay fresh."""
import importlib.util
import json
import re
import shutil
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


def test_I6_write_mode_rewrites_only_stale_files_and_names_them(tmp_path, monkeypatch, capsys):
    """A hand edit to a generated file (e.g. a tool writing .claude/settings.json) must not be
    lost UNSEEN: write mode names each STALE file it overwrites and leaves fresh files untouched."""
    import os
    import shutil
    g = load()
    shutil.copytree(REPO / "agent", tmp_path / "agent")
    for rel, text in g.generate(REPO).items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    fresh = tmp_path / ".claude/agents/mod-research.md"
    os.utime(fresh, (1_000_000_000, 1_000_000_000))
    edited = tmp_path / ".claude/settings.json"
    edited.write_bytes(b'{"hand": "edit"}\n')
    monkeypatch.setattr(g, "REPO", tmp_path)
    assert g.main([]) == 0
    out = capsys.readouterr()
    assert "STALE    .claude/settings.json" in out.out + out.err
    assert fresh.stat().st_mtime == 1_000_000_000          # untouched
    assert b"hand" not in edited.read_bytes()               # restored from agent/


# ---------------------------------------------------------------- lane E (Plan 2): E6 agent.yaml

CFI = "agent/agents/cross-file-impact/agent.yaml"
MR = "agent/agents/mod-research/agent.yaml"


def _agent_copy(tmp_path):
    shutil.copytree(REPO / "agent", tmp_path / "agent", ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def _edit(root, rel, old, new):
    p = root / rel
    t = p.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert old in t, f"fixture drifted: {old!r} is not in {rel}"
    p.write_bytes(t.replace(old, new, 1).encode("utf-8"))


def _frontmatter(text):
    from ruamel.yaml import YAML
    assert text.startswith("---\n")
    return YAML(typ="safe").load(text[4:text.index("\n---\n", 4)])


@pytest.mark.parametrize("tools", ["tools: Glob, Grep, Read, Bash",      # MEASURED: became G, l, o, b, ...
                                   "tools: Read",            # a string with no ',' or ' ': only the list clause sees it
                                   'tools: [Glob, "Read, Grep"]',
                                   "tools: [Glob, 7]",
                                   'tools: [Glob, ""]'])
def test_E6_tools_that_are_not_a_list_of_names_refuse(tmp_path, tools):
    g = load()
    root = _agent_copy(tmp_path)
    _edit(root, CFI, "tools: [Glob, Grep, Read, Bash]", tools)
    with pytest.raises(g.GenerationError, match="tools"):
        g.generate(root)


@pytest.mark.parametrize("desc", ["Note: use BEFORE editing", "Line one\\nLine two", "a #hash", "[bracketed]"])
def test_E6_any_description_survives_into_parseable_frontmatter(tmp_path, desc):
    """MEASURED: ': ' and a newline produced frontmatter that does not parse."""
    g = load()
    root = _agent_copy(tmp_path)
    _edit(root, CFI, 'description: "Use BEFORE', f'description: "{desc} -- Use BEFORE')
    fm = _frontmatter(g.generate(root)[".claude/agents/cross-file-impact.md"])
    assert fm["description"].startswith(desc.replace("\\n", "\n") + " -- Use BEFORE"), fm
    assert fm["name"] == "cross-file-impact" and fm["model"] == "sonnet"


@pytest.mark.parametrize("desc", ["Note: x",      # the render does not parse at all
                                  "a #hash"])     # it parses, but reads back as 'a'
def test_E6_TWIN_the_readback_refuses_a_render_that_does_not_parse_back(tmp_path, monkeypatch, desc):
    """The belt-and-braces clause on its own: with the quoting step broken, the re-read of the
    rendered frontmatter must refuse rather than emit a frontmatter Claude Code would misread.
    One param per clause of the re-read (parse error / value mismatch)."""
    g = load()
    root = _agent_copy(tmp_path)
    _edit(root, CFI, 'description: "Use BEFORE', f'description: "{desc} -- Use BEFORE')
    monkeypatch.setattr(g, "_yaml_scalar", lambda s: s)
    with pytest.raises(g.GenerationError, match="rendered frontmatter"):
        g.generate(root)


def test_E6_generated_frontmatter_parses_back_to_its_source():
    """Regression pin over the real agents: name/description/tools/model round-trip."""
    from ruamel.yaml import YAML
    out = load().generate(REPO)
    for name in ("cross-file-impact", "mod-research"):
        src = YAML(typ="safe").load((REPO / "agent" / "agents" / name / "agent.yaml").read_bytes())
        fm = _frontmatter(out[f".claude/agents/{name}.md"])
        assert fm["name"] == src["name"] and fm["description"] == src["description"]
        assert fm["tools"] == ", ".join(src["claude"]["tools"])


def test_E6_duplicate_agent_names_refuse(tmp_path):
    """MEASURED: one of the two agents was silently dropped."""
    g = load()
    root = _agent_copy(tmp_path)
    _edit(root, MR, "name: mod-research", "name: cross-file-impact")
    with pytest.raises(g.GenerationError, match="cross-file-impact"):
        g.generate(root)


@pytest.mark.parametrize("raw", ['"../../escaped"', '"sub/dir"', r"'sub\dir'", '"Upper-Case"',
                                 '"has space"', "123", '"-leading"', '""'])
def test_E6_a_name_that_is_not_a_plain_agent_name_refuses(tmp_path, raw):
    """MEASURED: '../../escaped' became .claude/agents/../../escaped.md -- outside .claude/."""
    g = load()
    root = _agent_copy(tmp_path)
    _edit(root, CFI, "name: cross-file-impact", f"name: {raw}")
    with pytest.raises(g.GenerationError, match="name"):
        g.generate(root)


def test_E6_TWIN_a_plain_new_name_still_generates(tmp_path):
    g = load()
    root = _agent_copy(tmp_path)
    _edit(root, CFI, "name: cross-file-impact", "name: impact-2")
    assert ".claude/agents/impact-2.md" in g.generate(root)


def test_E6_a_claude_block_that_is_not_a_mapping_refuses(tmp_path):
    g = load()
    root = _agent_copy(tmp_path)
    _edit(root, CFI, "claude:\n  tools: [Glob, Grep, Read, Bash]", "claude: [Glob]")
    with pytest.raises(g.GenerationError, match="claude"):
        g.generate(root)


# ---------------------------------------------------------------- lane E (Plan 2): E7 refusals

SK = "agent/skills/x4-debug/SKILL.md"


@pytest.mark.parametrize("label", ["never-closed frontmatter", "non-UTF-8 skill", "non-UTF-8 agent.yaml",
                                   "YAML syntax error", "duplicate YAML key"])
def test_E7_a_malformed_source_refuses_with_rc2(tmp_path, monkeypatch, capsys, label):
    """MEASURED: each of these escaped as a traceback (rc 1), not a refusal (rc 2)."""
    g = load()
    root = _agent_copy(tmp_path)
    if label == "never-closed frontmatter":
        (root / SK).write_bytes(b"---\nname: x4-debug\ndescription: d\nno closing fence\n")
    elif label == "non-UTF-8 skill":
        (root / SK).write_bytes((root / SK).read_bytes() + b"\xff\n")
    elif label == "non-UTF-8 agent.yaml":
        (root / CFI).write_bytes((root / CFI).read_bytes() + b"# \xff\n")
    elif label == "YAML syntax error":
        _edit(root, CFI, "tier: balanced", "tier: [balanced")
    else:
        _edit(root, CFI, "tier: balanced", "tier: balanced\ntier: deep")
    monkeypatch.setattr(g, "REPO", root)
    assert g.main(["--check"]) == 2, label
    err = capsys.readouterr().err
    assert err.startswith("REFUSING:") and ("SKILL.md" in err or "agent.yaml" in err), err


def test_E7_TWIN_an_unmodified_copy_is_not_refused(tmp_path, monkeypatch, capsys):
    g = load()
    root = _agent_copy(tmp_path)
    monkeypatch.setattr(g, "REPO", root)
    assert g.main(["--check"]) == 1          # a bare copy has no generated files: MISSING, not REFUSING
    assert "REFUSING" not in capsys.readouterr().err


def test_E7_a_non_utf8_generated_file_is_STALE_not_a_crash(fresh_copy):
    g, exp, root = fresh_copy
    (root / "CLAUDE.md").write_bytes(b"\xff\xfe broken\n")
    assert g.problems(exp, root) == ["STALE    CLAUDE.md"]

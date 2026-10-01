# Universal Agent Support — Plan 1: neutral source, generator, guard relocation, front door

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land spec v2 phases 1–2. Every agent-facing file is generated from a neutral `agent/` source tree, with Claude as the only target and its output **unchanged** apart from provenance banners. The existing guards move under that source **byte-identical**. A Layer-0 front door, `x4guard check`, lets any agent ask the guards for a verdict.

**Architecture:** `tools/x4validate/scripts/gen-agent-trees.py` copies the proven `gen-cli-reference.py` pattern: a pure `generate()`, a `problems()` drift check, and a pytest freshness gate. It renders `agent/` into `CLAUDE.md` and `.claude/{agents,skills,settings.json,hooks}`. The guards themselves are not modified (spec D10). `x4guard.py` is a stdlib-only script that ships beside them in `.claude/hooks/`. It builds the guard-shaped payload, runs the same guard scripts without side effects, and prints a neutral verdict. Anything that keeps it from running a guard becomes a `deny` marked `inert`, never an allow.

**Tech Stack:** Python 3.13 via uv for generator and tests (`tools/x4validate`); stdlib-only Python ≥ 3.10 for anything under `.claude/hooks/`; bash (Git Bash on Windows); pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-universal-agent-support-design.md` (v2, commit `9c4ea61`). Evidence: `docs/superpowers/measurements/2026-09-30-codex-spike.md`.

**Spec clarification, not a deviation.** The Claude adapter is the identity, so Claude's hook wiring in `settings.json` stays exactly as it is today. The single stable `entry.sh` (spec §5.4) exists for Codex's frozen hook definitions and is built in Plan 2 together with the Codex adapter. Building it now would change Claude's wiring for no benefit.

**Repo:** the toolkit repo root (`$X4_TOOLKIT`). Below, `PKG` means `tools/x4validate`. Run tests with `cd tools/x4validate && uv run --frozen python -m pytest -q -rs`.

## Global Constraints

- **Zero behaviour change for Claude Code.** Generated files may differ from today's only by an added `GENERATED` banner line plus one blank line. Hook files must be **byte-identical**.
- Anything under `.claude/hooks/` or `agent/guards/` is stdlib-only and must import on Python 3.10.
- Write files as UTF-8 with LF line endings: **encode first, then `write_bytes`**. Compare with CRLF normalised (`.gitattributes` has `* text=auto`).
- Every generated file is committed. A file under an owned prefix that the generator did not produce is a **GHOST**, and the drift check fails on it.
- No personal paths in committed files. `scripts/scan-identifiers.py` must stay clean, and the regex `[A-Za-z]:[\\/]|/home/|/Users/|\b\d{8}\b` must not match generated output.
- Stage explicit paths only; never `git add -A`. One commit per task on `master`. Never push.
- Skills stay `x4-*` under `.claude/skills/<name>/`, and agents stay `.md` directly under `.claude/agents/`. Both installers' global mode and `deploy-claude-dir.py` depend on that layout.
- Leave `$CLAUDE_PROJECT_DIR` inside `.claude/hooks/` alone: `_x4-env.sh` uses it as a fallback root. The `{{TOOLKIT}}` token applies to skills and agents only.
- Resolving bash: `X4_BASH` if set, else `shutil.which("bash.exe")`, else `shutil.which("bash")`. **Refuse a bash under `System32`**, which is the WSL stub (`gates/hook_false_positives.py:70-73`); that means an inert deny, never a run.

## Review Focus

1. **A guard that cannot run must not read as allow** (missing script, missing or WSL bash, timeout, non-zero exit, unparseable output). Expected: `decision:"deny"` with `inert:true` and the cause named. Pinned in Task 5: `test_missing_guard_is_inert_deny`, `test_wsl_bash_refused`, `test_unparseable_guard_output_is_inert_deny`.
2. **PowerShell text sent as "Bash"**, the measured Codex hole. Expected: the `--shell` flag decides the verdict, `powershell` denies and `bash` lets it through. Pinned in Task 5: `test_shell_routing_decides_the_verdict`.
3. **Paths containing spaces and backslashes** in `--path`. Expected: the same verdict the hook gives today. Pinned in Task 5: `test_write_path_with_spaces_and_backslashes`.
4. **A hand edit to a generated file**, or a stray file in an owned directory. Expected: STALE or GHOST, naming the file. Pinned in Tasks 1, 2 and 4 (`test_TWIN_*`).
5. **`check` must have no side effects.** The write guard's sibling, `backup-before-edit.sh`, copies files, and a check must not. Expected: the backup directory is untouched. Pinned in Task 5: `test_check_has_no_side_effects`.

---

## Task 1: Generator skeleton — instructions and subagents

**Files:**
- Create: `agent/instructions/core.md` (verbatim copy of today's repo-root `CLAUDE.md`), `agent/instructions/claude.md` (empty), `agent/instructions/codex.md` (empty)
- Create: `agent/agents/cross-file-impact/agent.yaml`, `agent/agents/cross-file-impact/instructions.md`, `agent/agents/mod-research/agent.yaml`, `agent/agents/mod-research/instructions.md`
- Create: `agent/README.md`
- Create: `PKG/scripts/gen-agent-trees.py`
- Create: `PKG/tests/test_gen_agent_trees.py`
- Modify (generated output): `CLAUDE.md`, `.claude/agents/cross-file-impact.md`, `.claude/agents/mod-research.md`

**Interfaces:**
- Produces in `gen-agent-trees.py`:
  - `BANNER_MD: str`
  - `TOKEN = "{{TOOLKIT}}"`
  - `TIER_MODEL = {"fast": "haiku", "balanced": "sonnet", "deep": "opus"}`
  - `OWNED: tuple[str, ...]` (repo-relative posix path prefixes)
  - `class GenerationError(Exception)`
  - `generate(repo: Path) -> dict[str, str]` (repo-relative posix path → LF text)
  - `problems(expected: dict[str, str], root: Path) -> list[str]` (entries `"MISSING  rel"`, `"STALE    rel"`, `"GHOST    rel"`, sorted)
  - `main(argv=None) -> int` (`--check` → 0 fresh / 1 problems; write mode → 0; `GenerationError` → 2)
- Agent source format: `agent/agents/<name>/agent.yaml` holds metadata; `instructions.md` holds the body **verbatim**. The body is kept out of YAML so its bytes cannot drift through a YAML scalar.

```yaml
# agent/agents/cross-file-impact/agent.yaml
name: cross-file-impact
description: <copy verbatim from the current .claude/agents/cross-file-impact.md frontmatter>
tier: balanced
read_only: true
claude:
  tools: [Glob, Grep, Read, Bash]
```

- [ ] **Step 1: Write the failing tests**

```python
# PKG/tests/test_gen_agent_trees.py
import importlib.util
import re
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
    pat = re.compile(r"[A-Za-z]:[\\/]|/home/|/Users/|\b\d{8}\b")
    hits = [rel for rel, text in load().generate(REPO).items() if pat.search(text)]
    assert hits == []


def test_agent_frontmatter_matches_the_claude_contract():
    out = load().generate(REPO)
    head = out[".claude/agents/cross-file-impact.md"].split("\n")
    assert head[:6] == ["---", "name: cross-file-impact", head[2], "tools: Glob, Grep, Read, Bash",
                        "model: sonnet", "---"]
    assert head[2].startswith("description: Use BEFORE implementing a multi-file X4 change.")


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


def test_gitignored_files_are_never_ghosts(fresh_copy):
    g, exp, root = fresh_copy
    import subprocess
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
```

- [ ] **Step 2: Run them; expect FAIL** (the script does not exist yet). Command: `uv run --frozen python -m pytest tests/test_gen_agent_trees.py -q`.

- [ ] **Step 3: Implement `gen-agent-trees.py`**

```python
#!/usr/bin/env python3
"""Generate every agent-facing file from the neutral source tree in agent/.

    uv run python scripts/gen-agent-trees.py           write the generated files
    uv run python scripts/gen-agent-trees.py --check   0 fresh, 1 stale/missing/ghost, 2 cannot generate

agent/ is the ONLY place to edit. Generated files carry BANNER_MD (markdown) and are committed;
tests/test_gen_agent_trees.py fails when they drift. Modelled on gen-cli-reference.py:
generate() is pure and never returns a partial result.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ruamel.yaml import YAML

PKG = Path(__file__).resolve().parents[1]
REPO = PKG.parents[1]

BANNER_MD = ("<!-- GENERATED by tools/x4validate/scripts/gen-agent-trees.py from agent/. "
             "Do not edit: regenerate. -->")
TOKEN = "{{TOOLKIT}}"
CLAUDE_TOOLKIT = "$CLAUDE_PROJECT_DIR"
TIER_MODEL = {"fast": "haiku", "balanced": "sonnet", "deep": "opus"}
OWNED: tuple[str, ...] = ("CLAUDE.md", ".claude/agents/")
_IGNORED_PARTS = ("__pycache__",)


class GenerationError(Exception):
    pass


def _read(p: Path) -> str:
    if not p.is_file():
        raise GenerationError(f"missing source file: {p}")
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _norm(b: bytes) -> str:
    return b.decode("utf-8").replace("\r\n", "\n")


def _with_banner_after_first_line(text: str) -> str:
    first, _, rest = text.partition("\n")
    return f"{first}\n\n{BANNER_MD}\n{rest}"


def _with_banner_after_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        raise GenerationError("expected YAML frontmatter at the top")
    end = text.index("\n---\n", 4) + len("\n---\n")
    return f"{text[:end]}\n{BANNER_MD}\n{text[end:]}"


def render_claude_md(src: Path) -> str:
    core = _read(src / "instructions" / "core.md")
    addendum = _read(src / "instructions" / "claude.md")
    out = _with_banner_after_first_line(core)
    return out if not addendum.strip() else out.rstrip("\n") + "\n\n" + addendum


def render_agent_md(agent_dir: Path) -> tuple[str, str]:
    meta = YAML(typ="safe").load(_read(agent_dir / "agent.yaml"))
    for key in ("name", "description", "tier"):
        if not meta.get(key):
            raise GenerationError(f"{agent_dir}/agent.yaml: missing {key}")
    if meta["tier"] not in TIER_MODEL:
        raise GenerationError(f"{agent_dir}/agent.yaml: unknown tier {meta['tier']!r}")
    tools = (meta.get("claude") or {}).get("tools") or []
    body = _read(agent_dir / "instructions.md").replace(TOKEN, CLAUDE_TOOLKIT)
    lines = ["---", f"name: {meta['name']}", f"description: {meta['description']}"]
    if tools:
        lines.append("tools: " + ", ".join(tools))
    lines += [f"model: {TIER_MODEL[meta['tier']]}", "---", ""]
    text = "\n".join(lines) + "\n" + body
    return f".claude/agents/{meta['name']}.md", _with_banner_after_frontmatter(text)


def generate(repo: Path) -> dict[str, str]:
    src = repo / "agent"
    if not src.is_dir():
        raise GenerationError(f"no neutral source tree at {src}")
    out: dict[str, str] = {"CLAUDE.md": render_claude_md(src)}
    agent_dirs = sorted(p for p in (src / "agents").iterdir() if p.is_dir()) if (src / "agents").is_dir() else []
    if not agent_dirs:
        raise GenerationError("agent/agents/ holds no agent")
    for d in agent_dirs:
        rel, text = render_agent_md(d)
        out[rel] = text
    return dict(sorted(out.items()))


def _git_visible(root: Path) -> set[str] | None:
    """Tracked + untracked-but-not-ignored files, or None when root is not a git work tree.
    A file .gitignore excludes (.pytest_cache/, __pycache__/) is never a GHOST."""
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return {p for p in r.stdout.decode("utf-8").split("\0") if p}


def _owned_files(root: Path) -> set[str]:
    visible = _git_visible(root)
    found: set[str] = set()
    for prefix in OWNED:
        p = root / prefix
        if prefix.endswith("/"):
            if p.is_dir():
                for f in p.rglob("*"):
                    rel = f.relative_to(root).as_posix()
                    if not f.is_file() or any(part in _IGNORED_PARTS for part in f.parts):
                        continue
                    if visible is None or rel in visible:
                        found.add(rel)
        elif p.is_file():
            found.add(prefix)
    return found


def problems(expected: dict[str, str], root: Path) -> list[str]:
    out: list[str] = []
    for rel, text in expected.items():
        p = root / rel
        if not p.is_file():
            out.append(f"MISSING  {rel}")
        elif _norm(p.read_bytes()) != text:
            out.append(f"STALE    {rel}")
    for rel in sorted(_owned_files(root) - set(expected)):
        out.append(f"GHOST    {rel}")
    return sorted(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    try:
        expected = generate(REPO)
    except GenerationError as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        return 2
    found = problems(expected, REPO)
    if args.check:
        for line in found:
            print(line, file=sys.stderr)
        return 1 if found else 0
    for rel, text in expected.items():
        p = REPO / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode("utf-8")            # encode FIRST: a failed encode cannot truncate
        p.write_bytes(data)
    print(f"wrote {len(expected)} file(s)")
    ghosts = [line for line in found if line.startswith("GHOST")]
    if ghosts:                                 # NEVER delete (user decision 2026-10-01): report and refuse
        for line in ghosts:
            print(line, file=sys.stderr)
        print(f"REFUSING to finish: {len(ghosts)} file(s) in generated folders are not generated. "
              "Move them into agent/ or delete them yourself, then re-run.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Populate the source verbatim.**
  - `agent/instructions/core.md`: copy the bytes of `CLAUDE.md`.
  - Each `agent/agents/<name>/instructions.md`: copy the current `.md` with its frontmatter and the single blank line after it removed.
  - In those bodies, replace `$CLAUDE_PROJECT_DIR` with `{{TOOLKIT}}`. `cross-file-impact` has exactly 1 occurrence: count it before and after, and assert 1 then 0.
  - Write `agent/README.md`, three lines: "Edit here, never in `.claude/` or `CLAUDE.md`. Regenerate with `cd tools/x4validate && uv run python scripts/gen-agent-trees.py`. The spec is `docs/superpowers/specs/2026-09-30-universal-agent-support-design.md`."

- [ ] **Step 5: Generate, then prove zero change.**
  - Run `uv run python scripts/gen-agent-trees.py`.
  - Run `git diff -U0 -- CLAUDE.md .claude/agents/`. Every added line must be either `BANNER_MD` or empty, and there must be **no removed lines**. Read the whole diff; if anything else appears, the render is wrong, so fix the renderer and do not adjust the test.

- [ ] **Step 6: Run the tests; expect PASS (10 tests).** Then run `uv run python gates/claude_md_budget.py`. Expect rc 1, because the banner grew `CLAUDE.md` by exactly `len(BANNER_MD) + 1` characters; any other delta means stop. Re-record the baseline with `--record`. That baseline is gitignored and local, so the step is recorded in the commit message.

- [ ] **Step 7: Commit.**
  - Stage explicitly: `git add agent/ tools/x4validate/scripts/gen-agent-trees.py tools/x4validate/tests/test_gen_agent_trees.py CLAUDE.md .claude/agents/cross-file-impact.md .claude/agents/mod-research.md`.
  - Message: `agent/: neutral source for instructions and subagents, generated into CLAUDE.md and .claude/agents (Claude only, zero change)`.

---

## Task 2: Skills and `settings.json` move under the generator

**Files:**
- Move: `.claude/skills/` → `agent/skills/` (`git mv`; the generator recreates `.claude/skills/`)
- Create: `agent/targets/claude/settings.json` (verbatim copy of `.claude/settings.json`), `agent/targets/claude/README.md` (one line: "Copied verbatim into `.claude/settings.json` by gen-agent-trees.py.")
- Modify: `PKG/scripts/gen-agent-trees.py`: set `OWNED = ("CLAUDE.md", ".claude/agents/", ".claude/skills/", ".claude/settings.json")`, and add skill and settings rendering
- Modify: `PKG/scripts/gen-cli-reference.py`: line 54 `SKILL_DIR` → `REPO / "agent" / "skills" / "x4-cli-reference"`; emit `{{TOOLKIT}}` wherever it currently emits `$CLAUDE_PROJECT_DIR`
- Modify: `PKG/tests/test_gen_agent_trees.py`, `PKG/tests/test_cli_reference.py` (path expectations, plus the same "not a source checkout (no agent/)" skip on its freshness and committability tests, since `SKILL_DIR` now lives under `agent/`, which installers do not ship)

**Interfaces:**
- Consumes `generate`, `problems`, `OWNED`, `TOKEN`, `BANNER_MD` and `_with_banner_after_frontmatter` from Task 1.
- Produces `render_skills(src: Path) -> dict[str, str]`. Every file under `agent/skills/<skill>/` is rendered with `TOKEN` replaced by `$CLAUDE_PROJECT_DIR`. A `SKILL.md` gets `BANNER_MD` after its frontmatter **unless it already contains `<!-- GENERATED`**: `x4-cli-reference` carries its own generator's banner, and a double banner would be noise.

- [ ] **Step 1: Add failing tests** to `test_gen_agent_trees.py`:

```python
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


def test_TWIN_a_hand_edited_skill_is_STALE(fresh_copy):
    g, exp, root = fresh_copy
    p = root / ".claude/skills/x4-debug/SKILL.md"
    p.write_bytes(p.read_bytes() + b"\nextra\n")
    assert g.problems(exp, root) == ["STALE    .claude/skills/x4-debug/SKILL.md"]
```

- [ ] **Step 2: Run them; expect FAIL.**

- [ ] **Step 3: Move the sources and implement.**
  - `git mv .claude/skills agent/skills`.
  - Replace `$CLAUDE_PROJECT_DIR` with `{{TOOLKIT}}` in `agent/skills/**/*.md`. Count before and after; expect 7 files and 7 occurrences, then 0. Assert both counts.
  - Copy `settings.json` into `agent/targets/claude/`.
  - Add to `generate()`: `out.update(render_skills(src))` and `out[".claude/settings.json"] = _read(src / "targets" / "claude" / "settings.json")`.
  - Make the `gen-cli-reference.py` edits.

- [ ] **Step 4: Regenerate both generators, CLI reference first.**
  - Run `uv run python scripts/gen-cli-reference.py`, then `uv run python scripts/gen-agent-trees.py`.
  - Prove zero change against the pre-move tree: `git diff -U0 HEAD -- .claude/skills .claude/settings.json`. Every added line must be `BANNER_MD` or empty, there must be no removed lines, and `settings.json` must have no diff at all.

- [ ] **Step 5: Run the full suite** with `uv run --frozen python -m pytest -q -rs`. Expected: the same pass and skip counts as the 2,966 / 3 baseline plus the new tests. Pay particular attention to `test_cli_reference.py`, `test_skills_are_documented.py`, `test_deploy_parity.py` and `test_deploy_claude_dir.py`.

- [ ] **Step 6: Commit** with explicit paths: `agent/skills`, `agent/targets`, `.claude/skills`, `.claude/settings.json`, both scripts and both test files. Message: `agent/: skills and settings.json generated from the neutral source (Claude only, zero change)`.

---

## Task 3: Phase-1 gate — deploy and live check

**Files:** none new. This task proves the result.

- [ ] **Step 1: Dry-run the deploy.** `uv run --no-project python scripts/deploy-claude-dir.py`. Expect updates only for skills and agents (the banners), and `0 REFUSED`. Read the list.
- [ ] **Step 2: Apply it** with `--apply`. Expect `parity after apply: N of N`.
- [ ] **Step 3: Live check in a fresh Claude Code session in the game root.**
  - Invoke `/x4-debug`: the skill loads, and its body shows the banner line.
  - Ask the `mod-research` agent a trivial question: it runs.
  - Record both results in the commit message of Step 4.
- [ ] **Step 4: Update the game-root `CLAUDE.md` Key Paths row** (the user's file; the guard allows `CLAUDE.md`).
  - From: `Toolkit .claude/ source | $X4_TOOLKIT/.claude/ -- this game root's .claude/ is a DEPLOYED copy: edit the source, then tools/x4validate/scripts/deploy-claude-dir.py --apply`
  - To: `Toolkit agent source | $X4_TOOLKIT/agent/ -- edit there, run tools/x4validate/scripts/gen-agent-trees.py, then deploy-claude-dir.py --apply; .claude/ in BOTH repos is generated`
  - Commit in the game-root repo with an explicit path.
- [ ] **Step 5: CHANGELOG.** Under `## Unreleased`, add: "Agent-facing files are now generated from a neutral source tree `agent/` (`scripts/gen-agent-trees.py`); edit there. No behaviour change." Commit.

---

## Task 4: Guards move under the generator, byte-identical

**Files:**
- Move: `.claude/hooks/*` → `agent/guards/claude-hooks/` (`git mv` every tracked file; `git ls-files .claude/hooks` gives the list, 13 files as of `2f8e913`)
- Modify: `PKG/scripts/gen-agent-trees.py`: add `.claude/hooks/` to `OWNED`, and add `render_hooks(src) -> dict[str, str]`, which copies every file **verbatim** with no banner and no token replacement. Bytes are decoded as UTF-8 and compared LF-normalised. `.sh` and `.py` are `eol=lf` in `.gitattributes` anyway.
- Modify: `PKG/tests/test_gen_agent_trees.py`

**Interfaces:**
- Consumes the Task 1/2 machinery.
- Produces generated `.claude/hooks/` that is byte-identical to the moved sources.

- [ ] **Step 1: Failing tests**

```python
def test_hooks_are_generated_byte_identical():
    out = load().generate(REPO)
    src = REPO / "agent" / "guards" / "claude-hooks"
    srcs = sorted(f.relative_to(src).as_posix() for f in src.rglob("*")
                  if f.is_file() and "__pycache__" not in f.parts)
    gen = sorted(p[len(".claude/hooks/"):] for p in out if p.startswith(".claude/hooks/"))
    assert gen == srcs and len(gen) >= 13      # MEASURED: 13 tracked hook files at 2f8e913
    for name in srcs:
        assert out[".claude/hooks/" + name] == (src / name).read_bytes().decode("utf-8").replace("\r\n", "\n")


def test_hooks_get_no_banner_and_no_token_rewrite():
    out = load().generate(REPO)
    assert not any("<!-- GENERATED" in t for p, t in out.items() if p.startswith(".claude/hooks/"))
    assert "CLAUDE_PROJECT_DIR" in out[".claude/hooks/_x4-env.sh"]   # its fallback root stays literal
```

- [ ] **Step 2: Run them; expect FAIL.**
- [ ] **Step 3: Move the hooks and implement `render_hooks`.** Regenerate.
- [ ] **Step 4: Prove byte identity against the pre-move commit.**
  - `git diff --stat HEAD -- .claude/hooks` must print **nothing**.
  - `git ls-files .claude/hooks | wc -l` must equal the pre-move count.
- [ ] **Step 5: Run every guard suite.** Each must pass with today's counts:
  - `bash .claude/hooks/test-protect-bash.sh`
  - `bash scripts/test-hooks.sh` (177/177)
  - `uv run --no-project python .claude/hooks/test_hook_facts.py`
  - `uv run --no-project python .claude/hooks/test_audit0924_hooks.py` (57/57)
  - `uv run --no-project python scripts/fuzz-guard.py` (control rediscovered, 0 bypass)
  - `uv run --no-project python scripts/verify-hook-tests.py` (0 holes)
  - the full pytest suite

  These read `.claude/hooks/`, the generated copy, and that is intended: CI tests what ships. Byte identity (Step 4) makes the 23,490-command replay gate redundant here. Note that in the commit rather than spending 30 minutes on it.
- [ ] **Step 6: Commit** with explicit paths. Message: `agent/guards: the guards move under the neutral source, regenerated byte-identical (no behaviour change)`.

---

## Task 5: `x4guard check` — the Layer-0 front door

**Files:**
- Create: `agent/guards/claude-hooks/x4guard.py` (it ships beside the guards it calls; Task 4's generator copies it to `.claude/hooks/x4guard.py`)
- Create: `PKG/tests/test_x4guard_check.py`

**Interfaces:**
- CLI: `python x4guard.py check --kind shell --shell {bash,powershell} --command CMD` | `check --kind {write,delete} --path P`. Exit code: 0 with one JSON verdict on stdout; 2 on a usage error.
- Verdict JSON: `{"v": 1, "decision": "allow"|"advise"|"ask"|"deny", "reason": str|null, "context": str|null, "inert": bool, "guards": [script names run]}`.
- `write` and `delete` both run `protect-files.sh` only. Delete gets the verdict a write gets (spec §5.2). `backup-before-edit.sh` is **never** run, because a check has no side effects.
- Python API for Plan 2's Codex adapter: `verdict_for(kind: str, shell: str | None, command: str | None, path: str | None) -> dict` (the same dict as the JSON), `parse_hook_output(out: str) -> tuple[str, str | None, str | None]`, `resolve_bash() -> tuple[str | None, str | None]` (path, or None with a reason).

- [ ] **Step 1: Write the failing tests.** The sandbox mirrors `scripts/test-hooks.sh:89-97` (the separate layout).

```python
# PKG/tests/test_x4guard_check.py
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1]
REPO = PKG.parents[1]
X4GUARD = REPO / ".claude" / "hooks" / "x4guard.py"
HAS_PWSH = bool(shutil.which("pwsh") or shutil.which("powershell"))


@pytest.fixture
def sandbox(tmp_path):
    tk, game = tmp_path / "toolkit", tmp_path / "X4 Foundations"
    for d in (tk / "dev" / "mymod", tk / "reference" / "libraries", game / "extensions",
              tmp_path / "profile" / "save", tmp_path / "mods", tmp_path / "docs", tmp_path / "backups"):
        d.mkdir(parents=True)
    (tk / "reference" / "libraries" / "wares.xml").write_text("ref\n", encoding="utf-8")
    env = dict(os.environ, X4_TOOLKIT=str(tk), X4_GAME=str(game), X4_REFERENCE=str(tk / "reference"),
               X4_PROFILE=str(tmp_path / "profile"), X4_MODS=str(tmp_path / "mods"),
               X4_EXTENSIONS=str(game / "extensions"), X4_SAVES=str(tmp_path / "profile" / "save"),
               X4_DOCUMENTS=str(tmp_path / "docs"), X4_BACKUPS=str(tmp_path / "backups"),
               X4_CONFIG="/nonexistent")
    return tmp_path, tk, env


def check(env, *args, script=X4GUARD):
    r = subprocess.run([sys.executable, str(script), "check", *args], capture_output=True, env=env, timeout=120)
    return r.returncode, (json.loads(r.stdout) if r.returncode == 0 else None), r.stderr.decode("utf-8", "replace")


def test_shell_bash_delete_in_reference_denies(sandbox):
    _, tk, env = sandbox
    rc, v, _ = check(env, "--kind", "shell", "--shell", "bash", "--command",
                     f"rm -rf '{(tk / 'reference' / 'libraries').as_posix()}'")
    assert rc == 0 and v["decision"] == "deny" and not v["inert"] and v["guards"] == ["protect-bash.sh"]


@pytest.mark.skipif(not HAS_PWSH, reason="no PowerShell to translate with -- routing NOT checked here")
def test_shell_routing_decides_the_verdict(sandbox):
    """The measured Codex hole: PowerShell text judged as bash. The flag must decide."""
    _, tk, env = sandbox
    cmd = f"Set-Content -Path '{tk / 'reference' / 'libraries' / 'wares.xml'}' -Value 'x'"
    _, as_ps, _ = check(env, "--kind", "shell", "--shell", "powershell", "--command", cmd)
    _, as_bash, _ = check(env, "--kind", "shell", "--shell", "bash", "--command", cmd)
    assert as_ps["decision"] == "deny"
    assert as_bash["decision"] != "deny"   # if this ever denies, pick a new twin: routing is no longer shown


def test_shell_echo_allows(sandbox):
    _, _, env = sandbox
    rc, v, _ = check(env, "--kind", "shell", "--shell", "bash", "--command", "echo hello")
    assert rc == 0 and v["decision"] == "allow"


@pytest.mark.parametrize("kind", ["write", "delete"])
def test_write_and_delete_into_reference_deny(sandbox, kind):
    _, tk, env = sandbox
    rc, v, _ = check(env, "--kind", kind, "--path", str(tk / "reference" / "libraries" / "wares.xml"))
    assert rc == 0 and v["decision"] == "deny" and v["guards"] == ["protect-files.sh"]


def test_write_path_with_spaces_and_backslashes(sandbox):
    tmp, _, env = sandbox
    p = str(tmp / "X4 Foundations" / "libraries" / "wares.xml").replace("/", "\\")
    _, v, _ = check(env, "--kind", "write", "--path", p)
    assert v["decision"] == "deny"           # a base-game file, named with backslashes and a space


def test_manifest_advises_and_profile_asks(sandbox):
    tmp, tk, env = sandbox
    _, adv, _ = check(env, "--kind", "write", "--path", str(tk / "dev" / "mymod" / "content.xml"))
    _, ask, _ = check(env, "--kind", "write", "--path", str(tmp / "profile" / "content.xml"))
    assert adv["decision"] == "advise" and ask["decision"] == "ask"


def test_check_has_no_side_effects(sandbox):
    tmp, tk, env = sandbox
    check(env, "--kind", "write", "--path", str(tk / "reference" / "libraries" / "wares.xml"))
    assert list((tmp / "backups").iterdir()) == []


def test_missing_guard_is_inert_deny(sandbox, tmp_path):
    _, _, env = sandbox
    lone = tmp_path / "lone"
    lone.mkdir()
    shutil.copy2(X4GUARD, lone / "x4guard.py")
    rc, v, _ = check(env, "--kind", "shell", "--shell", "bash", "--command", "echo hi", script=lone / "x4guard.py")
    assert rc == 0 and v["decision"] == "deny" and v["inert"] and "missing" in v["reason"]


def test_wsl_bash_refused(sandbox):
    _, _, env = sandbox
    env = dict(env, X4_BASH=r"C:\Windows\System32\bash.exe")
    _, v, _ = check(env, "--kind", "shell", "--shell", "bash", "--command", "echo hi")
    assert v["decision"] == "deny" and v["inert"] and "WSL" in v["reason"]


def test_missing_bash_is_inert_deny(sandbox, tmp_path):
    _, _, env = sandbox
    env = dict(env, X4_BASH=str(tmp_path / "no-such-bash.exe"))
    _, v, _ = check(env, "--kind", "shell", "--shell", "bash", "--command", "echo hi")
    assert v["decision"] == "deny" and v["inert"]


def test_unparseable_guard_output_is_inert_deny():
    sys.path.insert(0, str(X4GUARD.parent))
    import x4guard
    with pytest.raises(ValueError):
        x4guard.parse_hook_output("{not json")
    with pytest.raises(ValueError):
        x4guard.parse_hook_output('{"hookSpecificOutput": {"permissionDecision": "maybe"}}')


def test_usage_error_is_rc2(sandbox):
    _, _, env = sandbox
    rc, _, err = check(env, "--kind", "shell", "--shell", "bash")
    assert rc == 2 and "--command" in err
```

- [ ] **Step 2: Run them; expect FAIL.** If `pwsh` is absent, the routing test SKIPS and says so. Check the ubuntu `X4_MAX_SKIPS` ceiling in `.github/workflows/ci.yml` (around line 589) if CI lacks pwsh. GitHub's ubuntu runners ship pwsh, so expect no new skip.

- [ ] **Step 3: Implement** `agent/guards/claude-hooks/x4guard.py`:

```python
#!/usr/bin/env python3
"""x4guard -- one front door to the toolkit's guards (Layer 0 of the agent-portability design).

    python x4guard.py check --kind shell --shell {bash,powershell} --command CMD
    python x4guard.py check --kind {write,delete} --path P

Prints ONE JSON verdict and exits 0:
    {"v":1,"decision":"allow|advise|ask|deny","reason":...,"context":...,"inert":bool,"guards":[...]}
Exit 2 only on a usage error. It runs the SAME guard scripts Claude Code runs, with the payload shape
they already read, and NO side effects (backup-before-edit.sh is never run by a check).

A guard that could not run is never an allow: missing script, no bash, the WSL bash stub, a
timeout, a non-zero exit or unreadable output all return decision "deny" with inert=true and the
cause named. An agent that can ask the user may present an inert deny as a question; it may not
present it as an allow. Stdlib only; Python >= 3.10.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RANK = {"allow": 0, "advise": 1, "ask": 2, "deny": 3}
TIMEOUT_S = 25


def resolve_bash() -> tuple[str | None, str | None]:
    cand = os.environ.get("X4_BASH") or shutil.which("bash.exe") or shutil.which("bash")
    if not cand:
        return None, "no bash found (set X4_BASH to Git Bash)"
    if "system32" in cand.replace("/", "\\").lower():
        return None, f"refusing the WSL bash stub ({cand}): it cannot run a Windows-path guard; set X4_BASH to Git Bash"
    if not Path(cand).is_file():
        return None, f"X4_BASH points at nothing: {cand}"
    return cand, None


def guard_payload(kind: str, shell: str | None, command: str | None, path: str | None) -> dict:
    if kind == "shell":
        return {"tool_name": "PowerShell" if shell == "powershell" else "Bash",
                "tool_input": {"command": command}}
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": ""}}


def parse_hook_output(out: str) -> tuple[str, str | None, str | None]:
    out = out.strip()
    if not out:
        return "allow", None, None
    try:
        hso = json.loads(out)["hookSpecificOutput"]
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(f"guard output is not a hook verdict: {out[:120]!r}") from e
    decision = hso.get("permissionDecision")
    if decision in ("deny", "ask"):
        return decision, hso.get("permissionDecisionReason"), None
    if decision is None and "additionalContext" in hso:
        return "advise", None, hso["additionalContext"]
    raise ValueError(f"unrecognised hook verdict: {hso!r}")


def _inert(reason: str, guards: list[str]) -> dict:
    return {"v": 1, "decision": "deny", "inert": True, "guards": guards, "context": None,
            "reason": f"X4 GUARD INERT: {reason}. NOTHING was checked; this is a refusal, not a verdict on the command."}


def verdict_for(kind: str, shell: str | None, command: str | None, path: str | None) -> dict:
    script = "protect-bash.sh" if kind == "shell" else "protect-files.sh"
    guards = [script]
    target = HERE / script
    if not target.is_file():
        return _inert(f"guard script missing: {script}", guards)
    bash, why = resolve_bash()
    if not bash:
        return _inert(why, guards)
    payload = json.dumps(guard_payload(kind, shell, command, path)).encode("utf-8")
    try:
        r = subprocess.run([bash, str(target)], input=payload, capture_output=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return _inert(f"{script} timed out after {TIMEOUT_S}s", guards)
    except OSError as e:
        return _inert(f"{script} could not start: {e}", guards)
    if r.returncode != 0:
        return _inert(f"{script} exited {r.returncode}", guards)
    try:
        decision, reason, context = parse_hook_output(r.stdout.decode("utf-8", "replace"))
    except ValueError as e:
        return _inert(str(e), guards)
    return {"v": 1, "decision": decision, "reason": reason, "context": context, "inert": False, "guards": guards}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="x4guard", description="Ask the toolkit's guards for a verdict.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--kind", required=True, choices=("shell", "write", "delete"))
    c.add_argument("--shell", choices=("bash", "powershell"))
    c.add_argument("--command")
    c.add_argument("--path")
    a = ap.parse_args(argv)
    if a.kind == "shell" and (not a.shell or a.command is None):
        ap.error("--kind shell needs --shell and --command")
    if a.kind != "shell" and not a.path:
        ap.error(f"--kind {a.kind} needs --path")
    v = verdict_for(a.kind, a.shell, a.command, a.path)
    sys.stdout.write(json.dumps(v) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Regenerate** (Task 4's generator copies `x4guard.py` into `.claude/hooks/`), then run the new tests and expect PASS. Read every skip reason. Then run `uv run --no-project python scripts/scan-identifiers.py` and expect it clean.
- [ ] **Step 5: Mutation twins, run by hand and recorded in the commit** (CLAUDE.md #26). Apply each temporarily to `agent/guards/claude-hooks/x4guard.py`, regenerate, run `test_x4guard_check.py`, confirm the named test goes RED, revert, and clear `__pycache__`:

  | Mutant | Must turn red |
  |---|---|
  | `"PowerShell" if shell == "powershell"` → `"Bash"` | `test_shell_routing_decides_the_verdict` |
  | `_inert` returns `"allow"` | `test_missing_guard_is_inert_deny` |
  | remove the `system32` check | `test_wsl_bash_refused` |
  | `parse_hook_output` returns `"allow"` on bad JSON | `test_unparseable_guard_output_is_inert_deny` |

- [ ] **Step 6: Commit** with explicit paths. Message: `x4guard check: one side-effect-free front door to the guards; anything that keeps a guard from running is an inert deny`. Include the mutant table in the body.

---

## Task 6: Phase-2 gate — full functionality check and docs

**Files:** `CHANGELOG.md` and `agent/README.md` (docs only).

- [ ] **Step 1: Run the full regression set,** each result matching the pre-plan baseline:
  - pytest: 2,966 passed and 3 skipped, plus the new tests
  - `test-protect-bash.sh`
  - `test-hooks.sh`: 177/177
  - `test_hook_facts.py`
  - `test_audit0924_hooks.py`: 57/57
  - the fuzzer
  - `verify-hook-tests.py`
  - `gen-agent-trees.py --check`: rc 0
  - `gen-cli-reference.py --check`: rc 0
  - `scan-identifiers.py`: clean
- [ ] **Step 2: Deploy.** Run the dry run, then `--apply`. Expect `x4guard.py` as one **create**, and nothing else changed in `hooks/`. Run `gates/deploy_parity.py`: identical.
- [ ] **Step 3: Live end-to-end in a fresh Claude Code session in the game root** (prove it ran):
  - **(a)** a Bash `rm` on a decoy file inside `reference\` is denied with the usual message;
  - **(b)** an Edit of a decoy file under `reference\` is denied;
  - **(c)** a diff-XML edit in a dev mod shows the x4validate advisory;
  - **(d)** the session-start lines appear;
  - **(e)** `python "<game>/.claude/hooks/x4guard.py" check --kind write --path "<real reference>\libraries\wares.xml"` prints a deny that is not inert;
  - **(f)** the same with `--kind shell --shell powershell --command "Remove-Item -Force '<real reference>\libraries\wares.xml'"` prints a deny. Nothing executes in (e) or (f); they are verdicts only.

  Record every outcome in the commit message.
- [ ] **Step 4: Docs.**
  - CHANGELOG `## Unreleased`: "`x4guard check` (`.claude/hooks/x4guard.py`): ask the guards for a verdict from any agent; a guard that cannot run is reported as an inert deny, never an allow."
  - `agent/README.md`: one paragraph on `agent/guards/claude-hooks/`, saying the guards are edited here and the generator copies them byte-identical.
- [ ] **Step 5: Commit**, and report the totals to the user.

---

## Self-review

- **Spec coverage**, phases 1–2 of spec §10:
  - §4 layout: Tasks 1, 2 and 4.
  - §4 generated and committed with banners: Tasks 1 and 2.
  - §5.1 engine unchanged: Task 4 (byte identity).
  - §5.6 front door: Task 5.
  - §7.1 existing suites stay green: Tasks 4 and 6.
  - §5.4 `entry.sh`: Plan 2, per the clarification above.
  - §6 instruction split: phase 3, a separate plan.
- **Placeholder scan:** one step says "copy verbatim from the current file". That is a mechanical copy with a test that pins the result (Step 5's zero-diff proof), not a gap.
- **Type and name consistency:**
  - `generate`, `problems`, `OWNED`, `BANNER_MD`, `TOKEN` and `GenerationError` match across Tasks 1, 2 and 4.
  - `verdict_for`, `parse_hook_output` and `resolve_bash` are named exactly as Plan 2 will consume them.
- **Review Focus:** each of the five lines has a named test in its owning task.

## Execution handoff

Recommended: **subagent-driven**, meaning a fresh implementer and a fresh reviewer per task. There are 6 tasks; Tasks 1→2→4→5 chain through the generator's interface, and a mistake in Task 4 or 5 sits directly on the guard layer that protects the user's install. Task 3 and Task 6's live steps need the main session, because they need a fresh Claude Code session in the game root.

# Universal Agent Support, Plan 2, Lane A: the instruction split (spec phase 3, plus Layer-1 skills for Codex)

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the stopgap `AGENTS.md`, which today is `agent/instructions/codex.md` alone, with real shared instructions. The result is one agent-neutral core plus a per-agent addendum for each agent, assembled by `gen-agent-trees.py`. The generator **refuses** whenever `AGENTS.md` would exceed 32,768 BYTES or `CLAUDE.md` would exceed 40,000 CHARACTERS. It never truncates. Maintainer-only guidance moves verbatim into a new `x4-toolkit-dev` skill. The same skill sources also reach Codex and generic agents as `.agents/skills/`.

**Repo:** `$X4_TOOLKIT` = `$X4_TOOLKIT`, branch `master`. Below, `PKG` = `tools/x4validate`. Focused tests: `cd tools/x4validate && uv run --frozen python -m pytest -q -rs <file>`.

**Spec:** `docs/superpowers/specs/2026-09-30-universal-agent-support-design.md`, sections 4 and 6 and phase 3 of section 10. **Evidence:** `docs/superpowers/measurements/2026-09-30-codex-spike.md`.

## Context: what was measured for this plan (2026-10-02, read-only)

| Fact | Tier |
|---|---|
| `agent/instructions/core.md` holds **39,939 chars / 40,288 bytes**. `CLAUDE.md` = core + `<!-- GENERATED from agent/ -->` banner. `claude.md` is 0 bytes and `codex.md` is 3,550 bytes. | MEASURED (python, LF-normalised) |
| The five sections the spec moves (Narrows Data, Derived Artifact incl. "Memory and loaded context", Trustworthy-before-Lock, Bug Funnel, Concurrent Sessions incl. its 2 subsections) total **11,737 bytes / 11,659 chars**, which leaves core at **28,551 bytes / 28,280 chars** (spec section 6 said "about 11.9 KB, core about 29 KB"). | MEASURED |
| Seven routing rows whose "Use" column is a Python internal or a maintainer gate (`_scan.iter_mod_xml`, `_registry.mods` x2, `_scan.iter_corpus_xml`, `_effective.base_vpaths`, `x4effective dump --chain`, `gates/mutation_probe.py`) total **2,181 bytes**. One of them (`x4effective dump --chain`) is a CLI row and must stay, so about 6 rows / ~1.9 KB are movable. | MEASURED |
| The Claude-only tokens in core.md: `.claude/` x5, `.claude\` x2, `CLAUDE.md` x3, `CLAUDE_PROJECT_DIR` x2, `Claude Code` x2, `NotebookEdit` x2, `**Grep**` x2, `**Glob**` x1, `Claude` x1, `MEMORY.md` x1, `settings.json` x1. | MEASURED (grep -o) |
| These tests and gates READ the shipped `CLAUDE.md` text: `gates/claude_md_budget.py`, `gates/routing_coverage.py`, `tests/test_reference_fingerprint.py:210` (the `_freshness.ENGINE_SOURCES` cell, **which sits in the Derived Artifact section that moves**), `tests/test_config_precedence_agrees.py:34` (pins the phrase ``env var > `x4-paths.env` > default``), `tests/test_build_scripts_check_their_stamp.py:129` (the `build-corpus.sh` population; the rebuild line also moves), `tests/test_write_verb_promises_are_consistent.py:27`, and `tests/test_gen_agent_trees.py`. | MEASURED (grep over `tools/**/*.py`) |
| **`git check-ignore -v .agents/skills/x4-cli-reference/reference/x4save.md` returns `.gitignore:33:reference/`.** The exact bug from 2026-09-13 would recur for `.agents/skills`: the 11 generated help files would be silently uncommitted. | MEASURED (rc 0) |
| In pwsh 7 with `X4_TOOLKIT=probe-value` in the environment, `"$X4_TOOLKIT"` expands to **empty** and `$env:X4_TOOLKIT` to `probe-value`. Every `{{TOOLKIT}}` use (7 skills + 1 agent, all `cd {{TOOLKIT}}/tools/x4validate ...`) rendered as `$X4_TOOLKIT` therefore breaks under Codex-on-Windows, which runs PowerShell. It breaks loudly: `cd /tools/x4validate` fails. | MEASURED |
| Skill frontmatter keys: `name`, `description`, and `allowed-tools` on 9 of 10 skills. Descriptions run 213–682 chars. Codex ignores unknown frontmatter keys. | MEASURED (keys/lengths) / MEASURED on Codex 0.154 only (ignoring) |
| Codex reads `.agents/skills/`. | MEASURED on **0.154 only** (Skyrim session). **Not re-measured on 0.159.2**: Task 2 does it. |
| Codex truncates AGENTS.md "at 32 KiB". A 46,737-byte file was truncated and a 1,547-byte file was not. **The exact boundary, whether the budget is shared across a nested AGENTS.md chain, and whether a non-git directory loads AGENTS.md at all are NOT measured.** | MEASURED (coarse) / ASSUMED (boundary, chain, non-git) |
| Claude Code does not auto-load `AGENTS.md`. If it did, a Claude session would get the core twice. | ASSUMED: Task 2 measures it |
| The only tracked instruction files are `AGENTS.md`, `CLAUDE.md` and `agent/instructions/claude.md`. No nested AGENTS.md ships. | MEASURED (git ls-files) |

**Projected sizes (INFERRED from the measurements above; Task 1 re-measures them on the real cut before any text moves):** core after the spec's move is ~28.6 KB. Adding a ~0.8 KB stub/pointer and roughly neutral neutralisation gives ~29.0 KB. `AGENTS.md` = that + a ~2.4 KB Codex addendum + ~0.1 KB title/banner ≈ **31.5 KB, so only ~1.3 KB of headroom under 32,768 bytes**. That is too thin for one routine core edit, plus the lines lanes C and D must add to the Codex addendum. With the ~1.9 KB of maintainer routing rows also moved, headroom is ≈ **3.2 KB**. `CLAUDE.md` lands at ≈ 30 K chars, about 10 K under its ceiling. **The binding constraint is AGENTS.md bytes, not CLAUDE.md chars.**

## Global constraints

- **Edit `agent/`, then regenerate. Never edit `CLAUDE.md`, `AGENTS.md`, `.claude/` or `.agents/` by hand.** Run `cd tools/x4validate && uv run python scripts/gen-agent-trees.py`, then `--check` → `Expected: rc 0`.
- **Text is relocated, never deleted** (spec section 6). Each relocation is verified paragraph by paragraph (Task 4, Step 5). Neutralisation rewrites are listed by hand in the commit message.
- **Refuse, never truncate.** Every size or shape failure in the generator is a `GenerationError` → rc 2 with the cause named. A partial output is never written (`generate()` stays pure).
- Characters for CLAUDE.md are counted the way `gates/claude_md_budget.char_count` counts them: UTF-8 decode, CRLF→LF. Bytes for AGENTS.md are `len(text.encode("utf-8"))` on the LF text. Generated files are written LF.
- Encode first, then `write_bytes`. Write file content with the Write tool, never a heredoc (backslashes are lost).
- Stage explicit paths only (`git add -A` is a hook DENY). One commit per task on `master`. Never push.
- **Never regenerate, copy or commit while `gates/mutation_probe.py` runs** (#27).
- Hooks are untouched by this lane. `.claude/hooks/` must stay byte-identical (`test_hooks_are_generated_byte_identical`).
- No personal paths in generated output (`test_no_personal_path_reaches_generated_output`, `scripts/scan-identifiers.py`).

## Interfaces

**Produces (in `tools/x4validate/scripts/gen-agent-trees.py`):**

```python
ADDENDUM_MARKER = "{{AGENT_ADDENDUM}}"          # exactly one line in core.md, replaced per agent
CLAUDE_MD_MAX_CHARS = 40_000                     # == gates/claude_md_budget.HARD_CEILING (pinned by a test)
AGENTS_MD_MAX_BYTES = 32_768                     # unchanged; Codex silent truncation
AGENTS_MD_WARN_HEADROOM = 2_048                  # advisory line only, never a refusal
TARGETS: dict[str, dict]                         # per agent: entry file, addendum file, token values, skills dir
#   "claude": entry "CLAUDE.md", addendum "claude.md", skills ".claude/skills/",
#             tokens {"{{TOOLKIT}}": "$CLAUDE_PROJECT_DIR", "{{PROJECT_DIR}}": "$CLAUDE_PROJECT_DIR"}
#   "codex":  entry "AGENTS.md", addendum "codex.md", skills ".agents/skills/",
#             tokens {"{{TOOLKIT}}": <user Q2; recommended "$X4_TOOLKIT">,
#                     "{{PROJECT_DIR}}": "the project root (the folder the agent was started in)"}
#   both:     "{{GENERATED_FILES}}" rendered from OWNED (single source of truth)
NEUTRALITY_BANNED: tuple[tuple[str, str], ...]   # (regex, reason) applied to core.md SOURCE
NEUTRALITY_ALLOWED: tuple[str, ...]              # exact substrings exempted, each with a comment
def render_entry(src: Path, agent: str) -> str   # title (addendum line 1) + banner + core with addendum at marker
def check_neutral(core: str) -> None             # raises GenerationError naming pattern + line number
def size_report(out: dict[str, str]) -> list[str]  # "CLAUDE.md 30,112/40,000 chars", "AGENTS.md 29,8xx/32,768 bytes"
def render_skills(src: Path, agent: str) -> dict[str, str]   # agent-parameterised; claude output byte-identical
OWNED += (".agents/skills/",)
```

**Addendum file format** (`agent/instructions/<agent>.md`): line 1 must be an H1 (`# ...`). It becomes the entry file's title, followed by the banner. Lines 2+ are the body inserted at `{{AGENT_ADDENDUM}}`. An addendum that is empty, has no H1 on line 1, or has an empty body raises a refusal.

**Core format** (`agent/instructions/core.md`): no H1, because the title comes from the addendum. Exactly one `{{AGENT_ADDENDUM}}` line. Tokens are limited to `{{TOOLKIT}}`, `{{PROJECT_DIR}}` and `{{GENERATED_FILES}}`, and any other `{{...}}` left after rendering is a refusal.

**Consumes:** nothing from other lanes to start. See *Cross-lane dependencies* for the lines lanes C, D and E add to `codex.md` later, within the byte budget reserved here.

---

## Task 1: Measure the proposed split BEFORE moving any text

No repo changes. The output is a numbers table pasted into Task 4's commit message and into the measurement doc from Task 2.

**Files:** scratch only: `<scratchpad>/laneA/split_sizes.py` (never in the repo).

- [ ] **Step 1: Write the calculator.** It reads `agent/instructions/core.md` (bytes, CRLF→LF), splits on `## ` headings, and takes a MOVE manifest of heading prefixes plus row prefixes. It prints bytes/chars for: moved set, core', projected CLAUDE.md (core' + a draft claude addendum file), projected AGENTS.md (core' + a draft codex addendum + `# AGENTS.md ...` title + banner), and headroom against 40,000 chars and 32,768 bytes. It **refuses** (exit 2) when any manifest prefix matches 0 or more than 1 heading or row, so that a typo cannot under-count what moves (#35).

```python
import sys, pathlib
core = pathlib.Path(sys.argv[1]).read_bytes().decode("utf-8").replace("\r\n", "\n")
MOVE_H2 = ["## Core Principle: A Step That Narrows Data", "## Core Principle: A Derived Artifact",
           "## Core Principle: Tools Must Be Trustworthy", "## Core Principle: Bug Handling Is a FUNNEL",
           "## Concurrent Sessions:"]
MOVE_ROWS = ['| **"every XML a mod owns?"**', '| **"which MODS count?"**', '| **"is this mod installed',
             '| **"scan EVERY installed mod', '| **"every base+DLC vpath?"**', '| mutation-test code?']
lines = core.split("\n"); heads = [i for i, l in enumerate(lines) if l.startswith("## ")]
spans = dict(zip(heads, heads[1:] + [len(lines)]))
moved = []
for p in MOVE_H2:
    hit = [i for i in heads if lines[i].startswith(p)]
    if len(hit) != 1: sys.exit(f"REFUSING: {p!r} matched {len(hit)} headings")
    moved += lines[hit[0]:spans[hit[0]]]
option_b = "--rows" in sys.argv
if option_b:
    for p in MOVE_ROWS:
        hit = [l for l in lines if l.startswith(p)]
        if len(hit) != 1: sys.exit(f"REFUSING: {p!r} matched {len(hit)} rows")
        moved += hit
mv = "\n".join(moved) + "\n"
rest = core
for blk in [ "\n".join(lines[i:spans[i]]) + "\n" for p in MOVE_H2 for i in heads if lines[i].startswith(p)]:
    rest = rest.replace(blk, "", 1)
if option_b:
    for p in MOVE_ROWS:
        rest = "\n".join(l for l in rest.split("\n") if not l.startswith(p))
cl = pathlib.Path(sys.argv[2]).read_bytes().decode().replace("\r\n", "\n")   # draft claude addendum
cx = pathlib.Path(sys.argv[3]).read_bytes().decode().replace("\r\n", "\n")   # draft codex addendum
stub = pathlib.Path(sys.argv[4]).read_bytes().decode().replace("\r\n", "\n")  # draft core stub/pointer
banner = "<!-- GENERATED from agent/ -->\n\n"
claude = rest + stub + banner + cl; agents = rest + stub + banner + cx
print(f"moved        {len(mv.encode()):6d} B {len(mv):6d} ch")
print(f"core'        {len((rest+stub).encode()):6d} B {len(rest+stub):6d} ch")
print(f"CLAUDE.md    {len(claude):6d} ch  headroom {40000-len(claude):+d}")
print(f"AGENTS.md    {len(agents.encode()):6d} B   headroom {32768-len(agents.encode()):+d}")
```

- [ ] **Step 2: Draft the three inputs in scratch.** `claude-addendum.md` holds the Claude-specific lines that Task 5 will lift out of core: hook wiring, `$CLAUDE_PROJECT_DIR` anchoring, the "Guarded: Bash, PowerShell, Edit, Write, NotebookEdit; a timed-out hook (30 s) does NOT block" line, the backup line, and the Glob/Grep rows. `codex-addendum.md` is the Task 6 draft. `stub.md` holds the core pointer to `x4-toolkit-dev`, the X4-NOTES.md line, the generated-files line and the 3-line freshness stub.

- [ ] **Step 3: Run both options.**

```
uv run python <scratch>/laneA/split_sizes.py agent/instructions/core.md <scratch>/laneA/claude-addendum.md <scratch>/laneA/codex-addendum.md <scratch>/laneA/stub.md
uv run python <scratch>/laneA/split_sizes.py ... --rows
```

Expected: option A `moved 11737 B`, AGENTS.md headroom roughly +1,000..+1,600. Option B: headroom roughly +2,900..+3,500. CLAUDE.md headroom above +9,000 in both. **Write the prediction down before running** (#22). If `moved` differs from 11,737 in option A, the manifest or core changed: stop and re-derive.

- [ ] **Step 4: Decision rule (pre-committed).** Proceed with the option whose AGENTS.md headroom is **≥ 2,048 bytes**. That reserve covers lanes C and D (x4doctor and OS-lock lines, ~400 B) plus one ordinary core edit. If only option B meets it, option B needs the user's yes on **Q1** before Task 4. If neither does, stop and report the numbers. Do not trim prose to fit.

Confidence **95%**. It is pure measurement, and the manifest refuses on a mismatch.

---

## Task 2: Measure what Codex (0.159.2) and Claude Code actually load

The design rests on three facts that are ASSUMED today. Every outcome is read from **disk** (does a flag file exist?), never from the model's own report, following the spike's method. Each probe runs twice, plus a control. Everything happens in `<scratchpad>/laneA/m/`, never in the game root.

**Files:** create `docs/superpowers/measurements/2026-10-0X-agents-md-and-skills.md` (results, with each row labelled MEASURED and the Codex version recorded).

- [ ] **M-A1 (skills, Codex):** `git init` a scratch dir and add `.agents/skills/probe-magenta/SKILL.md` with frontmatter `name`, `description: Use when asked to run the MAGENTA-PROBE procedure.`, and `allowed-tools: Read` (an unknown key). The body says "create `SKILL-FIRED.txt` containing `4242`, then read `reference/extra.md` and create a file named after the word in it". `reference/extra.md` contains one word.
  `codex exec --sandbox workspace-write "Run the MAGENTA-PROBE procedure."`
  Expected: both files exist. Control: move the skill dir away and re-run. Expected: neither file exists. Variant: launch from a subdirectory and record whether `.agents/skills` is found from the git root.
  Also record any skill-description length limit Codex prints.
- [ ] **M-A2 (AGENTS.md boundary, chain, non-git):** generate files of exactly **32,768** and **32,769** bytes whose LAST line instructs "create `TAIL-SEEN.txt`". Expected (prediction): 32,768 → file created; 32,769 → not created. Chain: root `AGENTS.md` of 20,000 B with a head instruction (`HEAD.txt`) plus `sub/AGENTS.md` of 20,000 B with a tail instruction (`SUBTAIL.txt`), launched in `sub/`. This answers whether the cap is shared across the chain. Non-git: the same 1.5 KB control in a dir with no `.git`.
- [ ] **M-A3 (Claude Code and AGENTS.md):** in a scratch dir holding ONLY `AGENTS.md`, which says "create `CLAUDE-READ-AGENTS.txt`", run `claude -p --model haiku "Do what your project instructions say."`. Expected (prediction): the file is NOT created, so Claude does not double-load the core. Control: the same text in `CLAUDE.md` → created.

**Consequences, pre-committed:**
- M-A1 fails on 0.159.2 → Task 7 still generates `.agents/skills` (generic agents and OpenCode use it), but the Codex addendum must point to `.agents/skills/<name>/SKILL.md` by path. Record it as a gap.
- M-A2 shows a shared chain budget → add a test that the repo ships no second `AGENTS.md` and an install note for lane C.
- M-A2 boundary below 32,768 → lower `AGENTS_MD_MAX_BYTES` to the measured value.
- M-A3 shows Claude reads AGENTS.md → STOP. That is a design change: both files would load and need a decision.

Commit: `docs(measurements): Codex 0.159.2 skills discovery, AGENTS.md boundary/chain, Claude vs AGENTS.md`

Confidence **85%**. Model compliance adds noise, which the repeats and controls absorb. It needs the user's Codex and Claude credentials, but no approvals are written. The installer never trusts a project.

---

## Task 3: Generator: per-agent assembly at a marker, CLAUDE.md char refusal, leftover-token refusal (CLAUDE.md byte-identical)

**Files:** `tools/x4validate/scripts/gen-agent-trees.py`, `tools/x4validate/tests/test_gen_agent_trees.py`, `agent/instructions/core.md` (move the H1 out; add the marker as the LAST line), `agent/instructions/claude.md` (line 1 = today's H1, verbatim), `agent/README.md` (one paragraph on the marker and addendum format).

AGENTS.md keeps the stopgap rendering in this task, so the change stays small and CLAUDE.md is provably unchanged.

- [ ] **Step 1: Failing tests.**

```python
def test_claude_md_is_title_banner_core_with_addendum_at_the_marker(tmp_path):
    import shutil
    g = load(); shutil.copytree(REPO / "agent", tmp_path / "agent")
    (tmp_path / "agent/instructions/core.md").write_bytes(b"intro\n\n{{AGENT_ADDENDUM}}\n\noutro\n")
    (tmp_path / "agent/instructions/claude.md").write_bytes(b"# T\n\nADD\n")
    out = g.render_entry(tmp_path / "agent", "claude")
    assert out == "# T\n\n<!-- GENERATED from agent/ -->\nintro\n\nADD\n\noutro\n"

@pytest.mark.parametrize("core", [b"no marker\n", b"{{AGENT_ADDENDUM}}\n{{AGENT_ADDENDUM}}\n"])
def test_TWIN_marker_count_other_than_one_refuses(tmp_path, core):
    import shutil
    g = load(); shutil.copytree(REPO / "agent", tmp_path / "agent")
    (tmp_path / "agent/instructions/core.md").write_bytes(core)
    with pytest.raises(g.GenerationError, match="AGENT_ADDENDUM"):
        g.render_entry(tmp_path / "agent", "claude")

@pytest.mark.parametrize("addendum", [b"", b"no title\nbody\n"])
def test_TWIN_addendum_without_an_h1_title_refuses(tmp_path, addendum):
    import shutil
    g = load(); shutil.copytree(REPO / "agent", tmp_path / "agent")
    (tmp_path / "agent/instructions/claude.md").write_bytes(addendum)
    with pytest.raises(g.GenerationError, match="title"):
        g.render_entry(tmp_path / "agent", "claude")

def test_TWIN_an_oversized_claude_md_refuses(tmp_path):
    import shutil
    g = load(); shutil.copytree(REPO / "agent", tmp_path / "agent")
    p = tmp_path / "agent/instructions/core.md"
    p.write_bytes(p.read_bytes() + ("\u2605" * 400 + "\n").encode() * 30)  # +12,030 CHARS, ~36 KB bytes
    with pytest.raises(g.GenerationError, match="40000 characters|40,000 characters"):
        g.generate(tmp_path)

def test_claude_md_limit_is_counted_in_CHARACTERS_not_bytes(tmp_path):
    # twin of the above: multi-byte text under 40,000 chars but over 40,000 BYTES must pass
    import shutil
    g = load(); shutil.copytree(REPO / "agent", tmp_path / "agent")
    claude = len(g.render_entry(tmp_path / "agent", "claude"))
    room = g.CLAUDE_MD_MAX_CHARS - claude - 10
    p = tmp_path / "agent/instructions/claude.md"
    p.write_bytes(p.read_bytes() + ("\u2605" * room).encode())       # 3 bytes each
    out = g.render_entry(tmp_path / "agent", "claude")
    assert len(out) <= g.CLAUDE_MD_MAX_CHARS < len(out.encode("utf-8"))

def test_claude_md_ceiling_is_the_budget_gates_ceiling():
    from conftest import import_gate
    assert load().CLAUDE_MD_MAX_CHARS == import_gate("claude_md_budget").HARD_CEILING

def test_TWIN_an_unknown_token_left_after_rendering_refuses(tmp_path):
    import shutil
    g = load(); shutil.copytree(REPO / "agent", tmp_path / "agent")
    p = tmp_path / "agent/instructions/core.md"
    p.write_bytes(p.read_bytes() + b"\n{{NOT_A_TOKEN}}\n")
    with pytest.raises(g.GenerationError, match="NOT_A_TOKEN"):
        g.generate(tmp_path)
```

Run: `uv run --frozen python -m pytest -q tests/test_gen_agent_trees.py`. Expected: the 7 new tests FAIL (`render_entry`/`CLAUDE_MD_MAX_CHARS` missing). Every existing test passes.

- [ ] **Step 2: Implement.** Add `render_entry(src, agent)`. It reads the addendum and requires line 1 to start with `# ` (else refuse "title"). It reads core, requires `core.count(ADDENDUM_MARKER + "\n") == 1` and refuses otherwise, naming the count. It replaces the marker line with the addendum body (lines 2+, stripped of leading and trailing blank lines). An **empty body is allowed in this task only**, because Claude's addendum is empty today; Task 5 makes it a refusal. It then applies `TARGETS[agent]["tokens"]` plus `{{GENERATED_FILES}}`, refuses on any remaining `\{\{[A-Z_]+\}\}` naming the token, and returns `title + "\n\n" + BANNER_CLAUDE_MD + "\n" + body`. `render_claude_md` becomes `render_entry(src, "claude")` plus the char refusal. When it refuses, the message lists the 5 largest `## ` sections with their sizes, so the operator knows where to cut. Add `size_report()` and print it on every successful write and `--check` run (stdout, advisory).

- [ ] **Step 3: Move the H1** from core.md line 1 into `claude.md` line 1 verbatim. Put the marker where the old `out.rstrip + addendum` appended it: the LAST line of core.md.

- [ ] **Step 4: Prove CLAUDE.md is byte-identical.**

```
cd tools/x4validate && uv run python scripts/gen-agent-trees.py && cd ../.. && git diff --exit-code -- CLAUDE.md AGENTS.md .claude; echo rc=$?
```

Expected: `rc=0`. Prediction: identical. Today's render puts the banner after line 1 and appends an empty addendum, and the new render reproduces exactly that. If the diff is non-empty, the blank-line handling around the marker is wrong. Fix the generator, not the test.

- [ ] **Step 5:** `uv run --frozen python -m pytest -q tests/test_gen_agent_trees.py tests/test_claude_md_budget.py`. Expected: all pass.

Commit: `gen-agent-trees: assemble entry files from core + addendum at one marker; refuse CLAUDE.md > 40,000 chars and leftover tokens (CLAUDE.md byte-identical)`

Confidence **90%**.

---

## Task 4: Relocate the maintainer sections into a new `x4-toolkit-dev` skill (verbatim)

**Files:** create `agent/skills/x4-toolkit-dev/SKILL.md`. Modify `agent/instructions/core.md`, `tools/x4validate/tests/test_gen_agent_trees.py` (skill count 10→11), `tools/x4validate/tests/test_reference_fingerprint.py`, `tools/x4validate/tests/test_build_scripts_check_their_stamp.py`, `agent/instructions/codex.md` (its section 2 "edit agent/", section 4 Git and section 5 Tests move to the skill; the stopgap section 1 stays until Task 6). Generated: `CLAUDE.md`, `AGENTS.md`, `.claude/skills/x4-toolkit-dev/SKILL.md`.

What moves: the five H2 sections from Task 1, each with its subsections, plus core lines 95–96 ("Edit hooks in `agent/guards/claude-hooks/`... `bash scripts/test-hooks.sh`"). The 6 Python-API routing rows move too **if and only if** Task 1 selected option B and the user said yes to Q1. They move as a table with the same header, so the skill reads as a table.

What stays in core: a stub of about 700 bytes at the old Derived-Artifact position. Draft:

> **Working ON the toolkit** — its code, gates, hooks, generator or `agent/` source — **load the `x4-toolkit-dev` skill first**: it holds the rules for derived-artifact freshness, narrowing steps, the bug funnel, concurrent sessions, and trusting tools before a modlist lock.
> **A CLI banner saying UNKNOWN or STALE means the artifact may not describe your files: rebuild** (`uv run x4effective build` · `uv run x4xref build` · `cd tools/basex; bash build-corpus.sh; bash build-effective.sh`) before you trust a number from it. An absent fingerprint is UNKNOWN, never fresh.
> **Your own notes go in `X4-NOTES.md`** in the project root. Read it at session start if it exists. The toolkit never writes or overwrites it. Never edit {{GENERATED_FILES}}: they are regenerated and your edit is lost.

Note: the rebuild line keeps `bash build-corpus.sh; bash build-effective.sh` with `;`, never `&&`, which `test_build_scripts_check_their_stamp` enforces.

- [ ] **Step 1: Failing tests.**

```python
# test_gen_agent_trees.py
def test_every_skill_and_settings_is_generated():          # 10 -> 11
    out = load().generate(REPO)
    skills = sorted(p for p in out if p.startswith(".claude/skills/") and p.endswith("/SKILL.md"))
    assert len(skills) == 11, skills
    assert ".claude/skills/x4-toolkit-dev/SKILL.md" in skills

MOVED_HEADINGS = ("A Step That Narrows Data MUST Announce It", "A Derived Artifact Must Declare WHEN",
                  "Tools Must Be Trustworthy BEFORE the Modlist", "Bug Handling Is a FUNNEL",
                  "Concurrent Sessions: Isolate the TREE", "Memory and loaded context are LEADS")

@pytest.mark.parametrize("heading", MOVED_HEADINGS)
def test_maintainer_section_lives_in_exactly_one_place(heading):
    out = load().generate(REPO)
    skill = out[".claude/skills/x4-toolkit-dev/SKILL.md"]
    assert heading in skill, f"{heading!r} missing from the x4-toolkit-dev skill (relocated, never deleted)"
    assert heading not in out["CLAUDE.md"] and heading not in out["AGENTS.md"], f"{heading!r} still in an entry file"

def test_entry_files_point_to_the_dev_skill_and_x4_notes():
    out = load().generate(REPO)
    for f in ("CLAUDE.md",):            # AGENTS.md joins in Task 6
        assert "x4-toolkit-dev" in out[f] and "X4-NOTES.md" in out[f]

def test_the_generator_never_owns_x4_notes():
    g = load()
    assert not any("X4-NOTES" in p for p in g.OWNED) and not any("X4-NOTES" in p for p in g.generate(REPO))
```

```python
# test_reference_fingerprint.py: the freshness cell moved with its section
doc = REPO / ".claude" / "skills" / "x4-toolkit-dev" / "SKILL.md"
if not doc.is_file():
    pytest.skip("no x4-toolkit-dev skill beside the toolkit (not the shipped layout)")
# ... unchanged roster logic, plus:
assert "_freshness.ENGINE_SOURCES" not in (REPO / "CLAUDE.md").read_text(encoding="utf-8"), \
    "the freshness cell must live in ONE place; a second copy in CLAUDE.md would rot unchecked"
```

```python
# test_build_scripts_check_their_stamp.py: keep the moved rebuild line in the population
for skill_md in sorted((repo / "agent" / "skills").glob("*/SKILL.md")):
    candidates.append(skill_md)
```

Run: `uv run --frozen python -m pytest -q tests/test_gen_agent_trees.py tests/test_reference_fingerprint.py tests/test_build_scripts_check_their_stamp.py`. Expected: the new tests FAIL (no skill yet). `test_build_scripts...` still passes, because candidates grew and offenders stayed 0.

- [ ] **Step 2: Create the skill.** Frontmatter: `name: x4-toolkit-dev`, plus a `description:` under 1,024 chars and no `allowed-tools`. The description reads: "Use when working ON the X4 toolkit itself: editing tools/, gates/, scripts/, hooks or the agent/ source, regenerating agent trees, running the suite, building or trusting a derived artifact (effective store, BaseX x4raw/x4eff, x4xref), running concurrent sessions or worktrees, handling a suspected tool bug, or deciding whether tools are trustworthy enough to lock a modlist." The body is the moved sections **verbatim**, demoted one heading level (`##`→`#`, `###`→`##`), followed by `codex.md` sections 2, 4 and 5 verbatim under `# Working in the toolkit repo`.

- [ ] **Step 3: Cut the sections from core.md and insert the stub.** Regenerate.

- [ ] **Step 4: Run the focused tests.** Expected: pass.

- [ ] **Step 5: Relocation proof** (scratch script, kept out of the repo). It splits the OLD `git show HEAD:agent/instructions/core.md` and `HEAD:agent/instructions/codex.md` into paragraphs on blank lines, normalising whitespace and heading markers. It then asserts that every paragraph appears in the union of the NEW core.md, claude.md, codex.md and the skill, except an explicit list of rewritten paragraphs (the stub replaces nothing old; the list should be EMPTY for this task). It prints `N of M paragraphs found verbatim` and exits 1 on any miss.
  Expected: `M of M`, exit 0. Control: delete one moved paragraph from the skill in a scratch copy and re-run. Expected: exit 1 naming it.

- [ ] **Step 6: Budget.** Run `uv run python gates/claude_md_budget.py`. Expected: PASS, shipped size ≈ 28–29 K chars. Then `uv run python gates/claude_md_budget.py --record`. Expected: prints `shipped (repo root): floor 39971 -> <new>` and locks the smaller size in. The baseline is local and gitignored, so nothing is committed from it. **Paste the floor line in the commit message.**

Commit: `agent: relocate maintainer guidance from core to the x4-toolkit-dev skill (verbatim, N of N paragraphs); core <bytes>`

Confidence **85%**. The risk is an unlisted test or gate that reads one of the moved paragraphs from CLAUDE.md. Five readers were MEASURED by grep of `CLAUDE.md` path literals, but a reader that builds the path differently would be missed. The focused run catches what it touches, and the lane-end full suite catches the rest.

---

## Task 5: Make core agent-neutral, move Claude specifics into `claude.md`, and enforce neutrality

**Files:** `agent/instructions/core.md`, `agent/instructions/claude.md`, `tools/x4validate/scripts/gen-agent-trees.py`, `tools/x4validate/tests/test_gen_agent_trees.py`. Generated: `CLAUDE.md`, `AGENTS.md`.

Rewrites in core (each listed in the commit message):
- Preamble: "Guidance for Claude Code…" becomes "Guidance for the AI coding agent…". "Claude's role" becomes "The agent's role".
- `$CLAUDE_PROJECT_DIR` becomes `{{PROJECT_DIR}}`.
- `## Safety Rules (enforced by hooks in .claude/settings.json)` becomes `## Safety Rules`, followed by the `{{AGENT_ADDENDUM}}` marker. The marker MOVES here from end of file. It is followed by the neutral rule list (hard blocked / requires confirmation / general).
- "`sed -i` on a game or profile file (use Edit; it backs up)" becomes "(edit through your file-edit tool, which is backed up first)".
- The Glob/Grep rows become neutral: "a file-NAME search (your agent's glob/find tool)" and "a CONTENT search (ripgrep)". The Claude tool names move to the addendum as one line.
- `.claude/x4-paths.env` stays. It is allowlisted, and lane C moves it in phase 7.
- `.claude\backups\known-good-<name>\` stays. It is allowlisted: a toolkit directory that every agent's backup hook writes, not a Claude mechanism.

Moved into `claude.md` (body): the hook wiring sentence, "anchored on `$CLAUDE_PROJECT_DIR`; `.claude\`, `dev\`, `dist\`, `tools\` are the editable workspace", "Guarded: Bash, PowerShell (same rules), Edit, Write, NotebookEdit. A timed-out hook (30 s) does NOT block.", "Existing Edit/Write/NotebookEdit targets get a uniquely named backup first", and "Glob for names, the Grep tool for contents (never `grep -r` via Bash)".

- [ ] **Step 1: Failing tests. There is one falsification twin per banned clause (#26).**

```python
BANNED_SAMPLES = ["$CLAUDE_PROJECT_DIR", "Claude Code", "see CLAUDE.md", "MEMORY.md", "NotebookEdit",
                  "settings.json", ".claude/hooks/x", ".claude\\settings", "use **Glob**", "the **Grep** tool"]

@pytest.mark.parametrize("sample", BANNED_SAMPLES)
def test_TWIN_core_naming_a_claude_only_mechanism_refuses(tmp_path, sample):
    import shutil
    g = load(); shutil.copytree(REPO / "agent", tmp_path / "agent")
    p = tmp_path / "agent/instructions/core.md"
    p.write_bytes(p.read_bytes() + f"\nleak: {sample}\n".encode())
    with pytest.raises(g.GenerationError, match="neutral"):
        g.generate(tmp_path)

@pytest.mark.parametrize("allowed", [".claude\\backups\\known-good-x\\", ".claude/x4-paths.env"])
def test_allowlisted_toolkit_paths_do_not_refuse(tmp_path, allowed):
    import shutil
    g = load(); shutil.copytree(REPO / "agent", tmp_path / "agent")
    p = tmp_path / "agent/instructions/core.md"
    p.write_bytes(p.read_bytes() + f"\nok: {allowed}\n".encode())
    g.generate(tmp_path)              # must not raise

def test_the_committed_core_is_neutral():
    load().check_neutral((REPO / "agent/instructions/core.md").read_bytes().decode("utf-8"))

def test_TWIN_an_empty_addendum_body_refuses(tmp_path):
    import shutil
    g = load(); shutil.copytree(REPO / "agent", tmp_path / "agent")
    (tmp_path / "agent/instructions/claude.md").write_bytes(b"# Title only\n")
    with pytest.raises(g.GenerationError, match="addendum"):
        g.render_entry(tmp_path / "agent", "claude")

def test_claude_md_still_carries_its_hook_facts():
    text = load().generate(REPO)["CLAUDE.md"]
    for must in ("NotebookEdit", "timed-out hook", "CLAUDE_PROJECT_DIR", "env var > `x4-paths.env` > default"):
        assert must in text, must
```

Expected: they FAIL (`check_neutral` missing, and today's core is not neutral). `test_the_committed_core_is_neutral` failing on the CURRENT core is the proof that the gate can go red on real input.

- [ ] **Step 2: Implement** `NEUTRALITY_BANNED`, a tuple of `(regex, reason)`: `CLAUDE_PROJECT_DIR`, `\bClaude\b` (catches "Claude Code" too; one clause), `CLAUDE\.md`, `MEMORY\.md`, `NotebookEdit`, `settings\.json`, `\.claude[/\\]`, `\*\*Glob\*\*`, `\*\*Grep\*\*`. Then `NEUTRALITY_ALLOWED` = `(".claude\\backups\\", ".claude/backups/", ".claude/x4-paths.env")`, each with a comment naming why. Allowed substrings are blanked to equal-length spaces BEFORE matching, so line numbers stay exact. `check_neutral` runs on the core SOURCE inside `generate()` and raises "core is not agent-neutral: line N: <reason>". Make an empty addendum body a refusal.

- [ ] **Step 3: Rewrite core and fill `claude.md`** as listed above. Regenerate.

- [ ] **Step 4:** Run the focused tests, then:
  - `uv run --frozen python -m pytest -q tests/test_config_precedence_agrees.py tests/test_write_verb_promises_are_consistent.py tests/test_routing_coverage.py`
  - `uv run python gates/routing_coverage.py`

  Expected: pass. The routing gate reports every CLI routed on the shipped CLAUDE.md.

- [ ] **Step 5: Relocation proof again** (the Task 4 script, OLD = the Task 4 commit). Expected: every paragraph found, except the rewritten ones, which are listed by hand. **Each listed paragraph's Claude-specific facts must appear in `claude.md`.**

Commit: `agent: core is agent-neutral (generator refuses Claude-only names); Claude hook facts move to the claude addendum`

Confidence **80%**. The judgement calls are the wording, and whether a banned regex false-positives on legitimate prose. `\bClaude\b` will hit any future sentence about Claude. That hit is intended, and the remedy is the addendum. Twins cover every clause. Raise it by running `check_neutral` over all 10 skills as an INFO count (not gated) to see how many hits real prose produces. MEASURED today: 3 skill lines name `CLAUDE.md`/`.claude\`.

---

## Task 6: AGENTS.md = core + Codex addendum (retire the stopgap)

**Files:** `agent/instructions/codex.md` (rewrite), `tools/x4validate/scripts/gen-agent-trees.py` (`render_agents_md` → `render_entry(src, "codex")` + the byte refusal, with the section list), `tools/x4validate/tests/test_gen_agent_trees.py`, `tools/x4validate/gates/routing_coverage.py` (+ `tests/test_routing_coverage.py`), `tools/x4validate/tests/test_config_precedence_agrees.py`. Generated: `AGENTS.md`.

`codex.md` draft (≤ ~2.4 KB; line 1 is the title):

```
# AGENTS.md — X4 Foundations Modding (X4 AI Assistant Toolkit)
### How the safety rules reach you (Codex and other agents)
Under Claude Code these rules are enforced by tested hooks. **Under Codex they may not be:
Codex hooks fail OPEN** (measured, Codex 0.159.2): if a hook crashes, times out or was never
reviewed by the user, Codex runs the command anyway, and unreviewed or changed hooks are
skipped silently. Other agents have no hooks here at all. So keep every rule below by your
own discipline, and ask the guards before anything that writes or deletes:

    python .claude/hooks/x4guard.py check --kind shell --shell powershell --command "<cmd>"
    python .claude/hooks/x4guard.py check --kind write --path "<file>"
    python .claude/hooks/x4guard.py check --kind delete --path "<file>"

On Windows Codex runs shell commands in **PowerShell**: pass `--shell powershell` (judged as
bash, a PowerShell write into `reference\` was measured to pass), and write the toolkit root
as `$env:X4_TOOLKIT` where a skill says `$X4_TOOLKIT`. Treat `deny` and `ask` as a stop and
ask the user; treat `inert: true` as "nothing was checked", never a pass.
Skills live in `.agents/skills/<name>/SKILL.md`; open the one this file names before the task.
Never `git add -A` / `git add .`: stage explicit paths.
```

(The x4doctor line is reserved for lane C. The OS deny-delete line is reserved for lane D. Together they get a budget of ~400 B; see *Cross-lane*.)

- [ ] **Step 1: Failing tests.**

```python
def test_agents_md_is_core_plus_codex_addendum_within_the_byte_limit():
    out = load().generate(REPO)
    a, c = out["AGENTS.md"], out["CLAUDE.md"]
    assert a.startswith("# AGENTS.md") and "<!-- GENERATED from agent/ -->" in a
    assert len(a.encode("utf-8")) <= 32768
    # the shared core reaches both: the routing table and the evidence rules are in each
    for must in ("Route BEFORE you search", "Label the evidence tier", "x4-toolkit-dev", "X4-NOTES.md"):
        assert must in a and must in c, must

def test_agents_md_carries_what_codex_cannot_get_from_hooks():   # replaces the stopgap pin
    text = load().generate(REPO)["AGENTS.md"]
    for must in ("fail OPEN", "x4guard.py check", "--shell powershell", "inert: true", "reference",
                 ".agents/skills", "git add -A", "$env:X4_TOOLKIT"):
        assert must in text, must
    for banned in ("NotebookEdit", "CLAUDE_PROJECT_DIR", "timed-out hook (30 s)"):
        assert banned not in text, banned            # Claude facts must not leak into AGENTS.md

def test_TWIN_an_oversized_agents_md_refuses(tmp_path):          # updated: grow the CORE now
    import shutil
    g = load(); shutil.copytree(REPO / "agent", tmp_path / "agent")
    p = tmp_path / "agent/instructions/core.md"
    p.write_bytes(p.read_bytes() + b"filler line for the size limit\n" * 200)   # +6.2 KB
    with pytest.raises(g.GenerationError, match="silently drops"):
        g.generate(tmp_path)

def test_agents_md_limit_is_BYTES_not_chars(tmp_path):
    # twin: under 32,768 chars but over 32,768 bytes must refuse
    import shutil
    g = load(); shutil.copytree(REPO / "agent", tmp_path / "agent")
    cur = g.render_entry(tmp_path / "agent", "codex")
    room_chars = 32768 - len(cur) - 10
    p = tmp_path / "agent/instructions/codex.md"
    p.write_bytes(p.read_bytes() + ("\u2605" * room_chars).encode())
    with pytest.raises(g.GenerationError, match="silently drops"):
        g.generate(tmp_path)

def test_every_x4guard_line_in_agents_md_parses_and_answers():
    """The addendum quotes command lines; if lane E changes the flags, this goes red."""
    import json, shlex, subprocess, sys
    text = load().generate(REPO)["AGENTS.md"]
    lines = [l.strip() for l in text.splitlines() if "x4guard.py check" in l and l.strip().startswith("python ")]
    assert len(lines) >= 3, lines
    for l in lines:
        argv = shlex.split(l.replace('"<cmd>"', '"echo hi"').replace('"<file>"', '"dev/probe/x.xml"'))[1:]
        r = subprocess.run([sys.executable, str(REPO / argv[0]), *argv[1:]], capture_output=True, text=True, timeout=120)
        assert json.loads(r.stdout)["decision"] in {"allow", "advise", "ask", "deny"}, (l, r.stdout, r.stderr)
```

`routing_coverage.claude_md_paths()` gains `("shipped AGENTS.md", REPO_ROOT / "AGENTS.md")`. Its test gets a twin: an AGENTS.md whose table lacks a CLI → `missing()` names it. `test_config_precedence_agrees` asserts the phrase in BOTH files.

Expected: the new tests FAIL (AGENTS.md is still the stopgap).

- [ ] **Step 2: Implement.** `render_agents_md` = `render_entry(src, "codex")` plus a byte check that refuses with "AGENTS.md would be N bytes; Codex silently drops text past 32768" followed by the 5 largest sections. Below `AGENTS_MD_WARN_HEADROOM` it prints an advisory line naming the headroom, and it never refuses on that. Remove the STOPGAP docstring. Rewrite `codex.md`. Delete the stopgap's section 1 ("read CLAUDE.md in full"): it is now false, because the core is IN the file. Regenerate.

- [ ] **Step 3:** `uv run --frozen python -m pytest -q tests/test_gen_agent_trees.py tests/test_routing_coverage.py tests/test_config_precedence_agrees.py && uv run python gates/routing_coverage.py`. Expected: pass. The gate prints two rows (`shipped (repo root)`, `shipped AGENTS.md`) and every CLI is routed in both.

- [ ] **Step 4: Report the real sizes.** `uv run python scripts/gen-agent-trees.py --check`. Expected: rc 0, with the size report printing CLAUDE.md ≈ 30 K/40,000 chars and AGENTS.md ≤ 30,720/32,768 bytes (≥ 2 KiB headroom, per Task 1's rule). If headroom is below 2,048, STOP. Task 1's decision was wrong; re-run it.

Commit: `AGENTS.md: generated from the shared core + Codex addendum (<bytes>/32768); stopgap retired; routing gate covers AGENTS.md`

Confidence **85%**. Headroom depends on Task 1's option. The x4guard test needs bash for the guards, but an inert-deny JSON still satisfies it, so it is environment-robust.

---

## Task 7: The same skill sources reach Codex and generic agents as `.agents/skills/`

**Files:** `tools/x4validate/scripts/gen-agent-trees.py` (`render_skills(src, agent)`, `OWNED += (".agents/skills/",)`), `tools/x4validate/tests/test_gen_agent_trees.py`, `tools/x4validate/tests/test_cli_reference.py`, `.gitignore`, `tools/x4validate/scripts/gen-cli-reference.py` (line 182: "CLAUDE.md's routing table" → "the routing table in CLAUDE.md / AGENTS.md"), `agent/skills/x4-cli-reference/SKILL.md` (regenerated by gen-cli-reference), `agent/skills/x4-mod-interaction/SKILL.md:62` ("per the CLAUDE.md API-first rule" → "per the Nexus API-first rule in your project instructions"). Generated: `.agents/skills/**` (11 skills, 11 reference files), `.claude/skills/**` (the two changed skills only).

Depends on **Task 2 M-A1** and **user Q2** (token rendering).

- [ ] **Step 1: Failing tests.**

```python
def test_codex_skills_mirror_the_claude_skills_one_to_one():
    out = load().generate(REPO)
    cl = sorted(p[len(".claude/skills/"):] for p in out if p.startswith(".claude/skills/"))
    cx = sorted(p[len(".agents/skills/"):] for p in out if p.startswith(".agents/skills/"))
    assert cl == cx and len(cx) >= 22          # 11 SKILL.md + 11 cli reference files (MEASURED 2026-10-02: 10+11 before x4-toolkit-dev)

def test_codex_skills_render_the_toolkit_token_for_codex():
    out = load().generate(REPO)
    cx = {p: t for p, t in out.items() if p.startswith(".agents/skills/")}
    assert not any("CLAUDE_PROJECT_DIR" in t for t in cx.values())
    assert sum("$X4_TOOLKIT/tools/x4validate" in t for t in cx.values()) == 7    # 7 skills carry the token (MEASURED)

def test_claude_skills_are_unchanged_by_the_codex_target():
    # the claude rendering keeps $CLAUDE_PROJECT_DIR until phase 7 (spec section 4)
    out = load().generate(REPO)
    assert sum("$CLAUDE_PROJECT_DIR/tools/x4validate" in t for p, t in out.items()
               if p.startswith(".claude/skills/")) == 7

def test_TWIN_a_stray_codex_skill_is_a_GHOST(fresh_copy):
    g, exp, root = fresh_copy
    (root / ".agents/skills/stray").mkdir(parents=True); (root / ".agents/skills/stray/SKILL.md").write_bytes(b"x\n")
    assert g.problems(exp, root) == ["GHOST    .agents/skills/stray/SKILL.md"]
```

In `test_cli_reference.test_every_generated_file_is_COMMITTABLE`, add `f".agents/skills/x4-cli-reference/{rel}"` to the per-file tuple. **This test FAILS today**: MEASURED, `git check-ignore` matches `.gitignore:33:reference/`.

Expected: all of the above FAIL.

- [ ] **Step 2: Implement.** Parameterise `render_skills(src, agent)` with the skills dir and the `{{TOOLKIT}}` value from `TARGETS`. The Claude output must be byte-identical to before; `test_committed_trees_are_fresh` proves it. Frontmatter passes through verbatim, including `allowed-tools`. Codex ignores unknown keys, MEASURED on 0.154 and re-measured on 0.159.2 by M-A1. Add `!.agents/skills/*/reference/` to `.gitignore` beside the two existing re-includes, with a one-line comment. Apply the 2 text fixes and run `uv run python scripts/gen-cli-reference.py`, then `gen-agent-trees.py`.

- [ ] **Step 3:**
  - `uv run --frozen python -m pytest -q tests/test_gen_agent_trees.py tests/test_cli_reference.py`. Expected: pass.
  - `git check-ignore -q --no-index .agents/skills/x4-cli-reference/reference/x4save.md; echo rc=$?`. Expected: `rc=1`.
  - `git status --porcelain .agents | wc -l`. Expected: 22 untracked files, all staged explicitly by path.

Commit: `gen-agent-trees: render agent/skills to .agents/skills for Codex and generic agents; re-include their reference/ (was gitignored)`

Confidence **75%**. It rests on M-A1 confirming discovery on 0.159.2, and on Q2. If M-A1 fails, the files still ship for generic agents and OpenCode, and the addendum's "Skills live in `.agents/skills/<name>/SKILL.md`" sentence still lets Codex open one by path. The remaining 25% is whether Codex's model reliably picks a skill up from the description. Lane B's live E2E is what raises it.

---

## Task 8 (optional, low value): Repoint three prose pointers

`tools/x4validate/gates/obtainability_audit.py:176` and `tools/x4validate/tests/test_shell_scripts_never_reassign_tmp.py:90` both cite "CLAUDE.md 'a step that narrows data'". Change those to "the x4-toolkit-dev skill". These are comment-only edits. `scripts/x4lock.py:263` is **left** to lane C/D, which edit x4lock (F9), to avoid a merge conflict. `BLIND-SPOTS.md` is append-only history and is left as is. MEASURED with one regex shape: 5 hits, 2 of them in BLIND-SPOTS. A differently phrased pointer would be missed, so this is a lead, not a census.

Commit: `comments: point narrowing-data citations at the x4-toolkit-dev skill`. Confidence 95%.

---

## Files touched (union)

```
agent/instructions/core.md
agent/instructions/claude.md
agent/instructions/codex.md
agent/README.md
agent/skills/x4-toolkit-dev/SKILL.md                      (new)
agent/skills/x4-mod-interaction/SKILL.md
agent/skills/x4-cli-reference/SKILL.md                    (regenerated by gen-cli-reference.py)
tools/x4validate/scripts/gen-agent-trees.py
tools/x4validate/scripts/gen-cli-reference.py
tools/x4validate/gates/routing_coverage.py
tools/x4validate/tests/test_gen_agent_trees.py
tools/x4validate/tests/test_reference_fingerprint.py
tools/x4validate/tests/test_build_scripts_check_their_stamp.py
tools/x4validate/tests/test_config_precedence_agrees.py
tools/x4validate/tests/test_routing_coverage.py
tools/x4validate/tests/test_cli_reference.py
tools/x4validate/gates/obtainability_audit.py              (Task 8, comment only)
tools/x4validate/tests/test_shell_scripts_never_reassign_tmp.py  (Task 8, comment only)
.gitignore
docs/superpowers/measurements/2026-10-0X-agents-md-and-skills.md   (new)
GENERATED: CLAUDE.md, AGENTS.md, .claude/skills/x4-toolkit-dev/SKILL.md,
           .claude/skills/x4-cli-reference/SKILL.md, .claude/skills/x4-mod-interaction/SKILL.md,
           .agents/skills/** (new, 22 files)
```

## Cross-lane dependencies

- **B (Codex adapter):** both lanes edit `gen-agent-trees.py` (`OWNED`, `generate()`, `TARGETS`). **Proposed order: lane A's Tasks 3, 6 and 7 land first.** B then adds `.codex/hooks.json`, `.codex/rules/`, `.codex/agents/*.toml` and `entry.sh` rendering on top of the `TARGETS` table, which reduces conflicts to appends. A needs nothing from B to start. B's live E2E should add two assertions: AGENTS.md's last-line sentinel is seen, and one `.agents/skills` skill fires. That raises Task 7 above 90%. If B changes the `x4guard.py` invocation path (e.g. to `agent/guards/...` or `.codex/`), it must edit `codex.md`. `test_every_x4guard_line_in_agents_md_parses_and_answers` goes red until it does.
- **C (installers / x4doctor):**
  - Copy `AGENTS.md` and `.agents/` (F8). Add `AGENTS.md` to the x4lock manifest (F9).
  - **Never create or overwrite `X4-NOTES.md`.**
  - Migrate a personalised `CLAUDE.md` to `X4-NOTES.pre-4.0.md`. The core now tells every agent to read `X4-NOTES.md`.
  - Global-install mode must place `.agents/skills/` as well.
  - The new `x4-toolkit-dev` skill ships to every global install. Its description scopes it to toolkit work.
  - Add the "run x4doctor at session start" line to `codex.md`, budget ≤ 200 B.
  - When `x4-paths.env` moves to the toolkit root (phase 7), update core's two mentions and the `NEUTRALITY_ALLOWED` entry `.claude/x4-paths.env`, and keep the pinned phrase ``env var > `x4-paths.env` > default``.
  - `deploy-claude-dir.py` (or its successor) must deploy `AGENTS.md` and `.agents/` to an install.
- **D (Layer 2 OS protection):** once the deny-delete is live, add one line to `codex.md` ("deletes in `reference\` are blocked by the OS"), budget ≤ 200 B. Until then the addendum must NOT claim it.
- **E (x4guard hardening):** keep the three quoted `x4guard.py check` command forms valid, or update `codex.md` in the same commit. A's test pins them.
- **What A gives everyone:** `TARGETS` and `render_entry()`, plus the size report printed on every generator run. **Any lane adding text to `core.md` or `codex.md` must keep AGENTS.md ≤ 32,768 bytes.** The generator refuses otherwise, so a lane that overruns finds out at regeneration, not in a Codex session.

## Questions for the user

1. **Move the ~1.9 KB of maintainer routing rows (Python-internal `_scan`/`_registry`/`_effective` helpers and `gates/mutation_probe.py`) into the `x4-toolkit-dev` skill as well?** The spec moves only the five sections, which (MEASURED + projected) leaves AGENTS.md about 1.3 KB under Codex's cap. That is not enough for lanes C and D's lines plus one ordinary edit. **Recommended: yes.** Those rows tell a toolkit developer which internal helper to call, and a player or modder never calls them. The CLI rows, including `x4effective dump --chain`, stay. Task 1 confirms the numbers before you decide.
2. **How should skills write the toolkit root for Codex?** MEASURED: in PowerShell, `$X4_TOOLKIT` is EMPTY. Only `$env:X4_TOOLKIT` works, and Codex on Windows runs PowerShell. (a) Render `$X4_TOOLKIT`, as spec section 4 says, and have AGENTS.md tell Codex to write `$env:X4_TOOLKIT` in PowerShell. Bash agents work unchanged, and a miss fails loudly (`cd /tools/...`). (b) Render `$env:X4_TOOLKIT`, which is right for Windows Codex but breaks bash agents and Linux/macOS Codex (M9). **Recommended: (a)**. Revisit if lane B's E2E shows Codex ignoring the hint.

(Not asked, because the spec already decided them: the relocation itself, the skill's name, X4-NOTES.md, and that everything ships public.)

## Confidence summary

| Task | Confidence | What would raise a sub-90 task |
|---|---|---|
| 1 measure split | 95% | — |
| 2 Codex/Claude load measurements | 85% | the runs themselves; two repeats + control each |
| 3 marker assembly, char refusal | 90% | — |
| 4 relocation to x4-toolkit-dev | 85% | a census of every test/gate that reads CLAUDE.md by any path construction (grep for `"CLAUDE"` fragments, `glob("*.md")` over the repo root) before cutting |
| 5 neutral core + gate | 80% | run `check_neutral` over all skills as INFO and classify every hit by hand |
| 6 AGENTS.md assembly | 85% | Task 1 option B confirmed ≥ 2 KiB headroom; M-A2 boundary confirmed at 32,768 |
| 7 `.agents/skills` | 75% | M-A1 on 0.159.2 + lane B's live E2E with one skill firing |
| 8 pointers | 95% | — |

## Gate plan

- **Per task (focused only):** the pytest files named in each task's steps, plus `uv run python scripts/gen-agent-trees.py --check` (rc 0) after every regeneration. Task 4 also runs `gates/claude_md_budget.py` (then `--record`). Tasks 5 and 6 also run `gates/routing_coverage.py`. Task 7 also runs `git check-ignore` (rc 1).
- **Lane end (once):**
  - full `uv run --frozen python -m pytest -q -rs`, backgrounded (~30 min under load; #25);
  - `gates/claude_md_budget.py`;
  - `gates/routing_coverage.py`;
  - `scripts/scan-identifiers.py`;
  - `gen-agent-trees.py --check`;
  - `gen-cli-reference.py --check`, or its test;
  - `bash scripts/test-hooks.sh` (hooks are untouched, so this must be unchanged; it proves the generator did not move a byte);
  - a **cold clone** (`git clone` into scratch, then `test_gen_agent_trees.py` + `test_cli_reference.py`). This is the only check that catches a gitignored generated file (the 2026-09-13 class). Expected: pass with 0 MISSING.
- **Never run while** `gates/mutation_probe.py` is running (#27).


## Amendments -- 2026-10-02 (user decisions; binding, supersede the text above)

Read DECISIONS.md in this folder first. Changes to THIS lane:
- **#2 changed:** skills keep the token form in the generated Codex tree; do NOT hardcode `$env:X4_TOOLKIT`. Agree the token with lanes B and C; the installer renders it per OS (install.ps1 -> `$env:X4_TOOLKIT`, install.sh -> `$X4_TOOLKIT`). Keep the AGENTS.md line telling Codex on Windows to use `$env:X4_TOOLKIT` for the in-repo copy.
- **#13:** the game-root AGENTS.md is regenerated from this lane's output (today it points at the archived Desktop tools\x4validate).
- **#15:** nothing here may assume Windows; any path/shell example in the shared core needs a POSIX form too.
- **Measured 2026-10-02 (measure-A.md):**
  - **Claude Code DOES read AGENTS.md** (5/5, no tool call) -- but only when there is no CLAUDE.md; with both, only CLAUDE.md (2/2). Task 2's STOP trigger fired literally, but its reason (double-load) does not apply in our layout. **Ruling (orchestrator):** continue. The Codex addendum is headed so a non-Codex reader is not misled ('Codex only -- skip if you are another agent'), and lane C writes CLAUDE.md whenever the Claude target is installed (--agent all|claude). An --agent codex-only install with a Claude user in it gets core + a labelled Codex section: accepted, disclosed in the README.
  - **Option B is REQUIRED, not optional:** headroom option A +2,053 B (clears the 2,048 rule by 5 bytes; lanes C/D's ~400 B would break it) vs option B +3,971 B. DECISIONS #1 already approves the row move.
  - **Do NOT copy the plan's split_sizes.py verbatim:** it silently dropped the last section's removal (headroom read -1,594 B). Use the measure-A version with its conservation check.
  - Codex is **0.160.0**; `.agents/skills` discovery works there (incl. unknown `allowed-tools`, launch from a subdirectory).
  - AGENTS.md cap cuts at exactly **32,768 bytes** (2/2); **root + nested AGENTS.md share one budget** (2/2) -> add a test that the repo ships no second AGENTS.md, and tell lane C (install note).
  - `codex exec` needs `</dev/null` (else it hangs on stdin) and `--skip-git-repo-check` outside git.
  - Unmeasured: skill-description length limit; bytes vs chars on non-ASCII (tests were ASCII).

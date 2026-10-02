# Universal Agent Support — Plan 2, Lane C: installers, x4lock, x4doctor

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Test-first: every task's test
> must be watched FAILING before the implementation lands.

**Goal.** Close framework-audit F8 and F9, and ship `x4doctor`, the read-only health command from
spec §5.8. Both installers learn which agent target they are installing (`--agent`). They ship that
target's instruction file and trees, and never overwrite an `AGENTS.md` the toolkit did not write.
x4lock protects `AGENTS.md` and the Codex tree without reporting a Claude-only root as damaged.
`x4doctor` reports, for each agent target present, whether its guards are live. It covers deployed-vs-source
parity, a guard self-test with controls that must deny and must allow, the roots the guards actually
resolve, the toolchain the guards actually run (bash, python, jq), Codex trust and review state,
and `X4_GUARD`. **It never prints OK when it checked nothing.**

**Repo:** `$X4_TOOLKIT` = `$X4_TOOLKIT`, branch `master` (spec v2).
`PKG` = `tools/x4validate`. Tests: `cd tools/x4validate && uv run --frozen python -m pytest -q -rs <file>`.

## Context (what was measured while planning, 2026-10-02)

| Fact | Tier |
|---|---|
| `X4_COPY_ITEMS` (install.sh:503) and `$X4CopyItems` (install.ps1:314) are equal and contain `CLAUDE.md` and `.claude` but neither `AGENTS.md` nor `agent`. | READ |
| **0 of 23** tagged releases' `install.sh` (v1.0 … v3.3.1) names `AGENTS.md`; `AGENTS.md` was first added at `367cf2e` (2026-10-01), after v3.3.1. **So no AGENTS.md in any user's destination was written by this toolkit**: any that exists is user content. | MEASURED (`git show <tag>:install.sh \| grep -c AGENTS.md` per tag) |
| The release zip is `git archive`; `.gitattributes` export-ignores only `release/` and `mutate-mod-lua.py`, so the **zip already contains `AGENTS.md` and `agent/`** (45 tracked files). The omission (F8) happens only when an installer COPIES (in-game, or separate into a different dir). | READ |
| The author's game root has a **personal, hand-written `AGENTS.md`** (4,668 B, unlocked, committed in the game-root repo at `cf63b86`/`20079bc`). It points Codex at `<modding-root>\tools\x4validate`, **which was archived on 2026-09-14**, so it is stale. It is not the toolkit's generated file. | MEASURED (`ls`, `head`, `git log`) |
| The current generated `AGENTS.md` is **maintainer-facing** ("edit `agent/`, never the generated files"; "read `CLAUDE.md`"). Shipping it into a player's game root would give wrong guidance. CHANGELOG Unreleased: "the installers do not ship it yet". | READ |
| `x4lock._candidates()` puts every `_GAME_RELATIVE` entry into `missing()` unconditionally. Adding `AGENTS.md` there would report **MISSING** on every Claude-only game root and every v3.x install. `_GAME_GLOBS` entries are lock-if-present. | READ (x4lock.py:101-107, 249-251, 302-307) |
| `deploy_parity.py` and `deploy-claude-dir.py` cover `.claude/` only (`TOP_FILES` + `SUBTREES`). No script deploys or compares the root `CLAUDE.md`/`AGENTS.md`. | READ |
| Deployed `x4guard check` controls on this machine all behaved as expected, with `inert:false`. **Deny:** write, delete and pwsh `Set-Content` to a NON-EXISTENT `reference/__x4doctor_probe__.xml`, a write to the existing `reference/libraries/wares.xml`, and `rm -rf '<reference>'` as bash. **Allow:** `echo x4doctor` as bash. | MEASURED (check-only; nothing executed) |
| Sourcing `agent/guards/claude-hooks/_x4-env.sh` under Git Bash and calling `x4_python` returns the guards' own interpreter choice (`py` here). It also exposes `$X4_REFERENCE` and the config file it read (`$_x4_cfg`). | MEASURED |
| Three bash resolvers exist and disagree in shape. `scripts/gitbash.py::find_bash` checks Git install dirs first and skips the `system32`/`syswow64`/`windowsapps` stubs. `x4guard.resolve_bash` uses `X4_BASH`, then PATH `bash.exe`/`bash`, and rejects only `system32`. Each hook is started by whatever bash the agent host runs. | READ |
| `setup.sh` checks python with `command -v python/python3/py` only. It ignores `X4_PYTHON` and never executes the interpreter. The hooks' `x4_resolve_python` honours `X4_PYTHON` and refuses to fall back. A Store-stub `python` passes setup and fails at runtime. | READ (setup.sh:45-47, _x4-env.sh:337-347) |
| Python `_paths._find_env_file` finds `x4-paths.env` via `$X4_TOOLKIT`, else by walking up from CWD. The hooks use `$X4_CONFIG`, else `$X4_TOOLKIT/.claude/x4-paths.env`, with `X4_TOOLKIT` defaulting to `$CLAUDE_PROJECT_DIR` or the hook dir's `../..`. **With `X4_TOOLKIT` unset, the two can read different files.** | READ |
| `~/.codex/config.toml` keys projects by a **lower-cased** absolute path (`[projects.'c:\program files (x86)\steam\...']`, `trust_level = "trusted"`). `[hooks.state]` is currently empty on this machine. | MEASURED |
| No guard reads `X4_GUARD` yet (0 hits in `agent/guards/claude-hooks/*.sh`). Spec §5.7's escape hatch is unimplemented. | MEASURED (grep) |
| A new `[project.scripts]` entry makes `gates/routing_coverage.py` demand a CLAUDE.md routing row. CLAUDE.md has about 29 characters of headroom. | READ |
| ⚠ The toolkit `master` working tree is **dirty**: 18 modified files plus 1 untracked, apparently another session's F2/F3/F4 work. That includes `CHANGELOG.md` and `agent/instructions/core.md`. | MEASURED (`git status`) |

## Global constraints

- **Own worktree:** `git worktree add ../x4-toolkit-laneC -b session/laneC` (CLAUDE.md Concurrent
  Sessions #1). The master tree is dirty with another session's WIP (above), so never work in it.
- Never edit generated files (`CLAUDE.md`, `AGENTS.md`, `.claude/**` generated parts). This lane does
  not need to: it touches installers, `scripts/`, one gate, and tests.
- `install.sh` and `install.ps1` change **in the same commit, every time**. `test_installers_agree.py` parses
  both, and any per-agent list must be parsed from both files too, never restated in the test.
- `scripts/x4doctor.py` is **stdlib-only and must run on Python 3.10**. That matches x4lock, and it means a
  broken `uv`/venv cannot take down the tool that diagnoses it. TOML needs `tomllib` (3.11+). On 3.10
  the Codex rows report **UNKNOWN ("needs Python ≥ 3.11 to read config.toml")**, never OK.
- **ABSENCE vs NON-ANSWER, structurally.** Every doctor check returns one of `OK`, `FAIL`, `UNKNOWN`,
  or `N/A` (with a reason). `N/A` is only "this target is not installed here". A run where no check
  answered `OK`/`FAIL` exits non-zero. A check that raises becomes `UNKNOWN` with the exception named,
  never a skipped row.
- **Doctor is read-only and executes nothing it judges.** Guard self-tests go through `x4guard.py check`,
  which is side-effect-free (`test_check_has_no_side_effects`). Doctor writes no file, sets no attribute,
  and never touches `~/.codex/config.toml`.
- Installers: **never overwrite a user-owned `AGENTS.md`.** The proof that every existing one is
  user-owned is the 0-of-23 measurement above. `--dry-run` writes nothing (existing contract and tests).
- Stage explicit paths, one commit per task, on `session/laneC`. Merge to master only after the lane gate.
  Never push.

## Interfaces

**Produces (for other lanes and the release):**

- `install.sh --agent claude|codex|generic|all` and `install.ps1 -Agent …`. `opencode` is refused
  with "not yet supported (spec M8)". The default is per **Q2**. Per-agent copy sets are named once in each file:
  - `X4_AGENT_ITEMS_claude=".claude CLAUDE.md"`
  - `X4_AGENT_ITEMS_codex="AGENTS.md .codex .agents"`
  - `X4_AGENT_ITEMS_generic="AGENTS.md .agents"`
  - ps1 mirrors them as `$X4AgentItems = @{ claude=@(...); codex=@(...); generic=@(...) }`.

  `X4_COPY_ITEMS` drops `.claude` and `CLAUDE.md` into the claude set; everything else stays common.
  `agent/` is in **no** set (per **Q1**).
- The installers' AGENTS.md rule: if `<dest>/AGENTS.md` exists and is byte-different from the source's,
  move it aside to `<dest>/AGENTS.pre-4.0.md` (or `.pre-4.0.<stamp>.md` if that exists), print one line
  naming it, then copy. Dry-run reports it without moving anything.
- `x4lock`: `AGENTS.md`, `.codex/hooks.json` and `.codex/rules/*.rules` are lock-if-present. A
  **target-conditional expectation**: when `<game>/.codex/` exists, `AGENTS.md` and
  `.codex/hooks.json` are DEMANDED (reported MISSING if absent).
- `gates/deploy_parity.py`: a `TargetSpec(name, root_rel, top_files, subtrees, rewrite_scope)` and
  `TARGETS: dict[str, TargetSpec]`, with `"claude"` defined here, preserving today's behaviour byte for byte.
  `population(root, spec)` and `compare_trees(src, dst, spec)` keep their current call shape for
  claude through defaults, so `deploy-claude-dir.py` is unchanged.
- `scripts/x4doctor.py [--root DIR] [--json] [--agent NAME]`. Exit codes:
  - 0: every applicable check is OK and at least one check answered.
  - 1: any FAIL.
  - 3: no FAIL, but at least one UNKNOWN. This mirrors x4validate's degraded exit 3 (`_cli.py:162`).
  - 2: could not run. That covers no agent target found at `--root`, zero checks answered, or a usage error.

  JSON shape: `{"v":1,"root":…,"targets":{"claude":"present|absent",…},"checks":[{"id","target","status","detail"}],"summary":…}`.

**Consumes:**

- From **Lane B (Codex adapter):**
  - the generated tree layout: `.codex/hooks.json`, `.codex/rules/x4.rules`, `.agents/skills/` and whatever `.codex/agents/` holds;
  - its `TargetSpec` entry for `"codex"`;
  - where the Codex hook entry script lives at RUNTIME (see Cross-lane);
  - the M11 result: `trusted_hash` scheme, or a pinnable per-definition hash.
- From **Lane A (instruction split):** a game-root-appropriate generated `AGENTS.md` (core + codex
  addendum) to replace the maintainer stopgap, plus the one-line "run `x4doctor` at session start" in
  the codex addendum, and a routing-table row for `x4doctor` once headroom exists.
- From **Lane D (Layer 2):** a read-only query `x4lock.deny_delete_state(path) -> "present"|"absent"|"unknown"`
  (or equivalent), so doctor reports the `reference\` deny entry without reimplementing icacls parsing.
- From **Lane E (x4guard hardening):** a stable `x4guard check` contract. Doctor relies on `decision`,
  `inert`, `guards`, and exit 0/2. If E adds `--agent`, doctor passes it. If E implements the `X4_GUARD`
  hatch, doctor reads the same variable.

---

## Task 0: Measurements this lane builds on (no code)

**Files:** none in the repo. Record results in the lane's commit messages and in
`docs/superpowers/measurements/2026-09-30-codex-spike.md` only if Lane B owns that doc's edits (else in
this plan's Execution log section).

- [ ] **M-C1 (with Lane B; may BE spec M11).** Review the frozen `.codex/hooks.json` once in two
  different decoy directories, then read `~/.codex/config.toml`.
  - Record the exact `[hooks.state.'…']` key format: case, separators, path spelling.
  - Record whether `trusted_hash` is identical across the two directories, i.e. whether it covers the definition only.
  - Expected:
    - if the hash is equal across directories, doctor can PIN the expected hash per frozen definition (Task 9 compares to it);
    - if it differs, doctor reports `UNKNOWN (hash scheme unverified, M11)` for the hash and still reports entry presence.
- [ ] **M-C2.** Does Codex honour `CODEX_HOME` for config.toml? Check the Codex docs, then run
  `CODEX_HOME=<tmp> codex --version` and see whether `<tmp>/config.toml` is touched. Expected: yes. If not,
  doctor reads `~/.codex` only, and the docstring says so.
- [ ] **M-C3.** Run the doctor control commands from the planning table against the **in-game layout**
  (deployed `.claude/hooks/x4guard.py`) AND against the toolkit repo's `.claude/hooks/x4guard.py`, with
  `X4_TOOLKIT` set and unset. Expected: identical verdicts. Any difference becomes a doctor FAIL
  condition to design for, not an assumption.
- [ ] **M-C4.** Time 6 sequential `x4guard check` calls on this machine. Expected: under 30 s total.
  If not, doctor runs the controls with bounded parallelism (3 workers) and states the time it took.

Confidence it yields usable answers: 85% (M-C1 needs the user's interactive Codex review; see
Questions). Without M-C1, Task 9's hash row ships as UNKNOWN, which is honest, not a blocker.

---

## Task 1: x4lock protects AGENTS.md and the Codex tree (F9), without false MISSING

**Files:**
- Modify: `scripts/x4lock.py` (add to `_GAME_GLOBS`; add `_TARGET_DEMANDS`; extend `_candidates()`)
- Modify: `tools/x4validate/tests/test_x4lock.py`

**Failing tests first** (append to `test_x4lock.py`; `x4lock` is already loaded at module top):

```python
def _game(tmp_path, monkeypatch):
    game = tmp_path / "game"
    (game / ".claude").mkdir(parents=True)
    (game / "CLAUDE.md").write_text("c\n", encoding="utf-8")
    real = x4lock._cfg
    monkeypatch.setattr(x4lock, "_cfg", lambda n: game if n == "game_root" else real(n))
    return game


def _names(paths):
    return {p.relative_to(p.parents[len(p.parents) - 1]).as_posix() for p in paths}


def test_F9_a_present_AGENTS_md_is_in_the_manifest(tmp_path, monkeypatch):
    game = _game(tmp_path, monkeypatch)
    (game / "AGENTS.md").write_text("a\n", encoding="utf-8")
    assert any(p.name == "AGENTS.md" and p.parent == game for p in x4lock.manifest())


def test_F9_TWIN_a_claude_only_root_does_NOT_report_AGENTS_md_missing(tmp_path, monkeypatch):
    """The trap: _GAME_RELATIVE entries are demanded unconditionally. Every v3.x and
    Claude-only install would read as damaged."""
    game = _game(tmp_path, monkeypatch)
    assert not [p for p in x4lock.missing() if p.parent == game and p.name == "AGENTS.md"]


def test_F9_a_codex_root_DEMANDS_AGENTS_md_and_hooks_json(tmp_path, monkeypatch):
    game = _game(tmp_path, monkeypatch)
    (game / ".codex").mkdir()
    gone = {(p.parent.name, p.name) for p in x4lock.missing()}
    assert ("game", "AGENTS.md") in gone
    assert (".codex", "hooks.json") in gone


def test_F9_codex_rules_and_hooks_are_locked_when_present(tmp_path, monkeypatch):
    game = _game(tmp_path, monkeypatch)
    (game / ".codex" / "rules").mkdir(parents=True)
    (game / ".codex" / "hooks.json").write_text("{}", encoding="utf-8")
    (game / ".codex" / "rules" / "x4.rules").write_text("#", encoding="utf-8")
    got = {(p.parent.name, p.name) for p in x4lock.manifest()}
    assert (".codex", "hooks.json") in got and ("rules", "x4.rules") in got
```

Each test has a twin direction. Test 2 is the twin of tests 1 and 3: present-locked, absent-not-demanded, absent-demanded-when-codex.

**Implementation:**

```python
_GAME_GLOBS = (
    ...existing...,
    "AGENTS.md",                    # lock-if-present: never shipped before 4.0 (0 of 23 releases)
    ".codex/hooks.json",
    ".codex/rules/*.rules",
)

#: Files DEMANDED only when their agent target is installed. The marker is the target's
#: own directory, so a Claude-only root is never reported as missing a Codex file.
_TARGET_DEMANDS = {".codex": ("AGENTS.md", ".codex/hooks.json")}
```

In `_candidates()`, after the glob loop:
`for marker, rels in _TARGET_DEMANDS.items(): if (game / marker).is_dir(): out.extend(game / r for r in rels)`.
`_dedup` already merges the glob and demand hits.

Update the module docstring's manifest description by one sentence. Do NOT add `.agents/skills/**`.
It is regenerable from the toolkit, and the brief and audit both say "do not blanket-lock generated folders".
If the user wants it, it is a one-line glob (see **Q3**).

**Commands:**
- `cd tools/x4validate && uv run --frozen python -m pytest -q -rs tests/test_x4lock.py`
  Expected: the 4 new tests FAIL before the change (test 2 passes before and after, as a guard against the
  naive fix; confirm it FAILS against a mutant that puts `AGENTS.md` in `_GAME_RELATIVE`). After the
  change: all pass, 0 skipped beyond the existing platform skips.
- `python scripts/x4lock.py status` on this machine, read-only. Expected: the game root's personal
  `AGENTS.md` now listed as `unlocked`. **Do not run `lock`**; that is the user's call. Report it.

**Commit:** `x4lock: protect AGENTS.md and the Codex tree when present; demand them only where .codex/ is installed (audit F9)`

**Confidence:** 92%. Measure to raise it: `deploy-claude-dir.py --apply` auto-locks CREATED files that are in
the manifest. Confirm it never creates root files, which is READ: its population is `.claude/` only.

---

## Task 2: `deploy_parity` learns targets (claude unchanged), so doctor and Lane B share one comparer

**Files:**
- Modify: `tools/x4validate/gates/deploy_parity.py`
- Modify: `tools/x4validate/tests/test_deploy_parity.py`

**Failing tests first:**

```python
def test_TARGETS_has_claude_with_todays_population():
    t = parity.TARGETS["claude"]
    assert t.root_rel == ".claude"
    assert t.top_files == ("settings.json", "settings.local.json.example", "x4-paths.env.example")
    assert t.subtrees == ("hooks", "skills", "agents", "commands")
    assert t.rewrite_scope == ("skills/", "agents/")


def test_population_with_an_explicit_spec_reads_only_that_spec(tmp_path):
    spec = parity.TargetSpec("toy", ".toy", ("a.json",), ("sub",), ())
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "sub").mkdir(); (tmp_path / "sub" / "x.md").write_text("x", encoding="utf-8")
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")   # a CLAUDE file: must NOT count
    assert parity.population(tmp_path, spec) == {"a.json", "sub/x.md"}


def test_TWIN_default_population_is_still_claudes(tmp_path):
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    assert parity.population(tmp_path) == {"settings.json"}
```

**Implementation:** add a frozen `TargetSpec` dataclass and `TARGETS = {"claude": TargetSpec("claude",
".claude", TOP_FILES, SUBTREES, REWRITE_SCOPE)}`. Give `population(claude, spec=TARGETS["claude"])`,
`compare_file(..., spec=…)` (it uses `spec.rewrite_scope`) and `compare_trees(..., spec=…)` default
parameters. Keep the module constants as aliases, because `deploy-claude-dir.py` imports
`population`/`in_rewrite_scope`. `main()` is unchanged. Lane B appends `TARGETS["codex"]`. This lane
only provides the slot.

**Commands:**
- `uv run --frozen python -m pytest -q -rs tests/test_deploy_parity.py tests/test_deploy_claude_dir.py`
  Expected: the 2 new tests fail first (AttributeError), then everything passes, with the existing tests unchanged.
- `uv run python gates/deploy_parity.py` Expected: the same verdict and file count as before the change
  (record both numbers in the commit message; PER-ITEM: diff the two outputs, they must be identical).

**Commit:** `deploy_parity: a TargetSpec per agent tree; claude's population unchanged (prep for x4doctor and the Codex tree)`

**Confidence:** 93%.

---

## Task 3: Installers ship per-agent targets (`--agent`), both in agreement (F8)

**Prerequisite:** the user's answers to **Q1** and **Q2**. Lane A must have produced the game-root
`AGENTS.md`, or this task ships the generic/codex set **without** `AGENTS.md` and says so in the
install summary. The current stopgap AGENTS.md is maintainer-facing and must not land in a game root.

**Files:**
- Modify: `install.sh` (the `X4_COPY_ITEMS` split, `X4_AGENT_ITEMS_*`, `--agent` parsing and usage text,
  the copy loop, the dry-run listing, and the locked-target precheck, all consuming ONE resolved list `X4_ITEMS`)
- Modify: `install.ps1` (the same: `$X4CopyItems`, `$X4AgentItems`, `-Agent` param, one resolved `$X4Items`)
- Modify: `tools/x4validate/tests/test_installers_agree.py`
- Modify: `tools/x4validate/tests/test_install_over_existing.py` (end-to-end, both installers)

**Failing tests first.** Source-level, in `test_installers_agree.py`; parsed from both files and never restated:

```python
def sh_agent_items() -> dict[str, list[str]]:
    text = SH.read_text(encoding="utf-8")
    got = {m.group(1): sorted(m.group(2).split())
           for m in re.finditer(r'^X4_AGENT_ITEMS_(\w+)="([^"]*)"', text, re.M)}
    assert got, "no X4_AGENT_ITEMS_* in install.sh"
    return got


def ps1_agent_items() -> dict[str, list[str]]:
    text = PS1.read_text(encoding="utf-8")
    m = re.search(r"\$X4AgentItems\s*=\s*@\{(.*?)^\}", text, re.S | re.M)
    assert m, "no $X4AgentItems in install.ps1"
    return {k: sorted(re.findall(r"'([^']+)'", v))
            for k, v in re.findall(r"(\w+)\s*=\s*@\(([^)]*)\)", m.group(1))}


def test_both_installers_define_the_SAME_agent_sets():
    sh, ps = sh_agent_items(), ps1_agent_items()
    assert set(sh) == set(ps) >= {"claude", "codex", "generic"}, (sh.keys(), ps.keys())
    for k in sh:
        assert sh[k] == ps[k], f"agent {k}: install.sh {sh[k]} vs install.ps1 {ps[k]}"


def test_F8_codex_and_generic_ship_AGENTS_md_and_claude_ships_CLAUDE_md():
    a = sh_agent_items()
    assert "AGENTS.md" in a["codex"] and "AGENTS.md" in a["generic"]
    assert "CLAUDE.md" in a["claude"] and ".claude" in a["claude"]
    assert "CLAUDE.md" not in sh_items() and ".claude" not in sh_items(), (
        "agent-specific items must live in exactly one place: the agent set")


def test_the_neutral_source_tree_is_in_NO_installed_set():   # Q1 = runtime-only; flip if answered otherwise
    every = set(sh_items()).union(*sh_agent_items().values())
    assert "agent" not in every


def test_no_item_is_both_common_and_agent_specific():
    common = set(sh_items())
    for k, v in sh_agent_items().items():
        assert not common & set(v), f"{k}: {sorted(common & set(v))} is in both lists"
```

`test_both_installers_copy_the_same_items` keeps working. Its `>= 12` floor must be re-derived: the
common set drops 2 items, from 16 to 14, which is still ≥ 12. Recount in the commit and do not relax the floor.

End-to-end, in `test_install_over_existing.py`. Reuse `_install`/`_fresh`, parametrized over both installers like the existing tests:

```python
@pytest.mark.parametrize("agent,present,absent", [
    ("claude", ["CLAUDE.md", ".claude/settings.json"], ["AGENTS.md", ".codex"]),
    ("codex",  ["AGENTS.md", ".codex/hooks.json"],     ["CLAUDE.md", ".claude/settings.json"]),
    ("all",    ["CLAUDE.md", "AGENTS.md", ".codex/hooks.json"], ["agent"]),
])
def test_F8_each_agent_installs_its_own_files_and_nothing_else(installer, tmp_path, agent, present, absent):
    dest = _fresh(tmp_path)
    r = _install(installer, tmp_path, dest, *_agent_args(installer, agent))
    assert r.returncode == 0, r.stdout + r.stderr
    for rel in present:
        assert (dest / rel).exists(), f"--agent {agent} did not install {rel}"
    for rel in absent:
        assert not (dest / rel).exists(), f"--agent {agent} installed {rel}, which it must not"


def test_an_unknown_or_unsupported_agent_REFUSES_before_writing(installer, tmp_path):
    dest = _fresh(tmp_path)
    r = _install(installer, tmp_path, dest, *_agent_args(installer, "opencode"))
    assert r.returncode == 2 and "M8" in (r.stdout + r.stderr)
    assert not any(dest.iterdir()), "a refused install wrote something"
```

`_agent_args(installer, a)` returns `["--agent", a]` or `["-Agent", a]`. The `.codex` cases need
Lane B's tree committed. Until then, mark them with `pytest.skip("Lane B tree not landed")` keyed on
`(REPO / ".codex" / "hooks.json").exists()`. That gives a counted skip, never a bare return (CLAUDE.md #37).

**Implementation notes:**
- Parse `--agent` and `-Agent` next to `--method`, validate them against the set names plus `all`, and refuse `opencode` with M8.
- Resolve `X4_ITEMS="$X4_COPY_ITEMS $(agent items…)"` once, and replace every `$X4_COPY_ITEMS` *consumer* with `$X4_ITEMS`.
  `_tracked_copy_set`, `copy_toolkit`, the dry-run listing and the locked-target precheck at install.sh:521-540 all read it,
  and the ps1 equivalents at 215, 227, 339, 480 and 858.
- `test_installers_agree.sh_items()` must still parse the COMMON list, so keep the `X4_COPY_ITEMS=` literal.
- `--method global`: unchanged. It installs `.claude/skills` and `.claude/agents` into `~/.claude` only.
  `--agent codex --method global` refuses ("global layout is Claude-only; Codex global skills are a follow-up"),
  so no layout is half-supported. Add a test for that refusal, again on both installers.
- Print the installed targets in the summary: `agents installed: claude, codex`.

**Commands:**
- `uv run --frozen python -m pytest -q -rs tests/test_installers_agree.py` Expected: the new tests fail
  first, then pass.
- `uv run --frozen python -m pytest -q -rs tests/test_install_over_existing.py -k "F8 or unsupported or global"`
  Expected: pass, with the `.codex` rows skipped (counted) until Lane B lands, and 0 skipped after.

**Commit:** `installers: --agent claude|codex|generic|all ships each agent's own files; both installers agree (audit F8)`

**Confidence:** 80%. The installers are 70 KB each, and every past round found "fixed in bash, absent in
PowerShell". To raise it, run the whole of `test_install_over_existing.py` (both installers, about 1,500 lines of
regression) at the task's end rather than `-k`, plus a mutation twin: delete `AGENTS.md` from the ps1
codex set only, and require `test_both_installers_define_the_SAME_agent_sets` to go red.

---

## Task 4: Never overwrite a user-owned AGENTS.md

**Files:** `install.sh`, `install.ps1`, `tools/x4validate/tests/test_install_over_existing.py`

**Failing tests first:**

```python
def test_a_USER_AGENTS_md_is_moved_aside_never_overwritten(installer, tmp_path):
    dest = _fresh(tmp_path)
    mine = dest / "AGENTS.md"
    mine.write_bytes(b"# my own codex notes\n")
    r = _install(installer, tmp_path, dest, *_agent_args(installer, "codex"))
    assert r.returncode == 0, r.stdout + r.stderr
    kept = dest / "AGENTS.pre-4.0.md"
    assert kept.read_bytes() == b"# my own codex notes\n"
    assert "AGENTS.pre-4.0.md" in (r.stdout + r.stderr)        # SAID, not only done
    assert mine.read_bytes() != b"# my own codex notes\n"       # the shipped one is now in place


def test_TWIN_an_AGENTS_md_identical_to_the_shipped_one_is_not_moved(installer, tmp_path):
    dest = _fresh(tmp_path)
    (dest / "AGENTS.md").write_bytes((REPO / "AGENTS.md").read_bytes())
    _install(installer, tmp_path, dest, *_agent_args(installer, "codex"))
    assert not (dest / "AGENTS.pre-4.0.md").exists()


def test_a_second_preserved_copy_never_overwrites_the_first(installer, tmp_path):
    dest = _fresh(tmp_path)
    (dest / "AGENTS.pre-4.0.md").write_bytes(b"older\n")
    (dest / "AGENTS.md").write_bytes(b"newer\n")
    _install(installer, tmp_path, dest, *_agent_args(installer, "codex"))
    assert (dest / "AGENTS.pre-4.0.md").read_bytes() == b"older\n"
    assert any(p.read_bytes() == b"newer\n" for p in dest.glob("AGENTS.pre-4.0.*.md"))


def test_a_DRY_RUN_moves_nothing_and_says_what_it_would_move(installer, tmp_path):
    dest = _fresh(tmp_path)
    (dest / "AGENTS.md").write_bytes(b"mine\n")
    r = _install(installer, tmp_path, dest, *_agent_args(installer, "codex"), "--dry-run")
    assert (dest / "AGENTS.md").read_bytes() == b"mine\n"
    assert not (dest / "AGENTS.pre-4.0.md").exists()
    assert "AGENTS.pre-4.0.md" in r.stdout + r.stderr
```

(`--dry-run` vs `-DryRun`: use the same helper the existing dry-run tests use.)

**Implementation:** add one function per installer (`preserve_user_agents_md DEST` and `Save-UserAgentsMd $dest`).
- It runs BEFORE the copy and AFTER the locked-target precheck.
- It compares normalised bytes (CRLF→LF) to `$SRC/AGENTS.md`. If they differ, it moves the file to the first free
  `AGENTS.pre-4.0.md` / `AGENTS.pre-4.0.<stamp>.md` (a no-clobber move) and prints the path.
- A read-only (x4lock'd) user AGENTS.md hits the existing up-front locked-file refusal first. That is
  correct: it names `x4lock unlock`. Add one test asserting that refusal names AGENTS.md.
- Why a hash list is not needed, unlike spec §8's CLAUDE.md migration: 0 of 23 releases ever shipped
  AGENTS.md, so "differs from the source" is exactly "not ours". **When 4.0 ships, this rule must gain the
  hash list of shipped AGENTS.md versions.** Leave a comment saying so, and file a CHANGELOG line in the release task.

**Commands:** `uv run --frozen python -m pytest -q -rs tests/test_install_over_existing.py -k AGENTS`
Expected: 5 fail first, then pass, on both installers (10 parametrized results).

**Commit:** `installers: an AGENTS.md the toolkit never shipped is moved aside to AGENTS.pre-4.0.md, never overwritten`

**Confidence:** 88%. To raise it: the `-OverExisting` path. Run the same tests with `over_existing=True`
(the harness default) AND False, and confirm the refusal path never reaches the move.

---

## Task 5: `x4doctor` skeleton: the result model that cannot say OK about nothing

**Files:**
- Create: `scripts/x4doctor.py`
- Create: `tools/x4validate/tests/test_x4doctor.py`

**Failing tests first:**

```python
import importlib.util, json, subprocess, sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("x4doctor", REPO / "scripts" / "x4doctor.py")
doc = importlib.util.module_from_spec(_spec); sys.modules["x4doctor"] = doc; _spec.loader.exec_module(doc)


def test_no_agent_target_at_root_is_exit_2_never_ok(tmp_path):
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "x4doctor.py"), "--root", str(tmp_path)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 2 and "OK" not in r.stdout.split()


def test_summarise_all_UNKNOWN_is_not_ok():
    rows = [doc.Check("a", "claude", doc.UNKNOWN, "x")]
    assert doc.exit_code(rows) == 3


def test_summarise_zero_answered_is_2():
    assert doc.exit_code([]) == 2
    assert doc.exit_code([doc.Check("a", "codex", doc.NA, "not installed")]) == 2


def test_any_FAIL_wins_over_OK():
    rows = [doc.Check("a", "claude", doc.OK, ""), doc.Check("b", "claude", doc.FAIL, "")]
    assert doc.exit_code(rows) == 1


def test_a_check_that_RAISES_becomes_UNKNOWN_with_the_exception_named():
    def boom(ctx): raise RuntimeError("kaput")
    row = doc.run_check("boom", "claude", boom, ctx=None)
    assert row.status == doc.UNKNOWN and "kaput" in row.detail


def test_json_output_is_one_parseable_document(tmp_path):
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "x4doctor.py"), "--root", str(tmp_path), "--json"],
                       capture_output=True, text=True, timeout=120)
    d = json.loads(r.stdout)
    assert d["v"] == 1 and isinstance(d["checks"], list)
```

**Implementation:**

```python
OK, FAIL, UNKNOWN, NA = "OK", "FAIL", "UNKNOWN", "N/A"
@dataclass(frozen=True)
class Check: id: str; target: str; status: str; detail: str

def exit_code(rows) -> int:
    answered = [r for r in rows if r.status in (OK, FAIL)]
    if not answered: return 2
    if any(r.status == FAIL for r in rows): return 1
    return 3 if any(r.status == UNKNOWN for r in rows) else 0
```

The other pieces:
- `run_check(id, target, fn, ctx)` wraps every check function and turns any exception into `UNKNOWN`.
- `detect_targets(root)` returns `{"claude": (root/".claude/settings.json").is_file(), "codex": (root/".codex").is_dir(),
  "generic": (root/"AGENTS.md").is_file()}`.
- `main()` prints a fixed-width table, with **the verdict line FIRST** (CLAUDE.md #38: the head survives truncation),
  then the rows.
- Default `--root` is the nearest ancestor of CWD containing `.claude/` or `.codex/` or `AGENTS.md`.
- A Python version below 3.10 makes the script refuse with exit 2.

**Commands:** `uv run --frozen python -m pytest -q -rs tests/test_x4doctor.py` Expected: fail
(file missing), then 6 pass. Also run under the system interpreter that hooks use: `py -3.10 scripts/x4doctor.py --root .`
Expected: it runs (proves the 3.10 constraint).

**Commit:** `x4doctor: result model and exit contract -- OK only when something answered, UNKNOWN is never OK`

**Confidence:** 93%.

---

## Task 6: x4doctor: toolchain and roots, as the GUARDS see them

The rule here is to ask the same resolver the guards use, never a reimplementation, because a parallel
implementation answers an adjacent question (CLAUDE.md #22b).

**Files:** `scripts/x4doctor.py`, `tools/x4validate/tests/test_x4doctor.py`

**Checks:**

1. `bash`: report all three resolvers' answers (`gitbash.find_bash()`, `x4guard.resolve_bash()` by importing the
   deployed `x4guard.py` from `<root>/.claude/hooks/`, and `shutil.which("bash")`).
   - **FAIL** if the one x4guard uses is a stub (`system32`/`syswow64`/`windowsapps`) or does not run `bash -c 'echo ok'`.
   - **FAIL**, with the PATH order named, if `which("bash")` is a stub. That is the bash an agent host may pick for a hook command.
   - **UNKNOWN** if the resolvers disagree but both are real.
2. `python (guards)`: run `<bash> -c 'source <hooks>/_x4-env.sh >/dev/null 2>&1; x4_python'`, then EXECUTE the result with
   `-c "import sys; print(sys.version_info[:2])"`.
   - **FAIL** if it is empty, or if it resolves but fails to run (the Store-stub case).
   - **FAIL** if the version is below 3.10.
   - `X4_PYTHON` set but unresolvable is FAIL, with the variable named.
3. `jq`: `"${JQ:-jq}" -e . <<< '{}'` under the same bash. If jq is missing but python is OK, the row is **OK with a
   note**, matching setup.sh's WARN. If both are missing, it is FAIL.
4. `roots`: from bash, after sourcing `_x4-env.sh`, print `X4_TOOLKIT X4_GAME X4_REFERENCE X4_PROFILE X4_MODS _x4_cfg`.
   From Python, `_paths.game_root()/reference()/profile()` and `_find_env_file()`.
   - **FAIL** if a key the guards use is empty or names a nonexistent dir. Name it.
   - **FAIL** if bash and Python disagree on `X4_REFERENCE` or `X4_GAME`. The guards and the tools would then protect and
     read different trees, which is the cwd-walk vs `CLAUDE_PROJECT_DIR` divergence from the planning table.
   - Always print WHICH config file each side read.

**Failing tests first** (the fakes are stub executables written into `tmp_path` and put first on PATH):

```python
@pytest.mark.skipif(os.name != "nt", reason="the stub trap is Windows-only")
def test_a_WSL_stub_first_on_PATH_is_a_FAIL_naming_it(fake_root, monkeypatch):
    stub = fake_root / "Windows" / "System32"; stub.mkdir(parents=True)
    (stub / "bash.exe").write_bytes(b"MZ")                    # resolves, cannot run a Windows path
    monkeypatch.setenv("PATH", str(stub) + os.pathsep + os.environ["PATH"])
    rows = {r.id: r for r in doc.check_toolchain(doc.Ctx(root=fake_root))}
    assert rows["bash.path"].status == doc.FAIL and "System32" in rows["bash.path"].detail


def test_a_python_that_RESOLVES_but_FAILS_is_FAIL_not_OK(fake_root, monkeypatch, tmp_path):
    bad = tmp_path / "badpy"; bad.mkdir()
    _write_failing_exe(bad / "python")                         # exits 9, prints nothing
    monkeypatch.setenv("X4_PYTHON", str(bad / "python"))
    rows = {r.id: r for r in doc.check_toolchain(doc.Ctx(root=fake_root))}
    assert rows["python.guards"].status == doc.FAIL


def test_TWIN_a_working_python_is_OK(fake_root):
    rows = {r.id: r for r in doc.check_toolchain(doc.Ctx(root=fake_root))}
    assert rows["python.guards"].status == doc.OK


def test_bash_and_python_DISAGREEING_on_reference_is_FAIL(fake_root, monkeypatch):
    # X4_TOOLKIT unset; the root's x4-paths.env says REF=A; a cwd-walk config says REF=B
    ...  # build both files; assert rows["roots.agree"].status == FAIL and both paths in detail


def test_TWIN_agreeing_roots_are_OK(fake_root): ...
```

`fake_root` is a fixture that copies the repo's generated `.claude/hooks/` into `tmp_path/root/.claude/hooks/`.
Copy it, so the real `_x4-env.sh` runs. It also writes a `.claude/x4-paths.env` pointing at tmp dirs, in the shape
of `test_x4guard_check.py`'s `sandbox`.

**Commands:** `uv run --frozen python -m pytest -q -rs tests/test_x4doctor.py -k "toolchain or python or bash or roots"`
Expected: fail, then pass. Then `python scripts/x4doctor.py --root "<game root>"` (read-only). Expected:
python is `py` and OK, jq is OK, roots agree. Record the output in the commit.

**Commit:** `x4doctor: bash/python/jq and roots resolved exactly as the guards resolve them; a stub that resolves but cannot run is FAIL`

**Confidence:** 85%. The bash/Python roots comparison depends on how `_x4-env.sh` exports. Measure first with the
planning probe, which is MEASURED to expose `$X4_REFERENCE` and `$_x4_cfg`. `_x4_cfg` is an internal name, so add a
test that fails if it disappears, rather than trusting it silently.

---

## Task 7: x4doctor: parity per target

**Files:** `scripts/x4doctor.py`, `tools/x4validate/tests/test_x4doctor.py`

The source is the toolkit repo, found via `$X4_TOOLKIT`. If that is unset, it is UNKNOWN with the reason. Never use the doctor's own location,
because an installed copy would compare to itself. For each present target, with `spec = deploy_parity.TARGETS[target]`
(loaded via `importlib` from `$X4_TOOLKIT/tools/x4validate/gates/deploy_parity.py`):

- **Root is a different tree from the source:** `compare_trees(src/spec.root_rel, root/spec.root_rel, spec)`.
  Every row at parity gives **OK** with "N files". Any drift gives **FAIL**, naming at most 10 files and the count hidden.
- **Root IS the source tree** (in-game install, or a session in the repo): `deploy_parity` refuses this by design.
  - If `root/agent/` and `tools/x4validate/scripts/gen-agent-trees.py` both exist, use `problems(generate(root), root)` → OK/FAIL.
  - Otherwise **UNKNOWN: "this root is the toolkit and has no agent/ source; parity cannot be checked here"**.
    This is the normal case for an in-game install under Q1 = runtime-only, and it must be stated, not hidden. See Q4 for the stronger option.
- The root `CLAUDE.md`/`AGENTS.md` are NOT in any deploy population (READ). Report them as
  `instructions: present / absent / user-owned (no GENERATED banner)`. That is informational, so the status is OK or N/A.
  Flag a game-root AGENTS.md without the banner, because Codex reads THAT file. This is exactly the author's stale personal file today.
- A target present at root but absent from `TARGETS` (codex before Lane B lands) is **UNKNOWN**, never N/A.

**Failing tests first:** cover drift → FAIL; identical → OK; CRLF-only → OK; same-tree-without-agent → UNKNOWN; and codex present
with no spec → UNKNOWN. Each case gets a fixture tree pair.

```python
def test_same_tree_without_source_is_UNKNOWN_not_OK(fake_root, monkeypatch):
    monkeypatch.setenv("X4_TOOLKIT", str(fake_root))          # root IS the toolkit, no agent/
    rows = {r.id: r for r in doc.check_parity(doc.Ctx(root=fake_root))}
    assert rows["parity.claude"].status == doc.UNKNOWN
```

**Commands:** `uv run --frozen python -m pytest -q -rs tests/test_x4doctor.py -k parity`. Then run doctor against the game
root. Expected: `parity.claude` matches `uv run python gates/deploy_parity.py`'s verdict, with the same file count.
Compare the two outputs per item. A disagreement means the doctor is wrong (#22).

**Commit:** `x4doctor: deployed-vs-source parity per agent target, reusing deploy_parity; same-tree without source is UNKNOWN`

**Confidence:** 88%.

---

## Task 8: x4doctor: guard self-test (controls that must deny, controls that must allow)

**Files:** `scripts/x4doctor.py`, `tools/x4validate/tests/test_x4doctor.py`

Run `<root>/.claude/hooks/x4guard.py check` (or Lane B's runtime copy for codex, if separate) as a subprocess with
the guards' python. Six controls follow; all except the last were MEASURED on this machine during planning:

| id | kind / shell | target | must be |
|---|---|---|---|
| deny.write.ref | write | `<X4_REFERENCE>/__x4doctor_probe__.xml` (non-existent) | deny, `inert:false` |
| deny.delete.ref | delete | same | deny, `inert:false` |
| deny.pwsh.ref | shell/powershell | `Set-Content -Path '<ref>/__x4doctor_probe__.xml' -Value x` | deny, `inert:false` |
| deny.bash.rmref | shell/bash | `rm -rf '<ref>'` | deny, `inert:false` |
| allow.bash.echo | shell/bash | `echo x4doctor` | allow |
| allow.pwsh.echo | shell/powershell | `Write-Output x4doctor` | allow (**measure in Task 0 M-C3 before pinning**) |

The verdicts:
- All match: **OK**, with the elapsed time.
- Any `inert:true`: **FAIL ("guards cannot evaluate: <reason>")**.
- A deny control that allows: **FAIL ("the guard LET THROUGH a write into reference/")**.
- An allow control that denies: **FAIL ("guards deny everything; not a working guard")**. This is the twin: a guard that denies
  everything must not read as healthy.
- No `X4_REFERENCE` resolved: the deny controls are **UNKNOWN**, and the allow controls still run.

Doctor never creates the probe path. The non-existent file is the point: nothing to damage even if a future x4guard regressed into executing.

**Failing tests first:**

```python
def test_selftest_all_controls_hold_is_OK(guard_sandbox):
    rows = {r.id: r for r in doc.check_guards(guard_sandbox.ctx)}
    assert rows["guards.selftest"].status == doc.OK


def test_a_guard_that_ALLOWS_the_reference_write_is_FAIL(guard_sandbox):
    _replace_guard(guard_sandbox, "protect-files.sh", "#!/bin/bash\nexit 0\n")   # allows everything
    rows = {r.id: r for r in doc.check_guards(guard_sandbox.ctx)}
    assert rows["guards.selftest"].status == doc.FAIL and "deny.write.ref" in rows["guards.selftest"].detail


def test_a_guard_that_DENIES_everything_is_FAIL(guard_sandbox):
    _replace_guard(guard_sandbox, "protect-bash.sh",
                   '#!/bin/bash\nprintf \'{"hookSpecificOutput":{"permissionDecision":"deny","permissionDecisionReason":"x"}}\'\n')
    rows = {r.id: r for r in doc.check_guards(guard_sandbox.ctx)}
    assert rows["guards.selftest"].status == doc.FAIL and "allow.bash.echo" in rows["guards.selftest"].detail


def test_an_INERT_guard_is_FAIL_not_ok(guard_sandbox, monkeypatch):
    monkeypatch.setenv("X4_PYTHON", str(guard_sandbox.root / "no-such-python"))
    rows = {r.id: r for r in doc.check_guards(guard_sandbox.ctx)}
    assert rows["guards.selftest"].status == doc.FAIL and "inert" in rows["guards.selftest"].detail.lower()


def test_no_reference_configured_makes_deny_controls_UNKNOWN(guard_sandbox, monkeypatch): ...
```

`guard_sandbox` is the copied-hooks fixture from Task 6 plus a reference dir.

**Commands:** `uv run --frozen python -m pytest -q -rs tests/test_x4doctor.py -k guards`. Expected: fail, then pass. Doctor on the
game root: `guards.selftest OK`, with time under 30 s (M-C4).

**Commit:** `x4doctor: guard self-test -- reference deny controls and allow controls; inert, allow-all and deny-all are each FAIL`

**Confidence:** 90%.

---

## Task 9: x4doctor: per-agent "live" checks (Claude wiring, Codex trust and review, rules, X4_GUARD, Layer 2)

**Files:** `scripts/x4doctor.py`, `tools/x4validate/tests/test_x4doctor.py`

**Claude target:**
- `claude.wiring`: parse `<root>/.claude/settings.json` (stdlib json). For PreToolUse matchers `Bash`, `PowerShell`,
  `Edit|Write|NotebookEdit` (as currently registered; READ in the audit), every `command` must resolve to an
  existing script after substituting `$CLAUDE_PROJECT_DIR` → root.
  - **FAIL** if any matcher is missing, or if a script is absent.
  - `settings.local.json` containing `"disableAllHooks": true` is **FAIL** (ASSUMED key name; confirm it against
    Claude Code settings docs via the claude-code-guide agent before pinning).

**Codex target** (needs Python ≥ 3.11 for `tomllib`; otherwise UNKNOWN):
- `codex.config`: `$CODEX_HOME/config.toml` or `~/.codex/config.toml` (M-C2). Unreadable or absent is **UNKNOWN**,
  "Codex has never run here, or config is elsewhere".
- `codex.trusted`: `[projects.'<root lower-cased>']` must have `trust_level == "trusted"`. The case-folded key was
  MEASURED. Missing is **FAIL ("project not trusted: Codex will not load .codex/ here; run codex in this folder and
  trust it")**.
- `codex.reviewed`: for every hook definition `(event, i, j)` in `<root>/.codex/hooks.json`, a `[hooks.state.'<key>']`
  must exist, using the key format from M-C1.
  - Any missing: **FAIL ("hooks NOT REVIEWED: Codex skips them SILENTLY; open /hooks in Codex and approve")**.
  - `trusted_hash`: if M-C1 proved it pinnable, compare to the pinned value, and a mismatch is **FAIL ("definition changed since review")**.
    Otherwise **UNKNOWN**, citing M11.
- `codex.rules`: `<root>/.codex/rules/x4.rules` exists. If `codex` is on PATH, run
  `codex execpolicy check --rules <file> <one must-match command from Lane B's rule table>` and expect forbidden.
  Without `codex` on PATH, the parse check is UNKNOWN and file presence is OK.

**All targets:**
- `guard.escape`: `X4_GUARD` from the environment.
  - `off` gives **FAIL ("GUARDS OFF for sessions launched from this environment")**.
  - Unset or `on` gives OK.
  - Until Lane E implements the hatch, the detail adds "(guards do not yet read X4_GUARD)". MEASURED 0 readers.
- `layer2.reference`: call Lane D's query.
  - Absent gives **FAIL** for codex/generic targets and **OK-with-note** for claude-only, where the hook covers deletes.
  - If Lane D's function is not present, the row is UNKNOWN.
- `x4lock`: import `scripts/x4lock.py`. Unlocked or missing counts give **UNKNOWN**, informational, with counts. The lock
  is the user's choice, so it is not FAIL. Raised `Unresolvable` gives UNKNOWN.

**Failing tests first** (Codex rows use a fake `CODEX_HOME` with handwritten config.toml fixtures):

```python
def test_untrusted_project_is_FAIL(codex_root, codex_home):
    codex_home.joinpath("config.toml").write_text("[projects]\n", encoding="utf-8")
    rows = {r.id: r for r in doc.check_codex(doc.Ctx(root=codex_root))}
    assert rows["codex.trusted"].status == doc.FAIL


def test_TWIN_trusted_lowercased_key_is_OK(codex_root, codex_home):
    key = str(codex_root).lower()
    codex_home.joinpath("config.toml").write_text(
        f"[projects.'{key}']\ntrust_level = \"trusted\"\n", encoding="utf-8")
    rows = {r.id: r for r in doc.check_codex(doc.Ctx(root=codex_root))}
    assert rows["codex.trusted"].status == doc.OK


def test_unreviewed_hook_definition_is_FAIL_naming_the_silent_skip(codex_root, codex_home): ...
def test_hash_unverifiable_is_UNKNOWN_not_OK(codex_root, codex_home): ...
def test_no_codex_config_is_UNKNOWN(codex_root, codex_home): ...
def test_X4_GUARD_off_is_FAIL(claude_root, monkeypatch): ...
def test_missing_PowerShell_matcher_in_settings_is_FAIL(claude_root): ...
```

**Commands:** `uv run --frozen python -m pytest -q -rs tests/test_x4doctor.py -k "codex or claude or escape or layer2"`.
Then doctor on the game root. Expected now:
- `claude.wiring OK`;
- `codex` N/A (no `.codex/` deployed);
- `layer2.reference UNKNOWN` until Lane D lands.

**Commit:** `x4doctor: per-agent liveness -- Claude wiring, Codex trust/review/rules, X4_GUARD, Layer 2 and x4lock status`

**Confidence:**
- 75% for the Codex rows, because M-C1 is not yet measured. They ship as UNKNOWN for the hash until it is,
  which is correct behaviour, not a defect. A live review in two dirs (M-C1) raises them to 90%.
- 90% for the other rows.

---

## Task 10: Docs and lane gate

**Files:**
- `CHANGELOG.md`: Unreleased lines for F8, F9 and x4doctor; correct "the installers do not ship it yet".
- `README.md`: the install section gains `--agent`, plus an `x4doctor` paragraph in the guards section and the per-agent capability table from spec §3.
- `agent/README.md`: one line saying installed toolkits are runtime-only (per Q1).

Lane A owns `agent/instructions/*`. Hand them the routing row and the codex-addendum line; do not edit them here.

**Lane gate** (run once, at lane end, in the lane worktree; long jobs in the background per #25):
1. `bash scripts/test-hooks.sh`. Expected: 177 passed, 0 failed, 0 skipped. Unchanged; this lane does not touch hooks.
2. Focused: `uv run --frozen python -m pytest -q -rs tests/test_x4lock.py tests/test_deploy_parity.py
   tests/test_deploy_claude_dir.py tests/test_installers_agree.py tests/test_install_over_existing.py
   tests/test_x4doctor.py tests/test_gen_agent_trees.py`. Expected: all pass. Any skip is named and counted; the
   `.codex` skips must be 0 once Lane B has landed.
3. Full suite (background, about 30 min): `uv run --frozen python -m pytest -q -rs`. Expected: the previous
   baseline (3,011 passed, 3 skipped Windows symlink checks) plus this lane's new tests. Diff the test IDs per item, not just the totals.
4. `uv run python scripts/gen-agent-trees.py --check`: exit 0. `uv run python gates/deploy_parity.py`: unchanged verdict.
5. `python scripts/scan-identifiers.py`: clean. No personal paths in tests; fixtures use `tmp_path`.
6. **Falsification twins** (#26). Apply each mutant, run the named test, require red, then revert. Clear `__pycache__`.
   - x4doctor `exit_code` returning 0 for an empty list: `test_summarise_zero_answered_is_2` goes red.
   - The deny-all branch removed: `test_a_guard_that_DENIES_everything_is_FAIL` goes red.
   - `AGENTS.md` moved into `_GAME_RELATIVE`: the twin from Task 1 goes red.
   - `AGENTS.md` removed from only the ps1 codex set: the agreement test goes red.
   - The preserve step removed from install.sh only: `test_a_USER_AGENTS_md_is_moved_aside_never_overwritten[sh]` goes red.
7. Cold read: run `x4doctor` in the game root and in the repo, then read every row against what it claims (#41).

**Commit:** `docs: --agent, x4doctor, F8/F9 closed (CHANGELOG, README, agent/README)`

---

## Files touched (union)

- `install.sh`
- `install.ps1`
- `scripts/x4lock.py`
- `scripts/x4doctor.py` (new)
- `tools/x4validate/gates/deploy_parity.py`
- `tools/x4validate/tests/test_x4lock.py`
- `tools/x4validate/tests/test_deploy_parity.py`
- `tools/x4validate/tests/test_installers_agree.py`
- `tools/x4validate/tests/test_install_over_existing.py`
- `tools/x4validate/tests/test_x4doctor.py` (new)
- `CHANGELOG.md` (⚠ also dirty in master from another session; merge carefully)
- `README.md`
- `agent/README.md`

NOT touched: `agent/instructions/*`, `agent/guards/*`, generated files, `x4guard.py`, `deploy-claude-dir.py`
(Task 2 keeps its imports working unchanged).

## Cross-lane dependencies

**C needs:**

- **B:**
  1. The `.codex/` and `.agents/` tree layout, committed (Task 3's `.codex` rows, Task 9).
  2. `TARGETS["codex"]` in `deploy_parity.py`, after C's Task 2 lands. B appends; C owns the refactor.
  3. **Where the Codex hook entry lives at runtime.** Spec §5.4 points the frozen hook definitions at
     `agent/guards/entry.sh`. If that stands, the installed root needs `agent/guards/`, which contradicts Q1's
     recommended runtime-only install. **Recommend B generate the entry into a runtime location** (e.g. `.codex/hooks/entry.sh`, or reuse
     `.claude/hooks/`), so `agent/` stays source-only. This must be settled before B freezes the definitions, because a later move is a
     "Codex users must re-review" break.
  4. M-C1/M11 jointly.
  5. One must-match command per rule, for doctor's `execpolicy` probe.
- **A:** a game-root-suitable generated `AGENTS.md` before Task 3 ships it; the codex-addendum line "run `x4doctor` at
  session start"; and a routing-table row for `x4doctor` once the split frees headroom (CLAUDE.md has about 29 chars today).
- **D:** a read-only deny-delete state query for `reference\` (Task 9). D's unpack flow must lift and restore it, and it must not
  appear in x4lock's read-only manifest semantics without D and C agreeing on one owner for `x4lock.py` edits. **Conflict risk:** D and C both edit
  `scripts/x4lock.py`. Sequence: C's Task 1 is small, so land it first, then D rebases.
- **E:** a stable `x4guard check` JSON contract (doctor parses `decision`, `inert`, `guards`). The `X4_GUARD` hatch implementation is E's;
  the doctor row reports it either way. ⚠ E should also reconcile `x4guard.resolve_bash` with `scripts/gitbash.find_bash`. x4guard rejects only
  `system32`, not the `windowsapps`/`syswow64` stubs, and checks PATH before the Git install dirs. Doctor will SHOW the disagreement; E fixes it.

**Others need from C:**
- B and the release need `--agent` in both installers, the AGENTS.md preservation rule, and the `TargetSpec` slot.
- D needs the x4lock edit landed first.
- A's codex addendum and B's SessionStart output can name `x4doctor` (path `scripts/x4doctor.py`).

## Questions for the user (genuine decisions)

1. **Q1: What does an INSTALLED toolkit (game root, or separate folder) contain: runtime only, or the editable source?**
   **Recommend runtime only.**
   - Ship each agent's generated files (`CLAUDE.md` + `.claude/`, `AGENTS.md` + `.codex/` + `.agents/`). Do NOT ship `agent/`.
     Editing and regenerating is a maintainer act in the toolkit repo; the zip still contains `agent/` for anyone who wants it.
   - Consequences:
     - Codex's runtime hook entry must not live under `agent/` (see B.3);
     - doctor's parity in an in-game install is UNKNOWN unless Q4;
     - the maintainer-only stopgap AGENTS.md must never be what an installer ships.
2. **Q2: What should `--agent` default to?** **Recommend `all`.** It ships Claude and Codex files together:
   - the Codex files are inert without Codex;
   - a user who starts Codex later is covered once they review the hooks;
   - doctor reports exactly which are live.

   The alternative is `claude` (pure 3.x compatibility), which leaves Codex users unprotected unless they read the flag. `auto` means detecting
   agents on PATH, which is a guess, so I recommend against it.
3. **Q3: Should x4lock also lock `.agents/skills/*/SKILL.md`** (as it locks `.claude/skills/*/SKILL.md`)? **Recommend yes, for
   parity with Claude's skills**. The audit warned against blanket-locking generated folders, but skills are already locked for
   Claude, and the rule should not differ per agent. This is a one-line glob, deferred until you answer.
4. **Q4 (optional): Should the generator emit a hash manifest of every generated file** (e.g. `.x4-agent-manifest.json`), so that
   doctor can verify parity in an in-game install that has no `agent/` source? **Recommend yes, but as a follow-up**. Without it, that
   row is an honest UNKNOWN. It is a new generated artifact (Lane A/B's generator), so it is not in this lane.
5. **Q5 (yours, outside the toolkit): your game-root `AGENTS.md` is personal and stale.** It sends Codex to the Desktop
   `tools\x4validate`, which was archived on 2026-09-14. A Codex session there today reads it. Should it be updated or retired?
   Under the Task 4 rule, a 4.0 in-game install would move it aside to `AGENTS.pre-4.0.md` automatically.

## Confidence summary

| Task | Confidence | What raises it |
|---|---|---|
| 0 | 85% | M-C1 needs one interactive Codex hook review by the user |
| 1 x4lock | 92% | — |
| 2 deploy_parity targets | 93% | — |
| 3 installers `--agent` | 80% | full `test_install_over_existing.py` on both installers + the ps1-only mutation twin |
| 4 AGENTS.md preserve | 88% | the `-OverExisting` True/False matrix |
| 5 doctor skeleton | 93% | — |
| 6 toolchain/roots | 85% | a pinned test that `_x4_cfg`/exports still exist in `_x4-env.sh` |
| 7 parity | 88% | per-item agreement with `gates/deploy_parity.py` on the real game root |
| 8 guard self-test | 90% | M-C3 (pwsh allow control) |
| 9 per-agent live | 75% for the Codex rows, 90% for the rest | M-C1; confirm the `disableAllHooks` key name |

## Gate plan

- **Per task:** only the focused test file(s) named in that task, plus one read-only real run of the tool it touches
  (`x4lock status`, `deploy_parity.py`, `x4doctor`).
- **Lane end:** Task 10's gate, run once:
  - hook smoke;
  - the focused set;
  - the full pytest in the background;
  - generator check, identifier scan;
  - five named falsification twins;
  - a cold read of doctor output.

  The mutation gate (`mutation_probe.py`) is not needed. This lane touches none of its 9 target files. Never run it concurrently
  with a copy or port (#27).

## Wider findings (not in this lane's scope; surfaced per "what else is wrong")

- ⚠ The master working tree carries another session's uncommitted F2/F3/F4 work. The AUDIT doc says these are "FIXED on master", but
  as of this reading they are uncommitted. That is the other session's to resolve; until then, any count taken from master is contaminated (#7).
- `setup.sh`'s python check (`command -v` only, ignoring `X4_PYTHON`) disagrees with the guards' resolver. The doctor shows the
  disagreement, and setup should eventually call the same resolver. Candidate for Lane E or a follow-up.
- Three bash resolvers with different stub lists. Lane E.
- Two config-file discovery rules (bash: `X4_CONFIG` or `$X4_TOOLKIT/.claude`; Python: `$X4_TOOLKIT` or a cwd walk) can read different
  `x4-paths.env` files when `X4_TOOLKIT` is unset. Doctor's `roots.agree` exposes this. Spec §8's move of `x4-paths.env` to the toolkit root
  is unowned by any lane named in the brief, so it needs an owner.
- Spec §5.7's `X4_GUARD` escape hatch has 0 readers in the guards today.


## Amendments -- 2026-10-02 (user decisions; binding, supersede the text above)

Read DECISIONS.md in this folder first. Changes to THIS lane:
- **#2 changed:** the installers own the per-OS token rendering for the Codex tree (install.ps1 -> `$env:X4_TOOLKIT`, install.sh -> `$X4_TOOLKIT`), reusing the existing `$CLAUDE_PROJECT_DIR` rewrite; test both renderings in test_installers_agree.
- **#9 runtime-only, #10 --agent all, #11 lock .agents/skills/*/SKILL.md, #12 hash manifest deferred.**
- **#15:** x4doctor's checks must run on Linux/macOS best-effort (bash/python/jq resolution, POSIX layer-2 status from lane D); any Windows-only check reports N/A off Windows, never OK.
- **From lane A measurement:** root + nested AGENTS.md share ONE 32,768-byte budget -- an install must never place a second AGENTS.md under the game root (e.g. inside a mod or tools folder). Claude reads AGENTS.md only when no CLAUDE.md exists: write CLAUDE.md whenever the Claude target is installed.

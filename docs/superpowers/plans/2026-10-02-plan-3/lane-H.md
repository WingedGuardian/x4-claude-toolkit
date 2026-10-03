# Lane H -- installers: `--agent auto`, OS-level `X4_TOOLKIT`, 3.x -> 4.0 migration, Codex doc cap

Planner: lane H (read-only). Toolkit `$X4_TOOLKIT`, master `0cb667f`.
Branch for the implementer: `session/p3-H` (own worktree). Merge order J -> G -> L -> **H**, so H
rebases onto L's `--agent opencode` change in the same `case` block.

## Context

Plan 3 row H: `--agent auto`; set `X4_TOOLKIT` at OS level with `--no-env`, report-don't-overwrite
(user decision, binding); a personalised 3.x `CLAUDE.md` is kept as `X4-NOTES.pre-4.0.md`, found by
hashes of every shipped version; Codex `project_doc_max_bytes` opt-in; `install.sh` and `install.ps1`
agree.

### What I measured before planning (all read-only)

| # | Fact | Tier |
|---|---|---|
| F1 | **The "installer-REWRITTEN CLAUDE.md" premise does not hold for any tag.** I grepped `install.sh`, `install.ps1` and `setup.sh` at all 23 tags (v1.0..v3.3.1) for writers (`sed -i`, `-replace`, `Set-Content`, `WriteAllText`). The only rewrite is `$CLAUDE_PROJECT_DIR -> $X4_TOOLKIT` in the **global** arm. It is scoped to `~/.claude/skills/x4-*` and `~/.claude/agents/*.md` (v2.0 install.sh:155-157, v3.3.1 install.sh:860-880, v2.0 install.ps1:118-121). It never touches `CLAUDE.md`, and the global arm never copies `CLAUDE.md` at all. v1.x had no installer. | READ (23 of 23 tags) |
| F2 | 0 of 23 tag blobs of `CLAUDE.md` contain CRLF; 0 of 23 start with a BOM. 23 tags -> **10 distinct normalised hashes**. HEAD's `CLAUDE.md` (the 4.0 generated one) is in none of them, as expected. 42 commits on all refs touch `CLAUDE.md`. | MEASURED |
| F3 | CRLF can still reach an installed copy without any installer rewriting it: `* text=auto` in `.gitattributes` plus a Windows clone with `core.autocrlf=true`, or a zip built by `git archive` on such a machine. So normalisation is still required. It covers checkout and archive, not rewrite. | READ (.gitattributes) + INFERRED (autocrlf on users' machines) |
| F4 | `AGENTS.md` is 28,512 bytes, LF, blob = working copy (424 lines; it would be 28,936 if CRLF). The Codex cap is 32,768 B. Headroom is **4,256 B**. The generator already refuses more than 32,768 (`test_gen_agent_trees.py:127-164`). **A root `AGENTS.md` and a nested one SHARE that budget** (measure-A M-A2, Codex 0.160.0). Whether `~/.codex/AGENTS.md` counts against it was NOT measured. | MEASURED / READ |
| F5 | `copy_toolkit` does an unconditional `mkdir -p "$dest/.claude"` (install.sh:327), and `x4-paths.env` lives there for every agent target. So **an existing `.claude/` does NOT mean Claude Code**. Every 3.x install has one, and so does a 4.0 `--agent codex` install. The Claude marker has to be `CLAUDE.md` or `.claude/settings.json`. `.codex/` is created only when the Codex target is selected. | READ |
| F6 | On this machine: `claude` = `~/.local/bin/claude.exe` (native). `codex` is the npm shim set `codex`, `codex.cmd`, `codex.ps1`. Git Bash `command -v` finds the extensionless `codex` shim. PowerShell `Get-Command` returns `codex.ps1`. **The two lookups disagree on what they find**, so both installers use one explicit PATH walk with one name list. | MEASURED |
| F7 | User-scope `X4_TOOLKIT` here = `$X4_TOOLKIT` (backslashes). Machine scope is empty. The installer's `$TOOLKIT` is typically `C:/...` or `/c/...`. **A string compare would call this machine's own upgrade "different" every time**, so comparison must be canonical (separator, case, trailing separator). | MEASURED |
| F8 | Both installers already treat an inherited `$X4_TOOLKIT` as a NAMED destination (install.sh:25-26, install.ps1:37,42). Once lane H sets it at OS level, a later `install --method separate` with no `--toolkit` targets that folder. That is intended (upgrade in place), but it is new behaviour and the README must say so. | READ |
| F9 | The test harness (`test_install_over_existing.py:_install`) passes `os.environ` through and pins only `HOME`, `USERPROFILE`, `CLAUDE_CONFIG_DIR` and `CODEX_HOME`. Unchanged, **every existing installer test would write the developer's real HKCU `X4_TOOLKIT`** once T4 lands. In practice the different-value rule would refuse here, but CI runners have no value set. `ZDOTDIR` and `SHELL` are not pinned either. | READ |
| F10 | `scripts/verify-hook-tests.py` names neither installer, so no mutation anchors are involved. The CI `tests` job uses `actions/checkout@v4` with no `fetch-depth`, so it is shallow and has **no tags** (ci.yml:99; only the job at :659 has `fetch-depth: 0`). | READ |

## Global constraints

- Test-first: every test below is written and **watched failing** before the implementation lands.
  Each compound condition gets one falsification twin **per clause**.
- `install.sh` and `install.ps1` change in the same commit, and a test pins their agreement.
- Every new writer calls `refuse_if_dry_run` / `Refuse-IfDryRun` as its FIRST write-path statement.
  The dry-run listing reads the same decision function as the writer (the existing AGENTS.md pattern).
- New helpers are lane-prefixed: bash `_h_*`, PowerShell `*-H*` (e.g. `Get-HCanonicalSha256`).
- No test may touch the real user environment. The harness guard enforces this (T0). Use the Write/Edit
  tools for every file with backslashes; no heredocs.
- Config is written at the CURRENT location (`.claude/x4-paths.env` is not touched by this lane at all;
  lane I moves it).
- Focused tests only, one test process at a time. `test_install_over_existing.py` in full is long
  (~100 installer runs): run it once, at the end, with `run_in_background`.

## Interfaces

**Produces**
- `scripts/shipped-instruction-hashes.txt`: the data file. Line format
  `<sha256>  <CLAUDE.md|AGENTS.md>  <tag[,tag...]>`; `#` comments allowed. Ships in the copy set
  (`scripts` is already a copy item).
- `tools/x4validate/scripts/gen-shipped-hashes.py`: `canonical_sha256(bytes)`, `expected(repo)`,
  `check(repo)`, CLI `--write | --check` (rc 0/1/2).
- `scripts/x4-userenv.ps1`: the ONE Windows user-environment reader/writer, called by both installers.
  Args `get | set <value>`. Test seam `X4_INSTALL_ENV_REGKEY`.
- Installer flags: `--agent auto` / `-Agent auto`; `--no-env` / `-NoEnv`;
  `--codex-doc-max-bytes N` / `-CodexDocMaxBytes N`.
- Test seams (documented in-file as such): `X4_INSTALL_DETECT_PATH` (the PATH that agent detection
  walks), `X4_INSTALL_ENV_REGKEY` (the registry key in place of `HKCU\Environment`).
- Canonical form (one definition, three implementations): drop a leading UTF-8 BOM, delete every
  `0x0D`, strip trailing `0x0A` bytes, then SHA-256 as lowercase hex.

**Consumes**
- Lane L: `opencode` in `X4_AGENT_NAMES` / `$X4AgentNames`. Auto-detection iterates the agent names and
  skips any agent with no detect table, so L can add `X4_AGENT_DETECT_opencode` /
  `X4_AGENT_MARK_opencode` without touching H's code. If L lands first, H adds the opencode rows
  (`opencode` on PATH; marker `opencode.json` or `.opencode/`). They are READ from L's plan, not
  re-researched.
- Lane I: later moves `x4-paths.env` and edits `write_paths_env` and the summary `Config:` line. H
  touches neither, only the adjacent `IMPORTANT -- set X4_TOOLKIT` block.

---

## Task 0 -- measure, then make the harness unable to touch the real environment

**0a. Measurements (read-only, no code).** Record the results in the lane report.
- M-H0.1: list every subprocess call that runs `install.sh` or `install.ps1`, with
  `git grep -n -E "install\.(sh|ps1)" -- "tools/x4validate/tests/*.py" "scripts/*" "tools/x4validate/scripts/*"`
  and then reading each hit. Expected: only `_install()` in `test_install_over_existing.py`, plus
  `test_install_ps1_path_helpers...` (helpers only, no full run). Every other full-run caller gets
  `--no-env`.
- M-H0.2: list every existing test that writes a destination `CLAUDE.md` or `AGENTS.md` with text
  different from its source (`grep -n 'CLAUDE.md\|AGENTS.md' test_install_over_existing.py`). After T2
  those files are MOVED, so name every assertion that would change. Today I know of
  `test_the_refusal_the_user_SEES_first...:1163` (locked, and it refuses before any move), which stays
  green.

**0b. Harness change (`test_install_over_existing.py::_install`).** The test comes first:

```python
def test_the_harness_NEVER_lets_an_installer_reach_the_real_user_env(tmp_path, monkeypatch):
    """Every installer run gets a sandboxed registry key, HOME, ZDOTDIR and detect PATH,
    and --no-env unless the test asks for the env write. A test that forgot cannot reach
    HKCU\\Environment or the developer's ~/.zshenv."""
    captured = {}
    real_run = subprocess.run
    def spy(cmd, **kw):
        captured["cmd"], captured["env"] = cmd, kw["env"]
        return real_run(["python", "-c", "pass"], capture_output=True, text=True)
    monkeypatch.setattr(subprocess, "run", spy)
    monkeypatch.setattr(sys.modules[__name__], "_bash", lambda: "bash")   # never skip
    monkeypatch.setenv("ZDOTDIR", "<HOME>/.config/zsh")
    dest = _fresh(tmp_path)
    _install("sh", tmp_path, dest)
    env, cmd = captured["env"], captured["cmd"]
    assert env["X4_INSTALL_ENV_REGKEY"].startswith("HKCU\\Software\\X4ToolkitTests\\")
    assert pathlib.Path(env["ZDOTDIR"]).resolve().is_relative_to(tmp_path.resolve())
    assert pathlib.Path(env["X4_INSTALL_DETECT_PATH"]).resolve().is_relative_to(tmp_path.resolve())
    assert "--no-env" in cmd                                   # default
    _install("sh", tmp_path, dest, env_write=True)
    assert "--no-env" not in captured["cmd"]                   # twin: the opt-in reaches the CLI
```

Implementation: the new `_install` kwarg `env_write=False` adds `--no-env` / `-NoEnv` when False. The
env always carries `X4_INSTALL_ENV_REGKEY = HKCU\Software\X4ToolkitTests\<tmp_path.name>-<uuid8>`,
`ZDOTDIR = tmp_path/zdot`, `SHELL = /bin/bash` (tests override it), and
`X4_INSTALL_DETECT_PATH = tmp_path/no-agents` (an empty dir). `X4_TOOLKIT` is popped. The new flags
are mapped (`--no-env`, `--codex-doc-max-bytes N`; `--agent auto` already passes through).
`_refuse_unless_sandboxed` also refuses a regkey outside `HKCU\Software\X4ToolkitTests\`. A session
fixture `regkey_cleanup` runs `reg delete HKCU\Software\X4ToolkitTests /f` at session end, on Windows
only, and asserts it removed what tests created.

The flags do not exist yet in this task, so the spy test is the only run. It is RED (no regkey in env)
before the change and GREEN after.

- Files: `tools/x4validate/tests/test_install_over_existing.py`
- Run: `cd tools/x4validate && uv run pytest tests/test_install_over_existing.py -k "harness_NEVER" -q`
  Expected: `1 passed`
- Commit: `tests(installers): the harness sandboxes the user env, detect PATH and ZDOTDIR before any installer can write them`

Confidence 92%.

---

## Task 1 -- the shipped-instruction hash list, its generator, and a coverage test

**Decision: a data file, not hashes generated into the installers.** One file read by both installers
agrees with itself by construction. Two generated blocks would need their own agreement test and a
regeneration step in two languages. The data file sits in `scripts/`, which is already a copy item, so
it ships in zips and installs. If it is absent (a synthetic or truncated source), the installers say
so and treat every differing `CLAUDE.md` as the user's. That is the safe direction: kept, not lost.

**Decision: the scope is release tags `v[0-9]*`, as the spec says** (see Q3 for all-history blobs).
`AGENTS.md` rows use the same file. Today there are 0, because no tag shipped one (F4 / install.sh:585).
This also clears the standing `WHEN 4.0 SHIPS` warning at install.sh:588 / install.ps1:381 structurally.
Once v4.0.0 is tagged, the coverage test goes red until its `AGENTS.md` row is added.

Test first, in new file `tools/x4validate/tests/test_shipped_instruction_hashes.py`:

```python
"""Every tagged release's CLAUDE.md / AGENTS.md is KNOWN to the installers' 4.0 migration.

A tag missing from scripts/shipped-instruction-hashes.txt makes an upgrade from that release keep
the user's UNEDITED file as X4-NOTES.pre-4.0.md: safe, but noisy and wrongly worded."""
from __future__ import annotations
import hashlib, importlib.util, os, pathlib, subprocess
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
GEN = ROOT / "tools" / "x4validate" / "scripts" / "gen-shipped-hashes.py"


def _gen():
    spec = importlib.util.spec_from_file_location("gen_shipped_hashes", GEN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_canonical_form_one_twin_per_clause():
    c = _gen().canonical_sha256
    assert c(b"\xef\xbb\xbfa\r\nb\r\n\r\n") == hashlib.sha256(b"a\nb").hexdigest()
    assert c(b"a\r\nb") == c(b"a\nb")                 # clause: CR removed
    assert c(b"\xef\xbb\xbfa") == c(b"a")             # clause: leading BOM removed
    assert c(b"a\n\n\n") == c(b"a")                   # clause: trailing LF stripped
    assert c(b"a\nb") != c(b"a\nc")                   # content still counts
    assert c(b"\na") != c(b"a")                       # a LEADING newline is content
    assert c(b"x\xef\xbb\xbfa") != c(b"xa")           # a BOM is stripped only at the start


def _git(repo, *a):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)


def test_check_REPORTS_a_tag_missing_from_the_list(tmp_path):
    """The falsification twin for the coverage test: on a repo where it MUST go red, it does."""
    g = _gen()
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t"); _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "CLAUDE.md").write_bytes(b"one\n"); _git(tmp_path, "add", "CLAUDE.md")
    _git(tmp_path, "commit", "-qm", "1"); _git(tmp_path, "tag", "v1.0")
    (tmp_path / "CLAUDE.md").write_bytes(b"two\r\n"); _git(tmp_path, "commit", "-qam", "2")
    _git(tmp_path, "tag", "v2.0")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "shipped-instruction-hashes.txt").write_text(
        "%s  CLAUDE.md  v1.0\n" % g.canonical_sha256(b"one\n"), encoding="utf-8")
    missing = g.check(tmp_path)
    assert len(missing) == 1 and "v2.0" in missing[0], missing
    g.write(tmp_path)
    assert g.check(tmp_path) == []


def test_the_hash_list_covers_EVERY_tag():
    r = subprocess.run(["git", "-C", str(ROOT), "tag", "--list", "v[0-9]*"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("not a git checkout -- the shipped tags are unknown here")
    if not r.stdout.split():
        if os.environ.get("CI"):
            pytest.fail("CI checkout has NO tags: the tests job needs fetch-depth: 0 (ci.yml)")
        pytest.skip("no tags in this checkout (shallow clone)")
    assert _gen().check(ROOT) == []


def test_the_list_holds_NOTHING_that_was_never_shipped():
    """Set equality on (hash, name), not only coverage: a stray hash would let an installer
    overwrite a user's file that happened to match it."""
    g = _gen()
    have = g.read_rows(ROOT)
    r = subprocess.run(["git", "-C", str(ROOT), "tag", "--list", "v[0-9]*"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.split():
        pytest.skip("no tags here")
    assert {(h, n) for h, n, _ in have} == {(h, n) for h, n, _ in g.expected(ROOT)}
```

Implementation: `gen-shipped-hashes.py` (stdlib only). `expected(repo)` runs `git tag --list v[0-9]*`
and, per tag and per name in (`CLAUDE.md`, `AGENTS.md`), `git show <tag>:<name>` read as BYTES (never
through a text pipe, per the CRLF lesson). It groups by `(hash, name)`. `read_rows`, `write` and
`check` compare `(hash, name)` sets; the tag column is informational. The CLI is `--write`, or
`--check` with rc 1 on drift and rc 2 on an error.

- Files: `tools/x4validate/scripts/gen-shipped-hashes.py` (new), `scripts/shipped-instruction-hashes.txt`
  (new, generated), `tools/x4validate/tests/test_shipped_instruction_hashes.py` (new)
- Run: `cd tools/x4validate && uv run pytest tests/test_shipped_instruction_hashes.py -q`
  Expected: `4 passed` (RED first: 4 errors, the generator does not exist)
- Run: `uv run python scripts/gen-shipped-hashes.py --check` (from `tools/x4validate`)
  Expected: rc 0, `10 CLAUDE.md hashes over 23 tags; 0 AGENTS.md` (F2's numbers, re-derived)
- Commit: `installers: shipped-instruction hash list derived from every release tag, with a coverage test`

Confidence 93%.

---

## Task 2 -- 3.x -> 4.0: keep a personalised CLAUDE.md as X4-NOTES.pre-4.0.md (both installers)

Rule: the Claude target is selected AND a copy happens AND `dest/CLAUDE.md` exists AND its canonical
hash is neither the source `CLAUDE.md`'s canonical hash NOR a `CLAUDE.md` row in the data file. When
all hold, MOVE it to `X4-NOTES.pre-4.0.md`, or to `X4-NOTES.pre-4.0.<stamp>[-n].md` if that name is
taken. The step runs after every precheck and before the copy, the same position and shape as
`preserve_user_agents_md`. The dry-run listing reads the same `_h_claude_md_move_target`. The message
says the 4.0 file now loads every session, and that their own notes belong in `X4-NOTES.md`, which the
toolkit never writes. The same hash test is added to `_agents_md_move_target` /
`Get-AgentsMdMoveTarget`: a known shipped `AGENTS.md` is ours and is replaced, not kept.

Canonical hash, per installer:
- bash `_h_canonical_sha256 FILE`:
  `printf '%s' "$(LC_ALL=C sed $'1s/^\xef\xbb\xbf//' "$1" | tr -d '\r')" | _h_sha256`. Command
  substitution strips the trailing newlines. `_h_sha256` tries `sha256sum`, then `shasum -a 256`, then
  `openssl dgst -sha256 -r`, and takes the first field. If none exists, the hash is "unknown", which
  means "keep it" plus a note.
- PowerShell `Get-HCanonicalSha256 $path`: works on BYTES from `[IO.File]::ReadAllBytes`. It drops the
  BOM and every `13`, trims trailing `10`, and hashes with `[Security.Cryptography.SHA256]::Create()`.
  It never decodes, so invalid UTF-8 cannot change the answer.

Tests first. They go in `test_install_over_existing.py` next to the AGENTS.md block, and every one is
parametrised `installer in [sh, ps1]`:

```python
_V3_SHIPPED = "# CLAUDE.md -- as v3.3.1 shipped it\nrule one\n"


def _known(src, *texts, name="CLAUDE.md"):
    """Write the data file the way the generator does, hashing with PYTHON -- so every
    installer test below is also a three-implementation agreement test."""
    import hashlib
    def canon(b):
        b = b[3:] if b.startswith(b"\xef\xbb\xbf") else b
        return hashlib.sha256(b.replace(b"\r", b"").rstrip(b"\n")).hexdigest()
    (src / "scripts").mkdir(exist_ok=True)
    (src / "scripts" / "shipped-instruction-hashes.txt").write_text(
        "".join("%s  %s  vtest\n" % (canon(t.encode("utf-8")), name) for t in texts),
        encoding="utf-8")


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_a_PERSONALISED_claude_md_is_kept_as_X4_NOTES_pre_4_0(installer, tmp_path):
    src = _agent_source(tmp_path); _known(src, _V3_SHIPPED)
    dest = _fresh(tmp_path)
    mine = (_V3_SHIPPED + "my own rule\n").encode("utf-8")
    (dest / "CLAUDE.md").write_bytes(mine)
    r = _install(installer, tmp_path, dest, "--agent", "claude", source=src)
    assert r.returncode == 0, _ok(r)
    assert (dest / "X4-NOTES.pre-4.0.md").read_bytes() == mine, "the user's file was not kept BYTE-identical"
    assert (dest / "CLAUDE.md").read_bytes() == b"# CLAUDE.md -- shipped\n"
    assert "X4-NOTES.pre-4.0.md" in r.stdout and "X4-NOTES.md" in r.stdout, _ok(r)


@pytest.mark.parametrize("installer", ["sh", "ps1"])
@pytest.mark.parametrize("variant", ["lf", "crlf", "bom_crlf", "extra_trailing_newlines"])
def test_TWIN_an_UNEDITED_shipped_claude_md_is_replaced_not_kept(installer, variant, tmp_path):
    """One variant per canonicalisation clause: deleting any clause turns exactly one RED."""
    src = _agent_source(tmp_path); _known(src, _V3_SHIPPED)
    dest = _fresh(tmp_path)
    b = _V3_SHIPPED.encode("utf-8")
    b = {"lf": b, "crlf": b.replace(b"\n", b"\r\n"),
         "bom_crlf": b"\xef\xbb\xbf" + b.replace(b"\n", b"\r\n"),
         "extra_trailing_newlines": b + b"\n\n"}[variant]
    (dest / "CLAUDE.md").write_bytes(b)
    r = _install(installer, tmp_path, dest, "--agent", "claude", source=src)
    assert r.returncode == 0, _ok(r)
    assert not list(dest.glob("X4-NOTES.pre-4.0*")), "an unedited shipped file was kept as the user's"
    assert (dest / "CLAUDE.md").read_bytes() == b"# CLAUDE.md -- shipped\n"


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_TWIN_a_claude_md_equal_to_the_SOURCE_is_not_kept_even_with_no_list(installer, tmp_path):
    src = _agent_source(tmp_path)                   # no data file at all
    dest = _fresh(tmp_path)
    (dest / "CLAUDE.md").write_bytes(b"# CLAUDE.md -- shipped\r\n")
    r = _install(installer, tmp_path, dest, "--agent", "claude", source=src)
    assert r.returncode == 0, _ok(r)
    assert not list(dest.glob("X4-NOTES.pre-4.0*"))


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_with_NO_list_a_differing_claude_md_is_KEPT_and_the_run_SAYS_why(installer, tmp_path):
    src = _agent_source(tmp_path)
    dest = _fresh(tmp_path)
    (dest / "CLAUDE.md").write_bytes(_V3_SHIPPED.encode())
    r = _install(installer, tmp_path, dest, "--agent", "claude", source=src)
    assert r.returncode == 0, _ok(r)
    assert (dest / "X4-NOTES.pre-4.0.md").is_file()
    assert "shipped-instruction-hashes.txt" in r.stdout, "a narrowed decision must announce itself"


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_TWIN_a_codex_only_install_leaves_CLAUDE_md_ALONE(installer, tmp_path):
    src = _agent_source(tmp_path)
    dest = _fresh(tmp_path)
    (dest / "CLAUDE.md").write_bytes(b"mine\n")
    r = _install(installer, tmp_path, dest, "--agent", "codex", source=src)
    assert r.returncode == 0, _ok(r)
    assert (dest / "CLAUDE.md").read_bytes() == b"mine\n" and not list(dest.glob("X4-NOTES*"))


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_a_second_kept_CLAUDE_md_never_overwrites_the_first(installer, tmp_path):
    src = _agent_source(tmp_path)
    dest = _fresh(tmp_path)
    (dest / "X4-NOTES.pre-4.0.md").write_bytes(b"first\n")
    (dest / "CLAUDE.md").write_bytes(b"second\n")
    r = _install(installer, tmp_path, dest, "--agent", "claude", source=src)
    assert r.returncode == 0, _ok(r)
    assert (dest / "X4-NOTES.pre-4.0.md").read_bytes() == b"first\n"
    assert [p.read_bytes() for p in dest.glob("X4-NOTES.pre-4.0.*.md")] == [b"second\n"]


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_a_DRY_RUN_keeps_nothing_and_SAYS_what_it_would_keep(installer, tmp_path):
    src = _agent_source(tmp_path)
    dest = _fresh(tmp_path)
    (dest / "CLAUDE.md").write_bytes(b"mine\n")
    r = _install(installer, tmp_path, dest, "--agent", "claude", "--dry-run", source=src)
    assert r.returncode == 0, _ok(r)
    assert (dest / "CLAUDE.md").read_bytes() == b"mine\n" and not list(dest.glob("X4-NOTES*"))
    assert "X4-NOTES.pre-4.0.md" in r.stdout


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_a_KNOWN_shipped_AGENTS_md_is_replaced_not_moved_aside(installer, tmp_path):
    src = _agent_source(tmp_path)
    old = "# AGENTS.md as 4.0.0 shipped it\n"
    _known(src, old, name="AGENTS.md")
    dest = _fresh(tmp_path)
    (dest / "AGENTS.md").write_bytes(old.replace("\n", "\r\n").encode())
    r = _install(installer, tmp_path, dest, "--agent", "codex", source=src)
    assert r.returncode == 0, _ok(r)
    assert not list(dest.glob("AGENTS.pre-4.0*")), _ok(r)
```

The existing `test_a_USER_AGENTS_md_is_moved_aside_never_overwritten` remains the twin for the
unknown case. Mutations to run by hand after GREEN, one clause each, each predicted to turn exactly
the named test RED:
- drop `tr -d '\r'` -> `crlf`
- drop the BOM `sed` -> `bom_crlf`
- `printf '%s' "$(...)"` -> `cat` -> `extra_trailing_newlines`
- skip the list lookup -> `lf`
- skip the source comparison -> `..._equal_to_the_SOURCE...`

Do the same on the PowerShell side. Revert each mutation and clear any `__pycache__`.

Also in this task: the `require_direction` / `Assert-Direction` text at install.sh:1277-1279 and the
matching install.ps1 lines currently say an edited CLAUDE.md is "gone". After T2 that sentence is
false. Reword it to: "an edited CLAUDE.md or AGENTS.md is KEPT beside it (X4-NOTES.pre-4.0.md /
AGENTS.pre-4.0.md); your own KNOWLEDGEBASE.md and customised skills are replaced". The pinned phrase
`already an installation at the destination` (test at :1137) is unchanged.

- Functions touched. install.sh: `_agents_md_move_target`, `announce_copy_plan`, `require_direction`,
  the in-game and separate arms (one call line each), and new `_h_sha256`, `_h_canonical_sha256`,
  `_h_known_hash`, `_h_claude_md_move_target`, `preserve_user_claude_md`. install.ps1:
  `Get-AgentsMdMoveTarget`, `Show-CopyPlan`, `Assert-Direction`, the in-game and separate arms, and new
  `Get-HCanonicalSha256`, `Test-HKnownHash`, `Get-HClaudeMdMoveTarget`, `Save-HUserClaudeMd`. Also the
  `WHEN 4.0 SHIPS` comments in both, replaced by a pointer to the data file.
- Files: `install.sh`, `install.ps1`, `tools/x4validate/tests/test_install_over_existing.py`
- Run: `cd tools/x4validate && uv run pytest tests/test_install_over_existing.py -k "PERSONALISED or UNEDITED or equal_to_the_SOURCE or NO_list or codex_only_install_leaves_CLAUDE or second_kept_CLAUDE or keeps_nothing_and_SAYS or KNOWN_shipped_AGENTS or USER_AGENTS_md or AGENTS_md_identical" -q`
  Expected: `28 passed` on Windows (14 tests x 2 installers). RED first: the new tests fail with no
  `X4-NOTES.pre-4.0.md` and with an unedited CRLF file left in place.
- Commit: `installers: keep a personalised 3.x CLAUDE.md as X4-NOTES.pre-4.0.md, matched by canonical hash of every shipped version`

Confidence 86%. The weak link is BSD `sed` with a `$'\xef...'` pattern on macOS, where CI has no runner.
Raising it: run `printf '\xef\xbb\xbfa\r\n' > f; LC_ALL=C sed $'1s/^\xef\xbb\xbf//' f | od -c` under
Git Bash (GNU) now. macOS stays best effort, labelled UNMEASURED in the report; failure there only
over-keeps, it never overwrites.

---

## Task 3 -- `--agent auto`

Semantics:
- **Signals.** For claude: `claude` on the detect PATH, OR `dest/CLAUDE.md`, OR
  `dest/.claude/settings.json`. For codex: `codex` on the detect PATH, OR `dest/.codex/`. Never a bare
  `.claude/` (F5).
- **The PATH walk**, one explicit algorithm in both installers (F6): every entry of
  `${X4_INSTALL_DETECT_PATH:-$PATH}`. On Windows it checks `<n>`, `<n>.exe`, `<n>.cmd`, `<n>.bat` and
  `<n>.ps1` as regular files. On POSIX it checks `<n>` as a regular executable file. The name/extension
  list is one variable per installer, pinned equal by a test.
- **Results.** Detected = the union of signals; the selected agents are exactly those detected. Both
  found: both installed (claude + codex; codex's set already contains generic's). **None found: `all`
  (the documented default) plus a note** (see Q1).
- **Global.** `--method global` with auto behaves as `all` does there (Claude only, with the existing
  note).
- **The report** names each detection and its reason, e.g.
  `auto: claude (on PATH: /c/Users/x/.local/bin/claude.exe), codex (destination has .codex/)`.
- **When it resolves.** The destination is known only inside the arms, so auto resolves in
  `in-game`/`separate` right after `announce_target`, before any precheck reads `X4_ITEMS`. The items
  loop (install.sh:554-560, install.ps1:354-355) becomes `_h_resolve_items` / `Resolve-HItems`, called
  at the top for explicit agents and again after auto resolves.
- **Trap for the implementer:** a Windows-form seam value reaches Git Bash unconverted (`C:/x/y`), so
  splitting on `:` breaks it. On `OS=windows` with the seam set, convert it with `cygpath -u -p`
  first. The harness passes a single directory.

Tests first (`test_install_over_existing.py`, `installer in [sh, ps1]`). The fixture helper writes stub
executables into `tmp_path/agents-on-path`: an extensionless `#!/bin/sh` file with mode 755, plus a
`.cmd` copy on Windows.

```python
def _stub_agents(tmp_path, *names):
    d = tmp_path / "agents-on-path"; d.mkdir(exist_ok=True)
    for n in names:
        p = d / n; p.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8"); p.chmod(0o755)
        if os.name == "nt":
            (d / (n + ".cmd")).write_text("@exit /b 0\r\n", encoding="utf-8")
    return d


@pytest.mark.parametrize("installer", ["sh", "ps1"])
@pytest.mark.parametrize("on_path,present,absent", [
    (("codex",), ["AGENTS.md", ".codex/hooks.json"], ["CLAUDE.md", ".claude/settings.json"]),
    (("claude",), ["CLAUDE.md", ".claude/settings.json"], ["AGENTS.md", ".codex"]),
    (("claude", "codex"), ["CLAUDE.md", "AGENTS.md", ".codex/hooks.json"], []),
])
def test_auto_installs_exactly_the_agents_found_on_PATH(installer, on_path, present, absent, tmp_path):
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    r = _install(installer, tmp_path, dest, "--agent", "auto", source=src,
                 detect_path=_stub_agents(tmp_path, *on_path))
    assert r.returncode == 0, _ok(r)
    for rel in present: assert (dest / rel).exists(), rel + "\n" + _ok(r)
    for rel in absent: assert not (dest / rel).exists(), rel + "\n" + _ok(r)
    for n in on_path: assert "%s (on PATH" % n in r.stdout, _ok(r)


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_auto_with_NOTHING_found_installs_all_and_SAYS_so(installer, tmp_path):
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    r = _install(installer, tmp_path, dest, "--agent", "auto", source=src)   # harness PATH is empty
    assert r.returncode == 0, _ok(r)
    assert (dest / "CLAUDE.md").exists() and (dest / ".codex/hooks.json").exists()
    assert "no agent detected" in r.stdout, _ok(r)


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_auto_reads_a_CLAUDE_marker_in_the_destination(installer, tmp_path):
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    (dest / ".claude").mkdir(); (dest / ".claude" / "settings.json").write_text("{}\n")
    r = _install(installer, tmp_path, dest, "--agent", "auto", source=src)
    assert r.returncode == 0, _ok(r)
    assert (dest / "CLAUDE.md").exists() and not (dest / ".codex").exists(), _ok(r)
    assert "destination has .claude/settings.json" in r.stdout


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_TWIN_a_bare_dot_claude_dir_is_NOT_a_claude_signal(installer, tmp_path):
    """Every install makes .claude/ (x4-paths.env lives there) -- F5."""
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    (dest / ".claude").mkdir(); (dest / ".claude" / "x4-paths.env").write_text("X4_TOOLKIT=\n")
    (dest / ".codex").mkdir()
    r = _install(installer, tmp_path, dest, "--agent", "auto", source=src)
    assert r.returncode == 0, _ok(r)
    assert not (dest / "CLAUDE.md").exists() and (dest / ".codex/hooks.json").exists(), _ok(r)


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_TWIN_a_non_agent_file_on_PATH_is_not_detected(installer, tmp_path):
    d = _stub_agents(tmp_path, "claudette", "xcodex")          # near-miss names
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    r = _install(installer, tmp_path, dest, "--agent", "auto", source=src, detect_path=d)
    assert "no agent detected" in r.stdout, _ok(r)
```

Plus a static check in `test_installers_agree.py`:
`test_both_installers_detect_agents_with_the_SAME_names_extensions_and_markers` parses
`X4_AGENT_DETECT_*`, `X4_AGENT_MARK_*`, `X4_DETECT_EXTS` and their `$X4AgentDetect` / `$X4AgentMark` /
`$X4DetectExts` twins. The existing `test_an_unknown_or_unsupported_agent_REFUSES...` stays: `auto`
is not in its parameter list.

- Functions touched. install.sh: `usage`, the `case "$AGENT"` resolution block (adds `auto)`), the
  items loop extracted to `_h_resolve_items`, the in-game and separate arms (one call after
  `announce_target`), the global arm's `case "$AGENT"` (auto treated as all), `announce_copy_plan`
  (prints the detection), and new `_h_on_path`, `_h_detect_agents`, `resolve_auto_agents`.
  install.ps1: the `-Agent` validation block, the `$X4Items` build (moved to `Resolve-HItems`), the
  arms, `Show-CopyPlan`, and new `Test-HOnPath`, `Get-HDetectedAgents`, `Resolve-HAutoAgents`.
- Files: `install.sh`, `install.ps1`, both test files.
- Run: `cd tools/x4validate && uv run pytest tests/test_install_over_existing.py tests/test_installers_agree.py -k "auto or detect_agents" -q`
  Expected: `15 passed` (7 behavioural x 2 installers + 1 static). RED first: rc 2 `unknown --agent 'auto'`.
- Commit: `installers: --agent auto detects claude/codex on PATH and in the destination; nothing found installs all and says so`

Confidence 84%. The weak links are the seam path conversion under MSYS and the `.cmd`/extensionless
stub resolution. Raising it: before the implementation, run
`X4_INSTALL_DETECT_PATH='C:/tmp/x' bash -c 'echo "$X4_INSTALL_DETECT_PATH"; cygpath -u -p "$X4_INSTALL_DETECT_PATH"'`
in Git Bash and record whether MSYS already converts it.

---

## Task 4 -- set `X4_TOOLKIT` at OS user level; `--no-env`; report, never overwrite

**Windows (both installers): one mechanism, `scripts/x4-userenv.ps1`.**
- `get`: `[Environment]::GetEnvironmentVariable('X4_TOOLKIT','User')`, or with the seam set,
  `Get-ItemProperty -LiteralPath Registry::<key>`.
- `set <v>`: `[Environment]::SetEnvironmentVariable('X4_TOOLKIT',$v,'User')`, or with the seam, create
  the key if missing (`Test-Path` then `New-Item`, **never `New-Item -Force` on an existing key**) and
  `Set-ItemProperty`.
- install.ps1 calls it in-process (`& $script set $v`). install.sh on `OS=windows` calls
  `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$SRC/scripts/x4-userenv.ps1" set "$v"`,
  with the value passed as an argument after `cygpath -w`.
- **Why not `setx`:** it cannot be pointed at a test key, so its production path would be untestable.
  It also truncates at 1024 chars silently, and its broadcast behaviour would be a second mechanism to
  keep equal to install.ps1's. **Why not `reg add`:** it does not broadcast `WM_SETTINGCHANGE`, so new
  terminals started from Explorer would not see the value until the next logon.
  `SetEnvironmentVariable(...,'User')` writes `HKCU\Environment` and broadcasts. That is READ (.NET
  docs) for 5.1, and INFERRED for pwsh 7 / .NET Core. See M-H4.

**Value and comparison.**
- The value is written in native form: on Windows the absolute path with backslashes and no trailing
  separator; on POSIX `pwd -P`.
- "Same" means canonical equality. On Windows: separators unified, trailing separator stripped,
  compared case-insensitively. On POSIX: equal after `cd && pwd -P` when both exist, else equal as
  strings.

**Decision table** (one function, `_h_userenv_plan` / `Get-HUserEnvPlan`, read by both the dry-run
line and the writer):

| existing persisted value | action | output |
|---|---|---|
| none | set | `X4_TOOLKIT set for your user: <v> (new terminals only)` |
| same (canonical) | nothing | `X4_TOOLKIT already set to this toolkit` |
| different | **nothing** | `[WARNING] X4_TOOLKIT is set to <old>, not this toolkit <v>. Left unchanged. To point it here: <exact command>` (rc unaffected) |
| `--no-env` | nothing | the manual command (today's text) |
| write fails / no powershell.exe / profile not writable | nothing | added to `FAILED` (`X4_TOOLKIT (could not set: <why>; run: <cmd>)`), so the run reports INCOMPLETE |

**POSIX (`install.sh` only).**
- Persisted value = an `export X4_TOOLKIT=` line in the chosen profile file (inside or outside our
  block). A different value in the inherited process env also counts as "different".
- **The profile file, by `basename "$SHELL"`:**
  - `zsh`: `${ZDOTDIR:-$HOME}/.zshenv`. zsh reads it for every shell, interactive or not, so a
    `claude` or `codex` started from any zsh inherits it.
  - `bash` on macOS: `~/.bash_profile`. Terminal.app opens login shells, which do not read `.bashrc`.
  - `bash` elsewhere: `~/.bashrc`. Linux terminal emulators start interactive non-login shells, and
    Debian/Ubuntu `~/.profile` sources `.bashrc` for login shells.
  - anything else (fish, ksh, unset): no write, plus a note with the manual line. This is not a
    failure; we do not edit configs whose syntax we do not own. fish would need `set -Ux`.
- **The block:**
  ```
  # >>> X4 toolkit: X4_TOOLKIT (written by install.sh; delete this block to undo) >>>
  export X4_TOOLKIT='<v>'
  # <<< X4 toolkit <<<
  ```
  It is appended with a leading newline, and written temp-then-`mv` only when the file did not
  already hold an X4_TOOLKIT line. A value containing `'` or a newline is not written (FAILED, with
  the manual line).
- `install.ps1` on non-Windows: no write, plus a note: "install.ps1 sets X4_TOOLKIT only on Windows;
  use install.sh on Linux/macOS".

**Placement.** One call after the dispatch `esac` / switch `}`, before setup.sh, so no arm is touched:
`[ "$NO_ENV" = 1 ] || set_user_toolkit_env "$TOOLKIT"`. Dry-run never reaches it, because every arm
exits in a writer first. The setter still calls `refuse_if_dry_run` first, per the one-gate rule. The
dry-run preview line goes in `announce_copy_plan` from the same plan function. The trailing
`IMPORTANT -- set X4_TOOLKIT` block (install.sh:1619-1625, install.ps1:1554-1557) becomes the
result-dependent text from the table. README says a re-run with no `--toolkit` now targets the folder
`X4_TOOLKIT` names (F8).

Tests first. Registry tests are `installer in [sh, ps1]` and skip unless `os.name == "nt"`. Profile
tests are sh-only and skip on `nt`.

```python
def _reg_get(key):
    r = subprocess.run(["reg", "query", key, "/v", "X4_TOOLKIT"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return r.stdout.split("REG_SZ", 1)[1].strip()


@pytest.mark.skipif(os.name != "nt", reason="user environment lives in the registry on Windows only")
@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_an_UNSET_user_X4_TOOLKIT_is_set_to_this_toolkit_in_native_form(installer, tmp_path, regkey):
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    r = _install(installer, tmp_path, dest, source=src, env_write=True, regkey=regkey)
    assert r.returncode == 0, _ok(r)
    assert _reg_get(regkey) == str(dest.resolve()), _ok(r)          # backslashes, no trailing sep


@pytest.mark.skipif(os.name != "nt", reason="registry")
@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_a_DIFFERENT_existing_value_is_REPORTED_and_LEFT(installer, tmp_path, regkey):
    subprocess.run(["reg", "add", regkey, "/v", "X4_TOOLKIT", "/d", r"D:\elsewhere", "/f"], check=True,
                   capture_output=True)
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    r = _install(installer, tmp_path, dest, source=src, env_write=True, regkey=regkey)
    assert r.returncode == 0, _ok(r)
    assert _reg_get(regkey) == r"D:\elsewhere"
    assert r"D:\elsewhere" in r.stdout and "Left unchanged" in r.stdout, _ok(r)


@pytest.mark.skipif(os.name != "nt", reason="registry")
@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_TWIN_the_SAME_value_spelled_differently_is_not_different(installer, tmp_path, regkey):
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    spelled = dest.resolve().as_posix().upper() + "/"              # C:/.../TOOLKIT/
    subprocess.run(["reg", "add", regkey, "/v", "X4_TOOLKIT", "/d", spelled, "/f"], check=True,
                   capture_output=True)
    r = _install(installer, tmp_path, dest, source=src, env_write=True, regkey=regkey)
    assert _reg_get(regkey) == spelled and "already set" in r.stdout, _ok(r)
    assert "WARNING" not in r.stdout


@pytest.mark.skipif(os.name != "nt", reason="registry")
@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_TWIN_no_env_writes_NOTHING_and_prints_the_manual_command(installer, tmp_path, regkey):
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    r = _install(installer, tmp_path, dest, source=src, env_write=False, regkey=regkey)
    assert r.returncode == 0 and _reg_get(regkey) is None, _ok(r)
    assert "X4_TOOLKIT" in r.stdout and ("--no-env" in r.stdout or "-NoEnv" in r.stdout), _ok(r)


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell profile")
@pytest.mark.parametrize("shell,rel", [("/bin/zsh", "zdot/.zshenv"), ("/bin/bash", ".bashrc")])
def test_POSIX_writes_ONE_marked_block_to_the_shells_profile_and_is_idempotent(shell, rel, tmp_path):
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    for _ in range(2):
        r = _install("sh", tmp_path, dest, source=src, env_write=True, shell=shell)
        assert r.returncode == 0, _ok(r)
    body = (tmp_path / rel).read_text(encoding="utf-8")
    assert body.count(">>> X4 toolkit") == 1 and "export X4_TOOLKIT='%s'" % dest.resolve() in body


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell profile")
def test_POSIX_an_existing_DIFFERENT_export_is_LEFT_and_reported(tmp_path):
    (tmp_path / ".bashrc").write_text("export X4_TOOLKIT=/opt/other\n", encoding="utf-8")
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    r = _install("sh", tmp_path, dest, source=src, env_write=True, shell="/bin/bash")
    assert (tmp_path / ".bashrc").read_text() == "export X4_TOOLKIT=/opt/other\n"
    assert "/opt/other" in r.stdout and "Left unchanged" in r.stdout


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell profile")
def test_POSIX_an_UNKNOWN_shell_gets_NO_file_and_a_manual_line(tmp_path):
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    r = _install("sh", tmp_path, dest, source=src, env_write=True, shell="/usr/bin/fish")
    assert r.returncode == 0 and not (tmp_path / ".config/fish").exists(), _ok(r)
    assert "export X4_TOOLKIT" in r.stdout or "set -Ux X4_TOOLKIT" in r.stdout
```

Plus:
- A direct unit test of `scripts/x4-userenv.ps1`, Windows-only: `get` on an empty seam key prints
  nothing with rc 0; `set` then `get` round-trips a path with spaces and an `&`; `set` on an existing
  key keeps a sibling value (the `New-Item -Force` trap).
- A static agreement test: both installers name `scripts/x4-userenv.ps1`, the flag pair
  `--no-env`/`-NoEnv`, and the same seam names.
- `regkey` fixture: `HKCU\Software\X4ToolkitTests\<uuid>`, deleted in teardown, and teardown asserts
  the delete succeeded.

Functions touched. install.sh: `usage`, the arg parse loop (`--no-env`), new `_h_native_path`,
`_h_same_path`, `_h_win_userenv`, `_h_profile_file`, `_h_userenv_plan`, `set_user_toolkit_env`,
`announce_copy_plan`, the post-`esac` call, and the summary block :1619-1625. install.ps1: `param()`
(`[switch]$NoEnv`), new `Get-HUserEnvPlan`, `Set-HUserToolkitEnv`, `Show-CopyPlan`, the post-switch
call, and the summary :1554-1557. New `scripts/x4-userenv.ps1`.

- Files: `install.sh`, `install.ps1`, `scripts/x4-userenv.ps1` (new), both test files.
- Run (Windows): `cd tools/x4validate && uv run pytest tests/test_install_over_existing.py tests/test_installers_agree.py -k "X4_TOOLKIT or no_env or userenv or spelled_differently or DIFFERENT_existing" -q`
  Expected: `9 passed, 3 skipped` (4 registry tests x 2 + 1 static pass; the POSIX tests skip, and the
  userenv unit test counts among the passes). Read the `-rs` reasons: every skip must say "POSIX shell
  profile". On Linux CI the counts invert.
- Commit: `installers: set X4_TOOLKIT for the user (registry on Windows, a marked shell-profile block on POSIX); --no-env; a different value is reported, never overwritten`

Confidence 76%. The links, cheapest measurement first:
- M-H4a: does `SetEnvironmentVariable(...,'User')` from **powershell.exe 5.1 launched by Git Bash**
  land in HKCU with the exact bytes? (see Q2)
- M-H4b: is `.zshenv` the right zsh file? READ from the zsh manual (startup files); no machine needed.
- M-H4c: run `reg query` on a value containing `&` and spaces via the seam key, to prove the argument
  quoting through `powershell.exe -File` from Git Bash.
- M-H4d: the skip-ceiling delta, counted from the real run (T7).

---

## Task 5 -- Codex `project_doc_max_bytes`: opt-in `--codex-doc-max-bytes N`

**Decision: build it now, opt-in, no default value written.** The functional reason is measured.
Codex's 32,768-byte budget is SHARED across the root and nested `AGENTS.md` (M-A2), and the toolkit's
file leaves 4,256 B (F4). Any `AGENTS.md` the user keeps lower in the tree, such as a `dev/` repo's,
silently cuts the tail of ours, and the tail carries the Codex addendum. The generator gate protects
only the shipped file, not the chain. Lanes G and L may also grow `AGENTS.md`. This is spec §8 text,
and the cost is small.

Behaviour:
- `N` must be an integer between 32768 and 1048576, else rc 2 before any write.
- It requires the Codex target, or rc 2: "it configures Codex; this install does not select Codex".
  `--method global` also refuses with rc 2.
- It writes `<dest>/.codex/config.toml`:
  - absent: create it with `project_doc_max_bytes = N  # X4 toolkit installer (--codex-doc-max-bytes)`;
  - present without the key: insert that line as line 1, since root keys must precede any `[table]`;
    the rest is kept byte-for-byte;
  - present with the same value: untouched;
  - present with a different value: left, and reported with both values;
  - read-only and needing a change: refuse up front (`precheck_codex_doc_max_bytes`, beside
    `precheck_codex_hooks_json`), naming the x4lock unlock.
- `.codex/config.toml` joins `X4_KEEP_LOCAL` / `$X4KeepLocal`, so it never travels and is never pruned.
- The summary adds: "takes effect once you trust this folder in Codex". That a project config needs
  trust is INFERRED from the Codex trust model; the spike measured the cap raise in a trusted project.

Tests first (`installer in [sh, ps1]`):

```python
@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_codex_doc_max_bytes_writes_a_ROOT_key_and_keeps_existing_tables(installer, tmp_path):
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    (dest / ".codex").mkdir()
    (dest / ".codex" / "config.toml").write_bytes(b'[profiles.x]\nmodel = "m"\n')
    r = _install(installer, tmp_path, dest, "--agent", "codex", "--codex-doc-max-bytes", "65536", source=src)
    assert r.returncode == 0, _ok(r)
    lines = (dest / ".codex" / "config.toml").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("project_doc_max_bytes = 65536"), lines
    assert lines[1:] == ['[profiles.x]', 'model = "m"'], lines


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_TWIN_without_the_flag_no_codex_config_is_written(installer, tmp_path):
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    r = _install(installer, tmp_path, dest, "--agent", "codex", source=src)
    assert r.returncode == 0 and not (dest / ".codex" / "config.toml").exists(), _ok(r)


@pytest.mark.parametrize("installer", ["sh", "ps1"])
def test_a_DIFFERENT_existing_cap_is_LEFT_and_reported(installer, tmp_path):
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    (dest / ".codex").mkdir(); (dest / ".codex" / "config.toml").write_bytes(b"project_doc_max_bytes = 40000\n")
    r = _install(installer, tmp_path, dest, "--agent", "codex", "--codex-doc-max-bytes", "65536", source=src)
    assert (dest / ".codex" / "config.toml").read_bytes() == b"project_doc_max_bytes = 40000\n"
    assert "40000" in r.stdout and "65536" in r.stdout, _ok(r)


@pytest.mark.parametrize("installer", ["sh", "ps1"])
@pytest.mark.parametrize("agent,value", [("claude", "65536"), ("codex", "abc"), ("codex", "1000")])
def test_an_unusable_codex_doc_max_bytes_REFUSES_before_writing(installer, agent, value, tmp_path):
    src = _agent_source(tmp_path); dest = _fresh(tmp_path)
    r = _install(installer, tmp_path, dest, "--agent", agent, "--codex-doc-max-bytes", value, source=src)
    assert r.returncode == 2 and not any(dest.iterdir()), _ok(r)
```

Plus a static agreement test: `.codex/config.toml` is in both keep-local lists, and both installers use
the same bounds.

- Functions touched. install.sh: `usage`, the arg parse loop, `X4_KEEP_LOCAL`, the in-game and separate
  arms (one precheck line each), the post-`esac` call (guarded `METHOD != global`), the summary, and new
  `precheck_codex_doc_max_bytes`, `write_codex_doc_max_bytes`. install.ps1: `param()`, `$X4KeepLocal`,
  the arms, the post-switch call, the summary, and new `Test-HCodexDocCapPrecheck`,
  `Write-HCodexDocCap`. The value check runs at the agent-resolution point, before any write.
- Run: `cd tools/x4validate && uv run pytest tests/test_install_over_existing.py tests/test_installers_agree.py -k "codex_doc_max_bytes or doc_max" -q`
  Expected: `13 passed` (6 behavioural x 2 + 1 static). RED first: `unknown option`.
- Commit: `installers: --codex-doc-max-bytes N writes project_doc_max_bytes into the project .codex/config.toml (opt-in; never overwrites a different value)`

Confidence 88%. Open link: whether Codex reads a project `.codex/config.toml` before trust. That does not
change what we write, only the wording, which is already hedged.

---

## Task 6 -- user-facing text

- `install.sh` `usage()` and the install.ps1 header: document `auto`, `--no-env`/`-NoEnv` and
  `--codex-doc-max-bytes`/`-CodexDocMaxBytes`, and the seam variables as "test-only".
- README installer section: the three flags; the X4_TOOLKIT behaviour table (set / already / different
  -> left / --no-env); which profile file per shell; that a later re-run with no `--toolkit` targets
  `$X4_TOOLKIT` (F8); the 3.x migration (`X4-NOTES.pre-4.0.md`, and moving your notes into
  `X4-NOTES.md`); and the Codex cap opt-in with its reason (shared chain budget, MEASURED).
- CHANGELOG `## Unreleased`: one bullet per behaviour. Keep claims to what the tests pin; the macOS
  `bash`/`sed` paths are labelled "not measured".
- `release-review` / `releasing` note: after tagging, run `gen-shipped-hashes.py --write` and commit.
  The coverage test enforces it. This is only a pointer line in the CHANGELOG maintainer notes; the
  skill files are not edited here.
- Files: `install.sh` (usage only), `install.ps1` (header only), `README.md`, `CHANGELOG.md`
- Run: `cd tools/x4validate && uv run pytest tests/test_installer_literal_paths.py tests/test_installer_recovery_command_works.py tests/test_installers_agree.py -q`
  Expected: all pass (these pin installer text literals).
- Commit: `docs(installers): auto, --no-env, --codex-doc-max-bytes and the 3.x CLAUDE.md migration`

Confidence 95%.

---

## Task 7 -- CI: tags for the coverage test; skip ceilings

- `.github/workflows/ci.yml`: the `tests` job checkout (:99) gains `with: fetch-depth: 0`. Without it
  the coverage test FAILS in CI by design (T1), rather than skipping silently.
- `X4_MAX_SKIPS` (:619): add exactly the new skips counted from T4's real run on each OS. My prediction:
  Windows +4 (the POSIX profile tests: 2 parametrised + 2), ubuntu +9 (4 registry tests x 2 installers
  + the userenv unit test). Each added skip is named in the comment beside the number, in the existing
  convention. The early `ci/` branch run (Plan 3 step 0) is the measurement; change the numbers only
  from that, never from the prediction.
- Files: `.github/workflows/ci.yml`. Lane J also edits it (comment :47-50); the hunks are disjoint.
- Run: `python -c "import yaml,sys;yaml.safe_load(open('.github/workflows/ci.yml'))"`. Expected: no
  output, rc 0.
- Commit: `ci: full history in the tests job (the shipped-hash coverage test needs tags); skip ceilings for the platform-only installer env tests`

Confidence 80%: the skip counts are predictions. They are raised by the `ci/` branch run, read per job.

---

## Files touched (union)

- `install.sh`
- `install.ps1`
- `scripts/shipped-instruction-hashes.txt` (new)
- `scripts/x4-userenv.ps1` (new)
- `tools/x4validate/scripts/gen-shipped-hashes.py` (new)
- `tools/x4validate/tests/test_shipped_instruction_hashes.py` (new)
- `tools/x4validate/tests/test_install_over_existing.py`
- `tools/x4validate/tests/test_installers_agree.py`
- `README.md`
- `CHANGELOG.md`
- `.github/workflows/ci.yml`

Not touched: `agent/`, generated trees, `x4guard.py`, hooks, `_x4-env.sh`, `_paths.py`, `x4doctor.py`,
`write_paths_env` / `Write-PathsEnv`, the `Config:` summary line.

## Verify-hook-tests anchors touched

None. `scripts/verify-hook-tests.py` names no installer (F10).

## Cross-lane dependencies

- **L (merges before H):** both edit the `case "$AGENT"` block (install.sh:540-550) and the
  install.ps1 `-Agent` validation (:342-351). L also changes `test_an_unknown_or_unsupported_agent_REFUSES`
  (opencode stops refusing). H rebases and adds `auto)` beside L's arm. If L's opencode rows exist at
  rebase time, H adds `X4_AGENT_DETECT_opencode` / `X4_AGENT_MARK_opencode` from L's plan and one auto
  test row.
- **I (after H):** I moves `x4-paths.env` and rewrites `write_paths_env` and the `Config:` line. H's
  summary hunk is adjacent, so expect one trivial conflict. I's precedence matrix must not treat the
  OS-level `X4_TOOLKIT` H now sets as a config source. It is the pointer TO the config, so state this
  in I's brief.
- **J:** ci.yml, disjoint hunks (J :47-50, H :99 and :619). Both edit the README installer section and
  CHANGELOG Unreleased: append-only, expect textual merges.
- **Release (Wave 3):** cold-clone and red-team installs should pass `--no-env`. On this machine the
  different-value rule already protects the real value, because `X4_TOOLKIT` is set, but a scratch
  install should not depend on that.
- **Suggestion for whoever owns x4doctor (not H):** report the Codex `AGENTS.md` chain size against
  `project_doc_max_bytes`. Not built here, to keep this lane's files disjoint.

## Questions for the user

1. **`--agent auto` when NO agent is detected.** Options: install `all` (the documented default; inert
   files are harmless) / install `generic` only / refuse with rc 2. **Recommendation: `all` plus a note.**
   `generic` would leave a later Claude or Codex user with no guards, and refusing makes `auto` unusable
   in a fresh unattended setup.
2. **A one-off live probe of the production Windows write path** with a throwaway name. Set
   `X4_LANEH_PROBE` in the REAL HKCU via `scripts/x4-userenv.ps1` (from Git Bash -> powershell.exe 5.1
   and from pwsh 7), read it back from a fresh process, then delete it. Your real `X4_TOOLKIT` is never
   touched. **Recommendation: yes.** Without it, the production `[Environment]` call is covered only by
   READ docs; every test uses the seam key.
3. **Which versions count as "shipped".** Options: release tags only (23 tags -> 10 hashes, per spec) /
   also every historical `CLAUDE.md` blob on master (42 commits). **Recommendation: tags only.** A user
   who installed from an untagged commit gets their unedited file kept as `X4-NOTES.pre-4.0.md`, which
   loses nothing. All-history would also bless intermediate states nobody released.

## Confidence

| Task | % | Measurement that raises it (if < 90) |
|---|---|---|
| T0 harness | 92 | -- |
| T1 hash list | 93 | -- |
| T2 migration | 86 | GNU `sed $'\xef..'` BOM probe under Git Bash now; macOS labelled UNMEASURED (only over-keeps) |
| T3 auto | 84 | MSYS conversion of `X4_INSTALL_DETECT_PATH` (one Git Bash command); stub `.cmd` vs extensionless resolution under both walks |
| T4 env | 76 (**lowest**) | Q2 live probe; zsh startup-file READ; `&`/space quoting through `powershell.exe -File` via the seam key |
| T5 codex cap | 88 | none blocking (trust-before-load affects only wording) |
| T6 docs | 95 | -- |
| T7 CI | 80 | the `ci/` branch run's real skip counts, read per job |

## Gate plan (focused only; the orchestrator runs the one full gate per wave)

1. `cd tools/x4validate && uv run pytest tests/test_shipped_instruction_hashes.py -q`, expecting `4 passed`.
2. `uv run python scripts/gen-shipped-hashes.py --check`, expecting rc 0.
3. `bash -n ../../install.sh`, expecting rc 0. Then
   `pwsh -NoProfile -Command "$null=[System.Management.Automation.Language.Parser]::ParseFile('../../install.ps1',[ref]$null,[ref]$e); $e.Count"`,
   expecting `0`.
4. `uv run pytest tests/test_installers_agree.py tests/test_installer_literal_paths.py tests/test_installer_recovery_command_works.py -q`,
   expecting all pass.
5. The per-task `-k` selections above, each RED first, then GREEN.
6. Once, at the end, in the background: `uv run pytest tests/test_install_over_existing.py -q -rs`.
   Expected: 0 failed. Every skip reason is either "no Git Bash" / "no PowerShell" (pre-existing) or the
   platform reasons named in T4.
7. Hand mutations from T2 (one clause each), each predicted to turn exactly the named test RED. Revert
   each and re-run step 5.
8. `git status` shows only the union files above. Confirm with a `reg query HKCU\Software\X4ToolkitTests`
   = "unable to find" after the session-teardown fixture.

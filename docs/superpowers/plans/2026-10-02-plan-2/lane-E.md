# Universal Agent Support — Plan 2, Lane E: x4guard hardening + generator minors

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each task is test-first: write the test, run it, WATCH IT FAIL for the predicted reason, then implement.

**Goal:** Make `x4guard check` keep its promise under every failure shape it can meet on a real machine — a hung guard is bounded and its whole process tree dies, one time budget covers a whole check, every inert verdict names *why*, and a delete keeps every guard's advisory — and make `gen-agent-trees.py` refuse (rc 2, `REFUSING:`) on every malformed `agent/` source instead of either crashing (rc 1, traceback) or silently emitting a broken/escaped file.

**Architecture:** Two files of source, two test files. `agent/guards/claude-hooks/x4guard.py` gains `_run_bounded()` (Popen + bounded drain + `_kill_tree()`), a shared deadline threaded through `run_guard()`, a validated `X4_GUARD_TIMEOUT_S`, a richer inert cause, a `rm -rf --` delete probe and merged contexts. `tools/x4validate/scripts/gen-agent-trees.py` gains agent.yaml validation, YAML-safe description emission, a duplicate-name check, and conversion of every decode/parse/frontmatter failure into `GenerationError`. The generated copy `.claude/hooks/x4guard.py` is never hand-edited: edit `agent/`, regenerate.

**Tech stack:** Python 3.13 via uv for tests and the generator (`tools/x4validate`); x4guard stays **stdlib-only and Python ≥ 3.10** (it ships in `.claude/hooks/`); Git Bash on Windows.

**Repo:** `$X4_TOOLKIT` (`$X4_TOOLKIT`), branch `master` (or the lane worktree/branch the orchestrator assigns — CLAUDE.md "one worktree per session"). `PKG` = `tools/x4validate`. Focused test command form: `cd tools/x4validate && uv run --frozen python -m pytest -q -rs tests/<file>::<test>`.

---

## Context — what was measured while planning (2026-10-02)

All measurement scripts and raw output are in the session scratchpad `plan2/laneE_*.py|.out`. Nothing in the repo was written.

| # | Finding | Tier |
|---|---|---|
| M0 | Mechanism of item 1: `subprocess.run(timeout=)` on Windows calls `process.kill()` then an **unbounded** `process.communicate()` to collect output; the reader threads block until every holder of the pipe closes it. A guard's grandchild inherits the pipes, so the call returns only when the grandchild exits. | READ (CPython 3.13.14 `subprocess.run` source) |
| M2 | Stub guard `sleep 8` with `X4_GUARD_TIMEOUT_S=2`: wall **10.9 s**; `exec sleep 8`: **9.2 s** (MSYS `exec` still leaves the Win32 child behind). Both inert. | MEASURED |
| M3 | Delete with BOTH guards hung (`exec sleep 8`, timeout 2): wall **17.6 s** — two budgets, each stretched by the grandchild. | MEASURED |
| S1 | Spike, 3 process shapes (bash→python, bash→exec python, bash→subshell→python), Popen + communicate(timeout=2): **kill-only** → drain never completes, grandchild **alive 3/3**; **`taskkill /F /T /PID <bash>` before `p.kill()`** → drained in 2.3–2.5 s, grandchild **dead 3/3**. | MEASURED (Windows only) |
| S2 | Precedent in-repo: `tools/x4validate/audit/driver.py:104-108` already kills a tree with `taskkill /PID … /T /F`. | READ |
| M1 | Delete probe form: `rm -f '<p>'` vs `rm -rf -- '<p>'` through protect-bash.sh over **9 paths** (reference/, reference/libraries, profile/save, a save file, dev/mymod, game root, extensions, Documents, an outside dir): **9/9 identical verdicts**. `_operands()` (`hook_facts.py:1510`) skips every unquoted `-` token, so flags never reach a rule. | MEASURED / READ |
| M4 | Stub guard prints an ask JSON with reason `WHY-IT-FAILED` then `exit 3`: inert reason is `protect-bash.sh exited 3. NOTHING was checked…` — the guard's reason is **dropped**. Guards print their ask JSON *before* `x4_guard_check_inert` exits 2 (`_x4-env.sh:531-546`), so the exit-2 path drops it too. | MEASURED / READ |
| M5 | `check --kind delete --path <tk>/dev/mymod/content.xml` → `decision: ask` from protect-bash, **`context: null`**, while `--kind write` on the same path gives `advise` with the manifest advisory. The protect-files advisory is **lost** on a delete. The ask reason echoes the probe command (`…confirm: rm -f '…'`). | MEASURED |
| M6 | `X4_GUARD_TIMEOUT_S=abc` → module-level `int()` raises at import: **traceback, rc 1, no JSON on stdout**. `=0` → inert deny "timed out after 0s" (fail-closed, but the cause does not name the setting). | MEASURED |
| G1 | gen-agent-trees on tmp copies of `agent/`, 11 malformed shapes. **Silently wrong output (generate() succeeds):** tools as a string → frontmatter `tools: G, l, o, b, ,, …`; `: ` in description → generated frontmatter **does not parse** (ScannerError); multi-line description → does not parse; duplicate names → **one agent silently dropped**; name `../../escaped` → output key `.claude/agents/../../escaped.md` (write mode would write **outside the repo's `.claude/`**); name `sub/dir` → nested file; name `123` (int) → `123.md`. **Uncaught (rc 1 traceback, not rc 2):** YAML syntax error (ParserError), SKILL.md frontmatter never closed (ValueError from `str.index`), non-UTF-8 SKILL.md and non-UTF-8 agent.yaml (UnicodeDecodeError). | MEASURED |
| G2 | Duplicate YAML key in agent.yaml raises `DuplicateKeyError`, a `ruamel.yaml.error.YAMLError` subclass, uncaught → rc 1. | MEASURED |
| G3 | YAML plain-scalar round-trip (`load("k: " + s) == {"k": s}`) is True for both real agent descriptions and False/error for `Note: x`, `a #c`, `- d`, `x\ny`, `"q"`, `[x]`; `json.dumps(s)` round-trips all of them. So "plain when it round-trips, else JSON-quoted" leaves today's generated agent files **byte-identical**. | MEASURED |
| G4 | `problems()` → `_norm()` decodes generated files as UTF-8 with no guard: a non-UTF-8 generated file crashes `--check` (same shape as G1's decode errors, found by searching for the shape). | READ |

**Not measured (ASSUMED, each has a measuring step below):** POSIX process-group kill (`start_new_session=True` + `os.killpg`) — only the ubuntu CI leg can show it, and that leg is `continue-on-error` (informational). Claude Code accepting a JSON-double-quoted `description:` in agent frontmatter (it is valid YAML; the source `agent.yaml` already quotes it).

**What the Codex session's superseded x4guard got wrong (do NOT port wholesale)** — READ, `git diff master session/framework-audit-pre-rebase-20261002 -- agent/guards/claude-hooks/x4guard.py`: it deletes the `NOT_CHECKED` regex, the `_deployed()`/`X4_TOOLKIT` refusal (I2), `os.path.abspath` (I1), the `X4_GUARD_TIMEOUT_S` override, and it short-circuits a delete on the first deny (dropping `protect-bash.sh` from `guards`, which `test_write_and_delete_into_reference_deny` pins). Port only its four ideas: shared deadline, guard reason in the "exited N" cause, `rm -rf --` probe, merged contexts.

## Global constraints

- `x4guard.py` stays stdlib-only and imports on Python 3.10 (no `match`, no 3.11+ APIs). `ctypes` is used only in TESTS.
- **Never edit `.claude/hooks/x4guard.py` directly.** Edit `agent/guards/claude-hooks/x4guard.py`, then `cd tools/x4validate && uv run --frozen python scripts/gen-agent-trees.py` (expect `wrote 1 of N file(s)`), then run tests — the tests execute the GENERATED copy (`test_x4guard_check.py:16`).
- Verdict JSON schema stays `v: 1` with the same keys. `X4_GUARD_TIMEOUT_S` keeps its name and 25 s default; its meaning changes from *per guard* to *per check* (documented in the docstring, CHANGELOG and spec §5.6).
- No new `pytest.skip` on either CI leg (`X4_MAX_SKIPS` 56 windows / 68 ubuntu, `ci.yml:602`). Every new test must run on both OSes. Never a bare `return` in a test.
- Every hand mutation (CLAUDE.md #26): apply, regenerate, run the named test, confirm RED for the predicted reason, revert, delete `agent/guards/claude-hooks/__pycache__` and `.claude/hooks/__pycache__`, regenerate, confirm GREEN. Record the table in the commit body.
- Write files as UTF-8/LF, encode first then `write_bytes` (the generator already does).
- Stage explicit paths only; never `git add -A`. One commit per task. Never push. Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- CLAUDE.md is at ~39,971 of 40,000 chars: this lane adds **nothing** to it or to `agent/instructions/core.md`.

## Interfaces

**Produces (x4guard.py — Lane B's Codex adapter and Lane C's x4doctor consume these):**
- CLI and JSON verdict: unchanged shape. New guarantees: (a) `check` returns within **`TIMEOUT_S + KILL_WAIT_S + DRAIN_GRACE_S`** seconds of wall clock plus interpreter start-up (defaults 25 + 5 + 3 = **33 s**), whatever the guards' descendants do; (b) no guard descendant survives a timeout (Windows MEASURED by S1; POSIX via process group, ASSUMED until CI); (c) an inert `reason` carries the guard's own reason or its stderr tail; (d) a delete's `context` joins every guard's advisory, in guard order, separated by a blank line.
- Module constants: `TIMEOUT_S: float | None`, `TIMEOUT_ERROR: str | None`, `KILL_WAIT_S = 5`, `DRAIN_GRACE_S = 3`. Functions: `verdict_for(...)` (unchanged signature), `run_guard(script, payload, deadline=None)`, `_run_bounded(argv, payload, env, timeout) -> (returncode | None, stdout, stderr)`, `_kill_tree(proc)`, `_clock()`.
- `X4_GUARD_TIMEOUT_S`: positive finite number of seconds (float allowed). Anything else → inert deny naming the variable and value, rc 0.

**Produces (gen-agent-trees.py — Lanes A/B/C consume when they add targets):**
- `agent.yaml` contract, enforced: `name` a string matching `^[a-z0-9][a-z0-9-]*$`, unique across `agent/agents/`; `description` a non-empty string (any content — emitted plain when YAML round-trips it, else JSON-quoted); `tier` in `TIER_MODEL`; `claude`, if present, a mapping; `claude.tools`, if present, a YAML **list** of non-empty strings with no `,` or newline.
- Every malformed source (non-UTF-8 file, YAML error incl. duplicate keys, frontmatter never closed) → `GenerationError` naming the file → `main()` rc 2 with `REFUSING:` on stderr. A non-UTF-8 *generated* file → `STALE`, never a crash.
- New helpers other lanes may reuse when they render frontmatter: `_yaml_scalar(s: str) -> str`, `_load_yaml(p: Path) -> object`.

**Consumes:** nothing from other lanes. Baseline is master `cde1ebe` (READ 2026-10-02).

---

## Task E1: A timeout is bounded and kills the guard's whole process tree

**Files:**
- Modify: `agent/guards/claude-hooks/x4guard.py`
- Modify (generated): `.claude/hooks/x4guard.py`
- Modify: `tools/x4validate/tests/test_x4guard_check.py`

- [ ] **Step 1: Write the failing tests.** Add these helpers and two tests to `test_x4guard_check.py` (imports at the top: `import ctypes`, `import importlib.util`, `import signal`, `import time`; `ctypes` is stdlib on both OSes, `ctypes.windll` is only touched under `os.name == "nt"`).

```python
# ---------------------------------------------------------------- lane E (Plan 2) helpers

def _alive(pid: int) -> bool:
    """Is this PID a live process? Windows: STILL_ACTIVE exit code. POSIX: kill(pid, 0)."""
    if os.name == "nt":
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return code.value == 259                           # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_dead(pid: int, within: float = 5.0) -> bool:
    end = time.monotonic() + within
    while _alive(pid) and time.monotonic() < end:
        time.sleep(0.2)
    return not _alive(pid)


def _reap(pid: int | None) -> None:
    if pid and _alive(pid):
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGKILL)


def _stub_hooks(tmp_path, bodies: dict) -> Path:
    """A deployed-looking .claude/hooks holding this x4guard.py and the given stub guards."""
    hooks = tmp_path / "stub" / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy2(X4GUARD, hooks / "x4guard.py")
    for name, body in bodies.items():
        (hooks / name).write_bytes(body.encode("utf-8"))
    return hooks


def _grandchild(pidfile: Path, seconds: int = 60) -> str:
    """A guard whose CHILD inherits the pipes, records its own PID, and outlives any budget."""
    py = Path(sys.executable).as_posix()
    return (f"cat >/dev/null\n'{py}' -c \"import os,time;open(r'{pidfile.as_posix()}','w')"
            f".write(str(os.getpid()));time.sleep({seconds})\"\n")


def _load(script: Path):
    spec = importlib.util.spec_from_file_location(f"x4guard_under_test_{abs(hash(str(script)))}", script)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_E1_a_timeout_is_bounded_and_kills_the_guards_descendants(sandbox, tmp_path):
    """MEASURED 2026-10-02: a guard's grandchild held the pipes and subprocess.run(timeout=)
    waited for it (sleep 8 under a 2 s budget took 10.9 s). The grandchild here sleeps 60 s."""
    _, tk, env = sandbox
    pidfile = tmp_path / "grandchild.pid"
    hooks = _stub_hooks(tmp_path, {"protect-bash.sh": _grandchild(pidfile)})
    t0 = time.monotonic()
    v = _check_in(dict(env, X4_GUARD_TIMEOUT_S="3"), tk, "--kind", "shell", "--shell", "bash",
                  "--command", "echo hi", script=hooks / "x4guard.py")
    wall = time.monotonic() - t0
    assert pidfile.exists(), "the grandchild never started -- this test proved nothing"
    pid = int(pidfile.read_text())
    try:
        assert v["decision"] == "deny" and v["inert"] and "timed out" in v["reason"], v
        assert wall < 20, f"{wall:.1f}s: a 3 s budget did not bound the check"
        assert _wait_dead(pid), "the guard's grandchild survived the timeout"
    finally:
        _reap(pid)


def test_E1_TWIN_the_bound_holds_even_when_the_tree_kill_does_not(sandbox, tmp_path, monkeypatch):
    """Twin for the DRAIN clause: with the tree kill reduced to killing the root only, the
    grandchild keeps the pipes open -- and the check must STILL return on time."""
    _, tk, env = sandbox
    pidfile = tmp_path / "grandchild.pid"
    hooks = _stub_hooks(tmp_path, {"protect-bash.sh": _grandchild(pidfile)})
    for k, val in env.items():
        monkeypatch.setenv(k, val)
    g = _load(hooks / "x4guard.py")
    monkeypatch.setattr(g, "TIMEOUT_S", 3.0)
    monkeypatch.setattr(g, "_kill_tree", lambda proc: proc.kill())
    t0 = time.monotonic()
    v = g.verdict_for("shell", "bash", "echo hi", None)
    wall = time.monotonic() - t0
    pid = int(pidfile.read_text()) if pidfile.exists() else None
    try:
        assert pid, "the grandchild never started -- this test proved nothing"
        assert v["decision"] == "deny" and v["inert"], v
        assert wall < 3 + g.DRAIN_GRACE_S + 6, f"{wall:.1f}s: the drain is not bounded"
        assert _alive(pid), "control: the tree kill was meant to be OFF here"
    finally:
        _reap(pid)
```

- [ ] **Step 2: Run and watch both fail.**
  `cd tools/x4validate && uv run --frozen python -m pytest -q -rs tests/test_x4guard_check.py -k E1`
  Expected: `test_E1_a_timeout…` FAILS on `wall < 20` (~60 s, the grandchild's sleep). `test_E1_TWIN…` ERRORS/FAILS with `AttributeError: … has no attribute 'DRAIN_GRACE_S'` (or `_kill_tree`), since monkeypatch.setattr requires the attribute. ⚠ If the first test instead fails on `pidfile.exists()`, the stub never started — fix the fixture before going on.

- [ ] **Step 3: Implement** in `agent/guards/claude-hooks/x4guard.py`. Add `import signal`, `import time`. Add after `RANK`:

```python
#: After a timeout: how long taskkill may take, and how long to wait for the pipes to close once
#: the tree is dead. A check's wall clock is bounded by TIMEOUT_S + KILL_WAIT_S + DRAIN_GRACE_S
#: even if the kill fails, because the drain is never unbounded.
KILL_WAIT_S = 5
DRAIN_GRACE_S = 3
_TASKKILL = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "taskkill.exe")


def _clock() -> float:
    return time.monotonic()


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the guard AND its descendants. On Windows a killed bash.exe leaves its children
    running and holding the pipes (MEASURED 2026-10-02, 3 of 3 process shapes), so the tree is
    killed while the root is still known: taskkill /T walks parent PIDs from it. The PID cannot
    be reused meanwhile -- Popen holds a handle to the process. On POSIX the guard leads its own
    process group (start_new_session), so killpg reaches every descendant that did not leave it."""
    if os.name == "nt":
        try:
            subprocess.run([_TASKKILL, "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=KILL_WAIT_S)
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _run_bounded(argv: list, payload: bytes, env: dict, timeout: float):
    """(returncode, stdout, stderr), or (None, b"", b"") on timeout. Never `subprocess.run`:
    on Windows its timeout path ends in an UNBOUNDED communicate() that waits for every pipe
    holder, so a guard's grandchild stretched a 2 s budget to 10.9 s (MEASURED)."""
    extra = {} if os.name == "nt" else {"start_new_session": True}
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, **extra)
    try:
        out, err = proc.communicate(payload, timeout=timeout)
        return proc.returncode, out, err
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            proc.communicate(timeout=DRAIN_GRACE_S)
        except subprocess.TimeoutExpired:
            pass        # abandon: the reader threads are daemons and die with this process
        return None, b"", b""
```

  Replace the `subprocess.run(...)` block in `run_guard` with:

```python
    try:
        rc, out, err = _run_bounded([bash, str(target)], json.dumps(payload).encode("utf-8"),
                                    dict(os.environ, X4_GUARD_CHECK="1"), TIMEOUT_S)
    except OSError as e:
        return _inert(f"{script} could not start: {e}", guards)
    if rc is None:
        return _inert(f"{script} timed out after {TIMEOUT_S}s", guards)
```
  and use `rc`/`out` where the code read `r.returncode`/`r.stdout`. Do not use `with Popen(...)`: its `__exit__` waits.

- [ ] **Step 4: Regenerate and run.** `uv run --frozen python scripts/gen-agent-trees.py` → Expected: `wrote 1 of … file(s)`. Then `uv run --frozen python -m pytest -q -rs tests/test_x4guard_check.py` → Expected: all pass, 0 new skips; `test_I5…[sleep 6]` now finishes in ≈ 2–3 s instead of ≈ 6 s.
- [ ] **Step 5: Mutation twins (by hand):**

  | Mutant in `x4guard.py` | Must turn red |
  |---|---|
  | `_kill_tree` body → `proc.kill()` only | `test_E1_a_timeout…` on `_wait_dead` (Windows: grandchild alive) |
  | drain `proc.communicate(timeout=DRAIN_GRACE_S)` → `proc.communicate()` | `test_E1_TWIN…` on the wall bound (~60 s) |
  | taskkill issued AFTER `proc.kill()` (swap order) | `test_E1_a_timeout…` — PREDICTION: red on Windows (the root is gone before the tree walk). If it stays green, record that taskkill /T still found the orphans and drop the ordering claim from the docstring. |

- [ ] **Step 6: Commit.** `git add agent/guards/claude-hooks/x4guard.py .claude/hooks/x4guard.py tools/x4validate/tests/test_x4guard_check.py`. Message:
  `x4guard: a guard timeout is bounded and kills the guard's whole process tree` — body: M0/M2/S1 numbers, the mutant table, "POSIX path (process group) is exercised only by the ubuntu CI leg".

**Confidence: 85%.** Windows 92% (S1 measured 3/3 shapes, precedent in `audit/driver.py`). POSIX 70%: unmeasured locally. **Raise it:** push nothing; instead the lane-end CI-equivalent is unavailable locally, so ask the orchestrator to read the ubuntu leg of the next CI run for `test_E1_*` per test (it is `continue-on-error`, so a red there is silent unless read).

---

## Task E2: One time budget per check, and a bad budget setting is an inert deny

**Files:** same three as E1.

- [ ] **Step 1: Write the failing tests.**

```python
def _fake_runner(g, monkeypatch, costs: dict):
    """Replace the subprocess layer with a clock: each guard 'takes' costs[script] seconds and
    times out if that exceeds the timeout it was GIVEN. Records (script, timeout given)."""
    clock, seen = [1000.0], []
    monkeypatch.setattr(g, "_clock", lambda: clock[0])
    monkeypatch.setattr(g, "resolve_bash", lambda: ("bash", None))

    def run(argv, payload, env, timeout):
        name = Path(argv[1]).name
        seen.append((name, round(timeout, 3)))
        clock[0] += min(costs[name], timeout)
        return (None, b"", b"") if costs[name] >= timeout else (0, b"", b"")
    monkeypatch.setattr(g, "_run_bounded", run)
    return seen


def test_E2_the_second_delete_guard_gets_only_what_is_left(sandbox, monkeypatch):
    _, tk, env = sandbox
    for k, val in env.items():
        monkeypatch.setenv(k, val)
    g = _load(X4GUARD)
    monkeypatch.setattr(g, "TIMEOUT_S", 4.0)
    seen = _fake_runner(g, monkeypatch, {"protect-files.sh": 1.0, "protect-bash.sh": 0.5})
    v = g.verdict_for("delete", None, None, str(tk / "x.txt"))
    assert seen == [("protect-files.sh", 4.0), ("protect-bash.sh", 3.0)], seen
    assert not v["inert"], v


def test_E2_a_spent_budget_runs_no_further_guard_and_is_inert(sandbox, monkeypatch):
    _, tk, env = sandbox
    for k, val in env.items():
        monkeypatch.setenv(k, val)
    g = _load(X4GUARD)
    monkeypatch.setattr(g, "TIMEOUT_S", 4.0)
    seen = _fake_runner(g, monkeypatch, {"protect-files.sh": 99.0, "protect-bash.sh": 0.5})
    v = g.verdict_for("delete", None, None, str(tk / "x.txt"))
    assert seen == [("protect-files.sh", 4.0)], seen
    assert v["decision"] == "deny" and v["inert"], v
    assert v["guards"] == ["protect-files.sh", "protect-bash.sh"]
    assert "X4_GUARD_TIMEOUT_S" in v["reason"], v["reason"]


def test_E2_a_delete_with_both_guards_hung_spends_one_budget(sandbox, tmp_path):
    """Real processes: MEASURED 17.6 s for two hung guards under a 2 s budget before this lane."""
    _, tk, env = sandbox
    pids = [tmp_path / "a.pid", tmp_path / "b.pid"]
    hooks = _stub_hooks(tmp_path, {"protect-files.sh": _grandchild(pids[0]),
                                   "protect-bash.sh": _grandchild(pids[1])})
    t0 = time.monotonic()
    v = _check_in(dict(env, X4_GUARD_TIMEOUT_S="5"), tk, "--kind", "delete", "--path",
                  str(tmp_path / "x.txt"), script=hooks / "x4guard.py")
    wall = time.monotonic() - t0
    try:
        assert v["decision"] == "deny" and v["inert"], v
        assert wall < 9.5, f"{wall:.1f}s: two budgets were spent (one is ~5.5 s, two ~11 s)"
    finally:
        for p in pids:
            _reap(int(p.read_text()) if p.exists() else None)


@pytest.mark.parametrize("raw", ["abc", "0", "-3", "nan", "inf"])
def test_E2_a_bad_budget_setting_is_an_inert_deny(sandbox, raw):
    _, _, env = sandbox
    rc, v, err = check(dict(env, X4_GUARD_TIMEOUT_S=raw), "--kind", "shell", "--shell", "bash",
                       "--command", "echo hi")
    assert rc == 0, err                       # "abc" was a traceback, rc 1, no JSON (MEASURED)
    assert v["decision"] == "deny" and v["inert"] and "X4_GUARD_TIMEOUT_S" in v["reason"], v


def test_E2_TWIN_a_valid_budget_setting_is_honoured(sandbox):
    _, _, env = sandbox
    _, v, _ = check(dict(env, X4_GUARD_TIMEOUT_S="30.5"), "--kind", "shell", "--shell", "bash",
                    "--command", "echo hi")
    assert v["decision"] == "allow" and not v["inert"], v
```

- [ ] **Step 2: Run, watch fail.** `uv run --frozen python -m pytest -q -rs tests/test_x4guard_check.py -k E2` → Expected: the two fake-clock tests fail with `seen == [("protect-files.sh", 4.0), ("protect-bash.sh", 4.0)]` / two entries (per-guard budget); the hung-delete test fails on the wall bound (~11 s); `abc` fails `rc == 0` (rc 1); `0`/`-3` fail on `"X4_GUARD_TIMEOUT_S" in reason`; the TWIN with `30.5` fails today (`int("30.5")` → rc 1) and passes after. (`nan`/`inf`: `int()` raises → rc 1 → red.)

- [ ] **Step 3: Implement.** Add `import math`. Replace the `TIMEOUT_S = int(...)` line with:

```python
def _timeout_setting() -> tuple:
    """X4_GUARD_TIMEOUT_S: ONE budget for the whole check (both guards of a delete share it).
    A bad value is a configuration error: an inert deny naming it, never a traceback."""
    raw = os.environ.get("X4_GUARD_TIMEOUT_S")
    if raw is None or not raw.strip():
        return 25.0, None
    try:
        t = float(raw)
    except ValueError:
        t = math.nan
    if not math.isfinite(t) or t <= 0:
        return None, f"X4_GUARD_TIMEOUT_S={raw!r} is not a positive number of seconds"
    return t, None


TIMEOUT_S, TIMEOUT_ERROR = _timeout_setting()
```
  `run_guard(script, payload, deadline=None)`: first statement `if TIMEOUT_ERROR: return _inert(TIMEOUT_ERROR, [script])`; after resolving bash: `if deadline is None: deadline = _clock() + TIMEOUT_S`; `remaining = deadline - _clock()`; `if remaining <= 0: return _inert(f"{script} was not run: this check's {TIMEOUT_S:g}s budget (X4_GUARD_TIMEOUT_S) was already spent", guards)`; pass `remaining` to `_run_bounded`; timeout message `f"{script} timed out: this check's {TIMEOUT_S:g}s budget (X4_GUARD_TIMEOUT_S) ran out"`. In `verdict_for`: `deadline = _clock() + TIMEOUT_S if TIMEOUT_S else None` before any guard, passed to every `run_guard` call. Keep both guards running on a delete (no short-circuit on deny: `test_write_and_delete_into_reference_deny` pins `guards`). Update the module docstring: "`X4_GUARD_TIMEOUT_S` (default 25) is the budget for the WHOLE check; worst-case wall clock is that plus KILL_WAIT_S + DRAIN_GRACE_S."

- [ ] **Step 4: Regenerate, run the whole file.** Expected: all pass; `test_I5…` still passes (its reason now says "timed out: this check's 2s budget").
- [ ] **Step 5: Mutation twins:** `deadline` recomputed per guard inside `run_guard` (ignore the argument) → `test_E2_the_second…` red (`4.0` twice); remove the `remaining <= 0` early return → `test_E2_a_spent…` red (`seen` has two entries); `_timeout_setting` returns `(25.0, None)` on bad input → `test_E2_a_bad_budget…[abc]` red; drop the `t <= 0` clause only → `[0]` and `[-3]` red while `[abc]` stays green (one twin per clause).
- [ ] **Step 6: Commit.** Same three paths. Message: `x4guard: one X4_GUARD_TIMEOUT_S budget per check, shared by a delete's two guards; a bad setting is an inert deny, not a traceback`.

**Confidence: 92%.** The fake-clock tests make the clause deterministic; the wall test is a cross-check with ~3.5 s margin each side. **Risk:** the wall test under heavy load (mutation gate running) — if it flakes once, re-run it alone before touching the bound (#31: diagnose the instrument).

---

## Task E3: An inert verdict names the guard's own reason

**Files:** same three.

- [ ] **Step 1: Failing tests.**

```python
_ASK_THEN_EXIT = ("cat >/dev/null\nprintf '%s' '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\","
                  "\"permissionDecision\":\"ask\",\"permissionDecisionReason\":\"WHY-IT-FAILED\"}}'\nexit {code}\n")


@pytest.mark.parametrize("code", [2, 3])
def test_E3_a_failing_guard_names_its_own_reason(sandbox, tmp_path, code):
    _, tk, env = sandbox
    hooks = _stub_hooks(tmp_path, {"protect-bash.sh": _ASK_THEN_EXIT.format(code=code)})
    v = _check_in(env, tk, "--kind", "shell", "--shell", "bash", "--command", "echo hi",
                  script=hooks / "x4guard.py")
    assert v["decision"] == "deny" and v["inert"], v
    assert "WHY-IT-FAILED" in v["reason"], v["reason"]          # dropped today (MEASURED)
    assert f"exit {code}" in v["reason"] or f"exited {code}" in v["reason"], v["reason"]


def test_E3_TWIN_a_failing_guard_without_a_verdict_names_its_stderr(sandbox, tmp_path):
    """The unparseable-stdout clause: no hook JSON, so the cause comes from stderr -- and a
    parse failure must not escape as an exception or turn into anything but an inert deny."""
    _, tk, env = sandbox
    hooks = _stub_hooks(tmp_path, {"protect-bash.sh":
                                   "cat >/dev/null\nprintf 'not json'\necho 'boom: jq missing' >&2\nexit 1\n"})
    v = _check_in(env, tk, "--kind", "shell", "--shell", "bash", "--command", "echo hi",
                  script=hooks / "x4guard.py")
    assert v["decision"] == "deny" and v["inert"], v
    assert "exited 1" in v["reason"] and "boom: jq missing" in v["reason"], v["reason"]
```
  And strengthen the existing `test_I3_a_guard_that_checked_nothing…` final line to
  `assert v["decision"] == "deny" and v["inert"] and "could not be analysed" in v["reason"], v`
  (protect-bash.sh:199/345 both say "could not be analysed"; READ).

- [ ] **Step 2: Run, watch fail.** `-k "E3 or I3"` → Expected: both E3 params fail on `WHY-IT-FAILED`; TWIN fails on `boom`; I3 fails on `could not be analysed` (skips only if no PowerShell — Windows CI has it).
- [ ] **Step 3: Implement** in `run_guard`, replacing the two non-zero branches:

```python
    if rc != 0:
        why = _failure_detail(out, err)
        head = (f"{script} reported it could not evaluate this (exit 2, X4_GUARD_CHECK)" if rc == 2
                else f"{script} exited {rc}")
        return _inert(head + (f": {why}" if why else ""), guards)
```
```python
def _failure_detail(out: bytes, err: bytes) -> str | None:
    """The guard's own reason when it printed a hook verdict before failing (every X4_GUARD_CHECK
    exit 2 does), else the last 300 characters of its stderr."""
    try:
        _, reason, context = parse_hook_output(out.decode("utf-8", "replace"))
        if reason or context:
            return reason or context
    except ValueError:
        pass
    tail = err.decode("utf-8", "replace").strip()[-300:]
    return tail or None
```
- [ ] **Step 4: Regenerate, run whole file.** Expected: all pass.
- [ ] **Step 5: Mutation twins:** `_failure_detail` returns `None` → both E3 tests red; remove the stderr fallback only → TWIN red, `E3[2]`/`E3[3]` green.
- [ ] **Step 6: Commit.** Message: `x4guard: an inert verdict carries the failing guard's own reason, or its stderr tail`.

**Confidence: 95%.**

---

## Task E4: The delete probe is `rm -rf -- '<path>'`

**Honest scope (MEASURED, M1):** today no protect-bash rule distinguishes `rm -f` from `rm -rf --` — 9/9 paths gave identical verdicts, because flags never reach a rule. So this changes no verdict today. It makes the probe say what a directory delete is, so a future rule keyed on recursion (or a future `_operands` that honours `--`) judges a delete correctly. The Codex session's "stricter for directories" claim is **not** borne out by measurement and must not appear in the commit as a fact.

**Files:** same three.

- [ ] **Step 1: Failing tests.**

```python
def test_E4_the_delete_probe_is_a_recursive_rm(sandbox):
    """The ask reason echoes the probe command (MEASURED: 'confirm: rm -f ...')."""
    _, tk, env = sandbox
    v = _check_in(env, tk, "--kind", "delete", "--path", str(tk / "dev" / "mymod"))
    assert v["decision"] == "ask" and not v["inert"], v
    assert "rm -rf -- '" in v["reason"], v["reason"]


def test_E4_TWIN_a_quote_and_a_space_in_the_path_still_reach_the_rm_rule(sandbox):
    """Quoting clause: a broken quote would come back as the 'does not PARSE' ask instead."""
    _, tk, env = sandbox
    p = tk / "dev" / "mymod" / "it's here.xml"
    p.write_text("x\n", encoding="utf-8")
    v = _check_in(env, tk, "--kind", "delete", "--path", str(p))
    assert v["decision"] == "ask" and not v["inert"], v
    assert v["reason"].startswith("Deleting files in an X4 directory"), v["reason"]
    assert p.exists()
```
  Update `test_I4_a_delete_is_at_least_as_strict_as_rm`: add `s2 = _check_in(..., f"rm -rf -- '{target.as_posix()}'")` and assert `rank[d["decision"]] == max(rank[w["decision"]], rank[s["decision"]], rank[s2["decision"]])`.

- [ ] **Step 2: Run, watch fail.** `-k "E4 or I4"` → Expected: `test_E4_the_delete_probe…` fails on `"rm -rf -- '"`. The TWIN is a regression pin and PASSES today (PREDICTION; if it fails, the existing quoting is broken — stop and report, that is a separate finding). I4 passes before and after.
- [ ] **Step 3: Implement** in `verdict_for`: `rm = "rm -rf -- '" + quoted + "'"`. Keep the existing slash conversion and `'"'"'` quoting (do NOT switch to `shlex.quote` on the raw Windows path — the backslash conversion is what the guard resolves). Docstring: "a delete is judged as the stricter of a write and an `rm -rf --` of that path".
- [ ] **Step 4: Regenerate, run whole file.** Expected: all pass.
- [ ] **Step 5: Mutation twin:** revert the probe to `rm -f '` → `test_E4_the_delete_probe…` red. Quote mutant `quoted = path.replace("\\", "/")` (no `'` escaping) → TWIN red (reason becomes the "does not PARSE" ask).
- [ ] **Step 6: Commit.** Message: `x4guard: probe a delete as rm -rf -- (no verdict changes today: 9/9 paths measured identical)`.

**Confidence: 95%.**

---

## Task E5: A delete keeps every guard's advisory

**Files:** same three.

- [ ] **Step 1: Failing tests.**

```python
def test_E5_a_delete_keeps_the_file_guards_advisory(sandbox):
    """MEASURED: the delete ASKs (protect-bash) and the manifest advisory from protect-files
    was dropped -- context null."""
    _, tk, env = sandbox
    target = tk / "dev" / "mymod" / "content.xml"
    w = _check_in(env, tk, "--kind", "write", "--path", str(target))
    d = _check_in(env, tk, "--kind", "delete", "--path", str(target))
    assert w["decision"] == "advise" and w["context"], w
    assert d["decision"] == "ask" and d["context"] and w["context"] in d["context"], d


def test_E5_TWIN_contexts_join_in_guard_order_whoever_wins(monkeypatch):
    g = _load(X4GUARD)
    vs = iter([{"v": 1, "decision": "advise", "reason": None, "context": "A", "inert": False,
                "guards": ["protect-files.sh"]},
               {"v": 1, "decision": "advise", "reason": None, "context": "B", "inert": False,
                "guards": ["protect-bash.sh"]}])
    monkeypatch.setattr(g, "run_guard", lambda *a, **k: next(vs))
    v = g.verdict_for("delete", None, None, "x")
    assert v["decision"] == "advise" and v["context"] == "A\n\nB", v
    assert v["guards"] == ["protect-files.sh", "protect-bash.sh"]
```
- [ ] **Step 2: Run, watch fail.** `-k E5` → Expected: first fails on `d["context"]` (None); TWIN fails with `context == "A"` (winner-only; `max` picks the first of equal rank).
- [ ] **Step 3: Implement** at the end of `verdict_for`, after picking `worst`:
  `ctx = [v["context"] for v in parts if v.get("context")]` → `worst["context"] = "\n\n".join(ctx) or None`.
- [ ] **Step 4: Regenerate, run whole file.** Expected: all pass.
- [ ] **Step 5: Mutation twin:** keep the winner's context only → both E5 tests red; join with `""` → TWIN red only.
- [ ] **Step 6: Commit.** Message: `x4guard: a delete verdict carries every guard's advisory, not only the winner's`.

**Confidence: 93%.** Open question for Lane B, not for the user: whether its renderer caps the merged context (spec §5.2 keeps the 10,000-char bound).

---

## Task E6: agent.yaml hardening in gen-agent-trees.py

**Files:**
- Modify: `tools/x4validate/scripts/gen-agent-trees.py`
- Modify: `tools/x4validate/tests/test_gen_agent_trees.py`
- Generated output must NOT change (G3): `.claude/agents/*.md` stay byte-identical.

- [ ] **Step 1: Failing tests** (append to `test_gen_agent_trees.py`; add `import json`, `import shutil` at the top).

```python
CFI = "agent/agents/cross-file-impact/agent.yaml"
MR = "agent/agents/mod-research/agent.yaml"


def _agent_copy(tmp_path):
    shutil.copytree(REPO / "agent", tmp_path / "agent")
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
```
  The existing `test_agent_frontmatter_matches_the_claude_contract` is the twin of the quoting clause: it pins the PLAIN `description: Use BEFORE…` form, so "quote only when needed" cannot degrade to "always quote". `test_committed_trees_are_fresh` pins byte identity of the real output.

- [ ] **Step 2: Run, watch fail.** `uv run --frozen python -m pytest -q -rs tests/test_gen_agent_trees.py -k E6` → Expected: tools (4 params) fail "DID NOT RAISE"; description: `Note:` and `Line one` params fail with a ScannerError in `_frontmatter`, `a #hash` fails on the value (truncated at `#`), `[bracketed]` fails (parsed as a list); duplicate/name params fail "DID NOT RAISE" (except `""`, which already raises "missing name" — fine, and `123` passes `match="name"`? No: today it generates `123.md`, so DID NOT RAISE); claude-not-mapping fails with `AttributeError: 'list' object has no attribute 'get'` (not GenerationError). The round-trip pin and the TWIN pass today (PREDICTION).

- [ ] **Step 3: Implement** in `gen-agent-trees.py`. Add `import json`, `import re`, `from ruamel.yaml.error import YAMLError`.

```python
#: Claude Code agent names are lowercase letters, digits and hyphens; anything else could also
#: steer the output path (MEASURED: '../../escaped' rendered outside .claude/agents/).
_AGENT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _yaml_scalar(s: str) -> str:
    """s as a YAML value: plain when YAML reads it back unchanged (every real description today,
    MEASURED), else a JSON string, which is a valid YAML double-quoted scalar."""
    try:
        if YAML(typ="safe").load("k: " + s) == {"k": s}:
            return s
    except YAMLError:
        pass
    return json.dumps(s, ensure_ascii=False)


def _load_yaml(p: Path):
    try:
        return YAML(typ="safe").load(_read(p))
    except YAMLError as e:
        raise GenerationError(f"{p}: not valid YAML: {str(e).splitlines()[0]}") from e
```
  In `render_agent_md`: load via `_load_yaml`; require `name`, `description`, `tier` to be non-empty `str` (message `"{agent.yaml}: {key} must be a non-empty string"`); `if not _AGENT_NAME.match(meta["name"]): raise GenerationError(f"{p}: name {meta['name']!r} must match {_AGENT_NAME.pattern}")`; `claude = meta.get("claude") or {}`, `if not isinstance(claude, dict): raise GenerationError(f"{p}: claude must be a mapping")`; `tools = claude.get("tools") or []`, `if not isinstance(tools, list) or not all(isinstance(t, str) and t.strip() and "," not in t and "\n" not in t for t in tools): raise GenerationError(f"{p}: claude.tools must be a YAML list of tool names, e.g. [Read, Grep]")`. Emit `f"description: {_yaml_scalar(meta['description'])}"`. After building the frontmatter lines, re-parse them and refuse if `name`/`description`/`model` do not read back as intended (belt and braces against a value class not foreseen here; #36). In `generate()`: keep `seen: dict[str, Path]`; on a repeated `meta name` raise `GenerationError(f"agent name {name!r} is used by both {seen[name]} and {d}")` (do the check on the returned `rel`, so it covers whatever render returns).

- [ ] **Step 4: Run.** `uv run --frozen python -m pytest -q -rs tests/test_gen_agent_trees.py` → Expected: all pass, including `test_committed_trees_are_fresh` (no regeneration needed). Then `uv run --frozen python scripts/gen-agent-trees.py --check` → Expected: rc 0, no output.
- [ ] **Step 5: Mutation twins:** `_yaml_scalar` returns `s` → `Note:`/`Line one`/`#`/`[` params red; `_yaml_scalar` always JSON-quotes → `test_agent_frontmatter_matches_the_claude_contract` and `test_committed_trees_are_fresh` red; drop the duplicate check → `test_E6_duplicate…` red; widen the regex to `.+` → name params red except `123` (type clause) and `""` (missing clause) — one twin per clause; drop the `isinstance(tools, list)` clause only → `tools: Glob, …` param red.
- [ ] **Step 6: Commit.** `git add tools/x4validate/scripts/gen-agent-trees.py tools/x4validate/tests/test_gen_agent_trees.py`. Message: `gen-agent-trees: agent.yaml is validated (tools list, plain agent names, unique names) and a description is emitted YAML-safe` — body: the G1 table.

**Confidence: 88%.** The generator half is 95%. The 12% is the ASSUMED clause that Claude Code reads a JSON-quoted `description:` correctly. It affects no file today (G3: none is quoted), only future descriptions. **Raise it:** in a scratch project, create `.claude/agents/q-test.md` with `description: "Note: quoted"`, start `claude`, run `/agents`, and confirm the description shows without quotes. Delete the scratch project afterwards. This is a two-minute manual check, so the orchestrator or the user should run it. Nothing ships quoted until it has been run.

---

## Task E7: Every malformed source refuses with rc 2, and a non-UTF-8 generated file is STALE

**Files:** same as E6.

- [ ] **Step 1: Failing tests.**

```python
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
```
- [ ] **Step 2: Run, watch fail.** `-k E7` → Expected: the 5 params fail with the uncaught exception named in G1/G2 (ParserError, ValueError, UnicodeDecodeError ×2, DuplicateKeyError); STALE test fails with UnicodeDecodeError; TWIN passes today (PREDICTION).
- [ ] **Step 3: Implement.**
  - `_read(p)`: wrap the decode — `except UnicodeDecodeError as e: raise GenerationError(f"{p}: not UTF-8 (byte 0x{e.object[e.start]:02x} at offset {e.start})") from e`.
  - `_with_banner_after_frontmatter(text, where)`: `end = text.find("\n---\n", 4)`; `if not text.startswith("---\n") or end < 0: raise GenerationError(f"{where}: YAML frontmatter must open and close with '---' lines")`. Callers pass `f` (skills) and `agent_dir / "agent.yaml"` (agents).
  - `_load_yaml` from E6 already converts YAML errors (DuplicateKeyError is a YAMLError, MEASURED G2).
  - `_norm(b)`: return `None` on `UnicodeDecodeError`; `problems()` treats `None` as STALE (`None != text`).
  - `main()` keeps catching `GenerationError` only — no blanket `except Exception`, so a genuine bug still shows its traceback.
- [ ] **Step 4: Run whole file + `--check`.** Expected: all pass; `--check` rc 0.
- [ ] **Step 5: Mutation twins:** remove the `UnicodeDecodeError` catch in `_read` → both non-UTF-8 params red; restore `text.index` → never-closed red; `_load_yaml` without its `except` → syntax-error and duplicate-key params red; `_norm` without its catch → STALE test red.
- [ ] **Step 6: Commit.** Message: `gen-agent-trees: a malformed or non-UTF-8 source refuses (rc 2) instead of a traceback; a non-UTF-8 generated file is STALE`.

**Confidence: 95%.**

---

## Task E8: Docs, regenerate, lane-end gates

**Files:** `CHANGELOG.md` (Unreleased), `docs/superpowers/specs/2026-09-30-universal-agent-support-design.md` (the §5.6 "Implemented follow-up" paragraph only).

- [ ] **Step 1: CHANGELOG** under `## Unreleased`, extending the existing `x4guard check` bullet:
  - "A guard that hangs is bounded: its whole process tree is killed (Windows `taskkill /T`, POSIX process group), and `check` returns within `X4_GUARD_TIMEOUT_S` + 8 s even when the kill fails. Before this, a guard's child process held the pipes open and stretched a 2 s budget to 10.9 s."
  - "`X4_GUARD_TIMEOUT_S` is now ONE budget per check: a delete's two guards share it. An invalid value is an inert deny, not a traceback."
  - "An inert verdict names the failing guard's own reason (or its stderr). A delete keeps every guard's advisory. The delete probe is `rm -rf --`; that changes no verdict today."
  - "`gen-agent-trees.py` refuses (rc 2) on a malformed `agent/` source: a non-UTF-8 file, invalid YAML, an unclosed frontmatter, `tools` that is not a list, or an agent name that is not plain or is duplicated. A description that YAML would misread is emitted quoted."
- [ ] **Step 2: Spec §5.6.** Replace the sentence that begins "The authoritative wrapper at `74b38fe` applies a separate timeout budget…" through "…require separate verification." with a dated line: "Plan 2 lane E (2026-10-0x): one budget per check, shared by both delete guards; the guard's process tree is killed on timeout (Windows MEASURED, POSIX via process group: see CI); worst-case wall clock = `X4_GUARD_TIMEOUT_S` + 8 s. Agent-host enforcement still requires separate verification." Do not rewrite the dated audit doc (`docs/AUDIT-framework-2026-10-01.md`). It is a record.
- [ ] **Step 3: Regenerate and check.** `uv run --frozen python scripts/gen-agent-trees.py --check` should return 0. `uv run --no-project python ../../scripts/scan-identifiers.py` should come back clean.
- [ ] **Step 4: Lane-end gates.** Run each once and read every skip reason. Run long jobs with `run_in_background`, never two at once, and never while another session's mutation gate runs:
  1. `cd tools/x4validate && uv run --frozen python -m pytest -q -rs`, in the background. The result should be green, with the skip count unchanged from the lane's starting baseline: take that count first, on the base commit.
  2. `bash .claude/hooks/test-protect-bash.sh` and `python .claude/hooks/test_hook_facts.py`. Both should be unchanged, because no guard was edited. They are a control that only `x4guard.py` moved inside `.claude/hooks/`.
  3. `uv run --frozen python ../../scripts/verify-hook-tests.py`, in the background. It should pass. It is the mutation harness for the hook tests.
  4. `bash scripts/run-gates.sh`, the quick gates. Expect exit 0 or 3. If the exit is 3, each could-not-run gate is named, and none of them is `deploy_parity` for a reason this lane caused.
  5. A per-test read of `test_E1_*`/`test_E2_*` on the next CI ubuntu leg, which is `continue-on-error`. That run is the only POSIX measurement.
- [ ] **Step 5: Commit** the docs (`CHANGELOG.md`, the spec) with the message `docs: lane E -- x4guard bounded timeouts and generator refusals`.
- [ ] **Step 6: Game-root redeploy is NOT this lane's call.** After merge, `deploy_parity` will report the game-root `.claude/hooks/x4guard.py` as stale until someone runs `tools/x4validate/scripts/deploy-claude-dir.py --apply` and makes a game-root commit. Hand that to the orchestrator, who owns the game-root `.claude/` (CLAUDE.md "one owner per derived artifact").

**Confidence: 90%.** Full-suite timing under load is the only risk.

---

## Files touched (union)

- `agent/guards/claude-hooks/x4guard.py`
- `.claude/hooks/x4guard.py` (generated, never hand-edited)
- `tools/x4validate/tests/test_x4guard_check.py`
- `tools/x4validate/scripts/gen-agent-trees.py`
- `tools/x4validate/tests/test_gen_agent_trees.py`
- `CHANGELOG.md`
- `docs/superpowers/specs/2026-09-30-universal-agent-support-design.md` (§5.6 paragraph only)

## Cross-lane dependencies

- **Lane A (instruction split):** this is the highest conflict risk. A will almost certainly edit `gen-agent-trees.py` (`render_agents_md`, `render_claude_md`, new instruction parts) and `test_gen_agent_trees.py`. E6/E7 touch `_read`, `_norm`, `_with_banner_after_frontmatter` (new `where` parameter: **any new caller A adds must pass it**), `render_agent_md`, `generate()`'s agent loop and `problems()`. **Recommend landing E6+E7 first.** They are small and leave the output byte-identical. A then rebases onto them. If A lands first, E6/E7 rebase onto A instead. Either way, one lane at a time on that file.
- **Lane B (Codex adapter):** consumes `verdict_for()` and the verdict JSON, whose shape is unchanged. B needs from E: (1) the **worst-case wall clock**, `X4_GUARD_TIMEOUT_S + KILL_WAIT_S + DRAIN_GRACE_S` + interpreter start-up, which is ≈ 33–35 s at defaults. Spec §5.3 requires B's wrapper timeout to sit **below** Codex's hook timeout, so either B sets `X4_GUARD_TIMEOUT_S` lower for its calls or Codex's hook timeout is set above ~40 s. B decides; E only guarantees the bound. (2) Merged `context` can now be two advisories long, so B's renderer keeps the 10,000-char cap (§5.2). If B also edits `x4guard.py` (spec §5.6 names an `--agent` flag), sequence it after E1–E5 to avoid a same-file conflict.
- **Lane C (installers / x4doctor):** if x4doctor calls `x4guard check` to test liveness, it inherits the bound. An invalid `X4_GUARD_TIMEOUT_S` is now an inert deny with the variable named, which x4doctor can surface as a configuration finding. C needs nothing else from E.
- **Lane D (Layer 2 OS protection):** no dependency.
- **Orchestrator:** after merge, the game-root redeploy (`deploy-claude-dir.py --apply`) and a game-root commit (see E8 Step 6). Reading the ubuntu CI leg per test.

## Questions for the user

1. **Agent-name rule.** Should agent names be restricted to Claude Code's convention, `^[a-z0-9][a-z0-9-]*$`, or should the generator only reject what can escape `.claude/agents/` (`/`, `\`, `..`)? **Recommended: the strict rule.** Both current agents already comply. It also stops a name Claude Code would reject and a path escape with one check, and it can be loosened later if a target needs it.

Nothing else here is a policy decision. The budget semantics (per check instead of per guard) come from the brief and the Codex session. The invalid-setting behaviour (an inert deny) follows the module's existing rule that "a guard that could not run is never an allow".

## Confidence summary

| Task | Confidence | What would raise it |
|---|---|---|
| E1 tree kill + bounded drain | 85% (Windows 92%, POSIX 70%) | A per-test read of the ubuntu CI leg for `test_E1_*` |
| E2 shared budget + setting validation | 92% | Re-running the wall test alone if it ever flakes under load |
| E3 reason in the inert cause | 95% | — |
| E4 `rm -rf --` probe | 95% (no verdict changes, MEASURED 9/9) | — |
| E5 merged contexts | 93% | — |
| E6 agent.yaml hardening | 88% | The `/agents` scratch check that Claude Code reads a JSON-quoted description |
| E7 rc 2 refusals | 95% | — |
| E8 docs + gates | 90% | — |

## Gate plan

- **Per task (focused, seconds to about a minute):** E1–E5 run `uv run --frozen python -m pytest -q -rs tests/test_x4guard_check.py` (the whole file, since it is small; E1 adds about 10 s of deliberate timeouts). E6–E7 run `tests/test_gen_agent_trees.py` plus `scripts/gen-agent-trees.py --check`. Every task also gets its hand-mutation table (Step 5), recorded in the commit body.
- **Lane end, once:** E8 Step 4. That is the full pytest run (background), the hook regression suites as a control, `verify-hook-tests.py` (background), the quick gates, and the ubuntu CI per-test read. The full mutation gate (`gates/mutation_probe.py`) is **not** needed for this lane, because it mutates only the nine `x4validate/_*.py` files, and this lane touches none of them.


## Amendments -- 2026-10-02 (user decisions; binding, supersede the text above)

Read DECISIONS.md in this folder first. Changes to THIS lane:
- **#18:** strict agent names `^[a-z0-9][a-z0-9-]*$`.
- **#19 added:** implement `X4_GUARD=off` (the spec's documented escape hatch; no guard reads it today) -- test-first, with a twin proving guards still fire when it is unset or any other value; x4guard check reports it explicitly rather than as an allow.
- **#15:** the POSIX process-group kill (E1) is in scope; test on CI ubuntu and READ results per test.

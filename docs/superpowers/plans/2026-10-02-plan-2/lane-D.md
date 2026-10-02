# Universal Agent Support — Plan 2, Lane D: Layer 2 OS protection on `reference\` (spec D14)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** `reference\` carries an inherited OS deny-delete ACE that holds against every agent,
hooks or no hooks. A user, never an agent, lifts it. It never locks anyone out of a re-unpack, and
every state, including "this platform is unsupported", is reported as itself and never as "protected".

**Architecture:** a new stdlib-only `scripts/x4refguard.py` with `apply | remove | status [--json]`.
Writes go through `icacls` using the SID form (`*S-1-5-...`), so they do not depend on locale or
account name. Reads go through one `powershell.exe` call that returns `Get-Acl` rules as numeric
rights masks plus SIDs, as JSON, so status parsing does not depend on locale either. After every
change the script re-reads the ACL and confirms it, as x4lock's `_apply` does. `bin/unpack-reference.sh`
refuses to re-unpack while the deny is on and applies the deny after it writes the sentinel.
`x4lock status` prints one informational Layer-2 line. `x4doctor` (lane C) consumes `status --json`.

**Repo:** `$X4_TOOLKIT` = `$X4_TOOLKIT`, branch `master` (HEAD `cde1ebe`
when this plan was written). `PKG` = `tools/x4validate`. Focused tests are run from `PKG` with
`uv run --frozen python -m pytest <file> -q -rs`.

---

## Context: what was READ and MEASURED for this plan

| Claim | Tier | Source |
|---|---|---|
| `icacls <root> /deny <user>:(OI)(CI)(DE,DC)` blocked 8/8 delete primitives on a user-owned scratch tree. Reads, in-place writes and new-file creation still worked. No Synchronize right. Removable unelevated, with 0 deny entries left. DE on a file alone does NOT hold. | MEASURED (spike, scratch only) | `docs/superpowers/measurements/2026-09-30-codex-spike.md:99-117` |
| The old `(W,D,WDAC,WO)` deny was withdrawn: `W` includes SYNCHRONIZE, so reads failed. WDAC made the deny unremovable on Administrators-owned files. | MEASURED (historic) | `scripts/x4lock.py` docstring, "WHY THERE IS NO ACL HERE" |
| **`reference\` does NOT carry the read-only attribute today.** 0 of the 3,429 files sampled (the first 3,429 in `os.walk` order) are read-only. The root dir has the write bit. | **MEASURED 2026-10-02**, read-only `os.stat` sample, NOT the full 510,711 | this plan's own probe |
| So spec §4's Layer-2 row ("`reference\`: read-only attribute **plus** inherited deny-delete", spec line 68) describes something that does not exist. Today the only "lock" on `reference\` is the `.unpacked-and-locked` sentinel plus the Claude hooks (`protect-bash.sh:363,370,375`). x4lock's manifest never includes `reference\` (`_GAME_RELATIVE`/`_GAME_GLOBS`). | READ + MEASURED | `scripts/x4lock.py:96-115`, probe above |
| The sentinel exists on this machine. Its text is `... (steam buildid 23660954) on 2026-06-22 ... remove this file manually to re-unpack.` | MEASURED | probe |
| `reference\` and its parent `Desktop/Modding/X4` are not git repos (no `.git`), so D14's "not on git-tracked trees" carve-out does not bite here. | MEASURED | probe |
| **Every recovery message says "remove the sentinel".** Under DE,DC that `rm` fails with Access denied: `bin/unpack-reference.sh:40-42`, `protect-bash.sh:376`, `check-reference-version.sh:75`, and the sentinel text itself (`unpack-reference.sh:131,137`). Without changes, the deny would make the documented escape hatch fail. | READ | those lines |
| The sentinel parser takes the first `buildid[^0-9]*[0-9]+`, so rewording the sentinel tail is safe. | READ | `check-reference-version.sh:66` |
| `_freshness` hashes reference `mtime:size` (`_freshness.py:543,552`). An ACL change should not move either. | READ; "does not move" is INFERRED, and pinned by a test (Task 4) | |
| `_paths.reference()` resolves the configured root. Explicit `X4_REFERENCE` in any real layer wins (`_paths.py:373-415`). `_paths.reload()` exists (`:165`). | READ | |
| The installers copy the whole tree minus a prune list (`install.sh:157`), so a new `scripts/x4refguard.py` ships without any copy-list edit. | READ | |
| CI gates pytest on windows-latest and enforces a skip ceiling per OS (`ci.yml` `X4_MAX_SKIPS`: ubuntu 68, windows 56, with a classified bucket comment). | READ | `.github/workflows/ci.yml:595-605` |
| The Claude PowerShell tool misreads an inline `icacls /deny` as a system path. | RELAYED by the orchestrator, NOT re-measured here | brief |
| Ownership: on this machine the game root, `reference\` and `dev\` are owned by the user. | MEASURED (spike) | spike:114-116 |

**F1 (interpreter writes):** `python -c "open('<ref>/x.xml','w').write('x')"` passes the guards
(audit F1, 95%). The spike MEASURED that in-place writes still work under DE,DC. **The deny-delete
alone does not close F1 for `reference\`.** See Question Q1.

## Global constraints

- **PLAN ONLY until approved.** The real `reference\` is touched only in Task 7, and only by the
  user's own command.
- **Tests never touch the real reference tree.** Each test sets `X4_REFERENCE` to a `tmp_path` tree
  and calls `_paths.reload()`. A fixture-level tripwire (Task 3) wraps `subprocess.run` and fails the
  test if any `icacls` argv names a path outside `tmp_path`. It has a falsification twin.
- **Never run an inline `icacls /deny` through the Claude PowerShell tool.** Manual probes go in a
  `.py` or `.ps1` file in the session scratchpad and are run as a file. Tests call `icacls` via
  `subprocess.run([...])` with a list argv, never a shell string.
- **Rights are exactly `DE,DC`**, or `DE,DC,WD,AD` if Q1 is answered "yes". **Never `W`, `S`,
  `WDAC`, `WO` or `F`.** A test asserts the applied mask numerically: Delete `0x10000` +
  DeleteSubdirectoriesAndFiles `0x40` = **65600**, or + WriteData `0x2` + AppendData `0x4` = **65606**.
- **Exit-code contract** (matches the toolkit's: 2 = not configured or refused, 3 = checked nothing):
  `0` protected (or the action succeeded and was verified) · `1` absent or partial, or the action
  ran but verification disagrees · `2` unconfigured or refused · `3` unsupported platform.
- `scripts/x4refguard.py` is stdlib-only and must import on Python 3.10, like `x4lock.py`.
- Stage explicit paths only. One commit per task on `master`. Never push.
- CLAUDE.md has effectively no headroom (about 39,971 of 40,000). **This lane adds nothing to
  CLAUDE.md.** Usage lives in the script's `--help`/docstring and in README (routing rule: "how to
  USE a tool goes in the tool's own docs").
- Hooks advise or deny Claude. The only user prompt this lane may introduce is the lift (Q3), which
  is a precursor to a delete inside an X4 directory, a category CLAUDE.md already reserves for `ask`.

## Interfaces

**Produces**

```
python scripts/x4refguard.py status [--json] [--full]
python scripts/x4refguard.py apply  [--path P]           # P must equal the configured root
python scripts/x4refguard.py remove [--path P]           # the escape hatch (see "Escape hatch")
```

`status --json` emits one object on stdout, always, even on exit 2 or 3:

```json
{"state": "protected|absent|partial|foreign|unconfigured|unsupported|error",
 "root": "<abs path or null>", "mask": 65600, "mask_expected": 65600,
 "sentinel": true, "owner_is_user": true,
 "sampled": 33, "sample_ok": 33, "sample_scope": "root + sentinel + first file of each top-level dir (not a census; use --full)",
 "detail": "<one human sentence>"}
```

`foreign` means a deny ACE for the user's SID exists on the root with a mask this tool did not
write. The tool never alters a foreign ACE. It refuses and names it.

Python API, for x4lock and x4doctor: `x4refguard.report() -> dict` (the same object), and
`x4refguard.EXPECTED_MASK`.

**Consumes**

- `x4validate._paths.reference()`, `.game_root()`, `.reload()`.
- `scripts/gitbash.py` (tests only) for a real bash, never the WSL stub.
- Lane C (`x4doctor`) consumes `status --json`. Lane B (Codex `.rules`) and lane E (`protect-bash`)
  consume the command shape `x4refguard.py remove` to gate it (Q3).

**Escape hatch (D8), documented in the script's `--help`, the README and every refusal message:**

1. `python scripts/x4refguard.py remove` (unelevated; MEASURED removable on user-owned trees).
2. If the configured root has since changed: `python scripts/x4refguard.py remove --path <old>`.
   This is accepted on a non-configured path **only if** that path carries this tool's exact
   explicit ACE, so the escape hatch can never be turned against an arbitrary directory.
3. If the tool itself is broken: `icacls "<root>" /remove:d *<your SID>` from **cmd.exe** (not the
   Claude PowerShell tool); `whoami /user` prints the SID.
4. Last resort, from an elevated prompt: `icacls "<root>" /reset /T /C`. This discards every explicit
   ACE in the tree and restores inheritance from the parent.

---

## Task 1: Measure what the plan still ASSUMES (scratch only, no repo change except the record)

The spike measured DE,DC on a small scratch tree. Six facts the build depends on are unmeasured.

**Files:** create `docs/superpowers/measurements/2026-10-0X-layer2-reference-acl.md`. The probe
script lives in the session scratchpad and is NOT committed.

- [ ] **Step 1: Write `scratchpad/layer2_probe.py`.** Python only. It builds trees under
  `tempfile.mkdtemp()` and asserts it never receives a path outside that directory. For each
  measurement it records a control.
  - **M-a, propagation cost:** a synthetic tree of 100,000 files in about 5,000 dirs (mimicking
    `reference\` fan-out). Time `icacls /deny ...(OI)(CI)(DE,DC)` and `icacls /remove:d`. Repeat 3
    times; report the median. Extrapolate linearly to 510,711 and label that INFERRED. Note the
    `perf_counter` sleep trap (#31): disable sleep, or re-run on any outlier.
  - **M-b, idempotency:** apply twice, then count the explicit deny ACEs for the SID on the root
    (`Get-Acl` JSON). Expected 1, but icacls may merge or duplicate; record which.
  - **M-c, numeric mask:** the `[int]FileSystemRights` that `Get-Acl` reports for the root ACE and
    for an inherited child ACE. Expected 65600, plus `IsInherited` true on the child.
  - **M-d, mtime/size:** every file's `st_mtime_ns`/`st_size` before and after apply and remove.
    Expected unchanged; the freshness axes depend on this.
  - **M-e, root rename:** with the deny on `<tmp>/parent/reference`, attempt
    `os.rename(<tmp>/parent/reference, <tmp>/parent/reference.old)`. INFERRED to SUCCEED, because
    the parent grants delete-child. Then confirm the children still refuse delete. Record the result
    either way; this is a known gap to pin, not to fix.
  - **M-f, Q1 candidate `(OI)(CI)(DE,DC,WD,AD)`:** on a fresh tree:
    (i) reads still work: python `open(..., 'r')`, `Path.read_bytes`, PowerShell `Get-Content`,
    `cmd /c type`;
    (ii) F1 blocked: `open(p,'w')`, `write_text`, `os.truncate`, `shutil.copy2` over an existing file;
    (iii) `Copy-Item -Force` over an existing file blocked; this is x4lock's measured `-Force` gap;
    (iv) creating a new file and `mkdir` blocked;
    (v) removable unelevated with 0 deny entries left anywhere (walk every file);
    (vi) controls: every primitive above succeeds on an identical tree without the deny.
- [ ] **Step 2: Run it as a file:** `uv run --no-project python <scratchpad>/layer2_probe.py`, in the
  background if M-a exceeds 10 min (#25).
  Expected: a table per measurement with a control column. Any control that does NOT succeed makes
  that row a NON-ANSWER, not a pass.
- [ ] **Step 3: Record** each row as MEASURED, with its denominator, in the measurements doc. M-f's
  result is the evidence for Q1. Present it to the user before Task 3 fixes the mask.
- [ ] **Commit:** `docs/measurements: Layer-2 reference ACL -- propagation cost, idempotency, numeric mask, mtime, root-rename gap, write-deny candidate`

**Gate:** none beyond the probe's own controls. **Confidence 90%** (measurement only). Risk: a
100k-file tree takes minutes to build and tear down, so run it in the background.

---

## Task 2: `x4refguard.py` target resolution and refusals (pure logic, every OS)

**Files:** create `scripts/x4refguard.py` (resolution half only) and
`tools/x4validate/tests/test_x4refguard.py`.

- [ ] **Step 1: Failing tests** (platform-neutral; these run on ubuntu too, so they add no skips):

```python
# PKG/tests/test_x4refguard.py
r"""x4refguard must refuse every target that is not the configured, unpacked reference root,
and must never report "protected" for a state it did not confirm. The real reference tree is never
touched: every test points X4_REFERENCE at tmp_path."""
from __future__ import annotations
import importlib.util, json, os, sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("x4refguard", REPO / "scripts" / "x4refguard.py")
x4refguard = importlib.util.module_from_spec(_spec); sys.modules["x4refguard"] = x4refguard
_spec.loader.exec_module(x4refguard)
from x4validate import _paths

SENTINEL = ".unpacked-and-locked"

@pytest.fixture
def ref(tmp_path, monkeypatch):
    root = tmp_path / "reference"
    (root / "libraries").mkdir(parents=True)
    (root / "libraries" / "wares.xml").write_text("<wares/>", encoding="utf-8")
    (root / SENTINEL).write_text("Re-unpacked from X4 (steam buildid 1) on 2026-10-02.", encoding="utf-8")
    monkeypatch.setenv("X4_REFERENCE", str(root))
    _paths.reload()
    yield root
    _paths.reload()

def test_resolve_returns_the_configured_root(ref):
    assert x4refguard.resolve_target(None, action="apply") == ref.resolve()

def test_a_path_that_is_not_the_configured_root_is_REFUSED(ref, tmp_path):
    other = tmp_path / "elsewhere"; other.mkdir(); (other / SENTINEL).write_text("x")
    with pytest.raises(x4refguard.Refused, match="not the configured reference root"):
        x4refguard.resolve_target(other, action="apply")

def test_case_and_slash_variants_of_the_configured_root_are_ACCEPTED(ref):
    variant = Path(str(ref).replace("\\", "/"))
    if os.name == "nt":
        variant = Path(str(variant).upper())
    assert x4refguard.resolve_target(variant, action="apply") == ref.resolve()

def test_apply_REFUSES_a_root_without_the_sentinel(ref):
    (ref / SENTINEL).unlink()
    with pytest.raises(x4refguard.Refused, match="sentinel"):
        x4refguard.resolve_target(None, action="apply")

def test_remove_does_NOT_need_the_sentinel(ref):        # the escape hatch must always work
    (ref / SENTINEL).unlink()
    assert x4refguard.resolve_target(None, action="remove") == ref.resolve()

@pytest.mark.parametrize("bad", ["drive_root", "home", "git_root"])
def test_apply_REFUSES_dangerous_roots_even_when_configured(bad, tmp_path, monkeypatch):
    if bad == "drive_root":
        root = Path(Path.cwd().anchor)
    elif bad == "home":
        root = Path.home()
    else:
        root = tmp_path / "repo"; (root / ".git").mkdir(parents=True); (root / SENTINEL).write_text("x")
    monkeypatch.setenv("X4_REFERENCE", str(root)); _paths.reload()
    try:
        with pytest.raises(x4refguard.Refused):
            x4refguard.resolve_target(None, action="apply")
    finally:
        _paths.reload()

def test_apply_REFUSES_the_game_root(tmp_path, monkeypatch):
    game = tmp_path / "game"; game.mkdir(); (game / SENTINEL).write_text("x")
    monkeypatch.setenv("X4_REFERENCE", str(game)); monkeypatch.setenv("X4_GAME", str(game)); _paths.reload()
    try:
        with pytest.raises(x4refguard.Refused, match="game"):
            x4refguard.resolve_target(None, action="apply")
    finally:
        _paths.reload()

def test_UNCONFIGURED_is_exit_2_and_says_so(monkeypatch, capsys):
    monkeypatch.setattr(x4refguard, "_configured_root", lambda: None)
    rc = x4refguard.main(["status", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2 and out["state"] == "unconfigured"

@pytest.mark.skipif(os.name == "nt", reason="the POSIX twin of the Windows mechanism tests")
def test_POSIX_is_UNSUPPORTED_exit_3_never_protected(ref, capsys):
    # PIN, not skip: the disclosed gap must stay a named state (spec D13 disclosure).
    rc = x4refguard.main(["status", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 3 and out["state"] == "unsupported"
    assert x4refguard.main(["apply"]) == 3
```

The `skipif` on the POSIX twin adds **one Windows skip**; see Task 6 for the ceiling.

- [ ] **Step 2: Run, expect FAIL** (module missing):
  `uv run --frozen python -m pytest tests/test_x4refguard.py -q -rs`.
  Expected: collection error, `FileNotFoundError` on `scripts/x4refguard.py`.
- [ ] **Step 3: Implement** `resolve_target(path, action)`, `Refused`, `_configured_root()`
  (= `_paths.reference()`; it RAISES on import failure exactly like x4lock's `Unresolvable`, never
  None-by-accident), and the `main()` skeleton with the exit-code contract. Refusal order for
  `apply`: unsupported platform (3) → unconfigured (2) → explicit `--path` ≠ configured, comparing
  `os.path.normcase(resolve())` (2) → not a directory → anchor, home, game root, toolkit root, or a
  `.git` at the root (2) → sentinel absent (2). For `remove`, only the first three apply, plus the
  "non-configured path carries our exact explicit ACE" exception (Task 3).
- [ ] **Step 4: Run, expect PASS.** Same command. Expected: all pass, and on Windows exactly 1 skip
  (the POSIX twin).
- [ ] **Commit:** `x4refguard: target resolution refuses anything but the configured, unpacked reference root (no ACL code yet)`

**Confidence 92%.** Residual: `Path.home()` and the drive-anchor cases on the CI runner (INFERRED fine).

---

## Task 3: The Windows mechanism: apply, remove and status, verified and idempotent

**Files:** `scripts/x4refguard.py` (mechanism half) and `PKG/tests/test_x4refguard.py` (append).

- [ ] **Step 1: Failing tests** (Windows-only; each one SKIPs on ubuntu, and Task 6 counts them):

```python
win = pytest.mark.skipif(os.name != "nt", reason="NTFS ACLs: Windows-only mechanism (POSIX twin pins 'unsupported')")
import subprocess

@pytest.fixture
def tripwire(monkeypatch, tmp_path):
    """Fail the test if ANY icacls call names a path outside tmp_path. This is the real
    reference tree's protection against this suite."""
    real = subprocess.run
    seen = []
    def guarded(argv, *a, **k):
        if isinstance(argv, (list, tuple)) and argv and Path(str(argv[0])).stem.lower() == "icacls":
            target = Path(argv[1]).resolve()
            assert str(target).lower().startswith(str(tmp_path.resolve()).lower()), \
                "icacls aimed OUTSIDE the scratch tree: %s" % target
            seen.append(argv)
        return real(argv, *a, **k)
    monkeypatch.setattr(x4refguard.subprocess, "run", guarded)
    return seen

@pytest.fixture
def protected_cleanup(ref):
    yield ref
    # Never leave an undeletable dir in %TEMP%, whatever the test did.
    subprocess.run(["icacls", str(ref), "/reset", "/T", "/C", "/Q"], capture_output=True)

@win
def test_TRIPWIRE_fires_on_an_outside_path(tripwire, tmp_path):        # falsification twin
    with pytest.raises(AssertionError, match="OUTSIDE"):
        x4refguard.subprocess.run(["icacls", str(Path.home()), "/?"], capture_output=True)

@win
def test_apply_then_status_is_PROTECTED_with_the_exact_mask(protected_cleanup, tripwire):
    assert x4refguard.main(["apply"]) == 0
    r = x4refguard.report()
    assert r["state"] == "protected"
    assert r["mask"] == x4refguard.EXPECTED_MASK            # 65600, or 65606 under Q1
    assert r["sample_ok"] == r["sampled"] >= 2              # root + sentinel at minimum
    assert tripwire, "apply made no icacls call -- it cannot have applied anything"

@win
def test_apply_is_IDEMPOTENT_one_ace_no_second_write(protected_cleanup, tripwire):
    assert x4refguard.main(["apply"]) == 0
    n = len(tripwire)
    assert x4refguard.main(["apply"]) == 0
    assert len(tripwire) == n, "a second apply re-ran icacls"
    assert x4refguard._explicit_denies(protected_cleanup) == [x4refguard.EXPECTED_MASK]

@win
def test_remove_leaves_ZERO_deny_entries_anywhere(protected_cleanup, tripwire):
    assert x4refguard.main(["apply"]) == 0
    assert x4refguard.main(["remove"]) == 0
    assert x4refguard.report(full=True)["state"] == "absent"
    for p in [protected_cleanup, *protected_cleanup.rglob("*")]:
        assert x4refguard._deny_masks(p) == [], p          # explicit AND inherited

@win
def test_a_FOREIGN_deny_is_refused_and_left_alone(protected_cleanup, tripwire):
    sid = x4refguard._user_sid()
    subprocess.run(["icacls", str(protected_cleanup), "/deny", f"*{sid}:(WEA)"], check=True, capture_output=True)
    assert x4refguard.main(["apply"]) == 2
    assert x4refguard.main(["remove"]) == 2
    assert x4refguard.report()["state"] == "foreign"
    assert 16 in x4refguard._explicit_denies(protected_cleanup)    # WriteExtendedAttributes untouched

@win
def test_apply_REFUSES_a_root_the_user_does_not_own(protected_cleanup, tripwire, monkeypatch):
    monkeypatch.setattr(x4refguard, "_owner_is_user", lambda p: False)
    assert x4refguard.main(["apply"]) == 2                  # the lockout precondition (x4lock history)

@win
def test_a_verification_mismatch_is_exit_1_never_0(protected_cleanup, tripwire, monkeypatch):
    monkeypatch.setattr(x4refguard, "_explicit_denies", lambda p: [])   # icacls "succeeded", ACL disagrees
    assert x4refguard.main(["apply"]) == 1

@win
def test_remove_on_an_OLD_root_needs_our_exact_ace(protected_cleanup, tripwire, tmp_path, monkeypatch):
    assert x4refguard.main(["apply"]) == 0
    new = tmp_path / "newref"; new.mkdir()
    monkeypatch.setenv("X4_REFERENCE", str(new)); _paths.reload()
    assert x4refguard.main(["remove", "--path", str(protected_cleanup)]) == 0   # carries our ACE
    assert x4refguard.main(["remove", "--path", str(tmp_path)]) == 2            # carries none

@win
def test_PARTIAL_is_named_when_a_child_has_inheritance_cut(protected_cleanup, tripwire):
    assert x4refguard.main(["apply"]) == 0
    child = protected_cleanup / "libraries" / "wares.xml"
    subprocess.run(["icacls", str(child), "/inheritance:r", "/grant", f"*{x4refguard._user_sid()}:F"],
                   check=True, capture_output=True)
    r = x4refguard.report(full=True)
    assert r["state"] == "partial" and r["sample_ok"] < r["sampled"]
    assert x4refguard.main(["status"]) == 1
```

- [ ] **Step 2: Run, expect FAIL** (the functions do not exist):
  `uv run --frozen python -m pytest tests/test_x4refguard.py -q -rs -k "not POSIX"`.
- [ ] **Step 3: Implement.**
  - `_user_sid()` and `_acl(paths)`: ONE `powershell.exe -NoProfile -NonInteractive -Command <fixed script>`.
    The paths go in through the env var `X4RG_PATHS` (newline-separated), so nothing is interpolated
    into the command. The script calls `Get-Acl -LiteralPath`, then
    `.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier])` and
    `.GetOwner([...SecurityIdentifier])`, and prints JSON: `{user, items:[{path, owner, rules:[{sid, type, rights:int, inherited, inh:int, prop:int}]}]}`.
    A non-zero exit, empty stdout or unparseable JSON makes the state `error` (exit 2). It never
    becomes `absent`.
  - `_explicit_denies(p)` and `_deny_masks(p)` are filters over `_acl`.
  - `apply`: resolve (Task 2) → owner check → `foreign` check → already exact? then print
    `already protected` and return 0 without calling icacls → `icacls <root> /deny *SID:(OI)(CI)(DE,DC) /C /Q`
    → re-read. Return 0 only if exactly one explicit deny equals `EXPECTED_MASK` with OI|CI
    (`inh == 3`). Otherwise return 1, say what was found, and state that the tree may be partially
    protected.
  - `remove`: resolve → foreign check → `icacls <root> /remove:d *SID /C /Q` → re-read → 0 only if no
    deny for the SID remains on the root.
  - `status`: the sample is the root, the sentinel, and the first file found depth-first in each
    top-level subdirectory. `--full` walks everything and says how many it walked. **The sample
    scope is printed on every run** (a step that narrows data announces it).
  - `report(full=False)` returns the dict from the Interfaces section. `main` prints it with
    `--json`, or a human line otherwise. Absent prints `LAYER 2 OFF: reference\ has no deny-delete`.
  - Every refusal and every `absent` line prints the escape hatch (steps 1-4 above).
- [ ] **Step 4: Run, expect PASS** (Windows). Same command. Expected: all Task 2+3 tests pass.
  **Mutation twins**, run by hand once and recorded in the commit message: change `EXPECTED_MASK`
  to 65536 → `test_apply_then_status...` goes red; drop the idempotency short-circuit →
  `test_apply_is_IDEMPOTENT...` goes red; make `remove` skip the re-read →
  `test_a_verification_mismatch...` stays green, so add the mirrored remove-mismatch test before
  committing (one twin per clause, #26).
- [ ] **Commit:** `x4refguard: apply/remove/status for the reference deny-delete -- SID-based icacls, numeric Get-Acl verification, idempotent, refuses foreign ACEs and non-owned roots`

**Confidence 80%.** It rests on M-b (icacls idempotency), M-c (the numeric mask) and on
`/inheritance:r` producing a non-inheriting child. Task 1 raises it to 90%+. The CI runner's
`runneradmin` (admin token, UAC off) is INFERRED to honour a user-SID deny; the first CI run measures it.

---

## Task 4: Pin the behaviour: 8 delete primitives, the controls, mtime, and the known gap

**Files:** `PKG/tests/test_x4refguard_behaviour.py` (new, Windows-only).

- [ ] **Step 1: Write the tests** (they fail now only because `x4refguard.apply` cannot yet be
  imported from this file; the behaviour itself is measured, so this task PINS, it does not discover):

```python
# PKG/tests/test_x4refguard_behaviour.py
"""What the deny-delete stops, and what it does NOT, each row paired with a control
on an identical unprotected tree (a broken probe must not read as a working lock)."""
import importlib.util, os, shutil, subprocess, sys
from pathlib import Path
import pytest
pytestmark = pytest.mark.skipif(os.name != "nt", reason="NTFS ACL behaviour")

REPO = Path(__file__).resolve().parents[3]
def _load(name, rel):
    s = importlib.util.spec_from_file_location(name, REPO / rel); m = importlib.util.module_from_spec(s)
    sys.modules[name] = m; s.loader.exec_module(m); return m
x4refguard = _load("x4refguard", "scripts/x4refguard.py")
gitbash = _load("gitbash_rg", "scripts/gitbash.py")
from x4validate import _paths

def _bash():
    b = gitbash.find_bash()      # scripts/gitbash.py:45 -- never the WSL stub
    if not b: pytest.skip("no Git Bash")
    return b

def _ps(cmd, env):  return subprocess.run(["powershell.exe", "-NoProfile", "-Command", cmd], env=env, capture_output=True)

PRIMS = {
  "rm_f":        lambda t, e: subprocess.run([_bash(), "-c", 'rm -f "$T/libraries/wares.xml"'], env=e, capture_output=True),
  "remove_item": lambda t, e: _ps('Remove-Item -Force -LiteralPath "$env:T\\libraries\\wares.xml"', e),
  "del_fq":      lambda t, e: subprocess.run(["cmd", "/c", "del", "/f", "/q", str(t / "libraries" / "wares.xml")], capture_output=True),
  "os_remove":   lambda t, e: _try(os.remove, t / "libraries" / "wares.xml"),
  "rename":      lambda t, e: _try(os.rename, t / "libraries" / "wares.xml", t / "libraries" / "moved.xml"),
  "cat_force":   lambda t, e: _ps('Remove-Item -Force -LiteralPath "$env:T\\01.cat"', e),
  "rm_rf_tree":  lambda t, e: subprocess.run([_bash(), "-c", 'rm -rf "$T/libraries"'], env=e, capture_output=True),
  "ri_recurse":  lambda t, e: _ps('Remove-Item -Recurse -Force -LiteralPath "$env:T\\libraries"', e),
}
def _try(f, *a):
    try: f(*a)
    except OSError: pass

def _tree(root):
    (root / "libraries").mkdir(parents=True)
    (root / "libraries" / "wares.xml").write_text("<wares/>", encoding="utf-8")
    (root / "01.cat").write_text("cat", encoding="utf-8")
    (root / ".unpacked-and-locked").write_text("buildid 1", encoding="utf-8")
    return root

def _snapshot(root): return {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*") if p.is_file()}

@pytest.fixture
def protected(tmp_path, monkeypatch):
    root = _tree(tmp_path / "reference")
    monkeypatch.setenv("X4_REFERENCE", str(root)); _paths.reload()
    assert x4refguard.main(["apply"]) == 0
    yield root
    subprocess.run(["icacls", str(root), "/reset", "/T", "/C", "/Q"], capture_output=True)
    _paths.reload()

@pytest.mark.parametrize("name", sorted(PRIMS))
def test_the_deny_STOPS(name, protected):
    before = _snapshot(protected)
    PRIMS[name](protected, {**os.environ, "T": str(protected)})
    assert _snapshot(protected) == before, name + " deleted or moved a file under the deny"

@pytest.mark.parametrize("name", sorted(PRIMS))
def test_CONTROL_the_primitive_deletes_without_the_deny(name, tmp_path):
    root = _tree(tmp_path / "plain")
    before = _snapshot(root)
    PRIMS[name](root, {**os.environ, "T": str(root)})
    assert _snapshot(root) != before, name + " changed nothing even unprotected: the PROBE is broken"

def test_reads_still_work(protected):
    assert (protected / "libraries" / "wares.xml").read_text(encoding="utf-8") == "<wares/>"
    assert subprocess.run(["cmd", "/c", "type", str(protected / "01.cat")], capture_output=True).returncode == 0

def test_apply_moves_no_mtime_or_size(tmp_path, monkeypatch):     # the _freshness axes depend on this
    root = _tree(tmp_path / "reference"); before = _snapshot(root)
    monkeypatch.setenv("X4_REFERENCE", str(root)); _paths.reload()
    try:
        assert x4refguard.main(["apply"]) == 0 and x4refguard.main(["remove"]) == 0
    finally:
        subprocess.run(["icacls", str(root), "/reset", "/T", "/C", "/Q"], capture_output=True); _paths.reload()
    assert _snapshot(root) == before

def test_KNOWN_GAP_in_place_write_is_NOT_stopped(protected):        # F1; flips if Q1 = write-deny
    p = protected / "libraries" / "wares.xml"
    if x4refguard.EXPECTED_MASK & 0x2:
        with pytest.raises(OSError): open(p, "w").write("x")
    else:
        open(p, "w").write("x"); assert p.read_text() == "x"

def test_KNOWN_GAP_the_ROOT_itself_can_be_renamed(protected):       # result taken from M-e; pin whatever M-e measured
    ...
```

`test_KNOWN_GAP_the_ROOT_itself...` is written from Task 1's M-e result. If the rename succeeds, the
test asserts it succeeds AND that `status` afterwards reports `unconfigured`/missing, never
`protected`. If it fails, the test asserts the refusal. Either way the gap is pinned, not skipped.

- [ ] **Step 2: Run:** `uv run --frozen python -m pytest tests/test_x4refguard_behaviour.py -q -rs`.
  Expected on Windows: 8 STOPS + 8 CONTROL + 4 = 20 passed, 0 skipped. **Falsification:** temporarily
  set `EXPECTED_MASK` to Delete-only (65536) and rerun. The spike says DE alone does not hold, so
  several STOPS rows must go red. If none do, the probe is broken. Revert.
- [ ] **Commit:** `tests: pin what the reference deny-delete stops (8/8 deletes, each with a control), what it does not (in-place write, root rename), and that it moves no mtime`

**Confidence 88%.** The spike measured exactly these 8; residual risk is CI-runner variance and
Git Bash availability on windows-latest (INFERRED present).

---

## Task 5: `bin/unpack-reference.sh` integration: never lock out a re-unpack

**Files:** `bin/unpack-reference.sh`, `agent/guards/claude-hooks/check-reference-version.sh` (message
only), its generated copy under `.claude/hooks/` (regenerate, never hand-edit),
`PKG/tests/test_unpack_reference_layer2.py` (new).

Flow after this task:

1. Sentinel present, no `X4_FORCE_UNPACK` → refuse (unchanged). The message now reads: `To re-unpack:
   python scripts/x4refguard.py remove  (lifts the OS deny-delete), then rm "<ref>/.unpacked-and-locked"`.
2. `X4_FORCE_UNPACK=1` **and the deny present** → REFUSE, exit 2, with the same two steps. The script
   never lifts the deny itself: lifting is the user's explicit act (D8).
3. A successful unpack writes the sentinel (unchanged), then runs `python scripts/x4refguard.py apply`
   on Windows. Exit 0 → `Layer 2: reference\ deny-delete applied`. Exit 3 (POSIX) → print
   `Layer 2: not available on this OS (disclosed gap; see README)` and continue with exit 0. Any other
   exit → print the failure loudly and exit 1 ("it ran and something was wrong"). The unpack itself
   stays on disk.
4. The sentinel tail becomes `... reference/ is read-only and delete-protected; to re-unpack run
   python scripts/x4refguard.py remove, then remove this file.` The `buildid N` prefix is unchanged
   (parser at `check-reference-version.sh:66`).

For testability, the xrcat path becomes overridable: `XRCAT="${X4_XRCAT:-$HERE/xrcat}"`. The tests
then use a fake xrcat that writes N files. (Q4 asks whether that test seam is acceptable.)

- [ ] **Step 1: Failing tests** (Windows for the deny cases; the sentinel-text case runs everywhere):

```python
# PKG/tests/test_unpack_reference_layer2.py
import importlib.util, os, subprocess, sys
from pathlib import Path
import pytest
REPO = Path(__file__).resolve().parents[3]
UNPACK = REPO / "bin" / "unpack-reference.sh"
s = importlib.util.spec_from_file_location("gitbash_up", REPO / "scripts" / "gitbash.py")
gitbash = importlib.util.module_from_spec(s); s.loader.exec_module(gitbash)

def _env(tmp_path, ref, **kw):
    game = tmp_path / "game"; game.mkdir(exist_ok=True); (game / "01.cat").write_text("")
    fake = tmp_path / "fakexrcat"
    fake.write_text('#!/usr/bin/env bash\nwhile [ $# -gt 0 ]; do [ "$1" = -out ] && o="$2"; shift; done\n'
                    'mkdir -p "$o/libraries"; for i in $(seq 1 5); do echo x > "$o/libraries/f$i.xml"; done\n')
    return {**os.environ, "X4_GAME": str(game), "X4_REFERENCE": str(ref), "X4_XRCAT": str(fake),
            "X4_UNPACK_FLOOR": "1", "X4_TOOLKIT": str(REPO), **kw}

def _run(env):
    b = gitbash.find_bash() or pytest.skip("no Git Bash")
    return subprocess.run([b, str(UNPACK)], env=env, capture_output=True, text=True)

@pytest.mark.skipif(os.name != "nt", reason="deny-delete is Windows-only")
def test_FORCE_unpack_REFUSES_while_the_deny_is_on_and_names_the_lift(tmp_path):
    ref = tmp_path / "reference"; ref.mkdir(); (ref / ".unpacked-and-locked").write_text("buildid 1")
    env = _env(tmp_path, ref)
    subprocess.run([sys.executable, str(REPO / "scripts" / "x4refguard.py"), "apply"], env=env, check=True)
    try:
        r = _run({**env, "X4_FORCE_UNPACK": "1"})
        assert r.returncode == 2 and "x4refguard.py remove" in r.stderr
    finally:
        subprocess.run(["icacls", str(ref), "/reset", "/T", "/C", "/Q"], capture_output=True)

@pytest.mark.skipif(os.name != "nt", reason="deny-delete is Windows-only")
def test_a_fresh_unpack_ends_PROTECTED_and_the_lift_then_rm_path_works(tmp_path):
    ref = tmp_path / "reference"; env = _env(tmp_path, ref)
    try:
        r = _run(env); assert r.returncode == 0, r.stderr
        st = subprocess.run([sys.executable, str(REPO / "scripts" / "x4refguard.py"), "status", "--json"],
                            env=env, capture_output=True, text=True)
        assert '"state": "protected"' in st.stdout
        # THE ESCAPE HATCH, end to end (D8): lift, rm sentinel, re-unpack succeeds.
        assert subprocess.run([sys.executable, str(REPO / "scripts" / "x4refguard.py"), "remove"], env=env).returncode == 0
        (ref / ".unpacked-and-locked").unlink()
        assert _run(env).returncode == 0
    finally:
        subprocess.run(["icacls", str(ref), "/reset", "/T", "/C", "/Q"], capture_output=True)

def test_the_sentinel_still_parses_and_names_the_lift(tmp_path):
    ...  # run with a fake appmanifest (X4_APPMANIFEST) -> sentinel contains "buildid <n>" AND "x4refguard.py remove";
         # on POSIX the run exits 0 and prints "not available on this OS"
```

- [ ] **Step 2: Run, expect FAIL:** `uv run --frozen python -m pytest tests/test_unpack_reference_layer2.py -q -rs`.
  Expected: `X4_XRCAT` is ignored, so the real xrcat runs against an empty `01.cat` and fails, or the
  refusal text lacks `x4refguard`.
- [ ] **Step 3: Implement** the four changes above, plus the `check-reference-version.sh:75` message
  ("lift with `python scripts/x4refguard.py remove`, remove reference/.unpacked-and-locked, then run
  bin/unpack-reference.sh"). Regenerate with `uv run python tools/x4validate/scripts/gen-agent-trees.py`.
  Verify `.claude/hooks/check-reference-version.sh` changed by exactly that line (`git diff --stat`).
  **This is a hook-SCRIPT change, not a hook-DEFINITION change, so Codex re-review is not triggered
  (spike §"What this changes" 6).** The protect-bash.sh:376 message is lane E's file (see Cross-lane).
- [ ] **Step 4: Run, expect PASS**, plus the existing `test_reference_fingerprint.py`,
  `test_acf_buildid_has_one_parser.py` and `test_generate_baseline_refusals.py` (they read the script
  or sentinel) and the generator drift test `test_gen_agent_trees.py`. Expected: all green, unchanged counts.
- [ ] **Commit:** `unpack-reference: refuse a forced re-unpack while reference\ is delete-protected, apply the deny after a verified unpack, and name the lift in every recovery message`

**Confidence 85%.** ASSUMED: `_x4-env.sh` lets an env-exported `X4_REFERENCE`/`X4_GAME` win over the
toolkit's `.claude/x4-paths.env` when run with `X4_TOOLKIT=REPO`. If it does not, the test would
write into the REAL configured reference. **Step 0 of this task: READ `_x4-env.sh`'s precedence, and
make the test assert `X4_REFERENCE` resolved to `tmp_path` (echo it from the script's banner line
`Reference: ...`) BEFORE any write. Abort if not.**

---

## Task 6: Surfaces: x4lock line, README, CHANGELOG, spec correction, CI skip ceiling

**Files:** `scripts/x4lock.py` (status only), `PKG/tests/test_x4lock.py` (append), `README.md`,
`CHANGELOG.md`, `docs/superpowers/specs/2026-09-30-universal-agent-support-design.md` (Layer-2 row,
line 68), `.github/workflows/ci.yml` (skip ceiling).

- [ ] **Step 1: Failing test** in `test_x4lock.py`:

```python
def test_status_REPORTS_layer2_and_does_not_change_its_exit_code(tmp_path, monkeypatch, capsys):
    p = _fresh(tmp_path / "a.md"); monkeypatch.setenv("X4_PROTECTED", str(p))
    monkeypatch.setattr(x4lock, "_layer2", lambda: {"state": "absent", "detail": "LAYER 2 OFF"})
    x4lock._apply(p, True)
    rc = x4lock.cmd_status(None)
    err = capsys.readouterr()
    assert "reference deny-delete: absent" in (err.out + err.err)
    assert rc == 0      # informational: x4doctor is the verdict surface, x4lock's contract is unchanged
```

  plus a twin with `_layer2` raising, which must print `reference deny-delete: UNKNOWN (<error>)`,
  never `absent`.
- [ ] **Step 2: Run, expect FAIL:** `uv run --frozen python -m pytest tests/test_x4lock.py -q -rs -k layer2`.
- [ ] **Step 3: Implement** `x4lock._layer2()` (imports `x4refguard` from the same `scripts/` dir;
  any exception becomes UNKNOWN). Then the docs:
  - README "Write lock" section: add "Reference delete lock" with the commands, what it stops (8/8
    deletes), what it does not (in-place writes unless Q1; root rename; POSIX), and the 4-step escape hatch.
  - CHANGELOG `## Unreleased`: one entry.
  - Spec line 68: change "read-only attribute **plus** inherited deny-delete" to the MEASURED truth:
    "inherited deny-delete (D14) plus the `.unpacked-and-locked` sentinel; the read-only attribute
    is not applied to `reference\` (MEASURED 2026-10-02: 0 of 3,429 sampled files)". Keep the old
    wording struck through and dated (SUPERSEDED convention).
  - `ci.yml`: count the new Windows-only tests that SKIP on ubuntu by reading the CI `-rs` output, never
    by arithmetic. The plan-time estimate is Task 3's 9 + Task 4's 20 + Task 5's 2 = 31 ubuntu skips,
    and +1 windows skip (Task 2's POSIX twin). Add a bucket line, e.g. "`31  NTFS deny-delete
    (x4refguard): Windows-only mechanism; POSIX twin pins 'unsupported'`", and raise the ceilings by
    the MEASURED counts. **Better, if Q2 is answered "defer":** collapse Tasks 3 and 4 into parametrized
    tests behind one module-level `pytestmark`, which does not reduce the count (each parameter id
    skips). So accept the bump and classify it.
- [ ] **Step 4: Run** `tests/test_x4lock.py` (expected: 41 + 2 passed, per the audit's 41-pass
  baseline) and `uv run python gates/claude_md_budget.py` (expected: unchanged, since CLAUDE.md is untouched).
- [ ] **Commit:** `x4lock status reports Layer 2; README/CHANGELOG document the reference delete lock and its escape hatch; spec Layer-2 row corrected to the measured state; CI skip ceiling raised by the classified Windows-only count`

**Confidence 90%.** The skip count is the soft spot: measure it from the first CI run, never compute it.

---

## Task 7: USER STEP: apply to the real `reference\`

**Files:** none. Run by the user (or by the agent at the user's explicit go-ahead), from **cmd.exe or
Git Bash, never the Claude PowerShell tool**.

- [ ] `python scripts/x4refguard.py status --json` → expected `absent`, `owner_is_user: true`, `sentinel: true`.
- [ ] `python scripts/x4refguard.py apply`. Time it; Task 1 M-a predicts the duration (INFERRED,
  extrapolated from 100k files). Run it in the background if the prediction exceeds 10 min.
- [ ] `python scripts/x4refguard.py status --full --json` → expected `protected`, `sample_ok == sampled`
  over all ~510,711 files.
- [ ] Re-run the freshness check (`x4effective` banner): expected NO content-axis change (M-d).
- [ ] Record the real-path result (duration, counts) in the Task 1 measurements doc. This closes
  the spike's "Not measured: the same deny on the real paths". Commit the doc.

**Confidence 75%.** Unmeasured: propagation over 510k real files, and whether Windows Defender or an
indexer holding a handle makes some files fail (icacls `/C` continues, and `--full` status names them
as `partial`).

---

## Files touched (union)

- `scripts/x4refguard.py` (new)
- `scripts/x4lock.py`
- `bin/unpack-reference.sh`
- `agent/guards/claude-hooks/check-reference-version.sh` → regenerated `.claude/hooks/check-reference-version.sh`
- `tools/x4validate/tests/test_x4refguard.py` (new)
- `tools/x4validate/tests/test_x4refguard_behaviour.py` (new)
- `tools/x4validate/tests/test_unpack_reference_layer2.py` (new)
- `tools/x4validate/tests/test_x4lock.py`
- `README.md`
- `CHANGELOG.md`
- `docs/superpowers/specs/2026-09-30-universal-agent-support-design.md`
- `docs/superpowers/measurements/2026-10-0X-layer2-reference-acl.md` (new)
- `.github/workflows/ci.yml`

## Cross-lane dependencies

**Needs from others**

- **E (x4guard hardening):** (1) change the `protect-bash.sh:376` message from "Remove the sentinel
  first" to "Lift the OS deny-delete (`python scripts/x4refguard.py remove`, the user's step), then
  remove the sentinel". (2) Per Q3, a rule that gates an agent running `x4refguard.py remove`, raw
  `icacls ... /remove`, or `/reset` against the configured reference root. (3) Coordinate on F1: if Q1
  = write-deny, then F1 is closed at the OS layer **for `reference\` only**, and E's parser work for F1
  can scope to the other protected locations.
- **B (Codex adapter / .rules):** a `prompt` prefix rule for `python scripts/x4refguard.py remove`
  (and `uv run ... x4refguard.py remove`), per Q3. `.rules` are fail-closed and independent of hook
  review, which makes them the right layer for this.
- **C (installers / x4doctor):** x4doctor's Layer-2 row consumes `status --json` and maps `state` →
  live / not live / unknown (`protected` → live; `absent`/`partial`/`foreign` → not live;
  `error`/`unconfigured` → unknown; `unsupported` → "not available on this OS"). If C's installer
  work runs `install.sh --unpack` in tests, that path now applies the deny on Windows, so its fixtures
  need the `/reset` teardown. **F9 (x4lock's manifest omits AGENTS.md) touches `scripts/x4lock.py`**:
  Task 6 here changes only `cmd_status` and adds `_layer2`, so the merge is mechanical, but sequence it.
- **A (instruction split):** none. This lane adds nothing to CLAUDE.md or AGENTS.md. If A wants one
  line in the Codex addendum ("`reference\` is delete-protected at the OS level; deletes fail with
  Access denied, by design"), it costs about 110 bytes against the 32 KiB budget. That is A's call.

**Others need from D:** the `status --json` schema and exit codes (C); the exact `remove` command
shape (B, E); the measured mask constant (anyone asserting it).

## Questions for the user

**Q1. Should the deny cover WRITES on `reference\` too (closing audit F1 for this tree), or stay
delete-only as D14 decided?** The measured trade-off:

| Option | Stops deletes | Stops `open(p,'w')` (F1) | Stops `Copy-Item -Force` overwrite | Stops new files in ref | Cost / risk |
|---|---|---|---|---|---|
| **A. Delete-only `(DE,DC)`** (D14 as decided) | 8/8 MEASURED | **no** (MEASURED: in-place writes work) | no | no | MEASURED safe: no Synchronize, removable |
| **B. A + read-only attribute on every file** | 8/8 | yes: x4lock MEASURED 11/14 on single files | **no** (`-Force` clears the bit, x4lock MEASURED) | no | about 510k attribute writes per apply and lift; a re-unpack must clear it first; works the same on POSIX |
| **C. One ACE `(DE,DC,WD,AD)`** | 8/8 (same ACE) | yes: INFERRED, Task 1 M-f measures it | yes: INFERRED (WriteData is denied whatever the attribute) | yes | **no extra propagation cost** (one ACE). The withdrawn `(W,…)` failed because `W` contains SYNCHRONIZE and WDAC; WD/AD contain neither (INFERRED from the rights definitions, measured in M-f). It also blocks any program that opens reference files read-write "just in case" (none known; INFERRED). |

**Recommendation: C, conditional on Task 1 M-f passing all six checks (reads OK, F1 blocked, removable,
0 entries left, with controls).** It closes F1 for the one irreplaceable tree without any parser
change, and costs nothing over A. If any M-f row fails, ship A and leave F1 open for lane E. Either
way the tests pin the result (`test_KNOWN_GAP_in_place_write...` flips on the mask).

**Q2. Linux/macOS: Windows-only with the gap disclosed, or build the POSIX equivalent now?** The
equivalents: Linux `chmod a-w` on every **directory** (unlink, rename and create need write on the
directory, so this is the true analogue of DE,DC; owner-reversible, no root). `chattr +i` needs
root (CAP_LINUX_IMMUTABLE) and also blocks writes. macOS `chflags -R uchg` is owner-settable but
blocks writes too, or use the same directory chmod. All unmeasured. **Recommendation: Windows-only for
v4.0.** `status`/`apply` exit 3 `unsupported`, the README discloses it, and the POSIX twin test pins
it. Codex on Linux/macOS is already blocked on M9, and the directory-chmod variant can follow as its
own measured task.

**Q3. Who may run `x4refguard.py remove`?** D8 says only the user lifts a protection. **Recommendation:
Claude → `ask` (protect-bash, lane E). This is a precursor to deleting inside an X4 directory, a
category CLAUDE.md already reserves for `ask`. Codex → `.rules` `prompt` (lane B), which asks
interactively and refuses non-interactively.** A raw `icacls /remove` or `/reset` aimed at the reference
root gets the same treatment. Accepted residual risk: an opaque interpreter (`python -c` calling
icacls) bypasses both. That is the same F1 shape; the protection stops accidents, not intent.

**Q4. Accept the `X4_XRCAT` override in `bin/unpack-reference.sh` as a test seam?** Without it the
unpack-to-protected flow cannot be tested end to end without a real XRCatTool and game. **Recommendation:
yes.** It is an env override like the existing `X4_UNPACK_FLOOR`/`X4_FORCE_UNPACK`, and it only
changes which binary runs.

## Confidence summary

| Task | Confidence | What raises it |
|---|---|---|
| 1 Measure | 90% | n/a (it is the measurement) |
| 2 Resolution/refusals | 92% | n/a |
| 3 Mechanism | 80% | Task 1 M-b and M-c; first windows-latest CI run (runneradmin honouring the user-SID deny) |
| 4 Behaviour pin | 88% | first CI run (Git Bash present, primitives behave as on this machine) |
| 5 Unpack integration | 85% | Step 0: READ `_x4-env.sh` precedence and assert the test's reference resolves to `tmp_path` before any write |
| 6 Surfaces/CI | 90% | read the skip counts from CI `-rs` output |
| 7 Real apply | 75% | M-a's propagation timing; a `--full` status after apply |

## Gate plan

- **Per task (focused only):** Task 2 and 3: `tests/test_x4refguard.py`. Task 4:
  `tests/test_x4refguard_behaviour.py` plus its DE-only falsification run. Task 5:
  `tests/test_unpack_reference_layer2.py`, `test_reference_fingerprint.py`,
  `test_acf_buildid_has_one_parser.py`, `test_generate_baseline_refusals.py`, `test_gen_agent_trees.py`.
  Task 6: `tests/test_x4lock.py`, `gates/claude_md_budget.py`.
- **Mutation twins** (by hand, recorded in commit messages): `EXPECTED_MASK` → 65536; idempotency
  short-circuit removed; verification re-read removed (apply and remove separately); tripwire
  prefix check inverted; `_layer2` exception → "absent".
- **Lane end, once:** the full pytest suite on Windows (`uv run --frozen python -m pytest -q -rs` from
  PKG, backgrounded, about 30 min), `scripts/scan-identifiers.py` (no personal paths in the new tests
  or docs), the generator drift check, the hook suites touched by the regenerated
  `check-reference-version.sh` (`scripts/test-hooks.sh`), and `X4_MAX_SKIPS` checked against the
  measured counts on both OSes. Then Task 7.
- **Leak check after every Windows run:** no directory under `%TEMP%\pytest-of-*` may still carry a
  deny ACE. Every fixture does a `/reset /T` teardown. Spot-check with `x4refguard status --path` from a
  script file.


## Amendments -- 2026-10-02 (user decisions; binding, supersede the text above)

Read DECISIONS.md in this folder first. Changes to THIS lane:
- **#14:** delete+WRITE deny if the scratch measurement shows reads still work and it is removable; else delete-only. Record which.
- **#15 changed (user override): Linux/macOS are IN SCOPE, best-effort** -- not Windows-only. Implement the POSIX branch: Linux `chattr +i` when privileged, else `chmod a-w` on dirs+files; macOS `chflags uchg`, else `chmod`. `status` reports exactly what was applied and what was not (never OK for a layer it could not apply). Unit tests on disposable dirs; run on CI ubuntu, READ results per test. README: 'best effort, not device-tested'. Exit 3 'unsupported' is now only for a platform with NO available mechanism.
- **Measured 2026-10-02 (measure-D.md) -- #14 RESOLVED: delete+WRITE.** Use `(OI)(CI)(DE,DC,WD,AD)`, EXPECTED_MASK = 65606 (not the DE,DC-only mask). Reads 12/12 work; writes 20/20 and deletes/renames 15/15 blocked; removable by the same user 47/47 (105,051 -> 0 deny ACEs). DE,DC alone let 17/20 writes through, so WD,AD is what closes F1 for reference. Cost ~8 s per 100k files (INFERRED ~40 s for the real 510k tree); idempotent (merges into one ACE); mtime/size unchanged 100k/100k.
- **Judge every delete/write probe by the DISK, never the exit code:** `del /f /q` exits 0 while printing 'Access is denied' (MEASURED).
- The deny is liftable by any agent as the same user with one `icacls /remove:d`; only #16 gating (Claude ask, Codex .rules prompt) stops that -- lane E/B must gate raw `icacls /remove`/`/reset` on the reference root too.
- Still unmeasured: the real 510k tree, Administrators-owned files, the CI runner account, POSIX.

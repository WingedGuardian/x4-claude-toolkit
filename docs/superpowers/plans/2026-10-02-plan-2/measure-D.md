# Lane D Task 1: Layer-2 reference ACL measurements (scratch only), 2026-10-02

**Scope:** every ACL operation targeted only trees under `scratchpad\plan2\measureD\`. The probe
(`layerD_probe.py`) resolves each target and calls `os._exit(99)` unless the target sits strictly
under that folder. Self-test: a target outside it gave rc 99, and so did the folder itself. The real
`reference\`, the game root and the toolkit repo were not touched. Nothing was committed.

**Machine:** Windows 11 26200, a standard (unelevated) user account, unelevated session, user-owned
scratch trees (`owner == user SID` was checked by Get-Acl).

**Instruments:**
- `icacls` writes the ACEs, using the SID form `*S-...`.
- Verification reads `Get-Acl ... GetAccessRules(..., SecurityIdentifier)` as numeric JSON.
- Every effect is judged from **filesystem state**: the content bytes, whether the file exists, and
  the read-back bytes. Exit codes are not used, and the first item below shows why.

**Predictions:** `measureD/PREDICTIONS.md`, written before any run. Raw output: `measureD/{mbe,mf,cmdfix,ma}.out`.

## Verdict for decision #14: delete+WRITE deny `(OI)(CI)(DE,DC,WD,AD)` is VIABLE (MEASURED)

- **(a) Reads work: 12 of 12 read primitives**, each with a passing control. The 12 are:
  - Python: `open(r)`, `read_bytes`, `mmap` ACCESS_READ, `ElementTree.parse`, `os.walk`
  - PowerShell `Get-Content`, `cmd type`, `bash cat`
  - copy-out: `shutil.copy2`, `Copy-Item`, `cp`, `cp -p`

  Each copied-out file carried 0 deny ACEs, accepted an overwrite and could be deleted. A copy out of
  `reference\` into `dev\` is therefore unaffected.
- **(b) Writes blocked: 20 of 20 write primitives are blocked**, and the file stays byte-identical:
  - Python: `open(w)`, `write_text`, `os.truncate`, `open(a)`, `open(r+b)`, `shutil.copy2` over a file
  - PowerShell: `Copy-Item -Force` over a file (this is x4lock's `-Force` gap, and it is closed here), `Set-Content`
  - bash: `>`, `>>`, `sed -i`
  - cmd: `echo x>`, `copy /y` over a file
  - replace a file: `os.replace` onto it, `Move-Item -Force` onto it
  - create: new file by `open`, by `touch` and by `copy2`-in; `os.mkdir`, `mkdir -p`

  **Deletes blocked: 15 of 15 delete/rename primitives:**
  - Task 4's 8: `rm -f`, `Remove-Item -Force`, `del /f /q`, `os.remove`, file rename,
    `Remove-Item` of `01.cat`, `rm -rf` of a subtree, `Remove-Item -Recurse`
  - extras: `shutil.rmtree`, subdir rename, `mv` out, `rmdir` of an empty dir, `rm` of the
    sentinel, `rm -rf` of the root, `rd /s /q`

  Every blocked case failed with an access-denied error, and **every one of the 47 cases took effect
  on its un-denied control tree.**
- **(c) Removable by the same unelevated user: 47 of 47** `icacls /remove:d *SID` returned rc 0.
  Afterwards Get-Acl over every object in the tree found **0 deny ACEs**, and every tree was then
  deleted. At scale, 6 of 6 removals on 105,051 objects left 0 `(DENY)` lines, against 105,051 while
  the deny was on. The same counter, run on the deny, is the control that shows it can detect one.
- Cross-check with `DE,DC` only, on the same 47 cases:
  - deletes: 15 of 15 blocked
  - reads: 12 of 12 work
  - writes: **17 of 20 SUCCEED.** Only `sed -i`, `os.replace` onto a file and `Move-Item -Force` onto
    a file are blocked, because each needs DELETE on the target.

  So `WD,AD` is exactly what closes F1, as predicted.

## M-a to M-e

| # | Result | Tier |
|---|---|---|
| M-a | 100,000 files in 5,000 leaf dirs (105,051 objects). Median time over 3 reps each: DE,DC apply **7.9 s** and remove **7.0 s**; DE,DC,WD,AD apply **7.6 s** and remove **8.4 s**. Range 6.0-9.6 s. Sleep check: `perf_counter` agreed with `QueryUnbiasedInterruptTime` on 12 of 12 timings (no suspend). Build took 33 s and teardown 12 s. | MEASURED |
| M-a extrap. | 510,711 files: about **40 s** to apply and **36-43 s** to remove. Linear, at a fan-out unlike the real one. | INFERRED |
| M-b | Applying the same deny twice leaves **1** explicit deny ACE on the root (2 of 2 masks), and every object carries exactly 1 deny. Applying DE,DC and then DE,DC,WD,AD **merges** into one ACE of 65606. A tool that re-applies does not stack ACEs. | MEASURED (8-object trees) |
| M-c | Root: rights **65600** / **65606**, `IsInherited` False, InheritanceFlags 3, PropagationFlags 0. Child: the same mask, `IsInherited` True. Every M-f case also checked a file child (`libraries\wares.xml`) before running: 94 of 94 had 1 inherited ACE of the expected mask. No Synchronize bit. | MEASURED |
| M-d | `st_mtime_ns` and `st_size` were unchanged on **100,000 of 100,000** files after apply and again after remove, for both masks. The freshness axes do not move. | MEASURED |
| M-e | **Root rename SUCCEEDS** under either mask: 2 of 2, plus 2 of 2 controls. The parent grants delete-child. Inside the renamed root, the children still refuse delete (2 of 2; the controls deleted). This is a known gap to pin, as predicted. | MEASURED |

## Findings that matter for the plan

1. **`del /f /q` exits 0 on Access denied.** This is MEASURED in every DE,DC,WD,AD run of `del_fq`:
   rc 0, with "Access is denied" printed. Any test or status check that judges `del` by its exit code
   reads a blocked delete as a success. Task 4 must judge by filesystem state, as this probe did.
   `rd /s /q` returned rc 5 and was honest.
2. **The deny can be lifted by the same user, so by any agent that runs as that user.** (c) is a
   requirement, but it also means that `icacls /remove:d` is one command away for an agent. The
   gating in Q3/#16 (Claude `ask`, the Codex `.rules` prompt) is the only thing that stops it.
   INFERRED from (c); no agent was tested.
3. Writing ACLs and attributes is not denied (no WA, WEA, WDAC or WO in the mask). So `attrib +r`
   and similar commands still work on the tree. This is by design and was not probed.
4. A child that gains an **explicit allow** ACE, for example after `/inheritance:r`, is INFERRED to
   bypass the inherited deny (canonical ACE order). Not probed here; Task 3's `partial` test covers it.
5. Not measured:
   - the real `reference\` fan-out (510,711 files)
   - files on another volume or owned by Administrators
   - GitHub runner `runneradmin`
   - Linux/macOS (#15, best effort)

**Recommendation for Task 3:** fix the mask at **`(OI)(CI)(DE,DC,WD,AD)`, EXPECTED_MASK = 65606**.
The tests for it:
- assert the mask numerically
- judge every primitive by state, never by rc
- pin the M-e root-rename gap as a known allowance

## Cleanup (MEASURED)

- Every deny added was removed: 47 case trees, 4 M-e trees, 3 M-b trees and 6 M-a cycles.
- Every scratch tree was deleted. `measureD\` now holds only the predictions file and the `.out` logs.
- A final `icacls measureD /T` found **0** `(DENY)` lines in 46 output lines.

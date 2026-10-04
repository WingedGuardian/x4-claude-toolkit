# Individual-tool repairs — 2026-10-02

Status: repairs installed and verified after review and final E2E. The additional
store-metadata failure found during E2E is fixed, installed, and included in the
final full-suite run.
Approved plan: `docs/superpowers/plans/2026-10-02-tool-fixes.md` in the repository (not
shipped in the release bundle).
Historical [audit](2026-10-01-tools.md) remains the pre-fix evidence.

## Changes and compatibility

- TA01: BaseX attr accepts lexical QNames only; injection inputs refuse before JVM.
- TA02: only the documented restricted grammar authorizes raw-query zero claims.
  Unrecognized queries still run and return positives; their zeros return 4. This
  deliberately tightens earlier FLWOR behavior. Token scans are diagnostic only.
- Optional paging: refs/attr/xq accept nonnegative --limit/--offset, defaults
  unlimited/zero, limit 0 unlimited. Full sequence counts and semantic checks run
  before paging whole items. Unsupported requested wrappers refuse 2; unlimited
  prolog fallback remains. Output limits do not promise reduced query work.
- TA03: xref parses every row strictly and digests both TSV and exclusions in the
  freshness sidecar. Integrity failures refuse 2. Unsigned legacy positives warn;
  absence needs both integrity and current source freshness. Explicit rebuild only.
- TA04/05: malformed DEFLATE and unreadable/incompatible SQLite stores return 2;
  valid reads and ordinary SQL error behavior remain. SQLite URI filenames are
  escaped before mode=ro. Reader edits intentionally invalidate engine freshness.
- TA06: complete template validation before output; explicit offline template
  option, preserved file permissions, invalid templates rc 2 without retrieval.
- TA07/08: legacy deployment uses explicit guards under -O, batch preflight,
  containment and reparse-point rejection. Existing file/directory conflicts
  refuse the entire batch before writes. Apply remains nontransactional.
- Additional measured x4cat bug: index crashed printing Unicode on cp1252 pipes
  after completing work. CLI streams now use UTF-8, with a real subprocess regression.

## Initial verification (before final review)

Deploy: 14 passed, including four actual Windows junction placements, normal/-O
ownership/manifest refusals, batch refusal before first write, and scratch apply.
BaseX: 304 passed, including real disposable BaseX DB execution and paging controls.
Xref group: 41 passed. Save/effective group: 61 passed. Latest combined boundary
group: 55 passed. x4cat full suite: 279 passed / 10 skipped (eight unavailable game
schema inputs, two Windows symlink privileges). These counts describe separate
runs, not a summed total. Additional final runs supersede these counts below.

Intermediate toolkit full suite exposed one intentional-contract test expecting
a bare helper row list to authorize absence; corrected to require explicit
certification and added an unverified-default test. Initial environment failures
used the WSL bash stub; the audit runner now puts Git Bash first. Full suite
history scanning is slow under concurrent session load; runtime is not a verdict.

## Final review / E2E

Independent review found two important issues, both repaired with red/green
regressions: deploy file/directory conflicts allowed partial batch writes, and
xref freshness metadata parsing could escape the error boundary. Shape conflicts
now refuse before any batch write (both directions, normal and optimized Python).
Consumed metadata types and freshness comparison now return actionable refusal.
No additional critical or minor findings were confirmed by the reviewer. Later
E2E reproduced an additional effective-store failure: damaged JSON freshness
metadata in a structurally valid SQLite store escaped as AttributeError/KeyError/
TypeError. A narrow metadata-boundary conversion preserves SQL dispatch behavior.
Six damaged-metadata cases failed before the fix; all 20 store boundary tests
now pass, including a valid stale-store/read-only control. This follow-up was
reviewed locally after the independent review; no second agent review cycle.

Post-review targeted checks: deploy 18 passed; xref integrity 23 passed. Scratch
CLI checks passed for every suite entry point, corrupt inputs, disabled-mod
merging, dependency precedence, packed validation, save parsing, debug triage,
offline scaffolding and archive byte round trips. Real effective-store, collision,
xref, stats, similarity, copied registry, debug and save checks passed their
stated contracts. Vanilla find_station locations match an independent XML parse.
x4cat full suite: 279 passed / 10 skipped. All eight schema tests skipped by its
hardcoded foreign game path were separately run against this installation:
16 passed / 0 skipped in that file, using an in-memory path override and removing
only the decorator capturing the absent foreign path. Two symlink tests still
require a Windows privilege; actual junction regressions ran.

Final toolkit suite: 2914 passed / 49 skipped, including the metadata follow-up;
the five installer test files listed in the audit harness remain outside this
individual-tools scope. Earlier elapsed times included a long execution pause
and are not performance evidence. Generated agent tree and CLI reference checks
passed on the installed toolkit (39 tests); generation is current. The last
CLI-only metadata follow-up is outside ENGINE_SOURCES, so existing scratch
producer fingerprints remain valid; corpus and BaseX producer checks are unaffected.

Post-review real BaseX builds and queries completed. Raw coverage: 13920 readable
of 13931 documents, 11 named malformed exclusions (build rc 3). Effective coverage:
10970 indexed documents, 213 unproduced paths and 11 malformed overlays disclosed
(build rc 0). All ten real paging/refusal checks passed. For example, attr name
returned 113192 raw / 112812 effective total items while displaying five, preserving
the full totals. These are sequence items, not document or entity counts.

Full corpus: 125 mods / 250 reports, zero changed findings, zero crashes, no
duplicates or population changes. Existing findings remain (ordinary 1343 errors
across 36 mods; update 689 across 35 mods, one degraded report). This proves
validator compatibility, not that the modlist is error-free.

Protected-input comparison: 526564 metadata records unchanged before and after
the final controls, including installed-command checks. It covers this final
interval, starts after corpus launch, and compares size/mtime rather than all
content bytes. All writes remained in scratch outputs or authorized tool sources.

Installed-source checks match reviewed source text, accepting external Git CRLF
conversion. Actual uv launchers (without PYTHONPATH overrides) and scratch
workflows passed, including corrupt xref/save/store refusals, 18 deploy tests,
279 x4cat tests / 10 disclosed skips and pinned-template scaffolding. Installed
BaseX paging totals match independent native counts (371 raw / 352 effective ore
references, three displayed). Existing effective BaseX production data correctly
warns stale after reader edits; it was not rebuilt. The x4cat uv.lock hash stayed
identical. Official pack -> installed homegrown list/extract found the expected
XML and reproduced the input bytes exactly.

Two installation-harness expectations failed first: a captured default cwd
selected the audit checkout, and a bounded page was incorrectly required to
contain a ware rather than valid region references. The corrected run asserts
the import origin and native counts. A separate archive listing needed ext_01.cat
with prefix ext_; its former empty result is not counted as reader coverage.
Failing attempts remain archived. No live game, Nexus or production mod deploy.

Confidence at completion: deploy 97%, attr validation 98%, restricted
zero grammar 94%, paging 95%, xref 97%, save handling 98%, store handling 97%,
template handling 97%, UTF-8 CLI diagnostics 98%. These are judgment estimates
about the specified contracts, not statistical measurements or live-game claims.

Four additional real installed `uv` invocations verified three malformed metadata
vectors refuse with rc 2 and a valid stale-store read succeeds with its warning;
all four SQLite inputs remained byte-identical.

Installed code revisions: toolkit `1d7923b`, `25e261f`, `34d3fde`, `2e0273a`,
`467d379`; dev helper `9c23b2d` (including `6416920`); x4cat `6807545`.
Parallel uncommitted toolkit changes and the x4cat lockfile were preserved.
Production artifacts were not rebuilt; live-game X4 Live E2E remains outside
these offline checks.

## Legacy-tool handoff

The suite installation is the toolkit's tools/x4validate directory. The older
external location named in the game-root AGENTS.md is absent; the agent-support
handoff records that stale instruction. No duplicate suite is created.

Both local tools are retained as requested. Their repositories own the patches;
the toolkit does not silently become their source or deployer. See the
handoff note `docs/handoffs/2026-10-02-legacy-tools.md` in the repository (not shipped in
the release bundle).

## Workflow rulings

- Native PowerShell progress/evidence ledger replaces the skill shell wrappers;
  isolation and red/green requirements remain, with no behavior cost.
- refs matches references, not definition id; corrected the fixture accordingly.
- The measured cp1252 index crash is fixed with UTF-8 CLI streams (98% confidence);
  the compatibility cost is explicitly UTF-8 output.
- One independent final review, followed by tested corrections; no second review
  cycle. The later metadata follow-up is disclosed above and reviewed locally.
- Audit worktrees and raw evidence are retained for inspection. Cleanup is
  deferred rather than discarding verification evidence; the cost is local disk.

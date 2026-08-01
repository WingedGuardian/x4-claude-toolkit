# Changelog

## v2.01

**If you installed v2.0, take this update.** v2.0 shipped an installer that wrote one set of
environment variables and Python tools that read a different set. They overlapped on exactly one
name (`X4_REFERENCE`), and nothing bridged them — so on the **`separate`** and **`global`**
layouts, two of the three the README documents, a *successful* install still left `--tier b`,
`x4compat`, `x4stats`, `x4similar`, `x4xref`, `x4modlist` and `x4effective` resolving against
CWD-relative paths. They did not error; they looked in the wrong place and reported finding
nothing. The README's claim that "nothing is hardcoded" was true of the shell half and false of
the Python half.

### Fixed — the installed toolkit is actually wired up

- **One resolver for every location** (`x4validate/_paths.py`), layered: real environment →
  `.claude/x4-paths.env` → an explicit (empty) local seam. Within each layer, every alias *and*
  derivation is tried before dropping to the next. Both naming schemes work; the installer's names
  (`X4_GAME`, `X4_EXTENSIONS`, `X4_PROFILE`, `X4_MODS`, `X4_REFERENCE`) are the ones to teach.
- **`x4validate --paths`** — prints what resolved and which config file was read, marking anything
  that does not exist. Run it first when a result looks impossible.
- **Bare `--debug` was Windows-only.** It built `~/Documents/Egosoft/X4/<id>/debug.txt` — the
  Windows layout, hardcoded — so it could never work on Linux (`~/.config/EgoSoft/X4/<id>`) or
  macOS, both of which this toolkit documents and supports.
- **Two silent degradations closed.** With the game root unresolved, the packed mini-DLC dropped
  from 8 DLC to 6 with nothing reported (every patch against Hyperion/Envoy content quietly
  became "cannot verify"); an unresolved registry read as "0 mods" rather than "not configured".
  Both now name the loss.
- **Git Bash paths now work.** `install.sh` detects Steam at `/c/Program Files (x86)/...` under
  Git Bash, and the config file has always promised either style is fine. Python cannot open
  `/c/...` on Windows — it becomes `\c\...`, which does not exist. So the *first command the
  README gives a Windows user* wrote a config the Python silently could not use. `/c/...` and
  `/mnt/c/...` are now translated on Windows and left untouched on Linux, where they are
  legitimate paths. **Found by red-teaming this release's own install flow.**
- **`X4_TOOLKIT` is no longer claimed to be set for you.** The docs said "(the installer does)";
  no installer ever did. Both installers now print the exact `setx` / `export` command at the end,
  and the READMEs give it instead of the claim. Without it the config file is found only by
  walking up from the current directory, which fails from the game folder — the case the docs
  themselves call out as common.
- **Nothing is guessed.** An unresolved location prints `(unresolved)`; the Steam workshop path is
  derived only when the install really has that shape, because a guessed path scans nothing and
  would report "no mods" as though it were a finding.

### Fixed — patch-time and runtime are two different trees

A `sel=` sees only what has loaded by your mod's turn; "does this id exist?" is answered after
*every* extension has loaded. Tier B used one tree for both, which is wrong in both directions —
measured on a real pair of installed mods: 3 false alarms in one direction, and one genuine
runtime defect missed in the other (a loadout referencing a connection that the winning component
does not have). The trees are now separate.

### Added — schema validation of merged data files (`--update`)

42 vanilla files under `libraries/` declare an XSD, and mods ship them as `<diff>`, so the
document that has to be valid is the *merged* one. This catches a class nothing else here can: a
patch whose selector matches and whose XML is well-formed, but which leaves the merged document
structurally broken — measured case, a mod that `<remove>`s `<production>` and orphans the
`<limits>` sibling 30 times.

It is **differential**, which is not a refinement but the only workable form: Egosoft's own
base+DLC data produces 66 errors against Egosoft's own bundled schemas, so an absolute check would
open with 66 false positives on a mod that changed nothing. Enumeration failures naming a race or
faction your modlist actually defines are suppressed and counted; one naming something nothing
defines is reported.

### Added — `gates/`, so the engine-fidelity numbers are reproducible

The four harnesses that measure this tool against the engine rather than against itself:
`oracle.py` (diff layer, 234/234 ops, 0 false OK), `oracle_index.py` (index layer, 12/12),
`regress.py`, `schema_sweep.py`. They take every input from your configuration and **skip with a
named reason (exit 2)** when something is missing, rather than running empty and printing like a
pass. You supply your own captured `debug.txt` via `$X4_ORACLE_LOG` — a real log names your mods
and paths, so none is shipped. What transfers is the bars, not the counts.

### Measured and deliberately NOT shipped

An MD ordering lint (flagging `signal_cue_instantly` to a cue that cannot be listening yet) was
built and dropped. It scored **0 false positives** across 1,094 vanilla call sites and 2,912 in
installed mods — and also **0 on a saved copy of the exact bug it was written for**. The real
defect reaches its target through a variable, from a second cue, so a rule keyed on a literal name
cannot see it; widening it to catch that fires 407 times in vanilla code that demonstrably works.
A rule with no demonstrated true positive is not quiet, it is inert. Recorded here because a
changelog that only ever adds is a sales sheet.

### Also

- 243 → **264** tests.
- Docs: the root README now shows how to actually invoke `x4validate` and links to the
  configuration model; `x4-paths.env.example` states that `$VAR` expands and that the file is
  parsed, never executed; `gates/README.md` says up front that it is for contributors only.
- Every number above traces to a gate run, not to a claim.

## v2.0

**The toolkit is no longer Windows-only, and no longer assumes one folder layout.** Plus two
community contributions, a round of safety-hook fixes found by red-teaming the install flow, and
a `debug.txt`-driven oracle that measured x4validate's verdicts against what the engine actually
did — closing every gap it found.

Major version because the install model changed: there are now three supported layouts and every
X4 location is configurable. Existing v1.x users keep working — the in-game layout is unchanged
and the hooks fall back to the old folder-name patterns when nothing is configured.

### Fixed — x4validate: validated against the ENGINE, not against itself

x4validate's model of the engine had never been checked against the engine's own output. This
built and ran that check: a `debug.txt`-driven oracle that measures x4validate's verdicts against
what X4 actually did, op-for-op. Every defect below was found and fixed using it — not by
inspection. Tests grew to 170, and none of them are cosmetic: each is a real-data regression test
for a real false result, several mutation-verified against the pre-fix code to confirm they
actually catch it.

**The tool was blind to 9 of the 10 mods with the errors that matter, and said "OK":**
- **Packed mods were never sel-checked, and reported a clean pass.** `iter_diff_files` walked
  `mod_dir.rglob("*.xml")`, which finds nothing inside a `.cat`/`.dat` archive — so the core
  sel-resolution check silently examined zero ops on any packed mod and printed
  `OK: no issues found`, exit 0. Sibling code (`iter_mod_xml_roots`) already read packed mods via
  the catalog reader; the core check simply never used it. Measured against a real debug.txt: **9
  of 10 mods with engine-rejected diff ops are packed** — this covered most of the real damage.
  Fixed by delegating to the packed-aware iterator; a mod where nothing could be read is now a
  WARN, never a silent pass.
- **`--debug` correlation missed 74% of the log, and 100% of the class it exists to catch.**
  `_debuglog.parse_debug` recognized 4 error shapes; a real 2463-line `debug.txt` showed it
  returning 645 (26%) — and **zero** of the 453 "diff op matched 0 or >1 nodes" lines, the
  RFC-5261 failure this tool is built around. Two new shapes fixed it (453/453 now captured),
  after finding two parser traps: the engine omits the file extension on these lines (`'…\
  material_library'`, not `…material_library.xml`), and the selector itself contains single
  quotes (`@id='ore'`) in 91% of real cases, which a naive `[^']*` capture group truncates.
- **Tier B applied the mod under test LAST — the engine does not.** Cross-mod validation merged
  every *other* installed mod, then applied the mod under test on top — a tree that never exists
  at the moment the engine actually applies that mod's patches. A node added by a
  **later-loading** mod looked present when it should not have. Fixed by truncating the merge at
  the mod's own load-order position. Measured on a real 192-op case: **27 false "OK" results,
  now 0** — full agreement with the engine, verified op-for-op.
- **One malformed overlay file crashed validation of every OTHER mod that touched the same
  path.** An `XMLSyntaxError` while reading an overlay escaped uncaught; exit code 1 made a crash
  indistinguishable from "found real errors." Now recorded and reported as a WARN naming the mod
  and file, never a crash.
- **A patch targeting an uninstalled mod is a designed no-op, not an error.** Compatibility-patch
  mods commonly ship nested cross-mod patches for dozens of optional targets. Enabling packed
  input surfaced this loudly (one mod went from 0 to 76 reported errors, 72 of them for targets
  simply not installed). Now reported as INFO, the same treatment already given to a
  false `if=` guard. **76 errors → 4 errors + 72 info** on that mod.
- **A DLC installed-but-never-unpacked-into-`reference/` reported a hard ERROR asserting content
  doesn't exist** — something the tool cannot actually know. Now reported as an honest
  "cannot verify" INFO naming the DLC, not a false ERROR.

**x4modlist auto-resolved ~10% of mods to the wrong Nexus page:** `_resolve_identity` accepted
the top search hit unconditionally. Measured on a live 101-mod registry: **7 of 69 resolved
entries pointed at an unrelated mod**, most flagged `settled: stable` — silently tracking someone
else's update history. Root cause: a multi-word Nexus search can return zero hits where a
single-word search returns several correct ones, and the empty-result fallback (drop the leading
word and retry) can land on an unrelated mod sharing only a generic word like "VRO" or "patch."
Now requires at least one shared identity-bearing token (generic modding filler excluded) before
accepting a match; an unresolvable mod is now flagged for manual review instead of silently
mis-tracked.

**x4effective and x4stats gave confident-looking answers that meant "nothing was checked":**
- `x4effective ls ship` printed `0 ship(s)` — reading as "this game has no ships," when the real
  issue is that `ship` isn't a stored entity kind (ships are `kind=macro`). Unknown kinds are now
  rejected with the actual list of valid kinds and a hint for the common ship/equipment aliases.
- x4stats compared ungrouped wares against an unrelated 1386-ware pool. A ware with no `group=`
  attribute (a paint mod, a cosmetic prop) was bucketed with every *other* ungrouped ware in the
  game and given a real-looking percentile against a wildly unrelated price distribution. Now
  reported as "not comparable," never a fabricated percentile.

If you maintain a fork or a similar tool: the single highest-leverage test you can add is this
pattern — ground truth from the engine's own log (`debug.txt`), not from your own model of the
engine, compared op-for-op, not file-for-file. No regressions found: all 10 previously-tracked
dev mods re-validated clean; the corrected oracle count is unchanged after every fix (234/234
ops, 100% agreement, 0 false OK, 0 unclassified, across all mods the reference log names — 9 of
them packed).

### Added — cross-platform support & guided installer (thanks @blablup, #2)
- **Runs on Linux, macOS and Windows (Git Bash).** `.claude/hooks/_x4-env.sh` is a shared
  resolver — **env var > `.claude/x4-paths.env` > default** — with case- and slash-insensitive
  matching that resolves symlinks and `..` via `realpath`, guarded so a Windows `C:\...` path is
  never mangled.
- **`install.sh` / `install.ps1` with three methods:** `in-game` (copy into the X4 folder — the
  original model), `separate` (toolkit in its own folder, pointed at the game via config), and
  `global` (skills/agents into `~/.claude` so the toolkit works across many mod repos). Paths are
  auto-detected from Steam's `libraryfolders.vdf` and overridable by flag.
- **`bin/xrcat`** — OS-aware XRCatTool wrapper (direct on Windows, Wine + `winepath` elsewhere).
  **`bin/unpack-reference.sh`** — config-driven text-only base+DLC unpack into `reference/`.
- **`.claude/x4-paths.env.example`** — one documented source of truth for every path.
  Keys: `X4_TOOLKIT`, `X4_GAME`, `X4_REFERENCE`, `X4_PROFILE`, `X4_DEBUGLOG`, `X4_MODS`,
  `X4_EXTENSIONS`, `XRCATTOOL`, `X4_APPMANIFEST`.
- All five hooks and `setup.sh` are now driven by the configured paths, with the old folder-name
  patterns kept as a backstop so protection still works out of the box.

### Added — engine knowledge (thanks @blablup, #1)
Field-tested MD↔Lua / FFI / UI / persistence patterns in `KNOWLEDGEBASE.md`: the nested-blackboard
`$`-prefix key trap, which container/trade-rule FFI functions actually work from UI-Lua (and the
global-vs-`C.` cdef variant trap), `$ship.$var` not surviving save/load, the
`a and nil or b` Lua footgun, and the kuertee UI-Extensions station-tab gotchas (13-column limit,
`is_valid_for` scope, slider/table widget behaviour).

### Fixed — safety hooks
- **The game-installation hard block never fired.** It used a PCRE lookahead `(?!\.claude)` under
  `grep -E`, which cannot match — so the rule has been silently dead in every release to date.
- **`in-game` layout hard-denied edits to your own mod sources.** With the toolkit installed into
  the game folder, `dev/`, `dist/` and `$X4_MODS` fell through every whitelist to the
  game-installation block. Now whitelisted.
- **`content.xml` edits were silently allowed inside the working dirs.** The manifest confirmation
  sat *below* the workspace whitelist; it now runs above it, so a manifest edit always confirms.
- **`check-reference-version.sh` hardcoded one Steam path** — now derived from `X4_GAME` with
  cross-platform fallbacks, so GOG / second-library / Linux users get the stale-reference warning.
- **`x4validate-on-edit.sh` was anchored to the author's personal folder** (`Modding/X4/dev/`), so
  the advertised auto-validate-on-edit hook could never fire for anyone else. Now it triggers on
  any diff XML outside `reference/`, resolving the mod root by walking up to `content.xml`.

- **Auto-backup was not anchored to the toolkit.** `backup-before-edit.sh` was the only hook that
  never adopted the shared path resolver; it used `${CLAUDE_PROJECT_DIR:-.}`, so with that variable
  unset it wrote backups into whatever directory the shell happened to be in. It now resolves
  through `_x4-env.sh`, and Windows-style paths are normalized before the copy.
- **`_x4-env.sh` no longer falls back to `$(pwd)` for the toolkit root.** It derives it from the
  hook's own location (`<toolkit>/.claude/hooks/` -> `<toolkit>`), so every hook stays anchored
  even when `CLAUDE_PROJECT_DIR` is absent.

### Added — the guards now have tests
- **`scripts/test-hooks.sh`** — feeds every hook synthetic tool-call JSON and asserts the decision
  it returns: **33 assertions** across both the in-game and separate layouts (deny `reference/`,
  `.cat`/`.dat`, base-game files; ask on `content.xml`, profile, deployed `extensions/`; allow
  `dev/`, `$X4_MODS`, toolkit dirs), plus backup creation, audit-log append, backup anchoring, and
  the stale-reference warning in both directions. Run it after any change to `.claude/hooks/`.

  **Four** separate safety features shipped silently inert before this release, and every one of
  them passed code review. A silent guard is worse than no guard, so the guards now have tests.

### Fixed — x4validate reported a false OK on attribute-add ops (found before the oracle existed)
- **`<add sel="…" type="@attr">value</add>` was silently ignored.** RFC 5261 §4.3 defines an
  attribute-add; X4 supports it and real mods use it. `_merge._do_add` never implemented it — the
  op fell through to the append-children branch, found no element children, mutated nothing, and
  still reported `OK 1 target(s)`. That is a **false OK on exactly the silent-no-op class this tool
  exists to catch**, and it survived earlier review because the op *looks* handled when you read
  the code. `_do_add` now sets the attribute, and `apply_diff` reports any `type=` it does not
  model rather than pretending to apply it. Four regression tests.

  Attribute ops matter for cross-mod work: when another mod owns a sibling attribute, a whole-node
  `<replace>` bakes in whatever value was winning when you wrote the patch, while
  `<remove sel="…/@x"/>` + `<add type="@value">` leaves it alone.

### Changed
- `/x4-debug` no longer ships a hardcoded workshop id as a "known-benign" suppression rule — it
  now describes the *class* (an extension id not in your installed set) and warns against
  suppressing ids you haven't confirmed absent. It also documents two engine behaviours that look
  like regressions but aren't: an upstream mod's failed `<replace>` still logs even when a
  load-last overlay supplies the value, and a `sel=` matching multiple nodes is a silent no-op.
- Log comparison guidance: check whether each log is a new game or a save load before comparing
  error counts — they aren't comparable across that boundary.

### Verification
`bash scripts/test-hooks.sh` — **33/33** assertions across both install layouts. Python suite: 170.

## v1.4

Engine-fidelity release. Three ways X4's patch semantics differ from a naive XML merge were
found by dogfooding against a 95-mod install — each one had been silently producing either a
false alarm or, worse, a false OK. Plus the effective-values browser (`x4effective`) and the
version-diff tool (`x4diff`).

### Fixed — three silent-no-op / false-alarm classes

- **A `sel=` matching MULTIPLE nodes is a silent no-op, and was never flagged.** RFC 5261
  requires `sel` to select exactly one node; X4 enforces it by logging
  `Multiple matching nodes for path '<sel>' ... Skipping node` and applying **nothing**. The
  patch looks correct, validates clean, and does nothing. **236 such ops were being skipped
  across one real modlist** — including 11 belonging to a mod whose entire purpose was the
  behaviour those ops implement. `x4validate` now reports this as an ERROR, and the merge
  engine models the skip instead of applying the op to every match (which used to build an
  effective tree the game never has).

- **`if=` guards were unknown to the checker.** `if=` is the idiom for targeting content that
  may not be installed. The merge engine honoured it; the sel-checker did not know it existed
  and reported every deliberately-guarded op as a hard ERROR. Guards are now evaluated first,
  exactly as the engine does: a false guard reports INFO ("guarded no-op") and short-circuits
  before `sel=` is parsed. A guard that *passes* while its `sel=` still misses remains an
  ERROR — the author asserted that target exists.

- **Cross-mod patches at `extensions/<target>/<rel>` reported "no base game file".** That path
  is owned by `<target>`, not by the base game, so the base was never found and the patch's
  selectors went unchecked — while the engine applied them fine. The merge engine now resolves
  the owning mod and layers other mods' nested patches on top.

### Added

- **`--tier b`** — previously a stub that printed a warning and was never passed to the
  validator. It now merges the **installed extension set in load order**, so cross-mod patches
  resolve for real. It also catches the reverse failure Tier A silently passes: content another
  mod has **removed**. Real case that motivated it — one mod's `index/macros.xml` `<remove>`s a
  vanilla macro and never re-adds it, orphaning it for six other mods and generating 415 engine
  errors; Tier A reported that macro as defined. The mod under test is auto-excluded by both
  folder name and `content.xml` id (a dev folder is usually also deployed, and merging that copy
  would pre-apply its own ops and mask real misses). ~8s over 93 extensions.
  Ordering follows the community convention (alphabetical, dependencies first) — advisory.

- **`x4effective`** — the "xEdit for X4" effective-values browser. Every final value with
  per-attribute provenance (`base → modA replace-attr:12 → modB`), backed by SQLite.
  Subcommands: `build`, `ls`, `show`, `attr`, `who-sets`, `diff-mod`, `dump`, `sql`.
  Answers "show me all missiles and their damage" and "who set this, and what did it override".

- **`x4diff`** — semantic XML diff between two versions of a mod, with multi-baseline support
  (`--overlay`). Built for separating *your* edits from an author's when recovering personal
  modifications made to an older release.

- **`_provenance.py`** — provenance capture threaded through the merge (`Origin`/`Recorder`),
  keyed by live element objects rather than XPath strings, since paths shift as the tree mutates.

- **`_debuglog.py` / `--debug`** — folds the engine's own `debug.txt` errors for the mod under
  test into the report, and gates on them. The engine is the authority; static checks are not.

- **`_exprlint.py`** — always-on heuristic lint for MD/aiscript expression grammar.

### Changed

- `collect_macro_defs` now builds the **effective** `index/macros.xml` via the merge engine
  instead of unioning each directory's file. The old approach could see neither `<diff>`/
  `<remove>` ops nor packed `.cat` mods, so it reported macros as defined after they had been
  deleted from the effective index.
- `_merge.Config` gained an `overlays` field, threaded automatically into every
  `build_effective()` call, so Tier B needs no signature changes across the checkers.

### Tests

125 → 152. New `tests/test_tierb.py` encodes all three engine-fidelity rules plus Tier B
overlay resolution as permanent regressions.

## v1.3

New cross-mod interaction suite — the toolkit can now analyze how a mod behaves against your
installed set, not just validate it in isolation.

### Added
- **`x4compat`** — detects how installed mods collide over the effective (base+DLC+mods) tree:
  HARD (two mods replace/remove the same node — one silently loses), UNION-KEY (two mods define
  the same registry entry id), FULL-OVERRIDE (two full-file overrides of one asset), SOFT (benign
  coexisting adds). Dispatches by actual merge semantics, not raw file overlap — a shared-registry
  overlap (`t/`, `libraries/`, `index/`) isn't automatically a conflict. Candidate mode
  (`check <mod-folder>`) answers "what would collide if I added this?" before installing.
- **`_cat.py`** — an independent `.cat`/`.dat` reader so PACKED mods are finally visible to the
  whole toolkit (previously only loose-file mods could be analyzed). MD5-verified, reads both
  `ext_*` and `subst_*` catalogs, case-insensitive virtual-path lookup. Wired into the merge
  engine as a loose-over-packed fallback.
- **`x4xref`** — a who-calls / who-listens / cue cross-index over every MD/aiscript in base+DLC+
  installed mods. Answers behavioral-interaction questions ("who else touches this event/action")
  in one query instead of many exploratory greps — the useful tokens for this class of question
  often share no keyword with the concept you're actually asking about.
- **`x4stats`** — advisory numeric comparison of a candidate mod's wares/macros against the
  effective tree's same-group peers (so an installed overhaul's rescaled values are the baseline
  you're compared against, not vanilla's). Grounds a balance discussion; does not settle one.
- **`x4similar`** — advisory fuzzy same-ship detection: flags a mod's ship as a probable
  near-duplicate of one already present under a DIFFERENT id/name (an overhaul's rebalanced
  reskin, or two mods independently adding "the same" ship). Hard-filtered by ship class+purpose;
  requires 4+ shared numeric stats to avoid coincidental matches between unrelated small ships.
- **`/x4-mod-interaction` skill** orchestrating all four tools plus README/Nexus context into a
  single interaction brief with per-claim confidence — never loads a whole mod's XML into context.

## v1.2

Fixes and redesign from continued dogfooding on a real 30+ mod install.

### Fixed
- **`libraries/*.xml` (ships, wares, loadouts, ...) are now correctly UNIONED**, not
  full-file-overridden, matching the engine. Every DLC ships its own full `libraries/`
  files; treating them as full overrides silently clobbered base-game entries out of the
  effective tree, producing phantom "sel matched nothing" errors for any mod patching a
  base-game ship/ware/loadout. (`index/` and `t/` were already unioned — `libraries/` is
  now folded into the same additive-merge path.)
- **Mod-authored index entries (`index/macros.xml` etc.) no longer double their own
  path prefix.** Mods conventionally write index values game-root-relative
  (`extensions\<mod>\assets\...`); resolving that literally against the mod root (which
  already IS that `extensions\<mod>\` directory) produced a spurious "file missing".
  The leading `extensions\<mod>\` is now stripped before resolving.
- **Loadout connection-checking no longer flags `path=".."`/`"."` as a missing
  connection name.** Vanilla `<groups>` entries use `path=".."` to mean "the ship root,"
  not a connection — that's not a checkable name.

### Changed — `x4modlist` redesign
- **Installed-folder scan is now the PRIMARY source of truth**, not the profile
  `content.xml`. A registry built content.xml-first drifts from reality over time (see
  "content.xml ≠ what's installed" in KNOWLEDGEBASE.md) — `x4modlist ingest` now scans
  the real extension folders first and treats that as authoritative; content.xml is
  ingested as a secondary backfill/cross-check pass so a historically-tracked mod isn't
  silently lost, surfaced in its own "not currently installed" view instead.
- **Identity resolution now prefers a mod's own manifest name** over a humanized
  folder/id guess, with fallbacks for common author-prefix (`"kuertee: X"` → `"X"`) and
  suffix-qualifier (`"X - Divinity Edition"` / `"X VRO"` → `"X"`) naming patterns —
  substantially fewer wrong Nexus-search top hits.
- **New `custom-local` classification lane**: a mod whose upstream Nexus status is
  `removed`/`hidden` is no longer automatically classified `drop` if the user has
  marked it `custom_edited` — a locally-maintained fork/port isn't "abandoned" just
  because the author's page is temporarily unavailable.

## v1.1

Bug fixes from a cold-start install red-team (a no-context agent following only the shipped
docs), which surfaced gaps invisible from the inside.

### Fixed
- **`x4validate` no longer false-passes when the reference tree is missing or empty.** It used
  to report `OK: no issues found` (exit 0) even on a `sel=` that matched nothing, because there
  was nothing to match against — the exact silent-no-op the tool exists to catch, in the tool
  itself. It now errors and exits non-zero until a real `reference\` is present. (+ regression
  tests.)
- **`protect-files` hook now actually fires.** The game-install block used a PCRE lookahead
  invalid under `grep -E`, so it never triggered; path matching was also tied to one personal
  workspace layout. Reworked to anchor on `$CLAUDE_PROJECT_DIR`, so the `reference\` read-only
  block and the workspace whitelist work at any install location.

### Changed
- `CLAUDE.md` reconciled to the "workspace under the project root" layout and to the
  protections that actually exist; removed a hardcoded x4validate test count from docs.

## v1.0

Initial release. An AI-assisted X4: Foundations modding environment for Claude Code,
distilled from hands-on mod development on X4 v9.0.

### Included
- **~500-line `KNOWLEDGEBASE.md`** — X4 XML schema patterns, diff-patch idioms, the
  extension merge/load-order model, the 7.x→9.0 version migration map, a mechanics
  interlock map, and tool notes. Auto-loaded every session.
- **`CLAUDE.md`** — the modding workflow: diff-patch-first, confidence levels,
  "vanilla as frame of reference," native-engine-solutions-first, and the cognitive
  co-pilot principle.
- **`x4validate`** (bundled, Python/uv/lxml) — cross-file validator: checks every diff
  `sel=` resolves against the real base+DLC merged tree, that ware/macro/`{page,t}`
  references resolve, and completeness of new content vs a vanilla analogue. Also ships
  `x4modlist` (mod-registry triage via the Nexus API) and an XSD-based 7.x→9.0 migration
  checker.
- **4 skills** — `/x4-debug`, `/x4-modlist-review`, `/x4-scaffold`, `/x4-update-mod`.
- **2 subagents** — `cross-file-impact`, `mod-research`.
- **Safety hooks** — protect-bash, protect-files, auto-backup-with-audit-log,
  reference-version check (SessionStart), and advisory x4validate-on-edit.
- **`scripts/generate-baseline.sh`** — capture a known-good baseline (game version,
  installed-mod hashes, a normalized debug.txt error fingerprint) to diff against later.
- **`setup.sh`** — checks prerequisites (jq, uv/Python), wires up x4validate, and
  personalizes local paths.

### Notes
- Ships **no** Egosoft game data. `reference\` is unpacked locally from your own copy.
- All Nexus access is via the official API with **your own** API key (`X4_NEXUS_KEY`);
  no key is bundled.

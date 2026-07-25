# Changelog

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

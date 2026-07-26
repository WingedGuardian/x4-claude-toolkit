# Changelog

## v2.0

**The toolkit is no longer Windows-only, and no longer assumes one folder layout.** Plus two
community contributions and a round of safety-hook fixes found by red-teaming the install flow.

Major version because the install model changed: there are now three supported layouts and every
X4 location is configurable. Existing v1.x users keep working — the in-game layout is unchanged
and the hooks fall back to the old folder-name patterns when nothing is configured.

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

### Changed
- `/x4-debug` no longer ships a hardcoded workshop id as a "known-benign" suppression rule — it
  now describes the *class* (an extension id not in your installed set) and warns against
  suppressing ids you haven't confirmed absent. It also documents two engine behaviours that look
  like regressions but aren't: an upstream mod's failed `<replace>` still logs even when a
  load-last overlay supplies the value, and a `sel=` matching multiple nodes is a silent no-op.
- Log comparison guidance: check whether each log is a new game or a save load before comparing
  error counts — they aren't comparable across that boundary.

### Verification
`bash scripts/test-hooks.sh` — **33/33** assertions across both install layouts. Python suite: 152.

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

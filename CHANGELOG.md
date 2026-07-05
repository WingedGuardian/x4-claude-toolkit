# Changelog

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

---
name: x4-modlist-review
description: Review and triage the X4 mod registry (Phase-A worklist) — scan the ACTUALLY INSTALLED extension folders (the primary source of truth), cross-check against the old profile content.xml (diff/backstop only), refresh upstream mod metadata via the Nexus API, and drive the spot-check loop (confirm/correct identities, ignore junk, mark custom edits). Use when the user wants to triage their modlist for a game version, see what has updates / is obsolete / abandoned, or work the Phase-A modlist rebuild.
allowed-tools: Bash, Read
---

Triage the X4 modlist via the `x4modlist` CLI. **API-FIRST — never scrape Nexus.** Registry: `dev\_registry\modlist.yaml`; human dashboard: `dev\_registry\WORKLIST.md`.

**★ SOURCE OF TRUTH: the physically INSTALLED extension folders are PRIMARY** — game-root `extensions\`, profile `extensions\` (if present), Steam Workshop `content\392160\` (if present). That's what the game actually loads. The profile's `content.xml` enabled-list is a **SECONDARY cross-check only** ("did I forget to re-acquire something from my old modlist?") — it does NOT determine what's active. A mod tracked historically but not found on disk shows up in a separate "OLD MODLIST — NOT CURRENTLY INSTALLED" dashboard section, not in the active lanes.

Run commands via uv from the tool dir:
`cd $CLAUDE_PROJECT_DIR/tools/x4validate && uv run --python 3.13 x4modlist <cmd>`
Needs `X4_NEXUS_KEY` (user env). If a command errors "X4_NEXUS_KEY not set", the user must set it (see CLAUDE.md "Nexus API").

## Workflow
1. **Ingest** — `x4modlist ingest` scans the installed folders (reading each mod's OWN `content.xml` for its real `id`/`name`/`version`/`author` — folder names can differ from the manifest `id`, e.g. folder `X4CapturableXenonXL` → id `X4_Capturable_Xenon XL PERSONAL`) and merges that as PRIMARY; the old profile content.xml is a secondary backfill pass so nothing tracked historically is silently dropped. `--installed-only` skips the content.xml pass; `--dirs a,b,c` overrides the scanned directories.
2. **Refresh** — `x4modlist refresh` pulls upstream version/status and auto-resolves identities for installed mods. Identity resolution prefers each mod's REAL manifest name (far more reliable than guessing from the folder/id) over a humanized-id guess, with fallbacks for common author-prefix ("kuertee: X" → "X") and suffix-qualifier ("X - Divinity Edition" / "X VRO" → "X") naming patterns. `--force` bypasses the once-per-day TTL; `--ids a,b,c` targets specific mods (works even for NOT-installed old-list mods, to check upstream status before deciding to re-acquire).
3. **Present** — read `WORKLIST.md`; summarize the lanes (✅ ready / ⏸ churning / ⚠ predates-9.0 / 🔧 custom-local / ❌ drop), the **NEEDS SPOT-CHECK** count, and the **OLD MODLIST — NOT CURRENTLY INSTALLED** count (mods to potentially re-acquire).
4. **Spot-check loop** — `x4modlist needs-review` lists entries needing a human call. For each, show the auto-matched candidate(s) and have the user decide:
   - confirm/correct identity → `x4modlist resolve <id> <nexus_id>`
   - junk/personal/cheat mod → `x4modlist ignore <id> --reason "..."`
   - a mod they locally customized → `x4modlist mark <id> --custom --notes "..."`
   **Never guess keep/drop or fabricate a match** — surface candidates, the user decides. Search can return a wrong/deprecated/adoption-patch fork as the top hit (e.g. searching "kuertee UI Extensions and HUD" can match a niche "...for SW Interworlds adoption mod" instead of the real, popular mod) — always show the candidate list, don't just trust rank #1.
5. **Deep 9.0-readiness (opt-in only)** — the API gives version/date/status but **NOT "9.0-compatible"** (that gap is real; changelogs are sparse). For churning / predates-9.0 mods the user wants to keep, dispatch the `mod-research` agent (API-first) for changelog/community signal. Only on request.

## The 🔧 CUSTOM-LOCAL FORK lane
If a mod's Nexus status is `removed`/`hidden` AND it's `mark`ed `custom_edited`, it is classified `custom-local` — NOT `drop`. An author temporarily hiding their page mid-update (or a mod you've locally forked/ported yourself, e.g. in `dev\`) doesn't mean abandon it; "drop" would be actively wrong guidance there. This only applies once the user has `mark`ed the mod custom-edited.

## Honest framing
This produces the **auto-resolved worklist + the spot-check queue**. The keep/drop/custom decisions and in-game testing are the user's — it makes Phase A tractable, not instant. **Strategy:** work the ready + churning lanes first (the live mods); let predates-9.0 and unresolved bake, and re-`refresh` later as authors ship 9.0 updates. Periodically re-`ingest` to catch newly-installed/removed folders.

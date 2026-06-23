---
name: x4-modlist-review
description: Review and triage the X4 mod registry (Phase-A worklist) — ingest the profile content.xml, refresh upstream mod metadata via the Nexus API, and drive the spot-check loop (confirm/correct identities, ignore junk, mark custom edits). Use when the user wants to triage their modlist for a game version, see what has updates / is obsolete / abandoned, or work the Phase-A modlist rebuild.
allowed-tools: Bash, Read
---

Triage the X4 modlist via the `x4modlist` CLI. **API-FIRST — never scrape Nexus.** Registry: `dev\_registry\modlist.yaml`; human dashboard: `dev\_registry\WORKLIST.md`.

Run commands via uv from the tool dir:
`cd $CLAUDE_PROJECT_DIR/tools/x4validate && uv run --python 3.13 x4modlist <cmd>`
Needs `X4_NEXUS_KEY` (user env). If a command errors "X4_NEXUS_KEY not set", the user must set it (see CLAUDE.md "Nexus API").

## Workflow
1. **Refresh** — `x4modlist ingest` (sync content.xml → registry, preserving the user's `human:` fields) then `x4modlist refresh` (pull upstream version/status, auto-resolve identities). `--force` bypasses the once-per-day TTL; `--ids a,b,c` targets specific mods.
2. **Present** — read `WORKLIST.md`; summarize the lanes (✅ ready / ⏸ churning / ⚠ predates-9.0 / ❌ drop) and the **NEEDS SPOT-CHECK** count.
3. **Spot-check loop** — `x4modlist needs-review` lists entries needing a human call. For each, show the auto-matched candidate(s) and have the user decide:
   - confirm/correct identity → `x4modlist resolve <id> <nexus_id>`
   - junk/personal/cheat mod → `x4modlist ignore <id> --reason "..."`
   - a mod they locally customized → `x4modlist mark <id> --custom --notes "..."`
   **Never guess keep/drop or fabricate a match** — surface candidates, the user decides. Search can return a "DEPRECATED" fork above the real mod, so the candidate list matters.
4. **Deep 9.0-readiness (opt-in only)** — the API gives version/date/status but **NOT "9.0-compatible"** (that gap is real; changelogs are sparse). For churning / predates-9.0 mods the user wants to keep, dispatch the `mod-research` agent (API-first) for changelog/community signal. Only on request.

## Honest framing
This produces the **auto-resolved worklist + the spot-check queue**. The keep/drop/custom decisions and in-game testing are the user's — it makes Phase A tractable, not instant. **Strategy:** work the ready + churning lanes first (the live mods); let predates-9.0 and unresolved bake, and re-`refresh` later as authors ship 9.0 updates.

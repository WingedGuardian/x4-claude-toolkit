---
name: x4-update-mod
description: Port an existing X4 mod to a newer game version (e.g. 7.x → 9.0). Runs the mechanical checks (x4validate sel/refs/completeness + XSD schema validation + the runtime migration-map heuristic) and produces a mechanical-port report plus a research-assisted design brief (feature-fate + the decisions only the user can make). Use when the user wants to update, port, or modernize a mod for the current game version.
allowed-tools: Bash, Read, Glob, Grep
---

Port ONE mod to the current game version. **Mechanical work is automated + validated; design/gameplay decisions are surfaced to the USER — never auto-decided** (the two-layer rule).

Tool: `cd $CLAUDE_PROJECT_DIR/tools/x4validate && uv run --python 3.13 x4validate <dev\mod> --update`

## Phases
1. **Research (API-FIRST)** — dispatch the `mod-research` agent: game changelog (Egosoft patch notes), the mod's Nexus changelog/version/9.0-status, whether an updated upstream exists, known issues. Cross-check `KNOWLEDGEBASE.md` "Version Migration Map".
2. **Mechanical checks** — run `x4validate <mod> --update` and read the report:
   - **sel= / refs / completeness / connection** — diff patches matching nothing, dangling refs, broken loadout connections, missing companion files.
   - **XSD (`--update`, the migration backbone, ~100s warmup):** `[error] xsd` = *"attribute is required but missing"* → a REAL breakage (e.g. the `space=` family) — **fix these**. `[info] xsd-strict` = **md.xsd is stricter than the engine** (lowercase script/cue names, unknown-but-tolerated attributes) → **ADVISORY, usually safe to ignore** (the mod runs); only investigate if it actually misbehaves. (See KB: "md.xsd is STRICTER than the engine".)
   - **migration (`[warn] migration`)** — runtime-only dead APIs the XSD can't see: `Lua_Loader.Load` dead, `.keys.list.clone`, `kuertee_hud` — each with a fix note.
3. **Apply mechanical fixes** — fix the real errors (required attrs, dead APIs); re-run `--update` until the `error`/`migration` classes are clean. Validate each fix (and honor the diff-patch / vanilla-as-frame rules).
4. **Design brief (for the USER — research-assisted, NOT automated):** per notable feature / custom edit, classify the **feature-fate** — `still-needed` | `obsolete` (game now does it natively) | `moot/superseded` (a *different* game change made it irrelevant) | `same-goal-different-impl`. Then list the **decisions only the user can make** (keep/drop/adapt, balance/taste). The schema/API can't read gameplay intent — surface, don't decide.
5. **Custom edits (Scenario B)** — if the mod is `mark`ed `custom_edited` (registry) or has a `dev\` twin, surface the user's local changes for manual re-apply onto the updated upstream. (Automated 3-way merge is a later capability.)

## Honest framing
Mechanical = auto + validated. Gameplay/feature-fate = advisory brief, the user decides. In-game testing + `debug.txt` (`/x4-debug`) are still required — a clean `--update` is necessary, not sufficient. **Every mod is different** — use ATD's documented 7.x→9.0 port (KNOWLEDGEBASE Session Logs) as a *worked example*, not a template.

---
name: x4-debug
description: Read and summarize the active X4 profile's debug.txt, filtering known-benign noise and surfacing only real mod errors. Use after an in-game test, or when the user asks what went wrong or to check the debug output.
allowed-tools: Read, Bash
---

Read the active profile debug log and report only REAL errors.

**Path:** `$X4_DEBUGLOG` if set (the installer writes it to `.claude/x4-paths.env`; `x4validate --paths` shows what resolved). Otherwise: Windows `Documents\Egosoft\X4\<profile-id>\debug.txt`, Linux `~/.config/EgoSoft/X4/<profile-id>/debug.txt`. The `<profile-id>` is a numeric folder; if there are several, the ACTIVE one has the newest `debug.txt`/save timestamps (older profiles are stale).

**Filter out known-benign noise** (do NOT report these):
- `Failed to verify the file signature` (error 13/14) — normal for unsigned mods.
- `LibraryLoadout()` / `ConstructionPlan()` errors citing an extension id that is NOT in the installed set — saved loadouts/blueprints referencing a mod the player no longer has. Unrelated to the mod under test. (Check the id against the `extensions\` folders rather than assuming; only suppress ids you have confirmed are absent.)
- `[God Engine] God Entry ID: '…' no sectors in galaxy found, error in map?` — these god products require sectors that are `faction="[ownerless]"` AND tagged `anarchy`/`chaos`. No vanilla/DLC sector carries those tags at game start; they are acquired at runtime. Vanilla-normal noise.

**Expected-and-correct — do NOT report as a regression:**
- An upstream mod's failing `<replace>` still logs even when a load-last overlay supplies the value afterwards: the upstream op runs first and fails regardless. Judge such fixes by the effective value, not by the log line disappearing.
- A `sel=` matching MULTIPLE nodes is a silent no-op (`Multiple matching nodes … Skipping node`) — the op applies nothing. If a local overlay supplies that content instead, the original mod's two error lines still appear.

**Comparing two logs:** first check whether each is a NEW GAME or a save load (`grep -c "Universe generation begins"`). Raw error COUNTS are not comparable across that boundary — only per-category presence/absence is.

For everything else, focus on `[=ERROR=]` and `[=WARNING=]` lines. Group by mod/source, quote each with line numbers, and note the likely cause:
- XML parse error, missing/unresolved reference, unknown event/property, or a missing required attribute (→ cross-check the **Version Migration Map** in KNOWLEDGEBASE.md — e.g. the `space=` family).

Summarize: total real errors, grouped by source, with the highest-severity first. A mod that loads without crashing is NOT necessarily correct — call out silent reference failures.

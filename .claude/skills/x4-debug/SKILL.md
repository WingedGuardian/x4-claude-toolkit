---
name: x4-debug
description: Read and summarize the active X4 profile's debug.txt, filtering known-benign noise and surfacing only real mod errors. Use after an in-game test, or when the user asks what went wrong or to check the debug output.
allowed-tools: Read, Bash
---

Read the active profile debug log and report only REAL errors.

**Path:** `Documents\Egosoft\X4\<profile-id>\debug.txt`. The `<profile-id>` is a numeric folder; if there are several, the ACTIVE one has the newest `debug.txt`/save timestamps (older profiles are stale).

**Filter out known-benign noise** (do NOT report these):
- `Failed to verify the file signature` (error 13/14) — normal for unsigned mods.
- `LibraryLoadout()` / `ConstructionPlan()` errors citing missing extension `ws_1696862840` — the player's saved loadouts/blueprints referencing an uninstalled mod, unrelated to the mod under test.

For everything else, focus on `[=ERROR=]` and `[=WARNING=]` lines. Group by mod/source, quote each with line numbers, and note the likely cause:
- XML parse error, missing/unresolved reference, unknown event/property, or a missing required attribute (→ cross-check the **Version Migration Map** in KNOWLEDGEBASE.md — e.g. the `space=` family).

Summarize: total real errors, grouped by source, with the highest-severity first. A mod that loads without crashing is NOT necessarily correct — call out silent reference failures.

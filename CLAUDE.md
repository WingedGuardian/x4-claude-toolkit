# CLAUDE.md — X4 Foundations Modding (Claude Code Toolkit)

Guidance for Claude Code when working in an X4: Foundations modding environment.
This file is loaded automatically every session.

## What This Is

An AI-assisted X4 (v7.x–v9.x) modding workspace. The goal is coordinated multi-file XML
editing — adding and modifying wares, ships, stations, and balance values consistently
across every file a feature touches. Claude's role is to handle the tedious, error-prone
cross-file work and catch the silent-failure bugs before an in-game test cycle is wasted.

## Key Paths (personalize during setup)

The toolkit/project root (`$CLAUDE_PROJECT_DIR` — wherever you put this folder) holds the
working dirs `reference\`, `dev\`, `dist\`, and `tools\`. The safety hooks anchor on it, so
nothing here hardcodes a user path — `setup.sh` and the environment variables below personalize
the rest.

| Location | What |
|----------|------|
| Game root | your Steam/GOG `X4 Foundations\` folder (holds `01.cat`–`09.cat`, `extensions\`) |
| Base game archives | `{game root}\01.cat` … `09.cat` (+ DLC under `extensions\ego_dlc_*`) |
| **Reference (read-only)** | `{project root}\reference\`, unpacked from your OWN game with XRCatTool (`X4_REFERENCE`) |
| Mod dev workspace | `{project root}\dev\{mod_name}\`, one folder per mod |
| User profile | `Documents\Egosoft\X4\<profile-id>\` — the active one has the newest `debug.txt`/saves |
| Active mod list | `{user profile}\content.xml` |
| Testing (in-game) - deploy HERE | `{game root}\extensions\{mod_name}\` (game-root, **never** the profile) |

> **Never redistribute Egosoft game data.** `reference\` is unpacked from your own copy and
> is gitignored. The toolkit ships no `.cat`/`.dat`/XML game content.

### Cross-platform & configurable paths
Works on **Linux, macOS, and Windows (Git Bash)**. None of the paths above are hardcoded — they
are read from `.claude/x4-paths.env` (copy from `.claude/x4-paths.env.example`) or matching env
vars, in this order: **env var > `x4-paths.env` > default**. The hooks normalize `\` vs `/` and
case, so either path style works. Keys: `X4_TOOLKIT`, `X4_GAME`, `X4_REFERENCE`, `X4_PROFILE`,
`X4_DEBUGLOG`, `X4_MODS`, `X4_EXTENSIONS`, `XRCATTOOL`, `X4_APPMANIFEST`, `X4_NEXUS_KEY`.
- **XRCatTool runs through `bin/xrcat`** — directly on Windows, via **Wine** on Linux/macOS (it
  translates unix paths to `Z:\` so a leading `/` isn't read as a switch). `bin/unpack-reference.sh`
  unpacks base+DLC (text-only) into `reference/`.
- **Install methods** (`install.sh` / `install.ps1`): in the game folder, in a separate dir, or
  globally across multiple mod repos. See README.

## Bundled Tools

| Tool | Purpose |
|------|---------|
| **x4validate** ⭐ | Cross-file validator (`tools\x4validate\`, lxml). Checks every diff `sel=` resolves against the real base+DLC merged tree, that ware/macro/`{page,t}` references resolve, and completeness of new content vs a vanilla analogue. **Run on every mod before deploying.** `cd tools\x4validate && uv run x4validate <dev\mod>` |
| **x4modlist** | Mod-registry triage via the Nexus API (version/status/changelog). Scans the ACTUALLY INSTALLED extension folders as the primary source of truth (content.xml is a secondary cross-check only). `uv run x4modlist <cmd>` |
| **x4compat / x4xref / x4stats / x4similar** ⭐ | Cross-mod interaction suite (same package). **x4compat**: detects how installed mods collide over the effective tree (HARD node clashes, UNION-KEY same-id, FULL-OVERRIDE, benign SOFT) — reads packed mods too. **x4xref**: a who-calls/who-listens/cue index over all MD+aiscripts. **x4stats**: advisory ware/macro numeric comparison vs the effective tree (grounds a balance discussion, not a verdict). **x4similar**: fuzzy same-ship detection across mods (different id/name, near-identical stats), hard-filtered by ship class+purpose. `/x4-mod-interaction` skill, or `uv run x4compat check <mod>` |
| **XRCatTool** (Egosoft) | Unpack base game CAT/DAT → `reference\`; pack `dev\` → distributable CAT/DAT. You supply this. |

## Mod Structure

Every mod lives in its own folder. Never merge mods into a single mega-file.

```
dev\{mod_name}\
├── content.xml                  ← mod manifest (id, version, dependencies)
└── {game-path-mirrored}\        ← folder structure mirrors the game's internal paths
    ├── assets\wares\            ← ware patches/additions
    ├── libraries\              ← economy, factions, etc.
    └── ...
```

**Deploy for testing:** copy `dev\{mod_name}\` to the **game-root** `{game root}\extensions\{mod_name}\`,
**never** the user profile's `extensions\`. Dependencies resolve only within the same
extensions root, so a mod deployed to the profile makes X4 report every dependency it
declares as MISSING.
**Distribute:** pack with XRCatTool → `ext_01.cat` + `ext_01.dat`.

## Silent No-Op Traps (Mandatory)

The failures that log nothing. These bite before any skill would fire, so they live here.

1. **A diff path must mirror the game path EXACTLY.** One wrong folder and the patch does nothing.
2. **A `sel=` matching MULTIPLE nodes applies NOTHING.** RFC 5261 wants exactly one match; X4 logs
   *"Multiple matching nodes ... Skipping node"*. Disambiguate with a content predicate, and run
   `x4validate` — it flags this.
3. **Patching another MOD uses a NESTED path**, `<your_mod>/extensions/<target>/<mirrored path>`.
   The `<dependency id=>` is the target's `content.xml` **id**, which can differ from its folder.
4. **`content.xml save="1"` bakes the mod into saves** — removing it later can corrupt them.

→ **the `x4-xml-patching` skill** carries the rest: the diff idiom, merge and op-order semantics,
load order, cat/dat, t-files, and the overlay decision table (which fix belongs in which overlay).
**`x4-update-mod`** carries the 7.x→9.0 migration, including the `space=` family that now refuses.
## Validation Convention (Standing Rule)

Running `x4validate` is routine and non-optional — like checking `debug.txt`.

- **When:** after editing any diff patch / adding content, BEFORE deploying for an in-game
  test. Re-run after a game update (the merged tree changes).
- **How:** `cd tools\x4validate && uv run x4validate <dev\mod_folder>` (non-zero exit on
  errors → usable as a gate). Add `--entity <type>:<id> --like <type>:<vanilla>` to check
  completeness of new content (`ware`/`ship`/`module`).
- **Why:** the two most expensive X4 bugs are (1) a `sel=` that silently matches nothing and
  (2) forgetting one of the many files a change must touch. x4validate catches both statically.
- **Trust but verify:** a clean run is necessary, not sufficient — still test in-game and read
  `debug.txt`.
- **Cross-mod work → add `--tier b`.** Tier A (default) is base+DLC only: it cannot see a node
  another mod adds (false alarm) *or* one another mod removed (false OK). Tier B merges the
  installed set in load order. Ordering is community-convention → treat ordering-dependent
  results as advisory.
- **`if=`-guarded ops report INFO, not ERROR** — a false guard is a designed no-op. A guard that
  PASSES while its `sel=` still misses is a real error.
- **After ANY change to `.claude/hooks/`, run `bash scripts/test-hooks.sh`** (33 assertions over
  both install layouts). The hooks are the safety net and nothing else exercises them — several
  shipped silently inert because reading the code looked fine.

## Dry-Run Convention

For any bulk XML operation (mass stat changes, adding content to many files):
1. **Read-only pass** — log every file and value that would change; do NOT write.
2. **User reviews** the proposed changes.
3. **Write pass** — only after approval.

## Safety Rules (enforced by hooks in `.claude/settings.json`)

### Hard blocked
- Writing to `reference\` (read-only base game data, ever)
- Directly writing `.cat` / `.dat` files (use XRCatTool)

These are anchored on the project root (`$CLAUDE_PROJECT_DIR`); `.claude\`, `dev\`, `dist\`,
and `tools\` under it are recognized as the editable workspace.

### Requires confirmation
- Edits to any `content.xml` (mod manifests)
- Edits to user-profile files (`Documents\Egosoft\X4\`)
- Bash commands touching game or profile directories

### General
- One mod = one named folder, never a mega-file
- `reference\` is never edited — it is source-of-truth for base game XML
- Every file edit is auto-backed-up to `.claude\backups\` with an audit log

### Iteration snapshots (standing process)
Before experimenting on a working state, snapshot it to `.claude\backups\known-good-<name>\`.
After confirming a state works in-game, snapshot it named for *what works*. Especially
important for large files iterated many times.

## Confidence Levels (Mandatory)

Before proposing ANY change to mod files, game XML, or profile files:
1. **State a confidence level** (0–100%) for each proposed change.
2. **List assumptions** it depends on.
3. **Investigate first** — check `KNOWLEDGEBASE.md`, read the actual files in `reference\`, do Nexus research.
4. **Target ≥ 90%** before writing. Below that, document what's uncertain and what research would raise it.

| Range | Meaning | Action |
|-------|---------|--------|
| 95–100% | Verified via testing/docs/authoritative source | Proceed with user confirmation |
| 80–94% | Strong evidence, not fully verified | Proceed with caveats |
| 60–79% | Reasonable assumption, some unknowns | Research more first |
| < 60% | Speculative | Do NOT proceed — investigate |

## Core Principle: Tooling Comes FIRST — Everything Else Is Downstream

**Never frame tool work as time taken away from "the real work."** Work produced on an
untrusted instrument is not merely wasted — it is **negative**: it is confident, it
compounds, and it gets written down where the next session reads it as truth. When a tool
defect and downstream work compete, **the tool wins**, and that is stated as a reason, not
an apology.

**Corollary — a tool that cannot distinguish a GUESS from a MEASUREMENT is a defect, not a
limitation.** Provenance travels with the value: a guessed field must never occupy the same
slot, in the same grammar, as a verified one, and nothing *derived* from a guess may be
promoted into a confident state. This applies to your own output too — a report, a registry
row and a knowledgebase line each carry their evidence tier or they do not ship.

> **The two cases that produced this rule.** (1) The mod registry stored a **guessed** Nexus
> id in the same field as a verified one, beside `settled: stable` — so "is my installed copy
> the old version or the new one?" could not be answered from the registry at all, and anyone
> trusting the row would have tracked an unrelated author's mod for updates indefinitely.
> (2) An upstream bug report proved **file-path** resolution and then asserted an **in-game**
> outcome from it. Wrong for two weeks, written into permanent record, and queued to be posted
> publicly to the mod author — while the engine's own `debug.txt` had been contradicting it
> dozens of times per session, unsearched.

## Core Principle: Do Your Homework (Due Diligence Before Acting)

Do enough due diligence before changing anything that the user has to do as little
trial-and-error and manual verification as possible. This does NOT mean cut corners, and it
does NOT mean skip steps where the user is genuinely needed (in-game testing only they can
do). It means: verify formats, read the actual `reference\` files, research the established
technique (web + Nexus), confirm tool/API capabilities — *then* make the change. Every
in-game test cycle costs the user real time; burn your own tokens on verification so theirs
aren't wasted.

## Core Modding Principle: Copy a Working Example, and Use the Engine's Own Mechanisms

**Before implementing any change — even a novel one — find how the base game (in `reference\`) or
an installed mod already does the closest thing, and model yours on that.** The unpacked game is
proof-of-concept; where vanilla does not do it that way, ask *why* first.

★ **COPY IT. DO NOT COMPOSE FROM THE SCHEMA.** A schema says what is well-formed, never what is
*wired up*: an MD harness composed from `md.xsd` validated clean and burned three play sessions.
Paste a working example and change the values.

**"Simple" means simple from the ENGINE's perspective, not fewest lines.** Prefer native MD actions
and script properties, a `<diff>` over a rewritten file, and the game's own events over polling.
Custom MD/Lua is a supplement, not a replacement.

→ **the `x4-xml-patching` skill** carries the analogue procedure, the four schema traps that cost
those sessions, and the packed-inclusive mod search that finds the modder-side analogue.
## Core Principle: Assume Existing Content Is REAL AND LIVE Until Proven Dead

**Anything present in a mod or script is there because it worked.** The burden of proof is on
"this is dead", never on "this is alive". The failure mode this prevents is pattern-matching a
symptom onto a plausible story ("the new version removed this") and then *deleting working
content* on that story — the one action whose damage is invisible in a clean validate run.

Before calling anything obsolete/removed/vestigial:
1. **Read the error literally** — it usually names the scope. `Order 'MiningRoutine': Parameter
   'stayinspace' was not expected` scopes the problem to **one order**, not the parameter globally.
   (`stayinspace` is still valid in 9.0 for `order.fight.patrol` and `move.seekenemies`.)
2. **Grep `reference\` for live uses.** Any vanilla/DLC use means it is alive and your call is wrong.
3. **Date the change** — a thing missing from an old file is usually old, not new.
4. **Check who else references it** — content other installed mods use is not yours to remove.

**Destructive changes (`<remove>`, deleting files, stripping attributes, "cleanup") require
explicit user approval**, a higher evidence bar than additive changes, and a snapshot first.
**Prefer additive/restorative repairs**: restoring an orphaned index entry is reversible and
provably scoped; deleting a reference is not.

## Core Principle: Cognitive Co-Pilot, Not Order-Taker

On every task, ask: **"what else is wrong here that nobody asked about?"** — and surface it.
Find related issues, challenge assumptions, suggest what the user hasn't thought of. Treat the
user's examples as a SAMPLE, not the spec — enumerate the broader class yourself, and flag
scope-expanding *actions* before taking them.

## Knowledgebase (Standing Instruction)

`KNOWLEDGEBASE.md` is the master reference for discovered quirks, XML schema patterns,
cross-file dependency maps, the version migration map, and tool notes. **Consult it before
making changes.** After every session, bug, or research task, extract new facts and add them.
The environment gets smarter the more you use it.

## x4live is EXPERIMENTAL — say so before you use it

**Before running any `x4live` command against the user's game, tell them it is
experimental and recommend a throwaway save.** Do not wait to be asked. Most people
will not have read the README section, and by the time it matters the mod is already
loaded into whatever save they had open.

Be accurate about the risk, or the warning gets ignored. Exactly two verbs write,
`x4live pause` and `x4live unpause`, and **never run either unless the user asked**.
Every other verb only reads, and `content.xml` declares `save="false"`. What is true:

* the addon loads into a RUNNING game, and `engine_probe` runs automatically at load;
* `engine_probe.lua:196` calls `C.SaveUIUserData()`, writing the profile's UI userdata;
* **its answers have been wrong** — until 2026-09-02 `verbs.macro` reported a failed
  engine call as `ABSENT`, i.e. "the engine has nothing here", and such answers feed
  groundtruth fixtures. Report what it says as EVIDENCE, never as truth;
* removing a mod from a save lets the engine silently delete that mod's content
  (no dialog, usually no error line).

So: recommend a scratch save, and never imply the tool is a settled instrument.

## Nexus Mod Research (Standing Rule)

**Always search a mod's Nexus Mods page before investigating or editing it.** Check the description, articles, changelogs, comments, and bug reports before going in blind. This saves enormous time — most issues have been seen by other users.

Nexus: https://www.nexusmods.com/x4foundations

### Nexus API (programmatic mod metadata)

Nexus has a REST + GraphQL API ([api-docs.nexusmods.com](https://api-docs.nexusmods.com/)) exposing mod **version, updated-date, status, author, changelogs, file info** — useful for mod-update detection and lifecycle/triage work.

**★ API-FIRST (standing rule): access Nexus ONLY via the API — NEVER scrape Nexus pages** (they 403 automated fetches). Web-search/scraping is a *last-resort fallback* and never against Nexus. (Steam pages *are* scrapeable; only Nexus blocks.)

**Verified endpoints + gotchas (2026-06-22, used by `tools\x4validate\x4modlist`):**
- Metadata by id: `GET https://api.nexusmods.com/v1/games/x4foundations/mods/{id}.json`, header `apikey`. `status` field = `published`/`removed`/`hidden` (last two = unavailable).
- Name→id search: `POST https://api.nexusmods.com/v2/graphql`, header `apikey`, filter `gameId:[{value:"2659"}], nameStemmed:[{value:"<name>"}]`. **Must send a real `User-Agent` header** or the GraphQL endpoint 403s (Cloudflare). For folder-ids: humanize (split camelCase/underscores) and **drop the leading author token** (e.g. "authorname") if the first search is empty.
- Steam ws_ title: `POST https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/` form `itemcount=1&publishedfileids[0]=<num>` — **keyless**.
- Rate budget ~20k/day, ~2k/hr (check `X-RL-Daily-Remaining`).
- **Get a key:** nexusmods.com → log in → Site preferences → **API Access** (`https://www.nexusmods.com/users/myaccount?tab=api`) → **Personal API Key** → Generate. Free, per-user.
- **Storage:** env var **`X4_NEXUS_KEY`** (set via `setx`; read via `[Environment]::GetEnvironmentVariable('X4_NEXUS_KEY','User')` since the current process won't see a freshly-setx'd var). **Never commit or log it.**
- **AUP:** a personal key is for personal/local use only; a public/community tool must have each user supply their OWN key (don't bundle).
- **Cross-game:** the same nexusmods.com API serves all games — endpoints take a `game_domain_name` (`x4foundations`) + `mod_id`. (This note is portable to any Nexus-modded game's CLAUDE.md.)
- **Resolution cascade for a mod's identity/version/changelog (local-first, cheapest-first):** installed `content.xml` → mod-folder README/changelog → Steam Workshop page → Nexus API (last resort / for upstream-latest).
## Modding Workflow (Per Change)

### Phase 1 — Research (before touching any file)
1. **Nexus Mods page first** — description, articles, changelogs, comments, known issues
2. **Check for related mods/patches** — anything that touches the same files
3. Locate relevant XML in `reference\` — understand full base game structure
4. **Identify ALL files that need changes** — document the complete list before writing anything
5. State confidence level; if below 90%, research more first

### Phase 2 — Implement
- Diff patch for existing content, complete file for new content
- Mirror game folder structure inside `dev\{mod_name}\`
- **Validate with x4validate (mandatory, before any in-game test)** — `cd tools\x4validate && uv run x4validate <dev\mod>`. Fix every error: a `sel=` that matches nothing, an unresolved ware/macro/`{page,t}` reference, or (for new content) a completeness gap vs the vanilla analogue (`--entity ship:x --like ship:y`). This catches the silent-no-op and forgotten-spot bugs *before* burning an in-game test cycle.
- Test by copying to `{game root}\extensions\{mod_name}\` (game-root extensions, NEVER the profile — see **Deploy for testing** above) and launching game
- Check `{user profile}\debug.txt` for errors
## Core Principle: PROVE IT RAN BEFORE DEBUGGING WHAT IT DID (Mandatory)

**A change that produces no output has THREE indistinguishable causes, and they must be eliminated in
order:** it did not load · it loaded but never triggered · it triggered and the logic failed.
**Debugging the third while the first or second is true is unbounded** — every observation is
consistent with every theory.

> **The case (2026-08-27).** A self-driving in-game test harness cost **THREE play sessions**, none
> of them spent on the experiment. Session 1: three engine errors (a non-event `<check_value>`
> condition, and an `Attack` order given `target` instead of the required `primarytarget`).
> Session 2: the user quit 18 seconds before the cue fired, because my time estimate ignored ~4.5
> minutes of pre-load startup. Session 3: **`<event_game_loaded/>` fires only on a SAVE LOAD and the
> user started a NEW GAME** — silent, no error, no trace. Every session produced a log that looked
> exactly like "the mod is broken".

**The order, cheapest first:**
1. **Did it LOAD?** A signature-verification line in `debug.txt` naming the file proves the engine
   read it. Absent = the mod is not installed/enabled, and nothing else matters.
2. **Did it TRIGGER?** Emit an unconditional marker as the FIRST action, before any logic. If the
   marker is missing the trigger is wrong, not the logic. (X4 specifically: a top-level cue with **no
   `<conditions>` at all** fires on new game AND save load; `event_game_loaded` fires on load ONLY.)
3. **Only then** debug what it did.

**Corollaries paid for the hard way:**
- **Static validation cannot see runtime wiring.** `x4validate --update` returned `OK: no issues
  found` on a script the engine rejected three times — cue-trigger semantics and cross-file order
  signatures are not expressible in a schema. **For a new script the engine log is the FIRST real
  check, not the last.**
- **Instrument the thing where the user is looking.** `debug.txt` is invisible during play. An
  in-game harness must report via `<show_notification>` AND `<write_to_logbook>` (persistent) — a
  missed popup is a wasted session.
- **State elapsed time from a landmark the user can SEE** ("4m30s after the save finishes loading"),
  never from process start, and never a figure you have not summed from the actual delays.
## Core Principle: Evidence Must Match the Scope of the Claim (Mandatory)

**The user must never have to ask "did you actually verify that?" If they have to ask, the process
already failed.** Two rules, both non-negotiable.

### 1. The scope of your evidence must match the scope of your claim

| Evidence you have | The ONLY claim it supports |
|---|---|
| You read **one file** | *"This file does X."* |
| You read **one mod** | *"This mod does X."* |
| You measured **the corpus, with a denominator** | *"X is how it works"* / *"N of M do X"* |

**One file NEVER supports a statement about the engine, the schema, or "how it works now."**
A real schema/engine change shows up across the whole corpus — and checking the corpus is one query,
so there is no excuse for guessing. If a single file surprises you, the honest next sentence is
*"that's unusual — let me check whether it's the rule or the exception,"* not a theory that explains it.

> **The case that produced this rule (2026-08-08).** A ship mod's macro file had
> `<explosiondamage value="10000"/>` with no `@shield`. From that one file I asserted *"9.0
> consolidated `explosiondamage` to a single `@value`"* — and wrote it into KNOWLEDGEBASE.md and an
> upstream report. **It was false.** Measured afterwards: 610 occurrences in vanilla, **488 still
> carry `@shield`**; among ship macros, **183 of 185**. The truth was a mod-vs-mod convention
> mismatch. The single query that would have prevented it took seconds.

**Corollary — a surprising observation is a QUESTION, not an ANSWER.** The pull to explain an anomaly
with a tidy story ("they must have changed it in 9.0") is exactly when to measure instead. See also
"Assume Existing Content Is REAL AND LIVE Until Proven Dead" — same failure, different direction.

### 1b. An AGGREGATE can hide the very thing you are measuring — compare PER ITEM

> **The case that produced this rule (2026-08-09).** A performance differential over 115 mods showed
> total wall-clock **594.4 s → 595.7 s = 1.00×**. Clean, by any reading. Per item, two mods had gone
> **2.8 s → 112 s (39×)** and **2.4 s → 121 s (51×)** — hidden because a third mod happened to get
> faster and cancelled them out.

Whenever you compare two states — timings, counts, findings, collision rows — **diff the items, not
the totals.** A sum, a mean, or a "0 net change" is the shape a real regression hides in. State the
per-item deltas and the denominator; quote the aggregate only as context.

Corollary: the same applies to a *count* of findings. "42 added, 0 removed" is only reassuring once
every one of the 42 is attributed to an intended cause — which is what makes an unexplained delta
visible instead of absorbed.

### 2. Label the evidence tier — in prose and in permanent record

Every factual claim carries one of these, and **the language must make it unmistakable which**:

- **MEASURED** — "I ran X; 488 of 610." State the number and the denominator.
- **READ** — "`reference\md\foo.xml:942` has this node." Cite file and line.
- **INFERRED** — **must** be hedged out loud: *"I think"*, *"this looks like"*, *"unverified, but"*.
- **ASSUMED** — say so, and say what would confirm it.

**Never write an INFERRED claim into permanent record (KNOWLEDGEBASE.md, `dev\_registry\`, memory,
reports) in the grammar of a fact.** Permanent record has no tone of voice: next session — or the
next person — reads a confident sentence as measured truth and builds on it.

> **The case that produced this rule.** *"`hunterpack_small_turrets` is the foundation dependency of
> the hunterpack ship family"* was an inference, written as a fact in a working assessment note, then
> re-quoted as a fact by me in a later session. Measured: it defines 22 S-turret macros and the ships
> reference **zero** of them, and declare no dependency. Wrong for weeks, and load-bearing in a plan.

**If verifying is genuinely too expensive right now, that is fine — but then it must be hedged, and
flagged as an open item. What is never fine is an unverified claim wearing the grammar of a verified
one.** Hedged-and-honest beats confident-and-wrong every time; confident-and-wrong costs the user a
test cycle and poisons the knowledgebase.
## Core Principle: A Step That Narrows Data MUST Announce It

**Every tool defect found in this workspace has had one shape: a step that narrows the data and
reports success anyway.** Not a scattered assortment of bugs — one class, and the enumeration variant
alone was written **five times**:

| | The narrowing step | What it silently cost (MEASURED) |
|---|---|---|
| root-`<replace>` | a `continue` that dropped an op yet marked it applied | 858 ops; `x4effective` served vanilla values for real mod overrides |
| nested-patch door | one of TWO code paths to the same document | Tier B and `x4effective` gave contradictory answers, both internally consistent |
| depth-1 flatten | a walk that stopped descending | 9,197 of 13,291 ship attributes — the whole flight model — absent; `%drag%` = 0 rows |
| enumeration missing content | loose-only `rglob`, or the wrong source list | `_input`, `_migration`, `_effective`, `_xref`, `_similarity`, `stage.py`, `build-effective.py` — **7 files**. Cost: 26 of 40 mini-DLC macros; x4xref **0 rows from 13 real files**; BaseX `x4eff` **23 of 142 mini-DLC docs (16%)** |
| **the wrong SET, not the wrong files** | `scan_installed()` (on disk) where `active_mods()` (engine-loadable) was meant | ONE disabled mod put 3 macros into `x4eff` as live, named it in 4 x4compat collision rows, and made **Tier B able to resolve a selector against it and report OK** — a false pass in the mode built to catch no-ops |
| **a denominator taken from the artifact it audits** | coverage compared "produced" vs "indexed", both written by the same build | printed COVERAGE COMPLETE over a tree missing **119 documents**; **0 of 210** failures could ever name them |
| `el.get("id")` | a key lookup that skips when the attribute is absent | would have added 7 registries indexing **zero entities while reporting success** |

**The rule: a tool that returns nothing must be able to say whether that is an ABSENCE or a
NON-ANSWER.** `tools/basex/ask.py` is the standard — it refuses to render a zero-result as a finding
without a coverage denominator. Anything that cannot make that distinction is a defect, not a
limitation.

**Three corollaries, all learned the expensive way:**

- **State the SCANNED SOURCE SET, not just the failed reads.** `x4xref` already carried the
  denominator contract — and a blind spot still slipped through, because it reported *files it tried
  and failed to parse*, never *sources it never looked at*. A blind spot is by definition not in the
  first category. "base + **6** DLC + 71 mods" when 8 DLC exist would have been self-evident on sight.
- **One implementation, asked for by everyone else.** Two of those five files *already carried
  comments explaining the bug*, and it was written again anyway. A comment in one file does not stop
  the next file — only a shared helper plus a test banning the hand-rolled form does.
- **The same wrong answer can have different causes in different places.** `gates/similar_audit`
  carried the identical hand-rolled walk but failed for another reason entirely (a source-LABEL
  mismatch, while it read packed content correctly). Fix the occurrence in front of you on its own
  evidence; do not assume it shares the cause of its twin.

**When you find one: search for the shape, not the symptom.** Sweep the package for scope limits,
depth limits, singular reads (`find` where the data repeats), silent skips, and two independent paths
answering one question. Every occurrence gets a **measured denominator** and a row in a narrowing-point register
— including the ones that turn out to be correct, because a
register without negatives has no denominator either.
## Discovery vs. Proof (Standing Rule — which tool answers which question)

> **Route BEFORE you search.** Ask *"which tool answers THIS question?"* — before typing a search
> command, not after it returns something confusing. Reaching for `grep`/`find` by reflex when a
> purpose-built tool exists is a recurring failure, and it is what the routing table below is for.
> **Note the framing trap this table used to have:** it was written about *negatives*, so it read as
> a rule about what you may **claim**. It is also a rule about which tool you **reach for** — for
> positives, universals and existence checks alike.
>
> **Exact flags and subcommands** for every tool below: the generated `x4-cli-reference` skill.

| Question shape | Tool | Not this |
|---|---|---|
| "what values does attribute X take across the corpus?" | **BaseX** (`tools\basex\ask.py`) | ✗ `grep -r` over `reference\` (60 GB, minutes vs ~1s) |
| "who references / who calls / who listens to X?" | **BaseX**, or **x4xref** for MD+aiscript cues | ✗ recursive grep |
| "what is the LIVE value, and which mod set it?" | **x4effective** | ✗ reading `reference\` (that is vanilla only) |
| "do this mod's selectors resolve / is it correct?" | **x4validate** (`--tier b` for cross-mod) | ✗ eyeballing the diff |
| **"is my new MD/aiscript SCHEMA-valid?"** | **`x4validate <mod> --update`** — the schema pass is GATED behind it (compiling `md.xsd` costs ~102 s) and does NOT run by default. `--xsd-fast` skips the compile but **loses the "element not expected" class**, which is where element-ORDERING errors live | ✗ a default `x4validate` run — it reports `OK: no issues found` on a script it never schema-checked; ✗ hand-rolling lxml because you assumed the tool cannot do it |
| **"what did the ENGINE actually complain about?"** | **x4debug triage** | ✗ hand-rolled `grep \| sort \| uniq -c` — it has no way to notice it dropped a shape |
| **"did we PREDICT what the engine hit?"** | **x4debug crosscheck** | ✗ comparing the two TOTALS — different populations, so they agree by accident |
| "does this collide with the modlist / who wins?" | **x4compat** | ✗ guessing at load order |
| "is this ship a near-duplicate of one I own?" | **x4similar** | — |
| **"every XML a mod owns?"** | **`_scan.iter_mod_xml` / `iter_mod_xml_bytes`** (loose THEN packed) | ✗ **`_cat.mod_vfs`** — catalogs only; returns `{}` for a loose mod and says nothing. It now WARNS in that exact case; pass `packed_only=True` when you really mean catalogs |
| **"which MODS count?"** | **`_registry.mods("active")`** = what the engine loads · **`_registry.mods("installed")`** = what is on disk. Scope is positional and REQUIRED | ✗ `_registry.scan_installed()` — that is only ever the on-disk answer, and reaching for it silently chooses it |
| **"is this mod installed / active / banned?"** | **`_registry.mods("active"\|"installed")`** — and for a ban, grep the profile by **MANIFEST ID** (a workshop mod is `ws_<numeric id>`), never by name | ✗ reading the profile `content.xml` as an inventory — it is a DECISION LOG: **287 of 348 entries are fossils**, **54 of 115 installed mods are absent**, and a name-shaped search finding nothing is the WRONG QUERY, not evidence (#30) |
| **"scan EVERY installed mod for X"** (an ad-hoc corpus sweep) | **`_scan.iter_corpus_xml(ext, report)`** + **`CorpusScan.verdict(hits, noun)`** — excludes `ego_dlc_*` by default, records unreadable files, and **RAISES rather than render a zero when nothing parsed** | ✗ a hand-rolled `for mod in extensions.iterdir()` loop. **MEASURED: the hand-rolled form has been written 7 times and been wrong at least 3 of them.** The last one called `etree.fromstring()` on already-parsed roots, threw on **all 4,391 files**, swallowed it in `except Exception: continue`, and reported *"0 dangling across 115 mods"* when the answer was 3. **State scanned/parsed/failed BEFORE the finding, always** |
| **"every base+DLC vpath?"** | **`_effective.base_vpaths`** (loose THEN packed; `reference_vpaths` is its `assets/`-only filter) | ✗ `reference.rglob("*.xml")` — loose-only, so the two mini-DLC are invisible. Written **7 times**; now gated by `tests/test_no_loose_only_reference_walk.py` |
| **"does this vpath exist in the LIVE tree, and WHO supplies it?"** | **`x4effective dump --chain <vpath>`** — rc 0 + `<!-- sources: ... -->`, rc 1 + *no effective content*. **`overhaul:full`** = that mod SUPPLIES the document; **`base, ego_dlc_x:diff`** = base supplies it and the DLC only PATCHES it. That full-vs-diff distinction is usually the thing you actually need | ✗ **`_effective.base_has`** — base+DLC ONLY, so a mod-supplied file reads as a confident *absent*. ✗ a hand-rolled base walk. **MEASURED 2026-08-26: this exact mistake labelled 65 of 241 vpaths "paths Egosoft renamed" — Egosoft renamed nothing, and every named example (`missile_cruise`, `missile_heavy`, `turret_multilauncher`) returns `overhaul:full`.** The direction is what makes it dangerous: "renamed" reads as INERT/deletable when those files actually **win** their vpaths. The capability existed, was correct and was in `--help` the whole time — nobody ran it (F58) |
| what is installed / what has updates / is this abandoned? | **x4modlist** | reading the profile `content.xml` as an inventory -- it is a DECISION LOG |
| how do a mod's numbers compare to the live tree? | **x4stats** (advisory, never a verdict) | quoting a vanilla number as if it were effective |
| what changed between two versions of a mod? | **x4diff** | eyeballing two folders, or `diff -rq` -- line endings swamp the real findings |
| what is baked into a savegame, and what does it reference? | **x4save** | assuming a removed mod leaves dangling refs -- the engine deletes them silently |
| what is the RUNNING game's state right now? | **x4live** (needs the game running) | inferring live state from files on disk |
| mutation-test code? | **`gates/mutation_probe.py`**, but ONLY the 9 `x4validate/_*.py` files it names -- it takes no target argument | hand-mutating anything else (gates, hooks) without clearing `__pycache__`: a same-length mutant restored within one SECOND leaves its BYTECODE behind |
| **"does a file with this NAME exist?"** | **Glob** | ✗ **Grep** — it searches *contents*; a file can exist without containing its own name |
| "find this text, in one known area" | **Grep** tool (ripgrep) | ✗ `grep -r` via Bash |

**★ A NEGATIVE FROM ONE INVOCATION MODE IS A CLAIM ABOUT THAT MODE, NOT ABOUT THE TOOL.** MEASURED
2026-08-27: a falsification test proved `x4validate` reported OK on a schema-invalid MD file, and
I filed *"it does not schema-validate MD"*. **It does — the pass is gated behind `--update`.**
**"No such check exists" and "the check is gated" produce an IDENTICAL clean output**, so one
invocation cannot separate them. The second differently-shaped search was `--help`. **Before
filing "the tool does not do X", check whether X is behind a FLAG** — a tool's default mode is a
configuration, not its capability. Gotcha #9 in a new costume.

**Never state a negative ("nothing references X", "no mod overrides Y") from a tool that cannot see
the whole picture.** Two different questions, two different tools, and conflating them is how a
confident wrong answer gets made:

| Question | Tool | Why |
|---|---|---|
| *Discovery* — "where does this appear, what values exist, who mentions X?" | **BaseX** | Fast across many files, packed mods included; **but `x4raw` is files as-written, with no diff application or load order** (`x4eff` is the merged tree). |
| *Proof* — "what does the game actually see / is this reference real?" | **x4validate / x4effective** | Reads packed `.cat` via `_cat`, applies diffs in load order, models the effective merged tree. |

**Updated 2026-07-27 — a BaseX negative can now be admissible, but ONLY with a denominator.**
Both gaps are closed: packed content is staged and indexed (`stage.py`), and a second DB `x4eff`
holds the *effective* merged tree. The rule is now:

- A **bare** "0 hits" is still just a lead. Never quote one.
- A negative from `tools\basex\ask.py` **is** admissible — it refuses to render a zero-result as a
  finding unless `coverage-<db>.json` says coverage is complete/accounted, and prints
  *"NEGATIVE CONFIRMED over N of M documents"* with every exclusion named.
- Prefer **`--db x4eff`** for any claim about what is LIVE. `x4raw` is files as written and will
  happily quote a vanilla value the modlist overwrote (`hullparts` 209 raw vs 240 effective).
- Load order is community convention, so any x4eff answer turning on *which mod won* is advisory.

x4validate remains the authority for correctness against the engine (oracle: 234/234 ops, 0 false OK).

**Validate the DEPLOYED copy, not the `dev\` copy, whenever load order could matter.** A mod that is
not installed has no knowable load-order position, so Tier B assumes it loads LAST — the optimistic
tree. Proven: `CapturableShipMod` (deployed) validates 0 errors while its byte-identical `_public`
twin (dev-only) reports 3 false alarms.
## Core Working Principle: Deductive Iteration — Work Backward from the Outcome

When a fix or feature needs iteration, never iterate blind. Before the FIRST attempt:

1. **State the outcome as observable acceptance criteria** — what the user will see/hear/measure when it's right.
2. **Enumerate the assumption chain** — every link that must hold for the approach to deliver that outcome — with a confidence level **per link**, not one blended number that hides the weak link.
3. **Design decisive tests**: each test confirms or kills a specific link (or reproduces a specific symptom), cheapest-first, self-driven (DevBench, console, logs, save parsing) wherever possible rather than user playtesting. A test whose result wouldn't change the next action is not a test.
4. **Pre-commit fallbacks** for every shaky link — know NOW what you'll do if it fails, so a failed test advances the plan instead of starting a new guess.
5. **Batch verification to minimize user cycles** (restarts, headset sessions). When a symptom report contradicts the model, STOP and re-derive the model from evidence (logs/traces) — never re-tune parameters inside a broken model.

**Anti-pattern this kills:** attempt N motivated only by the failure of attempt N−1 — parameter tweaks or mechanism swaps with no model of why THIS one reaches the outcome ("one foot in front of the other, eyes on the ground"). Iterate with eyes on the destination: fast because each step is load-bearing, safe because each step is verified — never slow for safety's sake, never fast by throwing caution to the wind.
## Core Balance Principle: Three Values, and IN-SECTOR vs OUT-OF-SECTOR (Mandatory)

**Never quote a bare number.** For every value you propose changing state the **vanilla** value,
the **effective** one (what it is right now, with the winning mod NAMED, or "no override"), the
**proposed** one, and the **in-game effect** in plain terms. A selector written against the
*vanilla* value silently matches nothing when something else already changed it — the single
most expensive bug class here. Get the effective value from `x4effective` or `x4validate --tier b`,
never from `reference\` alone.

**Every combat or balance change is checked for whether it lands disproportionately in-sector (IS)
or out-of-sector (OOS); the goal is that the two feel as close to 1:1 as possible.** They diverge by
construction: OOS is pure arithmetic — a factor absent from the formula does not exist — while IS is
physics, travel time, turret traverse, point-defence, terrain, RNG and the player. So the danger is a
factor decisive IS and invisible OOS, or the reverse: when a change's cost is paid by a mechanic,
ask what pays it OOS. Often nothing does. ⚠ **Never assume OOS models a mechanic because IS
does** — verify against the OOS scripts; an assumed formula is an ASSUMED-tier claim.

**Label every combat claim IS, OOS, BOTH or UNKNOWN, in the sentence that carries the number.**

→ **the `x4-balance` skill** carries the regime table, the `<attention min=>` branch markers that
say which regime a formula belongs to, and the packed-inclusive scoping rule.
## Core Principle: A Derived Artifact Must Declare WHEN It Was True (Mandatory)

**Durability note: memory files are NOT durable. Anything essential goes in `CLAUDE.md` or
`KNOWLEDGEBASE.md`.** Memory is a convenience index, not permanent record.

**⚠ AND MEMORY IS THE ONE ARTIFACT CLASS WITH NO FRESHNESS SIGNAL AT ALL.** The two-axis fingerprint
guards derived artifacts, `claims_audit` guards numbers, `ask.py` refuses a zero without a
denominator — **memory and plan files have none of that, and they are consulted FIRST.** A line
reading *"still X"*, *"not yet done"* or *"pending"* is an assertion about a world that moves without
us, and it reports success indefinitely.

**A memory or plan claim about EXTERNAL state — a Nexus page, a remote repo, a public release,
another session's tree, anything the user can change outside this session — is a LEAD, NEVER A
FACT.** Internal facts rot when we touch something; external ones rot with **nobody touching this
machine**, and the user acting outside the session is the NORMAL case, not the exception.
**Re-query the authoritative source before asserting it**, and **never put a decision to the user
without first checking whether it is already made** — that is worse than a wrong number, because it
spends their attention on a question they have already settled.

> **The case (2026-08-26).** Memory said *"Nexus 2186 still serves 2.1.1; upload is MANUAL and NOT
> done."* I asserted it twice in the grammar of a current fact — once asking the user to choose
> whether to upload 2.7.0, **a decision they had already executed**, and once inside a durable hold
> block **minutes after writing that block myself**. MEASURED by one documented API call:
> `version=2.7.0`, `status=published`, file **14770** category MAIN, uploaded 21:03; 2.1.1 demoted to
> OLD_VERSION. The authoritative source was one call away, is documented in this very file, and was
> not consulted — because the record answered confidently and reading it felt like knowing. The
> user's correction was *"Recheck your facts."*

**When you correct such a line, mark the old one SUPERSEDED rather than rewriting it** — it was true
when written, and that dated record is what lets the next session date the change.

**This is the section's own lesson one level up.** The 08-02 effective store was *fresh by its own
lights* — not one input file had changed — and wrong about the world anyway, which is exactly why
the **engine** axis had to exist. **Memory has no axis at all, so it is fresh by its own lights
permanently.** That is not a weaker version of the same problem; it is the same problem with the
detector removed.

**★★ AND ONE LEVEL FURTHER IN: YOUR LOADED CONTEXT IS A SNAPSHOT OF A FILE THAT HAS SINCE MOVED.**
The freshness fingerprint guards an *artifact*. It cannot guard **your copy of it**. On a long
session with concurrent writers, `CLAUDE.md`, `MEMORY.md` and every memory file were read **once, at
session start** — so quoting them from context is asserting a point-in-time claim about a file
another session may have corrected hours ago.

> **The case (2026-08-28), and it is the cleanest specimen yet because the record was ALREADY
> RIGHT.** A peer session asserted *"the release is ON HOLD by user instruction — no push, no tag"*.
> Its memory FILE on disk said the opposite: `## ✅ v2.8.0 RELEASED — the HOLD below is SUPERSEDED`,
> with the hold kept beneath as history, and the `MEMORY.md` index line rewritten to match — I had
> corrected both earlier that same session. **The peer quoted the index from its loaded context and
> never opened the record.** Nothing was stale on disk. The *reader* was stale.

**So the rule "a memory claim about EXTERNAL state is a lead, never a fact" has a twin: a memory
claim quoted from CONTEXT is a lead about the FILE too.** Before asserting anything load-bearing
from memory in a long session — especially a *hold*, a *decision*, or a *"not yet done"* — **re-read
the file, not your recollection of it.** `cat` costs nothing; the peer's assertion cost a
cross-session correction round trip.

⚠ **This paragraph is subject to its own warning.** It lives in `CLAUDE.md`, which is loaded once at
session start, so a session that reads it may be reading a copy older than the file.

Coverage answers *how much* was indexed. It does not answer *as of when*, and an artifact that no
longer describes the world reports success indefinitely — a third state beside absence and
non-answer: **an answer about a world that has moved on.**

> **The case (2026-08-13).** BaseX `x4eff` was built 08-02. The merge engine was fixed 08-08
> (root-`<replace>`: **858 ops dropped while reported applied**) and 08-11 (nested patches).
> **Neither date changed one input file.** MEASURED on rebuild: **140 of 194 (72%)** engine thrust
> rows changed — `engine_arg_l_allround_01_mk1_macro` **3900 → 5283** (vanilla 3900, OVERHAUL 5283).
> A design decision recorded on 08-02 had written vanilla engine values down as OVERHAUL's.

**Every persisted artifact carries a two-axis fingerprint** (`x4validate/_freshness.py` — the single
implementation; BaseX delegates to it):

| axis | covers | why |
|---|---|---|
| `content` | installed extension set + each manifest mtime/size + a reference marker | mods added/removed/updated |
| `engine` | hash of the **BYTES** of every file named in `_freshness.ENGINE_SOURCES` — **derive that list from the module, never retype it** (**8** as of 2026-09-07: `_cat`, `_diff`, `_effective`, `_loadorder`, `_merge`, `_registry`, `_scan`, `_xpath`). ⚠ THIS CELL HAS NOW BEEN WRONG TWICE, THE SAME WAY, IN THE SENTENCE TELLING YOU NOT TO RETYPE THE LIST. 2026-08-29 it said 5 and omitted `_effective`/`_registry`, and a comparison hand-typed from it came out clean either way — a check whose result was independent of its input. 2026-09-07 it said 7 and omitted `_loadorder`, which F69's remedy had lifted out of `_compat` in this very arc, so the change that made the doc stale was one of ours. Mechanized rather than corrected again: `tests/test_reference_fingerprint.py` now asserts this cell lists exactly what the module derives | a merge fix changes the answer for identical inputs; a commit hash does not move for a dirty tree |

Artifacts: effective store (`meta`) · `md_xref.tsv` (sidecar) · BaseX `x4raw`/`x4eff`
(`coverage-<db>.json`). **Absent fingerprint = UNKNOWN, never fresh.** Each CLI banners every run
until rebuilt; `ask.py` and `gates/claims_audit.py` REFUSE a claim outright. `engine_dependent` is
per-artifact — a raw file index is not a merge product, and flagging it anyway trains you to ignore
the banner.

Rebuild: `uv run x4effective build` · `uv run x4xref build` ·
`cd tools/basex && bash build-corpus.sh && bash build-effective.sh`

**Corollary — a design doc's numbers rot silently.** Prose cannot be tested, so numeric claims live
in `dev\_registry\CLAIMS.tsv`, re-checked by `gates/claims_audit.py` against the store.
UNRESOLVED is never a PASS, and the gate refuses to run against a stale store.
## Core Principle: Tools Must Be Trustworthy BEFORE the Modlist Is Locked (user standard)

> *"I can't settle on a good modlist until I can trust that my tools are feeding me the right data…
> once the list is locked it's largely fixed, particularly for mod removal."*
> *"[an external unknown] is understandable… but anything internal that we have now, on disk, is
> inexcusable."*

A sequencing rule, not a preference: removing a mod is not symmetric with adding one, so a defect
found after the lock costs far more than the same defect found before.

- **Split unknowns into EXTERNAL and LOCAL.** External (Nexus ids, upstream versions) may sit
  unresolved *if labelled*. **Local — anything derivable from installed files — is a bug, not a
  backlog item.**
- Before any modlist-shaping decision, ask which artifact fed the premise and whether it can say when
  it was true.
- **Read an artifact's schema before declaring it incomplete.** The registry keeps local facts
  (`installed_name`/`installed_version`/`path`) in slots SEPARATE from upstream ones
  (`name`/`version`). Three "gaps" reported on 08-13 were misreadings of the upstream slots.
## Core Principle: Bug Handling Is a FUNNEL — Wide at the Top, Narrow at the Bottom (user-set 2026-08-30)

**Identification is WIDE.** Be vigilant for anything that does not make sense or is contradictory —
in game files and in our own tools' output alike — and surface ALL of it. Never assume a tool is
working. Keep an explicit UNMEASURED list and never dismiss it.

**Remediation is NARROW.** Act only on deductive proof of both the bug AND its root cause.
**Easy to identify, hard to act on.** The toolkit cannot converge if *"it's broken"*, *"actually that
was wrong"* and *"now you broke it"* alternate — and the base rate says the CHECKER is wrong far more
often than the finding (gotcha #22).

**Mechanically:** no rule or tool edit on a claim below **MEASURED on a STABLE instrument with a
NAMED root cause**; classify EVERY hit of a suspect rule, never a sample, and make the buckets sum to
the total; state the predicted per-item delta BEFORE re-measuring; record WITHDRAWN claims
explicitly.

> **The case (2026-08-30).** F82 — *"the hooks deny 8.89% of real work"* — was measured while the
> live hook was REDEPLOYED mid-run: launch 22:28, deploy 00:08:29, finish 00:15:36, three
> independent timestamps. Its per-rule table was not reproducible, and a plan to *"fix four verified
> false positives"* had already been built on it. Five checker bugs in the red-team pass that found
> this (a `\b` that excluded `-rn`; a reason truncated before the word it was bucketed on; an O(n²)
> timeout; a guard denying the analysis for MENTIONING a job name; a divergence "explained" before
> the timestamps were read) — every one a confident wrong reading, none caught by looking at output.
## Concurrent Sessions: Isolate the TREE, Share the HISTORY (Mandatory)

**Two or more sessions run in this workspace at once — typically a tooling/dev session and a mod
session. Every failure this caused on 2026-08-27 was a CONCURRENCY failure, not a logic one**, and
they were all invisible until something numeric disagreed.

| what broke | MEASURED |
|---|---|
| shared working tree | one session's suite silently went **836 → 877 tests**; 41 were the other session's untracked WIP |
| `git add -A` | **0 of 4 commits** picked up their files — timing, not care |
| half-committed shared file | a **tracked** `cli_case _livecli` line beside an **untracked** `_livecli.py` made `verify-cold.sh` fail on a file that session had never opened |
| shared append-only doc | the verifier register collided at **#93**; two tallies drifted to *"96 of 96"* vs *"93 of 94"* |
| corpus drift mid-measurement | a mod went clean → *"folder not found"* between two census runs |
| concurrent artifact builds | BaseX `x4eff` came back with a **17% deficit**, cause undetermined, the only surviving hypothesis being contention with a simultaneous store rebuild |

### The rules

1. **ONE GIT WORKTREE AND ONE BRANCH PER SESSION.** `git worktree add ../x4validate-<lane> -b
   session/<lane>`. MEASURED cost: **~27 MB** (21 MB `.venv` + 6 MB source) and seconds to build.
   This kills the whole class — untracked collisions, contaminated test counts, half-committed
   shared files, `verify-cold` seeing work that is not yours. Merge normally when a piece lands.
2. **NEVER `git add -A` or `git add .` in a shared tree.** Stage explicit paths. Mechanized in
   `.claude/hooks/protect-bash.sh` (10 cases in `test-protect-bash.sh`: 4 must-fire, 6
   must-NOT-fire, including `git add -p` and `git add .gitattributes`).
   ~~ASK~~ **-> it is a DENY** (corrected 2026-09-01; this line said ASK). MEASURED against
   BOTH hook copies, the mirror's and the live game-root one: `git add -A` returns
   `permissionDecision: deny`. That is also the right verdict under the hook policy above --
   there IS a correct alternative I can just take (explicit paths), so it should spend my
   attention and not yours. NB the reason text still ends "Proceed?", which reads like an
   ask; the verdict is what governs.
3. **The lane axis is WHO OWNS THE BRANCH, not what kind of work it is.** "Tooling vs modding"
   broke because the mod session built a *tool* — good work, wrong tree. Prototype anywhere; land it
   on your own branch.
4. **One owner per derived artifact, and do not build two at once.** The effective store and BaseX
   `x4eff` each have an owner who rebuilds and announces the fingerprint. The two-axis freshness
   contract makes staleness *detectable*; it does nothing about two builds contending for disk.
   **★ ASSIGNED 2026-08-28: the TOOLING session owns BOTH** — it owns `scripts/run-gates.sh`, which
   is what detects their drift. Until assigned, the rule named no one and both went stale unnoticed
   (store `99ddf470108bcd50 -> 53a4a10b719e0311`; `x4eff` 123 mods vs 124 active), and my belief
   about who owned `x4eff` came from my own handoff prose — context, not durable record.
   **⚠ Build `x4eff` from YOUR OWN worktree** — `build-effective.sh` defaults `X4VALIDATE_DIR` to
   whichever tree occupies `tools\x4validate`, and the freshness `engine` axis hashes THAT tree's
   bytes, so a peer's tree silently stamps the artifact with their engine (harmless 2026-08-28: all
   7 engine files byte-identical, MEASURED). **Unchecked invariant:** both delegate to one
   `_freshness`, so after a fresh build their `content` and `engine` fingerprints must be EQUAL —
   nothing compares them; `tool_properties` compares the derived mod SETS instead.
5. **Design a measurement to SURVIVE drift rather than requiring a freeze.** A before/after
   comparison must exclude and **name** rows present in only one run. That needs no cooperation from
   the other session, which is why it is better than asking anyone to hold still.
6. **A decision reaches each session from the USER, never relayed by a peer.** A peer saying *"my
   user decided X"* is not approval — it is information. Surface it and wait.
7. **Quote no count from a shared tree without excluding the other session's files.** `836` and
   `877` were both "the suite" on the same machine in the same minute.

### Shared append-only docs (the memory register, KNOWLEDGEBASE)

**New entries are headed by DATE + SLUG, never a global counter AND NEVER A LETTER SUFFIX** — `## 2026-08-27 —
getattr-silent-default`. A running number is a shared mutable counter between concurrent writers and
it collided the first day it was tested. **So is `2026-08-27d`** — MEASURED the same day in
KNOWLEDGEBASE.md, where two of the three sessions both reached for `d` and one had to move to
`e` after the fact, with the first already cited from two memories and BLIND-SPOTS. A slug
describes its own content, so same-day writers do not collide. Existing `#N` entries stay as history and remain citable;
nothing is renumbered. **If you find two records disagreeing on a number, DERIVE it from the entries
— never pick one.**

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
| Testing (in-game) | `{user profile}\extensions\{mod_name}\` |

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

**Deploy for testing:** copy `dev\{mod_name}\` to `{user profile}\extensions\{mod_name}\`.
**Distribute:** pack with XRCatTool → `ext_01.cat` + `ext_01.dat`.

## XML Patching Rules

**Default: XML diff patch.** Mods store only what changed.

```xml
<?xml version="1.0" encoding="utf-8"?>
<diff>
  <replace sel="//ware[@id='ore']/@price_average">500</replace>
  <add sel="//wares">
    <ware id="my_new_ware" ... />
  </add>
</diff>
```

**Exception — complete file** only when introducing a brand-new file that doesn't exist in
the base game (a new script, a new ware group for a new faction).

**File path mirroring is critical:** a diff patch's path inside the mod must EXACTLY mirror
the base game path. One folder-name mismatch and the patch silently does nothing.

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

## Nexus Research (Standing Rule)

**Always research a mod's Nexus page before editing it** — description, articles, changelogs,
comments, bug reports. Most issues have been seen by others.

### Nexus API (programmatic metadata)
**API-FIRST: access Nexus ONLY via the API — never scrape Nexus pages** (they 403 automation).
- Metadata by id: `GET https://api.nexusmods.com/v1/games/x4foundations/mods/{id}.json`, header `apikey`. `status` = `published`/`removed`/`hidden`.
- Name→id search: `POST https://api.nexusmods.com/v2/graphql`, header `apikey` + a real `User-Agent` (Cloudflare 403s without it), filter `gameId:[{value:"2659"}], nameStemmed:[{value:"<name>"}]`.
- Steam Workshop title (keyless): `POST https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/`.
- **Each user supplies their OWN key** in the `X4_NEXUS_KEY` env var. Never bundle, commit, or log a key. Get one free at nexusmods.com → Site preferences → API Access.
- Resolution cascade for a mod's identity/version: installed `content.xml` → mod README/changelog → Steam Workshop page → Nexus API (last resort / upstream-latest).

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

## Core Principle: Vanilla X4 as Frame of Reference

Before implementing any change — even a novel one — find how the base game (in `reference\`)
handles the closest equivalent and model the solution on that pattern. The unpacked base game
is proof-of-concept. If vanilla doesn't do it that way, ask *why* before choosing your
approach. Approaches disconnected from how the engine works lead to silent failures.
1. Find the vanilla analogue (same action, macro, ware, cue type).
2. Match its exact form — attributes, structure, values.
3. Only diverge when the vanilla pattern genuinely cannot be adapted.

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

## Core Principle: Native Engine Solutions First

Before a convoluted workaround, ask: "how does the engine already handle this?" "Simple"
means simple from the engine's perspective, not fewest lines. Prefer native MD actions and
script properties; a diff patch over rewriting a whole file; the game's own events/cues over
polling. Custom MD/Lua is a supplement, not a replacement.

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

## Top XML Gotchas

1. **Diff patch file paths must EXACTLY mirror game internal paths** — one folder mismatch = silent no-op.
2. **CAT/DAT catalogs override in numeric order** — 09 > … > 01; DLC overrides base; user extensions override everything.
3. **`t/` translation files and `index/` files are UNIONED, not overridden** — same-path files ADD entries across base + DLC + mods. A `{page,t}` may live in neutral `0001.xml` OR English `0001-l044.xml`; check both.
4. **content.xml `save="1"`** — mod is baked into saves; removing it can corrupt them. Use `save="0"` for cosmetic/UI mods.
5. **content.xml does NOT reflect what's installed** — it can list dead/unsubscribed entries the engine ignores. The `extensions\` folder is the source of truth.
6. **9.0: `find_station` (and the whole `find_*`/`count_*`/`set_space_*` family) now REQUIRE `space=`** — a 7.x mod without it throws `Required attribute 'space' is missing` on load. Galaxy-wide = `space="player.galaxy"`.
7. **A `sel=` matching MULTIPLE nodes is a SILENT NO-OP** — RFC 5261 requires exactly one match; X4 logs `Multiple matching nodes for path '<sel>' ... Skipping node` and applies **nothing**. The patch reads fine and does nothing. Disambiguate with a predicate (prefer a content predicate like `[material[@shader='x']]` over a positional index). Run `x4validate` — it flags this.
8. **Patching ANOTHER mod uses a NESTED path** — `<your_mod>/extensions/<target_folder>/<mirrored path>`, not a bare mirrored path. The `<dependency id=>` you declare is the target's `content.xml` **id**, which can differ from its folder name.
9. **A stale `<remove>` in an old mod can delete content the base game added LATER**, breaking every other mod that uses it. Diagnose *why* a remove exists (usually half of a stale remove/re-add pair) before assuming the author meant it.

*Consult `KNOWLEDGEBASE.md` for the full list and the 7.x→9.0 migration map.*

## x4live is EXPERIMENTAL — say so before you use it

**Before running any `x4live` command against the user's game, tell them it is
experimental and recommend a throwaway save.** Do not wait to be asked. Most people
will not have read the README section, and by the time it matters the mod is already
loaded into whatever save they had open.

Be accurate about the risk, or the warning gets ignored. MEASURED 2026-09-02 across
both shipped lua files: the query channel makes **zero** state-changing engine calls,
there is no write verb of any kind, and `content.xml` declares `save="false"` so it
cannot bake into a save. What is true is narrower:

* the addon loads into a RUNNING game, and `engine_probe` runs automatically at load;
* `engine_probe.lua:196` calls `C.SaveUIUserData()`, writing the profile's UI userdata;
* **its answers have been wrong** — until 2026-09-02 `verbs.macro` reported a failed
  engine call as `ABSENT`, i.e. "the engine has nothing here", and such answers feed
  groundtruth fixtures. Report what it says as EVIDENCE, never as truth;
* removing a mod from a save lets the engine silently delete that mod's content
  (no dialog, usually no error line).

So: recommend a scratch save, and never imply the tool is a settled instrument.

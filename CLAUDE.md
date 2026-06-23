# CLAUDE.md — X4 Foundations Modding (Claude Code Toolkit)

Guidance for Claude Code when working in an X4: Foundations modding environment.
This file is loaded automatically every session.

## What This Is

An AI-assisted X4 (v7.x–v9.x) modding workspace. The goal is coordinated multi-file XML
editing — adding and modifying wares, ships, stations, and balance values consistently
across every file a feature touches. Claude's role is to handle the tedious, error-prone
cross-file work and catch the silent-failure bugs before an in-game test cycle is wasted.

## Key Paths (personalize during setup)

X4 modding spans a few locations. Configure these for your install — `setup.sh` and the
environment variables below personalize them; nothing here hardcodes a user path.

| Location | What |
|----------|------|
| Game root | your Steam/GOG `X4 Foundations\` folder (holds `01.cat`–`09.cat`, `extensions\`) |
| Base game archives | `{game root}\01.cat` … `09.cat` (+ DLC under `extensions\ego_dlc_*`) |
| **Reference (read-only)** | a local `reference\` you unpack from your OWN game with XRCatTool (`X4_REFERENCE`) |
| Mod dev workspace | wherever you author mods, one folder per mod (`dev\{mod_name}\`) |
| User profile | `Documents\Egosoft\X4\<profile-id>\` — the active one has the newest `debug.txt`/saves |
| Active mod list | `{user profile}\content.xml` |
| Testing (in-game) | `{user profile}\extensions\{mod_name}\` |

> **Never redistribute Egosoft game data.** `reference\` is unpacked from your own copy and
> is gitignored. The toolkit ships no `.cat`/`.dat`/XML game content.

## Bundled Tools

| Tool | Purpose |
|------|---------|
| **x4validate** ⭐ | Cross-file validator (`tools\x4validate\`, lxml). Checks every diff `sel=` resolves against the real base+DLC merged tree, that ware/macro/`{page,t}` references resolve, and completeness of new content vs a vanilla analogue. **Run on every mod before deploying.** `cd tools\x4validate && uv run x4validate <dev\mod>` |
| **x4modlist** | Mod-registry triage via the Nexus API (version/status/changelog). `uv run x4modlist <cmd>` |
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

## Dry-Run Convention

For any bulk XML operation (mass stat changes, adding content to many files):
1. **Read-only pass** — log every file and value that would change; do NOT write.
2. **User reviews** the proposed changes.
3. **Write pass** — only after approval.

## Safety Rules (enforced by hooks in `.claude/settings.json`)

### Hard blocked
- Writing to `reference\` (read-only base game data, ever)
- Directly writing `.cat` / `.dat` files (use XRCatTool)
- Writing game installation files outside `.claude\`

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

*Consult `KNOWLEDGEBASE.md` for the full list and the 7.x→9.0 migration map.*

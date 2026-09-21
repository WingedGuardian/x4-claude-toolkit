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
| **x4validate** ⭐ | Cross-file validator: every diff `sel=` resolves against the real base+DLC merged tree, ware/macro/`{page,t}` references resolve, and new content is complete against a vanilla analogue. **Run on every mod before deploying.** `cd tools\x4validate && uv run x4validate <dev\mod>` |
| **x4modlist** | Mod-registry triage via the Nexus API. The INSTALLED extension folders are the primary source of truth; `content.xml` is a secondary cross-check. |
| **x4compat / x4xref / x4stats / x4similar** ⭐ | Cross-mod suite, one package: collisions over the effective tree (packed mods included), a who-calls/who-listens index over MD+aiscripts, advisory numeric comparison, and fuzzy same-ship detection. → the `x4-mod-interaction` skill. |
| **XRCatTool** (Egosoft) | Unpack base CAT/DAT → `reference\`; pack `dev\` for distribution. You supply it. |

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

**Running `x4validate` is routine and non-optional** — like checking `debug.txt`. Run it after
editing any patch and BEFORE deploying for an in-game test, and again after a game update. It
catches the two most expensive bugs statically: a `sel=` that silently matches nothing, and a
file the change forgot. **A clean run is necessary, not sufficient** — still test in-game.

**After ANY change to `.claude/hooks/`, run `bash scripts/test-hooks.sh`.** The hooks are the
safety net and nothing else exercises them; several shipped silently inert because the code
read fine.

→ **the `x4-xml-patching` skill** has the flags: `--tier b` for cross-mod work, `--entity/--like`
for completeness, and why an `if=`-guarded op reports INFO while a passing guard over a missing
`sel=` is a real error.

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

**Never frame tool work as time taken away from "the real work."** Work produced on an untrusted
instrument is not wasted, it is **negative**: it is confident, it compounds, and it gets written
where the next session reads it as truth. When a tool defect and downstream work compete, **the
tool wins** — stated as a reason, never as an apology.

**A tool that cannot distinguish a GUESS from a MEASUREMENT is a defect, not a limitation.**
Provenance travels with the value: a guessed field must never occupy the same slot, in the same
grammar, as a verified one, and nothing derived from a guess may be promoted into a confident
state. That applies to our own output too — a report, a registry row and a knowledgebase line
each carry their tier or they do not ship. The registry once stored a GUESSED Nexus id beside
`settled: stable`, so "is my copy the old version?" could not be answered from it at all.

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
"this is dead". The failure this prevents is pattern-matching a symptom onto a plausible story
("the new version removed this") and then deleting working content on it — the one action whose
damage is invisible in a clean validate run.

Before calling anything obsolete: **read the error literally** (it usually names the scope —
`Order 'MiningRoutine': Parameter 'stayinspace' was not expected` scopes to ONE order, and that
parameter is still valid in 9.0 elsewhere); **grep `reference\` for live uses** (any vanilla or
DLC use means your call is wrong); **date the change** (a thing missing from an old file is
usually old, not new); and **check who else references it**.

**Destructive changes — `<remove>`, deleting files, stripping attributes, "cleanup" — require
explicit user approval**, a higher evidence bar than additive ones, and a snapshot first. Prefer
additive repairs: restoring an orphaned index entry is reversible and provably scoped; deleting a
reference is not.

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

**Before running any `x4live` command against the user's game, tell them it is experimental and
recommend a throwaway save** — unprompted. Only `pause`/`unpause` write, and only when asked;
its answers are EVIDENCE, not truth (they have been wrong). → the **`x4-live`** skill has the
detail and the traps.

## Nexus Mod Research (Standing Rule)

**Always search a mod's Nexus page before investigating or editing it** — description, articles,
changelogs, comments, bug reports. Most issues have been seen by another user already.

**★ API-FIRST: reach Nexus ONLY through the API, NEVER by scraping** (pages 403 automated
fetches; Steam pages are scrapeable, Nexus is not). Each user supplies their OWN key in
`X4_NEXUS_KEY` (or `.claude/x4-paths.env`): never bundle, commit or log one.

→ endpoints, the rate budget, the local-first resolution cascade and how to get a key live in
`x4validate/_nexus.py`, next to the code that calls them; **`x4-modlist-review`** drives the triage.
## Modding Workflow (Per Change)

1. **Research first:** the mod's Nexus page, any mod touching the same files, and the vanilla
   structure in `reference\`. Name EVERY file the change must touch before writing one.
2. **Implement:** a diff patch for existing content, a complete file only for new content,
   mirroring the game's folder structure inside `dev\{mod_name}\`.
3. **Validate, then test:** `x4validate` before any in-game cycle, deploy to the game-root
   `extensions\`, then read `debug.txt`.

## Core Principle: PROVE IT RAN BEFORE DEBUGGING WHAT IT DID (Mandatory)

**A change that produces no output has THREE indistinguishable causes, eliminated in this
order:** it did not load · it loaded but never triggered · it triggered and the logic
failed. Debugging the third while the first or second is true is unbounded, because every
observation is consistent with every theory. One such harness cost **three play sessions**,
none of them spent on the experiment.

1. **Did it LOAD?** A signature line in `debug.txt` naming the file. Absent = not installed
   or not enabled, and nothing else matters.
2. **Did it TRIGGER?** An unconditional marker as the FIRST action, before any logic. X4
   specifically: a top-level cue with **no `<conditions>`** fires on new game AND save load,
   while `event_game_loaded` fires on a SAVE LOAD only — which silently wasted one of
   those three sessions.
3. **Only then** debug what it did.

⚠ **Static validation cannot see runtime wiring.** `x4validate --update` returned `OK: no
issues found` on a script the engine rejected three times: cue-trigger semantics and order
signatures (`Attack` takes `primarytarget`, not `target`) are not expressible in a schema.
**For a new script the engine log is the FIRST real check, not the last.** And instrument
where the USER is looking — `debug.txt` is invisible during play, so an in-game harness
reports through `<show_notification>` AND `<write_to_logbook>`, and states elapsed time from
a landmark they can SEE, never from process start.

## Core Principle: Evidence Must Match the Scope of the Claim (Mandatory)

**The user must never have to ask "did you actually verify that?" If they have to ask, the process
already failed.** Two rules, both non-negotiable.

### 1. The scope of your evidence must match the scope of your claim

| Evidence you have | The ONLY claim it supports |
|---|---|
| You read **one file** | *"This file does X."* |
| You read **one mod** | *"This mod does X."* |
| You measured **the corpus, with a denominator** | *"X is how it works"* / *"N of M do X"* |

**One file NEVER supports a statement about the engine, the schema, or "how it works now."** A
real engine change shows up across the whole corpus, and checking the corpus is one query. From
ONE macro file carrying `<explosiondamage value=...>` with no `@shield` I once asserted that 9.0
had consolidated the attribute — into the knowledgebase and an upstream report. Measured
afterwards: **488 of 610** occurrences still carry `@shield`, and **183 of 185** among ship
macros. It was a mod-vs-mod convention mismatch, and the query that would have caught it took
seconds. **A surprising observation is a QUESTION, not an ANSWER.**

### 1b. An AGGREGATE can hide the very thing you are measuring — compare PER ITEM

A performance run over 115 mods totalled **594.4 s → 595.7 s = 1.00x**, clean by any reading,
while two mods had gone **2.8 s → 112 s (39x)** and **2.4 s → 121 s (51x)** — hidden because a
third got faster and cancelled them out. Whenever you compare two states — timings, counts,
findings, collision rows — **diff the ITEMS, not the totals**, and quote the aggregate only as
context. The same holds for a COUNT of findings: "42 added, 0 removed" is reassuring only once
every one of the 42 is attributed to an intended cause.

### 2. Label the evidence tier — in prose and in permanent record

- **MEASURED** — "I ran X; 488 of 610." State the number and the denominator.
- **READ** — "`reference\md\foo.xml:942` has this node." Cite file and line.
- **INFERRED** — **must** be hedged out loud: *"I think"*, *"this looks like"*, *"unverified, but"*.
- **ASSUMED** — say so, and say what would confirm it.

**Never write an INFERRED claim into permanent record in the grammar of a fact.** Permanent record
has no tone of voice: the next session reads a confident sentence as measured truth and builds on
it. *"`hunterpack_small_turrets` is the foundation dependency of the hunterpack ship family"* was
an inference written as a fact, then re-quoted as a fact later; measured, it defines 22 S-turret
macros that the ships reference **zero** of. If verifying is too expensive right now, hedge it and
flag it as open — what is never fine is an unverified claim wearing the grammar of a verified one.

## Core Principle: A Step That Narrows Data MUST Announce It

**Every tool defect found in this workspace has had one shape: a step that narrows the data
and reports success anyway.** One class, not an assortment — and the enumeration variant
alone was written **five times**. What the instances cost, MEASURED: a `continue` that dropped
an op yet marked it applied (**858 ops**, so `x4effective` served vanilla values for real
overrides); a walk that stopped descending (**9,197 of 13,291** ship attributes, the whole
flight model, absent); a loose-only `rglob` or the wrong source list across **7 files**
(x4xref returned **0 rows from 13 real files**); the wrong SET, on-disk where engine-loadable
was meant, which let **Tier B resolve a selector against a DISABLED mod and report OK** —
a false pass in the mode built to catch no-ops; a denominator taken from the artifact it
audits (COVERAGE COMPLETE over a tree missing **119 documents**, which **0 of 210** failures
could ever name); and `el.get("id")` skipping an absent attribute, which would have indexed
**zero entities while reporting success**.

**The rule: a tool that returns nothing must say whether that is an ABSENCE or a NON-ANSWER.**
`tools/basex/ask.py` is the standard — it refuses to render a zero as a finding without a
coverage denominator. Anything that cannot make that distinction is a defect, not a limitation.

- **State the SCANNED SOURCE SET, not just the failed reads.** A blind spot is by definition
  not among the files you tried and failed to parse: "base + **6** DLC + 71 mods" when 8 DLC
  exist is self-evident on sight, and reporting only parse failures hid exactly that.
- **One implementation, asked for by everyone else.** Two of those five files already carried a
  comment explaining the bug, and it was written again anyway. Only a shared helper plus a test
  banning the hand-rolled form stops the next one.
- **The same wrong answer can have different causes.** A sibling gate carried the identical
  hand-rolled walk and failed for an unrelated reason. Fix the occurrence on its own evidence.

**When you find one, search for the SHAPE, not the symptom** — scope limits, depth limits,
singular reads, silent skips, two paths answering one question — and give every occurrence a
measured denominator and a register row, **including the ones that turn out correct**: a
register without negatives has no denominator either.

## Discovery vs. Proof (Standing Rule — which tool answers which question)

**Route BEFORE you search.** Ask *"which tool answers THIS question?"* before typing a search
command, not after it returns something confusing — reaching for `grep`/`find` by reflex when a
purpose-built tool exists is a recurring, expensive failure. It is a rule about which tool you
REACH FOR, not only about what you may claim. Exact flags and subcommands: the generated
`x4-cli-reference` skill.

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
| **"scan EVERY installed mod for X"** (an ad-hoc corpus sweep) | **`_scan.iter_corpus_xml(ext, report)`** + **`CorpusScan.verdict(hits, noun)`** — it states the scanned set, so a zero is an ABSENCE and not a non-answer. | a hand-rolled loop over `extensions/` — loose-only, and silent about what it never opened |
| **"every base+DLC vpath?"** | **`_effective.base_vpaths`** (loose THEN packed; `reference_vpaths` is its `assets/`-only filter) | ✗ `reference.rglob("*.xml")` — loose-only, so the two mini-DLC are invisible. Written **7 times**; now gated by `tests/test_no_loose_only_reference_walk.py` |
| **"does this vpath exist in the LIVE tree, and WHO supplies it?"** | **`x4effective dump --chain <vpath>`** — rc 0 names every source in order, rc 1 means absent. | `_effective.base_has` — base+DLC only, so a mod-supplied file reads as a confident ABSENT |
| what is installed / what has updates / is this abandoned? | **x4modlist** | reading the profile `content.xml` as an inventory -- it is a DECISION LOG |
| how do a mod's numbers compare to the live tree? | **x4stats** (advisory, never a verdict) | quoting a vanilla number as if it were effective |
| what changed between two versions of a mod? | **x4diff** | eyeballing two folders, or `diff -rq` -- line endings swamp the real findings |
| what is baked into a savegame, and what does it reference? | **x4save** | assuming a removed mod leaves dangling refs -- the engine deletes them silently |
| what is the RUNNING game's state right now? | **x4live** (needs the game running) | inferring live state from files on disk |
| mutation-test code? | **`gates/mutation_probe.py`**, but ONLY the 9 `x4validate/_*.py` files it names -- it takes no target argument | hand-mutating anything else (gates, hooks) without clearing `__pycache__`: a same-length mutant restored within one SECOND leaves its BYTECODE behind |
| **"does a file with this NAME exist?"** | **Glob** | ✗ **Grep** — it searches *contents*; a file can exist without containing its own name |
| "find this text, in one known area" | **Grep** tool (ripgrep) | ✗ `grep -r` via Bash |

★ **A negative from ONE invocation mode is a claim about that MODE, not about the tool.**
MEASURED 2026-08-27: `x4validate` reported OK on a schema-invalid MD file and was filed as "it
does not schema-validate MD". It does — the pass is gated behind `--update`, and **"no such
check" and "the check is gated" produce an IDENTICAL clean output.** Before filing *"the tool
does not do X"*, check whether X sits behind a FLAG; a default mode is a configuration, not a
capability. **Never state a negative from a tool that cannot see the whole picture:**

| Question | Tool | Why |
|---|---|---|
| *Discovery* — "where does this appear, what values exist, who mentions X?" | **BaseX** | Fast across many files, packed mods included; **but `x4raw` is files as-written, with no diff application or load order** (`x4eff` is the merged tree). |
| *Proof* — "what does the game actually see / is this reference real?" | **x4validate / x4effective** | Reads packed `.cat` via `_cat`, applies diffs in load order, models the effective merged tree. |

**A BaseX negative is admissible — but only with a denominator.** Packed content is staged and
indexed, and `x4eff` holds the effective merged tree, so: a **bare** "0 hits" is still only a
lead; `tools\basex\ask.py` refuses to render a zero as a finding unless `coverage-<db>.json`
says coverage is complete or accounted, printing *"NEGATIVE CONFIRMED over N of M documents"*
with every exclusion named. Prefer **`--db x4eff`** for any claim about what is LIVE — `x4raw`
is files as written and will quote a vanilla value the modlist overwrote. Load order is
community convention, so an x4eff answer turning on *which mod won* is advisory. x4validate
remains the authority for correctness against the engine.

**Validate the DEPLOYED copy, not the `dev\` copy, whenever load order could matter.** An
uninstalled mod has no knowable load-order position, so Tier B assumes it loads LAST — the
optimistic tree. Proven: one deployed mod validates clean while its byte-identical dev-only twin
reports three false alarms.

## Core Working Principle: Deductive Iteration — Work Backward from the Outcome

Never iterate blind. Before the FIRST attempt: state the outcome as **observable acceptance
criteria**; enumerate the **assumption chain** with a confidence **per link**, not one blended
number that hides the weak one; design tests that each confirm or kill a specific link,
cheapest-first and self-driven rather than by user playtesting; and **pre-commit a fallback for
every shaky link**, so a failed test advances the plan instead of starting a new guess.

**A test whose result would not change the next action is not a test.** Batch verification to
minimise user cycles, and when a symptom report contradicts the model, STOP and re-derive the
model from evidence — never re-tune parameters inside a broken model.

**The anti-pattern this kills:** attempt N motivated only by the failure of attempt N-1 —
parameter tweaks with no model of why THIS one reaches the outcome.

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

Coverage answers *how much* was indexed, never *as of when*, and an artifact that no longer
describes the world reports success indefinitely — a third state beside absence and non-answer.
MEASURED: a merge-engine fix changed **140 of 194 (72%)** engine thrust rows with **not one input
file changed**, after a design decision had already been recorded off the stale numbers.

**Every persisted artifact carries a two-axis fingerprint** (`x4validate/_freshness.py` — the single
implementation; BaseX delegates to it):

| axis | covers | why |
|---|---|---|
| `content` | installed extension set + each manifest mtime/size + a reference marker | mods added, removed or updated |
| `engine` | hash of the **BYTES** of every file named in `_freshness.ENGINE_SOURCES` — **derive that list from the module, never retype it** (**8** as of 2026-09-07: `_cat`, `_diff`, `_effective`, `_loadorder`, `_merge`, `_registry`, `_scan`, `_xpath`). ⚠ This cell has been wrong TWICE, the same way, in the sentence telling you not to retype the list, so `tests/test_reference_fingerprint.py` now asserts it lists exactly what the module derives | a merge fix changes the answer for identical inputs; a commit hash does not move for a dirty tree |

**Absent fingerprint = UNKNOWN, never fresh.** Each CLI banners every run until rebuilt; `ask.py`
and `gates/claims_audit.py` REFUSE a claim outright. `engine_dependent` is per-artifact — a raw file
index is not a merge product, and flagging it anyway trains you to ignore the banner. Rebuild:
`uv run x4effective build` · `uv run x4xref build` · `cd tools/basex; bash build-corpus.sh; bash build-effective.sh`

**Corollary — a design doc's numbers rot silently.** Prose cannot be tested, so numeric claims live
in `dev\_registry\CLAIMS.tsv`, re-checked by `gates/claims_audit.py` against the store. UNRESOLVED is
never a PASS, and the gate refuses to run against a stale store.

### Memory and loaded context are LEADS, not facts

**Memory files are NOT durable — anything essential goes in `CLAUDE.md` or `KNOWLEDGEBASE.md`.**
Memory is a convenience index, and **the one artifact class with no freshness signal at all**,
while being consulted FIRST: a line reading *"still X"*, *"not yet done"* or *"pending"* reports
success indefinitely. The fingerprint above exists because an artifact can be fresh by its own
lights and wrong about the world; memory has no axis at all, so it is fresh permanently.

**A memory or plan claim about EXTERNAL state — a Nexus page, a remote repo, a public release,
another session's tree — is a LEAD, NEVER A FACT**, because those rot with nobody touching this
machine. Re-query the source before asserting it, and **never put a decision to the user without
checking whether it is already made**. When you correct such a line, mark the old one
**SUPERSEDED** rather than rewriting it: that dated record is what lets the next session date
the change.

★★ **And your loaded context is a snapshot of a file that has since moved.** On a long session
with concurrent writers, `CLAUDE.md`, `MEMORY.md` and every memory file were read **once, at
session start**. A peer once asserted a release was on hold while the record on disk already said
SUPERSEDED — nothing was stale on disk, the READER was. Before asserting anything load-bearing
from memory — especially a *hold*, a *decision*, a *"not yet done"* — **re-read the file, not
your recollection of it.** ⚠ This paragraph is subject to its own warning.

## Core Principle: Tools Must Be Trustworthy BEFORE the Modlist Is Locked (user standard)

A sequencing rule, not a preference: removing a mod is not symmetric with adding one, so a defect
found after the lock costs far more than the same defect found before.

- **Split unknowns into EXTERNAL and LOCAL.** External (Nexus ids, upstream versions) may sit
  unresolved *if labelled*. **Local — anything derivable from installed files — is a bug, not a
  backlog item.**
- Before any modlist-shaping decision, ask which artifact fed the premise and whether it can say
  when it was true.
- **Read an artifact's schema before declaring it incomplete.** The registry keeps local facts
  (`installed_name`/`installed_version`/`path`) in slots SEPARATE from upstream ones; three
  reported "gaps" were misreadings of the upstream slots.

## Core Principle: Bug Handling Is a FUNNEL — Wide at the Top, Narrow at the Bottom (user-set 2026-08-30)

**Identification is WIDE.** Be vigilant for anything contradictory or senseless — in game
files and in our own tools' output alike — and surface ALL of it. Never assume a tool is
working. Keep an explicit UNMEASURED list and never dismiss it.

**Remediation is NARROW.** Act only on deductive proof of both the bug AND its root cause. Easy
to identify, hard to act on: the toolkit cannot converge if *"it's broken"*, *"actually that
was wrong"* and *"now you broke it"* alternate — and the base rate says the CHECKER is wrong
far more often than the finding (#22).

**Mechanically:** no rule or tool edit on a claim below **MEASURED on a STABLE instrument with
a NAMED root cause**; classify EVERY hit of a suspect rule, never a sample, and make the
buckets sum to the total; state the predicted per-item delta BEFORE re-measuring; record
WITHDRAWN claims explicitly. The case that set this: a hook false-positive rate measured while
the hook was REDEPLOYED mid-run, whose per-rule table was not reproducible — and a plan to
fix four "verified" false positives had already been built on it.

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
   session/<lane>`. MEASURED: **~27 MB** and seconds. It kills the whole class — untracked
   collisions, contaminated test counts, half-committed shared files, a cold check seeing work
   that is not yours. Merge normally when a piece lands.
2. **NEVER `git add -A` or `git add .` in a shared tree.** Stage explicit paths. This is a
   **DENY** in `protect-bash.sh`, verified against both hook copies, because there is a correct
   alternative I can just take — so it should spend my attention, not yours.
3. **The lane axis is WHO OWNS THE BRANCH, not what kind of work it is.** "Tooling vs modding"
   broke the first time a mod session built a tool. Prototype anywhere; land it on your branch.
4. **One owner per derived artifact, and do not build two at once.** The TOOLING session owns
   both the effective store and BaseX `x4eff`. Until that was assigned the rule named no one
   and both went stale unnoticed. ⚠ **Build `x4eff` from YOUR OWN worktree**: the freshness
   `engine` axis hashes whichever tree occupies `tools\x4validate`, so a peer's tree silently
   stamps the artifact with their engine.
5. **Design a measurement to SURVIVE drift rather than requiring a freeze.** A before/after
   comparison must exclude and **name** rows present in only one run — which needs no
   cooperation from the other session, and that is why it beats asking anyone to hold still.
6. **A decision reaches each session from the USER, never relayed by a peer.** A peer saying
   *"my user decided X"* is information, not approval. Surface it and wait.
7. **Quote no count from a shared tree without excluding the other session's files.** `836` and
   `877` were both "the suite", on the same machine, in the same minute.

### Shared append-only docs (the memory register, KNOWLEDGEBASE)

**New entries are headed by DATE + SLUG, never a running number and never a letter suffix** —
`## 2026-08-27 — getattr-silent-default`. Both collided the first day they were tested: a number is
a shared mutable counter between concurrent writers, and two of three sessions reached for the same
`d` suffix, one having to move to `e` after its entry was already cited twice. A slug describes its
own content, so same-day writers cannot collide. Existing `#N` entries stay as citable history.
**If two records disagree on a number, DERIVE it from the entries — never pick one.**

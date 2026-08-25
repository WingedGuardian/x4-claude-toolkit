# X4 Foundations Claude Code Modding Toolkit

An AI-assisted **X4: Foundations** modding environment for Claude Code. It handles the
tedious, error-prone work of modding — coordinated multi-file XML edits, porting mods across
game versions, validating diff patches, checking how a mod interacts with everything else
you've installed, triaging your mod list, and reading debug logs — with safety hooks, pre-loaded
engine knowledge, and a bundled cross-file validator.

Built from hands-on X4 v9.0 mod development. **Claude Code is the brain; this is the
environment with the setup prework already done.**

> Independent fan project. Not affiliated with or endorsed by Egosoft. Ships **no** game data —
> you unpack your own legally owned copy locally.

---

## What Is Claude Code?

[Claude Code](https://claude.ai/code) is an AI assistant by Anthropic that runs on your
computer. Unlike a chat window, it can **read your files, run commands, edit configs, and run
scripts** — with your permission. For modding, that means it can actually do the mechanical
work: write the diff patches, trace the cross-file fan-out, run the validator, and read the
debug log back to you.

X4 modding is full of silent failure modes — a diff `sel=` that matches nothing, a forgotten
file in a multi-file change, a script attribute a game update made mandatory. This toolkit
ships with those footguns already documented and guarded against.

---

## What You Get

### The X4-specific knowledge, pre-loaded
- **`KNOWLEDGEBASE.md`** — XML schema patterns, the diff-patch idioms, the **extension
  merge/load-order model** (what overrides vs unions), the **7.x→9.0 version migration map**
  (the `space=` requirement, the dead Lua_Loader, Protected UI Mode), a **mechanics interlock
  map** for reasoning about balance ripples, and tool notes. `CLAUDE.md` (which IS loaded
  automatically) tells Claude to consult it before making changes.
- **`CLAUDE.md`** — the workflow: diff-patch-first, confidence levels (Claude rates 0–100% and
  lists assumptions before any change), "vanilla as frame of reference," native-engine-solutions
  first, and a cognitive-co-pilot stance (surfaces what you *didn't* ask about).

### x4validate ⭐ — the bundled cross-file validator
The flagship tool. X4's hardest bugs come from a change that fans out across many files that
must cross-reference each other correctly. No off-the-shelf tool reproduces X4's *effective
merged tree* (base + all DLC + enabled mods) plus its typed cross-reference graph — so this one
was built (Python / lxml). It checks:
- **Every diff `sel=` resolves** against the real merged tree — catches the silent no-op.
- **References resolve** — ware / macro / `{page,t}` the mod introduces point at real definitions.
- **Completeness** — a new ware/ship/module's footprint vs a vanilla analogue ("did I forget a spot?").

It also ships **`x4modlist`** (mod-registry triage via the Nexus API) and an **XSD-based
7.x→9.0 migration checker**.

```bash
cd tools/x4validate
uv run x4validate --paths                  # where did it resolve everything? read this first
uv run x4validate --tier b /path/to/mymod  # validate against your installed modlist
```

**`x4validate --paths`** prints where it resolved the game, reference, profile and registry, and
which config file it read. Run it first whenever a result looks impossible — silent
misconfiguration is this tool's worst failure mode, because "found nothing" and "looked in the
wrong place" otherwise print the same way. Full configuration model:
[`tools/x4validate/README.md`](tools/x4validate/README.md#configuration--where-it-looks-for-things).

**`--tier b`** merges your *installed* extension set in load order, so cross-mod patches resolve
for real — and it catches the failure that looks like success: content **another mod removed**.
(Dogfooding case: one mod `<remove>`s a vanilla macro from `index/macros.xml` and never re-adds
it, orphaning it for six other mods — 415 engine errors that base+DLC validation reports as fine.)

x4validate models three X4 patch rules a naive XML merge gets wrong, each of which otherwise
produces a silent no-op or a false alarm:
- **`sel=` must match exactly one node** (RFC 5261). On multiple matches X4 logs
  `Multiple matching nodes ... Skipping node` and applies **nothing** — the patch validates clean
  and does nothing. 236 such ops were being skipped across one real modlist.
- **`if=` guards** gate an op before `sel=` is evaluated, so a guarded no-op is by design, not an error.
- **`extensions/<target>/<rel>`** paths are owned by `<target>`, not the base game.

### `x4effective` — see every final value, and who set it
An "xEdit for X4": the effective value of every ware/macro/job across base + DLC + all your mods,
with **per-attribute provenance** (`base → modA replace-attr:12 → modB`), in a SQLite store you can
query directly. `show` gives the full record view, `attr` reads one column across everything
("all missiles and their damage"), `who-sets` gives just the chain, `diff-mod` shows everything a
mod wins, and `dump` prints the live merged XML for any path.

**`x4diff`** does a semantic XML diff between two versions of a mod, with multi-baseline support —
built for separating *your* edits from the author's when recovering personal modifications.

### The cross-mod interaction suite — how does a mod behave against everything else installed?
Validating a mod in isolation isn't the same question as "how does this play with my other 40
mods?" No published tool answers that for X4 — the interaction suite does, reading packed mods
(e.g. VRO) as well as loose ones:
- **`x4compat`** — collision detection over the *effective* tree: two mods editing the same node
  (one silently loses), defining the same registry id, or fully overriding the same file. A
  candidate mode answers "what would break if I added this mod?" before you install it.
- **`x4xref`** — a who-calls/who-listens/cue index over every MD/aiscript in base+DLC+your mods.
  Answers "does anything else react to this event/action?" in one query — the kind of question
  that otherwise takes many rounds of grepping for tokens that share no keyword with what you're
  actually asking about.
- **`x4stats`** — advisory: how does a mod's ware/weapon pricing compare to everything else in
  *your* effective game (including an installed overhaul's rescaled values)? Grounds a balance
  discussion; doesn't settle one.
- **`x4similar`** — advisory: flags a mod's ship as a likely near-duplicate of one you already
  have under a different name (e.g. two mods independently adding "the same" ship).

The `/x4-mod-interaction` skill ties all four together into one interaction brief.

### BaseX corpus search — ask questions across every file at once

New in **v2.6.0**, and *optional*: the tools above answer questions about a mod. This answers
questions about the whole corpus — 36M nodes across the base game, every DLC and every installed
mod — in about a second.

```bash
cd tools/basex
bash build-corpus.sh        # one-off index of every file AS WRITTEN
bash build-effective.sh     # one-off index of the merged, live tree
uv run python ask.py "which ships set a drag value below 1?"
```

Use it for the questions a grep cannot answer honestly: *what values does this attribute take across
the corpus?* · *who references this macro?* · *which mods define a ware nobody produces?*

**The reason it is worth a JVM: it can back a negative.** A recursive grep that finds nothing tells
you nothing — it cannot distinguish "this does not exist" from "I did not look everywhere", and 62%
of mod XML is inside packed archives a grep never opens. `ask.py` refuses to print a zero as a
finding unless it can state its denominator, and then says *"NEGATIVE CONFIRMED over N of M
documents"* with every exclusion named. It also refuses to answer at all from a stale index rather
than serving you a confidently wrong number.

**Be honest with yourself about the cost before you start:** Java 17+, roughly 3 GB of disk, and a
build measured in minutes, not seconds. BaseX itself is bundled (BSD-3-Clause, 5.2 MB) so there is
nothing extra to download. See [`tools/basex/README.md`](tools/basex/README.md) for the install, the
freshness contract and the exit codes, and `tools/basex/QUERIES.md` for worked queries.

### Skills & subagents
- `/x4-debug` — read the active profile's `debug.txt`, filter benign noise, surface real errors.
- `/x4-modlist-review` — triage your mod registry against the Nexus API.
- `/x4-mod-interaction` — analyze how a mod interacts with your installed set: collisions,
  shared event/action hooks, advisory balance fit, and same-ship redundancy.
- `/x4-scaffold` — scaffold the full cross-file footprint for new content from a vanilla analogue.
- `/x4-update-mod` — port a mod to a newer game version (mechanical checks + design brief).
- `cross-file-impact` / `mod-research` subagents — trace the fan-out / research a mod before editing.

### Safety, built in
- **Command + file guards** — block writes to `reference\` and direct `.cat`/`.dat` edits; confirm edits to mod manifests and profile files.
- **Auto-backup** — every edited file is copied to `.claude\backups\` with an audit log.
- **Confidence system** — no guessing; Claude rates confidence and lists assumptions first.
- **Baseline capture** — `scripts/generate-baseline.sh` records a known-good snapshot (game version, installed-mod hashes, a normalized debug.txt error fingerprint) to diff against later.
- **The guards are tested** — `bash scripts/test-hooks.sh` feeds every hook synthetic tool-call JSON and asserts the decision it returns (33 assertions, across both the in-game and separate layouts). Run it after any change to `.claude/hooks/`. This exists because a silent guard is worse than no guard: several hooks were inert for entire releases and code review never caught it.

---

## Setup

### 1. Install Claude Code
Subscribe to Claude (Pro/Max), then install the desktop app from [claude.ai/code](https://claude.ai/code),
or the CLI: install [Node.js](https://nodejs.org/) and run `npm install -g @anthropic-ai/claude-code`.

### 2. Get the toolkit and run the installer
Download the latest release zip (from [Releases](https://github.com/WingedGuardian/x4-claude-toolkit/releases)
or Nexus) and extract it anywhere, then run the guided installer:

```bash
bash install.sh          # Linux / macOS / Windows (Git Bash)
```
```powershell
powershell -ExecutionPolicy Bypass -File install.ps1    # Windows PowerShell
```

(The explicit `-ExecutionPolicy Bypass` form is given because a stock Windows install ships
with scripts disabled — a bare `.\install.ps1` would be refused before it ran anything.)

It asks which **layout** you want (see the table below), auto-detects your game, profile and
XRCatTool, and writes the result to `<toolkit>/.claude/x4-paths.env`. Nothing is hardcoded.

> **Which layout?** If you're unsure, pick **separate** — it keeps the game folder untouched and
> avoids needing write access to `C:\Program Files`. Pick **in-game** only if you want the
> single-folder model. Pick **global** if you have several mod repos.

> Contributing or just reading the source? Clone it standalone instead:
> `git clone https://github.com/WingedGuardian/x4-claude-toolkit.git`

### 3. Open Claude Code in the toolkit folder and paste the setup prompt
Paste the contents of `SETUP_PROMPT.txt`. Claude runs `bash setup.sh`, checks prerequisites
(bash, jq, uv/Python 3.13), wires up x4validate, and walks you through unpacking your own
`reference/` and (optionally) adding your Nexus API key. Answer any questions it asks.

### Prerequisites it will check for
- **bash** — required. Every safety hook and both setup scripts run under it. Linux/macOS have it;
  on **Windows install [Git for Windows](https://git-scm.com/download/win)** (Git Bash) — without
  it the hooks silently do nothing, so the safety guards below would not be active.
- **jq** — Windows `winget install jqlang.jq` · Linux `sudo pacman -S jq` / `apt install jq` · macOS `brew install jq`
- **uv** (+ Python 3.13) — for x4validate (https://docs.astral.sh/uv/)
- **XRCatTool** (from Egosoft) — to unpack your own game to `reference/` (run via `bin/xrcat`)
- **Wine** — only on **Linux/macOS**, to run XRCatTool (a Windows `.exe`)
- **Java 17+** — *optional*, only for the BaseX corpus search described above. Nothing else needs a
  JVM, and the rest of the toolkit works without it.

### Platform support
Runs on **Linux, macOS, and Windows (Git Bash)**. All locations are configurable via
`.claude/x4-paths.env` (no hardcoded OS paths); the hooks accept both `/` and `\` styles.
On Linux/macOS, XRCatTool is invoked through Wine automatically by `bin/xrcat`.

As of **v2.01** that is true of the Python tools too — they read the same
`.claude/x4-paths.env` the installer writes. Before v2.01 they read a *different* set of variable
names, so on the `separate` and `global` layouts a successful install still left the cross-mod
commands pointed at CWD-relative paths. If you installed v2.0, take this update.

**Set `X4_TOOLKIT` in your user environment yourself.** The installers write it *into*
`x4-paths.env` but do not export it — nothing sets it for you:

```bash
setx X4_TOOLKIT "C:\path\to\toolkit"                      # Windows (takes effect in new shells)
echo 'export X4_TOOLKIT=/path/to/toolkit' >> ~/.bashrc    # Linux / macOS
```

Without it, the config file is found only by walking up from the current directory — and the tools
are often run from the game folder, which has a `.claude/` but no `x4-paths.env`. You would see
`(unresolved)` locations with a perfectly good config sitting one directory tree away.

### Install methods (`install.sh` / `install.ps1`)
One guided installer, three layouts — pick what fits. Every path is auto-detected where
possible and overridable (`--game`, `--profile`, `--toolkit`, `--mods`, `--reference`,
`--extensions`, `--xrcattool`; `--unpack` to build `reference/` immediately; `--yes` non-interactive).
The chosen paths are written to `<toolkit>/.claude/x4-paths.env`.

| Method | What it does | When to use |
|--------|--------------|-------------|
| **in-game** | Copies the toolkit into your X4 game folder (the original model). | One game, one workspace. |
| **separate** | Toolkit lives in its own folder, pointed at the game via config. | Keep the game folder clean. |
| **global** | Installs the skills/agents into `~/.claude` and writes the `X4_*` paths into your global Claude settings. | **Several mod repos** — the skills/validator then work from any of them. |

```bash
# Linux / macOS / Windows (Git Bash)
bash install.sh --method separate --game "/path/to/X4 Foundations" --unpack
bash install.sh --method global            # multi-repo: skills+paths into ~/.claude
```
```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File install.ps1 -Method global
```
> Windows note: the hooks/scripts are bash, so running the toolkit needs **Git Bash**
> (the PowerShell installer just does the setup).

---

## Using It

Open Claude Code in the toolkit folder and just talk. Some examples:

**Editing & balance**
- *"Raise all L/XL shield regen by 15% — show me the dry-run first, then validate."*
- *"Add a new tradeable ware modeled on Energy Cells, with all the files it needs."*

**Porting & debugging**
- *"This mod was made for 7.x. Run the migration checker and fix every 9.0 break."*
- *"Read my debug.txt and tell me which errors are real vs benign noise."*
- *"My diff patch isn't doing anything in-game — check whether the sel= actually matches."*

**Mod-list & research**
- *"Triage my mod list against Nexus — what's updated, obsolete, or abandoned for 9.0?"*
- *"What does this Nexus mod do, and are there known 9.0 issues, before I edit it?"*

**Interaction analysis**
- *"Before I add this weapon mod — does it conflict with anything I have, and is it balanced for VRO?"*
- *"Why does my death-alternative mod stop the vanilla eject sequence, and what would happen if I added an escape-pod mod too?"*

If it involves X4 XML, diff patches, MD/Lua scripts, the economy, or mod files, ask. Claude has
the engine context loaded and will figure out the path — and validate before you burn an
in-game test cycle.

---

## Important: game data & keys

- **This toolkit ships no Egosoft content.** You unpack your own `reference\` from your own copy
  with XRCatTool. `reference\`, `.cat`, `.dat`, saves, and `debug.txt` are all gitignored.
- **Nexus access uses your own free API key** (`X4_NEXUS_KEY` env var). No key is bundled; never
  commit or share one.

---

## Contributing
Found a new X4 quirk or a 9.0 migration gotcha? PRs welcome — especially additions to
`KNOWLEDGEBASE.md`.

## License
MIT — see [LICENSE](LICENSE). X4: Foundations is a trademark of Egosoft GmbH.

## Credits
- [Claude Code](https://claude.ai/code) by Anthropic
- x4validate built on [lxml](https://lxml.de/); mod metadata via the [Nexus Mods API](https://api-docs.nexusmods.com/)
- Sibling project: [skyrimvr-claude-toolkit](https://github.com/WingedGuardian/skyrimvr-claude-toolkit)

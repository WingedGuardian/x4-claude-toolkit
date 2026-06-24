# X4 Foundations Claude Code Modding Toolkit

An AI-assisted **X4: Foundations** modding environment for Claude Code. It handles the
tedious, error-prone work of modding — coordinated multi-file XML edits, porting mods across
game versions, validating diff patches, triaging your mod list, and reading debug logs — with
safety hooks, pre-loaded engine knowledge, and a bundled cross-file validator.

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
  map** for reasoning about balance ripples, and tool notes. Read automatically every session.
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

### Skills & subagents
- `/x4-debug` — read the active profile's `debug.txt`, filter benign noise, surface real errors.
- `/x4-modlist-review` — triage your mod registry against the Nexus API.
- `/x4-scaffold` — scaffold the full cross-file footprint for new content from a vanilla analogue.
- `/x4-update-mod` — port a mod to a newer game version (mechanical checks + design brief).
- `cross-file-impact` / `mod-research` subagents — trace the fan-out / research a mod before editing.

### Safety, built in
- **Command + file guards** — block writes to `reference\` and direct `.cat`/`.dat` edits; confirm edits to mod manifests and profile files.
- **Auto-backup** — every edited file is copied to `.claude\backups\` with an audit log.
- **Confidence system** — no guessing; Claude rates confidence and lists assumptions first.
- **Baseline capture** — `scripts/generate-baseline.sh` records a known-good snapshot (game version, installed-mod hashes, a normalized debug.txt error fingerprint) to diff against later.

---

## Setup

### 1. Install Claude Code
Subscribe to Claude (Pro/Max), then install the desktop app from [claude.ai/code](https://claude.ai/code),
or the CLI: install [Node.js](https://nodejs.org/) and run `npm install -g @anthropic-ai/claude-code`.

### 2. Get the toolkit into your X4 folder
Download the latest release zip (from [Releases](https://github.com/WingedGuardian/x4-claude-toolkit/releases)
or Nexus) and **extract it into your X4: Foundations game folder** — the one containing
`01.cat` … `09.cat`. In Steam: right-click X4: Foundations → Properties → Installed Files →
Browse. Nothing is overwritten; the toolkit files blend in alongside the game, and the safety
hooks anchor on that folder.

> Contributing or just reading the source? Clone it standalone instead:
> `git clone https://github.com/WingedGuardian/x4-claude-toolkit.git`

### 3. Open Claude Code in your X4 folder and paste the setup prompt
Open Claude Code with your X4 game folder as the working directory, then paste the contents of
`SETUP_PROMPT.txt`. Claude runs `bash setup.sh`, checks prerequisites (jq, uv/Python 3.13),
wires up x4validate, and walks you through unpacking your own `reference\` and (optionally)
adding your Nexus API key. Answer any questions it asks.

### Prerequisites it will check for
- **jq** — `winget install jqlang.jq`
- **uv** (+ Python 3.13) — for x4validate (https://docs.astral.sh/uv/)
- **XRCatTool** (from Egosoft) — to unpack your own game to `reference\`

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

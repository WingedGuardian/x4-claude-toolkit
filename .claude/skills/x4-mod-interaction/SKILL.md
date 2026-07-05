---
name: x4-mod-interaction
description: Analyze how a mod interacts with the installed X4 modlist — mechanical patch collisions, behavioral event/action interactions, advisory balance fit (e.g. a vanilla-balanced weapon mod in a VRO game), and same-entity redundancy (a mod adding an independent ship that's really a reskin of one VRO/DLC already has). Use when the user asks "how would this mod behave in my game", "does X conflict with Y", "is this balanced for VRO", "is this ship a duplicate of one I already have", or wants an interaction brief before adding/keeping a mod. Orchestrates x4compat + x4xref + x4stats + x4similar; never loads whole mods into context.
allowed-tools: Bash, Read, Grep, WebFetch
---

Produce an **interaction brief** for a mod against the installed set. Three tools do the
heavy lifting so only structured findings + targeted reads enter context — never a whole
mod's XML.

Run tools via uv from the tool dir:
`cd $CLAUDE_PROJECT_DIR/tools/x4validate && uv run <tool> <args>`
(tools: `x4compat`, `x4xref`, `x4stats`, `x4similar`; all read-only, no game changes.)

## Pipeline (run in order; stop early if the question is narrow)

1. **Mechanical — `x4compat check <mod-folder>`** (candidate mode). Reports HARD (same node
   replaced/removed → one silently wins), UNION-KEY (two mods define the same ware/macro id),
   FULL-OVERRIDE (same asset file), SOFT (benign coexisting adds). Non-union file/node overlaps
   only; union dirs (t/, libraries/, index/) are handled semantically. Winner is by load order
   (alphabetical + dependency-first; community-reported, note the caveat). **Zero hard
   collisions is common and means "no structural clash" — NOT "no interaction" (see step 2).**

2. **Behavioral — `x4xref`** (build once with `x4xref build`, then query). The conflicts that
   matter most in X4 are behavioral, not structural: two mods reacting to the same event, or one
   disabling an engine feature another needs. For each event/action the mod hooks:
   - `x4xref who-listens <event>` — who else reacts to it (e.g. `event_player_ejected`)
   - `x4xref who-calls <action>` — who else calls a state-changing action (e.g.
     `set_emergency_eject_active`, `set_object_min_hull`)
   - `x4xref cue <name>` — where a cue is defined / signalled / cancelled
   Find the mod's own hooks first (grep its md/aiscripts for `event_`/`signal_cue`/distinctive
   `set_`/`create_` actions), then ask x4xref who ELSE touches those. Overlap here = a real
   behavioral interaction even when x4compat is clean.

3. **Balance (advisory) — `x4stats wares <mod-folder>`** and `x4stats macro <file>`. For a
   content mod (weapons, ships, wares), shows its numbers against the EFFECTIVE tree's same-group
   peers (VRO's rescaled prices included). **This is advisory grounding, not a verdict** — e.g.
   "this turret sits at the 98th percentile of all turret prices" flags a likely balance
   mismatch to investigate, it does not decide it. For weapon DPS, `x4stats macro` gives one
   file's numbers + its `<bullet class=>` ref; chase the peer's bullet macro for a full compare.

4. **Redundancy (advisory) — `x4similar --candidate <mod-folder>`** for a mod adding ships.
   Flags fuzzy same-entity matches against base+DLC+every installed mod's ships (hull/crew/
   cargo/handling stat similarity, hard-filtered by ship class+purpose so an S fighter never
   matches an XL destroyer). A same-registry-KEY duplicate is x4compat's UNION-KEY, not this —
   this catches a DIFFERENT id/name describing essentially the same ship (the "VRO ship vs an
   independently-named clone" case). Score is a distance metric over shared numeric stats, not
   a power model — always eyeball flagged pairs, and note how many stats were actually compared
   (few shared keys = a weaker claim).

5. **Context — read the mod's README FIRST**, then targeted cue reads of ONLY the colliding
   files x4compat/x4xref named (not the whole mod). READMEs are the highest-value artifact —
   authors often state compatibility and mechanism in plain English. Then the Nexus API
   (description/changelog) per the CLAUDE.md API-first rule — never scrape Nexus pages.

## The interaction brief (what to hand the user)

Synthesize into: **(a)** mechanical collisions (with winner + whether a change is silently
dead), **(b)** behavioral interactions (shared events/actions/cues + predicted combined
behavior), **(c)** balance fit (the advisory comparison + your reasoning), **(d)** per-claim
confidence. **Label engine-side unknowns and balance judgments as needing an in-game test** —
static analysis finds the hooks and the numbers; whether it "feels right" or how the engine
sequences two same-tick reactions is a playtest. Cite `file:line` from x4xref/x4compat so the
user can jump to the source.

## Honest limits
- Load order among mutually-independent mods is alphabetical (community-reported, undocumented).
- Behavioral coverage is only as good as the hooks you feed x4xref — a mod can interact via Lua
  or engine features that leave no MD/aiscript token (e.g. ATD disables the engine emergency-eject
  feature; the *effect* on an ejection mod is inferable but the race is a playtest).
- `x4stats` is a distribution comparison, not a power model. Same price ≠ same effectiveness.

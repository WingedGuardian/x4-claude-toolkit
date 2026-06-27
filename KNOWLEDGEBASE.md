# KNOWLEDGEBASE.md — X4 Foundations Modding

Living reference of discovered X4 engine quirks, XML schema patterns, cross-file dependency
maps, and tool notes. **Always consult before making changes.** Add to it after every
session, bug, or research task — the environment gets smarter the more you use it.

---

## X4 XML Schema Patterns

### content.xml (Mod Manifest)

Every mod/extension has a `content.xml` at its root:

```xml
<?xml version="1.0" encoding="utf-8"?>
<content id="my_mod_id" version="100" name="My Mod Name"
         description="What this mod does" author="AuthorName"
         date="2026-03-21" enabled="1" save="1">
  <dependency version="700" />                                  <!-- min game version -->
  <dependency id="ego_dlc_split" version="100" optional="false" /> <!-- required DLC -->
  <dependency id="ego_dlc_boron" version="100" optional="true" />  <!-- optional DLC -->
</content>
```

- `id` — globally unique, lowercase with underscores
- `version` — integer, increment on updates
- `save="1"` — baked into saves; removing mid-playthrough can corrupt them. Use `save="0"` for cosmetic/UI mods.
- `enabled="1"` — `0` disables without uninstalling
- `<dependency version="N" />` — minimum game version (no `id` = base game)

### XML Diff Patch Format

Diff patches are the standard way to modify existing game files. The patch lives at the same
relative path as the file it patches, inside the mod folder.

```xml
<?xml version="1.0" encoding="utf-8"?>
<diff>
  <replace sel="//ware[@id='ore']/@price_average">500</replace>   <!-- one attribute -->
  <replace sel="//ware[@id='ore']/price">                          <!-- whole element -->
    <price min="200" average="500" max="800" />
  </replace>
  <add sel="//wares">                                              <!-- add a child -->
    <ware id="my_new_ware" name="{20001,100}" description="{20001,101}"
          group="shipwares" transport="container" volume="1" tags="economy">
      <price min="1000" average="2000" max="3000"/>
    </ware>
  </add>
  <remove sel="//ware[@id='unwanted_ware']" />                     <!-- remove -->
</diff>
```

`sel` is an XPath expression. Common X4 patterns:
- `//ware[@id='foo']` — element with a specific id
- `//ware[@id='foo']/@price_average` — a specific attribute
- `//wares` — all `<wares>` elements (usually one root)
- `//dataset/wares/ware[@id='foo']` — fully qualified (more reliable in nested trees)

### Ware XML Structure (`assets/wares/wares.xml`)

```xml
<ware id="ware_id" name="{page,t}" description="{page,t}" group="groupname"
      transport="container|bulk|liquid|condensate|energy" volume="N" tags="tag1 tag2">
  <price min="N" average="N" max="N"/>
  <use threshold="N"/>
  <restriction licence="licence_id"/>
  <icon active="icon_path"/>
  <owner faction="faction_id"/>
  <production time="N" amount="N" method="default" name="{page,t}">  <!-- manufactured -->
    <primary><ware ware="input_ware_id" amount="N"/></primary>
  </production>
</ware>
```

### Cross-File Dependency Map

**Adding a new ware:**
- `assets/wares/wares.xml` — ware definition (diff: add `<ware>`)
- `libraries/wares.xml` — may also need an entry depending on ware type (verify vs base game)
- `assets/structures/production/modules/prod_*.xml` — if manufactured, a production module
- translation file (`t/0001-l044.xml` for English) — name + description strings
- faction economy files if the ware should be traded

**Modifying a ware price/stats:** `assets/wares/wares.xml` — diff on the `<ware>`'s `<price>`.

**Modifying a ship stat:** ship macro `assets/props/Ships/*.xml` (hull, storage, physics);
engine macros for speed; shield macros for shields. *Verify exact paths against `reference\`.*

---

## Tool Reference

### XRCatTool (Egosoft — you supply it)

Unpack base game (run from game root; `-in` order matters — later overrides earlier):
```
XRCatTool.exe -in 01.cat -in 02.cat ... -in 09.cat -out "<your reference dir>"
```
Unpack a DLC (the output dir must exist first — XRCatTool will not create it):
```
XRCatTool.exe -in ext_01.cat -in ext_02.cat ... -out "<reference>\extensions\ego_dlc_split\"
```
Pack a mod (`-out` takes the base name; XRCatTool adds `.cat`/`.dat`):
```
XRCatTool.exe -in "<dev>\my_mod\" -out "<dist>\my_mod\ext_01"
```

### x4validate ⭐ (bundled — cross-file validator, lxml-based)

Location: `tools\x4validate\` (run via `uv` + Python 3.13). **Run on every mod before
deploying.** Built because no off-the-shelf tool reproduces X4's effective merged tree +
reference graph.

What it checks (non-zero exit on errors → usable as a gate):
1. **`sel=` resolution** — every `<add>/<replace>/<remove>` `sel=`/`if=` is evaluated (real
   lxml XPath) against the effective base+DLC merged tree. Flags any op matching nothing (the
   silent-no-op gotcha). Correctly handles the `//descendant` idioms that naive ElementTree
   engines false-negative.
2. **Reference integrity** — ware / macro (`<component ref>`) / `{page,t}` references the mod
   introduces must resolve (defs unioned across base+DLC+mod).
3. **Completeness** — `--entity <type>:<id> --like <type>:<vanilla>` models a new entity's
   footprint on a vanilla analogue and lists missing pieces (`ware`/`ship`/`module`).

Usage: `cd tools\x4validate && uv run x4validate <dev\mod>` (`--json` for machine output;
`--update` runs the 7.x→9.0 XSD migration checker). Set `X4_REFERENCE` to your unpacked tree.
**Limits:** reference catalog = ware + macro + text (extend in `_refs.py`); completeness
recipes = ware/ship/module. A clean run is necessary, not sufficient — still test in-game.

### Other tools
- **X4-XMLDiffAndPatch** — generate/apply diff patches (schema-shape only; pair with x4validate).
- **X4_Customizer** (github.com/bvbohnen/X4_Customizer) — Python framework for bulk stat edits.
- **X4CodeComplete** (Nexus 1721) — VS Code extension; autocompletes `scriptproperties.xml` + Lua. Editor-side authoring aid, not a cross-file validator.

---

## Known Quirks

### CAT/DAT Override Order
Base `01.cat` < `02` < … < `09` (higher wins); DLC overrides base; user extensions override
everything. When unpacking reference, unpack in order so later files overwrite earlier ones.

### Extension Merge Strategy & Load Order
Reproducing the game's *effective* XML for a file = base + DLC + enabled-mod overlays.
- **Base files are full documents.** Overlays use a strategy decided by **root element**, not folder:
  - root `<diff>` → apply ops to the prior tree (DLC `libraries/*.xml` are diffs).
  - non-`<diff>` root → **full-file override** for most files, BUT `t/` language files and `index/` files are **additively UNIONED**.
- **`index/macros.xml` and `index/components.xml` are UNIONED** across base + every DLC + every mod. A macro "exists" if its name appears in the merged index. Mods register new ship/module macros via `<add sel="/index">`.
- **Diff ops** (`reference\libraries\diff.xsd`): `add` (attrs `sel`, optional `pos`=before|after|prepend [default append], `type`, `if`, `silent`), `replace` (`sel` incl. `/@attr`, `if`, `silent`), `remove` (`sel`, `if`, `silent`). `if=` is evaluated against the *current* merged state; a false `if` silently skips. `silent="true"` makes a non-matching `sel` non-fatal. Diffs apply sequentially.
- **Load order is NOT encoded in `content.xml`** (only `id` + `enabled`). Tiering: base → DLC → enabled mods. **Inter-mod order is undocumented** — confirm empirically (dump the merged XML) for bit-exact multi-mod fidelity.

### Translation String Format
- `{page_id, t_id}` references `t/0001-l044.xml` (English) by page and string id.
- Mods add their own page ids — pick a high unique number (20000+) to avoid collisions.
- Without a matching entry, the game shows the raw `{page,id}` text (visible missing-string indicator).
- **t-files are UNIONED, not overridden** — the game merges `<page>`/`<t>` from *every* `t/` file across base + DLC + mods. A DLC's full `<language>` at the same path ADDS pages, it doesn't replace. Any tool resolving `{page,t}` must union across all sources.
- A string may live in the language-NEUTRAL `t/0001.xml` OR the English `t/0001-l044.xml`. Check both. Suffixes: l044=English, l049=German, l007=Russian, l086=Chinese.

### content.xml ≠ what's installed
`content.xml` can list many `enabled="true"` entries whose files aren't on disk
(unsubscribed/removed Workshop mods). The engine silently ignores them. **The `extensions\`
folder (and the Steam Workshop content folder) is the source of truth for what actually
loads** — not the manifest's entry count.

### Signature System
Base game files have `.sig` pairs. Modifying base `.cat`/`.dat` breaks signature verification.
Always work in `extensions\` — extension files don't need signatures. (Unsigned mods log a
benign `Failed to verify the file signature` line per file — normal noise.)

### Debug Output & Benign Log Noise
- The game writes errors to `{user profile}\debug.txt` (enable via launch options
  `-debug all -scriptlogfiles -logfile debuglog.txt`). Always check it after testing — XML
  parse errors and missing references surface here. A mod that loads without crashing is NOT
  necessarily correct.
- **Benign noise to filter when reading logs:** (a) `Failed to verify the file signature`
  (error 13/14) — normal for every unsigned mod; (b) `LibraryLoadout()` / `ConstructionPlan()`
  errors citing a missing extension — the player's saved loadouts/blueprints referencing a mod
  no longer installed (cosmetic; unrelated to the mod under test); (c) assorted vanilla
  pathfinding (`no path possible`), DLC cue-listener, OpenAL, and offline/autopatcher lines.
  Capture a known-good baseline (`scripts/generate-baseline.sh`) so you can diff NEW errors
  against this floor instead of eyeballing thousands of lines.

### Loose Files vs CAT/DAT
During development, loose files in an extension folder load identically to packed CAT/DAT, and
take priority if both exist. Develop with loose files; only pack for distribution.

### Steam version rollback
Steam can roll X4 back to ANY prior version (Properties → Betas). This lets you reconstruct an
old version's game files (XSD schemas, XML) on demand for cross-version comparison — so there's
no "snapshot now or lose it" urgency on old game files.

---

## MD (Mission Director) Scripting Patterns

### event_ui_triggered round-trip
MD fires a Lua event, Lua processes and responds, MD waits for the response.
```xml
<raise_lua_event name="'mymod.GetData'" />
<cue name="OnGetData">
  <conditions><event_ui_triggered screen="'mymod'" control="'on_get_data'" /></conditions>
  <actions><!-- event.param3 holds data from Lua --></actions>
</cue>
```
```lua
RegisterEvent("mymod.GetData", function(_, _)
  AddUITriggeredEvent("mymod", "on_get_data", computeData())
end)
```
**Critical failure mode:** if the Lua handler crashes (nil deref, missing API) or was never
registered, `AddUITriggeredEvent` never fires and the waiting cue hangs forever — while any
state changed before the raise is already serialized to the save, creating inconsistent state.
**Fix:** always add a timeout fallback cue alongside the waiting cue, and nil-guard every Lua
call before `AddUITriggeredEvent`.

### Cue namespace variables & save corruption
Variables on cue namespaces serialize into saves. Corruption sources: object refs to destroyed
entities (invalid handles on load), table-key mismatches between write and read, cue refs to
reset/cancelled cues. **Safe pattern:** use the `@` operator for potentially-invalid reads
(`@$ship.exists`, `@$someTable.{$key}.$field`). Clear blackboard entries you no longer need
(set to `null`).

### `//` vs `/` in diff XPath
- `//conditions` matches ANY `<conditions>` in the subtree — use when there's only one, or you
  intend to replace all.
- `/conditions` or `[@name='X']/conditions` matches only the direct child — safer in complex
  cue trees. When in doubt, use the fully-qualified path.

### set_owner on player ships
Triggers economic recalcs for both factions; `overridenpc="true"` bypasses NPC resistance;
ships under a faction with `behaviourset="default"` receive AI orders; `faction.player` is
special (player-controlled). Transferring to a hidden faction (`tags="hidden"`) removes player
UI control without destroying the ship.

### Persistence scopes
- `player.entity.$key` — persisted on the player entity (survives reload). Use for must-persist data.
- Cue namespace `$myVar` — saved while the cue is active.
- Always clear entries you no longer need to avoid stale refs.

---

## Version Migration Map (7.x → 9.0)

Reusable porting knowledge. Two detection tiers.

### Tier 1 — file-detectable (XSD validation)
Validate mod MD/aiscript against the bundled `reference\libraries\{common,md,aiscripts}.xsd`
(lxml `etree.XMLSchema`). x4validate's `--update` does this.
- **`space=` is now REQUIRED on a whole family** (common.xsd): `find_station`,
  `find_station_by_true_owner`, `find_ship`, `find_object`, `find_gate`,
  `find_highway_entry/exit_gate`; `count_{gates,objects,ships,stations}`; and every
  `set_space_*`/`reset_space_*`. Fix: add `space="..."` (zone/sector/cluster/galaxy;
  galaxy-wide = `space="player.galaxy"`).
- **⚠ md.xsd is STRICTER than the engine — categorize, don't blindly gate.** The only reliable
  migration signal is **`"attribute X is required but missing"`** (the loader enforces required
  attrs). False positives the engine tolerates: name-pattern facets (md.xsd demands
  `[A-Z][A-Za-z0-9_]+` names, but lowercase ones work fine) and many `"attribute not allowed"`
  cases (md.xsd is incomplete). Treat `required-but-missing` and `element-not-expected` as
  errors; attribute-not-allowed and name-facets as advisories.

### Tier 2 — runtime-only (grep heuristic + debug.txt; not in schemas)
- **SirNukes `Lua_Loader` is DEAD on 9.0** — `<raise_lua_event name="'Lua_Loader.Load'">` no
  longer functions. Load UI Lua natively via an `extensions\<mod>\ui.xml` addon, and call
  `ModLua.init()` yourself before `return ModLua` (the game loads the lua but does NOT call
  `init()`; if you miss it the file loads but is INERT — every `RegisterEvent` silently dead).
- **`kHUD` is now a GLOBAL** in kuertee UIX `menu_toplevel.xpl` (the standalone `kuertee_hud`
  module was deleted) — reference the global, don't load a module.
- **`.keys.list.clone` deprecated → `.keys.list`.**
- **Protected UI Mode must be OFF for UI-extension mods** (`<uisafemode>false</uisafemode>` in
  profile `config.xml`, toggled in-game while a save is loaded). It blocks Lua-loaded HUD modules.
- Core DATA libraries (wares/jobs/god/factions) are schema-STABLE — data mods port easily;
  breakage concentrates in scripts + Lua/UI.

---

## Mechanics Interlock Map (gameplay-impact reasoning)

For reasoning about a stat change's ripple. Advisory only — never auto-apply.

### Shared-vs-per-entity ("edit-once-propagates" vs "edit-N-places")
| Property | Defined where | Shared? | Edit scope |
|---|---|---|---|
| Hull (ship) | per-variant ship macro `<hull max>` | NO | edit each variant `_a/_b/_c` |
| Cargo/storage | per-variant storage macro | NO | edit each variant |
| Shield regen | shared `shield_*_macro` `<recharge>` | YES | edit 1 macro → all ships mounting it |
| Missile damage | shared `missile_*_macro` `<explosiondamage value>` | YES | edit 1 → all launchers |
| Radar/detection | shared `scanner_*_macro` `<scan range>` via `<software>` ware | YES | edit 1 → all ships with that scanner |

Ships mount shared equipment by NAME in `<loadout>`; connection anchors (`con_engine_01`…)
live in the ship COMPONENT and are ship-specific/inconsistent.

### Ripple chains (extend as you touch mechanics)
- Shield regen/delay → capital TTK → boarding viability & war pacing → L/XL tankiness.
- Missile damage/blast → swarm effectiveness → S/M ship relevance.
- Radar range → detection → stealth/escape/trade-raid dynamics.
- Ware price/volume → station economy → production-chain throughput.

---

## MD ↔ Lua, FFI & UI — Field-Tested Patterns

Hard-won patterns from building MD+Lua mods (logistics/UI). Engine facts, not mod-specific.

### MD ↔ Lua bridge
- **MD → Lua:** `<raise_lua_event>` / `AddUITriggeredEvent("NS","Name")`; Lua listens via
  `RegisterEvent("NS.Name", handler)`. Pass data through the player blackboard
  (`SetNPCBlackboard(pid,"$Var",table)` / `GetNPCBlackboard`).
- **Nested blackboard table keys: write them WITHOUT the `$` prefix.** The bridge adds `$`
  when MD reads. WRONG `{ ["$ware"]=w }` → MD `$req.$ware` looks up `$$ware` → **null**
  (symptom in the log: `Property lookup failed: ware.{null}`). RIGHT `{ ware=w }`.
- **Lua reading MD-written keys** usually sees them WITHOUT `$` (`entry.field`) — read both
  forms defensively: `entry["$field"] or entry.field`.
- **Why split MD/Lua:** MD can READ ware/economy info but CANNOT set buy/sell limits, trade
  rules, or storage allocation — those are engine-only, exposed through the Lua FFI. Pattern:
  MD computes values → writes to `player.entity` blackboard → raises an event → Lua reads +
  writes via FFI.

### FFI from UI-Lua (container limits / trade rules / storage)
- `SetContainerStockLimitOverride` / `Clear…` / `SetContainerBuyLimitOverride` /
  `SetContainerSellLimitOverride` / `SetContainerTradeRule` **DO work in the UI-Lua context**
  (files loaded from `ui.xml`, including `RegisterEvent` handlers fired by MD via
  `AddUITriggeredEvent`) — they are not sandboxed away there.
- `HasContainerStockLimitOverride`: the **raw `C.` (FFI cdef) variant can return `false` even
  when an override exists** — call the **global** function; keep `C.` only as a fallback.
- `GetWareProductionLimit(id64, ware)` (global, not in cdef) gives the effective storage limit
  (override OR auto); `C.GetContainerStockLimit` often returns 0.
- `GetContainerWareConsumption(id, ware, ignorestate=true)` — `ignorestate=true` is REQUIRED,
  or it returns 0 for inactive modules.
- **Robustness:** wrap each state-changing FFI call in its own `pcall` (one failure shouldn't
  skip the rest); avoid full-station rescans in a single callback (crash risk) — update
  incrementally and cache. **Log a read-back** to confirm a write actually took effect; a
  `pcall`-true-but-engine-no-op "phantom success" is otherwise invisible.

### Lua gotcha
- **`a and nil or b` ALWAYS yields `b`** (`a and nil` → `nil`). Never use `x and nil or y` for
  a toggle; use an explicit `if`.

### MD persistence (save/load)
- **Vars on a SHIP component (`$ship.$var`) do NOT reliably persist** across save/load. Vars on
  the **NPC/pilot** component and on **`player.entity`** DO. The durable store is a
  `player.entity.$saved_*` **flat list of component refs**, rebuilt in your `Init` cue on load.
- **Writing the list isn't enough — signal your save cue after mutating it** (do it inside the
  core set/remove cue, not in each caller), or it serializes empty: live state looks correct
  but vanishes on every reload.
- **Live counts flicker:** values derived each scan from the `commander`/subordinate chain drop
  out transiently after `cancel_all_orders` (e.g. mass reassignment) breaks the chain — keep a
  sticky ship→owner cache as a fallback for when the chain is momentarily unresolvable.

### Engine XML / script syntax traps (seen as real `[=ERROR=]` lines)
- **`@` cannot be combined with `?`** — `@$obj.$x?` is a parse error. Use `$obj.$x?` (exists
  test) OR `@$obj.$x` (safe read), not both.
- **`.keys.list.count` is wrong → `.keys.count`.**
- In diff XPath, `//` matches ANY descendant; in complex cue trees prefer the fully-qualified
  `[@name='X']/child` to avoid matching the wrong node.

### kuertee UI Extensions — station-info tab (a common UI dependency)
- Register via `info_sub_menu_to_show` / `info_sub_menu_is_valid_for` / `info_sub_menu_create`
  (`menu.registerCallback`, MapMenu).
- **13-column limit** in the tab strip: count `config.infoCategories` before inserting; at ≥13,
  don't insert (the info page fails validation and crashes).
- **Return `is_valid_for` true for ALL player-owned stations**, not just one subtype — otherwise
  switching stations invalidates the active tab and the info window "disappears"; handle content
  special-cases with a hint text inside `create`.
- **Tab-nav scaffolding:** finish with `menu.createOrdersMenuHeader(frame, infoBorder, instance)`
  (v9) or `(frame, instance)` (older — test via `pcall`), plus `addConnection` on the header/info
  tables and positioning `tableInfo.properties.y`. Omit it and the tab bar vanishes.
- **Tables:** `addTable` with `backgroundColor = Color["container_subsection_background"]`,
  `backgroundID="solid"`, `backgroundPadding=0`, and an explicit `width` — else the background
  renders wrong and columns overflow ("column width exceeds max table width"). Narrow columns as
  fixed px (`setColWidth(i,px,false)`); exactly one flexible column via `setColWidthMinPercent`.
- **Interactive cells need real widgets** (`createButton`/`createCheckBox`); clicks don't fire on
  `createText`. Give interactive rows a string id so selection survives `refreshInfoFrame()`.
- **Sliders:** track the value in `onSliderCellChanged`, commit+refresh in
  `onSliderCellDeactivated`; `onSliderCellConfirm` doesn't fire reliably on drag-release.

### Station storage allocation (when scripting stock-limit overrides)
- Never set a ware's override **below its current stock** (it would show >100% / not fit):
  `units = max(computed, stock)`.
- A "max share per ware" cap fits container storage; solid/liquid behave better with fixed
  per-ware caps because the engine splits the physical space (else stores with few wares never
  reach 100%).
- Reserve large headroom only for wares actually **consumed** (`consumption > 0`); give
  surplus/products just current stock plus a small margin.

### Debug
- The debug log is **overwritten each game session** — copy it promptly after a test. Tag your
  own log lines with a short prefix so they're greppable. A mod that loads without crashing is
  not necessarily correct — watch for silent reference failures.

## Hook Candidates

*Proposed protections — implement when patterns emerge.*
- Protect `debug.txt` from edits (read-only log).
- Warn when editing a file that already has a diff patch in `dev\` (avoid overwriting work).

---

## Session Log

*Add brief per-session notes here — what was investigated, what was learned. Starts empty in
a fresh install; grows as you and Claude work together.*

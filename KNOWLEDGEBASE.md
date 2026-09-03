# KNOWLEDGEBASE.md — X4 Foundations Modding

Living reference of discovered X4 engine quirks, XML schema patterns, cross-file dependency
maps, and tool notes. **Always consult before making changes.** Add to it after every
session, bug, or research task — the environment gets smarter the more you use it.

---

## X4 XML Schema Patterns

### content.xml (Mod Manifest)

Every mod/extension must have a `content.xml` at its root:

```xml
<?xml version="1.0" encoding="utf-8"?>
<content id="my_mod_id" version="100" name="My Mod Name"
         description="What this mod does" author="AuthorName"
         date="2026-03-21" enabled="1" save="1">
  <dependency version="700" />
  <!-- Required DLC dependency example: -->
  <dependency id="ego_dlc_split" version="100" optional="false" />
  <!-- Optional dependency example: -->
  <dependency id="ego_dlc_boron" version="100" optional="true" />
</content>
```

Key attributes:
- `id` — unique identifier, lowercase with underscores, must be globally unique
- `version` — integer, increment on updates
- `save="1"` — mod is baked into saves; removing it can corrupt them. Use `save="0"` for cosmetic/optional mods where possible.
- `enabled="1"` — set to `0` to disable without uninstalling
- `<dependency version="700" />` — minimum game version required (no `id` = base game version check)

### XML Diff Patch Format

Diff patches are the standard way to modify existing game files. The patch file lives at the same relative path as the file it patches, inside the mod folder.

```xml
<?xml version="1.0" encoding="utf-8"?>
<diff>
  <!-- Replace a single attribute value -->
  <replace sel="//ware[@id='ore']/@price_average">500</replace>

  <!-- Replace an entire element -->
  <replace sel="//ware[@id='ore']/price">
    <price min="200" average="500" max="800" />
  </replace>

  <!-- Add a new child element -->
  <add sel="//wares">
    <ware id="my_new_ware" name="{1001,100}" description="{1001,101}"
          group="shipwares" transport="container" volume="1" tags="economy">
      <price min="1000" average="2000" max="3000"/>
    </ware>
  </add>

  <!-- Remove an element -->
  <remove sel="//ware[@id='unwanted_ware']" />
</diff>
```

The `sel` attribute is an XPath expression. Key XPath patterns for X4:
- `//ware[@id='foo']` — element with specific id attribute
- `//ware[@id='foo']/@price_average` — specific attribute of that element
- `//wares` — all `<wares>` elements (usually just one root element)
- `//dataset/wares/ware[@id='foo']` — fully qualified path (more reliable)

### Patching ANOTHER extension's file (cross-mod patch) — verified 2026-07-06
To diff-patch a file owned by another MOD (not base/DLC), mirror the target's FULL path INCLUDING its
extension folder, nested inside your own mod:
`<your_mod>/extensions/<target_extension_folder>/<original relative path>`
(e.g. `atd_ejection_router/extensions/kuertee_alternatives_to_death/md/kuertee_atd.xml`). The file is a
normal `<diff>`; the engine applies it onto the target's merged file. This is NOT the base-game form
(which uses a bare mirrored path like `md/foo.xml`). Load your mod AFTER the target — declare a
`<dependency id="...">`.
- Real installed examples: `kuertee_additional_agent_actions/extensions/kuertee_crime_has_consequences/md/kuertee_chc.xml`;
  `kuertee_emergent_missions/extensions/ego_dlc_pirate/md/story_research_erlking.xml`;
  `kuertee_npc_reactions/extensions/extendedconversationmenu/md/extendedconversationmenu.xml`.
- The `<target_extension_folder>` is the target's FOLDER name (e.g. `kuertee_alternatives_to_death`),
  which can DIFFER from its content.xml `id` (e.g. `kuerteeAlternativesToDeath`). The `<dependency id=>`
  you declare uses the content.xml `id`, NOT the folder name.
- **x4validate CANNOT verify these** (it builds base+DLC only) — it reports `no base game file for '<path>'
  (path mismatch?)`. That is EXPECTED for a cross-mod patch, not a real error. Verify each `sel=` yourself:
  `etree.parse(target_mod_file).xpath(sel)` must match exactly one node. (Superseded for Tier A only:
  `--tier b` resolves these. But see the warning below — Tier B is over-permissive in the *other*
  direction.)

#### ⚠ The bare-path form is INERT — proven 2026-08-01, caught by x4validate since same day (F19)
The nested form is not merely the convention, it is the only form the engine loads. A `<diff>` at a
**bare mirrored path** targeting a file owned by another MOD is **silently ignored** — no error, no
debug line, nothing.

**How it was proven** (`debug.txt` 2026-07-26; the engine emits one signature-failure line per loaded
extension file — 6,144 of them, 3,454 under `assets/`, 1,455 under the nested form):

| file | form | engine loaded it? |
|---|---|---|
| `zzz_yourname_overlay\libraries\factions.xml` | base-game path | ✔ yes |
| `zzz_yourname_overlay\assets\…\shield_cpsdo_*_mk4_macro.xml` ×7 | **bare path over another mod** | ✘ **no** |
| `zzz_yourname_overlay\extensions\ship_variation_expansion\…\caiman_macro.xml` | nested | ✔ yes |

A controlled comparison inside one author's own mods, with the files deployed two days before the
log. The "the line is per-vpath so a second mod wouldn't log" objection was tested and killed:
**356 distinct relative paths are logged for 2+ different mods** (up to 40 for one `t/0001.xml`).

**✅ F19 FIXED 2026-08-01 — x4validate now catches this, both tiers.** A bare-path `<diff>` over a
file only another mod supplies is an ERROR (category `path`) naming the supplying mod and the exact
`extensions/<owner>/<rel>` path to move to. Before the fix, `--tier b` reported such a mod
**0 errors, exit 0** — it let the installed mod's full file become the base and applied the dead
diff on top, a merge the engine will not do (and `oracle.py` is structurally blind here: it replays
ops the engine *rejected*, and an op never loaded produces no error line). The merge model was
fixed too: `build_effective` refuses the dead diff (`<mod>:diff(inert)` in sources), so
`x4effective`/`x4stats` now show engine truth — before, 14 attribute values in the effective tree
were ones the engine never sees. Full non-diff files still override cross-mod (the engine's VFS
honours those — `cpsdo_vro` clobbering `cpsdo_zb_modpack` weapon-fx macros is live proof); the
refusal applies to `<diff>` roots only, and `t/*.xml` diffs are never refused (the engine always
supplies the language tree). NOTE: BaseX's `x4eff` DB predates the fix — rebuild
(`tools\basex\build-effective.py`) before quoting it on a bare-path-patched vpath.
- Live instance, **REPAIRED 2026-08-02**: `zzz_yourname_overlay` had 7 such files (2 hengdao ship
  macros, 5 shield mk4 macros) dead since 2026-07-24 — moved under `extensions/cpsdo_zb_modpack/`
  (dev + deployed, byte-identical; snapshot at `.claude\backups\known-good-2026-08-01-pre-f19-repair-cpsdo_tweaks\`).
  Tier B now 0 errors with all 9 diffs genuinely sel-checked; install-wide inert count 0. The
  `<dependency id="cpsdo_zb_modpack">` already existed, so no manifest change was needed.
  **✅ ENGINE-CONFIRMED 2026-08-02** (`debug.txt` 00:25 run): all 7 files signature-logged at the
  nested path, 0 errors from the mod in 2,590 error lines — the tweaks are live in-game for the
  first time since 2026-07-24. This makes the bare-path rule N=2 on the SAME seven files (absent
  at bare path in the 07-26 log, present at nested path in the 08-02 log) → 99% confidence.

### Ware XML Structure (`assets/wares/wares.xml`)

A ware entry:
```xml
<ware id="ware_id" name="{page,t}" description="{page,t}" group="groupname"
      transport="container|bulk|liquid|condensate|energy" volume="N" tags="tag1 tag2">
  <price min="N" average="N" max="N"/>
  <use threshold="N"/>
  <restriction licence="licence_id"/>
  <icon active="icon_path"/>
  <owner faction="faction_id"/>
  <!-- For manufactured wares: -->
  <production time="N" amount="N" method="default" name="{page,t}">
    <primary>
      <ware ware="input_ware_id" amount="N"/>
    </primary>
  </production>
</ware>
```

### Cross-File Dependency Map

*Expanding as we work on mods. Add entries here when you discover new dependencies.*

**Adding a new ware:**
- `assets/wares/wares.xml` — ware definition (diff patch: add `<ware>` node)
- `libraries/wares.xml` — may also need entry depending on ware type (verify against base game)
- `assets/structures/production/modules/prod_*.xml` — if it's a manufactured ware, needs production module
- Translation file (`t/0001-l044.xml` for English) — name and description strings
- Potentially faction economy files if ware should be traded

**Modifying an existing ware price/stats:**
- `assets/wares/wares.xml` — diff patch on the specific `<ware>` node's `<price>` child

**Modifying a ship stat:**
- `assets/props/Ships/*.xml` — ship macro file (hull, storage, physics)
- `assets/props/Engines/*.xml` — engine macros if touching speed
- `assets/props/Shieldgenerators/*.xml` — shield macros if touching shields

*Note: exact paths to be verified against reference\ when implementing.*

---

## Tool Reference

### XRCatTool

Official EgoSoft tool for packing/unpacking CAT/DAT archives.

**Unpack base game (run from game root, -in order matters — later overrides earlier):**
```
tools\XTools_1.11\XRCatTool.exe -in 01.cat -in 02.cat -in 03.cat -in 04.cat -in 05.cat -in 06.cat -in 07.cat -in 08.cat -in 09.cat -out "{user home}\{toolkit root}\reference\"
```

**Unpack DLC (output dir must exist first — XRCatTool will not create it):**
```
cd "...\extensions\ego_dlc_split"
XRCatTool.exe -in ext_01.cat -in ext_02.cat -in ext_03.cat -out "{user home}\{toolkit root}\reference\extensions\ego_dlc_split\"
# Repeat for each DLC (terran, pirate, boron, timelines, ventures)
```

IMPORTANT: Create each output folder (`mkdir`) before running XRCatTool. If the output folder doesn't exist, XRCatTool exits with "is neither a catalog nor a folder, aborting".

**Pack mod for distribution:**
```
XRCatTool.exe -in "C:\...\dev\my_mod_name\" -out "C:\...\dist\my_mod_name\ext_01"
# Output: ext_01.cat + ext_01.dat
```

Note: `-out` for packing takes the base name (without .cat/.dat extension); XRCatTool adds them.

### X4-XMLDiffAndPatch

Command-line tools for generating and applying XML diff patches.

- `XMLDiff.exe` — compare original XML against modified XML, output diff patch
- `XMLPatch.exe` — apply diff patches to validate they work correctly

**Generate a diff patch:**
```
XMLDiff.exe -original "reference\assets\wares\wares.xml" -modified "my_edited_wares.xml" -output "dev\my_mod\assets\wares\wares.xml"
```

**Validate a patch:**
```
XMLPatch.exe -source "reference\assets\wares\wares.xml" -patch "dev\my_mod\assets\wares\wares.xml" -output "test_output.xml"
# Compare test_output.xml against expected result
```

### X4_Customizer

Python-based framework for programmatic bulk edits. Best for mass stat changes (e.g., "raise all shield regen values by 15%").

- Each customization is a Python plugin that reads game XML and writes modified versions
- Supports both reading unpacked files and reading directly from CAT/DAT
- Generates output as a mod extension
- See GitHub: github.com/bvbohnen/X4_Customizer

### x4validate ⭐ (our cross-file validator — BUILT 2026-06-22)

Location: `tools\x4validate\` (lxml-based; runs via the bundled uv + Python 3.13 toolchain). **Run on every mod before deploying** — see CLAUDE.md "Validation Convention". Built because no off-the-shelf tool reproduces X4's effective merged tree + reference graph (see Tool Evaluation below).

**What it checks** (exit code non-zero on errors → usable as a gate):
1. **`sel=` resolution** — every `<add>/<replace>/<remove>` `sel=`/`if=` is evaluated (real lxml XPath) against the effective base+DLC merged tree. Flags any op matching nothing (the silent-no-op gotcha). Correctly handles `//ware[...]`, `//cue[@name=...]`, `//conditions` — the idioms x4cat false-negatives.
2. **Reference integrity** — ware / macro (`<component ref>`) / `{page,t}` references the mod *introduces* must resolve to a real definition (defs unioned across base+DLC+mod).
3. **Completeness** — `--entity <type>:<id> --like <type>:<vanilla>` models a new entity's footprint on a vanilla analogue and lists missing pieces. Types: `ware`, `ship`, `module` (all are `<ware>` entries; the analogue decides which footprint kinds matter: definition, name_string, description_string, price, production, component, owner, restriction).

**Usage:** `cd tools\x4validate && uv run x4validate <dev\mod>` ( `--json` for machine output; `--tier b` folds in enabled mods but warns — inter-mod order is undocumented).

**Verified 2026-06-22:** 30 unit tests pass (incl. the x4cat spike cases); real ATD mod validates clean; deliberately-broken `sel=` flagged; incomplete new ware/ship correctly report missing pieces (e.g. a bare ship flags missing `component`/`production`/`owner`/`restriction`). **Limits:** reference catalog = ware + macro + text (extend in `_refs.py`); completeness recipes = ware/ship/module; Tier B not wired; no MCP wrapper yet. **Cross-mod patch blind spot:** a diff targeting ANOTHER mod's file (not base/DLC) reports "no base game file" and its `sel=` goes unchecked — verify those directly with lxml (`etree.parse(target).xpath(sel)` == 1 node; done 2026-07-06 for the `atd_ejection_router`→ATD patch). A clean run is necessary, not sufficient — still test in-game + read debug.txt.

### x4modlist ⭐ (mod-registry / Phase-A triage tool)

Location: `tools\x4validate\x4validate\{_registry,_modlist,_nexus}.py`, CLI `x4modlist`, skill `/x4-modlist-review`. Canonical store `dev\_registry\modlist.yaml` (ruamel round-trip, `auto:`/`human:` field split so refreshes never clobber user notes); dashboard `dev\_registry\WORKLIST.md`.

**★ SOURCE OF TRUTH (corrected 2026-06-22): the physically INSTALLED extension folders are PRIMARY**, not the profile `content.xml` enabled-list. `content.xml` is now only a secondary cross-check/backfill pass ("did I forget to re-acquire something from the old modlist?"). `x4modlist ingest` scans `extensions\` (game-root + profile + Steam Workshop `content\392160\`), reading each mod's OWN `content.xml` for its real `id`/`name`/`version`/`author` — **folder name can differ from the manifest `id`** (e.g. folder `X4CapturableXenonXL` → id `X4_Capturable_Xenon XL PERSONAL`), so always read the attribute, never infer from the folder. A mod tracked historically but not found on disk gets `auto.installed=False` and moves to a separate dashboard section (not deleted — its prior research, e.g. `nexus_id`, is preserved for if it's ever re-acquired).

**Identity resolution (A3) prefers the mod's REAL manifest name over a humanized-id guess** (`_modlist._resolve_identity`) — since installed-scan captures `installed_name` straight from content.xml, that's searched first via Nexus GraphQL, with two fallback transforms for common manifest naming patterns before falling back to the old humanized-folder-id guess:
- **leading author/category label** (`_strip_author_label`): `"kuertee: Ship scanner"` → `"Ship scanner"`, `"kuertee UI: Boarding operation notifications"` → `"Boarding operation notifications"`.
- **trailing qualifier** (`_manifest_name_variants`): `"Vibrant Engine Plumes - Divinity Edition"` → `"Vibrant Engine Plumes"`; `"Terran Beam Weapons VRO"` → `"Terran Beam Weapons"` (drops a trailing ALL-CAPS 2-5 char word).

This raised the auto-resolve rate on a real 31-mod installed scan from scattered partial hits to 31/31 having a real candidate (some still need spot-check confirmation — auto-match ≠ verified).

**Classifier gotcha found by dogfooding — `custom-local` lane.** A mod with Nexus `status=hidden`/`removed` is classified `drop` — UNLESS it's `human.custom_edited=True`, in which case it's `custom-local` (upstream unavailable but you maintain your own fork). Caught via ATD itself: its Nexus page is genuinely `hidden` (author updating it, per the ATD session logs below) but ATD is NOT abandoned — we've spent multiple sessions porting it to 9.0 in `dev\`. Classifying it `drop` would have been actively wrong guidance. General lesson: **any auto-classification that only reads upstream status, without checking whether the user has a maintained local fork, risks recommending abandonment of active work.**

**Nexus GraphQL quirk:** search can rank a wrong/niche fork above the real mod (e.g. searching "kuertee UI Extensions and HUD" top-matched a niche "...for SW Interworlds adoption mod" instead of the actual popular mod, Nexus 552) — this is exactly why every auto-match is flagged for spot-check with its candidate list shown, never silently trusted.

### x4compat / x4xref / x4stats ⭐ (cross-mod interaction suite — BUILT 2026-07-05)

Same `tools\x4validate\` package. Skill `/x4-mod-interaction` orchestrates all three; each has a
CLI. All read-only. Built because NO published tool does node-level cross-mod collision detection,
effective-tree diffing, or semantic comparison (survey 2026-07-05: closest is x4cat
`check-conflicts`, but it works on modder source dirs with string-equality sel matching — the same
`//` false-negative defect we rejected — and can't see packed mods).

- **`_cat.py`** — our own CAT/DAT reader (format independently verified; byte-identical to
  meethune/x4cat on real VRO data). Reads `ext_*` AND `subst_*` catalogs, MD5-verified, XML/XSD
  members only, **case-insensitive vpath lookup** (VRO ships `t/0001-L007.xml`, others `l007`).
  Wired into `_merge.build_effective` via `overlay_root()` (loose-over-packed) so packed mods
  (VRO, 217 MB / 1,613 XML members) are finally visible to ALL our tooling.
- **`x4compat check <mod>`** (`_compat.py`) — collision classes: **HARD** (≥2 mods replace/remove
  the same resolved node → later load-order wins, earlier silently dead), **UNION-KEY** (≥2 mods
  define the same `@id`/`@name` in a shared registry — the "two versions of the same ship id"
  case), **FULL-OVERRIDE** (≥2 non-diff full files at one asset path), **SOFT** (benign
  same-parent `<add>`s). Dispatches by merge semantics — union dirs (`t/`,`libraries/`,`index/`)
  overlap is NOT a conflict. Excludes per-extension `ui.xml` (loaded once per extension, never
  overrides). Real 33-mod run: 0 hard / 37 SOFT — a curated set genuinely has few structural
  clashes. **masterranweapons vs VRO is a NON-collision** (it adds a new ware; VRO edits different
  wares) — proving structural ≠ balance (that's x4stats' job).
- **`x4xref`** (`_xref.py`) — a who-calls / who-listens / cue index over base+DLC+all-mods
  MD+aiscripts (139,890 rows in ~4s). Answers behavioral-interaction questions in ONE query that
  took ~10 grep searches manually: `x4xref who-calls set_emergency_eject_active` → ATD's
  Init/OnOptionsMenu; `who-listens event_player_ejected` → base `notifications.xml:766` +
  tutorial. Indexes events (`event_*`), cue signal/def edges, and real action tags; skips
  control-flow / variable-plumbing noise.
- **`x4stats wares <mod>`** (`_stats.py`) — ADVISORY: each candidate ware vs the effective
  (VRO-inclusive) same-`group` price distribution (percentile). masterranweapons' turret →
  98th percentile of 161 turret wares (priced like a top-tier VRO turret — a balance flag to
  investigate, NOT a verdict). `x4stats macro <file>` flattens a macro's numeric props for
  peer comparison. Weapon DPS spans weapon+bullet macro pair — reports one file + its
  `<bullet class=>` ref; chase the peer manually for full DPS.

**Load order (who-wins) is derivable** (community-reported, not officially documented): X4 loads
extensions **alphabetically by folder**, later overrides earlier, with `content.xml` `<dependency>`
entries forced earlier. `_compat.compute_load_order` = Kahn topo-sort with alphabetical tiebreak.

- **`x4similar`** (`_similarity.py`) — advisory fuzzy same-ship detection. Extracts a numeric
  vector per ship macro (hull/crew/cargo/handling), hard-filters by macro `class` (`ship_xs/s/m/l/xl`)
  and `purpose.primary` (an S fighter is NEVER compared to an XL destroyer), scores weighted
  relative-difference similarity over shared keys. **A same-registry-KEY duplicate is x4compat's
  UNION-KEY job**; this catches a DIFFERENT id/name describing the same ship — the "VRO adds a
  ship, an unrelated mod adds an independent version, possibly a different name" case. Verified
  end-to-end: a synthetic VRO-style 2%-rescaled clone of a real vanilla fighter scored 99.4% and
  was correctly flagged. **Tuning note from real data:** require ≥4 shared numeric keys, not 3 —
  a 3-key match (e.g. hull + zero-crew + secrecy) produced a coincidental 100% "match" between a
  combat drone and an unrelated scout ship; 4+ keys covers ~98% of real vanilla near-duplicate
  pairs and eliminates that false-positive class. Score is a distance metric, not a power model —
  same stats ≠ same effectiveness; always eyeball flagged pairs.

### Tool Evaluation (2026-06-22) — XML validation / code-intelligence survey

Researched whether an off-the-shelf tool could do cross-file validation (does a `sel=` resolve? are references intact? did I touch all the right files?). Conclusion: **no turnkey tool does X4's effective-merged-tree + typed cross-reference graph** — we are building one (`tools\x4validate\`, lxml-based; see plan `shiny-tickling-puffin.md`).

- **x4cat (meethune) — `validate-diff` has a real XPath defect. DO NOT use as a `sel=` gate.** Its docstring claims it checks each `sel`/`if` matches ≥1 element, but the engine is hand-rolled on stdlib `ElementTree`, not real XPath. It anchors the first path segment to the document root, so **every `//descendant` selector — the most common X4 idiom — returns "root element mismatch" (false negative).** Empirical spike (`tools\x4cat-spike\spike_test.py`) on a `<wares>`-shaped doc: `//ware[@id='ore']` → FALSE (should match); `/wares/ware[@id='ore']` (absolute) → matched. **lxml got 5/5 right on the same cases.** x4cat is still useful for: `parse_diff_ops` (line-numbered op extraction), cat/dat packing, conflict detection — just not `sel=` validation. Python lib, needs Python 3.13 + `uv`. Cloned at `tools\x4cat-spike\`.
- **Serena (oraios) — NOT adopting now.** MCP toolkit, symbol-level editing via LSP. Genuinely supports Lua + Markdown, but **XML support is shallow** (uses `vscode-html-language-server`: in-file element symbols only; cross-file definition/references NOT exposed). No value for X4's cross-file XML web. Revisit only if we do Lua-heavy work.
- **GitNexus / Understand Anything — skip.** Call-graph knowledge-graph tools for procedural code; X4 data XML has no call graph to map.
- **Codebase MCP / RepoMix — skip.** Packs files into context; we already have Grep/Glob/Read, and `reference\` is too large to pack.
- **X4CodeComplete (archenovalis, Nexus 1721) — complementary, human-side.** VS Code extension: autocompletes `scriptproperties.xml` + Lua, peek/go-to-def for script properties. Editor-side authoring aid; does not validate cross-file refs or `sel=`. Worth installing for hand-editing MD/aiscript.
- **Generic standards (all do XPath correctly):** **Schematron** (`<assert test="XPath">`, can assert cross-file relationships; full engine via Saxon) is the closest generic answer; **xmllint `--xpath`** (libxml2 CLI) is the zero-dependency one-liner for a single-file `sel=` check (empty set + non-zero exit on no match, XPath 1.0); **LemMinX / Red Hat vscode-xml** is the generic XML language server (XSD/DTD validation, XPath 3.1, cross-file go-to-def). None encodes X4's merge or ID graph — they are engines/languages, not X4 checkers.

---

## Known Quirks & Version Issues

### ★ A diff's ops apply IN ORDER, to a tree the earlier ops have already changed

Discovered 2026-08-13 by diffing the engine's own skipped ops against x4validate's predictions per
item (`x4debug crosscheck`). X4 applies each `<add>`/`<replace>/`<remove>` in document order to a
**mutating** tree, so an op's `sel=` is evaluated against the result of every op before it — not
against the base file.

Both directions bite, and they are wildly asymmetric in practice:

```xml
<!-- the node is GONE by the time the replaces run: engine logs "No matching node" for both -->
<remove  sel=".../connection[@name='con_room_001']" />
<replace sel=".../connection[@name='con_room_001']/offset/position/@y">...</replace>

<!-- the node exists ONLY because of the add above it: perfectly valid, engine is happy -->
<add     sel="/components/component/connections"><connection name="con_room_099"/></add>
<replace sel=".../connection[@name='con_room_099']/offset/position/@x">7</replace>
```

**Two interaction shapes, and the one that matters is NOT the structural one.**

*Structural* — a later op selects into an earlier op's subtree by path. MEASURED over 113 mods
(4,389 mod XML files, 2,649 diffs, 161 with a `<remove>`): **2** ops select into an earlier
`<remove>` (1 mod), **458** select into an earlier `<add>` (18 mods).

*Value-predicated* — a selector predicates on an attribute value an earlier op just **wrote**. This
is the dominant class, it was invisible to the structural count, and X4_Customizer emits it by
default:

```xml
<replace sel=".../price[@min='432'][@average='540'][@max='648']/@min">516</replace>
<replace sel=".../price[@min='516'][@average='540'][@max='648']/@average">688</replace>
<replace sel=".../price[@min='516'][@average='688'][@max='648']/@max">826</replace>
```

Each op's selector only matches *after* the previous one ran — chained **1,443 ops deep** in a
single file in `mlog_deadair_eco_no_da_wares/libraries/wares.xml`.

**MEASURED consequence for our own validator** (full-corpus differential, 115 mods, before/after
teaching `_check_ops` to apply ops in order): **1,206 findings removed — every one a FALSE POSITIVE**,
each confirmed by the engine logging zero diff-op errors for that mod (mlog_deadair_eco 1,195,
da_ku_ai_tweaks 7, chillturrets 3, mlog_deadair_scripts 1) — and **6 added, all genuine**
(moreroomsforships 2 and sve_vro_trim 1, both engine-confirmed; npc_economy_tweaks 3, where
`diff.xsd` restricts `type` to `@&qname;` so `type="min"` should be `type="@min"` — the engine never
logs that one, the schema is the evidence).

> **Transferable lesson.** The structural count (2 + 458) was taken first and called a FLOOR out
> loud, because a literal prefix match cannot see a differently-spelled path. That caveat is the only
> reason the full differential was run — and the real driver turned out to be a class the count could
> not represent at all. **A measurement that names its own blind spot is worth more than a bigger
> number that does not.**

**Practical consequence when writing a diff:** you may freely `<add>` a node and then patch it in the
same file, and that is common (458 ops do it). But **never `<remove>` a node and then touch it**, and
be aware that reordering ops in a diff can change whether they apply at all.


### ★ Macros resolve by NAME through `index/macros.xml` — same name in two files means one is DEAD

Discovered 2026-08-09 while re-deriving the missile roster. A macro is loaded via its **name**, and
`index/macros.xml` maps each name to exactly ONE file. So when two mods define the same macro name
in *different* files, only the indexed one is ever read — **the other file is dead content, and
nothing in the game or the log says so.** The author can edit it forever with no effect.

- **Vanilla does this legally** (`cluster_sm3_background_macro` at six paths), so the pattern is only
  a question BETWEEN MODS.
- Measured on the live modlist: **20 macro names defined at 2+ vpaths by 2+ non-base mods** →
  20 live / **20 dead** definitions. `cpsdo_faction` 19, `rackham` 1.
- ⚠ The 19 `cpsdo_faction` ones are all `extensions/cpsdo_zb_modpack/assets/`**`prop`**`/…` against
  the engine's `assets/`**`props`**`/…` — i.e. the **same one-letter typo** already recorded as
  "134 dead patches", rediscovered by a completely different route. (134 = every file under the
  typo'd dir; 19 = the subset that are macro definitions colliding by name. Both figures are right.)
- **`x4compat` now detects this** as kind `NAME-CLASH`. It reports **no winner** on purpose:
  `index/macros.xml` decides and is itself patchable, so load order does NOT settle it — resolve
  with `x4effective dump index/macros.xml`.
- The per-vpath collision scan structurally CANNOT see this class: the two mods never share a path.

### `<ammunition>` inside `<create_ship>` is engine-legal; `md.xsd` is incomplete there

`md.xsd` rejects it ("This element is not expected. Expected is one of ( orientation, position,
safepos, rotation )"), but the ENGINE accepts it — verified against a live `debug.txt` in which the
engine parsed the same files to LINE granularity (expression warnings at specific lines) while
raising no objection at any of the 9 `<ammunition>` sites, in a log carrying 3,005 errors overall.
`common.xsd:11738` defines exactly that nested `<ammunition><ammunition macro= exact=/></ammunition>`
shape. Same family as the already-known `create_ship/@position|@rotation` gaps. x4validate demotes it
to `info`/`xsd-schema-gap` via an allowlist whose entry bar is **engine evidence, not plausibility**.

★ **General lesson: before concluding "only an in-game test can settle this", check whether the
engine ALREADY answered.** The profile `debug.txt` is a standing oracle from every session played.

### Game Version Notes
- Game is on **v9.0 RELEASE** as of 2026-06-12 (Steam buildid **23660954**). `reference\` was **re-unpacked 2026-06-22 from this release build** → CURRENT/authoritative for the live game (all live `01-09.cat` date 2026-06-12, older than the re-unpack). NB: an earlier note said "v9.00 public beta 2026-04-27 / buildid 22907298" — superseded; there is NO April unpack on disk, reference was refreshed in June.
- Previous session (March 2026) was on v7.x; v8.x and v9.0 happened between sessions
- Major updates frequently break mods — always check mod Nexus pages after game updates
- Ship mods are particularly fragile across updates (macro format changes)
- **Steam can roll back to ANY prior game version** (Steam → X4: Foundations → Properties → Betas → pick a version) → lets us **reconstruct any past version's game files (XSD schemas, XML) on demand** for cross-version comparison. This is why we don't pre-snapshot old game files (no "snapshot now or lose it" urgency) and why the schema-version-diff tool was dropped as unnecessary (2026-06-22).

### Boarding & Capturability model (9.0, verified 2026-06-24)
- **Capturability is gated in the ship MACRO by `<capture allow="0|1"/>`**, NOT by `libraries/ships.xml`. A ship macro with `<capture allow="0"/>` cannot be captured; **no `<capture>` element = capturable by default.** (The standalone `capturable=` attribute exists only as a `<ship>` attribute on Kha'ak ships in 9.0 — a red herring for Xenon work.)
- **Xenon capital ships are blocked**: `ship_xen_xl_carrier_01_a_macro` / `..._destroyer_01_a_macro` carry `<capture allow="0"/>` + `<people capacity="0"/>` + an invisible cockpit (`cockpit_gen_invisible_01_macro`). The **Xenon H = `xenon_terraformer_l`** (L-class, added ~8.0) has NO `<capture>` element → it IS natively boardable, and is the right vanilla analogue for capturable-Xenon work. Its bridge is **`bridge_tfm_l_01_macro`** (`tfm`=terraformer).
- **Boarding difficulty for a crewless (Xenon/AI) ship = `<boarding resistance="N"/>` in the macro properties** (faction ships derive it from real marines instead, so they have no such element). Terraformer baseline = `1600`. Hull-scale for bigger hulls (XL destroyer 265k → ~3800, XL carrier 480k → ~6850 vs the L terraformer's 112k).
- To make a Xenon capital player-boardable+operable (what the "Capturable Xenon XL" mod does): macro-diff `<remove sel="//properties/capture"/>`, set `<people capacity>`, swap the invisible cockpit for a real bridge (`bridge_tfm_l_01_macro`), add docks/launchtubes/storage, and add `<boarding resistance>`. `noplayerblueprint` on the hull ware also gates player-ownership/equip operations — removing it is part of the workaround and is harmless because there's no in-game method to acquire a Xenon blueprint anyway.

### ⚠️ Frozen ship geometry CRASHES on spawn after a version bump (`.jcs` = Jolt collision) — verified 2026-06-24
- **`.jcs` = Jolt Collision Shape** (X4 migrated to the Jolt physics engine in **6.0**): compiled
  collision/physics geometry **baked from the visual mesh** (`.xmf`) via convex-hull decomposition.
  Egosoft **re-bakes `.jcs` per version** (8.0 notes: "Improved collision shapes", "Fixed clip into Xenon
  K hull"; 9.0: weapon-mount collision fixes). The `.xmf` (visual shape) can be **byte-identical** while
  the `.jcs` changes — same shape, new collision encoding.
- **Symptom:** a mod that ships a **frozen copy of a vanilla ship's geometry folder** (to add a part, e.g.
  a docking-bay door) **hard-CRASHES on spawn** under a newer version, because its stale `.jcs` are
  rejected by the new Jolt loader. (This is why "Capturable Xenon XL" — frozen at 7.x — crashed spawning a
  K under 9.0; debug.txt died right after loading `…_data_cx\part_main-hull.jcs`. The author had stayed on
  7.x precisely because 8.0's collision re-bake broke it.)
- **Durable fix = DON'T ship hull geometry.** Drop the component diff's `<replace sel="//source">…</replace>`
  that points at the frozen copy → the component uses the **live vanilla geometry** (correct `.jcs`,
  auto-updates each version). Attach additions (docks/bridge/storage) via **separate components +
  logical connections** (offset-only, no mesh), exactly as the vanilla terraformer (Xenon H) does. A
  mesh part the mod genuinely adds (e.g. an `anim_dockdoor`) goes on an **`.xmf`-only sub-component**
  (dockareas carry `anim_dockdoor` + `<animations>` in vanilla — `dockarea_arg_m_station_01.xml`), never
  the hull. **No 3D re-modeling needed** if the vanilla `.xmf` set matches (confirm: every `.xmf`
  byte-identical → shape unchanged). Standard community fix too (Ship Variation Expansion 9.0 port:
  "Fixed JCS collisions"). Caveat: 9.0 also renamed some material/`.out` refs — a stale one can crash
  independently of `.jcs`, so re-check refs + debug.txt after re-pointing.

### ⚠️ Restoring an animated door durably on an `.xmf`-only sub-component — verified 2026-06-26
The durable replacement for a hull-mounted `anim_dockdoor` part (see entry above). A `<part>` always pulls
its mesh from its component's single `<source geometry>`, so a door part on the **hull** forces a custom
hull-geometry copy (= the `.jcs` crash). Move it to its **own component** instead. Recipe (per ship,
"Capturable Xenon XL" K/I):
- **New `.xmf`-only door component + macro** (`class="dockarea"`), `<source>` → a tiny `_data` folder with
  just `anim_hatch-lod0.xmf` + `-collision.xmf` (**no `.jcs`** → version-proof; the door connection is
  `nocollision` anyway). Register both in `index/components.xml` + `index/macros.xml`.
- **Door part connection** carries the `anim_hatch` part + the original `<animations>` (`dockingbay_*`
  frames) AND **must include the `component` tag** in its `tags=` (that's the parent-attach mate point —
  e.g. `tags="part component animation detail_xl nocollision forceoutline anim_dockdoor "`).
- **Attach via the ship MACRO** (`<connection ref="con_animdoor"><macro ref="..._macro"
  connection="Connection01"/></connection>`) at a ship-COMPONENT connection (`con_animdoor tags="dockarea"`)
  placed at the **original hull `Connection71` offset** → net world placement unchanged, reuse known-good
  numbers, minimal in-game tuning.
- **★ A `dockarea`-class sub-component is a "non-virtual module" → it REQUIRES a wreck geometry**, else
  `[=ERROR=] Non-virtual module '<macro>' does not have a wreck geometry defined` (non-fatal but logged).
  Fix mirrors vanilla dockareas (`<part name="part_main" wreck="part_main_wreck">`): add `wreck="anim_hatch_wreck"`
  to the part and ship `anim_hatch_wreck-lod0.xmf` (+`-collision.xmf`) — a copy of the door mesh, still no `.jcs`.
  `<hull integrated="1"/>` does NOT exempt it (the working dockareas have both).
- **Animation likely won't auto-trigger** on a standalone component (the engine drives `anim_dockdoor` from
  a dockingbay's ship-presence, which a decorative door lacks) → it renders as a **static closed hatch**.
  Acceptable/cosmetic; clean static fallback = drop `<animations>` + the `.ANI`. The `.ANI` is named
  `<GEOMETRY_FOLDER_UPPERCASE>.ANI` beside the `_data` folder.
- **Public/personal folder-name dependency:** geometry `<source>` and `index` `value=` paths are relative
  to game root and **hardcode the extension folder name** (e.g. `extensions\X4CapturableXenonXL\…`). A
  public copy that reuses these paths only resolves its custom geometry if **installed under that exact
  folder name** — so a "personal vs public" pair that's content-identical (id-only diff) must distribute
  under the same folder name, OR have its paths rewritten. (Applies to ALL custom geometry, not just doors.)

### CAT/DAT Override Order
- Base game: `01.cat` < `02.cat` < ... < `09.cat` (higher number wins)
- DLC catalogs override base game catalogs
- User extension CAT/DAT override everything
- When unpacking reference files, unpack in order so later files overwrite earlier ones (correct final state)

### Version Catalogs `ext_vNNN.cat` — EXACT game-version match (engine-proven 2026-08-02, F16)
An extension may ship `ext_vNNN.cat` beside its plain cats. **The engine loads it ONLY when the
current game version equals NNN exactly** — documented in the official Egosoft Steam Workshop
guide (*"version 1.50 would look for ext_v150.cat; if it exists it will be used to override
content from your other extension catalog(s)"*) and engine-proven twice from one debug.txt on
v9.00 (`version.dat` = 900):
1. `ebi_timelines_faction_use_ship`'s `ext_v800.cat` wares define `ship_tfm_xl_carrier_01_a`;
   the engine logs `Property lookup failed: ware.ship_tfm_xl_carrier_01_a` → v800 never applied.
2. The same mod's MD file exists in both cats with the `_a` reference at lines 11+30 (ext_01) vs
   11+26 (v800); the engine's errors cite **11 and 30** → it parsed the ext_01 revision.

Consequences:
- **A non-matching version cat is dead weight** — "highest vNNN ≤ current" is disproven. After a
  game update, every mod's `ext_v<old>.cat` silently stops loading (the ebi mods run their
  pre-8.0 revision on 9.00; ebi_timelines logs 2 cosmetic errors/session from a leftover grant of
  a ware only its dead v800 wares.xml defines — functionally intact, its MD grants both variants
  and the loaded `_b` set works).
- **x4validate/`_cat.py` skipping version cats matches the engine** for every installed mod today.
- Egosoft also uses an **`ext_NN_diff_vNNN.cat`** form (`ego_dlc_ventures` ships
  `ext_01_diff_v900.cat`/`ext_03_diff_v900.cat`, signed, exported 2026-05). Presumed live on 9.00
  (~90%, not directly fingerprintable from the current log). **`reference\`'s ventures tree lacks
  those v900 deltas** (4 wares' icon-videos/`use threshold`, one MD file, 8 asset macro XMLs) —
  tiny, ventures-only staleness; re-check before trusting reference\ on venture equipment.
- Zero-byte members in a version cat are file DELETES for that version (same convention as
  higher-numbered base cats).

### Extension Merge Strategy & Load Order (mapped 2026-06-22)
Reproducing the game's *effective* XML for a file = base + DLC + enabled-mod overlays. Key facts:
- **Base files are full documents.** Overlays use a **mixed strategy decided by root element**, NOT by folder:
  - root `<diff>` → apply ops to the prior tree (DLC `libraries/*.xml` are diffs).
  - non-`<diff>` root → strategy depends on the DIRECTORY: **shared-registry dirs (`libraries/`, `index/`, `t/`) are additively UNIONED** (base + every DLC's entries coexist; dedupe by `@id`/`@name`, later-wins), while **`assets/` files are full-file overrides**. Every DLC ships `libraries/ships.xml`, `character_macros.xml`, `wares.xml`, `loadouts.xml`, … as full files and the engine MERGES their entries with the base — `libraries/` is NOT override-only. ⚠️ **x4validate clobber bug (FIXED 2026-06-24):** `_merge.build_effective` used to treat every non-diff overlay as `tree = oroot` (full override), so processing the DLC `libraries/ships.xml` (full `<ships>`) clobbered the base-game ships out of the effective tree → phantom "`sel` matched nothing" for any mod patching a base `<ship>` (e.g. `//ship[@id='xenon_carrier_xl']`). Fix = root-tag-match union for the registry dirs (`_ADDITIVE_DIRS`), dedupe by id/name. See `_merge.py::_union_children` + `tests/test_merge.py::test_full_file_registry_union`.
  - **`index/macros.xml` (and `index/components.xml`) are UNIONED** across base + every DLC + every mod — each extension registers its own `<entry name="X_macro" value="path"/>` mappings. A macro "exists" if its name appears in the merged index. x4validate's `collect_macro_defs` unions these (4663 macros in base+DLC). Mods register new ship/module macros via `<add sel="/index">`.
  - The three game-root mods (`sn_mod_support_apis`, `kuertee_ui_extensions`, `kuertee_alternatives_to_death`) all use `<diff>` for game XML; `sn_mod_support_apis` ships no game-XML patches (pure Lua/API).
- **Diff ops (`reference\libraries\diff.xsd`):** `add` (attrs `sel`, optional `pos`=before|after|prepend [default append], `type`, `if`, `silent`), `replace` (`sel` incl. `/@attr`, `if`, `silent`), `remove` (`sel`, `if`, `silent`). `if=` is evaluated against the *current* merged state; a false `if` silently skips. `silent="true"` makes a non-matching `sel` non-fatal. Diffs apply sequentially — a later diff sees earlier diffs' results.
- **Load order is NOT encoded in `content.xml`** (it lists `id` + `enabled` only). Tiering: base → every installed DLC → enabled mods. **Inter-mod order is undocumented** — any tool wanting bit-exact multi-mod fidelity must confirm empirically (dump the game's merged XML). DLC diffs use defensive `if="not(...)"` guards, implying DLC-applied-before-mods and order-independence within DLC.
- **The user profile lives at `Documents\Egosoft\X4\<profile-id>\`**, and that id is the Steam3 account id -- treat it as personal data and keep it out of anything you publish. `content.xml` there is the enabled-mod DECISION LOG, not an inventory. With the in-game Steam Workshop download option ON, subscribed mods land directly in the game-root `extensions\` folder; X4 has no `steamapps/workshop` directory of its own, so the absence of one says nothing about what is subscribed.

### Signature System
- All base game files have `.sig` signature pairs
- Modifying base game .cat/.dat files breaks signature verification = game may refuse to load
- Always work in the `extensions\` folder — extension files don't need signatures
- The game's signature system only applies to the core game files, not user extensions

### Debug Output
- Game writes errors to `{user home}\Documents\Egosoft\X4\{profile-id}\debug.txt`
- Always check this after testing a mod — XML parse errors and missing references show up here
- A mod that loads without crashing is NOT necessarily correct — check debug.txt

### Remote Desktop Input Conflict: RustDesk & On-Foot Mouse Cursor (discovered 2026-07-08)
When remote-controlling X4 via **RustDesk** (or similar remote desktop software):
- **Symptom:** Mouse cursor remains visible while walking on foot (first person). Cursor is pinned to screen edge; cannot turn 360° (capped at ~90°). Shift+Space / Ctrl+Space toggle has no effect; pressing it repeatedly shows no visible toggle.
- **Root cause:** RustDesk's cursor/input handling interferes with X4's mouse steering toggle, leaving the engine in "cursor mode" (UI pointer active) rather than "free-look mode" (cursor hidden, direct mouse control).
- **Diagnosis:** Same config works correctly on **native local monitor + mouse**. If remote and broken, if local and perfect, it's RustDesk.
- **Workaround:** Use native monitor + mouse for on-foot gameplay sections. Remote is fine for menus, space flight, docking.
- **Not a mod issue, not a 9.0 bug, not hardware drift** — it's a known interaction between remote desktop software and game input handling. (Likely other remote tools like TeamViewer, AnyDesk, etc. have the same issue; untested.)

### Translation String Format
- `{page_id, t_id}` format — references `t/0001-l044.xml` (English) by page and string ID
- Mods can add their own translation page IDs — pick a high unique number to avoid collisions with base game and other mods (e.g., 20000+)
- Without a matching translation entry, the game displays the raw `{page,id}` string as text (visible indicator of a missing string)
- **t-files are UNIONED, not overridden** (discovered 2026-06-22 building x4validate). The game merges `<page>`/`<t>` entries from *every* `t/` file across base + all DLC + all mods. A DLC's full `<language>` file at the same path does NOT replace the base file — it adds pages. Any tool resolving `{page,t}` must union across all sources, or it will wrongly report base strings as missing (a 5.8 MB base English file was masked by a 73 KB DLC file under naive override).
- **A string may be defined in the language-NEUTRAL `t/0001.xml` OR the English `t/0001-l044.xml`** (plus per-language `0001-l0NN.xml`). Many mods (e.g. ATD) put their English strings in `0001.xml`. When checking a `{page,t}` exists, look in BOTH `0001.xml` and `0001-l044.xml`. Language code suffixes: l044=English, l049=German, l007=Russian, l086=Chinese.

### content.xml Save Flag
- `save="1"` means the mod is referenced in save files
- If a player loads a save that references a mod, and that mod is missing/disabled, the game warns them
- Removing a `save="1"` mod mid-playthrough can cause issues
- Use `save="0"` for mods that only affect UI, visuals, or quality-of-life items that won't affect save state

### Loose Files vs CAT/DAT
- During development, loose files in an extension folder load identically to packed CAT/DAT
- The game reads loose files and CAT/DAT — loose files take priority if both exist
- Always develop with loose files; only pack for distribution

---

## MD (Mission Director) Scripting Patterns

### event_ui_triggered round-trip pattern
A common mod pattern: MD fires a Lua event, Lua processes and responds, MD waits for the response.

```xml
<!-- MD side: fire event and wait for response -->
<raise_lua_event name="'mymod.GetData'" />
<!-- ...cue resets here... -->
<cue name="OnGetData">
    <conditions>
        <event_ui_triggered screen="'mymod'" control="'on_get_data'" />
    </conditions>
    <actions>
        <!-- event.param3 contains data from Lua -->
    </actions>
</cue>
```

```lua
-- Lua side: respond to the event
RegisterEvent("mymod.GetData", function(_, _)
    local data = computeData()
    AddUITriggeredEvent("mymod", "on_get_data", data)
end)
```

**Critical failure mode:** If the Lua handler crashes (nil dereference, missing API) or was never registered, `AddUITriggeredEvent` never fires, and the `event_ui_triggered` cue waits forever. The game continues normally but the MD script is stuck. Any state changes made before the raise_lua_event call are saved to the save file, creating an inconsistent state.

**Fix pattern:** Always add a timeout fallback cue alongside the waiting cue, and nil-guard all Lua calls before `AddUITriggeredEvent`.

### ⚠️ `signal_cue_instantly` to a not-yet-listening callback sub-cue → "no corresponding listeners" (verified 2026-07-07)
A synchronous callback pattern that races: a parent cue's actions call a shared "compute" cue and pass one
of the parent's OWN nested sub-cues as the callback; the compute cue then `signal_cue_instantly`s that
sub-cue back with the result.

```xml
<cue name="DoRansom">
  <actions>
    <!-- ...this is the LAST action; the sub-cue below is NOT active yet... -->
    <signal_cue_instantly cue="GetPlayerProperties" param="table[$callback = TransferRansom]" />
  </actions>
  <cues>
    <cue name="TransferRansom"><conditions><event_cue_signalled/></conditions> ... </cue>
  </cues>
</cue>
<!-- inside GetPlayerProperties, after synchronous work: -->
<signal_cue_instantly cue="$callback" param="table[$properties=$properties]" />   <!-- FAILS -->
```

`signal_cue_instantly` runs entirely **inside the parent's still-executing action block**. A nested sub-cue
(`event_cue_signalled`) only becomes a listener **after its parent's actions finish**, so at the instant of
the instant-signal it is not listening → engine logs `Signalled cue <x> has no corresponding listeners` and
the callback **silently never runs** (e.g. the whole ransom/ownership transfer no-ops, no crash).

**⚠️ `signal_cue` does NOT defer the listener check — only the delivery.** The intuitive fix
(`_instantly`→`signal_cue` so it "lands next frame") does NOT work: `signal_cue` still verifies the target has
active listeners **at CALL time**, in the caller's context, and errors identically if the sub-cue isn't live
yet. (Verified in-game 2026-07-07: the error fired at the exact `<signal_cue>` line.) So the dispatch itself
must be MOVED to a cue that runs on a **later frame**.

**Correct fix — dispatch from a delayed sibling cue.** A nested sub-cue (`event_cue_signalled`) becomes a
listener only AFTER its parent's actions complete. So a producer that runs synchronously inside the caller's
action block cannot signal the caller's own callback sub-cue. Route it through a sibling that fires a frame
later:

```xml
<!-- producer GPP (synchronous): stash result + the pending callback; DO NOT signal the callback here -->
<set_value name="kATD.$gppResult"          exact="$properties" />
<set_value name="kATD.$gppPendingCallback" exact="$getPlayerPropertiesCallback" />

<!-- sibling: triggered by the producer being signalled, delayed one frame, THEN dispatches -->
<cue name="DispatchGppCallback" instantiate="true">
  <conditions><event_cue_signalled cue="GetPlayerProperties" /></conditions>
  <delay exact="1ms" />           <!-- any positive delay = next frame; caller sub-cue is live by then -->
  <actions><do_if value="kATD.$gppPendingCallback">
    <signal_cue_instantly cue="kATD.$gppPendingCallback" />   <!-- now it IS listening -->
    <set_value name="kATD.$gppPendingCallback" exact="null" />
  </do_if></actions>
</cue>
<!-- callback cue reads the var (signal_cue_instantly could carry param too, but the var keeps callbacks unchanged) -->
<set_value name="$properties" exact="@kATD.$gppResult" />
```

Also note **`signal_cue` cannot carry `param`** (md.xsd rejects `<signal_cue … param=…>`; base-game: 2996
`signal_cue_instantly` w/ param vs **0** `signal_cue` w/ param) — another reason the var hand-off is needed if
you ever DO use deferred `signal_cue`. Grounding for the sibling pattern: it's exactly how ATD's own
`OnGetPlayerProperties_Timeout` and the original async `OnGetPlayerProperties` already dispatch these callbacks
(from a later frame). A cue with no `namespace="this"` inherits its nearest ancestor's namespace — that's how
GPP + all four callbacks share `kATD.$gppResult`/`$gppPendingCallback`.

**Where this bit us:** kuertee ATD's 9.0 port made `GetPlayerProperties` synchronous but kept dispatching from
GPP's body → trust/confiscate/destroy/ransom all raced (ransom fired in-game). Two wrong attempts first:
(1) `_instantly`→`signal_cue` keeping `param` — md.xsd caught it (attribute not allowed); (2) `signal_cue` +
var hand-off — md.xsd-clean but STILL failed in-game (listener check is at call time). Fixed 2026-07-07 by
moving the dispatch to the delayed `DispatchGppCallback` sibling. See [[x4_atd_ransom_callback_fix]].

### ⚠️ A library/sub-routine that branches on a value set AFTER it's called → the branch is dead code (verified 2026-07-08)
An `include_actions`/`run_actions` library that does `<do_if value="$x == 'foo'">` runs its check against `$x`'s
value **at the moment the include executes**, not later. If the caller sets `$x` *after* the include, that branch
never fires on the main path — silently. Symptom looks like "the special-case behavior is being ignored."

**Where this bit us:** kuertee ATD `PlayerDeath` set `kATD.$deathAlternative = null`, then `include_actions
ref="FindNearestContainers"` (line ~1436, needed early to build the teleport-eligibility list), then chose the
outcome `$deathAlternatives.random` (`assimilation`/`ransom`/…) at line ~1488 — AFTER. `FindNearestContainers`
has a dedicated `do_if value="$deathAlternative == 'assimilation'"` branch (respawn at a station aligned with the
attacker faction), but at include time `$deathAlternative` was still `null`, so it always took the default branch
(nearest station neutral **to the player**) — identical to ransom. Net effect: **assimilation and ransom deposited
the player at the same station**; the assimilation branch was dead on the primary path (only reachable in the
teleport-failure retry loop, where the outcome happened to be set by then).

**Fix (2026-07-08):** re-run the routine after the branch value is known — `<do_if value="$deathAlternative ==
'assimilation'"><include_actions ref="FindNearestContainers"/></do_if>` inserted right after the outcome pick.
Re-including is safe when the library only writes local find vars (idempotent). Also hardened the assimilation
branch itself to `match owner="$attackerFaction"` FIRST (land at the new faction's OWN station), falling back to
the author's original `match_relation_to ge neutral` → `ge kill`. Lesson: **when a shared routine branches on
state, verify that state is populated at every call site** — a `find`/`include` before the deciding assignment is
a classic silent no-op. See [[x4_atd_assimilation_respawn_fix]].

### Cue namespace variables and save corruption
Variables stored on cue namespaces (e.g., `kATD.$ship`, `kATD.$shipCountdownCues`) are serialized into save files. Potential corruption sources:
- Object references to destroyed entities (ships, stations) — deserialize as invalid handles
- Table keys that mismatch between write and read (key prefix bugs)
- Cue references pointing to reset/cancelled cues

Safe pattern: always use `@` operator for potentially-invalid object reads (e.g., `@$ship.exists`, `@$someTable.{$key}.$field`).

**`save="0"` ≠ "leaves nothing in the save" (common misconception, clarified 2026-06-24).** The content.xml `save` flag ONLY controls whether the mod is recorded as a *save dependency* (the "this save requires extension X" record). It does NOT stop the mod's globals/active-cue namespaces from being serialized. A `save="0"` mod that sets `global.$foo` still writes `global.$foo` into the save; uninstalling leaves orphaned globals + any spawned entities (which persist as normal game objects). This is **residue / can't-cleanly-uninstall**, NOT data-loss corruption — a distinction the community routinely conflates. Mitigation: namespace every global (`global.$mymod_foo`, never `global.$conversation_list_temp`) to avoid cross-mod collisions.

**Cheat-mod "corrupts saves" myth — investigated 2026-06-24 (slan_cheat → iseeu0_cheat lineage).** No evidence of passive/silent vanilla save corruption. The only substantiated mechanism is self-inflicted: **spawning duplicate unique objects (e.g. multiple Player HQs)** — the engine assumes exactly one, so a second one breaks the save (acknowledged by Safe Cheat Panel's own author). The blanket "installing it kills your save" traces to the SWI total-conversion wiki (true only in SWI's script-replacement context) and got generalized as hearsay. Real lesser issues: (1) residue (above); (2) the 2018 `slan_cheat` patches base-game order scripts (`order.move.wait.xml` etc.) via `<diff>` — fragile across version bumps, and confirmed throwing `slan_cheat_database.xml: Property lookup failed` on 9.0. The `iseeu0_cheat` fork already fixed the script-collision by namespacing all orders to `order.iseeu0.cheat.*`.

### Spawning fully-equipped ships: `generate_loadout` + `apply_loadout` (verified vs 9.0 reference, 2026-06-24)
To spawn an EQUIPPED ship in MD, do NOT try to specify the loadout inline in `<create_ship>` — vanilla creates the ship bare, then equips it afterward:
- `generate_loadout` **returns a LIST** of loadout variants (vanilla even comments `"returns a LIST of loadouts"`). `apply_loadout` takes ONE element — iterate the list (`<do_for_each>`), or `$loadout.{1}`.
- `level` is a **scalar 0.0–1.0** (`level="1"`, `"0.9"`, `$ship.loadoutlevel`) — NOT a `<level min/max>` range. 1.0 = fully equipped.
- `faction` must **match the ship's owner/race** (`faction="$shipfaction"`), NOT hardcoded to one faction. Wrong faction → incompatible/empty loadout → ship spawns with no engines/weapons (the classic cheat-mod spawn bug).
- Robust pattern (from Safe Cheat Panel, working on 9.0): after `apply_loadout`, `find_object_component class="class.engine"` and retry/iterate until one has an engine.
```xml
<generate_loadout result="$loadout" faction="$ownerFaction" macro="$shipMacro" level="1.0"/>
<do_for_each name="$lo" in="$loadout"><apply_loadout object="$ship" loadout="$lo"/>
  <find_object_component name="$eng" object="$ship" class="class.engine"/>
  <do_if value="@$eng != null"><break/></do_if></do_for_each>
```

### Conversation choices now REQUIRE `actor` (9.0) — and the cheat-menu activation events
`<add_player_choice_subconv>` (and `<add_player_choice>`) now **require an `actor` (or `template`) attribute** in 9.0. Missing it → load-time `[=ERROR=] Neither of the attributes 'actor' and 'template' is present!` and the choice **silently does not appear in the menu** (the rest of the conversation still works). Fix: add `actor="player.computer"`. **x4validate's XSD pass does NOT catch this** (conditional-attribute rule, not plain content-model/required-attr) — only the engine/debug.txt flags it. → validator-extension candidate.
- The **Slan/ICU cheat menu is activated by game controls, not a mod hotkey**: `event_player_toggled_cockpit` → full menu (`start_conversation conversation="iseeu0_cheat_menu"`); `event_player_toggled_hud` → quick menu. User binds/uses **Settings → Controls → "Toggle Cockpit" / "Hide HUD"**. `event_player_toggled_cockpit` confirmed valid in 9.0 (vanilla `scenario_tutorials.xml`).
- Null-safety: `$obj.order.state` throws `Property lookup failed` when `.order` is null (idle ships) — guard with `@$obj.order.state`.

### Player ejection / death is ENGINE-INTERNAL; how ATD suppresses it (verified 2026-07-05)
Vanilla emergency-eject is a **built-in engine feature** ("Automatically eject in an emergency"),
NOT an MD cue. No script spawns the spacesuit — the engine does, then raises `event_player_ejected`,
which MD only *observes* (`base:md/tutorial_global.xml:351 FirstEmergencyEject`,
`base:md/notifications.xml:766 PlayerEjected`). Toggled via `set_emergency_eject_active` /
`player.hasemergencyeject`. **kuertee Alternatives To Death disables ejection with two independent
locks:** (1) `Init` runs `<set_emergency_eject_active active="false"/>` (engine feature off, so
`event_player_ejected` never fires — flipped back on only while the Options menu is open); (2) on
first damage `OnPlayerShipHit` pins the ship via `<set_object_min_hull object="$ship" exact="1"/>`
so the engine never reaches ship-destroyed-with-player-aboard. ATD then teleports the player out
FIRST and destroys the now-empty ship itself. **Interaction consequence:** a third ejection/escape
mod hooking `event_player_ejected` or `event_object_destroyed` on the player ship is DEAD under ATD
(neither fires); only a hull-% poll could co-fire (ATD holds hull at 1). ATD integrates kuertee's
own Escape Pod (Nexus 596) as a manual countdown button via `md.EscapePod.*` probing, not events.
Trace any such question with `x4xref who-calls set_emergency_eject_active` / `who-listens
event_player_ejected` (one query vs ~10 greps — the tokens share no keyword with "eject"/"death").
(The INSTALLED provider of `md.EscapePod` is Nexus **1899** "Escape Pod Reloaded" by
strayhound/Mystermask625/MrBlair29 — a fork of kuertee's original Nexus 596; both use namespace
`md.EscapePod`, so ATD's `md.EscapePod.*` integration binds to whichever is installed.)

### Vanilla crew/NPC bail is OWNERSHIP-gated (not size-gated); the atd_ejection_router mod (2026-07-06)
Two SEPARATE bail systems, NEITHER picks suit-vs-pod by ship size:
- **Harassment/surrender bail** — `base:md/notifications.xml:1184 PlayerOwnedShipAttacks`, fires while the
  ship is ALIVE (damage-to-claim). Vehicle = OWNERSHIP: `eject_people ... spacesuit="$target.isplayerowned"`
  → your crew → SUIT; the enemy branch is a bare `eject_people` (no `spacesuit=` → defaults FALSE) → enemy →
  vanilla POD (`crewtransfer.podmacro = ship_gen_xs_escapepod_01_a_macro`), at ALL sizes. The PLAYER is
  EXCLUDED (`not $target.pilot.isclass.player`) — never fires on the player's occupied ship.
- **Escape Pod mod NPC bail** — `escape_pod_npc.xml:54 PlayerOwnedKilled` on `event_player_owned_destroyed`,
  player-owned only. Size gates only the survivor COUNT (`$maxnum_bail` S:0-1 … XL:10-30); survivors go to
  SUITS then its own pod-rescue. Vanilla has NO crew-survives-on-destruction; the mod ADDS it.
- Suit-vs-pod for CREW is cosmetic — vanilla rescue mechanisms (`g_rescueplayersuit`, `RescueShip`,
  `rml_rescueship*`) all key on the PLAYER being in a suit, never crew; bailed crew are effectively lost
  either way. The pod is NOT stored in the hull (spawns beside the ship), so "too big for an S-ship" has no
  engine basis; enemy pods = intended lootable salvage.
- **Player spacesuit macro:** `ship_gen_xs_spacesuit_01_a_macro` (what `entity_player_macro` assigns);
  race variants `ship_{arg,par,tel}_xs_spacesuit_01_a_macro` exist. `eject_people`/`eject_npcs` `spacesuit=`
  bool chooses suit vs `crewtransfer.podmacro`; both FORBIDDEN on `ship_xs`.
- **Reusable technique — injecting an ejection branch into ATD** (from the `atd_ejection_router` mod):
  inject after ATD's `$deathAlternatives.random` pick (`kuertee_atd.xml:1488`) and null
  `kATD.$deathAlternative` + `$isDestroyShip` to neutralize ATD's own outcome, then run your own eject.
  Two findings verified in-game 2026-07-06: (1) **re-enabling the engine emergency-eject at the death
  moment DOES NOT eject** — `set_emergency_eject_active active="true"` honors (`isemergencyejectactive`
  0→1) but the engine never ejects on a scripted/held destruction (`event_player_ejected` never fires);
  spawn the craft yourself instead. (2) **A player craft spawned into active combat MUST be protected
  or it dies instantly** — an unprotected spacesuit was killed by enemy `hitbyareadamage` 0.04s after
  spawn. Pin it on creation: `set_object_min_hull object="$craft" exact="100"` (+
  `disable_collisions_between` with the doomed ship), then teleport the player in, destroy the empty
  hull, and release the pin after a grace window. This is exactly what Escape Pod's TriggerPod does for
  its pod. Mod specifics in project memory.

### NPC starting skills live in `libraries/characters.xml` (verified 2026-07-05)
Each `<character>` has a `<skills><skill type= min= max= exact=>` block on a **0–15 scale**
(15 = 5 stars; `common.xsd`: "steps of 1/3 of a star"). Selection is by `<category tags= faction=
race=>` + `<owner>`. Tiers (rookie/regular/veteran/elite) are SEPARATE `<character>` entries with
their own ranges — **no global multiplier**, a broad rebalance patches dozens. **Xenon and Kha'ak
DO have pilots with real skills**: `xenon_generic` (piloting 8–15, morale 12–15) and `khaak_generic`
(morale 9+), both `class="computer"` / non-commable but feeding the same skill math; DLCs only ADD
characters, never touch these two. Adjust via diff, e.g.
`sel="/characters/character[@id='xenon_generic']/skills/skill[@type='piloting']/@min"`.
`libraries/experiences.xml` = skill *progression* (gain-per-event), a separate file. **Engine-side
(not in XML, needs playtest): how a min/max range is rolled, and how a job/ship maps to which
character tier.** No script-side skill override exists (`create_npc_*` has no skill attribute).

### `<wait exact="...">` takes a TIME, never a cue/library reference
`<wait exact="$dur">` / `"10s"` / `"($target.hull)s"` are valid; `<wait exact="md.SomeScript.SomeLibrary"/>` is NOT (XSD: `Element 'wait' not expected`). A `purpose="run_actions"` library runs **synchronously inline** at `<run_actions>`, so there is nothing to wait for afterward — a trailing `<wait>` on it is both invalid and redundant; just delete it. (Also: `<do_if>` placed AFTER `</actions>` inside a `<cue>` → `Element 'do_if' not expected, expected (delay, force, patch, patches, cues)` — it's dead code; move it inside `<actions>` or delete.)

### md.xsd is STRICTER than the live 9.0 engine — false-positive catalog (2026-07-06)
The reference `md/md.xsd` rejects constructs the running engine accepts. Do NOT "fix" these on the schema's
say-so alone — check whether vanilla 9.0 `reference\` itself uses the same form:
- **mdscript `name` must match `[A-Z][A-Za-z0-9_]+`** (uppercase-first) per md.xsd — yet ATD ships
  `name="kuertee_atd"` (lowercase) and runs fine; the engine ignores the pattern. (Still, uppercasing your
  own script name, e.g. `ATD_Ejection_Router`, is a free way to pass the schema check.)
- `<orientation refobject= orientation="look_away">` inside `<create_ship>` — flagged, but vanilla 9.0 uses
  it in ~6 places (e.g. `gm_ambush.xml`). Valid.
- `<wait>` child of `<find_station>` — flagged, but vanilla `order.plunder.xml` uses it. Valid.
- Conversely, REAL 9.0 breaks md.xsd catches correctly: `<write_to_logbook>` now REQUIRES `title=` (83/83
  vanilla calls carry it); `<show_text>` is NOT a valid MD action (exists nowhere in vanilla — throws at
  load). Ground every xsd verdict against `reference\`, both directions.

### `//` vs `/` in diff XPath selectors
- `//conditions` matches ANY `<conditions>` element in the entire subtree — use when you know there's only one, or when you intend to replace all
- `/conditions` or `[@name='X']/conditions` matches only the direct child — safer for complex cue trees
- When in doubt, use the fully-qualified path to avoid unintended matches in nested cues

### `set_owner` behavior on player ships
`set_owner` changes the owning faction of a ship/station. Side effects:
- Triggers economic recalculations for both old and new faction
- With `overridenpc="true"`, bypasses normal NPC resistance checks
- Ships under a faction with `behaviourset="default"` will receive AI orders
- The `faction.player` faction is special; ships under it are player-controlled
- Transferring player ships to a custom hidden faction (`tags="hidden"`) removes player UI control but doesn't destroy the ship

### Entity blackboard vs cue namespace
- `player.entity.$key` — persisted on the player entity, saved to save file. Use for data that must survive game reload.
- Cue namespace variables (`$myVar` inside a cue) — also saved to save file when the cue is active.
- Always clear entity blackboard entries you no longer need (set to `null`) to avoid stale refs.

---

## Version Migration Map (pre-9.0 → 9.0)

Backbone for `/x4-update-mod` (later phase). Two detection tiers:

### Tier 1 — File-detectable (XSD validation, VERIFIED viable)
Validate mod MD/aiscript files against the **bundled** schemas `reference\libraries\{common,md,aiscripts}.xsd` via lxml `etree.XMLSchema`. (~100s one-time compile, then 1-12ms/file; cache the compiled schema; objects aren't picklable — **verified 2026-08-09**, `pickle.dumps` raises TypeError — so on-demand only, NOT the per-edit hook.)

> ⚠ **CORRECTION (measured 2026-08-09).** This entry used to say the compile is slow "because they
> include the 40k-line common.xsd". **That is false.** Measured: `etree.XMLSchema(common.xsd)` =
> **0.03 s** (1660 KB!), `md.xsd` = **98.55 s** (190 KB), `aiscripts.xsd` = **122.15 s** (151 KB).
> Size is not the driver. The cost is libxml2 building a content-model automaton for the
> **recursive `actions` group** — referenced 10× in `md.xsd`, and MD actions nest inside
> `do_if`/`do_all`, so the particle automaton explodes. Consequence worth knowing: adding elements
> to a *flat* schema is cheap; anything that deepens a recursive content model is not.
>
> ★ **The gating class needs no compile at all.** `"attribute X is required but missing"` — the only
> reliable 9.0 migration signal (Tier 1 below) — is a flat fact per element, extractable by plain
> `etree.parse` in **~0.05 s**. `x4validate` now does exactly that (`_xsd.required_attr_table`,
> always-on; `--xsd-fast` skips the compile entirely, 112 s → **2.5 s** on a real mod). Equivalence
> with libxml2 on that class is proven corpus-wide by `gates/xsd_fast_parity.py`, not assumed — its
> first run caught 226 false positives from walking `<diff>` files the compiled path never validates.
> **Caveat: 24 element names are declared with conflicting required sets** (`ware` requires nothing
> in one context, `ware` in another), so the table takes the INTERSECTION and can only under-report. Schema self-declares via root `<aiscript>`/`<mdscript>` + `xsi:noNamespaceSchemaLocation`. lxml catches the break exactly: `Element 'find_station': The attribute 'space' is required but missing`.
- **`space=` now REQUIRED on a whole family** (common.xsd): `find_station`, `find_station_by_true_owner`, `find_ship`, `find_object`, `find_gate`, `find_highway_entry_gate`, `find_highway_exit_gate`; `count_{gates,objects,ships,stations}`; and every `set_space_*`/`reset_space_*` (faction logic, economy, security, jobs, sunlight, location tags). Fix: add `space="..."` (zone/sector/cluster/galaxy; galaxy-wide = `space="player.galaxy"`).
- **⚠ md.xsd is STRICTER than the engine — CATEGORIZE XSD results, don't gate** (discovered 2026-06-22 running `x4validate --update` on *working* ATD: 14 schema "errors" yet the mod loads+runs on 9.0). The **only reliable migration signal is `"attribute X is required but missing"`** (the `space=` family — the loader enforces required attrs). FALSE POSITIVES the engine tolerates: **name-pattern facets** (md.xsd demands `[A-Z][A-Za-z0-9_]+` script/cue names, but lowercase `kuertee_atd`/`kATD`/`onDropDownConfirmed` work fine) and **`"attribute not allowed"`** (`debug_text/@exact`, `owner/@faction`, `create_ship/@position|@rotation`, `create_mission/@object` — md.xsd is incomplete; key/identity-constraint errors cascade from the name facet). x4validate's `check_xsd` **gates** (`error`) the **`required but missing`** class (loader enforces) AND **`element not expected`** (an action absent from the engine's schema → likely removed/renamed; for a migration tool, safer to flag than miss); attribute-not-allowed + name-facets + key cascades are `xsd-strict` advisories. **Nothing is hidden** — advisories are still reported; categorization only sets severity/exit-code. The **Migration Map + an in-game `debug.txt` run remain the authority** on what truly breaks; XSD is a categorized detector, not the final word.
- Future required-attr/removed-action shifts are auto-discoverable by **diffing old vs new XSDs** (the stewardship loop).

### Tier 2 — Runtime-only (grep-heuristic + debug.txt; NOT in schemas)
- **SirNukes `Lua_Loader` is DEAD** — `<raise_lua_event name="'Lua_Loader.Load'">` no longer functions. Load UI Lua natively via `ui.xml` + call `ModLua.init()` yourself (see 2026-06-22 Session 4 log).
- **`kHUD` is now a GLOBAL** in UIX `menu_toplevel.xpl` (standalone `kuertee_hud` module deleted).
- **`.keys.list.clone` deprecated → `.keys.list`.** Same family: **`.keys.list.count` → `.keys.count`** (engine emits a non-fatal "inefficient lookup pattern" warning, not an error, naming the exact replacement).
- **Protected UI Mode** must be OFF for UI-extension mods (`<uisafemode>false</uisafemode>` in profile `config.xml`, toggled in-game).
- Core DATA libraries (wares/jobs/god/factions) are schema-STABLE — data mods port easily; breakage concentrates in scripts + Lua/UI.
- **9.0 expression-grammar breaks — NOT visible to XSD, only to a live debug.txt load** (found porting `escape_pod`, 2026-07-06):
  - `$list.{random(1,$list.count)}` (the old `random(min,max)` call form) → `'}' expected` parse error. Fix: `$list.random` (vanilla's own idiom for "pick one element", used 12+ times in `fight.attack.object.*`).
  - A format string missing the required `.` before its substitution list — `'fmt'[args]` → `Operator expected`. Must be `'fmt'.[args]`. (Author typo, not itself a 9.0 change, but 9.0's parser now rejects it where 8.0 apparently didn't.)
  - A bare `{a, b}` used as a **list literal** (e.g. as `do_for_each ... in="{a, b}"`) now parses as a `{page,line}` textref reference first → `TextDB page ID expected`. Fix: use `[a, b]` (square brackets) for list literals — confirmed against vanilla `order.mining.routine.xml:788` / `trade.find.commander.xml:288` (`do_for_each ... in="[class.production, class.buildmodule]"`). **This is a silent-until-runtime break**: it doesn't error at load, only when the cue actually executes the malformed expression (yields `null`), producing `Evaluated value 'null' is not a list, group or table` at the `do_for_each`/`do_all` that consumes it — check debug.txt for this exact message, not just load-time `[=ERROR=]` lines.
- **These expression-grammar breaks are now AUTO-DETECTED by x4validate** (v1.2, 2026-07-06): the always-on `_exprlint` heuristic flags the `random(` call form, `'…'[` missing-dot, `in="{…}"` list-literal, and `.keys.list.count` (advisory/`warn`, 0 false positives across the whole installed corpus — it skips `sel=`/`if=` XPath). But a heuristic only knows *patterns*; the authoritative check is **`x4validate <mod> --debug <profile>\debug.txt`**, which folds the engine's own `[=ERROR=]` lines for the mod into the report and **gates** — it parses all 4 log shapes incl. runtime `Error in MD cue md.<Script>.<Cue> … * Action: …, line N` (resolved script-name→file), so it catches the `'null' is not a list` runtime error the static passes can't. **Run `--debug` against a log captured AFTER your fixes** (a gate on a stale log = false failure).

### Ship/flight/shield mechanics timeline, 7.x → 9.0 (researched 2026-07-24, multi-source)

**Correction to a natural assumption:** finding `<jerk>`/`<steeringcurve>`/`<accfactors>` missing from
a pre-9.0 ship macro does NOT mean 9.0 added them — that flight-tuning schema is from **7.50** (the
"Flight Model Update," beta Dec 2024 / released 2025-02-20), not 9.0. A ship mod predating 7.50 will
be missing this whole block; that's a 7.50-era port gap, not a 9.0 one. Source:
[wiki.egosoft.com Modding Support/Breaking Changes](https://wiki.egosoft.com/X4%20Foundations%20Wiki/Modding%20Support/Breaking%20Changes),
[Steam FAQ for the Flight Model Update](https://steamcommunity.com/games/392160/announcements/detail/509572974349651421),
[JPMFlight schema guide](https://wiki.egosoft.com/X4%20Foundations%20Wiki/Modding%20Support/Assets%20Modding/Guides/JPMFlight/).

| Change | Version | Confidence | Notes |
|---|---|---|---|
| `<jerk>` (forward/forward_boost/forward_travel/strafe/angular) + `<steeringcurve><point>` + `<accfactors>` added to ship macros | **7.00 Beta 7 → matured in 7.50** | high | NOT a 9.0 change — see correction above |
| Boost gets its own energy pool (previously drew from shields) | **7.50** | high | |
| Travel-drive charge-time/speed rebalanced per race/engine | **7.50** | high | Terran fastest charge, Paranid fastest top speed |
| 90+ shields rebalanced; new "shield modifiers" (capacity/recharge bonus on certain hulls) | **9.0** | high | Egosoft's own Beta 1/final notes |
| L/XL shields have a regen-delay mechanic | **9.0** | **CONFIRMED 2026-08-02** | Measured over every `shieldgenerator` macro in `reference\` (base + 6 DLC): **all four sizes carry `<recharge delay=…>` > 0** — S 34/34 (2–18.5 s), M 43/43 (2.5–16.6 s), L 22/22 (3–19 s), XL 13/13 (3–19 s). The old "previously S/M only" framing is wrong for 9.0; delay is universal. **But see the VRO row below — VRO strips it from S/M.** |
| "Travel Drive Stability" — ships absorb some hits before being knocked out of travel (previously any hit ended it) | **9.0** | medium-high (existence) / medium (mechanism detail) | |
| Collision-shape re-export required; S/M ship models resized (engines/shields moved INTO hull mesh) | **9.0** | high | the actual 9.0 ship-porting breaking change — not flight tuning |
| AI capital-ship movement/station-avoidance tuning | **9.0** | high | AI/piloting, not player-facing physics (drag/mass/thrust unchanged) |
| **VRO's "internal shield" mechanic** | never vanilla, any version | confirmed | VRO-only feature, removed in VRO 5.01 — see below |

**Practical implication:** a ship failing to load or behaving oddly under 9.0 is much more likely a
collision-shape/model-resize issue than a missing flight-tuning block (that schema's been stable
since 7.50). For ground-truth numeric deltas (exact shield rebalance values), diff a pre-9.0 vs
current `reference\` macro directly — prose changelogs don't carry the numbers.

### VRO-specific 9.0 shifts (VRO 5.01 / the 9.0 line)

**Standing baseline rule (user-set 2026-08-02): for anything weapons / engines / shields / missiles,
VRO 5.01 IS the baseline, not vanilla.** VRO is a total overhaul and is always in the modlist, so a
vanilla-only number is provenance, never a verdict. Quote vanilla *and* VRO (Three Values Rule).

- ✅ **`x4effective` under-reported VRO for months — FIXED 2026-08-08 (`72aea46`).** Root cause was
  NOT case-folding (an earlier entry here said so; that was wrong and unverified). It was
  `_merge._do_replace` dropping any `<replace>` whose selector resolved to the **document root** —
  i.e. VRO's `<replace sel="//macros">` whole-file override idiom — while `apply_diff` still
  reported the op applied. **858 ops** were affected: `vro` 848 (units 266, weaponsystems 220,
  engines 159, weaponfx 104, surfaceelements 101), `propersized_missile` 9, `code_vgr_battleship` 1.
  After the fix VRO went from **0 → 101** owned `shieldgenerator` entities.
  **`x4compat` was proven unaffected** — same modlist before/after gave 419 rows, 0 added, 0
  removed, **0 winner changes** — because collision topology and load-order winners do not depend on
  whether a value landed. Values-based tools (`x4effective`, `x4stats`, balance work) were the ones
  reading vanilla where a mod had overridden.
  - Case variance is still real but is a **portability** matter only: 491 VRO files and 101
    `pdrealisticboosters` files differ from vanilla paths by case. Windows and `_cat._get_ci`
    handle it; **Linux/Proton would not.**
- ✅ **Sibling defect, same family — NESTED cross-mod patches were invisible from the owner's-file
  door — FIXED 2026-08-11 (v2.2.1).** `build_effective` resolved `extensions/<owner>/<rel>` only
  when the *requested* vpath was the nested one; building the owner's PLAIN vpath (what the store
  does for every file) never probed later overlays for their nested form. Two doors to one logical
  document gave two answers: **Tier B said cpsdo_vro's 27 bullet overrides resolve, x4effective said
  cpsdo_zb_modpack owned every value — both were internally consistent and jointly false.** The
  engine has ONE document (F19), so the plain door was wrong. Measured on the corrected tree:
  **cpsdo_vro's weapon-fx half is FULLY LIVE** (27 diffs + 2 nested full overrides, all winning),
  and SVE-VRO's nested `<remove sel="//macros/macro[@name='tartarus_macro']"/>` really deletes the
  ship the old tree kept alive — any past x4stats/balance read of SVE or CPSDO content predating
  2026-08-11 is suspect. Full differential over the 114-mod install: 834 attr values, 27 entity
  origins, 60 phantom dupes, 21 remove-rows — **0 unexplained**. `x4compat` proven NOT blind (it
  aliases owner files under the nested key). **Double-nesting** (`extensions/<modA>/extensions/…`,
  a patch on another mod's patch file) is deliberately left at old behavior — engine handling
  unproven, and `ebi_m0_vro` ships both forms, so rewriting double-applied its ops.
  **Standing lesson: when two of our own tools disagree about the same value, that disagreement IS
  the finding — chase it before using either answer.**
- **VRO REMOVES the S/M shield regen delay that vanilla 9.0 has (measured 2026-08-02, RE-CONFIRMED
  2026-08-08 by direct `_cat` read of VRO's diffs — `shield_arg_s/m_*` delay=0, `shield_arg_l/xl_*`
  delay=10, `shield_kha_*` delay=2).** Counting
  `shieldgenerator` macros with `<recharge delay=…>` > 0: vanilla S **34/34** and M **43/43**; VRO
  S **1/24** and M **3/44**. L and XL keep it in both (VRO L 22/22, XL 11/11, delay 5–20 s). VRO
  shields are also much larger at those sizes (median capacity VRO S 3,443 / M 15,300 vs vanilla
  1,259 / 6,000), so the missing delay compounds. Any "shield regen cooldown for S/M" work is
  therefore a **VRO regression repair**, not a preference — and a diff written against vanilla's
  values will silently miss.
- **VRO travel-engine profile differs by size (measured 2026-08-02).** Median travel thrust
  multiplier — vanilla S 11.0 / M 8.0 / L 28.3 / XL 25.4; VRO S 14.4 / **M 19.8** / L 30.0 / XL 30.0.
  So VRO makes **M faster than S** (vanilla is the reverse) and **ties L with XL** (vanilla favors L).
  VRO expresses the size trade through charge time instead: S/M 1 s, L 8 s, XL 15 s. NB these are
  thrust multipliers, not m/s — final speed needs thrust × multiplier ÷ drag per ship.
- **VRO sets radar per-ship, not globally.** Its `libraries/defaults.xml` is a diff patch with **zero**
  radar elements; instead 54 ship macros carry their own `<radar range=…>` (e.g. Argon destroyers
  50,000 m, Scylla 60,000 m, Ariadne 55,000 m) against vanilla's 40,000 m default. Removing VRO's
  radar changes drops those 54 ships to the vanilla default — targeted, not sweeping.
- **VRO adds 43 missiles on top of vanilla's 41** (62 total) including a **cruise class that does not
  exist in vanilla** (`missile_cruise` / `missile_xen_cruise`, 30,000 m). Vanilla's longest guided is
  39,000 m; VRO's is 30,000 m. Within VRO alone, torpedoes cap at 13,000 m — below its own 20,000 m
  L beams.
  - ⚠ **CORRECTION (2026-08-08): do NOT quote the VRO-only figures as the game's missile ladder.**
    The live modlist has **124 effective missiles from 7 sources**, and the VRO-only picture is
    badly unrepresentative: `propersized_missile` adds **30,000 m torpedoes** (`missile_gen_l_torpedo2/3_01_mk1`,
    30,000 dmg, hull 300), `xspvro`'s `xen_cruise` reaches **60,000 m**, and `cpsdo_zb_modpack`
    contributes **33 missiles** including one at **80,000 m / 10,000,000 damage**. Effective spans:
    torpedo 3,000–30,000 m, cruise 14,000–60,000 m. Any missile-balance claim must come from the
    **effective store**, not from VRO+vanilla raw files.
- **Internal shields (`ishield_*`) REMOVED from VRO core (verified 2026-07-19).** Older VRO added an
  "internal shield" mechanic — extra shield generators mounted as internal surface elements
  (`ishield_*_macro`, class `shieldgenerator`). VRO 5.01 dropped it: **0 `ishield_` references in
  `extensions\vro\ext_01.cat`; 0 in vanilla 9.0 reference.** Consequence for porting: any ship/patch
  mod built for old VRO that ships `ishield_*` macros is now patching a **dead mechanic** — those
  files are vestigial (they define generators nothing mounts). This is a recurring, high-volume
  obsolescence signal when recovering pre-9.0 VRO content.
  - Quantified on the user's own recovery corpus: `mas_ror_vro_patch` = **53 of 54 files** are
    `ishield_ror_*` (≈98% obsolete for 9.0); `masvro_submod` = **155 of 397** (~39%); the `zMAS191`
    capstone = **0** (weapons/bullets/mines — survives intact). Ship-addon mods still shipping
    `ishield` in the effective tree today (advisory, they still load): `ebi_m0_vro` (1), and CPSDO's
    own **8.1**-era `cpsdo_vro` submod (18) — CPSDO's VRO patch predates the removal too.
  - **Detection idiom:** `uv run x4effective sql "SELECT name,origin FROM entities WHERE name LIKE
    '%ishield%'"` (current effective tree) or `grep -c ishield_` a mod's cat/loose files.
  - Regular (non-internal) shields — the shared `shield_*_macro` in `assets\props\SurfaceElements\
    macros\` — are UNAFFECTED; see the Mechanics Interlock table below.

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

*Proposed new hooks — log here proactively, implement when patterns emerge.*

- Consider adding protection for `debug.txt` — should never be edited (read-only log)
- Consider a hook that warns when editing a file that already has a diff patch in dev\ (to avoid overwriting work)

### ✅ IMPLEMENTED 2026-08-22 — three measurement-instrument traps, in `protect-bash.sh`

Prompted by CLAUDE.md #22: **10 of 10 checking-step bugs across three sessions were the CHECKER, not
the finding**, and three of them in one session were plain shell artefacts. Prose had already been
tried and failed — #20 sat in always-in-context text and the double-count still recurred twice in one
session — so the two textually-detectable traps got a tripwire.

| rule | decision | why that decision |
|---|---|---|
| `$?` read after a pipeline | **ask** | heuristic over shell text; sub-90% confidence buys a MEASUREMENT, not a gate |
| measurement output redirected into `/tmp` | **ask** | `/tmp` is shared across concurrent sessions — a parallel session's 4-hour-stale files were once nearly reported as this session's results |
| recursive search rooted AT the workspace / game root | **deny** | it does not finish: `grep -r` killed at **300 s**, ripgrep timed out at **20 s**, because `tools\basex\basex\data\` alone is GBs of binary pages. The existing rule covered only `reference\` |

**Two things this build taught, both worth more than the rules themselves.**

1. **The first draft of the `$?` rule FALSE-FIRED** on `cat >> f.md <<'EOF' | a | b | EOF; echo $?` —
   a markdown table inside a heredoc, a shape used constantly here. It would have misfired on my own
   work repeatedly. Caught by probing **must-NOT-fire** cases *before* wiring anything in. Fixed by
   stripping heredoc **bodies** first, then quoted strings, and only then looking for a pipeline.
   Final probe: 16/16 adversarial cases, 0 false positives.
2. **The rule cost ~195 ms (+59%) on EVERY Bash call**, because the `awk` that strips heredocs ran
   unconditionally. MEASURED against the pre-change hook — a total, not a guess. Gating it behind one
   cheap `grep -q '\$\?'` (most commands contain no `$?` at all) took it to **389 ms → 388 ms**.
   *A guard that taxes every call is a cost you pay forever; measure it against the version you replaced.*

**The hook now has a regression test: `.claude\hooks\test-protect-bash.sh`** (26 checks, 0 failures)
covering must-fire, must-stay-quiet, the pre-existing rules, and **fail-open on junk input** — a hook
that wedges the Bash tool is the one failure mode worse than no hook. Run it after ANY hook edit.
Its own first version reported 7 spurious failures because a silent hook emits no stdout and
`jq '... // "allow"'` over empty input yields empty — the harness was wrong, not the hook. Again.
### PROPOSED 2026-08-26 - a WRITE that flips a file's line endings

**Prompted by it happening TWICE in one session, the second time inside the script that was
documenting the first.** CLAUDE.md #22 is now at **58 of 58 checking-step bugs being the CHECKER**,
and two of the four added that day were this one shape.

| when | what it did | how it was caught |
|---|---|---|
| #52 | `Path.write_text` turned three LF source files fully CRLF - **F53's exact defect**, reintroduced by a repair script | git's own `warning: CRLF will be replaced by LF`, then a byte count |
| #57 | editing `CLAUDE.md` flipped **all 711** of its line endings - a **1,422-line diff for a 2-line change** | a backup taken first, and *expecting a specific diff size* |

**Why it is worth mechanizing rather than remembering:** the lesson was written down between the
two occurrences and did not prevent the second. That is the same argument the 2026-08-22 block
makes about #20 - prose in always-in-context text failed, so the trap got a tripwire.

**Why it is a good hook candidate specifically:** it is *cheap and exact*. Unlike the heuristics
above, this needs no guessing about shell text - a PostToolUse hook on Write/Edit compares the
file's CRLF/LF profile before and after and warns only on a **flip**, which is a pure byte count
with no false-positive surface.

⚠ **Heed the two lessons the 2026-08-22 build paid for.** (1) Probe **must-NOT-fire** cases first:
a file that is legitimately being converted, a brand-new file with no 'before', and this very KB,
which is **MIXED** (5,396 CRLF + 175 LF-only) and must not be reported as flipping every time
anyone appends to it. (2) **Measure the per-call cost against the version it replaces** - the `$?`
rule cost +59% on every Bash call until it was gated behind one cheap grep.

**Considered and NOT proposed:** a rule for backticks inside a double-quoted Bash string (#58,
which blanked two words and still reported success). Backticks are common and legitimate in this
workspace's markdown-heavy commands, so the false-positive rate would be high and the shape is not
reliably detectable from text. The durable mitigation there is behavioural and already recorded:
**write file content from a FILE, never an inline interpreter string, and read the sentence back.**

- x4validate ENHANCEMENT (not a hook): teach it to resolve cross-mod patch targets (load installed extensions into the tree) so a diff targeting another mod's file gets real `sel=` checking instead of a "no base game file" false error. Until then, cross-mod patches need a manual lxml sel-check (see the diff-patch section).

---

## Session Log

*Add brief per-session notes here — what was investigated, what was learned. Starts empty in
a fresh install; grows as you and Claude work together.*

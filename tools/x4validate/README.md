# x4validate

Cross-file validator for X4 Foundations mod diff patches. Built because no
off-the-shelf tool reproduces X4's *effective merged tree* + typed reference
graph (and x4cat's `validate-diff` false-negatives the `//` selector idiom —
see KNOWLEDGEBASE.md "Tool Evaluation").

It answers the three questions that matter when one logical change fans out
across many files:

1. **Will this patch silently do nothing?** — every `<add>/<replace>/<remove>`
   `sel=` (and `if=`) is evaluated against the real base+DLC merged tree (via
   lxml — correct XPath, unlike ElementTree-based matchers).
2. **Do the references resolve?** — ware / `{page,t}` / macro / component
   references must point at a real definition. Two scopes: what the mod
   *introduces* via `<add>` ops in `<diff>` files **gates as an error**, while
   references in **full (non-diff) files** report as INFO for now — that half was
   unchecked entirely until 2026-08-13 (1,625 files across 56 mods, 38% of their
   XML). Definitions are **unioned** across base + DLC + mod: text defs from every
   English/language-neutral t-file at any depth (not a fixed two-path list), and
   macro/component names from `index/` ∪ the libraries ∪ — only on a miss — the
   whole corpus, because the index is *not* the definition set. `@ware` values
   that are script expressions (`$var`, `ware.x`) are excluded and counted.
3. **Did I forget a spot?** — completeness: model a changed entity on a vanilla
   analogue and report which footprint pieces are missing.
   ⚠ **Scope: `<ware>`-WRAPPER fields only** (definition, name/description strings,
   price, production, `<component ref>`, owner, restriction). `ship` and `module`
   targets route through the same check, so the macro's INTERIOR — physics,
   connections/hardpoints, engine/shield/turret slots, storage, hull, software,
   steering curves — is never inspected. A clean completeness result does **not**
   mean the macro is complete; the run says so via a NOT CHECKED entry.

v1.1 adds: **file-existence** (a `<component ref>` macro resolves through
index→macro file→component→file), **connection-validation** (every `<loadout>`
`path` matches a `<connection>` on the ship's component), **variant-set
consistency** (patched `_a` but not its base `_b`/`_c` siblings → warn),
**page-id collision** (added `{page,t}` already in base/DLC → warn), and a
**`--file` fast mode** (sel-resolution for one edited file, for the per-edit hook).

v1.2 closes the **expression-grammar gap** — the XSDs validate XML *structure* but
treat every attribute *value* as an opaque string, so a broken script expression
(`random(1,n)`, `'…'[…]` missing the dot, `{a,b}` list-literal) sails through schema
validation and only fails when the engine parses it at load. Two complementary layers:
- **`_exprlint`** (always-on, *advisory*): a measured regex heuristic over attribute
  values, seeded from the KB Version Migration Map (0 false positives across the whole
  installed mod corpus). Flags the known-broken forms; never gates (it's a heuristic).
  Skips `sel=`/`if=` (those are diff XPath, a different grammar).
- **`--debug <debug.txt>`** (authoritative, *gates*): folds the engine's own `[=ERROR=]`
  lines for *this* mod into the report — load errors (by file path) **and** runtime
  errors (by script name → file, e.g. the `'null' is not a list` cue error). Engine
  errors gate the exit code; a clean static pass is necessary but not sufficient.

v1.3 adds **loader-sanity checks** learned from live debug logs: literal-newline
TextDB warnings in `t/` files, invalid `identification/@makerrace` values checked
against the effective `libraries/races.xml` race list, and non-identical engine
connection tag sets on a single component. These checks run against loose XML and
packed catalog XML through the shared CAT/DAT reader, with loose files overriding
packed members. Connection validation also uses this packed-aware XML iterator.

v2.01 adds **effective-schema validation for data files** (`--update`). 42 vanilla files
under `libraries/` declare a schema in `xsi:noNamespaceSchemaLocation`, and mods ship them
as `<diff>` — so the patch is not the thing to validate, the *merged document* is. This
catches a class nothing else here can: a diff whose selector matches and whose XML is
well-formed, but which leaves the merged document structurally broken (measured: a mod
that `<remove>`s `<production>` orphans the `<limits>` sibling 30 times).

It is **differential**, and that is not a refinement — it is the only form that works.
Egosoft's own base+DLC data fails Egosoft's own bundled schemas (66 errors across 6 files),
the same stricter-than-the-engine gap already known for `md.xsd`. So the tool validates the
tree *without* your mod, then *with* it, and reports only what you introduced. Enumeration
failures naming a race or faction your modlist actually defines are suppressed and counted
(the XSD list is a vanilla floor, not a closed set); one naming something nothing defines
is reported. Structural breakage gates; value-facet complaints are advisory.

## Usage

```sh
# from tools\x4validate\  (requires uv — https://docs.astral.sh/uv/ — which fetches Python 3.13)
uv run x4validate <path-to-mod-dev-folder>
uv run x4validate <mod> --entity ware:my_new_ware --like ware:ore   # completeness
uv run x4validate <mod> --json                                       # machine-readable
uv run x4validate <mod> --update                                     # + 9.0 XSD/migration/exprlint
uv run x4validate <mod> --debug                                      # correlate the active profile's debug.txt
uv run x4validate <mod> --debug path\to\debug.txt                    # correlate a specific log (gates on engine errors)
```

### `x4debug` — the engine's verdict, bucketed and compared to ours

```sh
uv run x4debug triage                      # bucket + attribute EVERY [=ERROR=] line
uv run x4debug crosscheck <deployed-mod>   # per-item diff: engine-skipped ops vs our predictions
uv run x4debug baseline                    # archive the log with a content fingerprint
```

### `x4save` — what a savegame bakes in, and what it would silently lose

```bash
uv run x4save info                         # header + the SAVE-BAKED extensions
uv run x4save check <save>                 # macro refs the live tree no longer defines
```

A save is the only artifact the ENGINE wrote, and it is cheap to read: the largest here
is 1.28 GB expanded and streams in **2.5s**. Two measured facts drive the output.

`<patches>` is **not** a record of what loaded — an extension appears iff its
`content.xml` `save` attribute is absent or `="1"`. MEASURED: **3 of 121 mods (2.5%)**.
It is the save-baked set, i.e. the removals that are dangerous.

And removing a mod leaves **no** dangling references — the engine deletes the orphaned
content **silently**. MEASURED on one removal: 37 macros went to 0, the engine logged
**one** error line naming a galaxy connection rather than any of the lost content, there
was no dialog, and the net error count went *down* because the mod's own errors left with
it. `check` is worth running precisely because `debug.txt` will not tell you.


`triage` states the log's mtime and whether it was a **new game** or a save load — error
counts are not comparable across that boundary — and its rows must sum to the lines read,
with the unclassified row printed **even when zero**. A row that appears only when non-zero
teaches you to read its absence as "nothing there" rather than "not measured".

`crosscheck` reports three buckets, never two totals. `observed-not-predicted` is a
**validator blind spot**, and is the reason the command exists: it is what found that a
diff's ops apply in order to a mutating tree (see `docs/BLIND-SPOTS.md`).

The expression linter runs on **every** invocation (cheap, advisory). `--debug`
is the authoritative gate — run it against a `debug.txt` captured *after* your latest
edits (a gate on a stale log is a false failure).

`--update` is deliberately slow: schema compilation dominates. Budget ~100s for the
md/aiscripts schemas, and a further **~122s if your mod patches `libraries/diplomacy.xml`**
— that one schema pulls in the 40k-line `common.xsd`, where every other data schema
measured ≤0.1s. It looks like a hang and is not.

**The cheap half of the script check runs by default**, since it needs no schema compile: the
required-attribute class — the KB's most reliable 9.0 migration signal — is checked on every run,
with corpus-wide parity against libxml2 proven by `gates/xsd_fast_parity.py` (555 script files, 0
false positives, 0 misses) and a measured cost of ~0.1s on the heaviest script mod in a 125-mod
install. What still needs `--update` is the `element not expected` class, where element-ordering
errors live, plus the schema-strict advisories — and a default run now says so by name rather than
reporting a bare "OK".

### `x4modlist changed` — which mod moved, when a fingerprint does

```sh
uv run x4modlist changed                       # vs the effective store (default)
uv run x4modlist changed --since latest --files  # vs the newest snapshot, naming files
uv run x4modlist snapshot --label pre-wave     # ~0.1s baseline, no rebuild needed
```

Every persisted artifact carries a two-axis fingerprint saying *when* it was true. When the
**content** axis moves, this says **what moved**: added / removed / version / content /
`touched` (rewritten with identical bytes) / `toggled` (enabled or disabled in the profile).

It exists because localising ONE changed mod once took nine investigative steps, and only
worked because that mod happened to bump its `version`. Three of those steps were the wrong
instrument — notably `find -newermt`, which is **structurally blind to a back-dated write**,
and the mod in question had back-dated all 26 of its files. Per-file identity is therefore
hashed as a **set** of `(relpath, mtime, size)`, never `max(mtime)`.

`snapshot` fills the gap between expensive rebuilds: the store and the xref index only
advance when something slow runs, so several days of drops otherwise collapse into one
unsequenced delta. Snapshots are named by **content**, so repeats of an unchanged world
collapse onto one file.

**A baseline with no vector exits 3 and says so.** Artifacts built before the vector existed
cannot answer "what changed", and reporting *no change* for one would be a wrong answer where
a non-answer is the honest one.

⚠ **Scope limit.** Per-file identity is `(mtime, size)`, not a content hash — hashing every
file would mean reading multi-hundred-MB `.cat` archives on every run. An edit changing
neither size nor mtime is invisible, and a same-size edit reads as `touched` rather than
`content`. Manifests *are* hashed. `--usn` adds NTFS change-journal corroboration (immune to
back-dating and to NTFS tunneling) but needs an elevated shell, so it degrades to a message
rather than failing.

⚠ MEASURED on an unelevated shell: **`fsutil usn queryjournal` SUCCEEDS while
`fsutil usn readjournal` returns `Error 5: Access is denied`.** The probe therefore tests
`readjournal` — the operation actually needed — because probing with `queryjournal` reported
the journal as readable when it was not. A tool claiming a capability it lacks is the
false-positive this package exists to refuse.

### Exit codes

| code | meaning |
|---|---|
| **0** | clean — and something was actually examined |
| **1** | error-level findings (use as the pre-deploy / pre-pack gate) |
| **2** | could not run: bad path, missing reference tree, usage error |
| **3** | **degraded** — a check you asked for could not run, so a clean result proves nothing |

**3 is separate from 1 on purpose:** a gate needs to tell "your mod is broken" from "the validator
was blindfolded". Cases that reach it: no `content.xml` (X4 would never load the folder), a packed
mod whose catalog will not open, an overlay that would not parse so the comparison tree is
incomplete, or a `--like` analogue that does not exist.

A mod with **no `<diff>` files is not degraded** — additive-only and asset-only mods are normal and
are reported as notes. Measured on a ~120-mod install: 16 additive-only, 1 asset-only, 0 unreadable.

Every run states its denominator (`sel-resolution: N diff file(s) checked across M payload XML
file(s)`), because "checked 14 files, all fine" and "checked 1 file, all fine" must not print the
same way.

Default merge tier is **A** (base + DLC, deterministic); `--tier b` also folds in enabled mods but
warns, because X4's inter-mod load order is undocumented.

## Configuration — where it looks for things

Run **`x4validate --paths`** to see what resolved, and which config file was read.
Do that first whenever a result looks impossible: silent misconfiguration is this
tool's worst failure mode, because "found nothing" and "looked in the wrong place"
print the same way.

Every location resolves in **layers** — for each one, all aliases *and* derivations
in a layer are tried before dropping to the next:

1. **Environment.** The installer's names first — `X4_GAME`, `X4_EXTENSIONS`,
   `X4_PROFILE`, `X4_MODS`, `X4_REFERENCE`, `X4_DEBUGLOG` — then the older
   `X4_GAME_ROOT`, `X4_GAME_EXTENSIONS`, `X4_PROFILE_CONTENT`,
   `X4_PROFILE_EXTENSIONS`, `X4_WORKSHOP_CONTENT`, `X4_REGISTRY`.
2. **`.claude/x4-paths.env`** — the file `install.sh` / `install.ps1` write. Found via
   `$X4_TOOLKIT`, else by walking up from the current directory.
3. `_paths._LOCAL_FALLBACK` — deliberately empty; the documented seam for a local
   override, so nobody hardcodes one somewhere else.

**Set `X4_TOOLKIT` in your user environment yourself** — the installers write it
*into* `x4-paths.env` but do not export it, so nothing sets it for you:

```sh
setx X4_TOOLKIT "C:\path\to\toolkit"           # Windows (new shells only)
echo 'export X4_TOOLKIT=/path/to/toolkit' >> ~/.bashrc   # Linux / macOS
```

Without it, resolution depends on walking up from the current directory — and the
CLI and gates are often run from the game folder, which has a `.claude/` but no
`x4-paths.env`. You would get `(unresolved)` locations with a perfectly good config
file sitting one directory tree away.

Prefer the **installer names**. The two schemes exist because until v2.01 the
installers wrote one set and the Python read another, overlapping on a single name
(`X4_REFERENCE`) — so a successful install still left every cross-mod command
pointed at CWD-relative paths. The old names keep working; they are not the ones to
teach.

Values may reference each other — `X4_REFERENCE="$X4_TOOLKIT/reference"` and
`${X4_TOOLKIT}/reference` both expand, matching what the shell half does with the
same file. The file is parsed, never executed, so only `$VAR` expansion happens: no
command substitution, no subshell.

**Git Bash / WSL drive paths are translated on Windows.** `install.sh` writes
`/c/Program Files (x86)/...` under Git Bash; `/c/...` and `/mnt/c/...` become
`C:/...` so Python can open them. On Linux those are left exactly as written,
because there they are legitimate absolute paths.

Derived when not set explicitly: `$X4_GAME/extensions`;
`$X4_PROFILE/{content.xml,extensions,debug.txt}`; `$X4_MODS/_registry/modlist.yaml`;
and the Steam workshop directory from `steamapps/common/<game>` — **only** when the
install really has that shape, since a guessed path scans nothing and would report
"no mods" as though it were a finding.

Nothing is guessed: an unresolved location prints `(unresolved)` and the run says so
rather than quietly substituting a default. `$X4_NEXUS_KEY` is deliberately NOT
handled here — it is a secret, not a path, and must never be written to a file.

## Layout
- `x4validate/_paths.py` — path resolution (the layers above) + `--paths` report.
- `x4validate/_merge.py` — effective-tree assembly (diff apply: add/replace/remove,
  pos/if/silent; full-file override by root element).
- `x4validate/_xpath.py` — lxml XPath wrapper (genuine no-match vs invalid-expr).
- `x4validate/_refs.py` — reference graph, dangling-ref detection, completeness.
- `x4validate/_exprlint.py` — expression-grammar heuristic (attribute-value rules).
- `x4validate/_debuglog.py` — `debug.txt` parser. 7 mod-identifying shapes (incl. diff-op
  cardinality and index-lookup misses) plus 17 engine-SUBSYSTEM shapes that name a game
  entity rather than a mod. `parse_log` accounts for every `[=ERROR=]` line: classified,
  or labelled `unclassified` and counted — never dropped.
- `x4validate/_debugcli.py` — `x4debug`: triage / crosscheck / baseline.
- `x4validate/_savecli.py` — `x4save`: savegame header + save-vs-live-tree
  reference check. Streams gzip; never builds a tree.
- `x4validate/_freshness.py` — the two-axis fingerprint every persisted artifact carries, and
  the per-folder **content vector** it is folded from. Deliberately NOT in `ENGINE_SOURCES`:
  widening the content axis must not claim the merge code changed.
- `x4validate/_changed.py` — `x4modlist changed` / `snapshot`: localise a moved fingerprint by
  diffing two vectors instead of investigating. Owns no enumeration of its own.
- `x4validate/_xsd.py` — schema validation: script files as written, data files as merged
  (differential — see `introduced`).
- `x4validate/_check.py` — orchestration + t-file union; `_cli.py` — CLI.
- `tests/` — `uv run pytest` (616 tests as of v2.5.0, incl. the x4cat spike cases).
- `gates/` — measured against the engine / the real modlist, not fixtures. Four engine
  gates: `oracle.py` (diff layer, 0 FALSE OK), `oracle_index.py` (index layer),
  `regress.py` (per-mod Tier A/B sweep), `schema_sweep.py` (effective-schema
  composition), plus `oracle_reverse.py` (the direction the first two cannot test:
  the engine complained — do we notice?). Plus nine corpus audits added in v2.1.0 —
  `noop_audit.py` (reported ≡ actual, per op), `provenance_audit.py` (a changed value
  names its mod), `consistency_audit.py` (store ≡ merge ≡ dump), `corpus_sweep.py`
  (every installed mod, both tiers), `qa_sweep.py` (every CLI × subcommand),
  `edge_sweep.py` (hostile inputs), `reader_edges.py` (damaged archives/encodings),
  `determinism_audit.py` (identical input ⇒ identical output), `mutation_probe.py`
  (break it and require the suite to notice), `fuzz_diff.py` (random legal ops vs
  invariants) and `stress_sweep.py` (unseen corpora, chained tools, pathological XML).
  v2.1.1 adds eight output-truth and parity gates — `tool_properties.py` (properties for
  the thinnest-covered tools), `cross_tool.py` (two tools must agree; a planted delta must
  be detected), `diff_truth.py` (planted mutations, reported exactly), `similar_audit.py`
  (every pair recomputed), `update_corpus.py` (every documented 9.0 break planted and
  found), `xsd_fast_parity.py` (the fast path must be set-equal to libxml2, corpus-wide),
  `perf_guard.py` (per-mod runtime, never an aggregate) and `nexus_fixture.py` (the
  network path, replayed offline).
  v2.2.0 adds `registry_provenance.py` (a guessed mod identity may never produce a
  confident verdict).
  **26 in total.** See `gates/README.md` for the bar each one holds.
- `docs/TRUST.md` — **start here if you are deciding whether to rely on this.** Every
  defect *shape* ever found in the toolkit, the measured cost when it happened, and
  the test or gate that now bans it — so *"is this shape guarded?"* is a lookup, not a
  matter of confidence. It also states plainly where the tools cannot be trusted.
- `docs/QA-PROCESS.md` — the process these gates came out of: what to test, in what
  order, and when it is honest to call a tool releasable. Read it before adding a tool.
- `docs/BLIND-SPOTS.md` — the narrowing-point register: every place a step could
  narrow the data and report success anyway, each with a **measured denominator** and
  an explicit STATE (re-verified against the code 2026-08-22). Includes the findings
  that turned out **not** to be defects — a register without its negatives has no
  denominator either.
- `CHANGELOG.md` — starts at **2.3.0**. Read the 2.3.0 entry before upgrading: it
  carries a **breaking change to `x4compat --json` output** (SUBTREE rows no longer
  populate `winner`; use `wiped_by`, or `live_value_owner()`) shipped under a minor
  version bump, so the version number alone does not warn you.

## Extending
Add reference types by extending the catalog in `_refs.py`; add completeness
recipes per content type (ship, module, …) alongside `ware_completeness`. Add an
expression-grammar rule by appending to `_exprlint.RULES` — **measure it against
vanilla `reference\` first** (a rule that flags valid code is dropped, not shipped;
see the removed `{a.b, c.d}` catch that fired on valid `.{[list]}` accessors).

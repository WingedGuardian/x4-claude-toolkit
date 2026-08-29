# Changelog

## Unreleased

### Added — the BaseX builds name the engine tree they used, and refuse an ambiguous one

`build-effective.sh` and `build-corpus.sh` defaulted `X4VALIDATE_DIR` to `$HERE/../x4validate`.
That is a *position*, not an identity. The freshness `engine` axis hashes the bytes of the engine
sources, so when more than one checkout sits side by side — one git worktree per concurrent
session — a build can stamp the artifact with a different tree's engine hash. A wrong engine hash
reads as **fresh**, not as an error.

Both builds now print the resolved tree with its git branch and HEAD, every run. That half has no
failure mode: a build whose provenance is in its own output can be audited afterwards.

The refusal fires **only** when the choice is genuinely ambiguous — more than one sibling that
actually contains `x4validate/_merge.py`, and no `X4VALIDATE_DIR`. A single-checkout install can
never trip it, and a stray `x4validate-backup/` is not mistaken for a rival.

### Changed — a deployed-mod edit is a hard block when the source lives elsewhere

Writing to a file under the live `extensions/` folder used to always ask. It now depends on
whether a source copy exists somewhere else, because that is what decides whether the edit is
recoverable:

| your setup | writing under `extensions/` |
|---|---|
| a separate mods root outside the game folder | **denied**, naming where the source is — every deploy overwrites this copy, so the edit would be silently lost |
| mods root IS the extensions folder | **allowed** — the deployed copy *is* the source; this is ordinary work |
| no mods root configured | **ask** — nothing says where the source is, so it cannot be decided for you |

All three branches have their own probe. The first two are reachable only in different
configurations, so testing one of them would have left the others as dead code.

### Fixed — `scripts/test-hooks.sh` counted a dropped probe as no probe at all

A probe line that fails to parse increments neither the pass nor the fail counter: it vanishes,
and the run still prints a cheerful total. That happened while adding the probes above — bash
printed `n: command not found` and the suite reported `33 passed, 0 failed`. The total is now
asserted against an expected count that has to be updated deliberately.

### Added — `X4_BACKUPS` documented in `x4-paths.env.example`

`backup-before-edit.sh` has always honoured it; nothing said so. It matters when the toolkit root
is not where an existing audit trail lives, because otherwise changing `X4_TOOLKIT` quietly starts
a second trail and the history splits in two.

### Changed — the advisory validate hook routes cross-mod files to Tier B

A file at `<mod>/extensions/<target>/...` is a cross-mod patch, and Tier A builds base+DLC only,
so it reports "no base game file — can never apply" for every such file. Measured on a real
cross-mod overlay: Tier A `error_count=1`, Tier B `error_count=0`, same correct file. Left on
Tier A the hook cries wolf on every edit to a cross-mod overlay, which is worse than not running.

### Fixed — the identifier scan could not see your newest file

`scripts/scan-identifiers.py` built its population from `git ls-files`, which reports the **index**.
A file you have created but not yet staged is therefore invisible to it by construction — and that
is the file most likely to carry something you have not thought about. It printed *"scanning 200
tracked file(s) ... clean"* over exactly such a file; staging it took the population to 201 and the
scan then meant something.

Both halves are now scanned, and the population line names both, so a zero is visible rather than
implied. Ignored build output stays out. A hit in an untracked file is a full finding, because that
is the case being prevented.

`--selftest` is new and CI runs it **before** the scan. In CI the untracked list is always empty, so
CI could never have caught this defect and cannot demonstrate the fix either; the selftest is the
only thing there that can go red over it.

### Added — the hooks that were only ever running locally, and a suite that proves them

`.claude/hooks/protect-bash.sh` shipped at **3,445 bytes** while the version in daily use was
**17,722**, and it was missing every rule added over the past month. `test-protect-bash.sh` — the
regression suite that makes those rules trustworthy — had never shipped at all.

Nine rule families are now here, each keeping the MEASURED cost of the failure it prevents, because a
guard whose reason has been trimmed away is the first one someone deletes:

| guard | what it cost when it happened |
|---|---|
| `git add -A` / `.` in a shared tree | 4 untracked files from a concurrent session, one commit-timing away from being committed |
| `timeout` above the harness cap | 600000 ms is silently clamped; four separate 10-minute losses in one session |
| a known long job in the foreground | the same clamp, reached by a different route |
| truncating redirect onto a durable record | `>` gets no backup; this wiped a file to 0 bytes |
| recursive search over the reference tree | route it to a tool that returns a denominator |
| recursive search rooted at a workspace root | `grep -r` killed at 300 s; ripgrep timed out at 20 s |
| profile `content.xml` searched by NAME | it is keyed by manifest id — a name-shaped zero is the wrong query, not an answer |
| `$?` read after a pipeline | reported a real exit 5 as "exit 0" |
| measurement output into shared `/tmp` | another session's stale files nearly reported as this run's results |

All paths resolve through `_x4-env.sh`; nothing is hardcoded. Path-dependent probes **SKIP loudly**
when a location is unconfigured and the tally names the skip count — otherwise a fresh clone would
print the same cheerful line as a real run, over rules that were never exercised.

**The suite immediately earned its place** by catching two regressions the port itself introduced: an
over-block that denied a deliberately *scoped* search, and an under-block where an unexpanded
`$X4_PROFILE` stopped matching. CI now runs it before the test suite.

### Changed — the six skills, merged rather than replaced

The shipped skills were behind the ones in use (one at 2,777 bytes against 5,131) but were **not
simply stale**: they carried cross-platform work the newer copies lacked — registry resolution
through `$X4_MODS`/`$X4_REGISTRY`, Linux profile locations, and an interpreter pin. Each file was
merged in both directions and every dropped line reviewed, so nothing regressed to a
machine-specific path.

Adds **`x4-balance`**, which grounds a stat-tuning discussion before any value is proposed: it names
which instrument answers which question and **what a zero from each one means**, then enforces the
three-values rule (vanilla / effective / proposed) and an in-sector vs out-of-sector check.

### Fixed — two named mods in published skill descriptions

Skills are generic procedure and must never name a specific mod. `x4-mod-interaction`'s description
referred to a particular overhaul by name, and `x4-update-mod` named specific mod APIs as its
migration examples. Both are generalised. Measured across all six skills: 0 named mods, 0 personal
paths.

## v2.9.0 — 2026-08-28

### Added — nested cross-mod script patches are now validated, through the document the engine builds (F70)

A patch at `<mymod>/extensions/<target>/md/foo.xml` was validated by **nothing**: both halves of the
script pass check direct children only. `--update` now validates each one through its **merged
result** — target + patch — rather than the patch file, which is a `<diff>` the engine never parses
on its own.

**It reports only what the patch is responsible for.** Validating the merged document alone would
blame a mod for its target's pre-existing schema violations. MEASURED over all 16 nested patches in
a real 125-mod install: **182 findings, of which 167 (91.8%) belong to the target** — a mod named
`moreroomsforships` fails `md.xsd`'s capital-letter pattern because its own author named it that, and
the patching mod can neither cause nor fix it. So both sides are validated and diffed per finding:

```
- XSD(nested): 1 cross-mod script patch(es) validated via their merged result
  — 0 introduced, 1 fixed, 0 not checkable
```

`fixed` is reported as well as `introduced`, because a check that can only go one way cannot be
trusted to go the other.

**A file that could not be checked never reads as one that came back clean**, and the two reasons are
kept apart:

- *target mod is not installed* — the engine no-ops the patch too; not a defect.
- *target is installed but does not supply that file* — a **stale patch that silently never applies**.
  One real instance in the live set: `ship_variation_expansion_vro` patches `md/spawnclaymore.xml`,
  and its target ships seven md files, none of them that one. No engine error is produced for this.

Findings are matched by message, not line number, so a patch shifting lines does not report every
inherited finding as both removed and added.

*Known limit, stated because it is easier to trust a tool that names its edges:* the attribution
compares the target alone against the target plus this mod. A finding that appears only in
combination with a **third** mod's patch is outside what it can see.

### Fixed — `x4effective dump` no longer reports a wrong FORM as a confident ABSENCE (F71)

`dump` keys documents by their **logical** vpath — the one the engine builds. Addressing a mod's
document by its path on disk, `extensions/<mod>/md/foo.xml`, missed and printed
`no effective content`. That reads as *the file is not in the live tree*, when the truth was *right
file, wrong form*. **1,713 of 3,257 touched vpaths are mod-owned**, so this covered a third of the
surface.

It now resolves the logical vpath and **says so**, because resolving silently would swap one
confident-wrong answer for another:

```
$ x4effective dump --chain extensions/moreroomsforships/md/morerooms.xml
<!-- note: 'moreroomsforships' is an installed MOD, not a DLC, so that is a disk path,
     not a game vpath; interpreted as logical vpath 'md/morerooms.xml' -->
<!-- sources: moreroomsforships:full, zzz_fixer_morerooms:diff(nested:moreroomsforships) -->
```

Deliberately narrow, and each limit is tested:

- The retry runs **only after the literal lookup genuinely fails**, so every path that resolves
  today resolves by the same route it does now.
- **DLC paths are never rewritten.** `extensions/ego_dlc_split/...` *is* a real game vpath; that
  case was already correct and is unchanged.
- **Double-nested paths are never rewritten**, mirroring `_effective.build_touch_map`, which
  refuses the same shape because patch-on-a-patch is not engine-proven.
- **A genuine absence is still `rc 1`.**

DLC-ness is asked of `Config.dlc_dirs()`, never guessed from an `ego_dlc_` name prefix — the
existing `test_dlc_enumeration` guard rejected the prefix form, correctly, on its first run.

### Correction — the "0 mods newly report an error" figure was wrong; it is 1, and it is a real bug found

The entry below claimed a per-mod census showed **0** mods changing exit code. A proper per-mod
census — the same run, both tiers, all 125 installed mods — shows **exactly one**, and it is a
**true positive**:

```
xenon e class ship   0 -> 1   md/xenone_resistant_system.xml:17
                             Element 'find_ship': attribute 'space' is required but missing
```

That is a genuine 9.0 breakage (`find_ship`/`find_station` gained a required `space` in 9.0), of the
class the knowledgebase calls the only reliable 9.0 migration signal — and it was **invisible in a
default run** until this change. So the change is doing exactly what it was built to do; the claim
about its blast radius was simply false.

**Why the first measurement said 0:** it filtered findings on `f.level`, and the field is
`f.severity`. `getattr(f, "level", "")` returns `""` rather than raising, so the filter matched
nothing and produced a confident zero. Use `Report.errors`, which cannot fail that way.

**One other row moved and is not a code change:** a mod folder was deleted between the two census
runs, so it went from validating cleanly to "mod folder not found" (exit 2). Corpus drift, named
here rather than absorbed.

### Changed — the cheap script check now runs on every validate, not only under `--update`

A mod whose payload is `md/` or `aiscripts/` files used to have **no script check at all** in a
default run, because every script check sat behind `--update` — which compiles `md.xsd` at ~102s.
For an additive-only script mod that meant the one check capable of failing was the one not run,
while the summary said "OK".

The required-attribute pass needs no schema compile, so it now runs always. MEASURED on a real
125-mod install: **6.3s total, 0.100s for the heaviest single mod, and 0 mods newly report an
error** — so no real modlist changes exit code. Its corpus-wide parity with libxml2 is proven by
`gates/xsd_fast_parity.py`: **555 script files, 0 false positives, 0 misses.**

What still needs `--update` is now named rather than implied:

```
 - required-attrs: 5 script file(s) checked without compiling a schema (0 gating breakage(s))
 - script-schema: 5 md/aiscripts file(s): the required-attribute class was checked and is
   COMPLETE, but the 'element not expected' class - where element ORDERING errors live - and
   the schema-strict advisories were not. Those need the ~102s schema compile: `--update`
```

That class matters: of the three real violations in the report that prompted this work, **two were
element-ordering errors**, and `--update` reports them as errors with exit 1.

⚠ **Considered and rejected: degrading those mods to exit 3.** It would have fired on 18 of 125 mods
permanently, clearable only by paying 102s every run — which turns exit 3 from "investigate" into
"ignore". The right answer to "a check did not run" is to run the check.

A mod with no script files gets no script commentary at all, in either direction.

### Fixed — cross-mod script patches were missed by the disclosure, and are validated by nothing

Found by red-teaming the follow-up plan rather than by a failure.

A mod that patches another mod puts its files at `<mymod>/extensions/<target>/md/foo.xml`, which
does not start with `md/`. The disclosure added in the previous release matched on that bare prefix
and so **missed every cross-mod script patch — 15 files across 7 mods**, which means the figures
published with it (77 of 124 mods, 17 script-only) were wrong. The true figures are **79 of 125 and
18**. The nesting strip is now a single shared helper used by both call sites, so they agree by
construction rather than by both being edited correctly.

**The larger half:** those nested files are validated by *nothing*. Both halves of the script pass
check direct children only — deliberately, so the loose and packed halves cover the same population
— while the effective-tree check skipped nested scripts *on the stated grounds that the script pass
already covered them*. It does not. That justification has been corrected in place, because a false
justification is how a gap stays invisible.

So the two populations are now reported **separately, because the advice differs**:

```
 - script-schema: N md/aiscripts file(s) were NOT validated ... runs only under `--update`
 - script-schema-nested: M nested cross-mod script patch(es) ... are NOT VALIDATED BY ANYTHING
   - not by this run and not by `--update` either, which checks direct children only
```

Simply counting the nested files into the existing message would have made the number complete and
the **advice false**, which is worse than the under-count it replaced.

⚠ **Coverage is unchanged and that is deliberate.** Widening the script pass to nested files alters
what `--update` validates and needs its own measurement; it is registered rather than done. The
evidence that these files are live: all 15 are `<diff>`, the nested path is the engine's documented
cross-mod patch form, and the engine demonstrably loads their targets.

### Fixed — a patched data file that declares a schema is disclosed as unvalidated too

Found by sweeping for the shape rather than by tripping over it. `check_effective_schema` validates
the *merged* result of every data file a mod patches against the schema that file declares, and it
sits behind `--update` exactly like the script pass. So a mod patching `libraries/god.xml` — which
declares a schema — reported `OK: no issues found` with no mention that the check existed and had
not run.

Now disclosed in the same NOT CHECKED channel, naming the count and an example file. Exit code
unchanged: unlike the script-only case, the diff itself genuinely *was* examined, so a clean result
is defensible — it just was not the whole story.

Eligibility and the schema lookup come from the existing `_xsd` helpers rather than being re-derived,
because a second implementation of the same normalisation is how these gaps get made in the first
place.

### Fixed — a mod shipping `md/` or `aiscripts/` no longer reads as a clean pass

An additive-only `<mdscript>` with three `md.xsd` violations returned **"OK: no issues found"**,
exit 0.

The schema check was not missing — `--update` reports two of those three as **errors** (element
ordering) and the third as an advisory. What was missing was the *sentence*. Compiling `md.xsd`
takes about 102 seconds, so every script check deliberately sits behind `--update`; in the default
run nothing examined the file, and the summary still said OK. For an additive-only script mod that
is the whole story: no diffs, no selectors, nothing else to resolve — **the one check that could
have failed was the one not run.**

The default run now records it in the existing NOT CHECKED channel, and the summary line changes
itself accordingly:

```
  no issues found in what could be checked

  NOT CHECKED:
   - script-schema: 1 md/aiscripts file(s) were NOT validated against their schema and are this
     mod's ONLY payload, so nothing that can fail was examined — the schema pass costs ~102s to
     compile and runs only under `--update`
```

**The exit code is unchanged.** MEASURED over the installed set, **79 of 125 mods ship script XML
and 18 are script-only**, so degrading the run here would fire on most of the corpus by default —
and a check that floods is worse than no check, because it teaches you to skip the output. Whether
the script-only case should degrade is left as a deliberate decision.

### Fixed — three-way diff: a whole-file override now joins the plain document it overrides

Found on the second real use, once the nested-path fix let the comparison get far enough to fail here
instead.

A mod supplies a document as `<diff><replace sel="//macros">PAYLOAD</replace></diff>` — the standard
whole-file override idiom, of which VRO alone ships 848 — while the mod it patches supplies the same
document plainly. Across the join every attribute path on one side then carried a `/diff/replace/`
prefix the other lacked, **nothing matched, and the whole document fell to node-level counts** like
`+14 / -12 node(s)`. That output was honest — node-level changes are reported, not classified — but
the files most worth classifying were exactly the ones it could not classify.

The payload is now unwrapped on each side independently, and the unwrapping is listed under
`UNWRAPPED` like any other path rewrite. It is narrowed by **self-consistency rather than a list of
known selectors**: the diff must hold exactly one element op, it must be a `replace`, it must carry
exactly one payload element, and the selector must name that payload's own tag. So
`<replace sel="//ware[@id='gun']/@damage">`, an `<add>`, and a two-op diff are all left alone.

### Added — additions and removals are labelled, not left to be inferred

An attribute the author **removed** and one upstream **added** are not value edits, and a consumer
applying either as a value edit would write the absence sentinel into the attribute rather than
deleting it. Both are now named in the listing:

```
  author edits (1):
    .../bullet_x.xml  ...damage@shield: 7500 -> ∅  [author-removal]

  upstream drift (1):
    libraries/wares.xml  ...@targetable: ∅ -> 1  [upstream-addition]
```

The second is the case this whole tool exists for: an attribute present today and missing from an
old file is upstream *addition* far more often than author *removal*, and it is now stated by the
tool rather than inferred by a reader. Bucket totals are unchanged — only the label is new.

### Fixed — three-way diff: a nested overlay is now compared against the mod it patches

Both defects below were found on the tool's **first real use**, hours after it shipped.

A mod that patches another mod puts its files at `<mymod>/extensions/<target>/<mirrored path>`, and
that is the normal shape for a personal overlay — which is precisely the porting job this tool
exists for. The overlay's vpaths therefore never joined with the vpaths of the mod it patches:
**0 documents compared**, with the *same logical file* listed under both exclusions at once, once as
`NO BASELINE` under the nested path and once as `NOT IN THE ARCHIVE` under the plain one. On the real
mod that surfaced this, all four files of interest were excluded and the comparison was empty.

The prefix is now removed when — and only when — `<target>` is a name the baseline answers to, by
folder name *or* `content.xml` id, since those differ often enough to matter. A patch aimed at some
third mod stays excluded: trading a false negative for a false positive would be no improvement.
Every rewrite is listed under `UNWRAPPED`, because silently rewriting a path is a transforming step,
and two paths collapsing onto one join key are reported rather than one being dropped.

### Fixed — three-way diff: `--file` was ignored

`--file` filtered nothing in three-way mode: two different files and no filter at all produced
byte-identical output. It now filters the listings while the **counts stay the whole comparison**,
said so explicitly, so the denominator is never quietly narrowed by a display option. A `--file`
that matches no classified attribute now says that this is an absence *only if the file is in the
comparison*, and points at the exclusion lists — rather than reading as "no differences".

### Added — `x4diff --base`: three-way diff, separating your edits from upstream drift

A two-way diff between an archived mod and the current release answers the wrong question and
answers it confidently. Measured on one real 2021 mod of 135 documents: **~440 attribute deltas
two-way, but only 15 were the author's.** 340 were upstream's own work since, and **124 of 135
documents were verbatim copies of the baseline** — so **96% of what the two-way diff called "the
port" was someone else's work.** Acting on it would have re-applied 340 upstream changes as if they
were the user's, and reverted the current release across 124 files.

Supply the common ancestor with `--base` and every attribute lands in exactly one bucket:

```
  documents shared with the baseline : 135
    the author edited                : 11
    VERBATIM (author touched nothing): 124
  attributes classified              : 356
    author edits ....... 15
    upstream drift ..... 340
    converged .......... 0   (both sides, same change)
    BOTH-MOVED ......... 1   <-- the decisions
```

**`BOTH-MOVED` is the point.** One conflict is a decision you can make; 440 undifferentiated deltas
are a wall you cannot. Exit 1 when there is one, 0 when the port is mechanical.

⚠ **A one-sided absence is reported as unknown, never as a deletion.** An attribute present in the
current tree and missing from an old file is upstream *addition* far more often than author
*removal*, and a two-way diff cannot distinguish them — 16 macros in that same mod appeared to have
lost an attribute nobody had touched. A three-way diff can tell them apart wherever a baseline
exists; where one does not, the document is **named and excluded from every bucket** rather than
guessed at. Documents present in the baseline but absent from the archive are likewise excluded and
never reported as drift.

The classification is a join over two ordinary two-way diffs, not a second differ — a duplicate
implementation of the same normalisation is exactly what once made an independent measurement report
2.6% where the truth was 65.4%.

### Changed — the CLI no longer lives inside the freshness-hashed engine sources

The `engine` freshness axis hashes the whole bytes of seven source files, so **editing an error
message invalidated the effective store and BaseX `x4eff`** exactly as a merge-semantics change
would — while the stale banner asserted *"the SAME inputs would now merge differently"*. Measured
twice in one session: a guard's CLI text moved the hash, and then a pure **docstring** (10 lines
added, 0 executable) moved it again.

The CLI surface is now `_effectivecli.py` and `_diffcli.py`, neither of which is hashed.
`_effective.py` drops 1,360 → 897 lines and `_diff.py` 276 → 188. Nothing about the merge changed,
and nothing you run changed — `x4effective` and `x4diff` behave identically.

Deliberately **not** done: making the hash cleverer. An AST- or token-level digest would fail in the
unsafe direction, where one missed merge change lets a stale artifact report itself fresh. Six tests
now pin the boundary: no hashed source may parse arguments, define a command entry point, or print
beyond a stated two-call allowance for the unconfigured-install refusal. Verified in both directions
— a CLI edit leaves the hash alone, an engine edit still moves it.

### Fixed — a mod-set mismatch reported the wrong direction

The check that BaseX `x4eff` models the *active* mod set listed only mods `x4eff` carries that the
engine will not load. In the common case — an index built before you added a mod — that list is
empty, so the failure printed an empty set and named a direction that was not the problem. It now
reports both, and names the mods that are active but not indexed.

### Fixed — `x4effective attr` no longer answers a bad question with a clean zero

`attr` took two free-form arguments and validated neither, so a query that could never match
anything printed `0 value(s)` and exited **0** — indistinguishable from a real, informative absence.

The guard for this already existed and was wired into `ls`, `show` and `who-sets`; `attr` was the
one command it never reached, and the only one where **both arguments can be individually valid
while the pair matches nothing**. `attr ship hull.max` is that case: `ship` is a real kind (514
entities) and `hull.max` is a real property (1,973 values) — they just live in different kinds.

`attr` now rejects an unknown kind (**exit 2**) or an unknown property (**exit 1**), states the
denominator, and points somewhere useful:

```
$ x4effective attr macro properties.hull.max
no macro carries prop 'properties.hull.max' - that kind has 8672 distinct prop(s)
       did you mean 'hull.max'? (1973 value(s))

$ x4effective attr ship hull.max
no ship carries prop 'hull.max' - that kind has 31 distinct prop(s)
       'hull.max' is carried by kind 'macro' (1973 value(s))
```

Suggestions are looked up **in the store**, never derived from a rule. Property names for *macros*
are stored with the `<properties>` wrapper stripped (`hull.max`, not `properties.hull.max`) — but
that is a macro convention, not a store-wide one: **6,842 rows legitimately keep the prefix**, so a
blanket rule would be wrong for every one of them. A genuine zero — the property exists for the kind
and a `--class` filter excludes every row — is still **exit 0**.

### Fixed — `apply_diff` names the argument you got wrong

The third positional parameter is `recorder`, not `source`. Passing a filename there failed four
frames down with `AttributeError: 'str' object has no attribute 'elem_replaced'`, naming an internal
method rather than the bad argument — and *which* method it named depended on which operation the
diff happened to contain, so a diff of pure `<remove>` ops recorded nothing and sailed through. It
now raises `TypeError` at the call, naming both `recorder` and `source`.

### Changed — a docstring that had rotted

`_registry.mods()` did not mention that **neither** scope includes the DLC — `ego_dlc_*` is
base-game content, and counting it would double-count against the unpacked reference tree. The
caveat was documented on `scan_installed`, but not on the function the documentation tells you to
prefer instead, so a dependency check asked `mods("installed")` whether a DLC was present and was
told no. For that question use `Config().dlc_dirs()` or `.packed_dlc_names()`.


### Added — `x4modlist tracked`: what the account FOLLOWS, against what is installed

Tracking is a **third population**, distinct from *installed* (on disk) and *active*
(engine-loadable): it is what you asked Nexus to watch. The two mismatches are the point —
**followed but not installed** (candidates you already showed interest in) and **installed but not
followed**, which means no update notification, and that one costs something silently. MEASURED on a
live account: **36 of 73** installed mods with a known Nexus id were untracked.

⚠ The endpoint is **account-wide** (1,616 rows across 9 games for 413 X4 ones), so filtering to one
game is a narrowing step and the denominator is printed first, always. A payload that is not a list
**raises** rather than reporting "0 tracked" — an upstream shape change is a non-answer, not an
absence.

## v2.8.0 — 2026-08-26

### Added — `x4save`: read a savegame, and say what it would silently lose

A save is the only artifact the ENGINE wrote, and it answers two questions no manifest can.
Both measured in-game.

`uv run x4save info` — the header, and the **save-baked** extensions. **`<patches>` is not a
record of what loaded.** An extension appears iff its `content.xml` `save` attribute is ABSENT
or `="1"`: of 129 installed extensions 11 qualify, 10 were recorded (the gap is an online DLC
not loaded as a content patch), and **0 of the 118** declaring `"0"`/`"false"` appeared. For
mods that is **3 of 121 (2.5%)** — *less* complete than the profile `content.xml`. The command
prints that denominator, so the list cannot be misread as coverage. What it does tell you is
which mods are welded into the save, i.e. which removals are dangerous.

`uv run x4save check <save>` — macro references the live tree no longer defines.

**This exists because the engine is silent.** Removing a mod leaves no dangling references: X4
**deletes the orphaned content**. Disabling one mod took its 37 macros / 46 references to zero;
the engine logged **one** error line, and it named a galaxy connection rather than the station,
the ship, the production modules or the 36 other macros that vanished. No dialog. And the net
error count went **down by 3**, because the mod's own 4 errors left with it — judged by
`debug.txt`, the removal looked like an improvement. `check` names 37 items where the log names
one. (Scope: n=1 mod, one save. The tool reports what a save references; it does not assert the
general rule.)

Cheap, despite the file size: the largest save here is 140 MB compressed and **1.28 GB**
expanded, and streams in **2.5 s**. Everything is streamed; nothing builds a tree.

### Fixed — a guard that caught a vanishing CLI but not a new one

`tests/test_unconfigured_refusal.py` asserted `len(entries) >= 9`. That catches an entry point
*disappearing* and silently accepts one being *added* — so shipping a new CLI passed a check
written to notice exactly that. Now `== 10`, changed deliberately.

### Fixed — CI had never once started a JVM (the vendored BaseX jar was untested)

The 24 BaseX tests pass on a machine with no Java, **because they mock**: `test_preflight.py`
monkeypatches `shutil.which` and writes a jar that is literally
`b"not really a jar, but it is a file"`. Since the jar was vendored in v2.6.0, no CI job on any
OS had executed it. A bad jar, a classpath change or an untracked `.basexhome` would have
shipped in silence — a green that could not have gone red.

CI now installs Temurin 17 and runs `tools/basex/smoke-basex.sh`, which builds a three-document
database and runs a real `collection()` query against the real jar. It is deliberately **not** a
pytest that skips when Java is absent, because a skip in CI is indistinguishable from a pass.
Proven able to fail in three ways: remove `.basexhome` → red, corrupt the jar → red, hide `java`
→ red.

### Fixed — `setup.sh` never checked for Java, while `README.md` promised it

`README.md` states "Java 17+ — optional, only for the BaseX corpus search", and the guided
install flow (`setup.sh`, `install.sh`, `install.ps1`, `SETUP_PROMPT.txt`) contained **zero**
mentions of it. Users met the requirement only when a corpus build refused with exit 2 — correct
behaviour, but the only mechanism. `setup.sh` now probes for it alongside `jq`/`uv`/`wine`, as a
warning rather than a failure since BaseX is optional. The floor is measured, not chosen: BaseX
12.4's classes are bytecode major 61.

### Added — `EntityDefs.all_names()`, and BLIND-SPOTS **F65**

`EntityDefs.__contains__` answers a per-NAME question at per-name cost, justified by a stated
population: *"7 distinct references across 114 mods miss the eager tiers."* True for a mod —
which is a property of the caller, not of the tool, and nothing enforced it. A savegame carries
**5,022** references, ~2,500 of which miss the eager index; the lazy tier blew a 600 s cap with
no result. Built in bulk the same answer takes ~19 s. No shipped caller was affected.

### Changed — provenance now says which source WON, not which INTRODUCED

`x4effective who-sets` and `dump --chain` report which overlays produced a value. A root
`<replace sel="//macros">` swaps the whole document, so **base contributes no chain entry at all** —
VRO's dominant idiom, 848 of them. A single-entry chain therefore read as *"this mod introduced this"*
when it usually means *"this mod re-supplied what vanilla already had."*

MEASURED: of **35,423** single-op root-replace attributes, **23,182 (65.4%)** also exist in vanilla
with the chain hiding it; only **39** vpaths are genuinely mod-added. `bullet_arg_m_ion_01_mk1_macro`
is the sharpest — vanilla 10, live 10, chain `[vro]`: identical value, sole credit, no hint a base
file exists. It cost a real design conclusion.

Both commands now disclose when base+DLC also supply the vpath, and stay **silent** for genuinely
mod-added vpaths, pure-base values, and chains that already name base. Scope is existence, not the
vanilla value — reporting the value would mean a second implementation of the property flatten, and
that is what made the original measurement of this defect report 2.6%. BLIND-SPOTS **F64**.

### Fixed — a store could be stamped with a world it was never built from

`_ext_root()` returned the real extensions directory unconditionally, behind an `except
AttributeError` that can never fire — the attribute exists and its value is `None`. A store built
over throwaway directories was stamped with a fingerprint describing the **real** installed game.
It now records an **UNKNOWN** content axis instead, which never reads as fresh. **F63 symptom 2.**

### Fixed — the line-ending pin was never checked against the bytes it governs

`.gitattributes` pins shell scripts and Python to LF. **A pin governs CHECKOUT; it does not repair a
file already in a working tree**, and nothing counted the bytes. MEASURED: **14 of 155** pinned files
held CRLF here — including `bin/xrcat` and `.claude/x4-paths.env.example`, where CRLF is
**functionally fatal** rather than cosmetic, because both are sourced by bash and a trailing CR lands
inside every value.

A fresh clone was never affected — checkout applies the pin — but nothing would have caught the next
file to drift. The new guard asks **git** what the pin resolves to and reads the **working tree**,
with no allow-list. BLIND-SPOTS **F67**.

### Internal — the checks that check the checks

**Mutation coverage 1 module → 6, 15 mutants, `killed 15/15, survivors 0`.** Every detector it names
is now provably killable rather than assumed so: the bare-vs-nested door, load order replaced by
alphabetical, property recursion truncated to depth 1, and the packed half of a scan never entered
(**F54**). `all_names()` gained the tests it shipped without — the property that matters is that it
is **never narrower** than the per-name door, since a narrower set does not crash, it reports defined
names as dangling. And **F66** records an investigation that found *nothing*: producer/consumer key
normalisation, three pairs, no disagreement — filed so the line is not silently re-opened.

## v2.7.0 — 2026-08-26

### Fixed — five tests failed on any machine with no game installed (F63)

`_effective._ext_root()` returns `_registry.GAME_EXTENSIONS`, guarded by `except AttributeError`.
**That guard never fires** — the attribute exists and its *value* is `None` when nothing is
configured. `_freshness.fingerprint()` then refused, correctly (it must never guess an extensions
root and hash whatever directory you are standing in), but it could not tell *"the caller forgot"*
from *"the caller looked and there is none"*.

Every fresh clone and every CI runner is the second case. Both now have spellings:
`fingerprint(config)` still **raises**; `fingerprint(config, extensions=None)` records the content
axis as **UNKNOWN**.

⚠ And UNKNOWN never reads as fresh. `None == None`, so a naive comparison would have made two
unknown content axes *match* and report FRESH — an artifact that cannot say which world it describes,
declaring that it still describes it. `compare()` now says freshness could not be **established**,
which is neither fresh nor known-stale.

`_freshness.py` is deliberately not among the sources the engine fingerprint hashes, so this changes
no artifact's fingerprint and nothing needs rebuilding.

### Fixed — the mutation gate ran a narrower scope than it reported (F62)

`gates/mutation_probe.py` drops a missing test path from a mutant's scope before invoking pytest.
Filtering a vanished path is right; doing it **silently** is not — and it was happening inside the
one gate built to detect vacuous assertions.

MEASURED: this gate's `_registry.py` scope lists four test files. In one checkout only three exist,
so it ran **3 of 4** and printed the same `killed` line as a full scope.

Two more in the same function. An **empty** scope returned the verdict `"hang"` — an absence
rendered as a timeout that was never measured, which the caller then "confirms" by re-running,
against a file that is still not there. And the test meant to catch all of this,
`test_every_target_has_tests_that_exist`, asserted `any(... exists ...)`: its NAME promises every
file, its ASSERTION accepted one, so three of four present passed.

Now: a partial scope **names what it dropped**; an empty scope returns a new verdict `noscope` with
its own bucket, excluded from the killed count and failing the gate; an empty BASELINE scope returns
**rc 2** (cannot run), never rc 1 (has findings). The check is `mp_scope_gaps()`, which returns the
**named gaps** rather than a boolean.

The asymmetry is the proof: it is GREEN against a complete tree and RED against an incomplete one,
naming the exact missing file. Six tests written first and each watched fail for the right reason —
one printing `killed 1/1` for a mutant that was never challenged. Probe re-run afterwards:
**11/11 killed, 0 survivors, 0 hangs, 0 unmeasured.**

### Changed — `docs/QA-PROCESS.md`: how to prove a port

Rule 2 said to prove a port with `diff -rq`. MEASURED on a real pair of trees, that reports **52
differences where 12 are real** — the other 40 are line endings, from a working tree checked out
before an LF pin, while both repositories store identical bytes. A proof that buries findings under
non-findings teaches you to skip it. The rule now says to compare **committed blobs**.

### Fixed — a mutating gate could not put the tree back if it died (F59)

`gates/mutation_probe.py` breaks a source file on purpose, runs the tests, and restores it. The
restore lived in a `finally:` — and **`finally` does not run on SIGKILL**. A killed probe therefore
left a deliberately-broken source on disk, and because that file is **tracked**, `git status` shows
an ordinary modification. **v2.5.0 shipped exactly that way once**: ambiguous-`sel` detection
silently disabled in a public release.

Not hypothetical. A stop command that **reported success and did not stop** left three gate sweeps
racing, so "never run a mutating gate against a tree in use" can be broken by accident.

**Reproduced rather than simulated** — launched the probe, polled until a target really differed from
HEAD, hard-killed it at t=7.5 s. It left `if len(new_children) != 1 and False:` on disk. Re-running
refused with **rc 2**; `--recover` restored it and named the mutated file.

Byte-for-byte pristine copies plus a `.mutation-probe-active` marker written **before** the first
mutation, so recovery never depends on the thing that failed. Recovery is explicit, never automatic:
auto-restore would need pid liveness, and on Windows `os.kill(pid, 0)` maps to `TerminateProcess`.

### Added — the mutation window is visible to every tool, and refuses writers

During a window every CLI answers from broken code with nothing on screen saying so. Reads now get a
**banner**; writes **refuse with rc 2**. The asymmetry is the point: a wrong read can be re-taken
once the ~70 s window closes, but a poisoned **artifact** outlives it and is trusted afterwards.

The banner rides on the decorator every entry point already carries, so all 9 CLIs are covered by
construction. The refusal sits at the two **stamping sites**, not at argument parsing, so no other
entry path can slip past it. ⚠ The marker resolves from `__file__`, never the CWD — these tools are
normally run from the game directory, where a CWD-relative lookup would report all-clear from the one
place it matters most.

### Changed — mutation coverage 1 file → 3, and a hang is its own verdict (F54)

`_merge` (6 mutants), `_registry` (3), `_compat` (2) — **11/11 killed**. Every mutant inverts a guard
whose failure has a **measured** cost, so a contrived mutant nothing kills cannot pad the number.
Per-mutant timeout **1800 s → 120 s**, and **HUNG** is now distinct from both killed and survived: a
mutant that hangs is a finding about the suite, not a pass.

### Changed — a stale verdict says how far it moved

Both freshness axes now quote `[stored -> now]`. "Moved how far, and by whose change?" is the first
question on hitting a stale artifact, and answering it previously needed a hand-written script.

### Fixed — a capability that existed, was correct, and was never reached (F58)

`x4effective dump --chain` answers whether a vpath exists in the live tree, **who supplies it**, and
whether they supply or merely patch it (`vro:full` vs `base, ego_dlc_x:diff`). A gap was filed
against it anyway, and a hand-rolled base-only substitute labelled **65 of 241 vpaths** as
"paths Egosoft renamed" — they are mod-supplied files that actually **win** those paths, so the error
pointed toward deleting them.

Fixed with a routing-table row, and **deliberately not a new helper**: the one added for this exact
trap the day before had **zero callers**. Also deliberately not a lint — the failure was in a
throwaway script, which no linter covers. MEASURED alongside: **21 of 30** CLI subcommands appear in
no routing surface.

### Fixed — the freshness content axis was blind to a mod's files changing (F57)

`_freshness.hash_content` stat'd **only** each mod folder's `content.xml`. The ordinary
overlay-deploy workflow — edit a file, copy it in, manifest untouched — moved nothing, so every
artifact reported **FRESH** while describing a different tree.

MEASURED: **72 of 121 non-DLC mods (59.5%)** have at least one file newer than their own manifest,
and the old code returned the identical digest `03122df005f47fbd` before and after a file-only edit.
This is a false **FRESH** — it fails in the unsafe direction, unlike F53's false STALE.

The axis now also hashes a per-mod `tree_sha` over sorted `(relpath, mtime, size)` for
`.xml/.cat/.dat/.lua`. Cost on a live 129-mod install: **0.10 s / 2,170 files**.

⚠ The suffix filter is **correctness, not speed**: 8 mods would otherwise move the fingerprint on
README/CHANGES/LICENCE churn alone.

⚠ **Scope limit**: `(mtime, size)`, not a content hash. An edit changing neither is invisible; a
same-size edit reads as `touched` rather than `content`. Manifests *are* hashed.

### Added — `x4modlist changed` / `x4modlist snapshot` (F56)

The digest said THAT the world moved, never WHAT. Localising one changed mod took nine investigative
steps and three false leads, and only worked because it happened to bump its `version`.

`content_detail()` now returns the per-folder vector, `hash_content()` folds it through a single
`_fold()`, and the vector is **persisted** beside the digest (190 KB) so a move is localised by
diffing rather than by forensics.

```sh
x4modlist changed [--since store|xref|latest|<path>] [--files] [--usn]
x4modlist snapshot [--label <name>]
```

- Triples are hashed as a **set**, never `max(mtime)` — the incident mod had **back-dated** its 26
  files, which is exactly what defeats a max and what made `find -newermt` useless.
- A baseline with **no vector raises `NoBaseline` and exits 3** — a non-answer, never "no change".
  Reading is optional, so no existing artifact flips to UNKNOWN.
- `--usn` needs Administrator (Microsoft's documented requirement for change-journal reads) and
  **degrades to a message** rather than failing the command.

### Fixed

- **F43** — the content axis could not see a mod being enabled or disabled in-game, because toggling
  rewrites only the PROFILE manifest. Now carried per mod, joined by **manifest id, never folder
  name**, defaulting to enabled for a mod the profile has never seen. Verified against the live
  profile: it finds exactly one disabled mod, matching independently-recorded ground truth.
- **F52** — `check_effective_schema`'s note went silent about files it skipped as soon as it
  validated anything. The `effective-schema: {checked} ` prefix is preserved; `gates/schema_sweep.py`
  parses it positionally.
- **F46 (swept)** — `fingerprint()` fell back to `Path("")` = `Path(".")`, hashing the current
  directory. It now refuses. All four production callers already passed the root explicitly.
- **F53** — the working tree is renormalised, so the untouched `ENGINE_SOURCES` are byte-identical to
  HEAD and this tree hashes like a fresh checkout.
- `_freshness` now walks **every** configured install root, not just one, so a mod deployed to the
  profile extensions root is no longer invisible.
- `_effective.base_has()` encapsulates the base-bare / DLC-prefixed vpath rule that made an audit
  report 58 DLC targets GONE when all 58 exist.

### Notes

- Tests **664 → 697**.
- The content and engine fingerprints each move **once**, deliberately. **The merge code has not
  changed** — `_freshness.py` is intentionally not in `ENGINE_SOURCES`.

---

## v2.6.0

**BaseX ships.** The corpus-search tool has been dev-only since it was written; it is now part of the
bundle, jar included. It exists to answer the one class of question a recursive grep answers
*dishonestly* — "nothing references X" — because a grep cannot distinguish *this does not exist* from
*I did not look everywhere*, and 62% of mod XML sits inside packed archives a grep never opens.
`ask.py` refuses to print a zero as a finding unless it can state the denominator it looked over, and
then says **"NEGATIVE CONFIRMED over N of M documents"** with every exclusion named.

It is **optional** and it is not free: Java 17+, roughly 3 GB of disk, and a build measured in
minutes. That is said up front rather than discovered on your first run.

Everything else here is the cost of making it safe to hand to someone else — plus five defects the
gates found while we did.

### Added

- **`tools/basex/`** — two indexes over the corpus: `x4raw` (every file *as written*) and `x4eff`
  (the merged, live tree, diffs applied in load order). Use `x4eff` for any claim about what the game
  actually sees; `x4raw` will happily quote a vanilla value your mod list overwrote.
- **BaseX itself is bundled** (5.2 MB, BSD-3-Clause, notice reproduced in `tools/basex/basex/LICENSE`)
  so there is nothing extra to download. Only the JVM is yours to install.
- **`tools/basex/README.md`** — install, and the two things that were nowhere in writing before: the
  **freshness refusal contract** (without it, a tool declining to answer reads as a bug rather than
  the feature it is) and the **exit codes** for all four entry points.
- **A preflight (F47).** Every entry point now checks the JVM, the jar, the index, `uv` and free disk
  **before** any long work, and refuses with exit **2** ("not configured"), never 1 ("your corpus has
  findings"). Previously: a missing JVM surfaced as `BaseX query failed: [WinError 2]` — blaming
  BaseX for a missing Java — and an unbuilt index printed a raw resource error that **never named the
  build script**, because the one line that does sits on a code path an unbuilt index cannot reach.
  The Java floor is read from the shipped jar's own bytecode level, not chosen.

### Fixed

- **A build that SUCCEEDED and was then reported as never built (F51).** `.basexhome` is a 0-byte
  marker in the BaseX archive, and it is what tells BaseX that a directory is its home. Without it
  BaseX relocates its whole home to `$HOME/basex` and builds there — successfully, and queryably —
  while every check looks in the tool's own directory and finds nothing. The first run would have
  been: run the multi-minute build, get told to run the build, forever. Caught before shipping;
  the marker is vendored and the preflight now names the relocation.
- **A crashed build reported as success (F48).** `build-effective.sh` swallowed its builder's exit
  code and wrote its manifest only at the end, so a crash left the *previous* run's manifest in place
  and coverage reconciled the new index against the old one — and could print `COVERAGE COMPLETE`.
  It now fails fast and deletes the manifest before rebuilding.
- **`ask.py` gave a traceback where it owed an answer.** An undeterminable freshness verdict escaped
  as a raw `EngineUnavailable` and exited **1**. "Could not check" is not "stale", and printing STALE
  would be an assertion where the honest answer is that nobody checked: it now reports
  **FRESHNESS UNKNOWN** and exits 4.
- **A guard blind to additions (F49).** The check that stops BaseX tests being orphaned pinned a
  *shrinking* file list but not a growing one — so adding a test file created 22 tests that passed by
  hand and were collected by nothing. A guard whose denominator comes from its own hand-maintained
  list can only ever be as complete as that list; it now discovers the files on disk.
- **A performance gate that could not tell a slow run from a sleeping machine (F50).**
  `time.perf_counter()` advances while Windows is suspended, so a sweep left running overnight
  charged the entire suspend to whichever item was being timed — reported as a **814× regression**
  with "investigate before shipping", on an item that re-timed *faster than its baseline*. A
  suspected regression is now re-timed once and reported only if it reproduces; one that **cannot**
  be re-timed is reported UNCONFIRMED and still fails, because "could not check" is not "not a
  regression".
- **The environment guard could not see a hardcoded path (F44).** v2.5.0's theme was "an executable
  that resolves its own environment instead of delegating", and the AST test that bans it detected
  only `os.environ` / `os.getenv` — so a hardcoded absolute path, the form that defect actually
  shipped in, sailed through. `docs/TRUST.md` named that test as what banned the shape, which means
  **the shipped trust document was overclaiming**. Both are corrected.
- **A corpus-wide crash check that could not see a crash.** `gates/corpus_sweep.py` decided whether a
  run had crashed by looking for a Python traceback in its output. A process killed by the OS loader
  never starts Python, so it prints nothing at all — and in a real run **173 of 242 invocations (71.5%)**
  died that way while the gate printed `CRASHES/HANGS: 0` and passed. The exit codes were in its own
  output, four lines above the verdict that ignored them. It now treats any code outside the documented
  `{0, 1, 3}` as a crash.
- **A coverage denominator taken from the current directory (F46).** `coverage.py`'s `--reference`
  and `--extensions` defaulted to `""`, and `Path("")` is `Path(".")` — so a bare run counted the
  directory it was standing in and published that as the denominator. It now refuses and writes
  nothing.

### Changed

- **POSIX: the 8 Linux CI failures are fixed** — all were test-side, none a library defect. Tests no
  longer patch the global `os` module to fake Windows (that steers `pathlib`'s flavour dispatch and
  raises `UnsupportedOperation`); `_paths._IS_WINDOWS` is a real seam instead. `x4validate --debug`
  now finds the log on POSIX. **Ubuntu deliberately stays informational, not a gate** — see below.
- **`docs/TRUST.md` gained a stated hole rather than a stronger claim.** The freshness fingerprint
  hashes each installed mod's manifest but not the *profile* manifest, so **enabling or disabling** a
  mod cannot move it and an artifact reports FRESH across that change. Installing or removing one
  does move it. Also newly stated: on Linux, four path lookups compare case-sensitively and **one of
  them fails silently**, which is why the Linux run stays informational — passing tests do not close
  that gap, and a green badge should not imply they did.
- **Java 17+** added to the prerequisite list, marked optional and scoped to BaseX.

### Verification

638 tests in the main suite plus 50 run as a subprocess in `tools/basex`, all 26 gates green, and the
suite verified on a genuinely cold checkout — one with every `X4_*` variable cleared and *proven*
unresolved first, because a partially-configured machine will otherwise masquerade as a clean one and
hand you a green that means nothing.

## v2.5.0

Three defects, one shape: **an executable that resolves its own environment instead of delegating to
the one resolver.** A probe of the whole population (9 CLIs, 26 gates, 7 BaseX scripts, 3 installers,
`bin/`, `scripts/`, 2 harnesses) found the CLIs already clean via `_paths` and the gates clean via
`gates/_env.py` — every defect was in something that hand-rolled its own lookup.

### Fixed

- **An unconfigured toolkit refuses instead of guessing (F39).** `_merge.REFERENCE` fell back to the
  *relative* path `reference`, so on a machine with nothing configured `x4validate <mod>` validated
  against a tree that does not exist, reported the whole base game missing **as findings about your
  mod**, and exited **1** — the code that means "your mod is broken". It now exits **2** and names
  `$X4_REFERENCE` and `.claude/x4-paths.env`.
  The refusal fires on *unresolved*, never on "you named a tree that happens not to exist".
- **Configuration is read through one door (F40).** `X4_NEXUS_KEY` placed in
  `.claude/x4-paths.env` — the placement `setup.sh` documents — was invisible, because `_nexus` read
  `os.environ` directly. `_effective` bound `X4_EFFECTIVE_DB` at *import* time into an argparse
  default while `gates/_env.py` resolved the same variable through `_paths`. New `_paths.value()` /
  `path_value()`; the split matters because the path form rewrites `/c/x` to `C:/x`, which would
  silently corrupt a credential. The Nexus key remains **optional** — callers catch and degrade to
  local facts, so offline work is unaffected.
- **Shipped scripts refuse instead of guessing (F41).** `scripts/generate-baseline.sh` defaulted its
  game directory to `$(pwd)`; a baseline is a *recovery* artifact, so that silently snapshotted
  whatever install you happened to be standing in. `bin/unpack-reference.sh` reported "not
  configured" as exit 1. Both exit **2** now.
- **24 tests that never ran on a fresh clone now run (F42).** Two test modules were skipped wholesale
  because the gate modules they import resolved configuration at import time — and a module-level
  skip collapses N tests into ONE line, so the summary read "586 passed, 11 skipped" while 24 tests
  had never been collected. Cold collection now equals warm: **619** either way.

### Added

- **`docs/TRUST.md`** — the trust register: every defect *shape* found in this toolkit, the measured
  cost when it happened, and the test or gate that now bans it. So "is this shape guarded?" is a
  lookup rather than a matter of confidence.
- **AST guard** (`tests/test_env_resolution_is_delegated.py`) banning direct `os.environ` reads
  outside `_paths`, with an `# env-ok:` escape hatch that cannot become a blanket amnesty.
- **A mechanical check that every entry point in `pyproject.toml`** carries the refusal wrapper, so a
  tenth CLI cannot be added without one.
- **A cold CLI matrix in `scripts/verify-cold.sh`** — every configuration-dependent executable is run
  on a genuinely cold checkout and must exit 2 with no traceback.

### Contract

Exit codes are uniform across the toolkit: **0** clean · **1** findings · **2** not configured or
usage error · **3** degraded · **5** stale artifact.

## v2.4.0

Four defects, all one shape: **a set was enumerated twice, by two different rules, and nothing
compared them.** Three were found by cross-tool disagreement rather than by a user; the fourth by
chasing three stray numbers left over from a coverage refresh.

### ⚠ BREAKING (output schema) — prop keys gain a collision suffix

When several sibling elements share a bracket discriminator, the 2nd and later now carry `#n`:
`licences.licence[generaluseequipment].factions`, then `licence[generaluseequipment#1]…`. The first
claimant keeps its original key, so **99.8% of prop keys are byte-identical** and stored baselines
mostly survive.

Why it had to move: the key was not unique, and `select value … where prop=?` with `fetchone()`
returned an arbitrary one of several genuinely different values. `faction/player` held **eight
distinct faction lists under one key**. MEASURED: 627 duplicate `(entity_id, prop)` groups → **0**;
1,153 rows changed prop and nothing else; 582,107 attr rows, 22,966 entities and the entire
entity+value multiset **unchanged**. `dev/_registry/CLAIMS.tsv` uses no bracket props, so no recorded
claim was invalidated. (BLIND-SPOTS **F33**, attr axis. The **entity** axis stays open on purpose —
`index/macros.xml` decides, not load order.)

### Fixed

- **x4eff was blind to the packed mini-DLC** (F34). `build-effective.py` walked `reference/`
  loose-only, so the index held **23 of 142 mini-DLC documents (16%)** — and the 23 only arrived
  because two unrelated mods nest patches under `extensions/ego_dlc_mini_0X/`. New
  `_effective.base_vpaths()` enumerates loose THEN packed, and the copy branch materializes packed
  members via `_cat` (without that half, the fix would have produced 119 *silent copy failures*).
  Now **142/142**. `reference_vpaths` is re-expressed as `base_vpaths` + an explicit `assets/` filter,
  proven set-equal beforehand: 4,002 and 7,551 vpaths, **0 added / 0 removed / 0 changed**.

- **Coverage took its denominator from the artifact it audited** (F35). `coverage.py` reconciled
  "documents produced" against "documents indexed" — both from the same build — so a vpath never
  enumerated could not fail, and it printed COVERAGE COMPLETE while missing 119 documents. The
  manifest now records the **scanned source set** (every configured source, its contributed count,
  loose or packed) and coverage fails when any contributed zero. The exclusions are carried in the
  JSON so a caller can render the caveat instead of reading a bare boolean.

- **The freshness fingerprint covered merge but not enumeration** (F36). `ENGINE_SOURCES` gained
  `_effective.py` and `_registry.py` — the modules deciding which documents, entities and *mods*
  exist. Near-miss that found it: F34's fix edited `reference_vpaths` and `claims_audit` returned
  21/21 green against a store built by the old enumeration. A dead duplicate of the list in
  `staleness.py` was deleted.

- **"The mod list" was two sets with no name for either** (F37). `_registry.mods(scope)` — `scope`
  positional and required, `"active"` (what the engine loads) vs `"installed"` (what is on disk).
  Across 13 call sites, 4 were wrong the same way. With one disabled mod present, x4eff carried its
  macros as live, x4compat listed it in 4 collision rows, and **Tier B would resolve a cross-mod
  selector against it and report OK — a false pass in the mode built to catch silent no-ops.**
  Verified per item: compat 445→445 rows, the same 4 rows minus that mod, **0 winner changes**;
  x4eff 10,799→10,789; x4raw unchanged (it correctly asks the other question); Tier B findings
  byte-identical across the 6 highest-overlap mods, so that repair is preventive, not corrective.

- **The variant-sibling check was blind to packed mods** (F22, re-scoped from "scope gap costing 0").
  All three of its enumerations walked loose files on disk. Of **378** variant-macro files it could
  reach **14 (3.7%)**. Now 378 are examined and it reports **3 real findings**. The identical defect
  was fixed in the function directly above it on 2026-07-26 and never carried across; an
  unresolvable owner is now `report.skip`, not silence.

- `build-effective.py` no longer emits **70+ spurious warning lines** per build (`_cat.mod_vfs`
  without `packed_only=True`, at a call site where the loose half is directly above).

### Added

- `tests/test_no_loose_only_reference_walk.py` — bans a loose-only `reference/` walk across
  `x4validate/`, `gates/` and `tools/basex/`. All 6 surviving sites were hand-verified before it was
  allowed to gate. Raises on a parse failure rather than skipping the file.
- `tests/test_mod_scope_is_explicit.py` — bans bare `scan_installed`, requires the scope to be a
  **literal** (a computed scope puts the choice back out of sight), and asserts both scopes remain in
  use so the API cannot become decorative.
- `tests/test_similarity_weights_pinned.py` — pins x4similar's weights equal to its oracle's
  hand-duplicated copy. The duplication is correct and stays; the silence about drift does not.
  Read by AST, never imported, so it works with no game installed.
- `gates/tool_properties.py` — mod-scope agreement: the store's mod set and x4eff's manifest must
  match **and** both be the ACTIVE set (two artifacts can agree while both modelling the wrong world).
- `gates/README.md` now documents `claims_audit.py`, which was undocumented since it was added.
- `tests/test_basex_tests_are_not_orphaned.py` — the 23 tests under `tools/basex/` PASSED but were
  never collected (`testpaths = ["tests"]`), so the suite reported green while saying nothing
  about `ask.py` (which gates every negative claim) and `staleness.py` (the freshness contract).
  They now run, and SKIP with a reason where the dev-only BaseX tooling is absent.
- `_effective.base_vpaths` is memoized (**2.25 s → 0.004 s** warm). Uncached it was re-derived per
  mod: the variant sweep over 115 mods went **47.6 s → 2.4 s**, same 3 findings.

### Changed

- `gates/tool_properties.py` re-pins F33's attr axis at **0** (a regression now fails); the entity
  axis stays pinned at 63 with its reason.
- `docs/BLIND-SPOTS.md`: F34/F35/F36/F37 registered; **F3's figures refreshed** (balance-relevant
  coverage **99.8%**, 3 of 1,916) and its scope confirmed rather than widened; F8 closed WONTFIX with
  a drift guard; F22 corrected with its wrong denominator called out; F33 split into a fixed axis and
  an open one.
- Suite **577 → 595**.

### Note on how these were found

None came from a user report. F34 and F35 came from two tools disagreeing about the same corpus; F37
came from F3's refreshed coverage leaving exactly three macros unaccounted for, and chasing those
three to ground. The alternative — writing "3 unexplained misses" into the register and moving on —
was one keystroke away, and would have left a false-pass path in Tier B in place.

Sixteen checking-step errors were made and caught during this work, and in **16 of 16 the checker was
wrong, not the finding** — including counting a *set* where a multiset was needed, comparing against
`kind='macro'` when ship macros are filed under `ship`, and running an AST scan on Python 3.10 that
could not parse a PEP 701 f-string. That base rate is the reason every number above was diffed per
item and predicted before it was measured.

---

## v2.3.0

### ⚠ BREAKING (output schema) — `Collision.winner` for SUBTREE rows

**This is a breaking change to tool OUTPUT shipped under a MINOR version bump.** SemVer is being
applied to the CLI *contract* (flags, exit codes), which is unchanged; the JSON payload moved. The
version number therefore does **not** signal this, and that is precisely why it is the first entry.

`Collision.winner` never meant one thing. For FULL-OVERRIDE / HARD / UNION-KEY it names the mod
whose value is **live**. For **SUBTREE it named the mod that did the WIPING** — which is not the
owner of the final value, because a third mod loading later can re-supply what was wiped.

    SUBTREE rows:   winner: "<mod>"   ->   winner: ""      + new key  wiped_by: "<mod>"

**Migration:**

| you want | before | now |
|---|---|---|
| the mod that wiped the subtree | `winner` | `wiped_by` |
| the mod whose value is actually live | `winner` (WRONG for SUBTREE) | `live_value_owner()` — returns `None` for SUBTREE / NAME-CLASH / SOFT, where naming one would be a guess |

`live_value_owner()` returning `None` is an answer, not a failure: it is the tool declining to
invent a winner it cannot know.

**Measured drift on the live modlist (115 mods), diffed PER ROW, not by totals:**

- 445 collision rows before, **445 after** — 0 added, 0 removed
- `winner` changed on **exactly 148 rows**, and all 148 are SUBTREE
- `detail` changed on **0** rows; every other field **0**
- a wipe later undone by another mod: **3 of 148 (2.0%)** — so the advisory is not noise

**Why it was worth breaking.** An inbound bug report claimed x4compat's winner was wrong for ~7
attributes across 2 Kha'ak ships and 1 engine. Re-measured: **x4compat was correct** and the report
had compared a SUBTREE `winner` against `x4effective`'s `origin` — two different questions. One
field answering two questions is a defect even when every value in it is right. See BLIND-SPOTS
**F25** (the report) and **F30** (the fix), and CLAUDE.md gotcha #18.

### Fixed

- **F27 — `md/` scripts were merged as if they were assets.** The engine registers MD scripts by
  **filename**, so a complete `<mdscript>` shipped at a vpath the base game already supplies is
  **inert** — it loads and its cues never take effect, with no error line anywhere. Our merge
  returned the mod's file; the engine was running vanilla's. `_merge` now returns mode
  `script(inert)` for that case, so `x4effective dump md/setup.xml` returns vanilla's **1,784-line**
  `Setup` instead of a mod's 44-line file. **Exactly 1 vpath of 299 changed hands.**

  *(Two line counts appear in the records and both are correct: the raw
  `reference\md\setup.xml` on disk is **1,795** lines; `dump` re-serialises through lxml and emits
  **1,784**. Neither is a typo for the other — MEASURED 2026-08-22.)*

  Mechanism **proven by controlled experiment**, not inferred: a uniquely-named mdscript in an
  overlay registers and runs, while a functionally identical script at the colliding vpath does not
  — same cue structure, same actions, same load position, both script `name=` differing from
  vanilla's, leaving the FILE PATH as the only variable.

  Scoped to `md/` **only**. `aiscripts/` is deliberately excluded: the corpus contains **zero**
  instances to verify a generalisation against, and `gates/tool_properties.py` carries a tripwire
  that fails the moment a real one appears.

- **F26 — `gates/cross_tool.py` verified one collision kind of five.** It checked FULL-OVERRIDE
  only: **14 of 445 rows (3.1%)**, with HARD / SUBTREE / UNION-KEY never checked against the store
  at all. Now asserts per kind, over the full population: FULL-OVERRIDE 14/14 · HARD 40/40 ·
  UNION-KEY 2/2 · SUBTREE 148/148 · NAME-CLASH 20/20 — **0 disagreements**.

  A single blanket assertion would have been wrong three different ways, and each wrong form was
  written and measured before being discarded — see F26 for the two checker bugs it produced.

- **F28 — a known-partial checker was presented as a completeness GATE.** `--entity ship:x
  --like ship:y` compares the `<ware>` wrapper only; the macro interior (physics, connections,
  engine/shield/turret slots, storage, hull, software, steering curves) was never examined, and a
  clean result read as "the ship is complete". It now declares the gap through the skip channel.

- **F29 — `_cat.mod_vfs` returned `{}` for a loose mod and said nothing.** Catalogs-only by nature,
  but silent about it: one corpus scan read **2,681 files instead of 4,401** and reported NOT FOUND.
  Now takes `packed_only=` and warns when a caller has not acknowledged the limit, enforced by an
  AST guard (`tests/test_no_packed_only_scan.py`) that accepts an inline `# packed-ok:` marker.

- **F31 — `<module group=>` was checked by nothing.** `modulegroups` was not an indexed registry and
  `module/@group` was unknown to `_refs`, so the engine rejected 3 references **43× per launch**
  while we reported the mod clean. Added as the 21st registry plus `check_module_groups`;
  engine-verified. Corpus: 146 groups, 22 references, **3 dangling in 1 of 115 mods**.

### Added

- `CHANGELOG.md` (this file).
- `tests/test_blind_spots_ids.py` — the register may not hand the same F-id to two findings. Written
  after two **concurrent sessions** each created a `## F30`, caught only by eye. Also pins the
  register's known bookkeeping gaps so new drift fails loudly.
- `_scan.iter_corpus_xml` + `CorpusScan` — one way to sweep every installed mod's XML, excluding
  `ego_dlc_*`, recording unreadable files, and **raising rather than rendering a zero** when nothing
  parsed. The hand-rolled form of this loop had been written **7 times** and was wrong in at least 3.
- **Summary-table integrity check** in `tests/test_blind_spots_ids.py`. A markdown row with fewer
  cells than the header does not fail to render — it renders **wrong**, shifting cells left and
  blanking the tail. That is how 15 register rows displayed an empty Status for weeks. The
  escape-aware cell splitter lives here once, with its own proven-to-fail test, so nobody hand-rolls
  `awk -F'|'` again (which cannot see a `\|` escape and calls a valid row malformed).
- **`check_store_key_uniqueness`** in `gates/tool_properties.py` — pins F33's measured duplicate-key
  counts (63 entity groups, 627 attr groups) so a known-open defect cannot grow in silence. A stale
  or absent store **SKIPS with a reason** rather than reading as a pass.

### Documentation

- `docs/BLIND-SPOTS.md`: every entry **re-verified against the code** and given an explicit STATE.
  The summary table was repaired in the same pass — it was missing **6 findings outright**
  (F21, F25, F26, F28, F29, F30) and **15 rows carried 4 of the header's 5 cells**, so their Status
  column rendered blank.
- **F33 (new)** — a non-unique key read with a singular read, measured and **left open**: 63
  duplicate `(kind,name)` entity groups (23 diverge) and 627 duplicate `(entity_id,prop)` groups
  (**201 diverge**). Identical pre- and post-rebuild, so pre-existing. **0 of 21** recorded claims
  resolve through an ambiguous key, so `claims_audit`'s 21/21 PASS is sound.
- **F32** — a dev-only *variant* is validated against a tree containing its own ops; documented as a
  scope limit and deliberately not "fixed", because the obvious relaxation trades a visible false
  alarm for an invisible false OK.

### Notes

- Suite **561 passing**. `gates/qa_sweep.py` 45 GREEN / 0 YELLOW / 0 RED.
- Effective store rebuilt 2026-08-22. Both freshness axes had moved (engine, via the F27 `_merge`
  change; content, via a redeployed overlay). Diffed per item against the pre-rebuild store:
  **0 entities added/removed, 0 attrs added/removed, 0 values changed, 0 origins changed** —
  confirming the F27 change has no blast radius outside `md/`.

## v2.2.1

**Nested cross-mod patches now apply through the owner's-file door too.**

`build_effective` handled `extensions/<owner>/<rel>` only when the *requested* vpath was
itself the nested path. Building the OWNER's plain vpath — which is what the effective
store does for every file — consulted only each overlay's bare `<vpath>`, so a later mod's
nested patch was invisible. Two doors to one logical file, two different answers: Tier B
(nested door) said a real add-on's 27 whole-file bullet overrides resolve; `x4effective`
(plain door) attributed every one of those values to the owner. The engine has ONE
document (F19, engine-proven), so the plain door was wrong.

Found because two of our own tools disagreed about the same value — cross-tool
disagreement is a defect signal, and this time it was real.

- The plain-door build now probes each later overlay for `extensions/<owner>/<vpath>`
  whenever an earlier overlay supplied the file, applying nested diffs (which are exempt
  from the bare-diff inert rule — the engine loads them) and nested full overrides.
- The store's touch map registers a nested patch under its owner's rel, so the patcher is
  handed to the merge and the phantom duplicate entity at the nested vpath disappears.
  **Single-level nesting only** — a double-nested file (a patch on another mod's patch
  file) keeps its old behavior, because the engine's handling of that shape is unproven
  and one installed mod ships both forms (rewriting it double-applied its ops).
- An applied nested `<remove>` now really removes: one installed add-on deletes a ship it
  rebalances elsewhere, and the old code resurrected it in the effective tree.

Measured impact on a real 114-mod install, full old-vs-new differential with **every**
changed row attributed and **0 unexplained**: 834 attribute values changed owner or value,
27 entity origins moved to the real winner, 60 phantom duplicates removed, 21 rows from
the now-honoured `<remove>`. `x4compat` was verified NOT to share the blindness (it
already aliases owner files under the nested key), and the engine oracles, noop/provenance/
consistency audits, determinism and the per-mod perf guard all pass unchanged.

Suite 392 → **397** (5 regression tests pin both doors agreeing, the inert bare-diff rule
surviving, and the nested `<remove>`).

## v2.2.0

**A guessed mod identity can no longer be laundered into a fact.** The registry stored a
fuzzy name match and a human-verified id in the *same field*, so a row whose identity was
invented by a search still read `settled: stable` / `classification: ready`. Measured on a
real 100-mod install: **3 of 100 identities were actually confirmed** — the other 97 were
guesses or blanks, all rendered with the same confidence as the 3.

Guessing is still fine. Guessing *silently* is not.

### Identity provenance

- **`auto.id_state` on every row** — `pinned` · `exact` · `guess` · `ambiguous` ·
  `unmatched` · `off-nexus` · `unsearched`. A stored id now always says how it was obtained.
- **Nothing derived from an untrusted id may reach a confident lane.** `classification` and
  `settled` are computed from upstream data fetched *using* the id, so they are only ever as
  good as the id. A guess is capped at the new `needs-confirmation` lane no matter how
  healthy the fetch looked — the reassuring part may describe somebody else's mod. This is
  the load-bearing invariant, and `gates/registry_provenance.py` proves it over the whole
  real registry (and was verified to FAIL when a single row is tampered).
- **Ambiguity is a real outcome.** `_match_strength` replaces a boolean "plausible?" with
  strong/weak/none, and the resolver now stores **no id at all** when two or more candidates
  are equally weak, instead of taking the first. The case that forced this: one mod name
  shares a single filler-ish token with several unrelated mods, and the true answer was
  unreachable by name search entirely.
- **Migration promotes nothing.** Every historical `auto (spot-check)` becomes `guess`, and
  a confident lane computed *before* the cap existed is withdrawn rather than grandfathered.
  Downgrading a real match costs one spot-check; upgrading a bad one re-creates the defect.

### Human-owned identity (permanent, never overwritten by a refresh)

- **`x4modlist resolve <id> <nexus_id> [--file <file_id>]`** now pins into `human:`.
- **`--file`: a mod is not always a page.** Plenty of add-ons ship as a *file* on someone
  else's mod page, where the page's version tracks a different release cadence entirely.
  Update-detection now compares the **file's** version and upload date (`_nexus.fetch_file`,
  which raises when the file is no longer listed — being superseded is information, not a
  lookup failure).
- **`x4modlist resolve <id> none`** and **`x4modlist source <id> steam:…|local|bundled:…|<url>`**
  record a mod with no Nexus page — Workshop items, bundled add-ons, your own overlays. They
  stop being searched, and move out of `untriaged` (which implied unfinished work) into a new
  `off-nexus` lane.

### Seeing it

- **`x4modlist verify`** — the burn-down list, with the denominator stated. Exit 1 while any
  identity is unconfirmed, so it works as a gate.
- **`verify --rescore`** — offline promotion of `guess` → `exact`, but **only** where the
  installed manifest name is *identical* to the stored upstream title. Containment is
  deliberately not enough: one real row's stored title merely *contains* the mod's name and
  is a different mod.
- The dashboard prints `N/M confirmed`, labels every row's provenance in its own lane table,
  and `refresh` refuses to end on a clean-sounding summary while unconfirmed rows remain.

Suite 379 → **392**. Gates 24 → **25**. QA sweep 38 → 41 cells.

## v2.1.1

**`--update` is no longer a 2-minute wait, and the whole toolkit's output has now been
verified exhaustively against independent ground truth.** 17 findings fixed across the
campaign, suite 363 → 379, 20 → 24 gates.

### Faster

- **`--update --xsd-fast`: ~112 s → ~2.5 s.** The gating class — `attribute X is required
  but missing`, the one reliable 9.0 migration signal — is a flat fact per element and
  needs no schema compile. It is now extracted by plain parsing (~0.05 s), scoped to the
  include-closure of the schema each document declares. Both passes still run by default,
  so nothing is lost; the flag skips only the slow advisory compile.
- The slow compile now **announces itself** instead of sitting silent for two minutes
  (a quiet spell that long reads as a hang), and only for the schemas that genuinely
  cost minutes.
- Corrected a false explanation in docs/comments: the compile cost was never "it includes
  the huge common.xsd" (that compiles in 0.03 s) — it is the recursive `actions` content
  model in `md.xsd`/`aiscripts.xsd`.

### Fixed

- **`--update` was blind to packed mods** in both the XSD and migration-heuristic passes —
  on a packed mod it examined zero script files and reported a clean 9.0 port. 33 installed
  packed mods were affected on the reference modlist.
- **9 false gating ERRORs demoted**: `md.xsd` does not model `<ammunition>` under
  `<create_ship>`, but the engine accepts it (verified against a live engine log). Now an
  advisory with the evidence inline, via an allowlist whose entry bar is engine evidence.
- A DLC-verdict message asserted "is installed" for extensions it never checked; it now
  looks in the game root and distinguishes installed-but-unreadable / not-installed /
  no-game-root.
- Two concurrent `x4effective build`s raced on one temp file and both died; the temp is
  now PID-qualified and the loser reports an actionable message. `build --kinds <typo>`
  no longer writes an empty store and exits 0.
- `x4compat` gained a **NAME-CLASH** collision class: two mods defining the same macro
  name in *different* files. X4 resolves macros by name through `index/macros.xml`, so
  only one definition is ever loaded and the other is dead content — structurally
  invisible to per-path collision scans. No load-order winner is claimed, because the
  index decides, not load order.

### Verified

- **`gates/xsd_fast_parity.py`** — the fast path proven set-equal to libxml2 over every
  script file in the corpus (it caught three would-be false-positive bugs during its own
  development; none reached a release).
- **Exhaustive output audits, shipped as gates**: every xref citation resolves to its
  exact line (packed and DLC included) · every stats value matches a fresh parse · every
  reported similar-pair recomputes to its printed score · planted mutations on real
  content are reported exactly (`tool_properties --exhaustive`, `similar_audit`,
  `diff_truth`).
- **`gates/perf_guard.py`** — per-mod runtime vs a machine-local baseline (aggregates
  hide regressions: a real 39×/51× slowdown summed to a 1.00× total), proven to fire.
- An old-vs-new output differential across the full modlist: zero unexplained changes.

### Docs

- **`docs/QA-PROCESS.md`** — the formal QA process for new tools, distilled from this
  campaign: contracts at design time, property tests, generative/perturbing techniques,
  differential and oracle testing, real-workflow use, the exhaustive output audit, and a
  stopping criterion that is a discovery curve rather than a feeling.

## v2.1.0

**If you run a total-conversion overhaul, take this update.** A `<replace>` whose selector resolved
to a document *root* was silently discarded — and reported as applied. On a 123-mod install that was
**858 mod operations** the tools never applied while telling you they had. Suite 316 → 333, six new
corpus gates, all four engine gates green.

### Fixed — the tools reported values the game does not use

- **`<replace sel="//macros">` was dropped.** That selector matches the document root, and a root
  has no parent to swap it through, so the operation was abandoned by a bare `continue` — while
  `apply_diff` still recorded `applied=True`. It is not an exotic form: it is the standard
  whole-file override idiom. One overhaul alone ships **848** of them, covering ships, weapons,
  engines, shields and bullets; two other mods contributed 10 more.
  **Consequence:** `x4effective`, `x4stats` and anything reading effective *values* reported the
  vanilla number wherever a mod had overridden it. After the fix, one overhaul went from owning
  **0** shield generators to **101** — matching exactly what its archive ships.
  *The engine was never affected*: it applies these operations and logs no complaint (it logs 467
  patch failures of two other shapes, and none of this one).
  **`x4compat` was proven unaffected** — same modlist before and after gives 419 rows, 0 added,
  0 removed, **0 winner changes** — because collision topology and load-order winners do not depend
  on whether a value landed.

- **A helper that could not apply an operation now says so.** `_do_replace` / `_do_remove` /
  `_do_add` return a reason, and `apply_diff` derives `AppliedOp.ok` from it instead of hard-coding
  `True`. That closes the *class*: any future unhandled case surfaces as "not applied, here's why"
  rather than a silent success.

- **`x4validate --file <missing>` crashed** with a raw lxml `OSError` traceback instead of telling
  you the path was wrong. A typo should not produce a stack trace.

- **`x4similar --threshold` accepted values outside 0–1.** A similarity score is a ratio;
  `--threshold -1` matched every ship against every other and emitted 1.7 MB of meaningless output.

- **`install.sh` could not auto-detect your game on Windows or macOS.** The Steam-root loop used
  an unquoted command substitution, so every path containing a space was word-split —
  `/c/Program Files (x86)/Steam` became three fragments. Only Linux (whose default paths have no
  spaces) ever worked, and the `libraryfolders.vdf` fallback was unreachable for the same reason.

- **`install.ps1` printed "install complete" after a failed unpack.** `$ErrorActionPreference` does
  not trap a native exit code, so a failing step was invisible. It now checks each step, reports
  which one failed, and exits non-zero. It also passes `CLAUDE_PROJECT_DIR` (the shell installer
  always did), so running it from a shell that already exports one no longer wires up the wrong
  folder — and the "bash not found" message now names the actual fix, since Git for Windows puts
  `bash.exe` in a directory it does not add to PATH by default.

- **`x4compat check` emitted its findings in a non-deterministic order.** Two identical runs
  produced the same 419 collisions in different orders, because a set's iteration order (which
  varies per process) leaked into the report. The *content* was never wrong — but it made every
  baseline diff noisy, which is how a real change hides. Now sorted at the source and at the
  reporting boundary.

- **No tool could tell you which build it was.** All eight CLIs now accept `--version`, and the
  package version is 2.1.0 (it had been left at 0.1.0).

### Added — gates that hunt the class, not the instance

That defect survived three sessions because nothing ever exercised the path. Six new contributor
gates now run against **your** installed modlist rather than fixtures:

- `noop_audit.py` — every operation of every installed mod applied against its real base document,
  comparing what the tool *reports* to what the tree *does*. **13,332 ops: 0 false OK, 0 false
  alarm.** Also surfaces mod XML that will not parse.
- `provenance_audit.py` — a changed value must name the mod that changed it. **3,709 values,
  917 mod-changed: 0 mis-attributed.**
- `consistency_audit.py` — the store, `build_effective` and `x4effective dump` are three paths to
  one truth and must agree. **120 sampled values: 0 disagreements.**
- `corpus_sweep.py` — `x4validate` over every installed mod, both tiers. **230 runs, 0 crashes.**
- `qa_sweep.py` — every CLI × every subcommand; targets discovered from your install, never named.
- `edge_sweep.py` — hostile inputs (empty mods, malformed manifests, SQL injection, path traversal,
  an unconfigured environment). The bar is *fail well*, and it needs no game paths.

- `determinism_audit.py` — the same command twice must give byte-identical output, and a rebuilt
  store must be logically identical. Without this, every recorded baseline is noise.
- `stress_sweep.py` — unseen mod corpora, chained tools, and deliberately pathological XML
  (entity bombs, XXE, 400-deep nesting, cyclic cross-mod patches, unicode with RTL overrides).

**Known characteristic, measured not guessed:** `apply_diff` is O(n²) in operations-per-file —
doubling the ops multiplies time by ~2.8→3.7×. It is not fixed here because severity is low by
measurement (the worst real file in a ~120-mod install is 1,443 ops, about 0.03 s — roughly 22×
headroom) and the fix would touch selector evaluation, the exact path this release exists to make
trustworthy.

The silent-swallow AST guard now also covers **control-flow** swallows in the diff mutators. The
pre-existing guard only inspected `except` handlers, so it could not have caught this one.

### Changed

- `schema_sweep` re-baselined to 168 pairs · 59 gating · 70 advisory · 42 mods flagged — attributed
  per mod (three added mods contribute 1 gating + 2 advisory; one removed mod took 2 + 9 with it),
  so the arithmetic closes rather than being asserted.

## v2.02

**If you use `--tier b` or the schema checks, take this update.** A red-team audit of the whole
toolkit (19 findings, every one dispositioned with measurements) found two defects that made
*clean results lie*, plus a class of cross-mod collisions nothing detected. All fixed here.
Suite 303 → 316, every fix mutation-verified, all four engine gates green (oracle 234/234).

### Fixed — results you could not trust

- **Schema checks looked up XSDs by basename in `libraries/` only.** Every schema whose XSD lives
  elsewhere (`index/`, `assets/`, cutscenes) was skipped as "not bundled" — all 31 such skips in a
  102-mod install were false. Schema coverage went 127 → 159 element-attribute pairs; the skips
  dropped to 1 (honest: a shader XSD the game truly does not ship).
- **Tier B blessed a cross-mod patch the engine never loads.** A `<diff>` at a BARE mirrored path
  targeting another MOD's file is never opened by X4 — only the nested
  `extensions/<owner>/<rel>` form works (engine-proven twice over: the same 7 files were absent
  from the engine's per-file log at the bare path and present after moving to the nested path,
  zero rejected ops). Tier B used to report such a mod **0 errors, exit 0**. Now it is an ERROR
  naming the owning mod and the exact path to move to, and the effective-tree model refuses the
  dead diff — `x4effective`/`x4stats` no longer show values the engine never sees (14 such lied
  values in the reference install, now 0). Language files (`t/*.xml`) are exempt: the engine
  always supplies the language tree.
- **`x4compat` could not analyze any cross-mod nested patch.** The owner extension was never
  supplied when building the comparison base, so every `extensions/<owner>/...` diff was silently
  discarded — 140 of 523 files in the reference install. They are analyzed now.

### New — collisions that were invisible

- **SUBTREE collisions.** A later-loading mod that `replace`s or `remove`s an element wipes every
  earlier mod's edit inside that subtree. Order-aware (a wipe loading *first* is the other mods'
  sel-check problem, not a collision), reported as hard-ish with the load-order caveat on every
  row. The reference install surfaced 153 — dominated by an overhaul wholesale-replacing engine
  macros another mod had tuned.
- **Duplicate-id detection now keys by `@id` first and spans whole documents.** A ware's `name=`
  is a `{page,text}` reference, not an identity — keying name-first hid an engine-confirmed
  same-id ware collision behind display-text noise, and per-anchor grouping missed same-id adds
  under different anchors. Mod-vs-BASE re-adds stay benign (measured: an engine-tolerated idiom
  used 476 times across major overhauls; the engine's own duplicate detector complained only
  about mod-vs-mod pairs).

### Fixed — found by red-teaming this release's own install flow (a v2.01 tradition)

- **The PowerShell installer wrote its config with a UTF-8 BOM** (Windows PowerShell 5.1's
  `-Encoding UTF8`), which bash reads as a command — so `bin/unpack-reference.sh`, the step that
  builds `reference/`, exited 127 on line 1 of `x4-paths.env`, and with `-Unpack` the installer
  still printed "install complete". The Python half tolerated the BOM, so the README's own verify
  step passed and the break only surfaced later. All installer writes are now BOM-free (and the
  bash-sourced config is written LF).
- **`x4modlist` no longer guesses CWD-relative paths.** Unconfigured, it either ingested whatever
  `content.xml` the working directory happened to hold, or reported "PRIMARY, 0 found" with
  exit 0 — "you have no mods" as a statement about your modlist instead of the missing setting.
  Every unresolved location is now a named refusal (exit 2, tells you the setting and points at
  `x4validate --paths`), the SECONDARY cross-check announces itself when skipped, and ingest
  prints the roots it scanned so "0 found" is auditable. Pinned by tests including a source-level
  guard on the fallback pattern itself.
- **The `global` install method no longer rewrites other people's skills/agents.** The
  `$CLAUDE_PROJECT_DIR` → `$X4_TOOLKIT` rewrite now touches only the files the installer itself
  just copied — a pre-existing agent in `~/.claude` that uses that variable on purpose is left
  alone.
- Windows Setup now leads with `powershell -ExecutionPolicy Bypass -File install.ps1` (a stock
  Windows install refuses a bare `.\install.ps1` before it runs anything) · `bin/xrcat` is pinned
  LF in `.gitattributes` and both OS branches now say "XRCatTool not found — set $XRCATTOOL"
  instead of a bare exec failure · `scripts/generate-baseline.sh` reads `x4-paths.env`
  (`X4_GAME`/`X4_PROFILE`) like everything else · the `x4-debug` and `x4-modlist-review` skills
  now give the configurable paths (and the Linux profile location) instead of hardcoded
  Windows ones · stale claims fixed (test count, "bundled" uv, "read automatically").

### Changed

- **Two advisory classes now gate as errors, on individually-verified evidence:** an enum value
  neither the XSD floor nor the whole effective tree defines (`schema-enum-undefined`), and an
  attribute on an element vanilla never pairs it with (`schema-dead-attr` — pair granularity
  matters: one real attribute on the wrong element was excusable at name level). MD-script
  unknown attributes stay advisory by design: spawn-time behavior cannot be settled statically,
  and a working released mod outranks a schema's opinion.
- **Version catalogs (`ext_vNNN.cat`): the skip is now known-correct.** Researched and
  engine-proven: X4 loads a version catalog only when the game version matches its `vNNN`
  *exactly* — a stale one is dead weight the engine ignores too. The skip warning now states the
  rule instead of guessing.
- Exit-code contract documented in the README (0 clean / 1 findings / 2 could-not-run /
  3 degraded), including why "the validator was blindfolded" is deliberately not "your mod is
  broken".

## v2.01

**If you installed v2.0, take this update.** v2.0 shipped an installer that wrote one set of
environment variables and Python tools that read a different set. They overlapped on exactly one
name (`X4_REFERENCE`), and nothing bridged them — so on the **`separate`** and **`global`**
layouts, two of the three the README documents, a *successful* install still left `--tier b`,
`x4compat`, `x4stats`, `x4similar`, `x4xref`, `x4modlist` and `x4effective` resolving against
CWD-relative paths. They did not error; they looked in the wrong place and reported finding
nothing. The README's claim that "nothing is hardcoded" was true of the shell half and false of
the Python half.

### Fixed — the installed toolkit is actually wired up

- **One resolver for every location** (`x4validate/_paths.py`), layered: real environment →
  `.claude/x4-paths.env` → an explicit (empty) local seam. Within each layer, every alias *and*
  derivation is tried before dropping to the next. Both naming schemes work; the installer's names
  (`X4_GAME`, `X4_EXTENSIONS`, `X4_PROFILE`, `X4_MODS`, `X4_REFERENCE`) are the ones to teach.
- **`x4validate --paths`** — prints what resolved and which config file was read, marking anything
  that does not exist. Run it first when a result looks impossible.
- **Bare `--debug` was Windows-only.** It built `~/Documents/Egosoft/X4/<id>/debug.txt` — the
  Windows layout, hardcoded — so it could never work on Linux (`~/.config/EgoSoft/X4/<id>`) or
  macOS, both of which this toolkit documents and supports.
- **Two silent degradations closed.** With the game root unresolved, the packed mini-DLC dropped
  from 8 DLC to 6 with nothing reported (every patch against Hyperion/Envoy content quietly
  became "cannot verify"); an unresolved registry read as "0 mods" rather than "not configured".
  Both now name the loss.
- **Git Bash paths now work.** `install.sh` detects Steam at `/c/Program Files (x86)/...` under
  Git Bash, and the config file has always promised either style is fine. Python cannot open
  `/c/...` on Windows — it becomes `\c\...`, which does not exist. So the *first command the
  README gives a Windows user* wrote a config the Python silently could not use. `/c/...` and
  `/mnt/c/...` are now translated on Windows and left untouched on Linux, where they are
  legitimate paths. **Found by red-teaming this release's own install flow.**
- **`X4_TOOLKIT` is no longer claimed to be set for you.** The docs said "(the installer does)";
  no installer ever did. Both installers now print the exact `setx` / `export` command at the end,
  and the READMEs give it instead of the claim. Without it the config file is found only by
  walking up from the current directory, which fails from the game folder — the case the docs
  themselves call out as common.
- **Nothing is guessed.** An unresolved location prints `(unresolved)`; the Steam workshop path is
  derived only when the install really has that shape, because a guessed path scans nothing and
  would report "no mods" as though it were a finding.

### Fixed — patch-time and runtime are two different trees

A `sel=` sees only what has loaded by your mod's turn; "does this id exist?" is answered after
*every* extension has loaded. Tier B used one tree for both, which is wrong in both directions —
measured on a real pair of installed mods: 3 false alarms in one direction, and one genuine
runtime defect missed in the other (a loadout referencing a connection that the winning component
does not have). The trees are now separate.

### Added — schema validation of merged data files (`--update`)

42 vanilla files under `libraries/` declare an XSD, and mods ship them as `<diff>`, so the
document that has to be valid is the *merged* one. This catches a class nothing else here can: a
patch whose selector matches and whose XML is well-formed, but which leaves the merged document
structurally broken — measured case, a mod that `<remove>`s `<production>` and orphans the
`<limits>` sibling 30 times.

It is **differential**, which is not a refinement but the only workable form: Egosoft's own
base+DLC data produces 66 errors against Egosoft's own bundled schemas, so an absolute check would
open with 66 false positives on a mod that changed nothing. Enumeration failures naming a race or
faction your modlist actually defines are suppressed and counted; one naming something nothing
defines is reported.

### Added — `gates/`, so the engine-fidelity numbers are reproducible

The four harnesses that measure this tool against the engine rather than against itself:
`oracle.py` (diff layer, 234/234 ops, 0 false OK), `oracle_index.py` (index layer, 12/12),
`regress.py`, `schema_sweep.py`. They take every input from your configuration and **skip with a
named reason (exit 2)** when something is missing, rather than running empty and printing like a
pass. You supply your own captured `debug.txt` via `$X4_ORACLE_LOG` — a real log names your mods
and paths, so none is shipped. What transfers is the bars, not the counts.

### Measured and deliberately NOT shipped

An MD ordering lint (flagging `signal_cue_instantly` to a cue that cannot be listening yet) was
built and dropped. It scored **0 false positives** across 1,094 vanilla call sites and 2,912 in
installed mods — and also **0 on a saved copy of the exact bug it was written for**. The real
defect reaches its target through a variable, from a second cue, so a rule keyed on a literal name
cannot see it; widening it to catch that fires 407 times in vanilla code that demonstrably works.
A rule with no demonstrated true positive is not quiet, it is inert. Recorded here because a
changelog that only ever adds is a sales sheet.

### Also

- 243 → **264** tests.
- Docs: the root README now shows how to actually invoke `x4validate` and links to the
  configuration model; `x4-paths.env.example` states that `$VAR` expands and that the file is
  parsed, never executed; `gates/README.md` says up front that it is for contributors only.
- Every number above traces to a gate run, not to a claim.

## v2.0

**The toolkit is no longer Windows-only, and no longer assumes one folder layout.** Plus two
community contributions, a round of safety-hook fixes found by red-teaming the install flow, and
a `debug.txt`-driven oracle that measured x4validate's verdicts against what the engine actually
did — closing every gap it found.

Major version because the install model changed: there are now three supported layouts and every
X4 location is configurable. Existing v1.x users keep working — the in-game layout is unchanged
and the hooks fall back to the old folder-name patterns when nothing is configured.

### Fixed — x4validate: validated against the ENGINE, not against itself

x4validate's model of the engine had never been checked against the engine's own output. This
built and ran that check: a `debug.txt`-driven oracle that measures x4validate's verdicts against
what X4 actually did, op-for-op. Every defect below was found and fixed using it — not by
inspection. Tests grew to 170, and none of them are cosmetic: each is a real-data regression test
for a real false result, several mutation-verified against the pre-fix code to confirm they
actually catch it.

**The tool was blind to 9 of the 10 mods with the errors that matter, and said "OK":**
- **Packed mods were never sel-checked, and reported a clean pass.** `iter_diff_files` walked
  `mod_dir.rglob("*.xml")`, which finds nothing inside a `.cat`/`.dat` archive — so the core
  sel-resolution check silently examined zero ops on any packed mod and printed
  `OK: no issues found`, exit 0. Sibling code (`iter_mod_xml_roots`) already read packed mods via
  the catalog reader; the core check simply never used it. Measured against a real debug.txt: **9
  of 10 mods with engine-rejected diff ops are packed** — this covered most of the real damage.
  Fixed by delegating to the packed-aware iterator; a mod where nothing could be read is now a
  WARN, never a silent pass.
- **`--debug` correlation missed 74% of the log, and 100% of the class it exists to catch.**
  `_debuglog.parse_debug` recognized 4 error shapes; a real 2463-line `debug.txt` showed it
  returning 645 (26%) — and **zero** of the 453 "diff op matched 0 or >1 nodes" lines, the
  RFC-5261 failure this tool is built around. Two new shapes fixed it (453/453 now captured),
  after finding two parser traps: the engine omits the file extension on these lines (`'…\
  material_library'`, not `…material_library.xml`), and the selector itself contains single
  quotes (`@id='ore'`) in 91% of real cases, which a naive `[^']*` capture group truncates.
- **Tier B applied the mod under test LAST — the engine does not.** Cross-mod validation merged
  every *other* installed mod, then applied the mod under test on top — a tree that never exists
  at the moment the engine actually applies that mod's patches. A node added by a
  **later-loading** mod looked present when it should not have. Fixed by truncating the merge at
  the mod's own load-order position. Measured on a real 192-op case: **27 false "OK" results,
  now 0** — full agreement with the engine, verified op-for-op.
- **One malformed overlay file crashed validation of every OTHER mod that touched the same
  path.** An `XMLSyntaxError` while reading an overlay escaped uncaught; exit code 1 made a crash
  indistinguishable from "found real errors." Now recorded and reported as a WARN naming the mod
  and file, never a crash.
- **A patch targeting an uninstalled mod is a designed no-op, not an error.** Compatibility-patch
  mods commonly ship nested cross-mod patches for dozens of optional targets. Enabling packed
  input surfaced this loudly (one mod went from 0 to 76 reported errors, 72 of them for targets
  simply not installed). Now reported as INFO, the same treatment already given to a
  false `if=` guard. **76 errors → 4 errors + 72 info** on that mod.
- **A DLC installed-but-never-unpacked-into-`reference/` reported a hard ERROR asserting content
  doesn't exist** — something the tool cannot actually know. Now reported as an honest
  "cannot verify" INFO naming the DLC, not a false ERROR.

**x4modlist auto-resolved ~10% of mods to the wrong Nexus page:** `_resolve_identity` accepted
the top search hit unconditionally. Measured on a live 101-mod registry: **7 of 69 resolved
entries pointed at an unrelated mod**, most flagged `settled: stable` — silently tracking someone
else's update history. Root cause: a multi-word Nexus search can return zero hits where a
single-word search returns several correct ones, and the empty-result fallback (drop the leading
word and retry) can land on an unrelated mod sharing only a generic word like "VRO" or "patch."
Now requires at least one shared identity-bearing token (generic modding filler excluded) before
accepting a match; an unresolvable mod is now flagged for manual review instead of silently
mis-tracked.

**x4effective and x4stats gave confident-looking answers that meant "nothing was checked":**
- `x4effective ls ship` printed `0 ship(s)` — reading as "this game has no ships," when the real
  issue is that `ship` isn't a stored entity kind (ships are `kind=macro`). Unknown kinds are now
  rejected with the actual list of valid kinds and a hint for the common ship/equipment aliases.
- x4stats compared ungrouped wares against an unrelated 1386-ware pool. A ware with no `group=`
  attribute (a paint mod, a cosmetic prop) was bucketed with every *other* ungrouped ware in the
  game and given a real-looking percentile against a wildly unrelated price distribution. Now
  reported as "not comparable," never a fabricated percentile.

If you maintain a fork or a similar tool: the single highest-leverage test you can add is this
pattern — ground truth from the engine's own log (`debug.txt`), not from your own model of the
engine, compared op-for-op, not file-for-file. No regressions found: all 10 previously-tracked
dev mods re-validated clean; the corrected oracle count is unchanged after every fix (234/234
ops, 100% agreement, 0 false OK, 0 unclassified, across all mods the reference log names — 9 of
them packed).

### Added — cross-platform support & guided installer (thanks @blablup, #2)
- **Runs on Linux, macOS and Windows (Git Bash).** `.claude/hooks/_x4-env.sh` is a shared
  resolver — **env var > `.claude/x4-paths.env` > default** — with case- and slash-insensitive
  matching that resolves symlinks and `..` via `realpath`, guarded so a Windows `C:\...` path is
  never mangled.
- **`install.sh` / `install.ps1` with three methods:** `in-game` (copy into the X4 folder — the
  original model), `separate` (toolkit in its own folder, pointed at the game via config), and
  `global` (skills/agents into `~/.claude` so the toolkit works across many mod repos). Paths are
  auto-detected from Steam's `libraryfolders.vdf` and overridable by flag.
- **`bin/xrcat`** — OS-aware XRCatTool wrapper (direct on Windows, Wine + `winepath` elsewhere).
  **`bin/unpack-reference.sh`** — config-driven text-only base+DLC unpack into `reference/`.
- **`.claude/x4-paths.env.example`** — one documented source of truth for every path.
  Keys: `X4_TOOLKIT`, `X4_GAME`, `X4_REFERENCE`, `X4_PROFILE`, `X4_DEBUGLOG`, `X4_MODS`,
  `X4_EXTENSIONS`, `XRCATTOOL`, `X4_APPMANIFEST`.
- All five hooks and `setup.sh` are now driven by the configured paths, with the old folder-name
  patterns kept as a backstop so protection still works out of the box.

### Added — engine knowledge (thanks @blablup, #1)
Field-tested MD↔Lua / FFI / UI / persistence patterns in `KNOWLEDGEBASE.md`: the nested-blackboard
`$`-prefix key trap, which container/trade-rule FFI functions actually work from UI-Lua (and the
global-vs-`C.` cdef variant trap), `$ship.$var` not surviving save/load, the
`a and nil or b` Lua footgun, and the kuertee UI-Extensions station-tab gotchas (13-column limit,
`is_valid_for` scope, slider/table widget behaviour).

### Fixed — safety hooks
- **The game-installation hard block never fired.** It used a PCRE lookahead `(?!\.claude)` under
  `grep -E`, which cannot match — so the rule has been silently dead in every release to date.
- **`in-game` layout hard-denied edits to your own mod sources.** With the toolkit installed into
  the game folder, `dev/`, `dist/` and `$X4_MODS` fell through every whitelist to the
  game-installation block. Now whitelisted.
- **`content.xml` edits were silently allowed inside the working dirs.** The manifest confirmation
  sat *below* the workspace whitelist; it now runs above it, so a manifest edit always confirms.
- **`check-reference-version.sh` hardcoded one Steam path** — now derived from `X4_GAME` with
  cross-platform fallbacks, so GOG / second-library / Linux users get the stale-reference warning.
- **`x4validate-on-edit.sh` was anchored to the author's personal folder** (`Modding/X4/dev/`), so
  the advertised auto-validate-on-edit hook could never fire for anyone else. Now it triggers on
  any diff XML outside `reference/`, resolving the mod root by walking up to `content.xml`.

- **Auto-backup was not anchored to the toolkit.** `backup-before-edit.sh` was the only hook that
  never adopted the shared path resolver; it used `${CLAUDE_PROJECT_DIR:-.}`, so with that variable
  unset it wrote backups into whatever directory the shell happened to be in. It now resolves
  through `_x4-env.sh`, and Windows-style paths are normalized before the copy.
- **`_x4-env.sh` no longer falls back to `$(pwd)` for the toolkit root.** It derives it from the
  hook's own location (`<toolkit>/.claude/hooks/` -> `<toolkit>`), so every hook stays anchored
  even when `CLAUDE_PROJECT_DIR` is absent.

### Added — the guards now have tests
- **`scripts/test-hooks.sh`** — feeds every hook synthetic tool-call JSON and asserts the decision
  it returns: **33 assertions** across both the in-game and separate layouts (deny `reference/`,
  `.cat`/`.dat`, base-game files; ask on `content.xml`, profile, deployed `extensions/`; allow
  `dev/`, `$X4_MODS`, toolkit dirs), plus backup creation, audit-log append, backup anchoring, and
  the stale-reference warning in both directions. Run it after any change to `.claude/hooks/`.

  **Four** separate safety features shipped silently inert before this release, and every one of
  them passed code review. A silent guard is worse than no guard, so the guards now have tests.

### Fixed — x4validate reported a false OK on attribute-add ops (found before the oracle existed)
- **`<add sel="…" type="@attr">value</add>` was silently ignored.** RFC 5261 §4.3 defines an
  attribute-add; X4 supports it and real mods use it. `_merge._do_add` never implemented it — the
  op fell through to the append-children branch, found no element children, mutated nothing, and
  still reported `OK 1 target(s)`. That is a **false OK on exactly the silent-no-op class this tool
  exists to catch**, and it survived earlier review because the op *looks* handled when you read
  the code. `_do_add` now sets the attribute, and `apply_diff` reports any `type=` it does not
  model rather than pretending to apply it. Four regression tests.

  Attribute ops matter for cross-mod work: when another mod owns a sibling attribute, a whole-node
  `<replace>` bakes in whatever value was winning when you wrote the patch, while
  `<remove sel="…/@x"/>` + `<add type="@value">` leaves it alone.

### Changed
- `/x4-debug` no longer ships a hardcoded workshop id as a "known-benign" suppression rule — it
  now describes the *class* (an extension id not in your installed set) and warns against
  suppressing ids you haven't confirmed absent. It also documents two engine behaviours that look
  like regressions but aren't: an upstream mod's failed `<replace>` still logs even when a
  load-last overlay supplies the value, and a `sel=` matching multiple nodes is a silent no-op.
- Log comparison guidance: check whether each log is a new game or a save load before comparing
  error counts — they aren't comparable across that boundary.

### Verification
`bash scripts/test-hooks.sh` — **33/33** assertions across both install layouts. Python suite: 170.

## v1.4

Engine-fidelity release. Three ways X4's patch semantics differ from a naive XML merge were
found by dogfooding against a 95-mod install — each one had been silently producing either a
false alarm or, worse, a false OK. Plus the effective-values browser (`x4effective`) and the
version-diff tool (`x4diff`).

### Fixed — three silent-no-op / false-alarm classes

- **A `sel=` matching MULTIPLE nodes is a silent no-op, and was never flagged.** RFC 5261
  requires `sel` to select exactly one node; X4 enforces it by logging
  `Multiple matching nodes for path '<sel>' ... Skipping node` and applying **nothing**. The
  patch looks correct, validates clean, and does nothing. **236 such ops were being skipped
  across one real modlist** — including 11 belonging to a mod whose entire purpose was the
  behaviour those ops implement. `x4validate` now reports this as an ERROR, and the merge
  engine models the skip instead of applying the op to every match (which used to build an
  effective tree the game never has).

- **`if=` guards were unknown to the checker.** `if=` is the idiom for targeting content that
  may not be installed. The merge engine honoured it; the sel-checker did not know it existed
  and reported every deliberately-guarded op as a hard ERROR. Guards are now evaluated first,
  exactly as the engine does: a false guard reports INFO ("guarded no-op") and short-circuits
  before `sel=` is parsed. A guard that *passes* while its `sel=` still misses remains an
  ERROR — the author asserted that target exists.

- **Cross-mod patches at `extensions/<target>/<rel>` reported "no base game file".** That path
  is owned by `<target>`, not by the base game, so the base was never found and the patch's
  selectors went unchecked — while the engine applied them fine. The merge engine now resolves
  the owning mod and layers other mods' nested patches on top.

### Added

- **`--tier b`** — previously a stub that printed a warning and was never passed to the
  validator. It now merges the **installed extension set in load order**, so cross-mod patches
  resolve for real. It also catches the reverse failure Tier A silently passes: content another
  mod has **removed**. Real case that motivated it — one mod's `index/macros.xml` `<remove>`s a
  vanilla macro and never re-adds it, orphaning it for six other mods and generating 415 engine
  errors; Tier A reported that macro as defined. The mod under test is auto-excluded by both
  folder name and `content.xml` id (a dev folder is usually also deployed, and merging that copy
  would pre-apply its own ops and mask real misses). ~8s over 93 extensions.
  Ordering follows the community convention (alphabetical, dependencies first) — advisory.

- **`x4effective`** — the "xEdit for X4" effective-values browser. Every final value with
  per-attribute provenance (`base → modA replace-attr:12 → modB`), backed by SQLite.
  Subcommands: `build`, `ls`, `show`, `attr`, `who-sets`, `diff-mod`, `dump`, `sql`.
  Answers "show me all missiles and their damage" and "who set this, and what did it override".

- **`x4diff`** — semantic XML diff between two versions of a mod, with multi-baseline support
  (`--overlay`). Built for separating *your* edits from an author's when recovering personal
  modifications made to an older release.

- **`_provenance.py`** — provenance capture threaded through the merge (`Origin`/`Recorder`),
  keyed by live element objects rather than XPath strings, since paths shift as the tree mutates.

- **`_debuglog.py` / `--debug`** — folds the engine's own `debug.txt` errors for the mod under
  test into the report, and gates on them. The engine is the authority; static checks are not.

- **`_exprlint.py`** — always-on heuristic lint for MD/aiscript expression grammar.

### Changed

- `collect_macro_defs` now builds the **effective** `index/macros.xml` via the merge engine
  instead of unioning each directory's file. The old approach could see neither `<diff>`/
  `<remove>` ops nor packed `.cat` mods, so it reported macros as defined after they had been
  deleted from the effective index.
- `_merge.Config` gained an `overlays` field, threaded automatically into every
  `build_effective()` call, so Tier B needs no signature changes across the checkers.

### Tests

125 → 152. New `tests/test_tierb.py` encodes all three engine-fidelity rules plus Tier B
overlay resolution as permanent regressions.

## v1.3

New cross-mod interaction suite — the toolkit can now analyze how a mod behaves against your
installed set, not just validate it in isolation.

### Added
- **`x4compat`** — detects how installed mods collide over the effective (base+DLC+mods) tree:
  HARD (two mods replace/remove the same node — one silently loses), UNION-KEY (two mods define
  the same registry entry id), FULL-OVERRIDE (two full-file overrides of one asset), SOFT (benign
  coexisting adds). Dispatches by actual merge semantics, not raw file overlap — a shared-registry
  overlap (`t/`, `libraries/`, `index/`) isn't automatically a conflict. Candidate mode
  (`check <mod-folder>`) answers "what would collide if I added this?" before installing.
- **`_cat.py`** — an independent `.cat`/`.dat` reader so PACKED mods are finally visible to the
  whole toolkit (previously only loose-file mods could be analyzed). MD5-verified, reads both
  `ext_*` and `subst_*` catalogs, case-insensitive virtual-path lookup. Wired into the merge
  engine as a loose-over-packed fallback.
- **`x4xref`** — a who-calls / who-listens / cue cross-index over every MD/aiscript in base+DLC+
  installed mods. Answers behavioral-interaction questions ("who else touches this event/action")
  in one query instead of many exploratory greps — the useful tokens for this class of question
  often share no keyword with the concept you're actually asking about.
- **`x4stats`** — advisory numeric comparison of a candidate mod's wares/macros against the
  effective tree's same-group peers (so an installed overhaul's rescaled values are the baseline
  you're compared against, not vanilla's). Grounds a balance discussion; does not settle one.
- **`x4similar`** — advisory fuzzy same-ship detection: flags a mod's ship as a probable
  near-duplicate of one already present under a DIFFERENT id/name (an overhaul's rebalanced
  reskin, or two mods independently adding "the same" ship). Hard-filtered by ship class+purpose;
  requires 4+ shared numeric stats to avoid coincidental matches between unrelated small ships.
- **`/x4-mod-interaction` skill** orchestrating all four tools plus README/Nexus context into a
  single interaction brief with per-claim confidence — never loads a whole mod's XML into context.

## v1.2

Fixes and redesign from continued dogfooding on a real 30+ mod install.

### Fixed
- **`libraries/*.xml` (ships, wares, loadouts, ...) are now correctly UNIONED**, not
  full-file-overridden, matching the engine. Every DLC ships its own full `libraries/`
  files; treating them as full overrides silently clobbered base-game entries out of the
  effective tree, producing phantom "sel matched nothing" errors for any mod patching a
  base-game ship/ware/loadout. (`index/` and `t/` were already unioned — `libraries/` is
  now folded into the same additive-merge path.)
- **Mod-authored index entries (`index/macros.xml` etc.) no longer double their own
  path prefix.** Mods conventionally write index values game-root-relative
  (`extensions\<mod>\assets\...`); resolving that literally against the mod root (which
  already IS that `extensions\<mod>\` directory) produced a spurious "file missing".
  The leading `extensions\<mod>\` is now stripped before resolving.
- **Loadout connection-checking no longer flags `path=".."`/`"."` as a missing
  connection name.** Vanilla `<groups>` entries use `path=".."` to mean "the ship root,"
  not a connection — that's not a checkable name.

### Changed — `x4modlist` redesign
- **Installed-folder scan is now the PRIMARY source of truth**, not the profile
  `content.xml`. A registry built content.xml-first drifts from reality over time (see
  "content.xml ≠ what's installed" in KNOWLEDGEBASE.md) — `x4modlist ingest` now scans
  the real extension folders first and treats that as authoritative; content.xml is
  ingested as a secondary backfill/cross-check pass so a historically-tracked mod isn't
  silently lost, surfaced in its own "not currently installed" view instead.
- **Identity resolution now prefers a mod's own manifest name** over a humanized
  folder/id guess, with fallbacks for common author-prefix (`"kuertee: X"` → `"X"`) and
  suffix-qualifier (`"X - Divinity Edition"` / `"X VRO"` → `"X"`) naming patterns —
  substantially fewer wrong Nexus-search top hits.
- **New `custom-local` classification lane**: a mod whose upstream Nexus status is
  `removed`/`hidden` is no longer automatically classified `drop` if the user has
  marked it `custom_edited` — a locally-maintained fork/port isn't "abandoned" just
  because the author's page is temporarily unavailable.

## v1.1

Bug fixes from a cold-start install red-team (a no-context agent following only the shipped
docs), which surfaced gaps invisible from the inside.

### Fixed
- **`x4validate` no longer false-passes when the reference tree is missing or empty.** It used
  to report `OK: no issues found` (exit 0) even on a `sel=` that matched nothing, because there
  was nothing to match against — the exact silent-no-op the tool exists to catch, in the tool
  itself. It now errors and exits non-zero until a real `reference\` is present. (+ regression
  tests.)
- **`protect-files` hook now actually fires.** The game-install block used a PCRE lookahead
  invalid under `grep -E`, so it never triggered; path matching was also tied to one personal
  workspace layout. Reworked to anchor on `$CLAUDE_PROJECT_DIR`, so the `reference\` read-only
  block and the workspace whitelist work at any install location.

### Changed
- `CLAUDE.md` reconciled to the "workspace under the project root" layout and to the
  protections that actually exist; removed a hardcoded x4validate test count from docs.

## v1.0

Initial release. An AI-assisted X4: Foundations modding environment for Claude Code,
distilled from hands-on mod development on X4 v9.0.

### Included
- **~500-line `KNOWLEDGEBASE.md`** — X4 XML schema patterns, diff-patch idioms, the
  extension merge/load-order model, the 7.x→9.0 version migration map, a mechanics
  interlock map, and tool notes. Auto-loaded every session.
- **`CLAUDE.md`** — the modding workflow: diff-patch-first, confidence levels,
  "vanilla as frame of reference," native-engine-solutions-first, and the cognitive
  co-pilot principle.
- **`x4validate`** (bundled, Python/uv/lxml) — cross-file validator: checks every diff
  `sel=` resolves against the real base+DLC merged tree, that ware/macro/`{page,t}`
  references resolve, and completeness of new content vs a vanilla analogue. Also ships
  `x4modlist` (mod-registry triage via the Nexus API) and an XSD-based 7.x→9.0 migration
  checker.
- **4 skills** — `/x4-debug`, `/x4-modlist-review`, `/x4-scaffold`, `/x4-update-mod`.
- **2 subagents** — `cross-file-impact`, `mod-research`.
- **Safety hooks** — protect-bash, protect-files, auto-backup-with-audit-log,
  reference-version check (SessionStart), and advisory x4validate-on-edit.
- **`scripts/generate-baseline.sh`** — capture a known-good baseline (game version,
  installed-mod hashes, a normalized debug.txt error fingerprint) to diff against later.
- **`setup.sh`** — checks prerequisites (jq, uv/Python), wires up x4validate, and
  personalizes local paths.

### Notes
- Ships **no** Egosoft game data. `reference\` is unpacked locally from your own copy.
- All Nexus access is via the official API with **your own** API key (`X4_NEXUS_KEY`);
  no key is bundled.

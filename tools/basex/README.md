# BaseX — XQuery over the X4 corpus

A **discovery** instrument. It answers *"where does this appear, what values exist,
who mentions X?"* across every XML file the game and your mods ship — base game,
all DLC, loose mod files and **packed** ones — in about a second.

It is not the authority on correctness. `x4validate` is. See
[Discovery vs. proof](#discovery-vs-proof) before quoting anything from here.

> **Numbers below are MEASURED on one real install as of 2026-08-24** and are there
> to set expectations, not as guarantees. Yours will differ with your modlist.

---

## Prerequisites

| | why |
|---|---|
| **Java 17 or newer** | BaseX 12.4's classes are bytecode **major 61**. An older JVM does not run slowly — it refuses to load them (`UnsupportedClassVersionError`). Read out of the shipped jar: `Build-Jdk-Spec: 17`. |
| **`uv`** (with Python 3.13) | the build scripts drive `x4validate` through `uv run python` |
| **~3 GB free disk** | the index is the durable artifact — measured **942 MB** (`x4raw`) + **949 MB** (`x4eff`) — plus a transient staging tree during the build |
| **a configured toolkit** | `$X4_REFERENCE` and `$X4_EXTENSIONS`, or `.claude/x4-paths.env`. The scripts **refuse** rather than guess: a corpus built over a path that does not exist indexes zero documents and would otherwise still exit 0. |

`preflight.py` checks all of these and refuses with **exit 2** before any long work
starts. You should never see a raw `[WinError 2]` or `Could not find or load main
class`; if you do, that is a bug worth reporting.

## Install

Put `BaseX.jar` in `basex/`. That is the whole installation — **`lib/` is not
needed** (verified: a real `collection()` query runs from a directory holding
only the jar). If it is missing, download BaseX 12.4 from
<https://basex.org/download/>.

Every caller invokes it as:

```bash
java -cp BaseX.jar org.basex.BaseX -q "<xquery>"
```

**not** `java -jar` and not `bin/basex` — the jar's `Main-Class` is `BaseXGUI`,
so `java -jar` opens a GUI.

## Build

```bash
bash build-corpus.sh      # x4raw — every file AS WRITTEN
bash build-effective.sh   # x4eff — X4's EFFECTIVE merged tree
```

Both are long jobs. Run them in the background rather than raising a timeout.

## Ask

```bash
cd ../x4validate
uv run python ../basex/ask.py refs <macro_or_ware_id> [--db x4eff]
uv run python ../basex/ask.py attr <attribute-name>
uv run python ../basex/ask.py xq   '<raw xquery>'
```

A query over the real corpus takes roughly **1.6 s**.

See **[QUERIES.md](QUERIES.md)** for the two-database model and a cookbook.

---

## Freshness: why it sometimes refuses to answer

This is the part with no equivalent anywhere else in the toolkit, and the reason
a refusal here is a **feature rather than a fault**.

Coverage answers *how much* was indexed. It does not answer *as of when*. An index
that no longer describes the world is a third state beside "found" and "not found":
**an answer about a world that has moved on.** That is not hypothetical — `x4eff`
spent eleven days serving pre-merge-fix values, and on rebuild **140 of 194** engine
thrust rows changed with **not one input file altered**.

So every index carries a **two-axis fingerprint**:

| axis | covers | why it must be separate |
|---|---|---|
| `content` | the installed extension set, each manifest's mtime/size, a reference marker | mods added, removed or updated |
| `engine` | a hash of the merge/enumeration source **bytes** | a merge fix changes the right answer for identical inputs |

`ask.py` prints a banner on every run against a stale index — including alongside
a **positive** result, which is still an answer about a superseded world — and
**refuses** to render a zero-result as a negative finding.

Three verdicts, and the third is the one that matters:

- **FRESH** — both axes match. Answers stand.
- **STALE** — an axis moved. Rebuild before making any claim.
- **FRESHNESS UNKNOWN** — freshness could not be *computed* at all (for example
  `x4validate` is not importable here). This is **not** "stale", and printing
  STALE would be asserting something nobody established. It is reported as
  undeterminable, and an absent fingerprint counts as UNKNOWN — never as fresh.

⚠ **One measured hole, stated rather than left to be found.** The content axis reads
each installed mod's own manifest but **not** the profile manifest recording which
mods are *enabled*. Installing or removing a mod moves the fingerprint; **toggling
one on or off does not.** If you have enabled or disabled a mod since your last
build, rebuild rather than trusting the banner.

Rebuild with `build-corpus.sh` / `build-effective.sh`; inspect without rebuilding:

```bash
cd ../x4validate && uv run python ../basex/staleness.py --db x4eff
```

---

## Exit codes

Every code below is **read from the source**, not assumed. Note that `2` always
means *"this is not set up"* and never *"your corpus has findings"* — the same
distinction the `x4validate` CLIs make.

| tool | code | meaning |
|---|---|---|
| **`ask.py`** | 0 | answered (a positive result, or a negative WITH a denominator) |
| | 2 | not set up, or the query and `--db` disagree about which database to search |
| | 4 | **cannot back a negative** — zero hits, but coverage is missing/unexplained, or the index is stale, or the query was `count()`-shaped |
| **`coverage.py`** | 0 | complete |
| | 2 | refused — a required root was not supplied (an empty root resolves to the *current directory*, which would publish a denominator measured over the wrong population) |
| | 3 | **accounted** — a deficit exists but every missing document is named. Still supports a negative claim. *`x4raw` path only.* |
| | 4 | unexplained deficit — cannot support a negative claim |
| **`staleness.py`** | 0 | fresh |
| | 5 | stale |
| | 6 | freshness undeterminable |
| **`preflight.py`** | 0 / 2 | ready / not ready |
| **`build-effective.py`** | 0 / 3 | all vpaths merged / some failed (the manifest names them; the tree is still built) |

⚠ **The two `coverage.py` paths do not share a scale.** The `x4raw` path has three
tiers (`complete` 0 / `accounted` 3 / `unexplained` 4); the `--eff-manifest` path
for `x4eff` has **no `accounted` tier** and returns only 0 or 4. Do not carry one
path's wording onto the other — that mistake was made while writing this table.

`build-corpus.sh` and `build-effective.sh` propagate their coverage verdict. A
non-zero exit there means *"the index is built and usable, but it cannot yet back
a negative claim"* — not "the build failed".

---

## Discovery vs proof

| question | tool |
|---|---|
| "what values does this attribute take across the corpus?" | **BaseX** |
| "who references / who calls X?" | **BaseX**, or `x4xref` for MD + aiscript cues |
| "what is the LIVE value, and which mod set it?" | **`x4effective`** |
| "do this mod's selectors resolve / is it correct?" | **`x4validate`** |

**A bare "0 hits" is a lead, never a fact.** `ask.py` will not print one as a
finding without a denominator — that guard is the reason this tool is quotable at
all. Prefer `--db x4eff` for any claim about what is live: `x4raw` holds files *as
written* and will happily quote a vanilla value your modlist overwrote.

**Load order is community convention**, not documented by Egosoft. Any `x4eff`
answer that turns on *which mod won* is advisory to exactly that degree.

## Housekeeping

`basex/data/` may contain databases no current script builds — an early index from
before packed staging existed, for instance. They are inert but not free (one such
fossil measured **908 MB**). `ls basex/data/` to see what is there; only `x4raw`
and `x4eff` are live.

BaseX writes a `.basex` config beside the jar on first use. It records absolute
paths, so it is gitignored — expect to generate your own.

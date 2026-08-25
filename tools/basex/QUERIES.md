# BaseX / XQuery over the X4 corpus

Discovery tool over the X4 corpus. Ships with the toolkit as of v2.6.0; it needs a
JVM (Java 17+) and a one-off index build. See [README.md](README.md) for install,
the freshness contract, and the exit codes.

```bash
bash build-corpus.sh      # x4raw  — every file AS WRITTEN      (~4 min)
bash build-effective.sh   # x4eff  — X4's EFFECTIVE merged tree (~1.5 min)
cd ../x4validate && uv run python ../basex/ask.py refs <id> [--db x4eff]
```

## Two databases, two questions — do not mix them

| DB | contents | answers |
|---|---|---|
| **`x4raw`** | every file as written, per mod (13,862 docs, as of 2026-08-24) | *who **wrote** this, in which mod* |
| **`x4eff`** | `_merge.build_effective` per vpath (10,937 docs, as of 2026-08-24) | *what does the **engine** see* |

`x4raw` will happily tell you vanilla sets a value that no longer survives the
modlist. For a claim about what is **live**, use `x4eff` — it applies diffs in
load order and resolves conflict winners. Demonstrated: `hullparts` price is
`209` in `x4raw` (vanilla) and `240` in `x4eff` (what actually loads).

**Advisory limit:** inter-mod load order is community convention (dependencies
first, then alphabetical), not documented by Egosoft. Any `x4eff` answer that
turns on *which* mod won is advisory to exactly that degree.

## A negative claim needs a denominator (this is the point)

A discovery tool that cannot prove a negative is just a faster way to guess.
Three gaps stood in the way; all three are closed:

| Gap | Was | Now |
|---|---|---|
| **1. Packed content** | 62% of mod XML lives in `.cat`/`.dat` and was invisible (vro alone = 1,613 files) | `stage.py` extracts via `_cat` into transient staging, indexed, then discarded |
| **2. Files as written** | no diff application, load order, or conflict winner | second DB `x4eff` from `_merge.build_effective` |
| **3. Silent drops** | `SET SKIPCORRUPT true` is required, but drops files **silently** | `coverage.py` reconciles indexed vs disk and **names every exclusion** |

**Never quote a bare "0 hits".** `ask.py` refuses to render a zero-result as a
negative finding unless `coverage-<db>.json` says coverage is complete or fully
accounted, and prints the denominator when it does:

```
0 items in x4eff.
  NEGATIVE CONFIRMED over 10937 of 10937 documents (complete).
```

### Gap 4 — a fourth was found on 2026-08-01, and it was in the guard itself

The count printed as "hits" was `len(output_lines)`, not the number of matches.
Measured: 847 occurrences across 4 documents printed as **"32 hit(s)"**, because
BaseX wrapped the serialized sequence over 32 lines.

The serious part was not the miscount. The zero-result guard keyed off that same
line list being empty, and a `count(...)` query returning zero emits the single
line `0` — so **the guard never ran, and a zero result rendered as "1 hit(s)"
with exit 0.** `count()` is the most natural way to ask "how many", and it
bypassed the entire mechanism this tool exists to provide.

Now the query is wrapped (`let $__ask := ( … ) return (count($__ask), SEP, $__ask)`)
so the count is the **result-sequence item count**, and the guard keys off that.
A count-shaped query that counted nothing is refused explicitly:

```
$ ask.py xq 'count(collection("x4raw")//ware[@id="nope"])'
0
1 item(s) in x4raw.
  ** NOT A NEGATIVE FINDING. ** That is one atomic value, not one match …
  Re-run returning the nodes themselves — drop the count(...) wrapper.
```
exit **4**. If the wrapper will not compile (a query with its own prolog), the
output says *"item count unavailable"* rather than quoting the line count as
though it meant something.

**Practical rule: ask for the nodes, not for `count()`.** Only the node form can
carry a coverage-backed negative. `test_ask.py` pins both directions and needs
neither BaseX nor a JVM.

Current coverage: **x4raw accounted** — 13,862 of 13,874; the 12 exclusions are
malformed XML (11 packed in `vro/**/tmp|backup|md_debug`, 1 loose in
`cpsdo_faction/t/0001-l088.xml`) that the *engine* cannot read either.
**x4eff complete** — 10,937 of 10,937, with 212 vpaths that have no effective
tree and 12 malformed overlays enumerated in `effective-manifest.json`.

### Why the deficit explainer matters — it caught a real bug

The first reconciled build reported an **unexplained** deficit of 30 against 12
known-malformed files. Cause: `_cat.mod_vfs(xml_only=True)` also admits `.xsd`,
but BaseX builds with `CREATEFILTER *.xml` — so 18 schemas were staged, never
indexed, and read as missing. Without the reconciler that would have silently
poisoned every negative claim forever. **The index looking complete is not
evidence that it is.**

## Queries that earned their keep

### Who references this macro? (packed content included since 2026-07-27)
```bash
uv run python ../basex/ask.py refs turret_xen_m_beam_02_mk1_macro
```
**217 hits**, overwhelmingly inside PACKED mods (`vro`, `xenon_backup`,
`xspvro`) — every one invisible before staging. This is the macro `xspvro`
removes from the index; the KB previously said "six other mods reference it",
which we can now enumerate exactly.

### Every value in use for an attribute, with counts
```bash
uv run python ../basex/ask.py attr roomtype
```
Also surfaces *unresolved variables* (`$key.$roomType`) beside literals — the
dynamic call sites a literal grep silently misses.

### Where is a variable DEFINED? (the `$HQ` class)
```xquery
for $n in collection('x4raw')//set_value[@name='$HQ']
return concat(document-uri(root($n)), '  ::  ', $n/../../@name, '/', $n/../@name)
```
The question both rejected `_exprlint` regex rules failed at (718 vanilla false
positives); here the cue context comes free from the tree structure.

### Cross-file JOIN: dangling references
```xquery
let $defined := distinct-values(collection('x4eff')//macro/@name)
for $r in distinct-values(collection('x4eff')//ware/component/@ref)
where not($r = $defined)
return $r
```
**Always sanity-check an empty result by counting both sides** — an empty join
and a broken query look identical.

## Gotchas

- **Invoke as `java -cp BaseX.jar org.basex.BaseX`.** The bundled `bin/basex`
  wrapper fails here with `ClassNotFoundException`.
- **Java is a native Windows process** and does not understand Git Bash's
  `/c/...` paths. Passing one made BaseX look for `C:/c/Users/...` — and it
  still **exited 0**. The build scripts run paths through `cygpath -m` and grep
  the output for `not found`, because BaseX's exit code is not a usable gate.
- **Staging and the serialized effective tree are transient** by design; the
  ~2.8 GB index is the durable artifact. `KEEP_STAGE=1` / `KEEP_EFF=1` to keep
  them while debugging. The *manifests* always persist — a coverage report you
  can only run mid-build is one nobody runs.

## What this still does NOT replace

`x4validate` remains the authority for *correctness against the engine* — it has
the oracle (agreement with the engine's own `debug.txt`: 234/234 ops, 0 false
OK). BaseX is for *discovery and structural questions across many files*. The
CLAUDE.md **Discovery vs. Proof** rule now has a third state: a BaseX negative
**with a stated denominator** is admissible; a bare one is still just a lead.

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
| **`x4raw`** | every file as written, per mod | *who **wrote** this, in which mod* |
| **`x4eff`** | `_merge.build_effective` per vpath | *what does the **engine** see* |

Document counts are a fact about one install at one build, so none is quoted here: every
zero-result `ask.py` prints the current denominator, and `coverage-<db>.json`
(`indexed.total` / `expected.total`) holds it between runs.

`ask.py` searches **`x4raw` unless you pass `--db`**, and for `refs` and `attr` says so under the
result (an `xq` query names its own collection). **From Git Bash, give an `xq` query with
`--file`:** MSYS rewrites path-like parts of command-line arguments (`//` becomes `/`) before
Python sees them, so
`ask.py` refuses to certify a zero from an argument there and shows the query as received. What it
counts are XQuery items -- for `refs`, one matching element per line -- not files or entities.

`x4raw` will happily tell you vanilla sets a value that no longer survives the
modlist. For a claim about what is **live**, use `x4eff` — it applies diffs in
load order and resolves conflict winners. Demonstrated once on one modlist: `hullparts`'
price read as the vanilla value in `x4raw` and as a mod's override in `x4eff`. The two values
depend on the modlist, so re-derive them (`collection('<db>')//ware[@id='hullparts']/price`
against each database, with the matching `--db`) rather than quote them.

**Advisory limit:** inter-mod load order is the engine's MEASURED signature-check
order (case-insensitive folder order in repeated dependency passes; see
`tools/x4validate/docs/BLIND-SPOTS.md` F128), not documented by Egosoft; that it is
also the patch-apply order was MEASURED by the in-game load-order probe (2026-09-26).
Other install roots are unobserved.

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
  NEGATIVE CONFIRMED over N of N documents (complete).
```
(`N` is the current `indexed.total`; the shape is illustrative, the number is whatever your
build holds.) The denominator describes the WHOLE database, so it is only printed for a query
that searched all of it: a query addressing a document or a path (`doc(...)`,
`db:get('<db>', '<path>')`, `collection('<db>/<path>')`), naming its database through a
variable, or naming a database other than `--db` is refused with rc 2, and a zero from a query
that names no database at all is refused with rc 4. A negative over the whole database covers
every path in it, so search the whole thing.

**The scope can also be narrowed OUTSIDE a reach call's own argument list** -- by a document's
identity (`collection('x4eff')[matches(document-uri(.),'libraries/wares')]`), by position
(`collection('x4eff')[position() le 9]`, `subsequence(collection('x4eff'), 1, 9)`), or through
a route no text scan can read (`collection#1('x4eff/libraries')`). MEASURED: each printed
"NEGATIVE CONFIRMED over 10970 of 10970 documents", rc 0, over a query that addressed a
subset. A list of narrowing *shapes* could not keep up (a release review walked 11 of 12
rewrites past one), so the rule is about *tokens*: the query, with comments removed and
string-literal contents blanked, is searched anywhere for

| class | tokens |
|---|---|
| identity | `document-uri` `base-uri` `path` (`db:path`, `fn:path`) `node-pre` `node-id` `generate-id` |
| position | `position()` `last()` `head` `tail` `foot` `trunk` `subsequence` `slice` `items-*` `take-while` `remove` `index-of` `index-where` `partition`; `filter` `for-each` `for-each-pair` `fold-left` `fold-right` (XQuery 4 callbacks receive the position); FLWOR `at $i`, `count $c`, `window`; a numeric predicate (`[1]`, `[$n]`, `[count(.//x)]`) anywhere |
| order | `<<` `>>` `is` |
| modules | `util:` `hof:` `array:` `map:` `random:`, `array {`, a `?1` lookup |
| indirect | a `#` function reference, a `Q{...}` EQName, `xquery:` `function-lookup` `load-xquery-module` `transform` `eval` |

If one is present the query **still runs and its hits are reported**; only a zero is withheld
(rc 4), with a line naming the token. Selecting by **content** is not narrowing -- every
document was read and judged by what it holds -- so `collection('x4eff')[.//ware]//x` and
`collection('x4eff')//ware[@id='x']` are still certified, and so is a token spelled inside a
string literal or a comment. The rule over-reports on purpose: `//ware[1]` loses its
certificate too, because once a sequence is bound or parenthesised a text scan cannot tell
documents from elements. `refs` and `attr` are ask.py's own whole-database queries and are
not scanned (`refs` returns `document-uri` to name each hit's file).

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
$ echo 'count(collection("x4raw")//ware[@id="nope"])' > q.xq
$ ask.py xq --file q.xq
0
1 item(s) in x4raw.
  (an item is one node or value the query returned -- not a count of files or entities)
  ** NOT A NEGATIVE FINDING. ** That is one atomic value, not one match …
  Re-run returning the nodes themselves — drop the count(...) wrapper.
```
exit **4**. If the wrapper will not compile (a query with its own prolog), the
output says *"item count unavailable"* rather than quoting the line count as
though it meant something.

**Practical rule: ask for the nodes, not for `count()`.** Only the node form can
carry a coverage-backed negative. `test_ask.py` pins both directions and needs
neither BaseX nor a JVM.

The same goes for other values computed from nothing: `exists(...)` returning `false` and
`string(...)` of an empty sequence returning `""` are refused with rc 4, never counted as a hit.

**Coverage figures are not quoted here** -- every run prints the current ones, and
`coverage-<db>.json` holds them. To read them: `status`, `indexed.total` of `expected.total`,
and for x4raw the named exclusions under `unparseable` (malformed XML the *engine* cannot read
either); for x4eff `negative_claim_excludes` (vpaths with no effective tree, malformed
overlays), enumerated in `effective-manifest.json`. x4raw is judged **per root** (`base`,
`mods`): each root's shortfall must equal its own malformed files, so a surplus in one cannot
offset a gap in another. ⚠ Figures recorded before the 2026-09-24 audit (BX-2) counted both
mini-DLC twice in x4raw -- once from `reference\` and once staged from their archives -- so
an older x4raw total is inflated by those duplicates.

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
When first run (2026-07-27) this returned hits overwhelmingly inside PACKED mods -- every
one invisible before staging -- where the KB had said only "six other mods reference it".
The count depends on the installed modlist, so it is not quoted; run it for today's.

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
  still **exited 0**. The build scripts convert only the paths they CREATE (the
  staging tree, the serialized effective tree) with `cygpath -m`, and fall back to
  the path unchanged where `cygpath` is absent; `$X4_REFERENCE` and `$X4_EXTENSIONS`
  reach BaseX exactly as resolved, so set them in Windows form (`C:/...`). What
  catches a wrong form is the grep of BaseX's output for `not found`, because
  BaseX's exit code is not a usable gate.
- **Staging and the serialized effective tree are transient** by design; the
  ~2.8 GB index is the durable artifact. `KEEP_STAGE=1` / `KEEP_EFF=1` to keep
  them while debugging. The *manifests* always persist — a coverage report you
  can only run mid-build is one nobody runs.

- **An `xq` query names its own database.** `count(//ware)` has no context to walk and BaseX
  answers `[XPDY0002] .: Context value is undefined`; `--db` sets the coverage and freshness
  denominator, not the input. Write `count(collection('x4eff')//ware)` and keep the two the
  same -- naming a DIFFERENT database than `--db` is refused, because the answer would be
  scored against the wrong world. `ask.py` says all of this when the error appears.

## What this still does NOT replace

`x4validate` remains the authority for *correctness against the engine* — it has
the oracle (agreement with the engine's own `debug.txt`: 234/234 ops, 0 false
OK). BaseX is for *discovery and structural questions across many files*. The
CLAUDE.md **Discovery vs. Proof** rule now has a third state: a BaseX negative
**with a stated denominator** is admissible; a bare one is still just a lead.

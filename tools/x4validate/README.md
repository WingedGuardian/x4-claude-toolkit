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
2. **Do the references resolve?** — ware / `{page,t}` text references the mod
   *introduces* must point at a real definition (text defs are **unioned**
   across base + DLC + mod, and across `0001.xml` + `0001-l044.xml`).
3. **Did I forget a spot?** — completeness: model a changed entity on a vanilla
   analogue and report which footprint pieces are missing.

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

## Usage

```sh
# from tools\x4validate\  (uses the bundled uv + Python 3.13 toolchain)
uv run x4validate <path-to-mod-dev-folder>
uv run x4validate <mod> --entity ware:my_new_ware --like ware:ore   # completeness
uv run x4validate <mod> --json                                       # machine-readable
uv run x4validate <mod> --update                                     # + 9.0 XSD/migration/exprlint
uv run x4validate <mod> --debug                                      # correlate the active profile's debug.txt
uv run x4validate <mod> --debug path\to\debug.txt                    # correlate a specific log (gates on engine errors)
```

The expression linter runs on **every** invocation (cheap, advisory). `--debug`
is the authoritative gate — run it against a `debug.txt` captured *after* your latest
edits (a gate on a stale log is a false failure).

Exit code is non-zero if any error-level finding is present (suitable as a
pre-deploy / pre-pack gate). Default merge tier is **A** (base + DLC,
deterministic); `--tier b` also folds in enabled mods but warns, because X4's
inter-mod load order is undocumented.

## Layout
- `x4validate/_merge.py` — effective-tree assembly (diff apply: add/replace/remove,
  pos/if/silent; full-file override by root element).
- `x4validate/_xpath.py` — lxml XPath wrapper (genuine no-match vs invalid-expr).
- `x4validate/_refs.py` — reference graph, dangling-ref detection, completeness.
- `x4validate/_exprlint.py` — expression-grammar heuristic (attribute-value rules).
- `x4validate/_debuglog.py` — `debug.txt` parser (4 engine-error shapes).
- `x4validate/_check.py` — orchestration + t-file union; `_cli.py` — CLI.
- `tests/` — `uv run --with pytest pytest` (125 tests, incl. the x4cat spike cases).

## Extending
Add reference types by extending the catalog in `_refs.py`; add completeness
recipes per content type (ship, module, …) alongside `ware_completeness`. Add an
expression-grammar rule by appending to `_exprlint.RULES` — **measure it against
vanilla `reference\` first** (a rule that flags valid code is dropped, not shipped;
see the removed `{a.b, c.d}` catch that fired on valid `.{[list]}` accessors).

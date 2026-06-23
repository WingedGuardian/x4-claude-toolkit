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

## Usage

```sh
# from tools\x4validate\  (uses the bundled uv + Python 3.13 toolchain)
uv run x4validate <path-to-mod-dev-folder>
uv run x4validate <mod> --entity ware:my_new_ware --like ware:ore   # completeness
uv run x4validate <mod> --json                                       # machine-readable
```

Exit code is non-zero if any error-level finding is present (suitable as a
pre-deploy / pre-pack gate). Default merge tier is **A** (base + DLC,
deterministic); `--tier b` also folds in enabled mods but warns, because X4's
inter-mod load order is undocumented.

## Layout
- `x4validate/_merge.py` — effective-tree assembly (diff apply: add/replace/remove,
  pos/if/silent; full-file override by root element).
- `x4validate/_xpath.py` — lxml XPath wrapper (genuine no-match vs invalid-expr).
- `x4validate/_refs.py` — reference graph, dangling-ref detection, completeness.
- `x4validate/_check.py` — orchestration + t-file union; `_cli.py` — CLI.
- `tests/` — `uv run --with pytest pytest` (26 tests, incl. the x4cat spike cases).

## Extending
Add reference types by extending the catalog in `_refs.py`; add completeness
recipes per content type (ship, module, …) alongside `ware_completeness`.

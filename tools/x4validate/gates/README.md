# Gates

> **These are contributor gates. You do not need them to use x4validate** — skip this
> page unless you are changing the merge model or the resolve chain. `uv run pytest`
> is the suite; this is the layer that checks the tool against the *engine*.

Harnesses that must pass before any commit that touches the merge model or the
resolve chain. They are **not** unit tests — they run against the real installed
modlist and a captured engine log, so they live here rather than in `tests/`.
Run them from `tools/x4validate/`.

| Gate | Run | Bar |
|---|---|---|
| `oracle.py` | `uv run python gates/oracle.py` | **234/234 ops agree, 0 FALSE OK.** Replays every diff op the engine itself rejected (from a captured `debug.txt`) and requires x4validate to reject the same ones. `debug.txt` is ground truth; a drop here means the merge model moved. |
| `oracle_index.py` | `uv run python gates/oracle_index.py` | **12/12 agree, 0 FALSE OK** over the index-lookup failures the engine logged. Note the structural limit stated in its own output: a failure-only log can prove FALSE OK but never completeness. |
| `oracle_reverse.py` | `uv run python gates/oracle_reverse.py [debug.txt]` | **0 disagreements with the engine.** The direction the two oracles above structurally cannot test: they replay what the engine *rejected*, so they prove "we never say fine where the engine said broken" — never completeness. This asks the reverse: the engine complained, do we notice? Covers the classes a merged tree can answer (missing text ids, missing component templates); runtime-state failures are out of scope by construction. |
| `reader_edges.py` | `uv run python gates/reader_edges.py` | **0 crashes, 0 silent-wrong results** on damaged input: BOMs, UTF-16, latin-1 in a UTF-8 file, non-XML, zero-byte `.cat`, truncated index, offset past the end of `.dat`, wrong MD5, `.dat` with no `.cat`, a mod path that is a file. Fail loudly or succeed correctly — never return garbage. |
| `regress.py` | `uv run python gates/regress.py [installed_mod ...]` | Tier A + Tier B error/degraded counts per mod under `$X4_MODS`. *(The recorded baseline — `X4CapturableXenonXL_public` 4 Tier B errors, every other 0 — is the author's own local mod set; yours will differ. What transfers is "no unexplained change from your own last run".)* |
| `schema_sweep.py` | `uv run python gates/schema_sweep.py` | **168 pairs · 59 gating + 70 advisory + 3 suppressed · 1 NOT checked · 42 mods flagged**, and the independently-evidenced defects still reported. Freezes the composition of the output so it cannot drift unnoticed. *(Baseline history lives in the measurement tables above the constants — most recently 2026-08-08, where the move was attributed per-mod rather than assumed: three added mods contribute 1 gating + 2 advisory, and one removed mod took 2 gating + 9 advisory with it, so the arithmetic closes exactly. **`NOT checked` is pinned too**: the gate previously froze only what WAS checked, so 31 documents skipped with a false reason never moved a number here.)* |

### Corpus audits (added 2026-08-08)

Written after a defect — a `<replace>` on a document root was discarded while being reported as
applied — survived three sessions because **nothing exercised that path**. These hunt the class,
not the instance, and they run over your own installed modlist rather than fixtures.

| Gate | Run | Bar |
|---|---|---|
| `noop_audit.py` | `uv run python gates/noop_audit.py` | **0 FALSE OK, 0 FALSE ALARM.** Applies every diff op of every installed mod against its real base document and compares what the tool *reports* to what the tree *does*. A structural op that changes nothing must never be reported as applied. Also surfaces mod XML that will not parse. |
| `provenance_audit.py` | `uv run python gates/provenance_audit.py` | **0 mis-attributed.** A value that differs from vanilla must name the mod that changed it; `origin=base` on a changed value is always a provenance bug — the subtle half of the defect above, where numbers look right and "who set this?" is wrong. |
| `consistency_audit.py` | `uv run python gates/consistency_audit.py [--samples=N]` | **0 disagreements** between three independent paths to the same truth: the store, `build_effective`, and `x4effective dump`. Callers pick whichever is convenient, so drift shows up as an inexplicable contradiction rather than an error. |
| `corpus_sweep.py` | `uv run python gates/corpus_sweep.py [--tier=a\|b\|both]` | **0 crashes, 0 hangs** running `x4validate` over every installed mod in both tiers. Looks for robustness, not findings — a mod with errors is the tool working. |
| `qa_sweep.py` | `uv run python gates/qa_sweep.py` | Every CLI × every subcommand against the real install. Mods and targets are discovered from your install, never named. |
| `determinism_audit.py` | `uv run python gates/determinism_audit.py [--with-build]` | **0 non-deterministic outputs.** The same command twice must produce byte-identical output, and a rebuilt store must be logically identical. Without this every recorded baseline is noise and "no change since last run" means nothing. |
| `stress_sweep.py` | `uv run python gates/stress_sweep.py [--corpus=DIR]` | **0 crashes** on unseen mod corpora, chained tools, and pathological XML (entity bombs, XXE, deep nesting, cyclic cross-mod patches, unicode with RTL overrides). Point `--corpus` at a folder of mods the toolkit has never processed. |
| `mutation_probe.py` | `uv run python gates/mutation_probe.py` | **every mutant killed.** Breaks the diff engine deliberately and requires the suite to notice. A survivor is a line nothing really checks — its first run found the RFC-5261 ambiguous-selector rule was untested by anything a contributor can run. |
| `fuzz_diff.py` | `uv run python gates/fuzz_diff.py [--n=N] [--seed=N]` | **0 invariant violations.** Generates random-but-legal diff ops and asserts what must hold for ANY of them: never raises · applied-and-structural implies the tree changed · not-applied implies unchanged · not-applied always carries a reason · the same op twice gives the same result. Seeded, so a failure reproduces. The corpus audits prove we handle every op that *exists*; this probes every op that is *legal*. |
| `edge_sweep.py` | `uv run python gates/edge_sweep.py` | Hostile and degenerate inputs — empty mods, malformed manifests, missing operands, SQL injection, path traversal, an unconfigured environment. The bar is **fail well**: a clear message and a sane exit code, never a traceback. Needs no game paths. |

### Output-truth, parity and performance gates (added 2026-08-09)

The audits above prove the tool handles every op that *exists* and every op that is
*legal*. These ask the next question: is what it **prints** true, and is a second
implementation of an existing check really equivalent? Every one of them derives its
ground truth independently of the tool under test — a fresh parse, a planted mutation,
or libxml2 — never the tool's own index.

| Gate | Run | Bar |
|---|---|---|
| `tool_properties.py` | `uv run python gates/tool_properties.py [--exhaustive]` | **0 violations** of properties that must hold for any input, for the three tools that previously had only "it ran and printed something" coverage (`x4diff`, `x4xref`, `x4stats`): identity, antisymmetry, monotonicity, and every printed citation/number re-derived from a fresh lxml parse. `--exhaustive` checks the entire output rather than a sample. "Exits 0 with output" is exactly the bar a confidently-wrong tool clears. |
| `cross_tool.py` | `uv run python gates/cross_tool.py` | **0 disagreements between different tools** answering the same question (the winner `x4compat` names for a contested file vs the origin `x4effective` records for entities in it), plus sensitivity — a planted delta must actually be *detected*, since identity and antisymmetry both hold trivially for a tool that under-reports. |
| `diff_truth.py` | `uv run python gates/diff_truth.py` | **exact.** Copies a real installed mod, mutates N numeric attributes chosen by a seeded RNG, and requires `x4diff --detail` to report exactly that set — every planted change found, nothing invented. Identity attributes are never mutated: changing an `id` changes *which element it is*, which correctly reads as structural. |
| `similar_audit.py` | `uv run python gates/similar_audit.py` | **every reported pair recomputed and confirmed, 0 unresolved.** Locates both macros with its own packed-aware scan, re-extracts the stat vector, recomputes the documented score, and asserts the printed percentage matches. Pairs are keyed by (name, **source**) — collapsing copies by name compares the wrong ones. |
| `update_corpus.py` | `uv run python gates/update_corpus.py` | **every planted break found.** A synthetic mod carrying every documented 9.0 break (XSD-gating, runtime-grep and expression-lint tiers). `--update` was only ever smoke-tested, and a migration checker that silently detects nothing is indistinguishable from a clean mod. |
| `xsd_fast_parity.py` | `uv run python gates/xsd_fast_parity.py` | **set-equal, corpus-wide.** The fast required-attribute table must produce exactly the findings libxml2 does over every installed mod's md/aiscript files. `fast \ full` is a false gating ERROR on a working mod and must be zero; `full \ fast` is a miss. A second implementation is only worth having if proven equivalent — otherwise it is a faster way to be wrong. Sampling is not enough: this passed at 25 mods and failed at 123, three separate times. |
| `perf_guard.py` | `uv run python gates/perf_guard.py --record` then `uv run python gates/perf_guard.py` | **no per-mod regression** beyond ratio > 3× **and** delta > 2.0 s together. Compares **items, never a total**: a measured 39×/51× regression on two mods summed to a 1.00× aggregate because a third got faster. The baseline is machine-local and gitignored — wall-clock is machine-specific, so a committed one would fail for everybody else. |
| `registry_provenance.py` | `uv run python gates/registry_provenance.py` | **0 violations** over your real registry: no row whose identity is a *guess* may occupy a confident lane, every stored id carries a known provenance, upstream data never appears without an identity that could have fetched it, and load→save is idempotent. Runs against a **sandbox copy** — a sweep that rewrites your triage state is itself a defect. Prints the denominator (`N/M confirmed`), because "0 violations" over an unknown population is not a result. |
| `nexus_fixture.py` | `uv run python gates/nexus_fixture.py` (replay) · `--record` (live, needs a key) | **0 parse/classification failures** against a recorded fixture, so the only network-dependent path is testable offline. The fixture is anonymized at record time — field names, types and status values preserved, ids and titles replaced — and asserted to contain no API key. Re-record periodically: a fixture that never drifts is a fixture that stopped tracking the API. |

## Inputs

Every input resolves through `gates/_env.py` → `x4validate._paths`, i.e. the same
env → `.claude/x4-paths.env` → fallback chain the CLI uses. Nothing is hardcoded:

| | from |
|---|---|
| installed extension set | `$X4_GAME` / `$X4_EXTENSIONS` |
| mod source folders (`regress.py`) | `$X4_MODS` |
| captured engine log (the two oracles) | **`$X4_ORACLE_LOG`** |

`$X4_ORACLE_LOG` must be a **capture, not the live `debug.txt`** — if the log moves
between runs the denominator moves and 234/234 stops meaning anything. It is
deliberately never committed: a real `debug.txt` names the mods you run, your
filesystem layout and your play session. Reproducing these numbers means supplying
your own log against your own modlist; the *bars* are what transfer, not the counts.

**A missing input is a SKIP with a named reason and exit 2** — never an empty run
that prints like a pass. Verified 2026-07-29 from a scrubbed environment, and re-verified 2026-08-08 across
all gates that take inputs: each
exit 2 and say which setting is absent.

> Until 2026-07-29 three of these four opened with hardcoded absolute paths from
> one developer's machine, and an earlier version of this README claimed the
> opposite. If you add a gate, take its inputs from `_env`.

**Why `oracle.py` is not in `tests/`:** it needs the installed extension set and
a specific captured log. A developer without those would see it fail for reasons
unrelated to their change, which is exactly how a gate gets disabled.

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

## Running them

**`scripts/run-gates.sh`** — quick gates by default, `--all` for everything (~55 min),
`--list` for the roster. It reports what it did **not** run and why, and the buckets sum
to the population: a bare *all green* from a runner that quietly skipped nine gates is the
defect this toolkit exists to refuse.

Until 2026-08-28 there were 27 gates and no runner, and CI cannot help — the gates need a
real X4 install. So they ran when someone remembered, which makes every gate's coverage a
matter of chance. **A gate nobody runs is indistinguishable from a gate that passes.**
`mutation_probe.py` is excluded even from `--all`: it rewrites source in place, so it must
run alone and be announced (gotcha #27).

⚠ Its first real run found two stale derived artifacts nobody had noticed — the effective
store and BaseX `x4eff`, both behind a modlist that three concurrent sessions had changed.
That is the argument for the runner in one line.
> **Measured runtimes — background the long ones.** A foreground Bash call is capped at
> 600000 ms (10 min) and a larger `timeout` is silently clamped, so an over-cap run is killed
> mid-way and looks like a hang. MEASURED on the reference machine over 115 mods:
> MEASURED on a full sweep 2026-08-26: **`corpus_sweep.py` ~1230 s** (242 runs, both tiers) ·
> **`perf_guard.py` and `--record` ~685 s** (replays `--update` per mod) ·
> `xsd_fast_parity.py` ~220 s · `schema_sweep.py` ~180 s · `noop_audit.py` ~160 s ·
> `regress.py` ~155 s · `stress_sweep.py` ~150 s · `update_corpus.py` ~105 s ·
> **`mutation_probe.py` ~70 s** (11 mutants across 3 files; a survivor costs one extra
> full-suite run, so it is slower only when it finds something). Everything else is seconds
> to ~1 min; the whole sweep is ~55 min. Run the long ones in the background, or scope them
> down (`perf_guard.py --limit=N`).

| `obtainability_audit.py` | `uv run python gates/obtainability_audit.py [--record]` | **No drift** in content the game DEFINES but cannot SELL, against a local baseline. Counts macros whose every supplier ware is tagged `deprecated`, plus LIVE macros whose ammunition is one of them. Baselined at **39 / 39 / 12 / 10** and 6 mods on the reference machine. The counts alone are near-worthless; what matters is when they MOVE — a game patch deprecating more, or a mod referencing it. Deliberately does NOT count macros with no ware at all: MEASURED **3,945 of 5,559 (71%)**, which is the normal state (bullet 170/170, scenery 89.5%) and would drown the signal. Baseline is gitignored — the counts depend on installed DLC and modlist. |
| `oracle.py` | `uv run python gates/oracle.py` | **234/234 ops agree, 0 FALSE OK.** Replays every diff op the engine itself rejected (from a captured `debug.txt`) and requires x4validate to reject the same ones. `debug.txt` is ground truth; a drop here means the merge model moved. |
| `oracle_index.py` | `uv run python gates/oracle_index.py` | **12/12 agree, 0 FALSE OK** over the index-lookup failures the engine logged. Note the structural limit stated in its own output: a failure-only log can prove FALSE OK but never completeness. |
| `oracle_reverse.py` | `uv run python gates/oracle_reverse.py [debug.txt]` | **0 disagreements with the engine.** The direction the two oracles above structurally cannot test: they replay what the engine *rejected*, so they prove "we never say fine where the engine said broken" — never completeness. This asks the reverse: the engine complained, do we notice? Covers the classes a merged tree can answer (missing text ids, missing component templates); runtime-state failures are out of scope by construction. |
| `reader_edges.py` | `uv run python gates/reader_edges.py` | **0 crashes, 0 silent-wrong results** on damaged input: BOMs, UTF-16, latin-1 in a UTF-8 file, non-XML, zero-byte `.cat`, truncated index, offset past the end of `.dat`, wrong MD5, `.dat` with no `.cat`, a mod path that is a file. Fail loudly or succeed correctly — never return garbage. |
| `regress.py` | `uv run python gates/regress.py [installed_mod ...]` | Tier A + Tier B error/degraded counts per mod under `$X4_MODS`. *(Baselines are the author's own local mod set; yours will differ. What transfers is "no unexplained change from your own last run".)* ⚠ **A dev-only copy is not a stable baseline.** `X4CapturableXenonXL_public` read 4 Tier B errors when this was written and reads **8** as of 2026-08-22 — not a regression: its installed twin `X4CapturableXenonXL` validates **0**. Tier B excludes the mod under test by folder name ∪ content.xml id, and the twins' ids differ (`X4_Capturable_Xenon XL` vs `…XL PERSONAL`), so the installed twin is merged into the very tree the dev copy is checked against — its own `<remove>` ops are already applied, and the dev copy's identical ops then match nothing. See docs/BLIND-SPOTS.md **F32**. |
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
| `mutation_probe.py` | `uv run python gates/mutation_probe.py` [`--recover`] | **every mutant killed.** Breaks a guard deliberately and requires the suite to notice. A survivor is a line nothing really checks — its first run found the RFC-5261 ambiguous-selector rule was untested by anything a contributor can run. **Covers `_merge.py`, `_registry.py` and `_compat.py` (11 mutants; 11/11 killed as of 2026-08-26)**, selected so that every mutant inverts a guard whose failure has a MEASURED cost in the register — a contrived mutant nothing kills is noise, not a finding. A mutant that HANGS is its own verdict, not a pass. ⚠ **THIS GATE DELIBERATELY BREAKS THE WORKING TREE WHILE IT RUNS**, and the mutated file is a TRACKED file, so the tree looks normal — tell anyone sharing it before starting. It writes `.mutation-probe-active` for the duration (a second party can check for that without asking you) and keeps byte-for-byte copies in `.mutation-probe-pristine/`, because `finally` does NOT run on SIGKILL. If a run is killed, the next invocation REFUSES with exit 2 and names `--recover`, which restores and says WHICH file was mutated. Proven by actually killing a run mid-mutation, not by simulating it. |
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
| `claims_audit.py` | `uv run python gates/claims_audit.py` | **every numeric claim in `dev/_registry/CLAIMS.tsv` re-checked against the effective store, at the TIER the claim is about.** Prose cannot be tested, so a design doc's numbers rot in silence; this makes them fail. UNRESOLVED is never a PASS, and the gate REFUSES to run (exit 5) against a stale store rather than answering from a world that has moved on. |
| `update_corpus.py` | `uv run python gates/update_corpus.py` | **every planted break found.** A synthetic mod carrying every documented 9.0 break (XSD-gating, runtime-grep and expression-lint tiers). `--update` was only ever smoke-tested, and a migration checker that silently detects nothing is indistinguishable from a clean mod. |
| `xsd_fast_parity.py` | `uv run python gates/xsd_fast_parity.py` | **set-equal, corpus-wide.** The fast required-attribute table must produce exactly the findings libxml2 does over every installed mod's md/aiscript files. `fast \ full` is a false gating ERROR on a working mod and must be zero; `full \ fast` is a miss. A second implementation is only worth having if proven equivalent — otherwise it is a faster way to be wrong. Sampling is not enough: this passed at 25 mods and failed at 123, three separate times. |
| `perf_guard.py` | `uv run python gates/perf_guard.py --record` then `uv run python gates/perf_guard.py` | **no per-mod regression** beyond ratio > 3× **and** delta > 2.0 s together. Compares **items, never a total**: a measured 39×/51× regression on two mods summed to a 1.00× aggregate because a third got faster. The baseline is machine-local and gitignored — wall-clock is machine-specific, so a committed one would fail for everybody else. |
| `registry_provenance.py` | `uv run python gates/registry_provenance.py` | **0 violations** over your real registry: no row whose identity is a *guess* may occupy a confident lane, every stored id carries a known provenance, upstream data never appears without an identity that could have fetched it, and load→save is idempotent. Runs against a **sandbox copy** — a sweep that rewrites your triage state is itself a defect. Prints the denominator (`N/M confirmed`), because "0 violations" over an unknown population is not a result. |
| `nexus_fixture.py` | `uv run python gates/nexus_fixture.py` (replay) · `--record` (live, needs a key) | **0 parse/classification failures** against a recorded fixture, so the only network-dependent path is testable offline. The fixture is anonymized at record time — field names, types and status values preserved, ids and titles replaced — and asserted to contain no API key. Re-record periodically: a fixture that never drifts is a fixture that stopped tracking the API. |
| `toolkit_usage.py` | `uv run python gates/toolkit_usage.py [--record]` | **Which of our own instruments do we still reach for.** Enumerates the CLI surface by ASKING the programs (pyproject `[project.scripts]`, `--help`, and argparse's invalid-choice listing) — never by parsing source, which is how the hand measurement missed `x4debug crosscheck` and `x4xref who-calls`. Then counts INVOKED vs merely NAMED per capability across the session transcripts. Findings are BASELINE-RELATIVE: a capability `qa_sweep` has NEWLY stopped exercising, and usage drift. The 13 known coverage gaps are accepted and still printed every run (this row said 17 until an argv-shape defect in the gate was fixed — 7 of 54 qa_sweep cells lead with a global flag, so the subcommand is not argv[0]) -- visible, not silenced -- because failing on a known backlog every time is the same flood as an uncalibrated threshold. Dormancy is **INFO only** — the threshold is uncalibrated, and failing on an uncalibrated threshold is the flood that trains you to ignore the output. Baselined at **41 capabilities, 38 invoked, 3 never** on the reference machine. **Dev-only, never ported** (it reads transcripts) and the baseline is gitignored. Refuses (rc 2) rather than guess: the project directory is derived from the game root, and zero invocations across the whole surface is treated as the wrong transcripts, not as disuse. |
| `control_bytes.py` | `uv run python gates/control_bytes.py [extra paths...]` | **0 hits** over every git-tracked text file plus any permanent-record files you pass (CLAUDE.md, KNOWLEDGEBASE.md, a memory directory). Finds collapsed-escape CONTROL BYTES — 0x07/0x08/0x0B/0x0C/0x1B, i.e. a `\a` `\b` `\v` `\f` that went to disk as the character instead of the escape. MEASURED 2026-08-30: three files in two days, one cause (content written through an inline interpreter string), none visible in any normal view — one inside the sentence documenting an escaping defect. rc 1 on a hit with offset and context; rc 2 when nothing was scanned, because a sweep over zero files is not a clean sweep. ~1 s over 242 files. |
| `lockstep.py` | `uv run python gates/lockstep.py` | **The two halves of the live channel agree in the COMMITTED blobs.** The channel's identity is spelled in two repositories — `<savedvariable name=...>` in the probe mod's `ui.xml`, `DEFAULT_VAR` in `x4validate/_livedump.py` — and a rename touches both. F87: one side was committed and the other left unstaged for two days, and BOTH sessions verified it by reading their WORKING TREES, where the rename was complete and correct. Two eyeball checks of two artifacts is not a check of the PAIR. This reads `git show HEAD:` on each side, in one command, and never consults the working tree for the verdict. rc 1 on mismatch or on a mod half that exists only in the tree; **rc 2 when it could not look** — an unreachable repo, an absent path, or a pattern matching nothing, because a gate that cannot tell "they agree" from "I did not look" is worse than none. The mod is located by GLOB, so no personal folder name is baked in. ~2 s. |

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

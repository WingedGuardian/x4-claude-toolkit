# Why you can trust this toolkit — and exactly where you cannot

This is the honest answer to *"how do I know these tools are telling me the truth?"*

It is not a claim that the toolkit is bug-free. Forty-two defects have been found in
it so far, every one by the toolkit or its own gates rather than by a user getting a
wrong answer, and the forty-third exists. The claim is narrower and checkable:

> **Every defect SHAPE that has occurred here has a test or gate that mechanically
> bans its recurrence; every answer that could be wrong carries a denominator and a
> freshness stamp; and where the engine can arbitrate, it does.**

An "audit found nothing" is not evidence — that criterion resets every time someone
looks harder. The table below is the evidence, and each row cites the file that
enforces it, so *"is this shape guarded?"* is a lookup rather than a feeling.

---

## The defect register

| # | Defect shape | MEASURED cost when it happened | What bans it now |
|---|---|---|---|
| 1 | **Enumeration narrowing** — a walk that sees only part of the corpus (loose files only, so packed mods and the two packed mini-DLC are invisible) | BaseX `x4eff` held **23 of 142** mini-DLC documents (16%) and reported success. The same shape was written **7 times** in different files | `tests/test_no_loose_only_reference_walk.py`, `tests/test_no_packed_only_scan.py`; one shared helper (`_scan.iter_mod_xml`, `_effective.base_vpaths`) that every caller must use |
| 2 | **Wrong population** — the check covers a different set than the finding | A `modulegroups` census reported **200** groups from 9 sources; the answer was **146** from 5, because `reference/` and `extensions/ego_dlc_*` are the same content counted twice | `gates/tool_properties.py`; the routing table in `CLAUDE.md`; `_scan.iter_corpus_xml` excludes `ego_dlc_*` by construction |
| 3 | **Wrong mod scope** — "installed on disk" used where "what the engine loads" was meant | One disabled mod put 3 macros into the effective index as live, named it in 4 collision rows, and let **Tier B resolve a selector against it and report OK** — a false pass in the mode built to catch silent no-ops | `tests/test_mod_scope_is_explicit.py` (scope must be a **literal**), `_registry.mods(scope)` with scope positional and required |
| 4 | **A stale artifact answering for a world that moved** | BaseX `x4eff` served pre-merge-fix values for **11 days**; on rebuild **140 of 194** engine-thrust rows changed, with no input file altered | `_freshness.py` two-axis fingerprint (content + engine bytes); `ask.py` and `gates/claims_audit.py` **refuse** rather than answer from a stale store |
| 5 | **A silent no-op reported as applied** | A bare `continue` dropped **858** root-`<replace>` operations while marking them applied, so the effective store served vanilla values for real mod overrides | `AppliedOp.ok` must carry a reason; `gates/noop_audit.py` re-proves it corpus-wide |
| 6 | **A zero rendered as a finding** — "nothing found" reported without saying whether anything was looked at | A corpus sweep threw on **all 4,391 files**, swallowed it, and reported *"0 dangling across 115 mods"* when the answer was 3 | `CorpusScan.verdict()` **raises** rather than render a zero over an empty population; `ask.py` requires a coverage denominator before printing a negative |
| 7 | **The checker was wrong, not the code** | **16 of 16** checking-step errors across four sessions were the instrument: `$?` after a pipeline, a text splitter arbitrating a structured format, an AST scan under the wrong interpreter reporting a file "unparseable" | Planted-truth gates (`gates/diff_truth.py`, `gates/oracle*.py`) — the checker is validated against known answers; every AST guard **raises** on a parse failure instead of skipping |
| 8 | **An aggregate hiding a per-item regression** | Two mods went **2.8 s → 112 s** and **2.4 s → 121 s** while the total moved **1.00×**, because a third got faster | `gates/perf_guard.py` compares **items, never totals** |
| 9 | **Two doors to one question** — the same thing resolved by two independent code paths | Tier B and `x4effective` gave contradictory answers about the same value, each internally consistent | One implementation per question; `gates/cross_tool.py` asserts tools agree |
| 10 | **An executable that resolves its own environment** — instead of delegating to the one resolver | A fingerprint script defaulted to a developer's absolute path: on any other machine it fingerprinted nothing and reported **FRESH forever**. A corpus build did the same and would index **zero documents, exit 0** | `tests/test_env_resolution_is_delegated.py` (AST, with a scoped escape hatch); `scripts/verify-cold.sh` runs all 9 CLIs on a genuinely cold checkout |

---

## What the guarantees actually are

**A negative answer carries its denominator, or it is refused.** "Nothing references X"
is only printed when the tool can say *over how many documents* it looked and name
every exclusion. A bare zero is a lead, never a fact.

**A stored answer says when it was true.** Every persisted artifact carries a two-axis
fingerprint: the installed content, and a hash of the merge/enumeration engine's own
bytes. A merge fix changes the right answer for identical inputs — so the artifact
goes stale and the tools say so, rather than serving the old answer confidently.

**A guess never wears the grammar of a measurement.** Provenance travels with the
value; nothing derived from a guess is promoted into a confident state.

**An unconfigured toolkit refuses.** Every CLI exits **2** — never 0 with a
plausible-looking answer computed from a directory that does not exist, and never 1,
which means "the thing you asked about has findings".

**The engine is the referee where it can be.** `x4debug crosscheck` compares what the
game actually skipped against what the validator predicted, per item. It found 1,206
false positives in our own tool — the half of the comparison Egosoft wrote cannot be
fooled by our assumptions.

---

## Where you cannot trust it (stated, not hidden)

- **Load order between mods is community convention, not engine-documented.** Any
  result that turns on *which mod won* is advisory and says so.
- **Every finding is recorded individually** — F1–F42, each with a measured cost, and
  where a limit was accepted rather than fixed, the reason it was accepted. The
  per-finding register (`docs/BLIND-SPOTS.md`) lives in the development tree because
  its evidence cites a specific private modlist by name; the findings fixed in each
  release are summarised in `CHANGELOG.md`, and the shapes are the table above.
- **A clean validate is necessary, not sufficient.** It does not replace an in-game
  test and a `debug.txt` read. The reference/completeness catalog is partial.
- **BaseX indexes are discovery instruments.** Use the effective store for claims
  about live values.
- **Windows is the tested platform.** Linux/macOS paths exist and are exercised, but
  a handful of tests are Windows-only by construction and skip elsewhere.

## How to check any of this yourself

```bash
uv run python -m pytest -q          # the suite
bash scripts/verify-cold.sh         # behaves on a machine with no X4 installed
uv run python gates/<name>.py       # any single gate; see gates/README.md
```

Every gate prints its denominator. If one prints a finding without one, that is a bug
in the gate, and it is the kind we most want reported.

# QA Process for New Tools

Distilled from a campaign that took this toolkit from "works when I use it" to
17 findings fixed, 24 gates, and a 379-test suite — with every late-stage bug
found by QA instead of by a user. Follow this for any new tool (or any major
feature on an existing one) **before** it is considered releasable.

The one-line summary: **a corpus pass proves robustness; only generative,
differential, and exhaustive techniques prove correctness.** Our broad corpus
pass found *one* bug; the other sixteen came from everything below.

---

## Phase 0 — Contracts, at design time

Cheaper to build in than to retrofit. Every tool must:

- **Report what it could not examine.** A skipped file, an unparseable archive,
  an unresolvable selector is a `skipped`/`unreadable` channel entry — never a
  silent `continue`. The AST guard (`tests/test_no_silent_swallow.py`) enforces
  this over the package **and** `gates/`; new code gets a `# silent-ok: <reason>`
  only when the miss provably surfaces elsewhere.
- **Never render its own limitation as a verdict** about the thing it checks.
  "I could not check X" and "X is wrong" are different outputs.
- **Never assert a fact it did not look up.** A message saying "X is installed"
  must be backed by a check of X's installation, not by the branch it sits in.
- **Carry denominators.** "0 findings" is meaningless without "over N of M".
  A truncated list must say it is truncated (`_scan.count_line`).
- **Never mutate the state it inspects.** Gates run against sandbox copies of
  registries/profiles; a QA sweep that regenerates a user file is a defect.
- Exit codes: 0 clean · 1 findings/violations · 2 misconfiguration · 3 degraded
  (nothing examined must never exit 0). `--version` from day one.
- Anything slow announces itself **before** the wait (a 2-minute silence reads
  as a hang), and only when genuinely slow — announcing a 0.0s step is noise,
  and noise is how real warnings stop being read.

## Phase 1 — Unit + property tests

- Tests for every behavior you fixed or decided — including the *other* side:
  a test that only pins "the bad thing is flagged" passes against a checker
  that flags everything. Always assert the clean case too.
- **Property tests** where the tool's algebra allows: identity (`diff(A,A)=∅`),
  antisymmetry, monotonicity (lower threshold ⊇ higher), idempotence.
- **Planted ground truth**: mutate a copy of real input in N known places; the
  tool must report exactly those, nothing more. (Exclude identity attributes —
  changing an `id` changes *which element it is*, which correctly reads as
  structural.)

## Phase 2 — The corpus pass (necessary, not sufficient)

Run every subcommand × mode over the full real install (`qa_sweep` pattern:
exit code, output size, traceback check). Expect it to find little — a corpus
only contains what someone already wrote. Its value is robustness and a
baseline for later differentials.

## Phase 3 — Generate and perturb (where the bugs actually are)

- **Mutation probe**: delete each guard/check; the suite must go red. A guard
  the suite cannot miss is untested. (Found: a load-bearing RFC-5261 guard that
  was deletable with everything green.)
- **Property fuzzing**: thousands of generated ops/inputs, multiple seeds —
  one bug here appeared under exactly one seed of six.
- **Determinism**: run twice, byte-compare. (Found: set-iteration order leaking
  into reports.) **Builder idempotence**: build twice, artifacts identical.
- **Concurrency**: race two builders on one output; race the same CLI against
  itself. The loser must lose *quietly* and leave valid state. And re-check the
  probe still tests its subject after each fix — ours silently stopped racing
  when an unrelated validation rejected its arguments, and still went green.
- **Hostile/edge input**: missing paths, wrong types, negative numbers, entity
  bombs, 400-deep nesting, unicode + RTL, paths past MAX_PATH, damaged
  archives (bad MD5, truncated index, orphan .dat), unconfigured environment
  (with *every* env alias cleared and CWD outside the repo — ours silently
  found its own dev config the first time).
- **Unseen corpora**: point the tool at inputs it has never processed. The
  biggest perf bug (a >900s hang) came from the first never-before-seen mod.

## Phase 4 — Differential and oracle (the strongest evidence)

- **Second-implementation parity**: if a fast path reimplements a slow one, a
  gate must prove **set-equality over the full corpus** — not a sample. Ours
  passed at 25 mods and failed at 123, three separate times.
- **Cross-tool agreement**: two tools answering the same question must agree
  (e.g. conflict winner vs provenance origin). Each audit that only compares a
  tool to itself misses this whole class.
- **Engine oracle, both directions**: everything the engine rejected we must
  flag; everything the engine accepted we must not gate on. A live `debug.txt`
  is a standing oracle — check whether the engine *already answered* before
  declaring something untestable.
- **Old-vs-new output differential**: run the previous release and the current
  tree over the full corpus; classify **every** changed finding against an
  intended cause. Unexplained delta = regression. "42 added, 0 removed" is only
  reassuring after all 42 are attributed.
- **Old-vs-new performance differential, PER ITEM**: our real 39×/51×
  regression summed to a **1.00× total** because another item got faster.
  Aggregates lie. Keep a machine-local (gitignored) baseline (`perf_guard`);
  fail only on ratio AND absolute delta together; **prove the guard fires** by
  tampering the baseline once (a gate that cannot fail is not a gate).

## Phase 5 — Real-workflow use

Use the tool for an actual task before release. This is a *distinct technique*:
it found a whole missing capability (a collision class structurally invisible
to the existing scan) after four rounds of synthetic QA found nothing new.

## Phase 6 — Exhaustive output audit ("the litmus test")

For every enumerable output the tool produces on the real corpus, verify it
against **independently derived** truth — a fresh parse, never the tool's own
index or helper functions. Citations must resolve to the exact line; numbers
must match the file; every reported pair must recompute to its printed score.

Verifier discipline, learned the hard way — **every single "violation" our
audits found was a bug in the verifier, not the tool**:
- Check the checker before accusing the tool.
- Key by (name, **source**) — collapsing copies by name compares wrong pairs.
- Count everything unreadable/unresolved and **fail** on it; never excuse it.
  A negative over 56% coverage is not a negative.
- A verifier that samples zero rows must FAIL, not pass vacuously.
- A gate's own status line must not misdescribe it ("0 elements" printed next
  to "exact parity" reads as vacuous verification even when it is not).

## Phase 7 — Release

- **Cold red-team**: a docs-only agent with no session context attempts the
  install and a first task. (Found two release blockers, including an install
  script dead on two of three OSes.)
- Personal-data scan on staged content (names, profile ids, absolute paths,
  API keys). Fixtures are anonymized at record time and asserted key-free.
- Version bump everywhere, CHANGELOG entry, `--version` correct; never re-point
  an existing tag; check open PRs before pushing.
- All gates green **in the public copy**, not just dev — run the suite there.

## Stopping criterion

Not "ran out of ideas". Track the discovery curve per round of *new* technique:
ours ran 10 → 6 → 3 → 0 → 1 → 0. Stop when a genuinely new technique returns
null AND a real-use round has happened AND every identified gap is closed —
then say plainly that this is evidence of diminishing discovery, not proof of
zero bugs, because no testing provides that. What protects users afterwards is
the gates re-running on every change, not the memory of this campaign.

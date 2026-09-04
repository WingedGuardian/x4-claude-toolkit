# What gets reviewed, and what does not

## Why this file exists

The release rule in the maintainer's global instructions reads: *"Not a review of the
last change, or of the risky-looking part. The whole release surface: every commit since
the previous release, and every file the bundle ships."*

Applied literally, that turns every release review into a **whole-repository audit**.
MEASURED on the v3.0.0 round-6 review, which was aimed at "the 9,163 lines earlier
rounds declared unread":

| | |
|---|---|
| findings | 3 CRITICAL + 13 IMPORTANT |
| of those, **predating the 3.0 arc** | **15 of 19 defect sites** (oldest 2026-06-23) |
| both CRITICALs | **already shipped in v2.8.0**, byte-identical |

So the round spent most of its budget finding defects that were already in users' hands
and that shipping or not shipping v3.0.0 would not change either way. That is a real
audit and worth doing — but it is not a **release gate**, and conflating the two is what
made three consecutive rounds each return ~15 findings and never converge.

**The split this file establishes: a RELEASE review is scoped to what the release
CHANGES. A CODEBASE AUDIT is scoped by blast radius and runs on its own schedule.**

---

## Track 1 — the RELEASE review (gates the release)

**Scope: every production file the arc ADDED or MODIFIED, and nothing else.**
Derive it, never list it from memory:

    BASE=$(git rev-list -n1 <previous release tag>)
    git diff --diff-filter=AM --name-only $BASE..HEAD

A file the arc did not touch cannot contain a regression the arc caused. If it holds a
defect, that defect is already released, and it belongs to Track 2.

**Two things this scope must NOT inherit from a diff-scoped review** (CLAUDE.md #37 --
a diff-scoped review cannot find a defect that predates the diff):

1. A file the arc **modified** is reviewed **in full**, not just its hunks. The arc's
   change may be correct while the function around it is not, and the arc is what puts
   it in front of new users.
2. A subsystem the arc **added** is reviewed in full before its first release, however
   large. MEASURED: `live_query.lua` (2,501 lines) was added on 2026-08-31 and first
   read in round 6 -- it carried 1 CRITICAL + 3 IMPORTANT, every in-arc finding of the
   round.

**Release exit criterion:** zero CRITICAL and zero IMPORTANT **among in-arc findings**.
Pre-existing findings are recorded to Track 2 and do not hold the release.

---

## Track 2 — the CODEBASE AUDIT (does not gate any release)

Ranked by one question: **does a defect here produce a confidently wrong FACT?**
That is the maintainer's criterion -- "the tools that are actually going to be spitting
truth values at us and declaring something is factual or not" -- and it sorts the repo
better than size or age does.

### Tier 1 — ORACLES. A defect writes a wrong fact into permanent record.

| file | lines | why it ranks here |
|---|---|---|
| `_compat.py` | 907 | computes LOAD ORDER -- decides who wins every conflict (#13) |
| `_effective.py` | 898 | builds the effective tree every "effective value" claim quotes |
| `_merge.py` | 836 | applies diffs; where 858 dropped-ops-reported-applied lived |
| `_resolve.py` | 247 | reference resolution (partial coverage only) |
| `_diff.py` | 189 | the diff primitive |
| `_xpath.py` | 47 | the selector primitive |

~3,124 lines. **Highest-value review in the repository.** Every Three-Values answer,
every Tier B verdict and every provenance claim rests on these six. All shipped since
v2.5.0, so none is a release blocker -- and all are load-bearing for correctness.

### Tier 2 — INSTRUMENTS. A defect means a gate cannot go red.

`gates/` (31 files, ~7,072 lines), `scripts/run-gates.sh`, `verify-cold.sh`,
`fuzz-guard.py`. Review the **contract**, not the logic: for each gate ask *what,
concretely, would make this go red?* (#26). MEASURED precedent -- round 5's B5 found a
FALSE OK that could not fail the run; round 6 found `qa_sweep` accepting
`expect=(0,1,3)` and `--sel-only` declared but never read. Both are cells with no
reachable failing branch.

### Tier 3 — FRESHNESS / PROVENANCE. A defect makes a stale artifact read as current.

`_freshness.py` (678, partial), `_provenance.py` (119).

### Tier 4 — REPORTING CLIs. A defect produces visibly wrong output.

`_effectivecli.py`, `_debugcli.py`, `_savecli.py`, `_diffcli.py`, `_changed.py`,
`_threeway.py`, `_debuglog.py`. Lower priority **because a wrong number on screen is
seen, while a wrong fact in the store is not.**

---

## Explicitly OUT of scope for human review

| | lines | why, and what covers it instead |
|---|---|---|
| `tests/` | 27,314 | **Not read. Swept MECHANICALLY.** A test that does not assert is exactly a tool declaring something factual when it is not -- so the risk is real, but it is a SHAPE, and shapes are better caught by an AST scan over all 114 files than by reading any of them. Sweeps: bare `return` as a precondition bail (round 5's B6 -- 3 tests reported PASSED without asserting), an assertion satisfied by a COMMENT or docstring (round 5's B7), `assert` on a substring where a structure is meant, and a mutation that leaves the named test green. `tests/test_no_bare_return_in_a_test.py` is the pattern to extend. |
| `tools/basex/` | 2,088 | Discovery, not proof -- its answers are never quoted as facts without a denominator. **Exception: `ask.py` is Tier 2**, since refusing a zero-result without coverage is the standard the rest of the repo is measured against. |
| `_nexus.py` | 240 | External API client. A defect yields a failed lookup, not a wrong local fact. |
| vendored `BaseX.jar` | -- | Third-party binary, BSD-3-Clause. Not ours to review. |

---

## The rule that makes this converge

**Record every finding with its ORIGIN, measured, not assumed:**

    git blame -L <line>,<line> --porcelain -- <file>

and bucket it IN-ARC or PRE-ARC against an explicit `<tag>..HEAD` range. Never
`--since`: it filters on COMMITTER date while `--date=short` prints AUTHOR date, which
silently drops commits and mis-reports a file as untouched (#37).

A review that does not separate the two will keep re-finding the repository's whole
history at every release, and will read as "the fixes are causing new bugs" when the
measured answer is the opposite.

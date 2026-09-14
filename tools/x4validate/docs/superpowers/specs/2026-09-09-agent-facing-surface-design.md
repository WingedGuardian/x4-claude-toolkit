# The agent-facing surface: a generated MCP registry, a routing gate, and a permanent CLAUDE.md ratchet

Date: 2026-09-09
Status: DESIGN — approved in outline, nothing implemented
Supersedes the 2026-09-07 outline, which was never written to file and whose premise has since changed.

All figures MEASURED on 2026-09-09 against the post-rewrite tree unless labelled otherwise.
Reproduction commands in Appendix A.

---

## 1. The standing objective (user-set, 2026-09-09)

**`CLAUDE.md` is loaded into every session, so making it smaller is a PERMANENT objective, not a
one-time cleanup.** The user's words, and they correct a framing this design previously carried:

> *"Just because CLAUDE.md is under the limit now because we optimized it a bit, doesn't mean we
> don't need a permanent fix. It should absolutely be something that is always looked at and
> always scrutinised to try to make it as small as possible."*

⚠ **Why the previous framing was wrong, in this workspace's own terms.** "Under 40,000 chars" is a
threshold that **cannot go red in the way that matters** (#26/#35): it reports PASS on a file full
of content that has a better home. Being under budget is not evidence that anything in the file
earns its place. **So the deliverable is a mechanism that keeps asking, not a number that was hit
once.** That is Workstream C, and it is the reason MCP is worth building even though the size
emergency is over.

---

## 2. The problem, measured

### 2a. Where CLAUDE.md stands now

A peer session cut it from **154,425 to 38,056 chars (−75.4%)** on 2026-09-07/08 by moving the
whole XML domain into a new `x4-xml-patching` skill (`2578d9a`, `fde0b91`, `e06444b`).

**That is the proof of mechanism this design rests on.** The question is no longer *"can content
leave CLAUDE.md?"* — it demonstrably can. The question is *what tier each kind of content belongs
in*, and whether anything enforces it.

Current state: **38,056 chars against a self-declared 40,000 budget — 95.1% full, 1,944 chars of
headroom**, under a rule the file states itself: *"Add a rule here only if no skill could ever be
triggered for it."*

Largest remaining sections:

| section | chars | % |
|---|---|---|
| Checking Your Own Work | 5,041 | 13.5% |
| Safety Rules | 3,256 | 8.7% |
| **Route the question before you search** | **2,617** | **7.0%** |
| A Derived Artifact Must Declare WHEN It Was True | 2,325 | 6.2% |
| Concurrent Sessions | 2,315 | 6.2% |

Skill precedent, for scale: `x4-xml-patching` is **24,521 chars**, the other seven skills 2,372 –
12,603 chars each — all loaded on demand, none resident.

### 2b. Five CLIs are absent from the routing table, and nothing can detect that

**⚠ CORRECTED 2026-09-12. The original heading read "Three CLIs are routed by NOTHING", and that
was measured over the wrong population and is FALSE.** It counted mentions in `CLAUDE.md` and
`.claude/skills/` only. Measured across the surfaces a cold agent actually reads:

| CLI | CLAUDE.md (then) | any skill | **KNOWLEDGEBASE.md** | **toolkit README** |
|---|---|---|---|---|
| `x4diff` | 0 | 0 | **10** | 0 |
| `x4save` | 0 | 0 | 0 | **5** |
| `x4live` | 0 | 0 | **27** | **13** |

`x4live` had **40 mentions**, including a dedicated README section with worked commands. The
sentence *"reachable only by someone who already knows it exists"* did not follow from the clauses
measured, and should never have been written.

★ **REFUTED BY EXPERIMENT, 2026-09-12.** A cold agent, given the workspace and a live-game routing
question with no hint that `x4live` exists, **found it and answered correctly in 193 seconds** — via
`KNOWLEDGEBASE.md` and the toolkit `README.md`, before the routing row existed. It independently
surfaced the not-a-census caveat, the ~93% Unknown names, per-launch sector tokens, the drift rate,
and the offline-only rc-2 half. **Cost of the gap: not unreachability. It is search cost** — 39 tool
calls and ~74k tokens to reach a lookup a resident row answers for free.

**So the justification for the routing requirement is RESIDENT ROUTING for a cold session, not
discoverability.** The gate must enforce exactly the user's rule — every CLI in the routing table —
and must NOT claim to protect against a tool being unfindable. Stating the stronger claim in the
gate's own docstring would re-introduce the error this paragraph corrects.

What remains true, and is the real finding: **the requirement is unenforced.** Whether a CLI is in
the routing table is a prose property no check tests, which is why 5 of 11 were absent through a
full rewrite. Landed 2026-09-12: all five rows added, table now 11 of 11, +732 chars.

Compounding it: a CLI has four hand-maintained registration points — `pyproject.toml`, the literal
`== 11` in `tests/test_unconfigured_refusal.py:108`, `gates/qa_sweep.py`, and
`scripts/verify-cold.sh`.

### 2c. What the routing table now points at

The table is **11 data rows**, 2,617 chars. Classified by target:

| target | rows | can MCP carry it? |
|---|---|---|
| a CLI | 7 | **yes** |
| BaseX (`ask.py`) | 2 | **yes** (approved scope) |
| the `x4-xml-patching` skill | 1 | no — it is a skill pointer |
| Claude Code native (Glob/Grep) | 1 | no — already first-class |

**9 of 11 rows are migratable, up from 10 of 19 on 2026-09-07.** The ratio improved because the
five internal-Python-API rows (`_scan.iter_corpus_xml`, `_registry.mods`, `_effective.base_vpaths`
…) already left for the skill. Those were the rows MCP structurally could not carry, and they are
no longer CLAUDE.md's problem.

---

## 3. The three-tier model

The rewrite established two tiers empirically. MCP is the third, and each tier has a test.

| tier | holds | loaded | the test |
|---|---|---|---|
| **CLAUDE.md** | what applies regardless of task — orientation, safety, self-checking | every session | *could no skill ever be triggered for this?* |
| **skills** | domain procedure and its traps | on demand | *is this about how to DO a kind of work?* |
| **MCP** | the tool INVENTORY — names, arguments, what each answers | on demand, self-describing | *is this derivable from the code?* |

**The MCP tier's defining property is that it is GENERATED.** Everything in it is reflected from
`pyproject.toml` and argparse, so it cannot drift from the code and cannot be forgotten when a CLI
is added. That is the whole argument; the protocol is incidental.

---

## 4. Decisions already taken

| decision | choice | when |
|---|---|---|
| Architecture | hybrid: generated MCP owns the tool inventory, skills own task procedure, the routing table keeps only what MCP cannot reach | 2026-09-07 |
| MCP scope | **the 11 CLIs + BaseX.** Internal Python APIs stay prose (now in the skill) | 2026-09-07 |
| Native tools | Claude Code's Grep/Glob/Read stay native, never wrapped | 2026-09-07 |
| Shipping | MCP ships as the **primary** agent surface; the CLI remains the fully-supported fallback | 2026-09-07 |
| Everything public | settled — including x4live's write path. **Do not re-raise** | 2026-09-07 |
| CLAUDE.md minimisation | a **standing objective**, mechanised, not a one-time cut | 2026-09-09 |

---

## 5. Non-goals

- Wrapping internal Python APIs. They are library calls made inside analysis code, and they now
  live in `x4-xml-patching` where they belong.
- Replacing the CLI. Gates, CI, `verify-cold.sh` and the user's shell all drive the CLIs. MCP is
  strictly additive: anything MCP does, the CLI must still do.
- A cross-plugin registration ABI (DevBench's C-ABI). It rests on an ecosystem X4 does not have —
  X4 mods are ui-lua in an environment the engine rebuilds on every reload, `_G` included.
- Compressing rules for their own sake. Workstream C moves content to a better tier; it does not
  make surviving rules terser at the cost of their teeth.

---

## 6. Workstream A — the routing coverage gate

**`gates/routing_coverage.py`**: derive the expected tool list from `pyproject.toml` plus argparse
introspection; fail if any CLI or subcommand is absent from BOTH **the routing surface** and the
skills. It replaces four hand-maintained registration points with one derived list.

**"The routing surface" is defined by which workstreams have landed, and the gate must read it from
one place rather than guessing:** before B it is CLAUDE.md's routing table; after B it is the
generated MCP registry, with the table holding only the 2 non-migratable rows. The gate takes the
surface as an explicit input (a module constant naming the files it scans), so the change from one
to the other is a one-line edit with a test, not a silent reinterpretation. A gate that inferred the
surface would pass for the wrong reason the moment B landed.

Deliverables:

1. The gate.
2. Routes for `x4diff`, `x4save`, `x4live` — **placed per the three-tier test, not reflexively in
   CLAUDE.md.** Under Workstream B they become MCP tools; until B lands, an `x4-live` skill is the
   correct home for x4live (its traps — uidata readable only while the game is CLOSED, Alt-Enter
   emptying the id allowlist, the channel stalling when X4 is not foregrounded — are procedure, not
   inventory, and a schema cannot carry them).
3. ⚠ Adding three rows to CLAUDE.md would spend ~25% of its remaining headroom on the
   lowest-value content in the file. **A is explicitly NOT "add three rows."**

A is useful alone and lands first.

---

## 7. Workstream B — the MCP server

> ⏸ **DEFERRED 2026-09-13 (user decision), with the evidence that decided it.** Asked what
> problem MCP actually solves, each claim was measured:
>
> | claim | MEASURED |
> |---|---|
> | more reliable invocation | **2 argparse errors in 2,965 x4 CLI invocations (0.07%)** across all 38 session transcripts on the author's machine (408 MB); both were `x4diff ... unrecognized arguments` |
> | knowing everything a tool can do | real — but it comes from GENERATION (§7b), which does not need a server |
> | the right tool at the right time | in this Claude Code build, MCP tools load **name-only and deferred** (a tool-search call is needed to see a schema); the routing table is in context every turn |
> | context cost | the tools' help text is **25,546 chars vs the routing table's 2,230 (11.5×)**. The table's `Not` column is earned judgement, not derivable from code, so the rows would not actually migrate |
> | new failure surface | MCP calls bypass the Bash guard hooks; output can be capped; stdio carries the protocol on stdout; +29 packages for `mcp` 2.2.0 |
>
> **Built instead:** the generated `x4-cli-reference` skill (`tools/x4validate/scripts/gen-cli-reference.py`,
> fresh-checked by `tests/test_cli_reference.py`) — the drift-proof inventory, loaded on
> demand — while the routing table stays the "right time" surface.
>
> **Reopen condition:** a cold-agent A/B on the same routing questions shows MCP tools beat
> the routing table plus the generated reference. The baseline to beat is not "nothing":
> without a routing row a cold agent needed 39 tool calls and 193 s; with one, about one call.
> §7a-7d below are kept unchanged as the design to build if that condition is met.

### 7a. Shape

One server, **13 tools**: 11 reflecting the CLIs (one tool per CLI, `action` enum over its
subcommands), plus `basex_ask` and `basex_coverage` wrapping `tools/basex/ask.py`
(`mode` in {refs, attr, xq}; `--db` in {x4raw, x4eff}).

One tool per CLI rather than one per subcommand (40 tools), following DevBench's measured finding:
a cold agent reads a tool's SUMMARY as its whole story, so a tool must be named for what it does.
`x4validate`, `x4compat`, `x4debug` already are.

### 7b. Generated, never hand-written

Schemas reflected from argparse at build time. A hand-written registry would reproduce the exact
defect this workstream exists to remove. The CLIs are already self-describing — all 43 subcommands
carry `help=` strings.

### 7c. Cross-cutting requirements

- **R1 — Cold start must not raise.** `gates/_env.py` signals "no install" with
  `raise SystemExit(2)` at import; #26 records that this made a fresh clone fatal and invisible on
  a configured machine. The server MUST follow `x4validate._paths`' lazy pattern
  (`registry() -> Path | None`) and answer "no X4 install configured" as a normal tool result
  naming the fix. **Verified by `scripts/verify-cold.sh`, never by unsetting a couple of env vars**
  — `$X4_TOOLKIT` and `.claude/x4-paths.env` make that look cold when it is not.
- **R2 — The refusal contract survives the transport.** A CLI exiting 2 (stale artifact) or 3
  (nothing examined) must surface as a REFUSAL, never an empty success.
- **R3 — Freshness banners reach the caller.** The two-axis fingerprint banner must not be eaten.
- **R4 — Long jobs return a handle, never block.** `corpus_sweep` ~2100 s and `perf_guard` ~600 s+
  exceed any sane MCP timeout. Excluded, or a job handle. A call that appears to hang is worse than
  no tool.
- **R5 — No secrets.** `X4_NEXUS_KEY` must never appear in a schema, a result, or a log.

### 7d. Shipping as the primary surface

- README install flow plus the `mcpJsonSnippet` pattern.
- **Install-flow redteam with a cold, docs-only subagent** (`redteam_release_install_flow`).
- Cold-clone verification via `scripts/verify-cold.sh`.
- Tool names and `action` values become a compatibility surface: renaming one is BREAKING under the
  CLI-contract SemVer note in CHANGELOG.md.
- Full release review of the whole commit range; nothing ships while anything is outstanding.

---

## 8. Workstream C — the permanent ratchet

The user's objective, mechanised. Three parts.

### C1 — A size gate that ratchets rather than thresholds

**`gates/claude_md_budget.py`**: CLAUDE.md may never exceed its size at the last release tag. An
addition must be accompanied by a removal, and the gate names both. A hard 40,000 ceiling stays as
a backstop but is NOT the operative check — a ratchet keeps working after the emergency ends,
which is precisely what a threshold does not.

### C2 — A tier test on every addition

Every new CLAUDE.md section answers, in the commit message: *which skill could have been triggered
for this, and why was it not?* Unanswerable means it belongs in a skill. This is the file's own
stated rule, currently unenforced.

### C3 — A periodic audit, with the migratable set measured

The audit asks, per section: *is this the tier this belongs in?* Section sizes and the routing-row
classification (§2a, §2c) are the baseline it re-derives, so its result can disagree with the last
one.

**Known candidates today, MEASURED, not yet decided:**

| candidate | chars | question |
|---|---|---|
| routing table rows 2–10 | ~1,900 of 2,617 | migrates to MCP under B |
| Checking Your Own Work | 5,041 | how much is rule vs case narrative? |
| IN-SECTOR vs OUT-OF-SECTOR | 1,755 | is `x4-balance` the right home? |
| Three Values Rule | 672 | same question |

⚠ **These are candidates, not a plan.** Each needs the §9 rule-retention check before it moves,
and the IS/OOS and Three-Values rules are user-set mandatory rules — moving them to a skill risks
them not being in context when a balance claim is made outside a balance task. **That specific
risk is why C3 is an audit that reports, not a job that cuts.**

---

## 9. Verification — every check must be able to go red

| workstream | the check | proven falsifiable by |
|---|---|---|
| A | `routing_coverage.py` | delete a CLI's route -> gate fails NAMING it; add a bogus CLI to pyproject -> gate fails |
| A | compound-condition twins | the condition is "in the routing surface OR in a skill" — **one twin per clause** (#26), or one side shadows the other |
| B | subcommand coverage | assert the reflector exposes exactly the argparse-derived set, computed from argparse, never against a literal like the `== 11` it replaces |
| B | R1 cold start | `scripts/verify-cold.sh`, which refuses to run until it has proven the three roots are `None` |
| B | R2 refusal contract | force a stale artifact; assert the MCP result is a refusal, not an empty pass |
| C1 | the ratchet | add 1 char -> gate fails; the gate must fail on a file it cannot measure, never pass |
| C3 | rule retention on any move | enumerate the rule-carrying tokens BEFORE the move and assert every one survives; a count, not a substring scan — prose satisfies substrings (#37) |

**Write the expected number before each measurement.** A prediction that cannot fail is decoration.

---

## 10. Sequencing

1. **A** — gate + the three routes. Independent, useful alone.
2. **C1** — the ratchet. Independent, small, and it protects everything after it.
3. ~~**B** — the MCP server.~~ **DEFERRED 2026-09-13** (see §7). Replaced by the generated
   `x4-cli-reference` skill; the routing table stays. Step 4 below therefore does not happen
   either: its premise was that the rows migrate into MCP tool descriptions.
4. **Migrate** the 9 routing rows; re-measure CLAUDE.md and record the actual reduction.
5. **C3** — first audit, once the migration has settled.

### Preconditions

- ⚠ **The dev tree is behind what shipped.** `<the dev repo's working branch>` is
  `version = "3.0.0"` / `## [Unreleased]`; the mirror shipped **v3.1.0 on 2026-09-09** (tag on
  origin, GH release published 05:57 UTC). **No dev branch carries 3.1.0.** Resolve or confirm-as-
  intended before B is scheduled into a release.
- Two peer sessions were live at time of writing and `KNOWLEDGEBASE.md` was being written
  concurrently (157 insertions, then 0, seconds apart). Isolate the tree; a clean tree is a moment,
  not a state (#8).

---

## 11. Risks

| risk | mitigation |
|---|---|
| C3 moves a mandatory rule out of context and a claim gets made without it | C3 reports, never cuts; each move needs an explicit user decision |
| MCP becomes a second place tool docs drift | schemas GENERATED; hand-written is forbidden by §7b |
| Shipping MCP primary raises the support surface | CLI stays fully supported; MCP failure must never block CLI use |
| The ratchet blocks a legitimately necessary addition | it names what must be displaced; it refuses silently-growing, not growing |
| Nexus 2186 falls further behind | out of scope here, but it is **four releases behind** (2.7.0 vs v3.1.0) and is the user's manual step |

---

## Appendix A — reproducing every number

- CLI count: `sed -n '/\[project.scripts\]/,/^\[/p' pyproject.toml | grep -c "="` -> 11
- Subcommands: `grep -h "add_parser(" x4validate/_*.py | wc -l` -> 40
- Routing coverage: per-CLI `grep -c` over CLAUDE.md and over `.claude/skills/`
- CLAUDE.md size and sections: read as UTF-8, `len(text)`; split on `^## ` / `^# `
- Routing rows: `awk '/^\| Question shape/,/^$/'`, classify each target cell
- Release state: `git ls-remote --tags origin`, `gh release view v3.1.0`
- Nexus: `GET https://api.nexusmods.com/v1/games/x4foundations/mods/2186.json`

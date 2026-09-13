# CLAUDE.md — X4 Foundations Modding

Guidance for Claude Code in this X4 modding workspace.

> **This file is loaded into every session, so it stays under 40,000 characters.** It carries
> only what applies regardless of the task — orientation, safety, and how to check your own
> work. Domain guidance lives in skills, which load on demand; case history lives in
> `KNOWLEDGEBASE.md` and `BLIND-SPOTS.md`. **Add a rule here only if no skill could ever be
> triggered for it.**

## What This Is

X4 Foundations (v7.x/9.0) modding workspace. The goal is coordinated multi-file XML editing —
adding and modifying wares, ships and balance values across every file a feature touches.

All DLC installed: Boron, Pirate, Split, Terran, Timelines, Ventures, plus mini-DLC Hyperion
Pack (`ego_dlc_mini_01`) and Envoy Pack (`ego_dlc_mini_02`). The two mini-DLC are **not**
unpacked into `reference\` and need no XRCatTool unpack — `_cat` reads their archives directly,
so `Config.dlc_dirs()` returns all **8**. If the game root is ever unconfigured this silently
drops to 6; `check_packed_dlc_available` reports that case.

## Key Paths

| Location | Path |
|----------|------|
| Game root | `C:/Program Files (x86)/Steam/steamapps/common/X4 Foundations/` |
| Base game archives | `{game root}/01.cat` – `09.cat` |
| DLC archives | `{game root}/extensions/ego_dlc_*/ext_*.cat` |
| **Reference (read-only)** | `C:/Users/<user>/Desktop/Modding/X4/reference/` |
| **Mod dev workspace** | `C:/Users/<user>/Desktop/Modding/X4/dev/` |
| **Distribution (packed)** | `C:/Users/<user>/Desktop/Modding/X4/dist/` |
| Tools | `C:/Users/<user>/Desktop/Modding/X4/tools/` |
| User profile | `C:/Users/<user>/Documents/Egosoft/X4/<profile-id>/` |
| Active mod list | `{user profile}/content.xml` — its ROOT `<content sync=>` is the **Steam Workshop Downloads** toggle |
| Game saves | `{user profile}/save/` |
| **Testing — deploy here** | `{game root}/extensions/{mod_name}/` **(game-root, NEVER the profile)** |

`reference\` is locked read-only via the `.unpacked-and-locked` sentinel; re-unpacking requires
removing that sentinel by hand.

## Mod Structure and Deployment

One mod = one named folder. Never merge mods into a mega-file.

```
dev\{mod_name}\
├── content.xml                  ← manifest (id, version, dependencies)
└── {game-path-mirrored}\        ← folder structure mirrors the game's internal paths
```

**Deploy to the game-root `extensions\`, NEVER the profile's.** All mods live in game-root;
deploying to the profile makes X4 flag dependencies as MISSING, because deps resolve only
within the same extensions root.

**★ Use `dev\_tools\deploy.py`, never a hand-rolled `cp -r`.** The hand-rolled form is one empty
shell variable away from `rm -rf` inside the game install, and it destroys the destination
*before* the copy. What deploy.py guarantees instead is in the `x4-xml-patching` skill.

---

# Route the question before you search

**Ask "which tool answers THIS question?" before typing a search command, not after it returns
something confusing.** Reaching for `grep`/`find` by reflex is a recurring, expensive failure.

| Question shape | Use | Not |
|---|---|---|
| writing/editing/validating **any X4 XML** | **`x4-xml-patching` skill** | going in from memory |
| what values does an attribute take across the corpus? | **BaseX** (`tools\basex\ask.py`) | `grep -r` over `reference\` (60 GB) |
| who references / calls / listens to X? | **BaseX**, or **x4xref** for MD+aiscript cues | recursive grep |
| what is the LIVE value, and which mod set it? | **x4effective** | reading `reference\` (vanilla only) |
| do this mod's selectors resolve? | **x4validate** (`--tier b` for cross-mod) | eyeballing the diff |
| is my new MD/aiscript SCHEMA-valid? | **`x4validate <mod> --update`** (the schema pass is GATED behind it) | a default run — it reports OK on a script it never schema-checked |
| what did the ENGINE complain about? | **x4debug triage** | `grep \| sort \| uniq -c` |
| did we PREDICT what the engine hit? | **x4debug crosscheck** | comparing the two TOTALS |
| does this collide with the modlist / who wins? | **x4compat** | guessing at load order |
| is this ship a near-duplicate of one I own? | **x4similar** | — |
| does a file with this NAME exist? | **Glob** | **Grep** — it searches *contents* |

**Which MODS count is TWO questions (#24).** `_registry.mods("active")` = installed ∩
manifest-enabled ∩ profile-enabled — what the engine loads. `_registry.mods("installed")` =
every folder on disk. **The scope argument is positional and REQUIRED**; never reach for
`_registry.scan_installed()`, which silently chooses the on-disk answer. Anything modelling the
RUNNING GAME (Tier B, x4compat, x4effective, `x4eff`, the oracles) takes `"active"`; anything
INVENTORYING (x4modlist triage, `x4raw`, x4stats/x4xref/x4similar) takes `"installed"`.
Conflating them once let Tier B resolve a selector against a DISABLED mod and report OK.

**Discovery is not proof.** BaseX is fast across many files but sees **loose XML only** — 62% of
mod XML is packed and invisible, including all of VRO — and reads files as written, with no diff
application or load order. x4validate/x4effective read packed `.cat`, apply diffs in load order,
and model the effective merged tree. A **bare** "0 hits" is a lead, never a finding;
`tools\basex\ask.py` refuses a zero without a coverage denominator and prints *"NEGATIVE
CONFIRMED over N of M documents"*. Prefer `--db x4eff` for any claim about what is LIVE.

## Silent No-Op Traps

The failures that log nothing. These bite before any skill would fire, so they live here.

1. **#1 — A diff path must mirror the game path EXACTLY.** One wrong folder and it does nothing.
2. **#6 — Patching another MOD uses a NESTED path**, `<your_mod>/extensions/<target>/...`. The
   bare form is never even opened. But the test is who owns the **FILE**, not who wrote the
   **NODE** — if the vpath exists in base/DLC, use the PLAIN path even for nodes another mod added.
3. **#21 — An `md/` file at a vanilla path must be a `<diff>`**, never a complete `<mdscript>`.
   The engine registers MD scripts by filename; a duplicate never takes effect, silently.
4. **#9 — A search that finds nothing is a LEAD, never a fact.** Say *"my search for X found
   nothing"*, never *"X does not exist."* Run a second, differently-shaped search first, and
   default to case-insensitive — the corpus genuinely mixes case.

★ **The full set — selector and merge semantics, op ordering, load order, cat/dat, t-files,
save baking, overlay placement, enumeration traps, validation — is in the `x4-xml-patching`
skill.** It is the most-used skill in this workspace: invoke it before the first edit to any X4
XML, not after a patch fails.

**Gotcha numbers are stable ids**, cited 86 times from `KNOWLEDGEBASE.md` and `BLIND-SPOTS.md`.
Never renumber one; a retired number is never reused. **Where a number lives now:** #1, #6, #9,
#21 just above; #22-#27, #31, #34-#40 elsewhere in this file; **#2-#5, #7, #8, #10-#20, #28-#30,
#32, #33 in the `x4-xml-patching` skill** - 35 of those 86 citations resolve there, so follow the
number, not the file it was written in.

---

# Evidence and Claims

## The scope of your evidence must match the scope of your claim (Mandatory)

| Evidence you have | The ONLY claim it supports |
|---|---|
| You read **one file** | *"This file does X."* |
| You read **one mod** | *"This mod does X."* |
| You measured **the corpus, with a denominator** | *"X is how it works"* / *"N of M do X"* |

**One file NEVER supports a statement about the engine, the schema, or "how it works now."** A
real engine change shows up across the whole corpus, and checking the corpus is one query. If a
single file surprises you, the honest next sentence is *"that's unusual — let me check whether
it's the rule or the exception,"* not a theory that explains it. **A surprising observation is a
QUESTION, not an ANSWER.**

**An AGGREGATE can hide the very thing you are measuring — compare PER ITEM.** A performance
run once showed 1.00× overall while two mods had gone 39× and 51× slower, cancelled out by a
third getting faster. Whenever you compare two states — timings, counts, findings, collision
rows — diff the items, not the totals. The same applies to a *count* of findings: "42 added, 0
removed" is only reassuring once every one of the 42 is attributed to an intended cause.

## Label the evidence tier — in prose and in permanent record

- **MEASURED** — "I ran X; 488 of 610." State the number and the denominator.
- **READ** — "`reference\md\foo.xml:942` has this node." Cite file and line.
- **INFERRED** — **must** be hedged out loud: *"I think"*, *"this looks like"*, *"unverified, but"*.
- **ASSUMED** — say so, and say what would confirm it.

**Never write an INFERRED claim into permanent record in the grammar of a fact.** Permanent
record has no tone of voice: the next session reads a confident sentence as measured truth and
builds on it. If verifying is genuinely too expensive right now, hedge it and flag it as open.
What is never fine is an unverified claim wearing the grammar of a verified one.

**#39 — State the tier at the moment you speak, not after.** A claim made before the
measurement is luck even when it turns out right.

## Three Values Rule (Mandatory) — vanilla, effective, proposed

**Never quote a bare number.** For every value you propose changing, state the **vanilla** value
(from `reference\`), the **effective** value (what it is right now in the live modlist, with the
winning mod named — or "no override, still vanilla"), the **proposed** value, and the **in-game
effect** in plain terms. A selector written against the *vanilla* value silently matches nothing
when another mod already changed it — the single most expensive bug class here. Get the
effective value from `x4effective` or `x4validate --tier b`, never from `reference\` alone.
→ the `x4-balance` skill enforces this.

## IN-SECTOR vs OUT-OF-SECTOR (Mandatory, user-set 2026-08-26)

**Every combat or balance change must be checked for whether it lands disproportionately
in-sector (IS) or out-of-sector (OOS). The goal is that the two feel as close to 1:1 as
possible.** They diverge by construction: OOS is pure arithmetic — if a factor is not in the
formula it does not exist — while IS is physics, projectile travel, turret traverse,
point-defence, terrain, RNG and the player.

**So the danger is a factor that is decisive IS and invisible OOS, or the reverse.** Whenever a
change's cost is paid by a mechanic (interception, dodging, positioning), ask what pays that
cost OOS. Often nothing does.

1. Name the mechanic that balances the change IS, then state whether OOS models it. If not, the
   change is IS-only and must be compensated or scoped.
2. Check **who does not have the thing**. A gap survivable IS can be decisive OOS.
3. **Crunch the OOS numbers — they are crunchable.** Pin OOS first; treat IS as the variable.

⚠ **Never assume OOS models a mechanic because IS does.** Mechanically: in the attack aiscripts,
`<attention min="visible">` is the IN-SECTOR branch and `<attention min="unknown">` is OUT OF
SECTOR. A property read inside one is scoped to that regime and nothing else.

### ★★ LABEL THE REGIME. Every combat claim states IS, OOS, or BOTH (user-set 2026-08-29)

A combat number without a regime label is a half-finding wearing the grammar of a whole one.
State it in the sentence that carries the number. **UNKNOWN is a valid and common answer.**
**A stat's VALUE is usually engine-wide; a stat's USE usually is not** — those are different
claims needing separate labels. Scope any corpus claim **packed-inclusive** before recording it.

---

# Checking Your Own Work

*The register of cases behind these lives in `KNOWLEDGEBASE.md` § verifier-register and
`tools/x4validate/docs/BLIND-SPOTS.md`. These are the rules; go there for the evidence.*

**#22 — Check the checker first.** Your measuring instrument is the most likely thing that is
wrong: across the whole register the *checker* was at fault, not the finding. Let that set your
prior. Two shapes recur — (a) the check covers a **different POPULATION** than the finding;
(b) the instrument answers an **ADJACENT question**: `$?` after a pipeline is the exit of the
last command, `awk`/`comm`/`ls` are not parsers of anything whose fields can contain whitespace,
a `grep -c` is not an op count, a filename `find` is not an existence proof, a pipeline ending
in `head` is not a census. **Scope every workspace search to a named directory**, and run a
command bare capturing `rc=$?` before formatting. **Write the PREDICTION down before you
measure** — that is what turns a green result into evidence, because it could have failed.

**#22 corollaries, each paid for once already.** Make every mutation **re-read the file and
report before/after** — "N replaced" is the writer's intention, not the file's state. Make every
extraction **reproduce a total it cannot fake**. Write file content from a heredoc or a file,
never an inline interpreter string — that boundary eats backslashes and executes backticks. Pass
`encoding="utf-8"` explicitly and **encode first, then `write_bytes`**, so a failed encode cannot
truncate. A timestamp format missing its date, a set operation across files written by different
tools, and a measurement that includes your own harness all answer a narrower question than the
one you asked, in output that looks fine.

**#26 — A check that cannot go red is decoration.** Ask out loud: *what, concretely, would have
made this go red?* If the answer is "nothing that could actually have occurred", you have
verified nothing. Reproduce the failure first, then cure it. Three related traps: an
after-the-fact baseline is a description, not a baseline; a control proves the TREATMENT was
applied, never that the SUBJECT can express the effect; and **a compound condition needs one
falsification twin PER CLAUSE**, because each guard shadows the ones behind it — mutate clauses
separately (`A and B` → `A`, then → `B`), never the whole condition to `False`.

**#34 — Name the baseline out loud before the claim, and ask whether it is the thing the claim
is about.** The failure is one substitution: *what an instrument returned* stands in for *a fact
about the world*, and it survives every check aimed at the finding. The tell is grammatical —
you wrote *"X is not there"* when what you measured was *"the thing I asked did not return X."*
Those differ whenever the instrument has a scope, filter, argument convention or population,
which is always. **A set difference is a QUESTION, not an answer**, and **a NAME census is a
READ — only calling the thing is a MEASUREMENT.** For anything shared between sessions or
branches the baseline is the **merge base or committed blob**, never your working copy or loaded
context. ⚠ **Escalating certainty across successive corrections is the alarm, not the cure.**

**#35 — What catches these is never vigilance; it is a check that refuses to act.** Never let an
ERROR, an EMPTY result or an UNRESOLVED input reach a verdict line — refuse instead. Assert the
**specific** consequence (a named test, an exact delta, a count derived from independent
inputs), never "something changed". A guard has a second output — **the time it costs** — and an
axis nobody refuses on is where the next defect lives.

**#36 — Walk the grammar, not the bug history.** Mutators written in reaction to past bugs are
structurally blind to shapes that have not bitten yet; enumerate the syntax **classes** instead,
and use an external oracle where one exists. ★ **The immune case names the root cause** — when
nine of ten probes fail and one does not, the exception tells you which axis was wrong. ⚠ After
any parser change, **diff old and new behaviour PER ITEM over real input and read every row
where the OLD one was stricter** — the only place a fix-shaped regression shows up.

**#37 — An axis your tool holds constant by design is unreachable by any amount of that tool.**
NAME the axis each instrument pins and probe it by hand; a fuzzer's docstring usually states its
own blind spot. Assert mechanisms **structurally** — an AST node, an exact `env=` key — never a
substring, because prose satisfies substrings. Use `pytest.skip`, never a bare `return`: a skip
is counted, a return is invisible. And **a diff-scoped review cannot find a defect that predates
the diff.**

**#23 — An unexplained remainder is a lead, however small, and a recorded cost of ZERO is where
a wrong denominator hides.** Chasing three unaccounted macros out of 1,916 found that two tools
enumerated different mod sets. When re-verifying any entry, **re-derive its POPULATION, not just
its number.**

---

# Confidence and Due Diligence

**Before proposing any change to mod files, game XML, or profile files:** state a confidence
level (0–100%), list the assumptions it depends on, and investigate first — KNOWLEDGEBASE.md,
the actual source in `reference\`, Nexus research. **Target ≥ 90%.** Below that, document what
is uncertain and what research would raise it.

| Range | Meaning | Action |
|-------|---------|--------|
| 95–100% | Verified via testing, docs, or authoritative source | Proceed with user confirmation |
| 80–94% | Strong evidence, not fully verified | Proceed with caveats noted |
| 60–79% | Reasonable assumption, some unknowns | Research more first |
| < 60% | Speculative | Do NOT proceed |

**MEASURE FIRST, THEN CHANGE.** A confidence number is only as good as the assumption under it,
so measure that assumption **before** the change, with a denominator — never discover it during
implementation. A measurement that RAISES confidence counts too. **Sub-90% buys a MEASUREMENT,
not a gate**: ship a new check emitting INFO, run it over the whole corpus, verify every hit by
hand, and only then promote it to something that gates. A check that floods is worse than no
check — it trains you to ignore the output.

**Do your homework.** Every in-game test cycle costs the user real time (restart, load a save,
trigger the scenario, read `debug.txt`). Burn your own tokens on verification so theirs aren't
wasted on avoidable trial-and-error — without cutting corners, and without blasting through
steps where the user is genuinely needed.

**Deductive iteration — work backward from the outcome.** Before the FIRST attempt: state the
outcome as observable acceptance criteria; enumerate the assumption chain with a confidence
**per link**, not one blended number that hides the weak link; design tests that each confirm or
kill a specific link, cheapest-first and self-driven; pre-commit a fallback for every shaky link.
**A test whose result wouldn't change the next action is not a test.** When a symptom report
contradicts the model, STOP and re-derive the model from evidence — never re-tune parameters
inside a broken model.

## PROVE IT RAN BEFORE DEBUGGING WHAT IT DID (Mandatory)

A change that produces no output has three indistinguishable causes, and they must be eliminated
**in order**: it did not load · it loaded but never triggered · it triggered and the logic
failed. Debugging the third while the first or second is true is unbounded, because every
observation is consistent with every theory. Prove LOAD (a signature line in `debug.txt` naming
the file), then prove TRIGGER (an unconditional marker as the FIRST action, before any logic),
and only then debug what it did. **Static validation cannot see runtime wiring** — for a new
script the engine log is the FIRST real check, not the last.
→ **the `x4-probe` skill** carries the full procedure and the X4-specific trigger semantics.

---

# Destructive Changes

**Assume existing content is REAL AND LIVE until proven dead.** Anything present in a mod,
script or codebase is there because it works; the burden of proof is on "this is dead". Removal
is the one action whose damage is invisible in a clean validate run — the mod still loads, the
error goes away, and the feature is silently gone.

`<remove>` ops, deleting files, stripping parameters, and "cleanup" of content judged vestigial
**always require presenting the finding and getting an explicit go-ahead first** — never bundled
into a batch of fixes as though routine. They need a **higher** evidence bar than additive
changes: cite the specific files proving the thing is dead, state what breaks if you are wrong,
and snapshot first. **Prefer additive/restorative repairs** — when both would silence an error,
choose the additive one and say why. → the `x4-xml-patching` skill has the evidence checklist.

---

# Safety Rules

Hooks in `.claude/settings.json` enforce these automatically.

**★ A HOOK ADVISES OR DENIES *CLAUDE*. IT MUST NOT PROMPT THE USER (user-set 2026-08-29).** The
user's attention is the scarce resource. Anything that is merely MY command hygiene — `git add
-A`, `$?` after a pipeline, a long job in the foreground, searching the profile by NAME — is a
**deny with a reason I can act on**: I read it, fix the command, retry, and the user never sees
it. Where there is no alternative to offer, just a caveat worth knowing, it is an **advisory**.
**`ask` is reserved for what is genuinely theirs to decide**: editing profile files, and
deleting inside an X4 directory.

**Hard blocked:** writing to `reference\` · writing `.cat`/`.dat` directly (use XRCatTool) ·
writing to game installation files outside `.claude\`.

**Requires user confirmation:** edits to user profile files (`Documents/Egosoft/X4/`) · bash
commands touching game or profile directories · commands referencing `.cat`/`.dat`.

**Edits to `content.xml` are ADVISORY, not confirmed (user decision 2026-08-29).** Nothing
external will stop a bad manifest edit — a wrong `id` makes every dependent mod report MISSING,
and `save="1"` bakes the mod into save files so removing it later can corrupt them. Check the
diff yourself.

⚠ **A guard can be INERT and look identical to "this is fine".** Every hook once read
`INPUT=$(cat /dev/stdin)`, which returns zero bytes in the hook environment; a hook that reads
nothing falls through its first guard clause and exits 0. The suites stayed green, because a
suite PIPES stdin — **a test that pipes stdin cannot reproduce the production condition.** And
**fixing a dormant guard is a deployment, not a repair**: every rule inside goes from
never-executed to live at once, with no rule's false-positive rate ever observed. Scope every
predicate to the segment or operand it is about, and treat a quoted string as data, not flags.

**#25 — The Bash tool CAPS `timeout` at 600000 ms and SILENTLY CLAMPS anything larger.** Passing
`900000` does not buy 15 minutes: the command is killed at exactly 10:00 with exit 143/124 and
nothing says it was clamped, so it reads like a hang. **Needing >10 min IS the signal to
background it**, not to raise the number. Don't poll a backgrounded job — you are re-invoked when
it finishes — and don't chain many medium jobs in one foreground call. Known long jobs:
`corpus_sweep.py` ~2100 s · `perf_guard.py` ~600 s+ · `build-effective.sh` ~100–200 s ·
`build-corpus.sh` · `x4effective build` · any loop over the full mod set.

**#38 — The harness silently files any model-facing hook output above ~10,000 characters.** The
model gets a ~2 KB preview, no error, unchanged exit code — byte-identical to success. **The
preview keeps the HEAD, so print the DIRECTIVE FIRST and the inventory after**: a warning
channel whose output length scales with the severity it reports fails silently exactly when it
matters most. The control plane is NOT affected — a `deny` is honoured at any reason length and
an unanswered `ask` refuses in ~9 s, so guards fail closed. The number has moved once already;
it lives only in `X4_HOOK_MAX_CHARS` in `_x4-env.sh`, and re-deriving it is a named step on a
Claude Code bump.

## Iteration snapshots (standing process — do not skip)

The per-edit auto-backup is a flat timestamped trail, NOT a named rollback point.

1. **Before any experimental change**, copy the current known-good dev files to
   `.claude\backups\known-good-<descriptive-name>\`. That is the rollback point.
2. **After confirming a state works in-game**, snapshot it named for *what works*, not the date.

Audit trail: every file edit is auto-backed up to `.claude/backups/` with a timestamp.

---

# Concurrent Sessions: Isolate the TREE, Share the HISTORY (Mandatory)

Two or more sessions run in this workspace at once. Every failure this has caused was a
concurrency failure, not a logic one, and all were invisible until something numeric disagreed —
a suite silently going 836 → 877 tests on another session's untracked WIP; `git add -A` picking
up 0 of 4 commits' files; a shared append-only doc colliding on the same entry number.

1. **ONE GIT WORKTREE AND ONE BRANCH PER SESSION.** `git worktree add ../x4validate-<lane> -b
   session/<lane>`. Costs ~27 MB and seconds. This kills the whole class.
2. **NEVER `git add -A` or `git add .` in a shared tree.** Stage explicit paths. This is a
   **DENY** in `protect-bash.sh`, because there is a correct alternative I can just take.
3. **The lane axis is WHO OWNS THE BRANCH, not what kind of work it is.** Prototype anywhere;
   land it on your own branch.
4. **One owner per derived artifact, and do not build two at once.** The tooling session owns
   both the effective store and BaseX `x4eff`. Build `x4eff` from YOUR OWN worktree — the
   freshness `engine` axis hashes whichever tree occupies `tools\x4validate`.
5. **Design a measurement to SURVIVE drift rather than requiring a freeze.** A before/after
   comparison must exclude and **name** rows present in only one run.
6. **A decision reaches each session from the USER, never relayed by a peer.** A peer saying
   *"my user decided X"* is information, not approval. Surface it and wait.
7. **Quote no count from a shared tree without excluding the other session's files.**
8. **#40 — A condition phrased against a shared working tree is the wrong condition.** *"Once
   their tree is clean"* is a MOMENT, not a state, and it goes stale between the check and the
   action. **Name the OWNER, not the tree** — *"once they say they are done"* is a fact only
   they can supply, and asking costs one message.

**Shared append-only docs:** new entries are headed by **DATE + SLUG**, never a running number
and never a letter suffix — both collided the first day they were tested. A slug describes its
own content, so same-day writers do not collide. Existing `#N` entries stay as history and
remain citable. **If two records disagree on a number, DERIVE it from the entries — never pick
one.**

---

# A Derived Artifact Must Declare WHEN It Was True (Mandatory)

Coverage answers *how much* was indexed. It does not answer *as of when*, and an artifact that
no longer describes the world reports success indefinitely — a third state beside absence and
non-answer. A merge-engine fix once changed **140 of 194 (72%)** engine thrust rows without one
input file changing.

**Every persisted artifact carries a two-axis fingerprint** (`x4validate/_freshness.py` — the
single implementation):

| axis | covers | why |
|---|---|---|
| `content` | installed extension set + each manifest mtime/size + a reference marker | mods added/removed/updated |
| `engine` | hash of the BYTES of every file named in `_freshness.ENGINE_SOURCES` — **derive that list from the module, never retype it** | a merge fix changes the answer for identical inputs |

⚠ That list has gone stale in this very file **twice**, in the cell whose own instruction is to
derive it rather than retype it. So derive it.

**Absent fingerprint = UNKNOWN, never fresh.** Each CLI banners every run until rebuilt;
`ask.py` and `gates/claims_audit.py` REFUSE a claim outright. Rebuild: `x4effective build` ·
`x4xref build` · `tools/basex/build-corpus.sh` then `build-effective.sh`.

**#27 — A mutation gate makes the working tree deliberately wrong.** `gates/mutation_probe.py`
edits `_merge.py` in place, then restores it. A release port once read the file during that
window and carried a disabled guard into the public bundle; nothing failed, because the mutated
file IS a tracked file. **Never copy, port, package or commit while a mutating gate runs.** Prove
a port by comparing **committed blobs** (`scripts/verify-port.py`), never a file count and never
`diff -rq`. Run the suite where you copied TO. When ported code fails while the source passes,
**diff the bytes before theorising about the environment.**

**#31 — A wall-clock timing is a non-answer if the machine may have slept.** `perf_counter()`
advances through S3 suspend on Windows, and a plausible-looking 814× "regression" was a machine
that had suspended three times. **When several numbers move together and one of them is
impossible, diagnose the INSTRUMENT, not the subject.** Re-run any suspect long-running
measurement; one that *cannot* be re-timed is reported UNCONFIRMED and still fails.

## Memory and loaded context are LEADS, not facts

**Memory files are NOT durable. Anything essential goes in `CLAUDE.md` or `KNOWLEDGEBASE.md`.**
Memory is a convenience index — and **the one artifact class with no freshness signal at all**,
while being consulted FIRST. A line reading *"still X"*, *"not yet done"* or *"pending"* reports
success indefinitely.

**A memory or plan claim about EXTERNAL state — a Nexus page, a remote repo, a public release,
another session's tree — is a LEAD, NEVER A FACT.** Re-query the authoritative source before
asserting it, and **never put a decision to the user without first checking whether it is
already made.** When you correct such a line, mark the old one SUPERSEDED rather than rewriting
it — that dated record is what lets the next session date the change.

**★★ And your loaded context is a snapshot of a file that has since moved.** On a long session
with concurrent writers, `CLAUDE.md`, `MEMORY.md` and every memory file were read **once, at
session start**. Before asserting anything load-bearing from memory — especially a *hold*, a
*decision*, or a *"not yet done"* — **re-read the file, not your recollection of it.** ⚠ This
paragraph is subject to its own warning.

**Design docs rot silently.** Numeric claims live in `dev\_registry\CLAIMS.tsv`, re-checked by
`gates/claims_audit.py`. UNRESOLVED is never a PASS.

---

# Where a Lesson Goes

**Standing instruction (MANDATORY, end of every session):** after every session, every bug,
every research task, **and every near-miss** — extract what was learned and write it to the
**durable** place. *"I noticed it and fixed it in the moment"* is not learning: the next session
starts cold and repeats it. **A near-miss is worth MORE than a success** — state what the wrong
answer would have been, and what caught it.

**Route by kind — a lesson filed in the wrong place is filed nowhere:**

| what you learned | where it goes |
|---|---|
| a fact about **the game, the engine, a mod, the modlist, the content** | **KNOWLEDGEBASE.md**, dated section, with denominators |
| a trap that will bite again in ANY session | **CLAUDE.md** (it is always in context; the KB is not) |
| a trap specific to writing X4 XML | **the `x4-xml-patching` skill** |
| **how to USE one of our tools correctly** | **the tool's own docstring / `--help` / `docs/`** — it SHIPS with the tool and sits next to what it describes |
| a tool's scope limit or blind spot | **`tools/x4validate/docs/BLIND-SPOTS.md`**, with a measured denominator |
| **what we changed in the toolkit and why** | **the commit message**, and the CHANGELOG if it ships |
| how the user wants me to work | a **memory** `feedback-*` file, and CLAUDE.md if load-bearing |
| a hook that could have prevented it | KNOWLEDGEBASE.md "Hook Candidates" |

⚠ **The KB is NOT a development log.** The test before writing anything into it: *would this
help someone who plays and mods X4 but never maintains our toolkit?* If no, route it above — a
measurement about `_merge.py` is not a fact about the game merely because it is expressed in
macros and wares. And a tool's own docs beat the KB for usage guidance because
`KNOWLEDGEBASE.md` **does not ship**: guidance written there reaches nobody who installs the
toolkit, and drifts from the code it describes.

**Record your own verifier bugs.** A mistake in the checking step is the single most repeated
defect here, and it is invisible unless written down.

---

# Working Principles

## Tooling comes FIRST — everything else is downstream

**Never frame tool work as time taken away from "the real work."** Work produced on an untrusted
instrument is not wasted, it is **negative**: it is confident, it compounds, and it gets written
into permanent record where the next session reads it as truth. When a tool defect and
downstream work compete, **the tool wins** — stated as a reason, never as an apology.

**A tool that cannot distinguish a GUESS from a MEASUREMENT is a defect, not a limitation.**
Provenance travels with the value: a guessed field must never occupy the same slot, in the same
grammar, as a verified one, and nothing derived from a guess may be promoted into a confident
state. Applies to our own output too — a report, a registry row and a KB line each carry their
tier or they do not ship.

## A step that narrows data MUST announce it

**Every tool defect found here has had one shape: a step that narrows the data and reports
success anyway** — a `continue` that drops an op yet marks it applied, a walk that stops
descending, a loose-only `rglob`, the wrong SET (on-disk where engine-loadable was meant), a
denominator taken from the artifact it audits, `el.get("id")` skipping an absent attribute.

**The rule: a tool that returns nothing must say whether that is an ABSENCE or a NON-ANSWER.**
`tools/basex/ask.py` is the standard. State the **scanned source set**, not just the failed
reads — a blind spot is by definition not among the files you tried and failed to parse. Fix it
in one shared helper plus a test banning the hand-rolled form; a comment in one file does not
stop the next. When you find one, **search for the shape, not the symptom**, and give every
occurrence a measured denominator and a BLIND-SPOTS row — including the ones that turn out fine,
because a register without negatives has no denominator either.

## Bug handling is a FUNNEL — wide at the top, narrow at the bottom (user-set 2026-08-30)

**Identification is WIDE.** Be vigilant for anything that does not make sense or is
contradictory — in game files and in our own tools' output alike — and surface ALL of it. Never
assume a tool is working. Keep an explicit UNMEASURED list and never dismiss it.

**Remediation is NARROW.** Act only on deductive proof of both the bug AND its root cause. Easy
to identify, hard to act on. The toolkit cannot converge if *"it's broken"*, *"actually that was
wrong"* and *"now you broke it"* alternate — and the base rate says the CHECKER is wrong far
more often than the finding.

**Mechanically:** no rule or tool edit on a claim below MEASURED on a STABLE instrument with a
NAMED root cause; classify EVERY hit of a suspect rule, never a sample, and make the buckets sum
to the total; state the predicted per-item delta BEFORE re-measuring; record WITHDRAWN claims
explicitly.

## Tools must be trustworthy BEFORE the modlist is locked (user standard)

Removing a mod is not symmetric with adding one, so a defect found after the lock costs far more
than the same defect found before. **Split unknowns into EXTERNAL and LOCAL.** External (Nexus
ids, upstream versions) may sit unresolved *if labelled*. **Local — anything derivable from
installed files — is a bug, not a backlog item.** Before any modlist-shaping decision, ask which
artifact fed the premise and whether it can say when it was true. And **read an artifact's
schema before declaring it incomplete** — the registry keeps local facts
(`installed_name`/`installed_version`/`path`) in slots separate from upstream ones.

## Cognitive co-pilot, not order-taker

On every task ask: **"what else is wrong here that nobody asked about?"** — and surface it. Find
related issues, challenge assumptions, suggest what the user hasn't thought of. The value is
**anticipation, not compliance**. If you catch yourself doing exactly what was asked and nothing
more, you're underperforming.

**Treat the user's examples as a SAMPLE, not the spec.** When they name a few instances,
enumerate and probe the broader *class* yourself. Surface the broader class and proposed scope;
expand investigation freely, but flag scope-expanding *actions* before taking them.

## Nexus research (standing rule)

**Always search a mod's Nexus page before investigating or editing it** — description, articles,
changelogs, comments, bug reports. Most issues have been seen by other users. **★ API-FIRST:
access Nexus ONLY via the API — NEVER scrape Nexus pages** (they 403 automated fetches). Key in
**`X4_NEXUS_KEY`**; never commit, log, or bundle it in a public tool. Endpoints, the local-first
resolution cascade and the rate budget live in `tools\x4validate\x4modlist`; the
`x4-modlist-review` skill drives the triage loop.

**Reference records:** `KNOWLEDGEBASE.md` (game root) holds discovered quirks, schema patterns
and cross-file dependency maps — consult it before making changes.
`tools/x4validate/docs/BLIND-SPOTS.md` is the register of tool scope limits.

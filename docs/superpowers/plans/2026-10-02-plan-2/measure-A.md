# Lane A measurements (Task 1 + Task 2), run 2026-10-02

Scratch: `...\scratchpad\plan2\measureA\` (laneA\ = Task 1 calculator and drafts; m\ = Codex/Claude probes; m\logs\ = every raw log).
Nothing was written to the toolkit repo or the game root. Versions: **Codex CLI 0.160.0** (NOT 0.159.2 as the plan says; model gpt-6.1-sol, PowerShell 7 shell), **Claude Code 2.1.287** (model haiku).
Every Codex/Claude outcome below is read from DISK (does the flag file exist), not from the model's report.

## Task 1: the split sizes (MEASURED, python, LF-normalised working copy of agent/instructions/core.md)

Baseline re-derived: core.md = **40,288 B / 39,939 ch** (LF), matches the plan. Note: the working-copy core.md is CRLF (568 CRLF) and shows as modified in `git status`; HEAD's blob is LF, 40,301 B. The plan's numbers are for the LF-normalised working copy.

Prediction (written before running, from the plan): option A moved = 11,737 B, AGENTS.md headroom +1,000..+1,600; option B headroom +2,900..+3,500; CLAUDE.md headroom > +9,000 in both.

Command: `python laneA/split_sizes.py <core.md> claude-addendum.md codex-addendum.md stub.md [--rows]` (drafts: claude addendum 500 B, codex addendum = the plan's draft verbatim 1,304 B, stub 828 B).

| | moved | core' | CLAUDE.md | AGENTS.md | AGENTS headroom |
|---|---|---|---|---|---|
| A (5 sections) | 11,737 B (matches) | 29,379 B | 29,634 ch (+10,366) | 30,715 B | **+2,053** |
| B (+6 rows)    | 13,655 B (1,918 B of rows) | 27,461 B | 27,739 ch (+12,261) | 28,797 B | **+3,971** |

Results vs prediction: moved matches exactly; CLAUDE.md headroom inside prediction; **AGENTS headroom is ABOVE the predicted band for both (A +2,053 vs +1,000..1,600)** because the drafted codex addendum is only 1,304 B, not the ~2.4 KB the plan budgets.
Controls: (1) a typo'd heading prefix -> `REFUSING ... matched 0 headings`, rc 1 (the manifest refuses). (2) Conservation check printed per run: kept + dropped lines = 569 = total lines, and `core - rest` bytes equals the moved bytes exactly.
**Verifier near-miss (record it):** the plan's calculator as written removed blocks with `str.replace`, which silently FAILED for the last section (the file-end span gets an extra "\n"), reporting AGENTS.md headroom -1,594 (A) / +324 (B) with no error. Caught only because the number contradicted the plan's projection; fixed by removing by line index plus the conservation check above. The script in the plan text must not be copied verbatim.

**Decision rule (plan Step 4: proceed with the option whose headroom >= 2,048 B):**
- A passes by **5 bytes** with the drafts as written, and that is before lanes C and D add their ~400 B and before the real Codex addendum grows toward the ~2.4 KB budget. At a 2.4 KB addendum A is about +960, which FAILS the rule. Lane C/D lines (+400 B) take A to about +1,650, also a fail.
- B passes with margin: +3,971 as drafted, about +2,870 with a 2.4 KB addendum, about +2,470 after C/D's 400 B.
- **Changes the plan?** Yes, in the sense of settling it: use **option B** (move the 6 routing rows). DECISIONS.md #1 already says yes to that, so no user question remains. The earlier "+1.3 KB / needs B" projection is confirmed in direction; the numbers are better than projected by about 0.7 KB because the addendum drafts are small, but A is not safe.

## Task 2: what Codex 0.160.0 and Claude Code 2.1.287 load

Harness hazards found and fixed along the way (all #22 shapes): codex waits on an inherited stdin ("Reading additional input from stdin", hung until stopped) so every run uses `</dev/null`; a non-git dir needs `--skip-git-repo-check`.

### M-A1 skills discovery: PASS on 0.160.0
Prediction: `.agents/skills/<name>/SKILL.md` is discovered, an unknown frontmatter key (`allowed-tools`) is ignored, a file under the skill's own `reference/` is readable; with the skill absent neither file appears.
- Treatment (skill `probe-cyan`, trigger phrase "CYANPROBE procedure", `allowed-tools: Read`): `SKILL-FIRED.txt` (4242) and `zebrafish.txt` both created. A first treatment run with the MAGENTA-PROBE skill gave the same, log shows the model reading `.agents/skills/probe-magenta/SKILL.md` then `reference/extra.md`. **MEASURED, 2 of 2 treatments.**
- Variant: launched from `sub/` of the git repo: found, read via the absolute path of the git-root `.agents/skills/...`, files created in `sub/`. **1 of 1.**
- Control: **my first two controls were INVALID** (skill moved to a sibling dir, then logs left in a parent dir; the model searches upward with `rg` and found the procedure text, so files were still created). Valid control: skill dir removed and nothing containing the new token anywhere in the ancestor chain, trigger phrase "CYANPROBE": **no file created** (0 of 1). Only one valid control; treat the negative as 1 of 1.
- Unknown frontmatter key `allowed-tools` did not prevent discovery (2 of 2).
- Skill-description length limit: none printed in any of the 6 skill logs (grep for limit/truncat found nothing). NOT MEASURED beyond that: I did not test a long description.
- Not measured: whether the model picked the skill from the available-skills list vs by searching (the log says "I'll use the probe-magenta skill", which reads as a list match, INFERRED).
- Plan impact: none. Task 7's discovery assumption holds on 0.160.0 (and 0.154 earlier). Record the version as 0.160.0.

### M-A2 AGENTS.md boundary, chain, non-git (Codex 0.160.0)
Prediction: 32,768-B file keeps its last line, 32,769 B loses it; the cap is shared across a root+sub chain; non-git loads with the skip flag.
- **My first boundary test was mis-specified:** at 32,769 B only the final "\n" is dropped, the instruction text stays, so TAIL-SEEN.txt was created in both 32,768 and 32,769 (4 of 4, with the model confirmed not to read any file: its only tool calls were file creation). That result says nothing about the boundary.
- Position-marker test (49,152-B file, a `MARK-<offset>` line every 128 B, task = create `LARGEST-<n>.txt`): **LARGEST-032640 in 2 of 2** (the last marker line fully inside 32,768). No marker from offset 32,768 on was visible.
- Byte-exact test: 32,768 B of content then a further instruction at bytes 32,768+: `HEAD.txt` created, `PAST-CAP.txt` NOT created (2 of 2). Together with the 32,768-B file keeping its last line (b32768, 2 of 2): **the cut is exactly at 32,768 bytes**. ASCII only, so bytes vs characters is not distinguished (the plan's byte rule stands as documented).
- **Chain budget IS SHARED:** `root/AGENTS.md` 20,000 B (instruction at its head) + `sub/AGENTS.md` 20,000 B (instructions at head and at the very end), launched in `sub/`: `ROOTHEAD.txt` and `SUBHEAD.txt` created, `SUBTAIL.txt` NOT created (2 of 2). Both files were loaded and the combined text was cut at 32,768 B.
- **Non-git:** without `--skip-git-repo-check`, `codex exec` refuses ("Not inside a trusted directory", rc 1) before reading AGENTS.md. With the flag, a 1,500-B AGENTS.md loads, both head and tail instructions executed (1 of 1). Interactive behaviour is not measured.
- Consequence rules (pre-committed in the plan): boundary is 32,768, so `AGENTS_MD_MAX_BYTES` stays 32,768 (no change). **Shared chain budget -> the plan's rule fires:** add a test that the repo ships no second `AGENTS.md`, and an install note for lane C. Extra: any nested AGENTS.md anywhere in an installed project (a user's own, or the user's `~/.codex/AGENTS.md` if Codex loads a global one, NOT measured) eats into the same 32,768 B. That makes the planned ~2 KB headroom a shared resource, another reason for option B.

### M-A3 Claude Code and AGENTS.md: PREDICTION FALSIFIED (plan-changing)
Prediction: a dir holding ONLY `AGENTS.md` -> Claude Code does not act on it.
- AGENTS.md only (instruction: create `CLAUDE-READ-AGENTS.txt`): **file created, with Claude Code 2.1.287**, in 5 of 5 runs across 3 configurations (plain `-p`; stream-json with tool calls listed; and again with all hooks disabled via `--settings {"disableAllHooks":true}`). The tool log shows only a `Write` call, no Read/Glob/Bash, and the model never mentioned AGENTS.md when hooks were off, so Claude Code itself injected the file's content.
- Not the superpowers SessionStart hook: with `disableAllHooks` (0 hook_started events) the result is unchanged.
- Controls: same text in `CLAUDE.md` -> created (positive control, 2 of 2); an empty dir -> nothing created (0 of 1, so the model does not make the file up).
- **Both files present** (CLAUDE.md says create FROM-CLAUDE-MD.txt, AGENTS.md says create FROM-AGENTS-MD.txt, hooks disabled): only `FROM-CLAUDE-MD.txt` created, 2 of 2. So Claude Code uses AGENTS.md **as a fallback when no CLAUDE.md exists** and ignores it when CLAUDE.md is present.
- Plan impact: the plan's assumption "Claude Code does not auto-load AGENTS.md" is WRONG and its pre-committed branch literally says STOP and report. The branch's *reason* (a Claude session would get the core twice) is NOT triggered in the repo layout, because CLAUDE.md wins (2 of 2). So: not a blocker for the generated tree, but (a) correct the sentence in the plan table and in the spec; (b) any layout that ships AGENTS.md without CLAUDE.md (e.g. an installer `--agent codex` on a machine also used with Claude Code) gives Claude Code the Codex addendum, including the "guards do not protect you" text, which is false there only if hooks are not wired; (c) a test that every install that ships AGENTS.md also ships CLAUDE.md, or an accepted note; (d) the Codex addendum should not claim "Claude Code never reads this". Needs a user/orchestrator decision whether (b) is acceptable. Only one Claude version (2.1.287) and one model (haiku) tested; whether `@AGENTS.md` imports or a symlink behave differently is not tested.

## Items that need the user
None blocked. Everything ran with the user's existing Codex (ChatGPT login) and Claude credentials, no approvals written. The one open decision is the M-A3 consequence (b/c) above.

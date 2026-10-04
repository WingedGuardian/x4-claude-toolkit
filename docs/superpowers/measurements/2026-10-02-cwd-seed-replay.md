# Lane F measurement: relative paths resolved against the payload `cwd` (2026-10-02)

Required before any verdict change ships (CLAUDE.md #36). The historical replay compares OLD and
NEW per item, classifies every changed verdict, and the buckets sum to the total.

## Instruments (not in the repo)

The scripts below lived in the maintainer's session scratchpad and read the maintainer's own
Claude Code transcripts, so this replay cannot be re-run from a clone. This file is the record
of its method, controls and counts (committed 2026-10-04 for release review R6-13; the text
below is the 2026-10-02 original, unchanged apart from this paragraph).


| step | script | what it does |
|---|---|---|
| corpus | `extract.py` | Every Bash/PowerShell `tool_use` in `~/.claude/projects/**/*.jsonl`, carrying the transcript line's own `cwd`, deduped on (tool, command, cwd). |
| stage 1 | `replay_facts.py` | `hook_facts.facts()` OLD (master `552208b` source) vs NEW (lane F source), in-process. The payload carries `cwd` at the top level. Roots are the live machine's (game root, `Desktop/Modding/X4/reference`, profile, saves, Documents, `dev`, the toolkit main checkout). Both modules share one PowerShell translation cache; `ps_translate.ps1` is byte-identical in both trees, and the script refuses to run otherwise. |
| stage 2 | `replay_hooks.py` | The REAL `protect-bash.sh`, OLD tree (main checkout `.claude/hooks`) vs NEW tree (worktree `.claude/hooks`), with identical env and roots. It runs on every stage-1 changed row plus a 400-row random control sample (seed 20261002) of unchanged rows. Inspect only. |

**Why stage 1 is sufficient for unchanged rows.** `protect-bash.sh` is unchanged in lane F. Its
verdict depends only on the fact stream, the command text and the env, so identical facts give an
identical verdict. Stage 2's 400-row sample checks that argument against the real hooks: **0 of
400 changed** (373 allow, 25 deny, 2 advise on both sides).

**Controls (stage 2 refuses to report unless all three hold):**
- absolute `rm -f <ref>/libraries/__p.xml`: deny / deny
- `ls`: allow / allow
- relative `rm -f reference/libraries/__p.xml` with cwd = `Desktop/Modding/X4`: **allow / deny**. This is the defect, reproduced and fixed.

Stage 1 controls (`controls.jsonl`): the same relative delete and write, plus a PowerShell
`Remove-Item`, changed facts. `ls` did not.

## Denominator

819 transcript files (172 top-level sessions + 647 subagent transcripts). That is 55,948 shell
tool_uses (54,348 Bash + 1,600 PowerShell); deduped, **53,828 unique (52,276 Bash + 1,552
PowerShell)**. All 53,828 carry a `cwd`. Errors on either side: **0**.

## Result: the shipped code (lane F HEAD, `5506cfb` + docstring)

Prediction written before the run: "fewer than the prototype's 113 rows; no deny and no ask
change; only advisories".

| | rows |
|---|---|
| replayed | 53,828 |
| facts identical | 53,825 |
| facts changed | **3** |

Every changed row, through the real hooks:

| corpus row | OLD | NEW | bucket | what it is |
|---|---|---|---|---|
| 28335 | allow | advise | **neutral (allow->advise), false advisory** | a `join -o 0,1.2,2.2 ...` / `mv in <shas>` comparison one-liner. The segmenter mis-splits the text, so clean-looking words are read as `mv` operands under the game-root cwd. |
| 49428 | allow | advise | **neutral (allow->advise), false advisory** | a hook-probe harness whose quoted probe strings are mis-segmented. Its `rm` "operands" resolve under the game root. |
| 42641 | deny | deny | **no verdict change** | a PowerShell scratch script, already denied (durable-record redirect). It gains an rm_in_x4_dir advisory that the deny outranks. |

Buckets: true positive 0 + false positive (asked/denied) 0 + neutral 2 + unchanged verdict 1 =
**3 = the changed total.**

- **Rows where OLD was stricter: 0.** At fact level every one of the 3 changes is False -> True.
  At verdict level OLD is never above NEW.
- **New ASK prompts: 0** anywhere, so none outside the X4 profile or saves. **New denies: 0.**
- **True positives in history: 0.** Nothing in 53,828 commands wrote or deleted a protected file
  by a relative path. The defect is real (the controls, and lane B's live Codex overwrite) but
  never fired in this corpus. That is a statement about this machine's history, not about the
  risk.

## How it got there: the prototype measured first, then narrowed

The prototype seeded the payload cwd everywhere. **113 rows** changed facts, all False -> True.
The worst verdict per row (READ mapping from `protect-bash.sh`'s `on ... &&` table) was:
**105 advise, 5 deny, 3 ask**. Every deny and ask row was read by hand:

| row(s) | would-be verdict | cause | narrowing |
|---|---|---|---|
| 40033, 40188 | deny (sed -i in game) | `cd "$X4_TOOLKIT" && sed -i ... scripts/x` from the game root. The unresolved cd target was joined onto the seed (the 2026-09-02 sticky join). | From the SEED, an unresolved, relative `cd` makes the directory unknowable. After an absolute `cd`, the sticky join is unchanged. |
| 16460, 51592 | deny (sed -i in game) | `2>/dev/null` read as a sed -i TARGET, joined under the game root | Parse debris (a token with a quote, paren, `<>`, pipe or backtick) keeps its pre-seed directory |
| 50206 | deny (rm_hits_game + sed -i) | a probe harness. `$D -rf extensions")"` and escaped-quote operands were mis-segmented out of quoted arguments. | the same debris rule |
| 52067, 52068 | ask (unknown cmdlet) | a user-defined PowerShell function called with relative names from the game root | `x4-unknown-cmdlet` arguments are judged unseeded (exactly as before) |
| 52803 | ask (git clean) | a probe harness's quoted `git clean -fdx` string | `git clean` / `reset --hard` (they name no path) are judged unseeded |
| 9 advise rows | advise (redirect into game) | `2>nul` / `>nul` from the game root | a Windows device name is not a file in the directory |

A carried command (bash -c, `$(...)`, a heredoc fed to a shell) is seeded only when nothing in the
command changes directory, because the carrier walk cannot see a surrounding `cd`. The bare-python
rule keeps its own stand-in base (`seeded=False`).

Re-replay of the same 113 rows after narrowing: 12 changed, all advisory (9 of them `nul`, gone
after the device rule). The final full run above has 3.

## Residuals (disclosed, not closed)

- Neutral false advisories from mis-segmented shell text. There are 2 in history. They come from
  the segmenter (quoted `&&` inside `$(...)` arguments), not from the seed. Today they are an
  advisory to Claude, never a prompt.
- `git clean -f` / `reset --hard` and unknown PowerShell cmdlets do NOT use the seed. A bare `git
  clean -fdx` from the toolkit root is therefore still allowed, as it was before lane F. Making it
  ask would be a new prompt outside the profile (user, 2026-10-02).
- Codex: the shell `workdir` is not visible to hooks (lane B, C7). A relative operand is judged
  against the session cwd, which may differ from where the command runs.
- A cd target that cannot be resolved, taken from the seed, now makes later relative operands
  unknowable. This is the same as no seed, so it is never worse than before.

## Codex conformance

See the lane report: `tests/test_codex_conformance.py`, plus 3 new extras (a relative delete
through bash and through PowerShell must deny on both chains; the unrelated-cwd twin must allow).
The Claude side of the extras now carries the same `cwd` the Codex payload does.

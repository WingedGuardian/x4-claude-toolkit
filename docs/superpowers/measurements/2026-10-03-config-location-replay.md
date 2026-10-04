# Config-location replay: OLD vs NEW guard verdicts (Plan 3 lane I)

**Date:** 2026-10-03 · **Tier:** MEASURED · **Result:** 0 changed verdicts, 0 ERROR rows, in
every pass; every control held.

Plan 3 lane I moves `x4-paths.env` from `<toolkit>/.claude/` to the toolkit root, adds a
deprecation path for the 3.x location, and records (never prints, per call) the config state.
The binding risk control: no guard verdict may change because of the move, for a configured,
a legacy and an unconfigured toolkit alike.

## Setup

- **OLD** hooks: master `0660a2d` (`.claude/hooks/` of a detached worktree). **NEW** hooks:
  `session/p3-i` after the installer commit.
- One fake toolkit dir, the SAME path for both sides; the passes run one after the other, so
  the config file's LOCATION is the only thing that differs. Its bytes are this machine's real
  config with the `X4_NEXUS_KEY` line removed: real root STRINGS. The hooks only decide; no
  command is run.
- Environment: every `X4_*`, `CLAUDE_PROJECT_DIR` and `HOOK_DIR` removed, then
  `X4_TOOLKIT=<fake tk>`; no `X4_CONFIG`.

| pass | OLD reads | NEW reads |
|---|---|---|
| K1 configured | `<tk>/.claude/x4-paths.env` | `<tk>/x4-paths.env` |
| K2 legacy | `<tk>/.claude/x4-paths.env` | `<tk>/.claude/x4-paths.env` |
| K3 unconfigured | nothing | nothing |

## Stage 1: the argument (exhaustive)

Sourcing `_x4-env.sh` and dumping `declare -p` / `declare -f` on each side, per pass: **0
variables or functions differ** outside the allowlist (`_x4_cfg`, `_x4_cfg_src`, `_x4_cfg_tk`,
`_x4_ref_defaulted`, `x4_config_banner`, and bash dynamics). OLD 134 / NEW 137 variables in K1
and K2, 126 / 129 in K3 (the 3 extra are the allowlisted state variables); 17 / 18 functions.
`X4_REFERENCE` was the configured tree on both sides in K1 and K2 and `<tk>/reference` on both
in K3. `protect-bash.sh`, `protect-files.sh`, `hook_facts.py`, `x4guard.py` and
`ps_translate.ps1` are identical OLD vs NEW once full-line comments are stripped. So
verdict = f(command, cwd, environment, code) has every argument identical.

⚠ **Checker bug found and fixed before any row was read:** the first stage-1 run split the dump
at the FIRST `@@FUNCS@@` marker, which also occurs inside `BASH_EXECUTION_STRING`'s value, and
compared 13 of ~130 variables -- reporting "identical" vacuously. The harness now splits at the
last marker and REFUSES a dump with fewer than 60 variables, no `X4_REFERENCE` or no `x4_norm`.

## Stage 2: real hooks, sampled

| pass | hook | rows | identical | changed | ERROR | NEW verdicts |
|---|---|---|---|---|---|---|
| K1 | protect-bash.sh | 1,986 | 1,986 | 0 | 0 | allow 1831, deny 142, advise 11, ask 2 |
| K1 | protect-files.sh | 1,000 | 1,000 | 0 | 0 | allow 986, advise 10, deny 4 |
| K2 | protect-bash.sh | 1,986 | 1,986 | 0 | 0 | allow 1831, deny 142, advise 11, ask 2 |
| K2 | protect-files.sh | 1,000 | 1,000 | 0 | 0 | allow 986, advise 10, deny 4 |
| K3 | protect-bash.sh | 1,986 | 1,986 | 0 | 0 | allow 1848, deny 136, advise 2 |
| K3 | protect-files.sh | 1,000 | 1,000 | 0 | 0 | allow 993, advise 4, deny 3 |

17,916 hook calls, wall 3,803 s, 4 workers at below-normal priority (machine CPU 48% sampled).
K3's distribution differs from K1's on BOTH sides alike: with no config the guards know fewer
roots, which is today's behaviour and is what the session banner and `x4doctor` now say.

**Samples.** Shell: lane F's `corpus.jsonl` (53,828 unique Bash/PowerShell commands with their
transcript cwd), 1,000 uniform + 1,000 uniform from the root-mentioning stratum (20,884 rows),
seed 20261003 → 1,986 unique. Edit/Write: `extract_files.py` over 867 transcripts (8,757 Edit +
4,425 Write tool uses → 5,036 unique (tool, path, cwd)), 1,000 uniform, same seed.

**Controls (each pass refuses to report unless all hold, on both sides):**
K1/K2 -- `rm -f <configured reference>/libraries/__p.xml` deny, `Edit` of the same path deny
(proves each side READ its file: without it the reference would default to `<tk>/reference`
and these allow), `ls` allow. K3 -- `rm -f <tk>/reference/libraries/__p.xml` deny (the default
hard block is kept), and the configured-reference delete and edit NOT deny (no config leaked
into the unconfigured pass). All 18 control calls held.

## Re-running

The harness lives in the session scratchpad (`plan3/laneI/replay_config.py`,
`extract_files.py`; lane F's `plan2/laneF/corpus.jsonl`): `python replay_config.py stage1`, then
`python replay_config.py stage2 --workers 4`. Seed 20261003.

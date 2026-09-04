# The block every subagent prompt must carry

A reviewer subagent overwrote a user's `CLAUDE.md` and `KNOWLEDGEBASE.md` on 2026-09-02,
and a live mod registry was emptied during a review round on 2026-09-03. Neither agent
was careless and neither was doing anything it had been told not to do. Both were doing
exactly what a reviewer should: reproducing a defect, and probing whether a refusal
fires.

That is the point. **A reviewer's job brings it into contact with live data by its
nature**, so "be careful with live paths" is not a usable instruction. What follows is
the specific, checkable version.

---

## Paste this into every reviewer / prober / red-team subagent prompt

> **SANDBOX RULES — these are not advisory.**
>
> 1. **Never run an installer, deploy script, or anything that writes, against a real
>    target.** Point it at a fake directory you created. If the tool auto-detects its
>    destination, patch the detection function in a *copy* of the script first.
>
> 2. **Clearing `X4_*` environment variables is NOT a sandbox — it is how the worst
>    incident happened.** With `X4_GAME` unset, `install.sh` fell through to detecting
>    the user's real Steam install and wrote 1,642 files into it. Resolution also falls
>    through `$X4_TOOLKIT` → `.claude/x4-paths.env`, so a "cold" environment can still
>    be fully configured. Cold means *proven* cold: assert the roots resolve to `None`,
>    or use `tools/x4validate/scripts/verify-cold.sh`, which refuses to run until it has
>    proved that.
>
> 3. **Reproduce a defect on a COPY.** Copy the artifact into your scratchpad and break
>    that. Never demonstrate a data-destroying bug against the file it destroys.
>
> 4. **To probe whether a refusal fires, do not rely on the refusal.** If the guard is
>    broken — which is what you are testing — the action happens for real. Aim it at a
>    fake target so that a broken guard costs nothing.
>
> 5. **These paths are never write targets, whatever the reason:** the game
>    installation, the user profile (`Documents/Egosoft/X4/`), the mod source tree, the
>    reference tree, the mod registry, `CLAUDE.md`, `KNOWLEDGEBASE.md`, the memory
>    directory, and any `x4-paths.env`. Many are marked read-only by
>    `scripts/x4lock.py`; a `PermissionError` from one of them is the guard working, not
>    a bug to route around. **Do not unlock anything.**
>
> 6. **Write every measurement, script and artifact to the scratchpad directory named in
>    your prompt.** Never `/tmp` (shared between concurrent sessions) and never the
>    repository working tree (another session may be mid-commit in it).
>
> 7. **Do not edit the working tree.** Review it. If you want to prove a fix, do it in a
>    `git worktree` or a copy and say which.

---

## What the dispatching session owes, and it is not a promise to be careful

- **Run `python scripts/x4canary.py` before and after every subagent batch.** It exits 1
  on a loss and 2 when it could not check. The 2026-09-03 registry loss was visible in
  `git status` from the moment it happened and was found six hours later by accident;
  the detector existed and nothing ran it.
- **Name the scratchpad path in the prompt.** An agent with nowhere to write will write
  somewhere.
- **Never dispatch a subagent while a mutating gate runs.** `gates/mutation_probe.py`
  edits tracked source in place, so a reviewer reading the tree reads deliberately
  broken code and reports it as a defect.
- **Prefer worktrees for anything that edits.** One branch per lane; the shared tree is
  how one session's untracked WIP became another's test count.

## Why this file exists rather than another line in CLAUDE.md

150 KB of instructions were in context during every one of these incidents. Prose did
not stop them, and a rule that has already failed four times does not become true by
being restated. This is a *checklist to paste*, so it is present at the moment of
dispatch rather than remembered — and the parts that can be mechanised (the locks, the
canary, the read-only registry) have been, because those are the ones that work.

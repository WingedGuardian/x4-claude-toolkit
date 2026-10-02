# AGENTS.md — X4 Foundations Modding (X4 AI Assistant Toolkit)

### How the safety rules reach you (Codex only: another agent may skip this part)

Under Claude Code these rules are enforced by tested hooks. **Under Codex they may not be:
Codex hooks fail OPEN** (measured, Codex 0.159.2): if a hook crashes, times out or was never
reviewed by the user, Codex runs the command anyway, and unreviewed or changed hooks are
skipped silently. So keep every rule below by your own discipline (and never write into the
game installation), and ask the guards before anything that writes or deletes:

    python .claude/hooks/x4guard.py check --kind shell --shell powershell --command "<cmd>"
    python .claude/hooks/x4guard.py check --kind write --path "<file>"
    python .claude/hooks/x4guard.py check --kind delete --path "<file>"

On Windows Codex runs shell commands in **PowerShell**: pass `--shell powershell` (judged as
bash, a PowerShell write into `reference\` was measured to pass), and write the toolkit root
as `$env:X4_TOOLKIT` where a skill says `$X4_TOOLKIT`. On Linux/macOS pass `--shell bash` and
use `python3`. Treat `deny` and `ask` as a stop and ask the user; treat `inert: true` as
"nothing was checked", never a pass.
Skills live in `.agents/skills/<name>/SKILL.md`; open the one this file names before the task.
Never `git add -A` / `git add .`: stage explicit paths.

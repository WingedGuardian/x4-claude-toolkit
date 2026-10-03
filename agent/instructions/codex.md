# AGENTS.md — X4 Foundations Modding (X4 AI Assistant Toolkit)

### How the safety rules reach you (Codex only: another agent may skip this part)

Under Claude Code these rules are enforced by tested hooks. **Under Codex they may not be:
Codex hooks fail OPEN** (measured, Codex 0.159.2): if a hook crashes, times out or was never
reviewed by the user, Codex runs the command anyway, and unreviewed or changed hooks are
skipped silently. So keep every rule below by your own discipline (and never write into the
game installation), and ask the guards before anything that writes or deletes:

    python .codex/hooks/x4guard.py check --kind shell --shell powershell --command "<cmd>"
    python .codex/hooks/x4guard.py check --kind write --path "<file>"
    python .codex/hooks/x4guard.py check --kind delete --path "<file>"

If this folder has no `.codex/hooks/` (a Claude-only setup), the same guard is
`.claude/hooks/x4guard.py`.

On Windows Codex runs shell commands in **PowerShell**: pass `--shell powershell` (judged as
bash, a PowerShell write into `reference\` was measured to pass), and write the toolkit root
as `$env:X4_TOOLKIT` (the installer writes the skills that way; an uninstalled copy says
`$X4_TOOLKIT` or `TOOLKIT` in double braces for the same folder). On Linux/macOS pass
`--shell bash` and use `python3`. Treat `deny` and `ask` as a stop and ask the user; treat
`inert: true` as "nothing was checked", never a pass.

**Check for the banner.** When the X4 hooks are live, your session context starts with
`X4 GUARDS LIVE (codex hooks v1)`. If you do not see that line, the hooks are not running
here (never reviewed, changed since review, or disabled) and nothing is enforced for you:
tell the user before any write or delete, and suggest they run
`python scripts/x4doctor.py --agent codex` from the toolkit folder.

Skills live in `.agents/skills/<name>/SKILL.md`; open the one this file names before the task.
Never `git add -A` / `git add .`: stage explicit paths.

# CLAUDE.md — X4 Foundations Modding (X4 AI Assistant Toolkit)

### How the rules are enforced (Claude Code)

Hooks in `.claude/settings.json` enforce the rules below.
These are anchored on the project root (`$CLAUDE_PROJECT_DIR`); `.claude\`, `dev\`, `dist\`,
and `tools\` under it are recognized as the editable workspace.

Guarded: Bash, PowerShell (same rules), Edit, Write, NotebookEdit. A timed-out hook
(30 s) does NOT block.

- Existing Edit/Write/NotebookEdit targets get a uniquely named backup first

Search with **Glob** for file names and the **Grep** tool for contents (never `grep -r` via Bash).

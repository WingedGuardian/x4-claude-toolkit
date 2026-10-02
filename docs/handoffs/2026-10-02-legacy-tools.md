# Claude handoff: retained legacy tools

User decision: patch and retain BOTH the local dev deploy helper and x4cat for
now. Claude receives the later migration/retirement decision. This document does
not authorize a retirement, user-mod deploy, or communication to another session.

## Changes

`dev/_tools/deploy.py`: explicit ownership/name/manifest checks under -O; all-mod
preflight including file/directory shape conflicts; refuse symlinks/reparse points;
canonical containment and operand checks;
dry-run default, retired toolkit-helper restriction and byte verification preserved.
Trusted configured roots, no transactional rollback or hostile-concurrency guarantee.

`tools/x4cat-spike`: complete pinned-template validation before output; CLI
--template-dir and keyword-only library template_dir; invalid present/explicit
templates never trigger retrieval. Missing default retains pinned retrieval.
UTF-8 CLI diagnostics fix a measured cp1252 crash. The required template is still
the existing extension_poc pin f9e195a998347f43cd74de2edf11703735cebb02.

## Later decision

Compare the local helper's OWNED list, retired restrictions and orphan handling
against the toolkit deployer before replacing either workflow. For x4cat, archive
pack/read/index/scaffold capabilities differ from x4validate; demonstrate replacement
parity before proposing retirement. Preserve local uv.lock edits and untracked spikes.

The game-root AGENTS.md still names the removed external tools/x4validate path.
The actual suite is now `$X4_TOOLKIT/tools/x4validate`. Correct that installed
instruction through the agent-support workflow; this tool repair does not edit
the game-root harness directly or recreate a duplicate external suite.

Reviewed revisions, installed status and E2E evidence belong in the
[repair report](../audits/2026-10-02-tool-fixes.md). No retirement performed here.

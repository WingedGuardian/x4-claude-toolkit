#!/bin/bash
# Protect against destructive bash commands. Cross-platform & config-driven.
# Matches the configured paths (.claude/x4-paths.env / env vars) in the command text, with
# legacy folder-name patterns as a backstop so it still guards out of the box.
JQ="${JQ:-jq}"
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/_x4-env.sh"

INPUT=$(x4_hook_input)
x4_require_input "$INPUT" "X4 GUARD INERT: this hook received NO INPUT, so it checked nothing. Allowing silently is how five hooks sat dead for weeks while their suites passed. Confirm only if you know why the payload is missing."
# ONE jq call for all three fields. This hook runs on EVERY Bash invocation, so a
# second invocation is a tax paid forever -- MEASURED at +58 ms/call (+14%).
# The command is emitted LAST and read with `cat`, because a command may be
# multi-line (heredocs are routine here) and @tsv would escape the newlines,
# silently changing what every rule below matches against.
{ read -r TIMEOUT; read -r BACKGROUND; COMMAND=$(cat); } < <(
  echo "$INPUT" | "$JQ" -r '(.tool_input.timeout // 0),
                             (.tool_input.run_in_background // false),
                             (.tool_input.command // "")'
)
TIMEOUT=${TIMEOUT%$'\r'}
BACKGROUND=${BACKGROUND%$'\r'}
# jq.exe on Windows emits CRLF. Strip the CR or `[ "$TIMEOUT" -gt N ]` dies with
# "integer expression expected" -- and it gets that far because grep treats the CR
# as a line terminator, so `^[0-9]+$` MATCHES and the numeric guard is passed a
# value it cannot compare. Caught by the hook's own regression suite, 15 failures.
[ -z "$COMMAND" ] && exit 0

deny() { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'; exit 0; }
# advise <reason> -- ALLOW, and explain to CLAUDE why the command is questionable.
# The user's attention is the scarce resource: a prompt spends theirs, a deny or an
# advisory spends mine. Anything that is merely MY hygiene must never reach them.
# MEASURED 2026-08-29: fixing the stdin defect brought five inert hooks to life at
# once and turned bypass-permissions mode into manual mode.
advise() { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$r}}'; exit 0; }
ask()  { "$JQ" -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:$r}}'; exit 0; }

nCMD="$(x4_norm "$COMMAND")"
# has VALUE -> 0 if the (normalized) command mentions that (non-empty, normalized) path/name.
has() { [ -n "$1" ] && printf '%s' "$nCMD" | grep -qF "$(x4_norm "$1")"; }
# has_root VALUE -> 0 if the command names that path AS A ROOT: the path followed
# by end-of-string, whitespace, or a quote. Plain `has` is wrong here -- it also
# matches "$ROOT/tools/x4validate", so a deliberately SCOPED search would be
# blocked, and over-blocking is the worse of the two failures: it makes
# legitimate work impossible and the reason is not obvious from the message.
#
# Pure-bash `case` globbing, deliberately: this hook runs on EVERY Bash call, so
# a subprocess here is a tax paid forever. It also sidesteps regex escaping --
# the first draft built a sed character class and the escaping collapsed, so the
# pattern matched nothing and the rule silently stopped firing. The suite caught
# it; the code did not.
has_root() {
  [ -n "$1" ] || return 1
  local root q a
  root="$(x4_norm "$1")"; root="${root%/}"
  q='"'; a="'"
  case "$nCMD" in
    *"$root"|*"$root"/) return 0 ;;
    *"$root "*|*"$root"/" "*|*"$root$q"*|*"$root"/"$q"*|*"$root$a"*|*"$root"/"$a"*) return 0 ;;
  esac
  return 1
}

is_rm() { printf '%s' "$COMMAND" | grep -qE '(^|[;&|[:space:]])rm([[:space:]]|$)'; }

# === HARD BLOCK — delete the game installation ===
{ is_rm && { has "$X4_GAME" || printf '%s' "$nCMD" | grep -qF 'x4 foundations'; }; } && deny "BLOCKED: cannot delete the X4 game installation directory."

# === HARD BLOCK — delete the reference folder (read-only base game data) ===
{ is_rm && has "$X4_REFERENCE"; } && deny "BLOCKED: cannot delete reference/ — it is the read-only unpacked base game data (re-unpack only via bin/unpack-reference.sh)."

# === HARD BLOCK — re-unpack into a locked reference/ ===
# Sentinel-gated: once reference/.unpacked-and-locked exists, block accidental re-unpacks.
if printf '%s' "$COMMAND" | grep -qiE 'xrcat|XRCatTool' && printf '%s' "$nCMD" | grep -qE '\-out' \
   && has "$X4_REFERENCE" && [ -f "$X4_REFERENCE/.unpacked-and-locked" ]; then
  deny "BLOCKED: reference/ is locked (reference/.unpacked-and-locked exists). Re-unpacking would overwrite the read-only base. Remove the sentinel first if you really mean to re-unpack."
fi

# === CONFIRM — rm targeting the game, profile, reference, mods, or toolkit ===
{ is_rm && { has "$X4_GAME" || has "$X4_PROFILE" || has "$X4_MODS" || has "$X4_TOOLKIT" \
    || printf '%s' "$nCMD" | grep -qE 'x4 foundations|egosoft/x4'; }; } \
  && ask "Deleting files in an X4 directory — confirm: $COMMAND"

# === CONFIRM — mv/cp into the game or profile dirs ===
printf '%s' "$COMMAND" | grep -qiE '^[[:space:]]*(mv|cp|move|copy)\b' \
  && { has "$X4_GAME" || has "$X4_PROFILE" || printf '%s' "$nCMD" | grep -qE 'x4 foundations|egosoft/x4'; } \
  && advise "Copying into a game or profile directory. That is the documented DEPLOY path, so it is allowed -- but use dev/_tools/deploy.py rather than a hand-rolled cp: it refuses a wrong destination, deletes orphans one named file at a time, and re-reads the destination to prove every file is byte-identical."

# === CONFIRM — output redirect into game or profile dirs ===
printf '%s' "$COMMAND" | grep -qE '>' \
  && { has "$X4_GAME" || has "$X4_PROFILE" || printf '%s' "$nCMD" | grep -qE 'x4 foundations|egosoft/x4'; } \
  && advise "Redirecting output into a game or profile directory. Allowed, but a truncating > has no backup: if the target is a durable record, write to a temp file and move it into place."

# === CONFIRM — sed -i on game or profile files ===
printf '%s' "$COMMAND" | grep -qE 'sed[[:space:]]+-i' \
  && { has "$X4_GAME" || has "$X4_PROFILE" || printf '%s' "$nCMD" | grep -qE 'x4 foundations|egosoft/x4'; } \
  && deny "In-place edit in game/profile directory — confirm: $COMMAND"

# === CONFIRM — direct reference to .cat/.dat archives ===
# DROPPED 2026-08-29: this fired on any command whose TEXT mentioned a .cat -- including
# an `echo` that merely discussed one. Writing a .cat is already covered by 
# protect-files.sh, which checks the actual TARGET PATH rather than the command text.


# =============================================================================
# The rules below were developed in a live modding workspace and ported here on
# 2026-08-29. Each carries the MEASURED cost of the failure it prevents -- that
# is deliberate, because a guard whose reason has been trimmed away is the first
# one someone deletes. Paths resolve through _x4-env.sh, never as literals.
# =============================================================================

# === ASK — `git add -A` / `git add .` in a workspace shared by concurrent sessions ===
# MEASURED 2026-08-27: a second session had four untracked WIP files in the same
# tree (`_livecli.py`, `_livedump.py` + tests). They inflated the suite 836 -> 877
# and `git add -A` would have committed someone else's half-finished work. It did
# not, but only by timing -- none of the four commits happened to fall after their
# files appeared. Stage explicit paths instead.
#
# Deliberately ASK, not deny: with a worktree per session `-A` is safe again, and
# there are legitimate uses (an initial import, a scripted scrub). The prompt is
# there to make you look at `git status` first, not to forbid the flag.
echo "$COMMAND" | grep -qE '(^|[;&|]\s*)git\s+add\s+(-A\b|--all\b|\.\s*$|\.\s*[;&|])' && deny "GIT ADD -A / . IN A SHARED WORKSPACE: this stages EVERY untracked file, including another session's work-in-progress. MEASURED 2026-08-27: 4 untracked files from a concurrent session sat in this tree. Prefer explicit paths (git add <file> ...). Proceed?"


# === DURABLE RECORDS — a truncating write via Bash has NO backup and NO guard ===
# backup-before-edit.sh and protect-files.sh are wired to Edit|Write ONLY. A file edited
# through Bash (a `>` redirect, or python's open(p,"w")) gets neither. And open(p,"w")
# TRUNCATES AT OPEN, so an exception mid-write leaves the file EMPTY, not unchanged —
# the traceback looks like "nothing happened" while the content is gone.
# Measured 2026-08-22: that is exactly how a memory file was wiped to 0 bytes.
# Appends (`>>`) are deliberately NOT blocked — they cannot truncate.
DURABLE='(memory[/\][A-Za-z0-9_.-]+\.md|MEMORY\.md|KNOWLEDGEBASE\.md|CLAUDE\.md|BLIND-SPOTS\.md)'

# Unambiguous: a single `>` pointed straight at a durable record.
if echo "$COMMAND" | grep -qE "[^>]>[[:space:]]*[\"']?[^|;&>]*$DURABLE"; then
  deny "BLOCKED: truncating redirect onto a durable record.
A '>' replaces the file, and a Bash write gets NO backup (backup-before-edit.sh only covers Edit|Write).
Use instead:
  - the Edit tool for a surgical change (backed up, and it fails loudly if the match is not unique)
  - the Write tool for a full replacement (backed up)
  - '>>' to append — it cannot truncate
Command: $COMMAND"
fi

# Heuristic: a python truncating open in a command that also names a durable record. The
# path is usually in a variable, so it will not appear inside open() itself.
if echo "$COMMAND" | grep -qE "$DURABLE" \
   && echo "$COMMAND" | grep -qE "open\([^)]*,[[:space:]]*[\"']w[\"']"; then
  deny "python open(...,'w') in a command that names a durable record (memory / KNOWLEDGEBASE / CLAUDE.md / BLIND-SPOTS).
open() TRUNCATES AT OPEN — if the write then raises, the file is left EMPTY. This wiped a memory file on 2026-08-22.
Prefer the Edit/Write tools (backed up), or write to a temp and rename. If you proceed, VERIFY the size afterwards.
Command: $COMMAND"
fi

# === TOOL ROUTING — block recursive text search over the 60 GB reference tree ===
# Purpose-built tools answer these far faster and with a denominator. See CLAUDE.md
# "Discovery vs. Proof" routing table. This blocks the reflex, not the capability:
# a scoped grep at a specific subdirectory still works.
if echo "$COMMAND" | grep -qiE '\b(grep|rg|ag)\b[^|;]*(-[a-zA-Z]*[rR]|--recursive)' \
   && has "$X4_REFERENCE"; then
  deny "WRONG TOOL: recursive text search over the whole reference\\ tree (~60 GB).
Route the question first (CLAUDE.md 'Discovery vs. Proof'):
  - 'what values does attribute X take / who references X?' -> BaseX: cd tools\\basex && python ask.py ...
    (fast, and gives a DENOMINATOR — which a bare grep count never does)
  - 'what is the LIVE value and who set it?'                -> uv run x4effective
  - 'does a file with this NAME exist?'                     -> the Glob tool (NOT grep: grep searches CONTENTS)
  - 'find this text in ONE known area'                      -> the Grep tool (ripgrep), or scope this grep to a subdirectory
If you truly need a full-tree scan, scope it to a subpath so it is deliberate rather than reflexive."
fi

# === MEASUREMENT-INSTRUMENT TRAP — searching the profile content.xml by NAME ===
# The profile content.xml keys EVERY entry by the mod's MANIFEST ID, never by
# folder name and never by display name. MEASURED 2026-08-23: of 123 on-disk
# mods, 60 match by manifest id and only 9 by folder name.
#
# The failure this catches actually happened, 2026-08-23: `grep -i xspvro` on the
# profile returned nothing -- because the entry is `ws_3691358137` -- and that
# zero was one keystroke from being written into permanent record as "xspvro has
# no ban record, so a Steam re-download would come back ENABLED". It would have
# destroyed a CORRECT memory and reported a real safety protection as absent.
#
# `ask`, not `deny`, and deliberately: mod ids and mod names are not
# syntactically distinguishable (`escape_pod` is both), so a deny would
# over-block legitimate id lookups. This interrupts the reflex; it does not
# remove the capability.
if echo "$COMMAND" | grep -qiE '\b(grep|rg|ag|findstr|Select-String)\b' \
   && { has "$X4_PROFILE" || echo "$COMMAND" | grep -q "X4_PROFILE"; } && echo "$COMMAND" | grep -qi "content" \
   && ! echo "$COMMAND" | grep -qE 'ws_[0-9]{4,}'; then
  deny "CHECK THE INSTRUMENT: the profile content.xml is keyed by MANIFEST ID, not by mod name.
A name-shaped search finding nothing proves NOTHING -- it is the wrong query.
MEASURED: 60 of 123 on-disk mods match by manifest id, only 9 by folder name.
Real case (2026-08-23): 'grep -i xspvro' -> 0 hits, but the entry is 'ws_3691358137'.

Route it instead:
  - 'is this mod active / installed?'  -> _registry.mods(\"active\"|\"installed\") -- never the raw file
  - 'what is this mod's id?'           -> read the mod's OWN extensions/<folder>/content.xml @id
  - and remember: the profile is a DECISION LOG, not an inventory. MEASURED 2026-08-23:
    348 entries, 287 FOSSILS (82.5%), and 54 of 115 installed mods absent from it entirely.
    ABSENT != DISABLED -- X4 adds an unseen folder as ENABLED. See CLAUDE.md #30.

If you already have the manifest id and are grepping for THAT, proceed."
fi


# ============================================================================
# MEASUREMENT-INSTRUMENT TRAPS  (added 2026-08-22)
# ----------------------------------------------------------------------------
# MEASURED across three sessions: 10 of 10 checking-step bugs were the CHECKER,
# not the finding. Three of them, in one session, were plain shell artefacts.
# CLAUDE.md #22 records the rule; prose alone has already failed to stop a
# repeat here (#20 was in always-in-context text and still recurred twice in
# one session), so the two textually-detectable ones get a tripwire.
#
# Both are `ask`, NOT `deny`, on purpose. They are heuristics over shell text,
# and this workspace's own rule is that sub-90% confidence buys a MEASUREMENT
# rather than a gate. Promote to `deny` only after they run clean for a while;
# a check that misfires is worse than no check, because it trains you to ignore
# the output.
#
# Detector development is recorded because it is the point: the first draft
# false-fired on `cat >> f.md <<'EOF' | a | b | EOF; echo $?` -- a markdown
# table in a heredoc, which is a shape used constantly in this workspace. It
# was caught by probing must-NOT-fire cases BEFORE wiring anything in. Final
# probe: 16/16 adversarial cases correct, 0 false positives.

# --- `$?` read after a pipeline -------------------------------------------
# `cmd | head; echo $?` reports HEAD's exit code, not cmd's. This turned a
# stale-index refusal (real exit 5) into an apparent "exit 0" and was nearly
# filed as a tool defect.
# Order matters: strip heredoc BODIES first, then quoted strings, and only then
# look for a real pipeline -- otherwise `grep -E "a|b"` reads as one.
# CHEAP GATE FIRST. The awk below costs a subprocess on every single Bash call,
# and MEASURED it added ~195 ms (+59%) when run unconditionally. The overwhelming
# majority of commands contain no `$?` at all, so one grep short-circuits them.
if echo "$COMMAND" | grep -qE '\$\?' && ! echo "$COMMAND" | grep -q 'PIPESTATUS'; then
_PB_NOHD=$(printf '%s\n' "$COMMAND" | awk '
  function term(s){ gsub(/^<<-?[ ]*/,"",s); gsub(/["\x27]/,"",s); return s }
  { if (skip) { if ($0 == t || $0 == t";") { skip=0 }; next }
    line=$0
    if (match(line, /<<-?[ ]*["\x27]?[A-Za-z_][A-Za-z0-9_]*["\x27]?/)) {
      t = term(substr(line, RSTART, RLENGTH)); skip=1 }
    print line }')
if printf '%s' "$_PB_NOHD" | grep -qE '\$\?' \
   && printf '%s' "$_PB_NOHD" | sed "s/'[^']*'//g; s/\"[^\"]*\"//g" \
      | grep -qE '[^|]\|[^|]'; then
  deny "\$? AFTER A PIPELINE reports the LAST command's exit code, not the one you mean.
  cmd | head; echo \$?      -> that is HEAD's exit code
Measured 2026-08-22: this reported a stale-index refusal (real exit 5) as 'exit 0',
and it was nearly written up as a tool defect. See CLAUDE.md #22.
Use instead:
  cmd > out 2>&1; rc=\$?     # capture FIRST, format afterwards
  \${PIPESTATUS[0]}          # if you must keep the pipeline
Proceed only if the \$? genuinely belongs to a non-piped command.
Command: $COMMAND"
fi
fi

# --- measurement output into shared /tmp ----------------------------------
# /tmp is shared across CONCURRENT sessions. Near-miss: 5 of 8 gate outputs
# read back were a parallel session's, 4 hours stale, and were nearly reported
# as this session's results. Reads and cleanup are fine; only writes fire.
if echo "$COMMAND" | grep -qE '(>|>>|-o|--output[= ])[[:space:]]*"?/tmp/'; then
  deny "WRITING MEASUREMENT OUTPUT TO /tmp — it is shared across concurrent sessions.
A parallel session's stale files were once nearly reported as this session's results.
Use the session scratchpad instead (see the 'Scratchpad Directory' section of the
system prompt), and never glob a pattern that can match another run's files.
Command: $COMMAND"
fi

# --- recursive search rooted AT the workspace / game root -----------------
# Distinct from the reference\ rule above, which only covers reference\.
# MEASURED 2026-08-22: `grep -rn` over the whole workspace root was killed at 300 s
# ripgrep tool timed out at 20 s -- tools\basex\basex\data\ alone was 3.7 GB of
# binary database pages. The path must TERMINATE at the root, so a scoped
# search into any subdirectory is unaffected.
if echo "$COMMAND" | grep -qiE '\b(grep|rg|ag)\b[^|;]*(-[a-zA-Z]*[rR]|--recursive)' \
   && { has_root "$X4_TOOLKIT" || has_root "$X4_GAME" || has_root "$X4_MODS"; }; then
  deny "WRONG SCOPE: recursive text search rooted at the whole workspace / game root.
It does not finish — MEASURED 2026-08-22: grep -r killed at 300 s, ripgrep timed out at
20 s, because tools\basex\basex\data\ alone is GBs of binary database pages.
Name the directory you actually mean:
  tools\x4validate  ·  dev  ·  tools\basex (excluding basex/data)
Or route the question (CLAUDE.md 'Discovery vs. Proof'):
  values / who-references-X  -> BaseX ask.py (gives a DENOMINATOR)
  the LIVE value + who set it -> uv run x4effective
  does a FILE by this name exist -> the Glob tool, not grep
Command: $COMMAND"
fi

# --- timeout ABOVE the harness cap ----------------------------------------
# The Bash tool caps `timeout` at 600000 ms and SILENTLY CLAMPS anything larger.
# Passing 900000 does not buy 15 minutes: the command is killed at exactly 10:00
# with exit 143/124, and nothing says it was clamped -- so it reads like the
# command hanging rather than the harness stopping it.
# MEASURED 2026-08-22: this cost four separate 10-minute losses in ONE session
# (corpus_sweep, a 19-gate loop, a 5-gate loop, perf_guard), every time from
# passing a number that was assumed to raise the ceiling and never did.
# Pure-bash numeric test: no subprocess. This hook runs on EVERY Bash call, so a
# grep here would be unconditional tax on every command in the session.
case "$TIMEOUT" in ''|*[!0-9]*) TIMEOUT_NUM=0 ;; *) TIMEOUT_NUM=1 ;; esac
if [ "$TIMEOUT_NUM" = 1 ] && [ "$TIMEOUT" -gt 600000 ]; then
  deny "TIMEOUT ABOVE THE CAP: you passed ${TIMEOUT}ms, but the Bash tool's maximum is 600000ms.
Larger values are silently clamped -- the command will be KILLED at exactly 10:00 (exit 143),
which looks like a hang and is not one.
Needing more than 10 minutes IS the signal to background it, not to raise the number:
  run_in_background: true      <- no cap; you are re-invoked when it finishes (do NOT poll)
Or split the work so no single foreground call approaches the cap."
fi

# --- a known LONG job in the foreground ------------------------------------
# Measured runtimes in this workspace: gates/corpus_sweep.py ~2100s,
# gates/perf_guard.py (and --record) ~600s+, build-effective.sh ~100-200s,
# `x4effective build` and build-corpus.sh minutes. A loop over the full mod set
# blows the cap even when no single item is slow.
# Pre-filter with a pure-bash `case` so the OVERWHELMING majority of commands pay
# ZERO subprocesses here. Only a command naming a known long job goes on to the
# grep that confirms it is an INVOCATION rather than a mention -- which is what
# keeps `grep -n corpus_sweep gates/README.md` from firing.
case "$COMMAND" in
  *corpus_sweep*|*perf_guard*|*build-effective.sh*|*build-corpus.sh*|*stage.py*|*x4effective*build*) LONGJOB=1 ;;
  *) LONGJOB=0 ;;
esac
if [ "$LONGJOB" = 1 ] && [ "$BACKGROUND" != "true" ] \
   && echo "$COMMAND" | grep -qE '\b(uv run|python|python3|bash)\b'; then
  deny "LONG JOB IN THE FOREGROUND — this is a known multi-minute command and the Bash
tool hard-caps a foreground call at 600000ms (10 min).
MEASURED: corpus_sweep ~2100s · perf_guard ~600s+ · build-effective.sh ~100-200s.
Prefer  run_in_background: true  — it has no cap and re-invokes you on completion.
Proceed in the foreground only if you have scoped it down (e.g. --limit=N).
Command: $COMMAND"
fi

exit 0

exit 0

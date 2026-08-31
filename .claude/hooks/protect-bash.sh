#!/bin/bash
# Protect against destructive bash commands. Cross-platform & config-driven.
#
# STRUCTURE: hook_facts.py does ONE parse pass over the command and answers every
# rule's question; this file holds the POLICY -- which verdict, and the prose that
# explains it. Nothing here re-parses shell text.
#
# WHY, and it is measured. Each rule used to hand-roll its own quote-aware parsing in
# bash. On 2026-08-31, clean machine, a 201-char command cost 13,585 ms per Bash call
# against 1,205 ms before the rules were re-scoped -- 11.3x -- because resolve_var
# re-derived its assignment table per TOKEN inside per-SEGMENT loops, and writes_under
# and searches_rooted_at were re-invoked 5 and 4 times, each re-tokenising from scratch.
# PreToolUse blocks the tool call, so that was pure latency on every command.
#
# Every gap a code review found also lived in that duplicated parsing: `mv -t`, `>|`,
# wrapper verbs (time/nice/env/sudo/xargs), `grep -r -e`, rg being recursive by default,
# and a heredoc marker inside a quoted string opening a skip region. Fixing them one
# predicate at a time meant writing the same parser eight more times. The parse pass is
# unit-tested directly (test_hook_facts.py, 99 tests) and every test is proven able to
# fail by a planted mutation (13 of 13), with all 19 predicates probed in both directions.
JQ="${JQ:-jq}"
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/_x4-env.sh"

INPUT=$(x4_hook_input)
x4_require_input "$INPUT" "X4 GUARD INERT: this hook received NO INPUT, so it checked nothing. Allowing silently is how five hooks sat dead for weeks while their suites passed. Confirm only if you know why the payload is missing."

# emit KIND REASON -- render one verdict as JSON.
#
# jq is used when it works, and PYTHON renders it when jq does not. That fallback is
# not belt-and-braces: this hook no longer parses with jq, only EMITS with it, so a
# broken jq turned every deny into empty stdout -- which the harness and the client
# both read as ALLOW. Silence is allow, and that is the exact defect that left five
# hooks dead for five weeks. Python is already required to reach this line, so the
# fallback is always available.
#
# The reason travels through the ENVIRONMENT, never the command line: a message
# containing quotes, newlines and backslashes is routine here, and every attempt to
# escape one through an interpreter argument in this workspace has collapsed.
emit() {
  if [ "$JQ_OK" = 1 ]; then
    if [ "$1" = "advise" ]; then
      "$JQ" -n --arg r "$2" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$r}}'
    else
      "$JQ" -n --arg k "$1" --arg r "$2" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:$k,permissionDecisionReason:$r}}'
    fi
  else
    X4_KIND="$1" X4_REASON="$2" "$PY" -c 'import json, os, sys
k = os.environ["X4_KIND"]; r = os.environ["X4_REASON"]
h = {"hookEventName": "PreToolUse"}
if k == "advise":
    h["additionalContext"] = r
else:
    h["permissionDecision"] = k; h["permissionDecisionReason"] = r
sys.stdout.buffer.write(json.dumps({"hookSpecificOutput": h}).encode("utf-8"))'
  fi
}

deny() { VERDICT=1; emit deny "$1"; exit 0; }
ask()  { VERDICT=1; emit ask  "$1"; exit 0; }
# advise <reason> -- ALLOW, and explain to CLAUDE why the command is questionable.
# The user's attention is the scarce resource: a prompt spends theirs, a deny or an
# advisory spends mine. Anything that is merely MY hygiene must never reach them.
#
# ACCUMULATES, and does NOT exit. An advisory is an ALLOW THAT CARRIES A NOTE, not a
# decision -- so it must never make the rules below it unreachable. MEASURED
# 2026-08-30 (F84): with the six advisory/ask rules off, 298 of the 1,846 commands
# they catch are REFUSED by a rule further down -- 130 timeout-above-the-cap, 64
# shared-/tmp, 35 durable truncating-open, 27 exit-status-after-a-pipeline, 26
# profile-manifest-by-name, 11 stage-everything. Every one measured genuine, every
# one silently suppressed by a note. deny/ask still exit: those ARE decisions.
VERDICT=""
ADVICE=""
# Flush on EVERY exit path. A tail-only flush is silently skipped by the whitelist
# `exit 0`s in the middle of this file -- MEASURED 2026-08-30: it turned the manifest
# advisory into a plain allow.
flush_advice() {
  [ -n "$VERDICT" ] && return 0
  [ -n "$ADVICE" ] || return 0
  emit advise "$ADVICE"
}
trap flush_advice EXIT
advise() { if [ -n "$ADVICE" ]; then ADVICE="$ADVICE
$1"; else ADVICE="$1"; fi; }

# --- the single parse pass ---------------------------------------------------
# A guard that cannot see its input must not stay silent: silence IS allow, and that
# is exactly how every hook here sat dead for five weeks. So a missing interpreter, a
# crash, or an unparseable payload ASKS -- it never falls through.
PY=""
if [ -n "${X4_PYTHON:-}" ]; then
  # An EXPLICITLY configured interpreter that does not resolve is an error, not a cue to
  # quietly use a different one. Falling through would mean the guard runs under an
  # interpreter the operator did not choose, and it would leave the "no Python" branch
  # unreachable -- a failure path that cannot be provoked is not a failure path.
  command -v "$X4_PYTHON" >/dev/null 2>&1 && PY="$X4_PYTHON"
else
  for c in python python3 py; do
    command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
  done
fi
# Does jq actually WORK? Presence on PATH is not the question -- the probe that caught
# this pointed JQ at a missing binary. Tested once, here, rather than discovered on the
# verdict path where a failure is silent.
JQ_OK=0
printf '%s' '{}' | "$JQ" -e . >/dev/null 2>&1 && JQ_OK=1

if [ -z "$PY" ]; then
  printf '%s' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"X4 GUARD INERT: no Python interpreter was found, so protect-bash.sh could not analyse this command and checked NOTHING. Set X4_PYTHON, or put python on PATH. Confirm only if you know why it is missing."}}'
  exit 0
fi

# The roots go over STDIN, ahead of the payload -- NOT through the environment.
#
# Two reasons, both measured. (1) _x4-env.sh only exports what came from x4-paths.env
# (via `set -a`); X4_DOCUMENTS is computed in a loop and X4_SAVES/X4_REFERENCE come from
# `: ${VAR:=...}`, so none of those are exported and the child would see them EMPTY --
# `under()` is false for an empty root, so those rules would be silently dead.
# (2) Worse, and the reason the environment cannot be used at all: MSYS/Git-Bash
# TRANSLATES a POSIX-looking value when passing an environment variable to a NATIVE
# Windows process. Exporting "/tmp/x/docs" arrived as
# "C:/Users/.../AppData/Local/Temp/x/docs", while the command text still said
# "/tmp/x/docs" -- so no path rule could ever match. The README tells users they may
# write roots as "C:\..." OR "/c/...", so this is a real installation, not a test-only
# concern. A byte stream on stdin is not translated.
emit_roots() {
  printf 'game\t%s\n'       "$X4_GAME"
  printf 'profile\t%s\n'    "$X4_PROFILE"
  printf 'reference\t%s\n'  "$X4_REFERENCE"
  printf 'toolkit\t%s\n'    "$X4_TOOLKIT"
  printf 'mods\t%s\n'       "$X4_MODS"
  printf 'documents\t%s\n'  "${X4_DOCUMENTS:-}"
  printf 'saves\t%s\n'      "${X4_SAVES:-}"
  printf -- '--X4-ROOTS-END--'
}

FACTS_RAW=$( { emit_roots; printf '%s' "$INPUT"; } | "$PY" "$HOOK_DIR/hook_facts.py" 2>/dev/null)
PARSE_RC=$?
if [ "$PARSE_RC" != 0 ]; then
  printf '%s' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"X4 GUARD INERT: the command analyser exited non-zero, so this command was NOT checked. That is the stdin defect one layer in: allowing silently would look identical to deciding it is fine. Confirm only if you know why."}}'
  exit 0
fi

# Split on the sentinel with parameter expansion -- no eval, no subprocess. The command
# is emitted LAST and raw because it may be multi-line (heredocs are routine here) and
# any escaping scheme would change what the messages below print.
SENT=$'\n__X4_COMMAND__\n'
FACT_LINES="${FACTS_RAW%%$SENT*}"
COMMAND="${FACTS_RAW#*$SENT}"
[ -z "$COMMAND" ] && exit 0

# Facts are matched against a NEWLINE-DELIMITED STRING, not an associative array.
#
# `declare -A` is bash 4+, and macOS ships bash 3.2 as /bin/bash. There the declare
# fails, `F[key]=v` becomes an ARITHMETIC index into an ordinary array, every predicate
# collapses into one slot, and the hook ALLOWS EVERYTHING while looking healthy -- a
# guard silently dead on an entire platform, which is the exact defect this file exists
# to prevent. Nothing here can catch that at runtime, because bash 3.2 cannot be run on
# the machine that wrote it, so scripts/test-hooks.sh carries a STATIC check instead.
#
# CRs are stripped first. hook_facts.py writes BYTES so none should arrive, but a CR is
# invisible and turns every "1" into "1\r"; the same trap is already recorded for jq.exe.
FACT_LINES="${FACT_LINES//$'\r'/}"
FACTS_NL="
$FACT_LINES
"
# on() KEY -> true when the parse pass says that predicate holds. Bounded by newlines on
# BOTH sides so a key cannot match a longer key's line, nor a value match a longer value.
on() {
  case "$FACTS_NL" in
    *"
$1	1
"*) return 0 ;;
  esac
  return 1
}

# The timeout value, for the message that quotes it back. Pure parameter expansion; the
# TAB after the name is what stops `timeout` matching `timeout_over_cap`.
_t="${FACTS_NL#*
timeout	}"
TIMEOUT_MS="${_t%%
*}"

# === HARD BLOCK — delete the game installation ===
# The target must be a real path in the tree, OR bear the game's name while not being
# an archive. MEASURED 2026-08-30: 7 of 8 refusals here were a .zip merely NAMED after
# the game in an unrelated folder -- the extension exclusion, not dropping the name
# test, is what removed those. The name test is also the ONLY protection an installer
# with no configured paths has, which is why it is here rather than only on the ask.
on rm_hits_game && deny "BLOCKED: cannot delete the X4 game installation directory."

# === HARD BLOCK — delete the reference folder (read-only base game data) ===
on rm_targets_reference && deny "BLOCKED: reference/ is the read-only unpacked base game data (re-unpack only via bin/unpack-reference.sh)."

# === HARD BLOCK — re-unpack into a locked reference/ ===
# Sentinel-gated: once reference/.unpacked-and-locked exists, block accidental re-unpacks.
# The FILESYSTEM test stays here; the parse pass never touches the disk.
if on xrcat_reunpack && [ -f "$X4_REFERENCE/.unpacked-and-locked" ]; then
  deny "BLOCKED: reference/ is locked (reference/.unpacked-and-locked exists). Re-unpacking would overwrite the read-only base. Remove the sentinel first if you really mean to re-unpack."
fi

# === CONFIRM — rm targeting the game, profile, reference, mods, or toolkit ===
on rm_in_x4_dir && ask "Deleting files in an X4 directory — confirm: $COMMAND"

# === CONFIRM - deleting a SAVE GAME ===
# Named separately from the rule above so the prompt says what is at risk. There is
# no undo and no backup: on the reference machine that is 25 files and 1.7 GB.
on rm_saves && ask "DELETING A SAVE GAME. Saves are not reproducible and nothing backs them up. Confirm: $COMMAND"

# === CONFIRM - deleting or overwriting anything else under Documents ===
# Game settings, other games' data, personal files. Not ours, not reproducible.
# MEASURED 2026-08-30: 193 of 196 hits were a command that merely NAMED a path there.
# This was the only rule left spending the USER's attention on a false positive, so it
# tests the write TARGET, not the whole string.
on writes_documents && ask "WRITING OR DELETING UNDER YOUR DOCUMENTS FOLDER: this is outside the toolkit and the game. Confirm: $COMMAND"

# === CONFIRM — mv/cp into the game or profile dirs ===
# MEASURED: 49 of 86 hits were a copy OUT of the game, or a mention. The DESTINATION
# decides -- including `mv -t <dir>` and a `tee` behind a wrapper, both of which the
# bash version missed because it required the verb to be the segment's first word.
on copy_into_game_or_profile \
  && advise "Copying into a game or profile directory. That is the documented DEPLOY path, so it is allowed -- but use dev/_tools/deploy.py rather than a hand-rolled cp: it refuses a wrong destination, deletes orphans one named file at a time, and re-reads the destination to prove every file is byte-identical."

# === CONFIRM — output redirect into game or profile dirs ===
# MEASURED 2026-08-30: 1,269 of 1,320 hits were `2>/dev/null` plus a game path mentioned
# anywhere -- 13.4% of every command in the corpus carrying a note about a write it was
# not making. Now the TRUNCATING redirect target must resolve under the tree. An append
# cannot truncate, so it is not this rule's business.
on redirect_truncate_into_game_or_profile \
  && advise "Redirecting output into a game or profile directory. Allowed, but a truncating > has no backup: if the target is a durable record, write to a temp file and move it into place."

# === CONFIRM — sed -i on game or profile files ===
on sed_i_in_game_or_profile && deny "In-place edit in game/profile directory — confirm: $COMMAND"

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
# MEASURED 2026-08-27: a second session had four untracked WIP files in the same tree
# (`_livecli.py`, `_livedump.py` + tests). They inflated the suite 836 -> 877 and
# `git add -A` would have committed someone else's half-finished work. It did not, but
# only by timing. Stage explicit paths instead.
#
# A heredoc BODY is data, not commands: this rule blocked the session's own work on the
# staging phrase appearing inside a payload being written.
on git_add_all && deny "GIT ADD -A / . IN A SHARED WORKSPACE: this stages EVERY untracked file, including another session's work-in-progress. MEASURED 2026-08-27: 4 untracked files from a concurrent session sat in this tree. Prefer explicit paths (git add <file> ...). Proceed?"


# === DURABLE RECORDS — a truncating write via Bash has NO backup and NO guard ===
# backup-before-edit.sh and protect-files.sh are wired to Edit|Write ONLY. A file edited
# through Bash (a `>` redirect, or python's open(p,"w")) gets neither. And open(p,"w")
# TRUNCATES AT OPEN, so an exception mid-write leaves the file EMPTY, not unchanged —
# the traceback looks like "nothing happened" while the content is gone.
# Measured 2026-08-22: that is exactly how a memory file was wiped to 0 bytes.
# Appends (`>>`) are deliberately NOT blocked — they cannot truncate.
if on durable_truncating_redirect; then
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
if on durable_python_open_w; then
  deny "python open(...,'w') in a command that names a durable record (memory / KNOWLEDGEBASE / CLAUDE.md / BLIND-SPOTS).
open() TRUNCATES AT OPEN — if the write then raises, the file is left EMPTY. This wiped a memory file on 2026-08-22.
Prefer the Edit/Write tools (backed up), or write to a temp and rename. If you proceed, VERIFY the size afterwards.
Command: $COMMAND"
fi

# === TOOL ROUTING — block recursive text search over the 60 GB reference tree ===
# Purpose-built tools answer these far faster and with a denominator. See CLAUDE.md
# "Discovery vs. Proof" routing table. This blocks the reflex, not the capability:
# a scoped grep at a specific subdirectory still works -- the SEARCH PATH must BE the
# root. rg and ag count with no flag at all: they recurse by default, which the
# flag-gated bash version missed entirely.
if on search_rooted_reference; then
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
# The profile content.xml keys EVERY entry by the mod's MANIFEST ID, never by folder
# name and never by display name. MEASURED 2026-08-23: of 123 on-disk mods, 60 match by
# manifest id and only 9 by folder name.
#
# The failure this catches actually happened, 2026-08-23: `grep -i xspvro` on the
# profile returned nothing -- because the entry is `ws_3691358137` -- and that zero was
# one keystroke from being written into permanent record as "xspvro has no ban record,
# so a Steam re-download would come back ENABLED". It would have destroyed a CORRECT
# memory and reported a real safety protection as absent.
if on profile_search_by_name; then
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

# --- `$?` read after a pipeline -------------------------------------------
# `cmd | head; echo $?` reports HEAD's exit code, not cmd's. This turned a
# stale-index refusal (real exit 5) into an apparent "exit 0" and was nearly
# filed as a tool defect. A pipe inside a process substitution runs in a subshell,
# so its status never becomes $? -- that exclusion is in the parse pass.
if on dollarq_after_pipe; then
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

# --- measurement output into shared /tmp ----------------------------------
# /tmp is shared across CONCURRENT sessions. Near-miss: 5 of 8 gate outputs
# read back were a parallel session's, 4 hours stale, and were nearly reported
# as this session's results. Reads and cleanup are fine; only writes fire.
if on write_to_tmp; then
  deny "WRITING MEASUREMENT OUTPUT TO /tmp — it is shared across concurrent sessions.
A parallel session's stale files were once nearly reported as this session's results.
Use the session scratchpad instead (see the 'Scratchpad Directory' section of the
system prompt), and never glob a pattern that can match another run's files.
Command: $COMMAND"
fi

# --- recursive search rooted AT the workspace / game root -----------------
# Distinct from the reference\ rule above, which only covers reference\.
# MEASURED 2026-08-22: `grep -rn` over the whole workspace root was killed at 300 s and
# the ripgrep tool timed out at 20 s -- tools\basex\basex\data\ alone was 3.7 GB of
# binary database pages. The path must BE the root, so a scoped search into any
# subdirectory is unaffected -- including `cd <root> && grep -rn x subdir/`, which this
# rule's own message recommends and which the bash version nonetheless blocked.
if on search_rooted_workspace; then
  deny "WRONG SCOPE: recursive text search rooted at the whole workspace / game root.
It does not finish — MEASURED 2026-08-22: grep -r killed at 300 s, ripgrep timed out at
20 s, because tools\\basex\\basex\\data\\ alone is GBs of binary database pages.
Name the directory you actually mean:
  tools\\x4validate  ·  dev  ·  tools\\basex (excluding basex/data)
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
if on timeout_over_cap; then
  deny "TIMEOUT ABOVE THE CAP: you passed ${TIMEOUT_MS}ms, but the Bash tool's maximum is 600000ms.
Larger values are silently clamped -- the command will be KILLED at exactly 10:00 (exit 143),
which looks like a hang and is not one.
Needing more than 10 minutes IS the signal to background it, not to raise the number:
  run_in_background: true      <- no cap; you are re-invoked when it finishes (do NOT poll)
Or split the work so no single foreground call approaches the cap."
fi

# --- a known LONG job in the foreground ------------------------------------
# Measured runtimes in this workspace: gates/corpus_sweep.py ~2100s,
# gates/perf_guard.py (and --record) ~600s+, build-effective.sh ~100-200s,
# `x4effective build` and build-corpus.sh minutes.
# MEASURED 2026-08-30: 125 of this rule's 144 hits merely NAMED a job rather than
# running one. It denied this session's own analysis script (the name sat inside a
# regex literal) and the write of the plan that proposed fixing it. Both the job name
# and an invoker must now appear in the SAME segment, with quoted strings blanked so a
# name inside a literal is a mention.
if on longjob_foreground; then
  deny "LONG JOB IN THE FOREGROUND — this is a known multi-minute command and the Bash
tool hard-caps a foreground call at 600000ms (10 min).
MEASURED: corpus_sweep ~2100s · perf_guard ~600s+ · build-effective.sh ~100-200s.
Prefer  run_in_background: true  — it has no cap and re-invokes you on completion.
Proceed in the foreground only if you have scoped it down (e.g. --limit=N).
Command: $COMMAND"
fi

exit 0

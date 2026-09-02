#!/bin/bash
# Smoke-test every safety hook by feeding it synthetic tool-call JSON and asserting the
# decision it returns. Run this after ANY change to .claude/hooks/.
#
#   bash scripts/test-hooks.sh
#
# Why this exists: the hooks are the toolkit's safety net, but nothing exercised them, so
# several were silently inert for entire releases — a `(?!\.claude)` PCRE lookahead that can
# never match under `grep -E` (game-install block), a hook anchored to one developer's folder
# (auto-validate), and auto-backups scattering into the cwd. All three passed code review and
# shipped. Assertions catch that; reading does not.
#
# Requires: bash, jq. Uses only temp dirs — touches nothing real.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS="$REPO/.claude/hooks"
command -v jq >/dev/null 2>&1 || { echo "jq is required"; exit 2; }

# The sandbox must NOT live under /tmp. One of the rules under test refuses writes into
# shared /tmp, so a sandbox rooted there makes every unrelated write probe trip it -- the
# probe for "an append cannot truncate" would fail for a reason that has nothing to do
# with appends. That went unnoticed until 2026-08-31 only because the /tmp rule's regex
# accepted a double quote and not a single one, and these probes quote with singles: the
# harness was passing because of a gap in the rule it was standing next to.
_SBX="${X4_TEST_SANDBOX:-$REPO/.test-sandbox}"
mkdir -p "$_SBX" || { echo "cannot create sandbox base $_SBX"; exit 2; }
TMP="$(mktemp -d "$_SBX/hooks.XXXXXX")"; trap 'rm -rf "$TMP"' EXIT
case "$TMP" in
  /tmp/*|/var/tmp/*) echo "REFUSING: sandbox landed under /tmp ($TMP); the shared-/tmp rule
       would fire on unrelated write probes and the failures would be misattributed."; exit 2 ;;
esac
pass=0; fail=0
ok(){ pass=$((pass+1)); printf '  OK   %s\n' "$1"; }
no(){ fail=$((fail+1)); printf '  FAIL %s\n' "$1"; }

# decide <expected> <hook> <json> <label>
decide(){
  local exp="$1" hook="$2" json="$3" label="$4" out got
  if ! printf '%s' "$json" | jq -e . >/dev/null 2>&1; then
    no "$label -- MALFORMED PROBE PAYLOAD: not valid JSON, so this probe exercises the
        parser-contract guard rather than its own rule"
    return
  fi
  out=$(printf '%s' "$json" | bash "$HOOKS/$hook" 2>/dev/null)
  if [ -z "$out" ]; then got="allow"
  else
    got=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // "allow"' 2>/dev/null)
    # An advisory is an allow that CARRIES A REASON FOR CLAUDE. Distinguishing the two
    # matters: "allow" and "advise" are the same decision and a different intent, and a
    # hook that silently stopped advising would otherwise still read as passing.
    if [ "$got" = "allow" ]        && [ -n "$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext // ""' 2>/dev/null)" ]; then
      got="advise"
    fi
  fi
  [ "$got" = "$exp" ] && ok "$label ($got)" || no "$label — expected $exp, got $got"
}
fj(){ printf '{"tool_name":"Edit","tool_input":{"file_path":%s}}' "$(printf '%s' "$1" | jq -Rs .)"; }
# jq -Rs does the JSON escaping. The first version interpolated the command RAW,
# so any probe containing a double quote emitted INVALID JSON -- and since the
# parser-contract guard landed, the hook correctly answers `ask` to that. A probe
# written with quotes was therefore testing the parser guard, not its own rule.
cj(){ printf '{"tool_name":"Bash","tool_input":{"command":%s}}' "$(printf '%s' "$1" | jq -Rs .)"; }
pj(){ printf '{"tool_name":"Grep","tool_input":{"pattern":"x","path":%s}}' "$(printf '%s' "$1" | jq -Rs .)"; }

run_layout(){ # run_layout <name> <toolkit> <game>
  local name="$1" TK="$2" GAME="$3"
  mkdir -p "$TK/.claude/hooks" "$TK/dev/mymod" "$TK/reference" "$GAME/extensions/deployed" \
           "$TMP/profile" "$TMP/mods/other"
  export X4_TOOLKIT="$TK" X4_GAME="$GAME" X4_REFERENCE="$TK/reference" \
         X4_PROFILE="$TMP/profile" X4_MODS="$TMP/mods" X4_EXTENSIONS="$GAME/extensions" \
         X4_CONFIG=/nonexistent CLAUDE_PROJECT_DIR="$TK" \
         X4_SAVES="$TMP/profile/save" X4_DOCUMENTS="$TMP/docs"
  mkdir -p "$TMP/profile/save" "$TMP/docs/My Games/SomeGame" "$TMP/docs/Other Game"
  echo; echo "=== protect-files.sh — $name layout ==="
  decide allow protect-files.sh "$(fj "$TK/dev/mymod/libraries/wares.xml")" "mod source in dev/"
  decide allow protect-files.sh "$(fj "$TMP/mods/other/wares.xml")"         "mod source in \$X4_MODS"
  decide allow protect-files.sh "$(fj "$TK/.claude/hooks/x.sh")"            "toolkit .claude/"
  decide allow protect-files.sh "$(fj "$TK/CLAUDE.md")"                     "CLAUDE.md"
  decide deny  protect-files.sh "$(fj "$TK/reference/libraries/wares.xml")" "reference/ is read-only"
  # A BACKSLASH path, which the harness could not carry until 2026-08-30: fj
  # interpolated raw, so a Windows path was invalid JSON (\U is not a valid
  # JSON escape) and the probe silently exercised the parser-contract guard.
  decide deny  protect-files.sh "$(fj "$(printf '%s' "$TK/reference/libraries/wares.xml" | tr / '\\')")" \
    "reference/ is read-only, named with BACKSLASHES"
  decide deny  protect-files.sh "$(fj "$GAME/01.cat")"                      ".cat archive"
  decide deny  protect-files.sh "$(fj "$GAME/01.dat")"                      ".dat archive"
  decide deny  protect-files.sh "$(fj "$GAME/libraries/wares.xml")"         "base game file"
  decide advise protect-files.sh "$(fj "$TK/dev/mymod/content.xml")"        "content.xml manifest"
  # The PROFILE's own content.xml is the mod enable/disable list and the Steam
  # Workshop toggle. Turning the manifest prompt into an advisory (2026-08-29)
  # nearly bypassed the profile confirmation for it: the advisory exits 0, so it
  # short-circuited a rule the user had explicitly kept. It must still ASK.
  decide ask   protect-files.sh "$(fj "$TMP/profile/content.xml")"          "profile content.xml still confirms"
  # ...and a DEPLOYED mod's manifest must still reach the extensions rule below the
  # advisory. MEASURED 2026-08-30 (F84): an advisory that exits makes every rule under
  # it unreachable, so this manifest was advised and never confirmed.
  decide deny  protect-files.sh "$(fj "$GAME/extensions/deployed/content.xml")"  "a deployed mod manifest reaches the deployed-copy rule"
  decide ask   protect-files.sh "$(fj "$TMP/profile/config.xml")"           "user profile file"
  # Saves, game settings and everything else under Documents (user request
  # 2026-08-30). MEASURED first: over 11,133 historical commands this fires on 7
  # MORE than the existing profile rules already did, and on zero more edits.
  decide ask   protect-files.sh "$(fj "$TMP/profile/save/save_001.xml.gz")"  "a save game"
  decide ask   protect-files.sh "$(fj "$TMP/docs/My Games/SomeGame/x.ini")"  "under My Games"
  # `.dat` is a GENERIC extension. The X4-archive rule denied another game's save
  # outright until it was scoped to X4 locations -- a guard blocking a file that was
  # never ours. It must ask here, and still deny inside the game folder.
  decide ask   protect-files.sh "$(fj "$TMP/docs/Other Game/saved.dat")"     "another game's .dat is not an X4 archive"
  decide deny  protect-files.sh "$(fj "$GAME/01.dat")"                       ".dat INSIDE the game still denies"
  # X4_MODS is outside $GAME in both layouts, so the source lives elsewhere -> hard block.
  decide deny  protect-files.sh "$(fj "$GAME/extensions/deployed/x.xml")"   "deployed extensions/ (source elsewhere)"
}

# The in-game layout is the interesting one: toolkit IS the game folder, so mod sources sit
# inside it and must not be caught by the game-installation block.
run_layout "in-game"  "$TMP/game/X4 Foundations" "$TMP/game/X4 Foundations"
run_layout "separate" "$TMP/sep/toolkit"         "$TMP/sep/X4 Foundations"

# The OTHER branch of the same rule, and it must be exercised or the deny above is the
# only reachable outcome and the ask is dead code. Mods living INSIDE the game folder is
# the common single-location setup: there is no separate source, so denying would block
# every normal edit.
echo; echo "=== protect-files.sh -- deployed edit when mods live INSIDE the game ==="
GAME="$TMP/game/X4 Foundations"
mkdir -p "$GAME/extensions/deployed"
# The hook runs as a CHILD process, so a bare `VAR=x decide ...` prefix does not reach
# it -- the values must be EXPORTED. That is why this saves and restores instead of
# using a subshell: `decide` increments the pass/fail counters, which a subshell would
# discard, and the run would go quiet again in a different way.
_sm="$X4_MODS"; _se="$X4_EXTENSIONS"; _sg="$X4_GAME"
# THREE reachable branches for a write under extensions/, one probe each -- otherwise
# the deny above is the only outcome ever exercised and the rest is dead code.
export X4_EXTENSIONS="$GAME/extensions" X4_GAME="$GAME"
#  (a) no mods root configured at all: nothing says where the source is, so CONFIRM.
unset X4_MODS
decide ask protect-files.sh "$(fj "$GAME/extensions/deployed/x.xml")" "deployed edit, no mods root configured"
#      ...and a MANIFEST must reach it too: the manifest advisory sits above this rule
#      and used to exit, so it never did (F84).
decide ask protect-files.sh "$(fj "$GAME/extensions/deployed/content.xml")" "a deployed manifest still confirms"
#  (b) mods root IS the extensions folder: the deployed copy IS the source, so this is
#      ordinary work and must not prompt at all.
export X4_MODS="$GAME/extensions"
decide allow protect-files.sh "$(fj "$GAME/extensions/deployed/x.xml")" "deployed edit IS the source"
export X4_MODS="$_sm" X4_EXTENSIONS="$_se" X4_GAME="$_sg"


# =============================================================================
# search-scope.sh -- a content search that returns a PARTIAL answer looking complete
# =============================================================================
# Grep and Glob read LOOSE files only. A mod that ships a .cat archive is invisible to
# them, so a zero result means "not in the loose subset", not "absent" -- in the same
# shape a complete answer would have. Measured on the reference machine: 54 of 133
# installed mods ship BOTH, so the misleading case is the common one.
echo; echo "=== search-scope.sh ==="
GAME="$TMP/game/X4 Foundations"
mkdir -p "$GAME/extensions/packedmod" "$GAME/extensions/loosemod/md" \n         "$X4_TOOLKIT/dev/mymod"
: > "$GAME/extensions/packedmod/ext_01.cat"
: > "$GAME/extensions/packedmod/readme.txt"
: > "$GAME/extensions/loosemod/md/a.xml"
export X4_EXTENSIONS="$GAME/extensions" X4_GAME="$GAME"
decide advise  search-scope.sh "$(pj "$GAME/extensions")"              "search rooted at extensions/"
decide advise  search-scope.sh "$(pj "$GAME/extensions/packedmod")"    "search inside a .cat-shipping mod"
# The must-NOT-fire half is not decoration: when this hook was first written a
# collapsed backslash made it inert, every must-fire probe went red and every
# must-NOT-fire probe went green. Silence is indistinguishable from allow, so the
# fire cases above are what give these their meaning.
decide allow search-scope.sh "$(pj "$GAME/extensions/loosemod")"     "loose-only mod is fully visible"
decide allow search-scope.sh "$(pj "$GAME/extensions/packedmod/readme.txt")" "a single FILE is not a survey"
decide allow search-scope.sh "$(pj "$X4_TOOLKIT/dev/mymod")"          "the mod workspace"
decide allow search-scope.sh '{"tool_name":"Grep","tool_input":{"pattern":"x"}}' "no path at all"

echo; echo "=== protect-bash.sh ==="
decide deny  protect-bash.sh "$(cj "rm -rf '$X4_GAME'")"      "rm the game directory"
# --- Block B: two rules measured ~97% GENUINE, but with the same FP shape -------
# Each blocked this session's own work on its trigger word inside a quoted fixture.
# Overriding a rule that measures as working needs its own evidence, so these are
# probed and committed separately from the six.
_GA2="git add ""-A"
decide deny  protect-bash.sh "$(cj "$_GA2")"   "staging everything still denies"
decide allow protect-bash.sh "$(cj "echo 'do not run $_GA2 here' >> notes.md")"   "the phrase inside a quoted string is a mention"
decide allow protect-bash.sh "$(cj "grep -n '$_GA2' scripts/test-hooks.sh")"   "searching for the phrase is a mention"
decide deny  protect-bash.sh "$(cj "grep -i xspvro '$X4_PROFILE/content.xml'")"   "searching the profile manifest by NAME still denies"
decide allow protect-bash.sh "$(cj "echo 'the profile content.xml is keyed by id' >> notes.md")"   "describing the manifest is not searching it"
# A HEREDOC BODY IS DATA, NOT COMMANDS. Both rules blocked this session's own work on
# text inside one -- a script whose payload happened to contain the phrase at a command
# position, and one that merely mentioned a search, the profile var and the word content.
# The `$?` rule already strips heredoc bodies; both now use the same helper.
decide allow protect-bash.sh "$(cj "python - <<'PY'
s = \"cd x && git add -A > log\"
PY")"   "the staging phrase inside a heredoc body is data"
decide allow protect-bash.sh "$(cj "python - <<'PY'
guard = 'grep -qiE content.xml against \$X4_PROFILE'
PY")"   "a manifest search described inside a heredoc body is data"
decide deny  protect-bash.sh "$(cj "rm -rf '$X4_REFERENCE'")" "rm reference/"
decide ask   protect-bash.sh "$(cj "rm -f '$TMP/profile/save/save_001.xml.gz'")" "deleting a save game"
decide ask   protect-bash.sh "$(cj "echo x > '$TMP/docs/notes.txt'")"            "writing into Documents"
# ...but only when Documents is the TARGET. MEASURED 2026-08-30: 193 of 196 hits
# were a command that merely NAMED a path there -- `(rm|mv|cp|tee|>) anywhere` AND
# `a Documents path anywhere`, two independent tests over the whole string. This is
# the only rule left that spends the USER's attention on a false positive.
decide allow protect-bash.sh "$(cj "P='$TMP/docs/Egosoft'; ls -la \"\$P\" 2>/dev/null")"   "reading a Documents path is not writing to it"
decide allow protect-bash.sh "$(cj "cp '$TMP/docs/notes.txt' '$TMP/copy.txt'")"   "copying OUT of Documents"
decide allow protect-bash.sh "$(cj "grep -n x '$TMP/docs/notes.txt' > '$TMP/out.txt'")"   "reading from Documents, writing elsewhere"
decide ask   protect-bash.sh "$(cj "cp '$TMP/a.txt' '$TMP/docs/b.txt'")"   "copying INTO Documents"
decide ask   protect-bash.sh "$(cj "rm -f '$TMP/docs/notes.txt'")"   "deleting inside Documents"
decide ask   protect-bash.sh "$(cj "tee '$TMP/docs/log.txt' < '$TMP/a.txt'")"   "tee INTO Documents"
decide ask   protect-bash.sh "$(cj "D='$TMP/docs'; echo x > \"\$D/n.txt\"")"   "a variable Documents destination still confirms"
decide ask   protect-bash.sh "$(cj "rm -rf '$X4_MODS/other'")" "rm inside mod sources"
# --- rule 2: the redirect advisory must test the TARGET, not the whole string ----
# MEASURED 2026-08-30: 1,269 of its 1,320 hits were `2>/dev/null` plus a game path
# mentioned anywhere -- 13.4% of every command in the corpus carrying a spurious note.
decide allow protect-bash.sh "$(cj "find '$X4_GAME/extensions' -maxdepth 2 -type d 2>/dev/null")"   "stderr suppression is not a write into the game"
decide allow protect-bash.sh "$(cj "cat '$X4_GAME/CLAUDE.md' > '$TMP/copy.md'")"   "reading from the game, writing elsewhere"
decide advise protect-bash.sh "$(cj "echo x > '$X4_GAME/notes.txt'")"   "a truncating write into the game still advises"
decide allow protect-bash.sh "$(cj "echo x >> '$X4_GAME/notes.txt'")"   "an APPEND cannot truncate, so it does not advise"
# --- rule 6: cp/mv must test the DESTINATION -----------------------------------
# MEASURED: 49 of 86 hits were a copy OUT of the game, or a mention.
decide advise protect-bash.sh "$(cj "cp -r '$TMP/mods/other' '$X4_GAME/extensions/other'")"   "a deploy INTO the game still advises"
decide allow protect-bash.sh "$(cj "cp '$X4_GAME/CLAUDE.md' '$TMP/backup.md'")"   "copying OUT of the game is not a deploy"
# --- rule 7: the game-delete backstop must name the install ROOT ---------------
# MEASURED: 7 of 8 hits were a .zip merely NAMED after the game, in another folder.
decide allow protect-bash.sh "$(cj "rm -f '$TMP/X4 Foundations Toolkit v1.zip'")"   "a zip named after the game is a file, not the install"
decide deny  protect-bash.sh "$(cj "rm -rf '$X4_GAME'")"   "deleting the install itself still denies"
# The BOUNDARY of the hard block, probed on both sides. It used to cover anything UNDER
# the game folder. MEASURED 2026-08-31 over a 1,000-command replay of real history: all 4
# hits of the rule were `rm -rf "$DST"` with DST resolving to extensions/<one mod> -- the
# documented deploy path, which deploy.py performs itself. It only started firing there
# because variable resolution got BETTER; the predicate was never edited.
#
# The original objection to narrowing was that `rm -rf <game>/extensions` would fall
# through to a confirmation. It does not: extensions/ WHOLESALE is still a hard block.
# Only a path INSIDE it falls to the confirm, which is the verdict CLAUDE.md assigns to
# deleting in an X4 directory, and it is recoverable by redeploying from dev/.
decide deny  protect-bash.sh "$(cj "rm -rf '$X4_GAME/extensions'")"   "extensions/ WHOLESALE is still a hard block"
decide ask   protect-bash.sh "$(cj "rm -rf '$X4_GAME/extensions/deployed'")"   "ONE deployed mod confirms, it is not a hard block"
decide ask   protect-bash.sh "$(cj "rm -f '$X4_GAME/extensions/deployed/ext_01.cat'")"   "one file inside a deployed mod confirms"
# ...and with the destination in a VARIABLE, which is the form that exposed this and the
# form no probe used before.
decide ask   protect-bash.sh "$(cj "DST='$X4_GAME/extensions/deployed'; rm -rf \"\$DST\"")"   "a variable deploy destination confirms, not blocks"
# --- rule 3: the long-job rule must see an INVOCATION, not a mention -----------
# MEASURED 2026-08-30: 125 of its 144 hits merely NAMED a job. It denied this session's
# own analysis script (the name sat in a regex literal) and the write of the PLAN that
# proposed fixing it -- a plan file being the purest possible mention-not-invocation.
_J="corpus_sweep"
decide deny  protect-bash.sh "$(cj "uv run python gates/$_J.py")"   "invoking a long job in the foreground still denies"
decide allow protect-bash.sh "$(cj "python -c \"print('$_J')\"")"   "the job name inside a quoted string is a mention"
decide allow protect-bash.sh "$(cj "grep -n $_J gates/README.md")"   "searching for the job name is a mention"
decide allow protect-bash.sh "$(cj "echo 'see gates/$_J.py for details' >> notes.md")"   "writing the name into a document is a mention"
decide advise protect-bash.sh "$(cj "G='$X4_GAME'; echo x > \"\$G/notes.txt\"")"   "a variable game destination still advises"
# The FALSE POSITIVES these rules produced the moment they first ran (2026-08-29).
# Until this week no rule in protect-bash.sh had ever executed in production, so
# none of their false-positive rates were known. The delete rules tested 'an rm
# appears SOMEWHERE' AND 'the game path appears SOMEWHERE' as two independent
# checks over the whole command -- so deleting a temp file was blocked because the
# command also mentioned the game directory in a variable. They now test only the
# segments that actually invoke a delete.
decide allow protect-bash.sh "$(cj "L='$X4_GAME/.claude'; rm -f /tmp/scratch.log")" "temp delete, game dir in a variable"
decide allow protect-bash.sh "$(cj "echo 'working on $X4_GAME'; rm -f /tmp/x")"      "temp delete, game dir in an echo"

# --- shared /tmp: the rule had NO probe, and its regex accepted only a DOUBLE quote ---
# So a single-quoted target slipped past, and the hook suite's own sandbox depended on
# that gap. Both quote styles are asserted here so closing it cannot silently reopen.
decide deny  protect-bash.sh "$(cj 'uv run x4validate > "/tmp/out.log"')"  "measurement output to /tmp, double-quoted"
decide deny  protect-bash.sh "$(cj "uv run x4validate > '/tmp/out.log'")"  "measurement output to /tmp, SINGLE-quoted"
decide deny  protect-bash.sh "$(cj 'uv run x4validate > /tmp/out.log')"    "measurement output to /tmp, unquoted"
# Reads and cleanup are fine; only writes fire. Without these the rule could be widened
# to "mentions /tmp" and nothing would notice.
decide allow protect-bash.sh "$(cj 'cat /tmp/out.log')"                    "READING from /tmp is fine"
decide allow protect-bash.sh "$(cj 'ls -la /tmp/')"                        "listing /tmp is fine"
decide allow protect-bash.sh "$(cj "ls -la '$X4_GAME/extensions'")"                 "no delete at all, game dir named"
decide deny  protect-bash.sh "$(cj "cd /tmp && rm -rf '$X4_GAME/extensions'")"     "delete of the game dir, chained"
decide allow  protect-bash.sh "$(cj "ls '$X4_GAME/01.cat'")"   "command naming a .cat"   # DROPPED: naming a .cat is harmless; protect-files.sh checks the TARGET
decide allow protect-bash.sh "$(cj "ls -la .")"               "harmless ls"
decide allow protect-bash.sh "$(cj "git status")"             "git status"

echo; echo "=== backup-before-edit.sh ==="
TK="$X4_TOOLKIT"; SUBJ="$TK/dev/mymod/libraries/wares.xml"
mkdir -p "$(dirname "$SUBJ")"; echo '<diff/>' > "$SUBJ"
printf '%s' "$(fj "$SUBJ")" | bash "$HOOKS/backup-before-edit.sh" >/dev/null 2>&1
[ "$(ls "$TK/.claude/backups/" 2>/dev/null | grep -c 'wares.xml')" -ge 1 ] \
  && ok "backup created" || no "no backup created"
grep -q "wares.xml" "$TK/.claude/backups/AUDIT_LOG.txt" 2>/dev/null \
  && ok "audit log appended" || no "no audit log entry"
# Must stay anchored to the toolkit even with CLAUDE_PROJECT_DIR unset.
mkdir -p "$TMP/elsewhere"
( unset CLAUDE_PROJECT_DIR X4_TOOLKIT; cd "$TMP/elsewhere" \
  && printf '%s' "$(fj "$SUBJ")" | bash "$HOOKS/backup-before-edit.sh" >/dev/null 2>&1 )
[ -d "$TMP/elsewhere/.claude/backups" ] \
  && no "backups scattered into the cwd when CLAUDE_PROJECT_DIR is unset" \
  || ok "backups stay anchored to the toolkit"

echo; echo "=== check-reference-version.sh ==="
printf '"AppState"\n{\n\t"buildid"\t\t"99999999"\n}\n' > "$TMP/acf"
echo "11111111" > "$TK/.claude/.reference-buildid"
X4_APPMANIFEST="$TMP/acf" bash "$HOOKS/check-reference-version.sh" 2>/dev/null \
  | grep -q "stale-reference" && ok "warns on build mismatch" || no "no stale-reference warning"
echo "99999999" > "$TK/.claude/.reference-buildid"
[ -z "$(X4_APPMANIFEST="$TMP/acf" bash "$HOOKS/check-reference-version.sh" 2>/dev/null)" ] \
  && ok "silent when builds match" || no "warned when builds match"

echo
# A probe line that fails to PARSE increments neither counter -- it vanishes, and the
# run still prints a cheerful total. That happened while adding the probe above: bash
# reported "n: command not found" and the suite still said "33 passed, 0 failed".
# So the total is asserted against a number that must be updated deliberately.
EXPECT=134

# =============================================================================
# PATH DIALECT -- a verdict must not depend on HOW the path was written
# =============================================================================
# MEASURED 2026-08-30: x4_norm is `tr 'A-Z\' 'a-z/'` -- lowercase and backslash to
# slash, and nothing else. So Git Bash's "/c/Users/..." and Windows' "C:/Users/..."
# never compare equal, and a rule rooted purely on a configured PATH misses one of
# the two dialects entirely. Rules carrying a NAME backstop (the game, the profile)
# survived; Documents, reference/ and the workspace root did not.
# 2,553 historical commands use the MSYS form. No probe in this suite had ever used
# a drive-lettered root at all, so nothing here could have caught it.
echo; echo "=== path dialect ==="
_sd="$X4_DOCUMENTS"; _sr="$X4_REFERENCE"
export X4_DOCUMENTS="C:/fixture/Documents"
decide ask   protect-bash.sh "$(cj 'echo x > "C:/fixture/Documents/n.txt"')"   "Documents write, root Windows / command Windows"
decide ask   protect-bash.sh "$(cj 'echo x > "/c/fixture/Documents/n.txt"')"   "Documents write, root Windows / command MSYS"
export X4_DOCUMENTS="/c/fixture/Documents"
decide ask   protect-bash.sh "$(cj 'echo x > "C:/fixture/Documents/n.txt"')"   "Documents write, root MSYS / command Windows"
decide allow protect-bash.sh "$(cj 'echo x > "C:/elsewhere/n.txt"')"   "an unrelated path is still allowed in either dialect"
export X4_DOCUMENTS="$_sd"
export X4_REFERENCE="C:/fixture/reference"
decide deny  protect-bash.sh "$(cj 'grep -rn foo "/c/fixture/reference"')"   "recursive search at reference root, MSYS form"
# --- rules 4 and 5: a search rule must test the SEARCH PATH, not the whole string
# MEASURED 2026-08-30: 67 of 80 reference refusals and 12 of 20 workspace refusals were a
# search SCOPED to a subdirectory, or not recursive at all. The reference rule's own
# comment already promised a scoped search would be allowed; it never was.
decide allow protect-bash.sh "$(cj 'grep -rn foo "C:/fixture/reference/aiscripts"')"   "a subdirectory-scoped search is allowed, as its own message promises"
decide allow protect-bash.sh "$(cj 'cd "C:/fixture/reference" && grep -rn foo aiscripts/')"   "cd to the root, then scope to a subdirectory"
decide allow protect-bash.sh "$(cj 'cd "C:/fixture/reference" && grep -n foo one.xml')"   "a NON-recursive search is not this rule"
decide deny  protect-bash.sh "$(cj 'cd "C:/fixture/reference" && grep -rn foo .')"   "cd to the root then search dot still denies"
export X4_REFERENCE="$_sr"

# =============================================================================
# THE STDIN CONTRACT -- a hook that receives NOTHING must not read as ALLOW
# =============================================================================
# MEASURED 2026-08-29, and it had made every hook here inert: `cat /dev/stdin`
# returns ZERO BYTES in the Claude Code hook environment while a bare `cat`
# returns the payload (7 of 7 probes: 0 vs 641-2840 bytes). The failure is
# invisible by construction -- a hook that reads nothing falls through its first
# guard clause and exits 0, which is byte-identical to deciding "this is fine".
#
# THIS SUITE PASSED THROUGHOUT, because it pipes stdin explicitly and /dev/stdin
# resolves fine that way. So the probes below deliberately close stdin instead:
# they reproduce the PRODUCTION condition, which piping never can.
echo; echo "=== stdin contract ==="
for h in protect-bash.sh protect-files.sh search-scope.sh backup-before-edit.sh; do
  out=$(bash "$HOOKS/$h" </dev/null 2>/dev/null)
  got=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // "allow"' 2>/dev/null)
  [ -z "$got" ] && got="allow"
  if [ "$got" = "ask" ]; then ok "$h asks when it received no input"
  else no "$h -- empty stdin read as '$got'; silence IS allow"; fi
done
# ...and the refusal itself must not depend on the tool that may have failed.
# MEASURED 2026-08-30: x4_require_input emitted its `ask` THROUGH jq, so with jq
# unavailable an empty payload was reported by nothing at all -- allow again.
for h in protect-bash.sh protect-files.sh search-scope.sh backup-before-edit.sh; do
  out=$(JQ=no_such_jq_binary bash "$HOOKS/$h" </dev/null 2>/dev/null)
  got=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // "allow"' 2>/dev/null)
  [ -z "$got" ] && got="allow"
  if [ "$got" = "ask" ]; then ok "$h asks on empty input even with jq unavailable"
  else no "$h -- empty input + broken jq read as '$got'; the refusal ran through the broken tool"; fi
done
# The static half. A runtime probe only covers the hooks it lists; this covers any
# hook, including one added later, and it is the cheaper of the two to keep true.
if grep -nE '^[^#]*cat /dev/stdin' "$HOOKS"/*.sh >/dev/null 2>&1; then
  no "a hook reads 'cat /dev/stdin' again -- that returns EMPTY in the real hook environment"
else
  ok "no hook reads 'cat /dev/stdin'"
fi

# A hook whose PARSER fails must not read as ALLOW either. MEASURED 2026-08-30
# (code-review probe): with JQ pointing at a missing binary, protect-bash.sh
# exited 0 with EMPTY stdout -- the jq call failed, $COMMAND came back empty, and
# `[ -z "$COMMAND" ] && exit 0` treated "could not parse" as "nothing to check".
# Same shape as the stdin contract, one layer in.
AP=$(printf '\047')
Q=$(printf '\042')
# ONE backslash. `printf '\\\\'` emits TWO (single quotes keep both pairs) and the
# probe below then builds a validly-escaped command instead of a malformed one --
# which is how this case silently passed as 'allow' while claiming to test a refusal.
BSL=$(printf '\\')
X4_GAME_BS="${X4_GAME//\//\\}"
echo; echo "=== the command must PARSE, and bash is the judge ==="
# A guard whose helpers are all quote-aware fails OPEN on one unbalanced quote: the rest
# of the command reads as quoted text, no rule sees it, and every rule returns false --
# which is indistinguishable from "this is fine". MEASURED 2026-09-01 against c400a05:
# one apostrophe in an English comment turned 5 of 5 refusals into a silent allow.
#
# The hand-rolled scanner that first fixed it was wrong BOTH ways over 13,203 real
# commands -- 13 false positives (command substitution inside double quotes resets the
# quoting context) and 6 false negatives. `bash -n` parses, executes nothing, costs
# ~14 ms, and needs no dependency this hook does not already have.
#
# The four ALLOW cases are the ones the hand-rolled version got wrong; they are the
# point of the exercise, not padding.
decide allow protect-bash.sh "$(cj "echo hello")"                      "a balanced command parses"
decide allow protect-bash.sh "$(cj "# it${AP}s fine
echo hi")"                                                             "an apostrophe in a COMMENT is prose, not a quote"
decide allow protect-bash.sh "$(cj "cat > f <<${AP}X${AP}
it${AP}s data
X")"                                                                   "an apostrophe in a HEREDOC BODY is prose"
decide allow protect-bash.sh "$(cj "echo ${Q}a \$(grep -o ${AP}x|y${AP} f) b${Q}")"   "nested quotes inside \$( ) still parse"
decide ask   protect-bash.sh "$(cj "echo ${AP}unterminated")"          "a genuinely unbalanced quote is REFUSED, not ignored"
decide ask   protect-bash.sh "$(cj "ls ${Q}C:${BSL}Users${BSL}x${BSL}${Q} 2>/dev/null")"  "a Windows path ending in a backslash is REFUSED"

# The most natural way a Windows user writes a path must still reach every rule: inside
# double quotes bash keeps a backslash literal unless it precedes $ ` " \ or newline.
# Unescaping unconditionally deleted the separators, so the game-delete HARD BLOCK fired
# NOTHING on a backslash path -- c400a05 denied it, the parse pass allowed it.
decide deny  protect-bash.sh "$(cj "rm -rf ${Q}${X4_GAME_BS}${Q}")"    "a BACKSLASH game path still hits the hard block"

echo; echo "=== parser contract ==="
# --- STATIC: no personal identifier may reach a tracked file -----------------
# This repo already SHIPPED scripts/scan-identifiers.py and it was never wired to
# anything, so nothing made it run. MEASURED 2026-08-31: a hook test fixture carried the
# author's Windows username in four paths plus their 8-digit game-profile id, committed
# (never pushed). Fed the pre-fix content the scanner fires on all four lines -- so the
# guard was correct the whole time and the only gap was that running it depended on
# remembering to. That is the third instance in one day of a correct tool going unrun.
#
# Its own selftest runs first: a scan that cannot be shown to fail is not evidence that
# the tree is clean, it is evidence that something printed the word "clean".
if python "$REPO/scripts/scan-identifiers.py" --selftest >/dev/null 2>&1; then
  ok "the identifier scanner's own selftest passes"
else no "scan-identifiers.py --selftest FAILED; its verdict on the tree means nothing"; fi
if python "$REPO/scripts/scan-identifiers.py" >/dev/null 2>&1; then
  ok "no personal identifier in any tracked file"
else no "a personal identifier reached a tracked file -- run scripts/scan-identifiers.py"; fi

# --- STATIC: no hook may use a bash-4-only feature ---------------------------
# macOS ships bash 3.2 as /bin/bash. `declare -A` there is not a syntax error that stops
# the script -- it fails, then `F[key]=v` becomes an ARITHMETIC index into an ordinary
# array, every predicate collapses into one slot, and the hook ALLOWS EVERYTHING while
# looking healthy. This machine cannot run bash 3.2, so a runtime probe is impossible and
# a static check is the only reachable one. Comments are excluded so the entry
# explaining the trap does not trip it.
_b4=$(grep -nE '^[^#]*(declare[[:space:]]+-A|\$\{[A-Za-z_][A-Za-z0-9_]*(,,|\^\^)\}|mapfile|readarray)' \
        "$HOOKS"/*.sh 2>/dev/null)
if [ -z "$_b4" ]; then ok "no hook uses a bash-4-only feature (macOS /bin/bash is 3.2)"
else no "a hook uses a bash-4-only feature -- on macOS the guard would die SILENTLY: $_b4"; fi

# CONTRACT CHANGED, and it is now STRONGER. protect-bash.sh no longer PARSES with jq --
# hook_facts.py does that -- so jq is only the EMITTER. That made a broken jq far more
# dangerous than before: every deny became empty stdout, which the client reads as
# ALLOW. So there is now a Python emitter fallback, and the assertion is that a broken
# jq still produces the CORRECT VERDICT rather than degrading to a prompt.
# The probe also needs a command that actually triggers a rule: the old one used a
# delete of "/" which matches no configured root, so it could only ever have tested the
# refusal path, never the verdict path.
out=$(printf '%s' "$(cj 'git add -A')" | JQ=no_such_jq_binary bash "$HOOKS/protect-bash.sh" 2>/dev/null)
got=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // "allow"' 2>/dev/null)
[ -z "$got" ] && got="allow"
if [ "$got" = "deny" ]; then ok "a broken jq still emits the verdict (python fallback)"
else no "protect-bash.sh -- with jq broken the deny came out as '$got'; silence IS allow"; fi

# And a missing PYTHON must ASK: the parse pass is the only thing that inspects the
# command now, so without it the hook has checked nothing at all.
# X4_PYTHON points at a binary that does NOT run. Emptying PATH instead would break
# `dirname` and `cat` as well, so the hook would fail before reaching the python check
# and the probe would be testing nothing -- a green with no reachable failure branch.
out=$(printf '%s' "$(cj 'git add -A')" | X4_PYTHON="$TMP/no_such_python" bash "$HOOKS/protect-bash.sh" 2>/dev/null)
got=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // "allow"' 2>/dev/null)
[ -z "$got" ] && got="allow"
if [ "$got" = "ask" ]; then ok "protect-bash.sh asks when no Python is available"
else no "protect-bash.sh -- with no Python the command read as '$got'; unchecked IS allow"; fi

# =============================================================================
# AN ADVISORY MUST NOT SUPPRESS A LATER REFUSAL
# =============================================================================
# An `advise` is an ALLOW that carries a note; a `deny` is a refusal. Emitting the
# note and EXITING made every rule below the advisory unreachable.
# MEASURED 2026-08-30 by neutralising the six advisory/ask rules and replaying the
# 1,846 commands they catch: 298 are refused by a rule further down -- 130
# TIMEOUT-above-the-cap, 64 /tmp, 35 durable open(,'w'), 27 dollar-question-mark
# after a pipeline, 26 profile-content.xml-by-name, 11 stage-everything. Each was
# measured GENUINE, and each was silently suppressed by a note.
echo; echo "=== an advisory never masks a later verdict ==="
_GA="git ""add -A"
decide deny   protect-bash.sh "$(cj "cd $GAME && $_GA > $GAME/build.log")"   "a redirect advisory does not hide the stage-everything refusal"
decide deny   protect-bash.sh "$(cj "grep -rn foo $X4_REFERENCE > $GAME/out.txt")"   "a redirect advisory does not hide the reference-tree refusal"
# NB the fixture roots live under /tmp, so a redirect INTO the fixture game dir is
# also a write to /tmp and is refused for that -- correctly. These two use a
# relative redirect target so the advisories can be observed in isolation.
decide advise protect-bash.sh "$(cj "cp a '$GAME/b'")"   "one advisory still advises"
decide advise protect-bash.sh "$(cj "cp a '$GAME/b' > log.txt")"   "two advisories still advise"
# ...and BOTH texts must survive into the single note, not just the last one.
# Uses a FAKE game root outside /tmp: the fixture roots live under /tmp, so a real
# redirect into the fixture game dir is also a shared-/tmp write and is refused for
# that instead -- correctly, but it would stop this probe reaching the advisories.
_sg2="$X4_GAME"; export X4_GAME="C:/fixture/game"
_out=$(printf '%s' "$(cj 'cp a "C:/fixture/game/b" > "C:/fixture/game/log.txt"')" | bash "$HOOKS/protect-bash.sh" 2>/dev/null)
_n=$(printf '%s' "$_out" | jq -r '.hookSpecificOutput.additionalContext // ""' | grep -c .)
if [ "$_n" = "2" ]; then ok "both advisories are carried in ONE note"
else no "advisory accumulation -- expected 2 lines in additionalContext, got $_n"; fi
export X4_GAME="$_sg2"
decide deny   protect-bash.sh "$(cj "rm -rf '$GAME'")"   "a hard block still wins over everything"

echo "RESULT: $pass passed, $fail failed"
if [ $((pass + fail)) -ne "$EXPECT" ]; then
  echo "FAIL: $((pass + fail)) probes ran, expected $EXPECT -- a probe was DROPPED, not passed."
  echo "      (If you added or removed one deliberately, update EXPECT.)"
  exit 1
fi
[ "$fail" -eq 0 ]

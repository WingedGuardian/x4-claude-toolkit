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

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
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
EXPECT=95

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
echo; echo "=== parser contract ==="
out=$(printf '%s' "$(cj 'rm -rf /')" | JQ=no_such_jq_binary bash "$HOOKS/protect-bash.sh" 2>/dev/null)
got=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // "allow"' 2>/dev/null)
[ -z "$got" ] && got="allow"
if [ "$got" = "ask" ]; then ok "protect-bash.sh asks when its jq parse fails"
else no "protect-bash.sh -- a FAILED jq parse read as '$got'; an unparsed command IS allow"; fi

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
decide advise protect-bash.sh "$(cj "cp $GAME/a b")"   "one advisory still advises"
decide advise protect-bash.sh "$(cj "cp $GAME/a b > log.txt")"   "two advisories still advise"
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
decide deny   protect-bash.sh "$(cj "rm -rf $GAME")"   "a hard block still wins over everything"

echo "RESULT: $pass passed, $fail failed"
if [ $((pass + fail)) -ne "$EXPECT" ]; then
  echo "FAIL: $((pass + fail)) probes ran, expected $EXPECT -- a probe was DROPPED, not passed."
  echo "      (If you added or removed one deliberately, update EXPECT.)"
  exit 1
fi
[ "$fail" -eq 0 ]

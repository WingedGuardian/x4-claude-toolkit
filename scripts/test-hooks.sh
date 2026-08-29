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
  out=$(printf '%s' "$json" | bash "$HOOKS/$hook" 2>/dev/null)
  if [ -z "$out" ]; then got="allow"
  else got=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // "allow"' 2>/dev/null); fi
  [ "$got" = "$exp" ] && ok "$label ($got)" || no "$label — expected $exp, got $got"
}
fj(){ printf '{"tool_name":"Edit","tool_input":{"file_path":"%s"}}' "$1"; }
cj(){ printf '{"tool_name":"Bash","tool_input":{"command":"%s"}}' "$1"; }

run_layout(){ # run_layout <name> <toolkit> <game>
  local name="$1" TK="$2" GAME="$3"
  mkdir -p "$TK/.claude/hooks" "$TK/dev/mymod" "$TK/reference" "$GAME/extensions/deployed" \
           "$TMP/profile" "$TMP/mods/other"
  export X4_TOOLKIT="$TK" X4_GAME="$GAME" X4_REFERENCE="$TK/reference" \
         X4_PROFILE="$TMP/profile" X4_MODS="$TMP/mods" X4_EXTENSIONS="$GAME/extensions" \
         X4_CONFIG=/nonexistent CLAUDE_PROJECT_DIR="$TK"
  echo; echo "=== protect-files.sh — $name layout ==="
  decide allow protect-files.sh "$(fj "$TK/dev/mymod/libraries/wares.xml")" "mod source in dev/"
  decide allow protect-files.sh "$(fj "$TMP/mods/other/wares.xml")"         "mod source in \$X4_MODS"
  decide allow protect-files.sh "$(fj "$TK/.claude/hooks/x.sh")"            "toolkit .claude/"
  decide allow protect-files.sh "$(fj "$TK/CLAUDE.md")"                     "CLAUDE.md"
  decide deny  protect-files.sh "$(fj "$TK/reference/libraries/wares.xml")" "reference/ is read-only"
  decide deny  protect-files.sh "$(fj "$GAME/01.cat")"                      ".cat archive"
  decide deny  protect-files.sh "$(fj "$GAME/01.dat")"                      ".dat archive"
  decide deny  protect-files.sh "$(fj "$GAME/libraries/wares.xml")"         "base game file"
  decide ask   protect-files.sh "$(fj "$TK/dev/mymod/content.xml")"         "content.xml manifest"
  decide ask   protect-files.sh "$(fj "$TMP/profile/config.xml")"           "user profile file"
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
#  (b) mods root IS the extensions folder: the deployed copy IS the source, so this is
#      ordinary work and must not prompt at all.
export X4_MODS="$GAME/extensions"
decide allow protect-files.sh "$(fj "$GAME/extensions/deployed/x.xml")" "deployed edit IS the source"
export X4_MODS="$_sm" X4_EXTENSIONS="$_se" X4_GAME="$_sg"

echo; echo "=== protect-bash.sh ==="
decide deny  protect-bash.sh "$(cj "rm -rf '$X4_GAME'")"      "rm the game directory"
decide deny  protect-bash.sh "$(cj "rm -rf '$X4_REFERENCE'")" "rm reference/"
decide ask   protect-bash.sh "$(cj "rm -rf '$X4_MODS/other'")" "rm inside mod sources"
decide ask   protect-bash.sh "$(cj "ls '$X4_GAME/01.cat'")"   "command naming a .cat"
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
EXPECT=35
echo "RESULT: $pass passed, $fail failed"
if [ $((pass + fail)) -ne "$EXPECT" ]; then
  echo "FAIL: $((pass + fail)) probes ran, expected $EXPECT -- a probe was DROPPED, not passed."
  echo "      (If you added or removed one deliberately, update EXPECT.)"
  exit 1
fi
[ "$fail" -eq 0 ]

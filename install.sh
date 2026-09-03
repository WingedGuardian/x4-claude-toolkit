#!/usr/bin/env bash
# X4 Claude Toolkit installer — Linux / macOS / Windows (Git Bash).
# Three install methods, all with fully configurable paths (nothing hardcoded):
#
#   in-game   Copy the toolkit INTO your X4 game folder (the upstream model). One workspace.
#   separate  Keep the toolkit in its OWN folder, pointed at the game via config.
#   global    Install the skills/agents into ~/.claude and write the X4_* paths into your
#             global Claude settings, so they work across MANY mod repos (multi-project).
#
# Every location is auto-detected where possible and overridable by flag/env. The chosen
# paths are written to <toolkit>/.claude/x4-paths.env (the single source of truth the hooks
# and bin/ scripts read).
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # repo / toolkit source

# --- defaults (overridable by flags / env) ---------------------------------
METHOD=""; ASSUME_YES=0; DO_UNPACK=0; OVER_EXISTING=0; DRY_RUN=0
#: Did a HUMAN name the destination, or did we find it by scanning? Recorded at
#: parse time: an env var is a deliberate act, a Steam-folder scan is not.
GAME_NAMED=$([ -n "${X4_GAME:-}" ] && echo named || echo detected)
TOOLKIT_NAMED=$([ -n "${X4_TOOLKIT:-}" ] && echo named || echo detected)
GAME="${X4_GAME:-}"; PROFILE="${X4_PROFILE:-}"; TOOLKIT="${X4_TOOLKIT:-}"
MODS="${X4_MODS:-}"; REFERENCE="${X4_REFERENCE:-}"; EXTENSIONS="${X4_EXTENSIONS:-}"
XRCAT="${XRCATTOOL:-}"

usage() {
  # The comment block ends at line 12. '2,16p' printed four lines of live shell
  # source into the middle of the help text.
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'USAGE'

Usage: bash install.sh --method in-game|separate|global [options]
  --game DIR         X4 install (folder with 01.cat..09.cat)   [auto-detected]
  --profile DIR      user profile (saves/config/debug log)     [auto-detected]
  --toolkit DIR      where the toolkit lives (separate/global) [repo dir / game dir]
  --mods DIR         your mod source repos root
  --reference DIR    unpacked base game (default <toolkit>/reference)
  --extensions DIR   live deploy target (default <game>/extensions)
  --xrcattool PATH   XRCatTool.exe location
  --unpack           also unpack reference/ now (needs --game + XRCatTool [+wine])
  --over-existing    REQUIRED to install over an existing installation
  --dry-run          print the destination and the item list; write nothing
  --yes              don't prompt; accept detected/blank values (never a
                     detected DESTINATION -- name that with --game/--toolkit)
  -h, --help         this help
USAGE
}

# Every value-taking flag goes through need2 first. Under `set -u` a bare `--game`
# died with "install.sh: line 44: $2: unbound variable" -- a bash-internal diagnostic
# naming a line number, with no usage hint. install.ps1 gets this free from param().
need2() {
  [ "$2" -ge 2 ] || { echo "ERROR: $1 requires a value" >&2; echo >&2; usage >&2; exit 2; }
}

while [ $# -gt 0 ]; do
  case "$1" in
    --method) need2 "$1" $#; METHOD="$2"; shift 2;;
    --game) need2 "$1" $#; GAME="$2"; GAME_NAMED=named; shift 2;;
    --profile) need2 "$1" $#; PROFILE="$2"; shift 2;;
    --toolkit) need2 "$1" $#; TOOLKIT="$2"; TOOLKIT_NAMED=named; shift 2;;
    --mods) need2 "$1" $#; MODS="$2"; shift 2;;
    --reference) need2 "$1" $#; REFERENCE="$2"; shift 2;;
    --extensions) need2 "$1" $#; EXTENSIONS="$2"; shift 2;;
    --xrcattool) need2 "$1" $#; XRCAT="$2"; shift 2;;
    --over-existing) OVER_EXISTING=1; shift;;
    --dry-run) DRY_RUN=1; shift;;
    --unpack) DO_UNPACK=1; shift;;
    --yes|-y) ASSUME_YES=1; shift;;
    -h|--help) usage; exit 0;;
    *) echo "unknown option: $1" >&2; usage; exit 2;;
  esac
done

case "$(uname -s 2>/dev/null)" in
  Linux*) OS=linux;; Darwin*) OS=macos;; MINGW*|MSYS*|CYGWIN*|Windows*) OS=windows;; *) OS=unknown;;
esac
echo "X4 Claude Toolkit installer — OS: $OS, source: $SRC"

# --- helpers ---------------------------------------------------------------
ask() {  # ask VAR "prompt" "default"
  local cur="${!1}" def="$3"
  [ -n "$cur" ] && def="$cur"
  if [ "$ASSUME_YES" = 1 ]; then printf -v "$1" '%s' "$def"; return; fi
  local ans; read -r -p "$2 [${def:-blank}]: " ans || true
  printf -v "$1" '%s' "${ans:-$def}"
}

steam_roots() {
  case "$OS" in
    linux)   printf '%s\n' "$HOME/.steam/steam" "$HOME/.local/share/Steam" "$HOME/.steam/root" \
               "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam";;
    macos)   printf '%s\n' "$HOME/Library/Application Support/Steam";;
    windows) printf '%s\n' "/c/Program Files (x86)/Steam" "/c/Program Files/Steam";;
  esac
}

detect_game() {
  [ -n "$GAME" ] && return 0
  local root vdf lib
  # Read line-by-line, NOT `for root in $(steam_roots)`. Unquoted command
  # substitution word-splits on spaces, which shreds every path this function
  # emits on Windows ("/c/Program Files (x86)/Steam" -> three fragments) and on
  # macOS ("$HOME/Library/Application Support/Steam"). Only Linux's paths happen
  # to be space-free, so auto-detection silently worked on exactly one platform
  # — including the libraryfolders.vdf fallback, which the loop never reached.
  while IFS= read -r root; do
    [ -n "$root" ] || continue
    [ -d "$root/steamapps/common/X4 Foundations" ] && { GAME="$root/steamapps/common/X4 Foundations"; return 0; }
    vdf="$root/steamapps/libraryfolders.vdf"
    [ -f "$vdf" ] || continue
    while IFS= read -r lib; do
      [ -d "$lib/steamapps/common/X4 Foundations" ] && { GAME="$lib/steamapps/common/X4 Foundations"; return 0; }
    done < <(grep -oE '"path"[[:space:]]*"[^"]+"' "$vdf" | sed -E 's/.*"path"[[:space:]]*"([^"]+)"/\1/')
  done < <(steam_roots)
  return 0
}

detect_profile() {
  [ -n "$PROFILE" ] && return 0
  local base newest="" d
  case "$OS" in
    windows) base="${USERPROFILE:-$HOME}/Documents/Egosoft/X4";;
    *)       base="$HOME/.config/EgoSoft/X4";;   # Linux/macOS vary; override with --profile if different
  esac
  [ -d "$base" ] || return 0
  for d in "$base"/*/; do
    [ -d "$d" ] || continue
    if [ -z "$newest" ] || [ "$d" -nt "$newest" ]; then newest="$d"; fi
  done
  PROFILE="${newest%/}"
  return 0
}

detect_xrcat() {
  [ -n "$XRCAT" ] && return 0
  local c
  for c in "$SRC/tools/XRCatTool/XRCatTool.exe" "$SRC/XTools/XRCatTool.exe" \
           "${GAME:+$GAME/../XRCatTool.exe}"; do
    [ -f "$c" ] && { XRCAT="$c"; return 0; }
  done
  return 0
}

MISSING=""
#: Paths never copied between toolkits, pruned from the destination BOTH before and
#: after the copy. One list, named once: two passes over two hand-written lists is how
#: they drift, and the whole defect here was one of the passes not running.
X4_COPY_PRUNE="tools/x4validate/.venv tools/x4validate/.pytest_cache tools/x4validate/.mutation-probe-pristine"

copy_toolkit() {
  refuse_if_dry_run "copying the toolkit into" "$1"  # copy_toolkit DEST  — copy tracked toolkit files (never game data / local config)
  local dest="$1"; mkdir -p "$dest/.claude"
  local item

  # BEFORE the copy loop, and that ordering IS the fix. `cp -r "$SRC/.claude"`
  # below overwrites these two, so a backup taken AFTERWARDS preserves the SOURCE
  # machine's file and reports it as the user's. MEASURED 2026-09-02 against a
  # source that had itself been set up -- which is what any working toolkit folder
  # looks like: the destination's X4_NEXUS_KEY was gone from every file, the .bak
  # held the source's values, and the run printed "kept your existing".
  # A reassurance that fires exactly when the thing it names has been destroyed is
  # worse than saying nothing at all.
  local stamp; stamp="$(date +%Y%m%d-%H%M%S)"
  local keep
  for keep in settings.local.json x4-paths.env; do
    [ -f "$dest/.claude/$keep" ] || continue
    cp "$dest/.claude/$keep" "$dest/.claude/$keep.bak-$stamp" 2>/dev/null || true
  done
  # `mods` carries the game extension x4live needs (README: "copy that folder into
  # {game}/extensions/"). Omitting it shipped a documented instruction pointing at a
  # directory the installer never created.
  # PRUNE THE DESTINATION FIRST. This list also runs after the loop, and running it
  # ONLY after was the defect: uv hardlinks package files from a shared cache, so once
  # both sides have been synced the same file has the same INODE in each and `cp -r`
  # refuses with "are the same file". MEASURED 2026-09-02 on the documented upgrade
  # path: hundreds of those, exit 1, a half-copied destination -- and because `set -e`
  # kills the script at the cp, neither the prune below nor the config restore after it
  # ever ran. A cleanup that only runs after the copy cannot make the copy possible.
  local junk
  for junk in $X4_COPY_PRUNE; do
    rm -rf "$dest/$junk" 2>/dev/null || true
  done
  for item in .claude tools bin scripts mods CLAUDE.md KNOWLEDGEBASE.md README.md CHANGELOG.md \
              LICENSE setup.sh install.sh install.ps1 SETUP_PROMPT.txt .gitignore .gitattributes; do
    # NAMED, never silently skipped -- that silence is how the absent mods/ folder
    # survived a whole release.
    [ -e "$SRC/$item" ] || { MISSING="$MISSING $item"; continue; }
    cp -r "$SRC/$item" "$dest/"
  done
  # A VIRTUALENV MUST NOT TRAVEL. uv hardlinks package files from a shared cache,
  # so once the source and the destination have each been synced the same file has
  # the SAME INODE in both -- and `cp -r` then fails with "are the same file", 1,334
  # times, part way through, leaving a half-copied destination. `set -e` kills the
  # script there, before the restore below, so there is no backup either.
  # pyvenv.cfg and the Scripts shims also embed absolute paths, so a copied venv
  # points back at the source. setup.sh recreates it anyway.
  # ...and again afterwards, so the SOURCE machine's virtualenv does not linger here.
  # pyvenv.cfg and the Scripts shims embed absolute paths, so a copied venv points back
  # at the machine it came from. setup.sh recreates it.
  for junk in $X4_COPY_PRUNE; do
    rm -rf "$dest/$junk" 2>/dev/null || true
  done

  # PUT THE USER'S BACK. Whatever the copy just landed here came from the SOURCE
  # machine -- its paths, its Nexus key -- and has no business on this one. These
  # two files are gitignored precisely because they are per-machine.
  #
  # PRESERVED, not merely archived. The previous version backed the file up and
  # then DELETED it, so every upgrade silently reverted the live config and the
  # user had to know to go looking in a .bak. setup.sh only recreates
  # settings.local.json when it is ABSENT, so keeping it here is what makes an
  # upgrade non-destructive rather than merely recoverable.
  for keep in settings.local.json x4-paths.env; do
    if [ -f "$dest/.claude/$keep.bak-$stamp" ]; then
      cp "$dest/.claude/$keep.bak-$stamp" "$dest/.claude/$keep"
      echo "  [note] kept your existing $keep (backup: $keep.bak-$stamp)"
    else
      # Nothing was here before, so anything present now arrived from the source.
      rm -f "$dest/.claude/$keep" 2>/dev/null || true
    fi
  done
  [ -n "$MISSING" ] && echo "  [note] not in the source, so not copied:$MISSING"
  return 0
}

write_paths_env() {  # write_paths_env TOOLKIT_DIR
  refuse_if_dry_run "writing the path config into" "$1/.claude/x4-paths.env"
  local t="$1" f="$1/.claude/x4-paths.env"
  mkdir -p "$1/.claude"

  # BACKED UP HERE, not at the call sites. `copy_toolkit` backs this file up and puts it
  # back, which covers --method in-game and --method separate; --method global never
  # calls copy_toolkit and went straight to this function, so it rewrote the file with no
  # backup at all.
  #
  # MEASURED 2026-09-02 on this repository, by accident: a `--method global` smoke run
  # with `--toolkit <the repo>` replaced the checkout's own config with sandbox paths and
  # left no .bak beside it. Five cold tests then failed, because the reference path
  # resolved to a directory that does not exist and the skip guarding them did not fire.
  #
  # Third instance of "installing destroys the user's config" in this release. The first
  # two were fixed by adding a backup at one call site each; putting it here means a
  # fourth caller cannot be added without one.
  if [ -f "$f" ]; then
    local _stamp; _stamp="$(date +%Y%m%d-%H%M%S)"
    if cp "$f" "$f.bak-$_stamp" 2>/dev/null; then
      echo "  [note] kept your previous x4-paths.env as x4-paths.env.bak-$_stamp"
    else
      # A backup that silently did not happen is worse than none, because the message
      # above would have said it did.
      echo "  WARNING: could not back up $f -- it is about to be rewritten." >&2
    fi
  fi

  # A trailing separator is not cosmetic here. The value lands inside a bash
  # double-quoted string, so a path ending in a backslash writes a line whose quote
  # never closes; `set -a; . "$cfg"` aborts on it and EVERY X4_* comes out unset while
  # the installer reports success. Windows tab-completion appends that backslash, and a
  # drive root is one.
  _esc_env_value() {
    local v="$1"
    v="${v%/}"                       # trailing separator, either dialect
    v="${v%\\}"
    v="${v//\\/\\\\}"                # backslashes FIRST, or we double the ones added below
    v="${v//\"/\\\"}"
    v="${v//\$/\\\$}"
    v="${v//\`/\\\`}"
    printf '%s' "$v"
  }

  # KEYS THIS FUNCTION DOES NOT OWN ARE CARRIED OVER. setup.sh tells the user to keep
  # X4_NEXUS_KEY in this file, and the file's own header says "edit freely" -- yet every
  # upgrade rebuilt it from scratch, so both were silently reverted and the key survived
  # only in a .bak the user had no reason to open.
  local owned=" X4_TOOLKIT X4_GAME X4_REFERENCE X4_PROFILE X4_DEBUGLOG X4_MODS X4_EXTENSIONS XRCATTOOL "
  local carried="" line key
  if [ -f "$f" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      case "$line" in
        '#'*|'') continue ;;
        *=*)     key="${line%%=*}" ;;
        *)       continue ;;
      esac
      case "$owned" in
        *" $key "*) continue ;;
      esac
      carried="$carried$line
"
    done < "$f"
  fi

  {
    echo "# Written by install.sh ($(date -u +%Y-%m-%dT%H:%MZ)) - edit freely. All paths overridable."
    echo "X4_TOOLKIT=\"$(_esc_env_value "$t")\""
    [ -n "$GAME" ]    && echo "X4_GAME=\"$(_esc_env_value "$GAME")\""
    echo "X4_REFERENCE=\"$(_esc_env_value "${REFERENCE:-$t/reference}")\""
    [ -n "$PROFILE" ] && echo "X4_PROFILE=\"$(_esc_env_value "$PROFILE")\""
    [ -n "$PROFILE" ] && echo "X4_DEBUGLOG=\"$(_esc_env_value "$PROFILE")/debug.txt\""
    [ -n "$MODS" ]    && echo "X4_MODS=\"$(_esc_env_value "$MODS")\""
    echo "X4_EXTENSIONS=\"$(_esc_env_value "${EXTENSIONS:-${GAME:+$GAME/extensions}}")\""
    [ -n "$XRCAT" ]   && echo "XRCATTOOL=\"$(_esc_env_value "$XRCAT")\""
    if [ -n "$carried" ]; then
      echo "# --- carried over from your previous x4-paths.env ---"
      printf '%s' "$carried"
    fi
  } > "$f"

  # VERIFY THE ARTIFACT, never the exit code. A config bash cannot source is exactly the
  # failure the escaping above exists to prevent, and proving it costs one subshell --
  # the same rule this installer already applies to the jq merge.
  if ! ( set -a; . "$f" ) >/dev/null 2>&1; then
    echo "ERROR: wrote $f but bash cannot SOURCE it, so every X4_* would come out unset." >&2
    echo "       Refusing to report success. This is a quoting fault in one of the paths." >&2
    return 1
  fi
  echo "  wrote $f"
  if [ -n "$carried" ]; then
    echo "  [note] carried over $(printf '%s' "$carried" | grep -c .) setting(s) you had added"
  fi
  return 0
}

install_global_claude() {  # copy skills/agents to ~/.claude and write X4_* env into settings.json
  local home_claude="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
  refuse_if_dry_run "installing skills and agents into" "$home_claude"
  # jq is checked FIRST, before anything is copied. This method cannot complete without
  # it (the settings.json merge below is jq-only), and by the time that merge runs the
  # skills/agents have already been copied AND rewritten to reference $X4_TOOLKIT -- so
  # failing late leaves a half-install whose every skill resolves to an undefined
  # variable. setup.sh treats a missing jq as a warning because it can proceed; this
  # cannot.
  if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: --method global needs jq to merge the X4_* env into $home_claude/settings.json." >&2
    echo "       Install jq (https://jqlang.github.io/jq/), or use --method separate/in-game," >&2
    echo "       which do not need it. Nothing has been changed." >&2
    exit 1
  fi
  mkdir -p "$home_claude/skills" "$home_claude/agents"
  local s a copied=0
  for s in "$TOOLKIT/.claude/skills/"x4-*; do
    [ -e "$s" ] || continue
    cp -r "$s" "$home_claude/skills/" && copied=$((copied + 1))
  done
  for a in "$TOOLKIT/.claude/agents/"*.md; do
    [ -e "$a" ] || continue
    cp "$a" "$home_claude/agents/" && copied=$((copied + 1))
  done
  # "Copied nothing" must never print as "installed". MEASURED 2026-09-02: with the x4
  # skills removed this printed `installed x4 skills + agents` and exited 0.
  # install.ps1:173-178 has had this refusal; bash had none.
  if [ "$copied" -eq 0 ]; then
    echo "ERROR: copied NOTHING from $TOOLKIT (.claude/skills/x4-* and .claude/agents/*.md)." >&2
    echo "       Nothing was installed into $home_claude -- this is a FAILURE, not a no-op." >&2
    echo "       Check that --toolkit points at a real toolkit checkout." >&2
    exit 1
  fi
  # global skills/agents run from any repo → resolve the validator via $X4_TOOLKIT, not
  # $CLAUDE_PROJECT_DIR. Rewrite ONLY the files this installer just copied — a user's
  # pre-existing skills/agents may use $CLAUDE_PROJECT_DIR on purpose and must not be
  # touched, so both lists are derived from the TOOLKIT's own contents, never from a
  # destination glob (a pre-existing user skill named x4-* must not match).
  {
    for s in "$TOOLKIT/.claude/skills/"x4-*; do
      [ -e "$s" ] && echo "$home_claude/skills/$(basename "$s")"
    done
    for a in "$TOOLKIT/.claude/agents/"*.md; do
      [ -e "$a" ] && echo "$home_claude/agents/$(basename "$a")"
    done
    # STATUS-NEUTRAL terminator, and it is load-bearing. A `{ ... }` group's exit
    # status is its LAST command: with no agents/*.md match the `for` above ends on a
    # false `[ -e ]` and returns 1, `pipefail` promotes that to the pipeline, and
    # `set -e` kills the installer HERE -- after the copy, before the jq merge, with
    # no message. An unmatched glob is a normal state, not a failure.
    true
  } | while read -r tgt; do
    # `|| true` is LOAD-BEARING: grep exits 1 when it matches nothing, `set -o pipefail`
    # promotes that to the pipeline's status, and `set -e` then killed the whole
    # installer. MEASURED 2026-09-01: 2 of the 7 shipped skills (x4-debug, x4-probe)
    # contain no $CLAUDE_PROJECT_DIR, so `--method global` exited 1 on this very tree --
    # after copying skills and agents, and before writing any env. A skill that needs no
    # rewrite is the NORMAL case, not an error.
    hits="$(grep -rl 'CLAUDE_PROJECT_DIR' "$tgt" 2>/dev/null || true)"
    [ -n "$hits" ] || continue
    printf '%s\n' "$hits" | while read -r f; do
      sed -i.bak 's#\$CLAUDE_PROJECT_DIR#$X4_TOOLKIT#g' "$f" && rm -f "$f.bak"
    done
  done
  echo "  installed $copied x4 skill/agent item(s) into $home_claude"
  # STATED, because it is the difference between this layout and the other two, and
  # nothing else in the run mentions it. The hooks are registered in the repo's
  # .claude/settings.json, which this method does not copy, and each is addressed as
  # $CLAUDE_PROJECT_DIR/.claude/hooks/... -- which globally resolves to whatever repo
  # the user has open, not to the toolkit.
  echo
  echo "  NOTE: this layout installs the SKILLS AND AGENTS ONLY."
  echo "        The safety guards -- the command and file hooks, and the automatic"
  echo "        backup before every edit -- are NOT installed by --method global."
  echo "        They are per-project: they live in a repo's .claude/settings.json and"
  echo "        resolve their paths from that project. Use --method in-game or"
  echo "        --method separate in a mod repo to get them there."
  # merge env into settings.json (jq); create if absent
  local sj="$home_claude/settings.json"
  [ -f "$sj" ] || echo '{}' > "$sj"
  local tmp; tmp="$(mktemp)"
  jq --arg tk "$TOOLKIT" --arg g "$GAME" --arg ref "${REFERENCE:-$TOOLKIT/reference}" \
     --arg p "$PROFILE" --arg m "$MODS" --arg ext "${EXTENSIONS:-${GAME:+$GAME/extensions}}" --arg xc "$XRCAT" '
     .env = ((.env // {})
       + {X4_TOOLKIT:$tk, X4_REFERENCE:$ref}
       + (if $g  != "" then {X4_GAME:$g}       else {} end)
       + (if $p  != "" then {X4_PROFILE:$p, X4_DEBUGLOG:($p+"/debug.txt")} else {} end)
       + (if $m  != "" then {X4_MODS:$m}       else {} end)
       + (if $ext!= "" then {X4_EXTENSIONS:$ext} else {} end)
       + (if $xc != "" then {XRCATTOOL:$xc}    else {} end))' "$sj" > "$tmp" && mv "$tmp" "$sj"
  # NEVER announce success from a line that cannot have failed. `A && B` does not trip
  # `set -e` when A fails (A is not the command following the final &&), so a failing jq
  # skipped the mv and this echo still printed -- exit 0, "merged X4_* env into ...",
  # and settings.json left as `{}`. Verify the ARTIFACT, not the exit code of the shell
  # that wrapped it.
  if ! jq -e '.env.X4_TOOLKIT' "$sj" >/dev/null 2>&1; then
    echo "ERROR: the X4_* env merge did not land in $sj." >&2
    echo "       Skills and agents were copied, but they resolve paths via \$X4_TOOLKIT," >&2
    echo "       which is now undefined. Set it by hand, or re-run once jq works." >&2
    exit 1
  fi
  echo "  merged X4_* env into $sj"
}

# --- writing somewhere needs DIRECTION, not inference -----------------------
#
# MEASURED 2026-09-02: `install.sh --method in-game --yes` with no --game wrote 1,642
# files into a real Steam install and exited 0. Every X4_* variable had been cleared
# first and none of it mattered -- steam_roots() is hardcoded, so detection found the
# game directly, and --yes accepted that destination without ever printing it. Seven
# personal files were overwritten, including a 145 KB CLAUDE.md and a 631 KB
# KNOWLEDGEBASE.md. They were recovered from a Volume Shadow Copy: luck, not design.
#
# The rule (user-set, and stronger than "prompt first"): a new install must not proceed
# over an EXISTING install without strict user DIRECTION -- a flag naming the intent --
# not merely an approval the user can click through. And a destination the user never
# named is not a destination at all when nobody is there to read the prompt.

#: Does this directory already hold a toolkit? Any one marker is enough; they are the
#: things an install would overwrite.
looks_installed() {
  local d="$1"
  [ -e "$d/.claude/hooks/protect-bash.sh" ] && return 0
  [ -e "$d/tools/x4validate" ]              && return 0
  [ -e "$d/CLAUDE.md" ]                     && return 0
  [ -e "$d/KNOWLEDGEBASE.md" ]              && return 0
  return 1
}

#: refuse_if_dry_run WHAT DEST -- the ONE dry-run gate, called by every writer.
#:
#: It used to live in `announce_target`, which is only called when a COPY would happen --
#: so `--method global` never reached it and did a complete install, and so did an
#: in-place `separate`. MEASURED 2026-09-02: `--method global --dry-run` wrote the config,
#: copied 9 items into the global Claude home over the user's own skills with no backup,
#: merged settings.json and printed "install complete".
#:
#: Placed on the WRITERS instead: every write in this script goes through copy_toolkit,
#: write_paths_env or install_global_claude, so an arm added later cannot write without
#: passing it. The flag is documented three times with no qualification, and a user
#: reaching for it is reaching for safety.
refuse_if_dry_run() {
  [ "$DRY_RUN" = 1 ] || return 0
  echo
  echo "  --dry-run: NOT $1"
  echo "      $2"
  echo
  echo "=== dry run complete: nothing was changed ==="
  exit 0
}

#: require_direction DEST WHAT_NAMED_IT
#: Called immediately before the first write of every method.
require_direction() {
  local dest="$1" named="$2"

  # (a) Nobody named it AND nobody is watching. `--yes` is documented as "accept
  #     detected values", which is fine for a profile path and is not fine for the
  #     directory about to be written to in bulk.
  # ...or nobody is watching for any other reason. `--yes` was the only trigger, so a
  # CLOSED STDIN walked straight through: `ask()` is `read ... || true`, the read fails
  # at EOF, the `|| true` swallows it, and the detected default is accepted in silence.
  # The rule this branch states is "a destination the user never named is not a
  # destination at all when nobody is there to read the prompt" -- and no tty is exactly
  # that. The Bash tool this toolkit is driven by has no tty.
  if [ "$named" = "detected" ] && { [ "$ASSUME_YES" = 1 ] || [ ! -t 0 ]; }; then
    if [ "$ASSUME_YES" = 1 ]; then
      echo "REFUSING: --yes with an auto-detected destination." >&2
    else
      echo "REFUSING: an auto-detected destination with no terminal to confirm on." >&2
    fi
    echo "  Detected: $dest" >&2
    echo "  Nothing named that path -- it came from scanning the usual Steam locations," >&2
    echo "  and nobody will see a prompt before the write starts." >&2
    echo "  Name it explicitly:  --game \"$dest\"   (or --toolkit for separate/global)" >&2
    exit 2
  fi

  # (b) Something is already installed there. A flag is the direction; a prompt is not.
  if looks_installed "$dest" && [ "$OVER_EXISTING" != 1 ]; then
    echo "REFUSING: there is already an installation at the destination." >&2
    echo "  Destination: $dest" >&2
    echo "  Found:" >&2
    for m in .claude/hooks/protect-bash.sh tools/x4validate CLAUDE.md KNOWLEDGEBASE.md; do
      [ -e "$dest/$m" ] && echo "      $m" >&2
    done
    echo >&2
    echo "  Installing over it REPLACES those files. If any of them are yours -- an" >&2
    echo "  edited CLAUDE.md, your own KNOWLEDGEBASE.md, customised skills -- they are" >&2
    echo "  gone, and only .claude/x4-paths.env and settings.local.json are preserved." >&2
    echo >&2
    echo "  To upgrade it anyway, say so explicitly:" >&2
    echo "      bash install.sh --method $METHOD --over-existing ..." >&2
    exit 2
  fi
}

#: announce_target DEST -- say what is about to happen, before it happens.
announce_target() {
  local dest="$1"
  echo
  echo "  About to write the toolkit into:"
  echo "      $dest"
  if [ "$DRY_RUN" = 1 ]; then
    echo "  --dry-run: nothing will be written. Items that would be copied:"
    local item
    for item in .claude tools bin scripts mods CLAUDE.md KNOWLEDGEBASE.md README.md \
                CHANGELOG.md LICENSE setup.sh install.sh install.ps1 SETUP_PROMPT.txt \
                .gitignore .gitattributes; do
      [ -e "$SRC/$item" ] && echo "      $item"
    done
    echo
    echo "=== dry run complete: nothing was changed ==="
    exit 0
  fi
}

#: Strip a trailing path separator, which otherwise makes a STRING comparison lie.
#: `--toolkit "$SRC/"` is not equal to `$SRC`, so the `SRC != TOOLKIT` test said
#: COPY and `cp -r "$SRC/.claude" "$SRC//"` copied a directory into itself. Under
#: `set -e` the script died there, BEFORE the FAILED accounting exists -- so there
#: was no INCOMPLETE banner and no config written, and the exit code was the only
#: sign. MEASURED 2026-09-03 in a sandbox: rc 1, "are the same file", zero config.
#:
#: Both separators, because this runs under Git Bash where a Windows path gets
#: pasted in. A drive root and `/` KEEP their separator: stripping it would turn an
#: absolute path into a relative one. No backslash appears in a case PATTERN here --
#: the first draft had one and the tool boundary collapsed it into a syntax error.
#: Are these the SAME directory? Asked canonically, never as a string.
#:
#: `$SRC` is MSYS-style (`/tmp/...`) because it comes from `cd $(dirname) && pwd`
#: under Git Bash, while `--toolkit` is whatever the user pasted -- and every path
#: this project documents is Windows-style (`C:/...`). So the plain string test
#: compared two spellings of one directory and said COPY. `cp -r` then reported
#: "are the same file" and `set -e` killed the script BEFORE the FAILED accounting
#: exists: no INCOMPLETE banner, no failed: line, no config. MEASURED in a sandbox.
#:
#: `cd ... && pwd -P` settles dialect, trailing separators, . / .. and symlinks at
#: once. A destination that does not exist YET cannot be the source, so a failed cd
#: means "different" -- which is the right answer for a fresh install.
same_dir() {
  local a b
  a=$(cd "$1" 2>/dev/null && pwd -P) || return 1
  b=$(cd "$2" 2>/dev/null && pwd -P) || return 1
  [ "$a" = "$b" ]
}

strip_trailing_sep() {
  local p="$1" bs last
  bs=$(printf '%b' '\134')            # one backslash, from its octal value
  while [ ${#p} -gt 1 ]; do
    last="${p: -1}"
    [ "$last" = "/" ] || [ "$last" = "$bs" ] || break
    case "$p" in
      ?:?) break ;;                   # a drive root
    esac
    p="${p%?}"
  done
  printf '%s' "$p"
}

# --- choose method ---------------------------------------------------------
if [ -z "$METHOD" ]; then
  echo; echo "Install method:"; echo "  1) in-game    2) separate    3) global (multi-repo)"
  if [ "$ASSUME_YES" = 1 ]; then METHOD=separate; else
    read -r -p "Choose [1/2/3]: " m || true
    case "$m" in 1) METHOD=in-game;; 3) METHOD=global;; *) METHOD=separate;; esac
  fi
fi
echo "Method: $METHOD"

detect_game; detect_profile; detect_xrcat
ask GAME    "X4 game folder (01.cat..09.cat)" "$GAME"
ask PROFILE "X4 user profile folder"          "$PROFILE"
ask XRCAT   "XRCatTool.exe path"              "$XRCAT"

# Normalised HERE and again after the in-arm ask below, because a destination
# can arrive either way and a single up-front pass would miss the interactive
# one.
GAME="$(strip_trailing_sep "$GAME")"
PROFILE="$(strip_trailing_sep "$PROFILE")"
TOOLKIT="$(strip_trailing_sep "$TOOLKIT")"

case "$METHOD" in
  in-game)
    [ -n "$GAME" ] || { echo "ERROR: in-game needs --game"; exit 1; }
    TOOLKIT="$GAME"
    # Only when a COPY would actually happen. Re-running from inside the toolkit
    # folder overwrites nothing, so it needs no direction.
    if ! same_dir "$SRC" "$TOOLKIT"; then
      require_direction "$TOOLKIT" "$GAME_NAMED"
      announce_target "$TOOLKIT"
      copy_toolkit "$TOOLKIT"
    fi
    write_paths_env "$TOOLKIT"
    ;;
  separate)
    [ -n "$TOOLKIT" ] || TOOLKIT="$SRC"
    ask TOOLKIT "Toolkit folder" "$TOOLKIT"
    TOOLKIT="$(strip_trailing_sep "$TOOLKIT")"
    if ! same_dir "$SRC" "$TOOLKIT"; then
      require_direction "$TOOLKIT" "$TOOLKIT_NAMED"
      announce_target "$TOOLKIT"
      copy_toolkit "$TOOLKIT"
    fi
    write_paths_env "$TOOLKIT"
    ;;
  global)
    [ -n "$TOOLKIT" ] || TOOLKIT="$SRC"
    write_paths_env "$TOOLKIT"
    install_global_claude
    ;;
  *) echo "ERROR: unknown method '$METHOD' (in-game|separate|global)"; exit 2;;
esac

# wire x4validate + prereqs in the target toolkit
# `|| true` swallowed a failed setup.sh entirely, and this script had no INCOMPLETE
# branch at all -- so a half-finished install printed exactly the same success text as
# a good one. install.ps1 has accumulated $failed and exited 1 for a while; this is the
# same accounting on the bash side.
# ACCUMULATES. A single assignment could only ever name one failure, and the unpack
# below was outside the accounting entirely: under `set -e` a failing unpack killed the
# script with NO summary -- neither banner, no `failed:` line, no next steps.
# install.ps1 has used an array with three contributors for a while; this is parity.
FAILED=""
add_failed() { FAILED="$FAILED${FAILED:+, }$1"; }

( cd "$TOOLKIT" && CLAUDE_PROJECT_DIR="$TOOLKIT" bash setup.sh ) || add_failed "setup.sh"

if [ "$DO_UNPACK" = 1 ]; then
  echo "Unpacking reference/ ..."
  ( cd "$TOOLKIT" && CLAUDE_PROJECT_DIR="$TOOLKIT" bash bin/unpack-reference.sh ) \
    || add_failed "bin/unpack-reference.sh"
fi

echo
# An INCOMPLETE install must not print the success text. install.ps1 has accumulated
# $failed and exited 1 for a while; install.sh swallowed a failed setup.sh with
# `|| true` and had no such branch at all, so a half-finished install and a good one
# were indistinguishable from the output.
if [ -n "${FAILED:-}" ]; then
  echo
  echo "=== install INCOMPLETE ($METHOD) ==="
  echo "  failed: $FAILED"
  echo "Toolkit:   $TOOLKIT"
  echo "Fix the above and re-run, or complete that step by hand."
  exit 1
fi

echo "=== install complete ($METHOD) ==="
echo "Toolkit:   $TOOLKIT"
echo "Config:    $TOOLKIT/.claude/x4-paths.env  (edit any path here)"
[ "$METHOD" = global ] && echo "Global:    skills/agents + X4_* env added to your ~/.claude — works from any mod repo."
echo "Next:      set X4_GAME if blank, then  (cd \"$TOOLKIT\" && bash bin/unpack-reference.sh)  to build reference/."
echo
echo "IMPORTANT — set X4_TOOLKIT in your user environment so the tools find the config"
echo "above from ANY directory (they are often run from the game folder, which has a"
echo ".claude/ but no x4-paths.env). This installer cannot do it for you:"
case "$OS" in
  windows) echo "           setx X4_TOOLKIT \"$TOOLKIT\"        (takes effect in NEW shells)";;
  *)       echo "           echo 'export X4_TOOLKIT=\"$TOOLKIT\"' >> ~/.bashrc   # or your shell's rc";;
esac
echo "Verify:    (cd \"$TOOLKIT/tools/x4validate\" && uv run x4validate --paths)"

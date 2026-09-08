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
#: Machine-local paths that must not travel. `.gitignore` is already the correct
#: enumeration of 'must not leave this machine' and nothing derived this from it,
#: so the copy carried 217 files of `.claude/backups/`, every __pycache__ and
#: .pytest_cache under the copy set, and `.perf-baseline.json` -- whose own
#: .gitignore entry says MACHINE-LOCAL by design because wall-clock differs per
#: machine, and which the installer then copied to another machine for
#: perf_guard to compare against a stranger's timings.
X4_COPY_PRUNE="tools/x4validate/.venv tools/x4validate/.pytest_cache tools/x4validate/.mutation-probe-pristine .claude/hooks/__pycache__ .claude/hooks/.pytest_cache scripts/__pycache__ tools/.pytest_cache tools/basex/__pycache__ tools/basex/basex/.basex tools/x4validate/.perf-baseline.json tools/x4validate/.obtainability-baseline.json tools/x4validate/gates/__pycache__ tools/x4validate/scripts/__pycache__ tools/x4validate/tests/__pycache__ tools/x4validate/x4validate/__pycache__"

#: Per-machine files that must NEVER travel from the source: they hold THIS
#: machine paths and secrets, and the destination copy is the user own.
#:
#: Distinct from X4_COPY_PRUNE, and the difference is the whole point: a pruned
#: path is also DELETED from the destination, which is right for a stale .venv and
#: catastrophic for a config. These are skipped on the way IN and left alone on
#: the way OUT.
#:
#: This replaces a backup-then-overwrite-then-restore round trip on the same two
#: files. That round trip had two defects and both are removed rather than fixed:
#: it wrote a file it never intended to change (so `x4lock`, which the README
#: tells users to run, made the whole install fail with a bare `cp: Permission
#: denied` on item 1 of 16), and its restore sat 53 lines after its backup with
#: no trap between them, so any failure in the copy loop skipped the restore and
#: left an orphaned .bak. Not copying a file cannot fail to restore it.
X4_KEEP_LOCAL=".claude/x4-paths.env .claude/settings.local.json .claude/backups"

#: Copy $SRC/REL to DEST/REL, never descending into a pruned relative path.
#:
#: The virtualenv used to be copied in full (1,407 files, 38 MB) and deleted on
#: arrival, while the CHANGELOG said it no longer travels. Worse than wasteful:
#: under `set -e` a failure among those copies aborts BEFORE both the prune and
#: the config restore, so the most expensive thing copied was also the thing most
#: likely to break the install -- and nothing wanted it copied.
#:
#: `cp -r` has no portable exclude. rsync is absent from Git Bash and from a stock
#: macOS, and tar's --exclude differs between GNU tar and bsdtar, so the walk is
#: done here -- and ONLY where needed: a directory containing no pruned path is
#: still copied in one cp, so only tools/ is ever descended into.
#:
#: `cp -r "$src/." "$dest/$rel/"`, not `cp -r "$src" "$dest/"`: the second copies a
#: directory INTO an existing directory of the same name on an upgrade, which is
#: how you get .claude/.claude. This form merges, and is idempotent.
copy_item() {   # copy_item REL DEST
  # `src` is assigned on its OWN line. `local a="$1" b="$SRC/$a"` does not work: bash
  # expands every word of the `local` command before the builtin assigns any of them,
  # so `$a` is still unset there -- and under `set -u` that is a hard "unbound
  # variable", which is how the upgrade case failed the moment this was added.
  local rel="$1" dest="$2" junk needs_walk=0 child src
  src="$SRC/$rel"
  for junk in $X4_COPY_PRUNE $X4_KEEP_LOCAL; do
    [ "$junk" = "$rel" ] && return 0
    case "$junk" in "$rel"/*) needs_walk=1 ;; esac
  done
  # AND EVERY SIBLING OF A KEEP-LOCAL FILE, not just the exact name. `.bak-<stamp>`
  # and `.tmp<pid>` sit beside the config, carry X4_NEXUS_KEY by construction, and
  # travelled to the destination because this matched two literal strings.
  #
  # ★ The same arc widened .gitignore from those two names to `x4-paths.env.*` and
  # explained why -- and left THIS matching exactly. The ignore rule and the copy
  # rule describe one set; only one of them had been told. When you generalise a
  # rule, find its twin.
  #
  # `.example` is re-included for the same reason .gitignore negates it: the
  # templates SHIP, and a blanket prefix skip stops the installer installing its
  # own example files.
  for junk in $X4_KEEP_LOCAL; do
    case "$rel" in
      "$junk".example) : ;;
      "$junk".*)       return 0 ;;
    esac
  done
  if [ ! -d "$src" ] || [ "$needs_walk" = 0 ]; then
    mkdir -p "$dest/$(dirname "$rel")"
    if [ -d "$src" ]; then
      mkdir -p "$dest/$rel"
      cp -r "$src/." "$dest/$rel/"
    else
      cp "$src" "$dest/$rel"
    fi
    return 0
  fi
  mkdir -p "$dest/$rel"
  for child in "$src"/* "$src"/.[!.]* "$src"/..?*; do
    [ -e "$child" ] || continue
    copy_item "$rel/$(basename "$child")" "$dest"
  done
}

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
  for item in $X4_COPY_ITEMS; do
    # NAMED, never silently skipped -- that silence is how the absent mods/ folder
    # survived a whole release.
    [ -e "$SRC/$item" ] || { MISSING="$MISSING $item"; continue; }
    copy_item "$item" "$dest"
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
  # THE BACKUP/RESTORE ROUND TRIP IS GONE, not repaired. These two files are now
  # in X4_KEEP_LOCAL, so the copy never touches them -- and a file that is never
  # overwritten needs no backup and no restore.
  #
  # Removing it fixes two defects at once rather than handling them. The restore
  # sat 53 lines after the backup with NO trap between, so any failure in the copy
  # loop skipped it and left an orphaned .bak; and the restore itself WROTE to the
  # config, so a config the user had locked (as README instructs) failed the
  # install -- at the restore, after the copy had already succeeded.
  #
  # MEASURED 2026-09-07: with the copy skipped but the round trip still present,
  # the upgrade still died with `cp: cannot create regular file .../x4-paths.env:
  # Permission denied` -- the restore, not the copy. Half the fix was no fix.
  [ -n "$MISSING" ] && echo "  [note] not in the source, so not copied:$MISSING"
  return 0
}

#: The key=value lines write_paths_env OWNS, as it would write them now.
#: Factored out so the precondition below and the writer cannot disagree about
#: what "would change" means -- two renderings of one rule is the defect this
#: installer already carries a comment about elsewhere.
#: HOISTED to file scope. It used to be defined INSIDE write_paths_env, which
#: means it does not exist until that function has been entered -- so the
#: precondition check above, which runs BEFORE any writing, called a function
#: that was not there yet. Bash reports `command not found`, the substitution
#: yields an empty string, every rendered value comes out blank, and the
#: comparison therefore ALWAYS differs: the check refused every upgrade,
#: including the ones it should have waved through. A helper two callers need
#: cannot live inside one of them.
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

_owned_lines_new() {   # _owned_lines_new TOOLKIT_DIR
  local t="$1"
  echo "X4_TOOLKIT=\"$(_esc_env_value "$t")\""
  [ -n "$GAME" ]    && echo "X4_GAME=\"$(_esc_env_value "$GAME")\""
  echo "X4_REFERENCE=\"$(_esc_env_value "${REFERENCE:-$t/reference}")\""
  [ -n "$PROFILE" ] && echo "X4_PROFILE=\"$(_esc_env_value "$PROFILE")\""
  [ -n "$PROFILE" ] && echo "X4_DEBUGLOG=\"$(_esc_env_value "$PROFILE")/debug.txt\""
  [ -n "$MODS" ]    && echo "X4_MODS=\"$(_esc_env_value "$MODS")\""
  # CONDITIONAL, matching install.ps1. Emitted unconditionally, with neither
  # --game nor --extensions this wrote `X4_EXTENSIONS=""` while PowerShell omitted
  # the key -- two configs from one input, reachable via --method global with no
  # game detected. An empty value is a claim; an absent key is not.
  [ -n "${EXTENSIONS:-${GAME:+$GAME/extensions}}" ] && echo "X4_EXTENSIONS=\"$(_esc_env_value "${EXTENSIONS:-${GAME:+$GAME/extensions}}")\""
  [ -n "$XRCAT" ]   && echo "XRCATTOOL=\"$(_esc_env_value "$XRCAT")\""
  return 0
}

#: The same keys as they stand in the file today. Comments and carried keys are
#: excluded deliberately: carried keys come FROM the file so they can never
#: differ, and a timestamp header changes on every run, which would make every
#: upgrade look like a change and defeat the whole check.
CR=$(printf '\r')   # one carriage return, built once
_owned_lines_old() {   # _owned_lines_old CONFIG_FILE
  local f="$1" line key
  # EXISTS-BUT-NOT-A-READABLE-FILE is its own answer. `[ -f ]` is false for a
  # DIRECTORY standing where the config belongs, so the old form returned "no
  # config" for a path that plainly is one -- and the caller then compared an
  # empty result against the rendered lines and read it as "the paths changed".
  # Absent, unreadable and different are three states, not two.
  if [ -e "$f" ] && [ ! -f "$f" ]; then
    echo "__X4_UNREADABLE__"
    return 0
  fi
  [ -f "$f" ] || return 0
  # READABLE, or say so. A config held open by an editor, an AV scanner or a sync
  # client gives `Device or resource busy` here, and an unreadable file used to
  # produce raw shell errors and an empty result -- which the caller then compared
  # against the rendered lines and read as "everything changed". Cannot-read is
  # not the same as differs, and it must not be silently promoted to it.
  if ! [ -r "$f" ] || ! head -c 1 "$f" >/dev/null 2>&1; then
    echo "__X4_UNREADABLE__"
    return 0
  fi
  while IFS= read -r line || [ -n "$line" ]; do
    # STRIP THE CR. `read -r` keeps it and `_owned_lines_new` renders without one,
    # so a config saved by any Windows editor compared UNEQUAL forever: bash
    # refused the documented locked upgrade with a remedy that cannot help, while
    # PowerShell's Get-Content strips CR and reported "already matches". One
    # input, opposite verdicts -- and the test written for that path could not see
    # it, because the installer it had just run wrote LF.
    line="${line%$CR}"
    case "$line" in '#'*|'') continue ;; *=*) key="${line%%=*}" ;; *) continue ;; esac
    case " X4_TOOLKIT X4_GAME X4_REFERENCE X4_PROFILE X4_DEBUGLOG X4_MODS X4_EXTENSIONS XRCATTOOL " in
      *" $key "*) echo "$line" ;;
    esac
  done < "$f"
  return 0
}

#: PRECONDITION, checked before ANY file is written and in dry-run too.
#:
#: `x4lock` marks the path config read-only and README tells users to run it, so
#: the documented upgrade path met a bare `cp: Permission denied` on item 1 of 16
#: -- after the copy had already begun, with no statement of what had landed.
#: MEASURED 2026-09-07 on a real install and reduced to a fixture.
#:
#: Two outcomes, and the split is the point. An upgrade that does not need to
#: CHANGE the config never writes it, so the lock is irrelevant and the install
#: proceeds. An upgrade that genuinely must change it REFUSES, up front, naming
#: the unlock command -- because an installer that silently unlocked would defeat
#: the mechanism the user deliberately turned on.
#: THE COPY SET, named ONCE. It was written out twice -- in the copy loop and in
#: the dry-run listing -- and a third caller now needs it (the locked-target
#: precheck below). Two statements of one list is the shape this file already
#: warns about elsewhere; three would be asking for the listing and the copy to
#: disagree about what an install actually writes.
X4_COPY_ITEMS=".claude tools bin scripts mods CLAUDE.md KNOWLEDGEBASE.md README.md CHANGELOG.md LICENSE setup.sh install.sh install.ps1 SETUP_PROMPT.txt .gitignore .gitattributes"

#: Destination files the copy would overwrite that CANNOT be written.
#:
#: precheck_config guarded ONE file. x4lock's manifest under a game root covers
#: about twenty-six -- CLAUDE.md, KNOWLEDGEBASE.md, .claude/settings.json, the
#: hooks, the skills, the agents -- and for `--method in-game` the game root IS
#: the destination, so all of them sit inside the copy set. Guarding the env file
#: alone moved the failure from one filename to another.
#:
#: MEASURED 2026-09-07 with one locked hook in the destination: install.sh died
#: mid-copy on a bare `cp: Permission denied`, half-copied, with no unlock hint;
#: install.ps1 returned 0 and OVERWROTE it, because `Copy-Item -Force` clears the
#: read-only attribute. One installer destroyed what the lock protected and the
#: other left a mess, and nothing decided which was correct. Refusing before
#: either writes anything is the only answer that is right for both.
_locked_targets() {   # _locked_targets DEST  -> prints blocked destination paths
  local dest="$1" item rel f junk skip
  for item in $X4_COPY_ITEMS; do
    [ -e "$SRC/$item" ] || continue
    if [ -d "$SRC/$item" ]; then
      ( cd "$SRC/$item" 2>/dev/null && find . -type f -print 2>/dev/null ) | while IFS= read -r rel; do
        rel="${rel#./}"
        skip=0
        for junk in $X4_COPY_PRUNE $X4_KEEP_LOCAL; do
          case "$item/$rel" in "$junk"|"$junk"/*) skip=1 ;; esac
        done
        [ "$skip" = 1 ] && continue
        f="$dest/$item/$rel"
        [ -e "$f" ] && [ ! -w "$f" ] && printf '%s\n' "$f"
      done
    else
      f="$dest/$item"
      [ -e "$f" ] && [ ! -w "$f" ] && printf '%s\n' "$f"
    fi
  done
  return 0
}

#: PRECONDITION over the whole copy set, before anything is written, dry run too.
precheck_locked_targets() {   # precheck_locked_targets DEST
  local dest="$1" blocked n
  blocked="$(_locked_targets "$dest")"
  [ -z "$blocked" ] && return 0
  n="$(printf '%s\n' "$blocked" | grep -c .)"
  echo                                                                          >&2
  echo "REFUSING: $n file(s) this install would overwrite are READ-ONLY."        >&2
  printf '%s\n' "$blocked" | head -8 | sed 's/^/      /'                        >&2
  [ "$n" -gt 8 ] && echo "      ... and $((n - 8)) more NOT LISTED"              >&2
  echo                                                                          >&2
  echo "  This is x4lock doing its job -- README tells you to run it, and it"    >&2
  echo "  cannot tell an installer from any other process that writes here."     >&2
  echo "  Nothing has been changed."                                            >&2
  echo                                                                          >&2
  echo "  Unlock, re-run this installer, then lock again:"                       >&2
  echo "      python scripts/x4lock.py unlock"                                   >&2
  echo "      <re-run this command>"                                             >&2
  echo "      python scripts/x4lock.py lock"                                     >&2
  exit 1
}

precheck_config() {   # precheck_config TOOLKIT_DIR
  local t="$1" f="$1/.claude/x4-paths.env"
  [ -e "$f" ] || return 0                      # nothing there to protect
  local _now; _now="$(_owned_lines_old "$f")"
  if [ "$_now" = "__X4_UNREADABLE__" ]; then
    echo "REFUSING: $f exists but cannot be READ, so this run cannot tell whether" >&2
    echo "      your paths would change. Something is holding it open -- an editor," >&2
    echo "      an AV scanner, or a sync client. Nothing has been changed." >&2
    exit 1
  fi
  [ "$_now" = "$(_owned_lines_new "$t")" ] && return 0
  [ -w "$f" ] && return 0
  echo                                                                        >&2
  echo "REFUSING: your path config must change, and it is READ-ONLY."         >&2
  echo "      $f"                                                             >&2
  echo                                                                        >&2
  echo "  This is x4lock doing its job -- README tells you to run it, and it"  >&2
  echo "  cannot tell an installer from any other process that writes here."  >&2
  echo "  Nothing has been changed."                                          >&2
  echo                                                                        >&2
  echo "  Unlock, re-run this installer, then lock again:"                    >&2
  echo "      python scripts/x4lock.py unlock"                                >&2
  echo "      <re-run this command>"                                          >&2
  echo "      python scripts/x4lock.py lock"                                  >&2
  echo                                                                        >&2
  echo "  (An upgrade that does NOT change your paths does not need this: it" >&2
  echo "   leaves the config untouched and the lock never applies.)"          >&2
  exit 1
}

write_paths_env() {  # write_paths_env TOOLKIT_DIR
  local t="$1" f="$1/.claude/x4-paths.env"
  # THE GATE IS THE FIRST STATEMENT, and it has to stay there.
  #
  # The "nothing to change" fast path below was inserted ABOVE it, which made
  # --dry-run perform a REAL install whenever `same_dir` was true: no copy runs,
  # so this is the only writer reached, the fast path returned before the gate,
  # and execution fell through to `bash setup.sh` at top level -- which synced
  # dependencies for real. MEASURED on all four arms, rc 0, "install complete",
  # no dry-run banner. Proven a regression against the same fixture at c6fe0f0^.
  #
  # An early return added above a gate is invisible to a check that COUNTS call
  # sites, which is what install.ps1's own comment here already warned about --
  # and the same arc then moved the gate below a return anyway.
  refuse_if_dry_run "writing the path config into" "$1/.claude/x4-paths.env"
  # NOTHING TO CHANGE, NOTHING TO WRITE. An upgrade that resolves the same
  # paths used to rewrite this file anyway -- which meant a config the user
  # had locked (as README instructs) failed the whole install for a write
  # that would have changed nothing, and a config with hand-written COMMENTS
  # lost them on every run, because only key=value lines are carried over.
  if [ -f "$f" ] && [ "$(_owned_lines_old "$f")" = "$(_owned_lines_new "$t")" ]; then
    echo "  [note] $f already matches these paths; left untouched"
    return 0
  fi
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
      # States what is TRUE NOW, not a prediction. This used to say "it is about to
      # be rewritten" and then the run died before rewriting anything -- a warning
      # that was false in the only case that printed it.
      echo "  WARNING: could not back up $f. If this run goes on to replace it," >&2
      echo "           the previous values will not be recoverable from a .bak." >&2
    fi
  fi

  # A trailing separator is not cosmetic here. The value lands inside a bash
  # double-quoted string, so a path ending in a backslash writes a line whose quote
  # never closes; `set -a; . "$cfg"` aborts on it and EVERY X4_* comes out unset while
  # the installer reports success. Windows tab-completion appends that backslash, and a
  # drive root is one.
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

  # RENDER TO A TEMP, VERIFY THE TEMP, THEN REPLACE. The redirect used to target
  # the LIVE config, and `>` truncates before the first byte is written -- so a
  # render that failed part way left the user with a half-written config, and the
  # verification below then reported the failure about a file it was already too
  # late to protect. "Refusing to report success" was honest and the config was
  # gone regardless, recoverable only from a .bak the user had to go and find.
  #
  # This is the third instance of one shape today: `_effective._write_db` leaked
  # its temp because the cleanup only existed on one exit path, `_registry.save`
  # already had the answer, and this had the answer inverted -- it wrote to the
  # live path and checked afterwards. Build beside, prove, then move.
  tmp="$f.tmp$$"
  {
    echo "# Written by install.sh ($(date -u +%Y-%m-%dT%H:%MZ)) - edit freely. All paths overridable."
    # ONE RENDERING. These eight lines were re-emitted here by hand while
    # _owned_lines_new claimed in its own docstring to exist so the
    # precondition and the writer could not disagree -- a property asserted
    # and not held, and the X4_EXTENSIONS divergence above is what it hid.
    _owned_lines_new "$t"
    if [ -n "$carried" ]; then
      echo "# --- carried over from your previous x4-paths.env ---"
      printf '%s' "$carried"
    fi
  } > "$tmp" || { rm -f "$tmp"; echo "ERROR: could not write $tmp; your existing config is untouched." >&2; return 1; }

  # VERIFY THE ARTIFACT, never the exit code -- and verify it BEFORE it is live.
  # A config bash cannot source is exactly the failure the escaping above exists
  # to prevent, and proving it costs one subshell.
  if ! ( set -a; . "$tmp" ) >/dev/null 2>&1; then
    rm -f "$tmp"
    echo "ERROR: the config this run would write cannot be SOURCED by bash, so every" >&2
    echo "       X4_* would come out unset. This is a quoting fault in one of the paths." >&2
    echo "       NOTHING was changed: your existing $f is untouched." >&2
    return 1
  fi
  mv -f "$tmp" "$f" || { rm -f "$tmp"; echo "ERROR: could not install $f; your existing config is untouched." >&2; return 1; }
  echo "  wrote $f"
  if [ -n "$carried" ]; then
    echo "  [note] carried over $(printf '%s' "$carried" | grep -c .) setting(s) you had added"
  fi
  return 0
}

require_jq_for_global() {
  command -v jq >/dev/null 2>&1 && return 0
  local home_claude="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
  echo "ERROR: --method global needs jq to merge the X4_* env into $home_claude/settings.json." >&2
  echo "       Install jq (https://jqlang.github.io/jq/), or use --method separate/in-game," >&2
  echo "       which do not need it. Nothing has been changed." >&2
  exit 1
}

#: Read-only targets in the GLOBAL destination, checked BEFORE any write.
#:
#: Two defects, and the second was in both installers. (1) This tested `-w` on the
#: skill DIRECTORY, so a read-only SKILL.md inside a writable directory was
#: invisible: the run then reached the copy, `cp` failed with Permission denied, and
#: it ended "1 item(s) could not be copied ... a partial install is not recoverable"
#: -- the outcome the guard exists to prevent. install.ps1 recursed per file and
#: refused correctly, so it was a genuine divergence. (2) It lived INSIDE
#: install_global_claude, which the dispatch calls AFTER write_paths_env, so a
#: refused run had already rewritten the path config. install.ps1's own comment
#: states the rule: "refusing after the path config has already been rewritten is a
#: partial write, which is the shape of the bug rather than a fix" -- which is why
#: Assert-GlobalOverExisting sits ahead of the writer, and this now does too.
precheck_global_locked() {
  local home_claude="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
  local blocked="" _t _f
  for s in "$TOOLKIT/.claude/skills/"x4-*; do
    [ -e "$s" ] || continue
    _t="$home_claude/skills/$(basename "$s")"
    [ -d "$_t" ] || continue
    # EVERY FILE, not the directory: a directory stays writable while the file
    # inside it is read-only, which is exactly the case that got through.
    while IFS= read -r _f; do
      [ -n "$_f" ] || continue
      [ -w "$_f" ] || blocked="$blocked$_f
"
    done <<EOF
$(find "$_t" -type f 2>/dev/null)
EOF
  done
  for a in "$TOOLKIT/.claude/agents/"*.md; do
    [ -e "$a" ] || continue
    _t="$home_claude/agents/$(basename "$a")"
    [ -e "$_t" ] && [ ! -w "$_t" ] && blocked="$blocked$_t
"
  done
  if [ -n "$blocked" ]; then
    echo "REFUSING: file(s) in $home_claude are READ-ONLY and this would overwrite them." >&2
    printf '%s' "$blocked" | head -8 | sed 's/^/      /' >&2
    echo "      Unlock them, or move them aside, and re-run. Nothing has been changed." >&2
    exit 1
  fi
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
  require_jq_for_global   # ONE implementation; the arm calls it before any write

  # LOCKED TARGETS IN THIS DESTINATION TOO. precheck_locked_targets covers the
  # 16 copy items against $TOOLKIT; this arm writes to a SECOND destination that
  # neither precheck knew about, and the invariant is the same one 18b220d
  # states: refusing before either installer writes is the only answer correct
  # for both. MEASURED before this: install.ps1 CLOBBERED a read-only skill via
  # Copy-Item -Force and returned 0; install.sh skipped it and ALSO returned 0.
  mkdir -p "$home_claude/skills" "$home_claude/agents"
  local s a copied=0 failed_copies=0
  # `cp … && copied=…` is an && LIST, which `set -e` does NOT trip -- so a failed
  # copy was invisible and the run still printed "install complete" at rc 0. This
  # file already carries a comment about that exact construct for the jq merge,
  # three functions below. Counted explicitly instead.
  for s in "$TOOLKIT/.claude/skills/"x4-*; do
    [ -e "$s" ] || continue
    if cp -r "$s" "$home_claude/skills/"; then copied=$((copied + 1)); else failed_copies=$((failed_copies + 1)); fi
  done
  for a in "$TOOLKIT/.claude/agents/"*.md; do
    [ -e "$a" ] || continue
    if cp "$a" "$home_claude/agents/"; then copied=$((copied + 1)); else failed_copies=$((failed_copies + 1)); fi
  done
  if [ "$failed_copies" -gt 0 ]; then
    echo "ERROR: $failed_copies item(s) could not be copied into $home_claude." >&2
    echo "       This method keeps no backup, so a partial install is not recoverable." >&2
    exit 1
  fi
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
  # ...AND THE FILE LIST MUST BE TOOLKIT-DERIVED TOO, not just the directory list.
  # This emitted DESTINATION DIRECTORIES and then ran `grep -rl` inside them. With
  # --over-existing that directory holds the toolkit's files MERGED with the user's,
  # so a note the user kept in ~/.claude/skills/x4-balance/ was rewritten in place by
  # the sed below and `rm -f "$f.bak"` deleted the only copy: rc 0, nothing printed.
  # The rule two lines up was already right; it was applied one level too shallow --
  # toolkit-derived for directories, destination-derived for files. install.ps1 built
  # its list from $srcRoot and was never exposed, which is what named the fix.
  {
    for s in "$TOOLKIT/.claude/skills/"x4-*; do
      [ -e "$s" ] || continue
      # Every file THIS TOOLKIT SHIPS in that skill, mapped to where it was copied.
      # A user's own file has no counterpart under $TOOLKIT, so it cannot be named.
      find "$s" -type f 2>/dev/null | while read -r src; do
        echo "$home_claude/skills/${src#"$TOOLKIT/.claude/skills/"}"
      done
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
  } | while read -r f; do
    # `|| continue` on both tests is LOAD-BEARING: grep exits 1 when it matches
    # nothing, `set -o pipefail` promotes that to the pipeline's status, and `set -e`
    # then killed the whole installer. MEASURED 2026-09-01: 2 of the 7 shipped skills
    # (x4-debug, x4-probe) contain no $CLAUDE_PROJECT_DIR, so `--method global` exited
    # 1 on this very tree -- after copying skills and agents, and before writing any
    # env. A skill that needs no rewrite is the NORMAL case, not an error.
    [ -f "$f" ] || continue
    grep -q 'CLAUDE_PROJECT_DIR' "$f" 2>/dev/null || continue
    sed -i.bak 's#\$CLAUDE_PROJECT_DIR#$X4_TOOLKIT#g' "$f" && rm -f "$f.bak"
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
  # BACKED UP FIRST. This rewrites the user's GLOBAL Claude settings, and it was the
  # one write in either installer with no backup at all -- copy_toolkit and
  # write_paths_env both take one, and install.ps1 now does too. A settings.json
  # carries hand-added keys (this machine's has many), and `/model` is documented as
  # dropping them, so an unbacked rewrite here is not recoverable from anywhere.
  if [ -f "$sj" ]; then
    if ! cp "$sj" "$sj.bak-$(date +%Y%m%d-%H%M%S)" 2>/dev/null; then
      echo "ERROR: could not back up $sj. Refusing to rewrite it." >&2
      exit 1
    fi
  else
    echo '{}' > "$sj"
  fi
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
#: Says WHERE, and nothing else. It used to also perform the dry-run exit with a
#: listing of the items a copy would move -- two unrelated jobs, and because the
#: second only makes sense where a copy happens, the first was wired into the COPY
#: branch too. So `global`, and a `separate` install landing in place, reached the
#: config writer without ever saying where they were writing, while the CHANGELOG
#: claimed the destination is printed 'in every mode'.
announce_target() {
  echo
  echo "  About to write the toolkit into:"
  echo "      $1"
}

#: The dry-run listing, for the arms where a COPY would actually happen. The gate
#: itself does not depend on this: refuse_if_dry_run sits inside all three writers,
#: so an arm that copies nothing still stops before it writes.
announce_copy_plan() {
  [ "$DRY_RUN" = 1 ] || return 0
  echo "  --dry-run: nothing will be written. Items that would be copied:"
  local item
  for item in $X4_COPY_ITEMS; do
    [ -e "$SRC/$item" ] && echo "      $item"
  done
  echo
  echo "=== dry run complete: nothing was changed ==="
  exit 0
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
    announce_target "$TOOLKIT"
    # ORDER, and each position is load-bearing for a different reason:
    #   require_direction     FIRST, and only when a copy will happen. Both
    #                         prechecks can exit 1 telling the user to unlock and
    #                         re-run -- against a destination they never named,
    #                         when Steam detection picked it. The refusal they
    #                         should see is "you did not name this". Neither
    #                         precheck writes, so this was a wrong MESSAGE rather
    #                         than a wrong outcome.
    #   precheck_config       OUTSIDE the copy guard: the config is written on
    #                         BOTH branches, so an in-place upgrade skipped the
    #                         only check in front of it and the orphaned .bak
    #                         came back.
    #   precheck_locked_targets INSIDE: with no copy there is nothing to
    #                         overwrite, and checking anyway refuses an in-place
    #                         run for no reason.
    if ! same_dir "$SRC" "$TOOLKIT"; then
      require_direction "$TOOLKIT" "$GAME_NAMED"
    fi
    precheck_config "$TOOLKIT"
    if ! same_dir "$SRC" "$TOOLKIT"; then
      precheck_locked_targets "$TOOLKIT"
      announce_copy_plan
      copy_toolkit "$TOOLKIT"
    fi
    write_paths_env "$TOOLKIT"
    ;;
  separate)
    [ -n "$TOOLKIT" ] || TOOLKIT="$SRC"
    ask TOOLKIT "Toolkit folder" "$TOOLKIT"
    TOOLKIT="$(strip_trailing_sep "$TOOLKIT")"
    announce_target "$TOOLKIT"
    # ORDER, and each position is load-bearing for a different reason:
    #   require_direction     FIRST, and only when a copy will happen. Both
    #                         prechecks can exit 1 telling the user to unlock and
    #                         re-run -- against a destination they never named,
    #                         when Steam detection picked it. The refusal they
    #                         should see is "you did not name this". Neither
    #                         precheck writes, so this was a wrong MESSAGE rather
    #                         than a wrong outcome.
    #   precheck_config       OUTSIDE the copy guard: the config is written on
    #                         BOTH branches, so an in-place upgrade skipped the
    #                         only check in front of it and the orphaned .bak
    #                         came back.
    #   precheck_locked_targets INSIDE: with no copy there is nothing to
    #                         overwrite, and checking anyway refuses an in-place
    #                         run for no reason.
    if ! same_dir "$SRC" "$TOOLKIT"; then
      require_direction "$TOOLKIT" "$TOOLKIT_NAMED"
    fi
    precheck_config "$TOOLKIT"
    if ! same_dir "$SRC" "$TOOLKIT"; then
      precheck_locked_targets "$TOOLKIT"
      announce_copy_plan
      copy_toolkit "$TOOLKIT"
    fi
    write_paths_env "$TOOLKIT"
    ;;
  global)
    [ -n "$TOOLKIT" ] || TOOLKIT="$SRC"
    announce_target "$TOOLKIT"
    # THE GLOBAL DESTINATION WAS NEVER GATED. `require_direction` is called for
    # in-game and separate and never here, and `looks_installed` was never asked about
    # $HOME/.claude -- so `--over-existing` could not gate a method that copies skills
    # and agents in and rewrites settings.json.
    #
    # NOT routed through require_direction: that refusal is about a destination that
    # came from SCANNING (the Steam locations), and ~/.claude is a fixed, well-known
    # path, so its reasoning does not transfer. What does transfer is the
    # over-existing rule, and the backup below.
    _hc="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
    # AGENTS TOO. This gate enumerated skills only, while the global install copies
    # every <toolkit>/.claude/agents/*.md over the destination -- so a user's own
    # edited ~/.claude/agents/mod-research.md was replaced with no prompt, no
    # --over-existing, no backup, and rc 0. Raised by the v3.1.0 release reviewer,
    # who measured it against install.ps1; install.sh had the identical gap, so this
    # is NOT one of the "fixed in bash, absent in PowerShell" class -- both halves
    # gated half their destination.
    #
    # Only files this install would actually WRITE are named: an unrelated agent of
    # the user's own is not at risk and must not be listed as though it were.
    _hits=""
    _NL='
'
    # ENUMERATED FROM THE TOOLKIT, then checked against the destination -- the shape
    # the agents leg below already uses, and the property the comment above already
    # claims. This globbed the DESTINATION, so a user's own `x4-mycustom/` was listed
    # as a file the install "would REPLACE" and the run refused until they passed
    # --over-existing, against a directory this installer never touches. The comment
    # was right and the code was one enumeration away from it.
    if [ -d "$_hc/skills" ] && [ -d "$TOOLKIT/.claude/skills" ]; then
      for _s in "$TOOLKIT/.claude/skills/"x4-*; do
        [ -e "$_s" ] || continue
        [ -e "$_hc/skills/$(basename "$_s")" ] &&
          _hits="$_hits      skills/$(basename "$_s")$_NL"
      done
    fi
    if [ -d "$_hc/agents" ] && [ -d "$TOOLKIT/.claude/agents" ]; then
      for _a in "$TOOLKIT/.claude/agents/"*.md; do
        [ -e "$_a" ] || continue
        [ -e "$_hc/agents/$(basename "$_a")" ] &&
          _hits="$_hits      agents/$(basename "$_a")$_NL"
      done
    fi
    if [ -n "$_hits" ] && [ "$OVER_EXISTING" != 1 ]; then
      echo "REFUSING: $_hc already carries files this install would REPLACE." >&2
      printf '%s' "$_hits" >&2
      echo "  Re-run with --over-existing to replace them, after checking you have not" >&2
      echo "  edited them in place. This method also rewrites $_hc/settings.json." >&2
      exit 2
    fi
    # BEFORE the first write. `install_global_claude` checks jq at its own top and
    # exits 1 saying "Nothing has been changed." -- but `write_paths_env` has already
    # rewritten x4-paths.env by then, so on a machine without jq the user was told
    # nothing changed while their live config had been regenerated. The message was
    # true of the function and false of the run.
    require_jq_for_global
    precheck_global_locked       # BEFORE the config write, not inside the copier
    precheck_config "$TOOLKIT"   # --method global writes the config and never copied
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

# A BACKSTOP, and today it is UNREACHED -- stated rather than implied. Every
# dispatch arm ends in a writer whose first statement is `refuse_if_dry_run`,
# which exits 0, so control does not arrive here on any path measured (all three
# arms, both installers: this branch printed zero times). It is kept because the
# writers' gate covering these two is an accident of ORDERING rather than a
# property: setup.sh and bin/unpack-reference.sh are invoked at TOP LEVEL,
# outside all three writers, so any future arm not ending in a writer would run
# them under --dry-run. Dead today, correct tomorrow -- and nobody should read it
# as the thing currently doing the work. refuse_if_dry_run's
# own docstring claimed "every write goes through" those three; it does not, and
# these two are the counter-example. A dry run that syncs dependencies or unpacks
# 60 GB of game archives is not a preview.
if [ "$DRY_RUN" = 1 ]; then
  echo "  --dry-run: NOT running setup.sh"
else
( cd "$TOOLKIT" && CLAUDE_PROJECT_DIR="$TOOLKIT" bash setup.sh ) || add_failed "setup.sh"
fi

if [ "$DO_UNPACK" = 1 ] && [ "$DRY_RUN" = 1 ]; then
  echo "  --dry-run: NOT unpacking reference/"
elif [ "$DO_UNPACK" = 1 ]; then
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

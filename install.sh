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
METHOD=""; ASSUME_YES=0; DO_UNPACK=0
GAME="${X4_GAME:-}"; PROFILE="${X4_PROFILE:-}"; TOOLKIT="${X4_TOOLKIT:-}"
MODS="${X4_MODS:-}"; REFERENCE="${X4_REFERENCE:-}"; EXTENSIONS="${X4_EXTENSIONS:-}"
XRCAT="${XRCATTOOL:-}"

usage() {
  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
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
  --yes              don't prompt; accept detected/blank values
  -h, --help         this help
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --method) METHOD="$2"; shift 2;;
    --game) GAME="$2"; shift 2;;
    --profile) PROFILE="$2"; shift 2;;
    --toolkit) TOOLKIT="$2"; shift 2;;
    --mods) MODS="$2"; shift 2;;
    --reference) REFERENCE="$2"; shift 2;;
    --extensions) EXTENSIONS="$2"; shift 2;;
    --xrcattool) XRCAT="$2"; shift 2;;
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
  for root in $(steam_roots); do
    [ -d "$root/steamapps/common/X4 Foundations" ] && { GAME="$root/steamapps/common/X4 Foundations"; return 0; }
    vdf="$root/steamapps/libraryfolders.vdf"
    [ -f "$vdf" ] || continue
    while IFS= read -r lib; do
      [ -d "$lib/steamapps/common/X4 Foundations" ] && { GAME="$lib/steamapps/common/X4 Foundations"; return 0; }
    done < <(grep -oE '"path"[[:space:]]*"[^"]+"' "$vdf" | sed -E 's/.*"path"[[:space:]]*"([^"]+)"/\1/')
  done
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

copy_toolkit() {  # copy_toolkit DEST  — copy tracked toolkit files (never game data / local config)
  local dest="$1"; mkdir -p "$dest"
  local item
  for item in .claude tools bin scripts CLAUDE.md KNOWLEDGEBASE.md README.md CHANGELOG.md \
              LICENSE setup.sh install.sh install.ps1 SETUP_PROMPT.txt .gitignore .gitattributes; do
    [ -e "$SRC/$item" ] || continue
    cp -r "$SRC/$item" "$dest/"
  done
  rm -f "$dest/.claude/settings.local.json" "$dest/.claude/x4-paths.env" 2>/dev/null || true
}

write_paths_env() {  # write_paths_env TOOLKIT_DIR
  local t="$1" f="$1/.claude/x4-paths.env"
  mkdir -p "$1/.claude"
  {
    echo "# Written by install.sh ($(date -u +%Y-%m-%dT%H:%MZ)) — edit freely. All paths overridable."
    echo "X4_TOOLKIT=\"$t\""
    [ -n "$GAME" ]       && echo "X4_GAME=\"$GAME\""
    echo "X4_REFERENCE=\"${REFERENCE:-$t/reference}\""
    [ -n "$PROFILE" ]    && echo "X4_PROFILE=\"$PROFILE\""
    [ -n "$PROFILE" ]    && echo "X4_DEBUGLOG=\"$PROFILE/debug.txt\""
    [ -n "$MODS" ]       && echo "X4_MODS=\"$MODS\""
    echo "X4_EXTENSIONS=\"${EXTENSIONS:-${GAME:+$GAME/extensions}}\""
    [ -n "$XRCAT" ]      && echo "XRCATTOOL=\"$XRCAT\""
  } > "$f"
  echo "  wrote $f"
}

install_global_claude() {  # copy skills/agents to ~/.claude and write X4_* env into settings.json
  local home_claude="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
  mkdir -p "$home_claude/skills" "$home_claude/agents"
  local s
  for s in "$TOOLKIT/.claude/skills/"x4-*; do [ -e "$s" ] && cp -r "$s" "$home_claude/skills/"; done
  cp "$TOOLKIT/.claude/agents/"*.md "$home_claude/agents/" 2>/dev/null || true
  # global skills/agents run from any repo → resolve the validator via $X4_TOOLKIT, not $CLAUDE_PROJECT_DIR
  grep -rl 'CLAUDE_PROJECT_DIR' "$home_claude/skills/"x4-* "$home_claude/agents/"*.md 2>/dev/null \
    | while read -r f; do sed -i.bak 's#\$CLAUDE_PROJECT_DIR#$X4_TOOLKIT#g' "$f" && rm -f "$f.bak"; done
  echo "  installed x4 skills + agents into $home_claude"
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
  echo "  merged X4_* env into $sj"
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

case "$METHOD" in
  in-game)
    [ -n "$GAME" ] || { echo "ERROR: in-game needs --game"; exit 1; }
    TOOLKIT="$GAME"
    [ "$SRC" = "$TOOLKIT" ] || copy_toolkit "$TOOLKIT"
    write_paths_env "$TOOLKIT"
    ;;
  separate)
    [ -n "$TOOLKIT" ] || TOOLKIT="$SRC"
    ask TOOLKIT "Toolkit folder" "$TOOLKIT"
    [ "$SRC" = "$TOOLKIT" ] || copy_toolkit "$TOOLKIT"
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
( cd "$TOOLKIT" && CLAUDE_PROJECT_DIR="$TOOLKIT" bash setup.sh ) || true

if [ "$DO_UNPACK" = 1 ]; then
  echo "Unpacking reference/ ..."
  ( cd "$TOOLKIT" && CLAUDE_PROJECT_DIR="$TOOLKIT" bash bin/unpack-reference.sh )
fi

echo
echo "=== install complete ($METHOD) ==="
echo "Toolkit:   $TOOLKIT"
echo "Config:    $TOOLKIT/.claude/x4-paths.env  (edit any path here)"
[ "$METHOD" = global ] && echo "Global:    skills/agents + X4_* env added to your ~/.claude — works from any mod repo."
echo "Next:      set X4_GAME if blank, then  (cd \"$TOOLKIT\" && bash bin/unpack-reference.sh)  to build reference/."

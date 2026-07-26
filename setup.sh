#!/bin/bash
# X4 Foundations Claude Code Modding Toolkit — setup (cross-platform: Linux / macOS / Windows Git Bash)
# Checks prerequisites, wires up the bundled x4validate, and seeds local config. Idempotent.

set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
echo "=== X4 Claude Code Modding Toolkit setup ==="
echo "Toolkit root: $ROOT"
echo

ok()   { echo "  [ok]   $*"; }
warn() { echo "  [warn] $*"; }

# --- detect OS for install hints ------------------------------------------
case "$(uname -s 2>/dev/null)" in
  Linux*)                 OS=linux;   PKG="your package manager (e.g. sudo pacman -S jq / sudo apt install jq / sudo dnf install jq)";;
  Darwin*)                OS=macos;   PKG="brew install jq";;
  MINGW*|MSYS*|CYGWIN*)   OS=windows; PKG="winget install jqlang.jq";;
  *)                      OS=unknown; PKG="your package manager";;
esac
echo "Detected OS: $OS"
echo

# --- 1. prerequisites ------------------------------------------------------
echo "1) Checking prerequisites..."
if command -v jq >/dev/null 2>&1; then ok "jq found"; else
  warn "jq not found — install with: $PKG  (then restart your shell)"; fi

if command -v uv >/dev/null 2>&1; then ok "uv found"; else
  warn "uv not found — install from https://docs.astral.sh/uv/ (powers x4validate / Python 3.13)"; fi

if [ "$OS" != "windows" ]; then
  if command -v wine >/dev/null 2>&1; then ok "wine found (needed to run XRCatTool on $OS)"; else
    warn "wine not found — needed to run Egosoft's XRCatTool on $OS (bin/xrcat). Install it via $PKG-equivalent."; fi
fi

# --- 2. x4validate ---------------------------------------------------------
echo
echo "2) Setting up bundled x4validate..."
X4V="$ROOT/tools/x4validate"
if [ -d "$X4V" ] && command -v uv >/dev/null 2>&1; then
  ( cd "$X4V" && uv sync >/dev/null 2>&1 ) && ok "x4validate dependencies synced (uv)" \
    || warn "uv sync failed — run it manually:  cd tools/x4validate && uv sync"
  echo "     test it:  cd tools/x4validate && uv run pytest -q"
  echo "     run it:   cd tools/x4validate && uv run x4validate <your_mod>"
else
  warn "skipped (need uv + tools/x4validate)"
fi

# --- 3. local settings + path config --------------------------------------
echo
echo "3) Local settings & path config..."
LOCAL="$ROOT/.claude/settings.local.json"
EXAMPLE="$ROOT/.claude/settings.local.json.example"
if [ -f "$LOCAL" ]; then ok "settings.local.json already present"
elif [ -f "$EXAMPLE" ]; then cp "$EXAMPLE" "$LOCAL"; ok "created settings.local.json from example (gitignored)"
else warn "no settings.local.json.example to copy"; fi

CFG="$ROOT/.claude/x4-paths.env"
CFG_EX="$ROOT/.claude/x4-paths.env.example"
if [ -f "$CFG" ]; then ok "x4-paths.env already present"
elif [ -f "$CFG_EX" ]; then cp "$CFG_EX" "$CFG"; ok "created x4-paths.env from example (gitignored) — edit it to point at your game/profile"
else warn "no x4-paths.env.example to copy"; fi
echo "     For a guided install (game folder / separate dir / global multi-repo) run:  bash install.sh   (or install.ps1 on Windows)"

# --- 4. reference tree (your own game data — never redistributed) ----------
echo
echo "4) Base-game reference (you unpack your OWN copy):"
echo "   Set X4_GAME in .claude/x4-paths.env, then:  bash bin/unpack-reference.sh"
echo "   (text-only unpack via XRCatTool → reference/, ~0.6 GB; gitignored, never redistributed.)"

# --- 5. Nexus API (optional, your own key) ---------------------------------
echo
echo "5) Nexus mod triage (optional): x4modlist uses the official Nexus API with YOUR OWN free key."
echo "   Get one at https://www.nexusmods.com/users/myaccount?tab=api then set X4_NEXUS_KEY:"
if [ "$OS" = "windows" ]; then
  echo "       setx X4_NEXUS_KEY \"<your-key>\"          (or add it to .claude/x4-paths.env)"
else
  echo "       export X4_NEXUS_KEY=\"<your-key>\"        (add to your shell rc, or to .claude/x4-paths.env)"
fi

echo
echo "=== setup complete ==="
echo "Open Claude Code in this folder and start modding. See README.md for examples."

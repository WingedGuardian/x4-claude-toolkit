#!/bin/bash
# X4 Foundations Claude Code Modding Toolkit — setup
# Checks prerequisites, wires up the bundled x4validate, and personalizes local paths.
# Safe to re-run (idempotent).

set -uo pipefail
ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
echo "=== X4 Claude Code Modding Toolkit setup ==="
echo "Toolkit root: $ROOT"
echo

ok()   { echo "  [ok]   $*"; }
warn() { echo "  [warn] $*"; }

# --- 1. prerequisites ------------------------------------------------------
echo "1) Checking prerequisites..."
if command -v jq >/dev/null 2>&1; then ok "jq found"; else
  warn "jq not found — install with:  winget install jqlang.jq   (then restart your shell)"; fi

if command -v uv >/dev/null 2>&1; then ok "uv found"; else
  warn "uv not found — install from https://docs.astral.sh/uv/ (powers x4validate / Python 3.13)"; fi

# --- 2. x4validate ---------------------------------------------------------
echo
echo "2) Setting up bundled x4validate..."
X4V="$ROOT/tools/x4validate"
if [ -d "$X4V" ] && command -v uv >/dev/null 2>&1; then
  ( cd "$X4V" && uv sync >/dev/null 2>&1 ) && ok "x4validate dependencies synced (uv)" \
    || warn "uv sync failed — run it manually:  cd tools/x4validate && uv sync"
  echo "     test it:  cd tools/x4validate && uv run pytest -q"
  echo "     run it:   cd tools/x4validate && uv run x4validate <dev/your_mod>"
else
  warn "skipped (need uv + tools/x4validate)"
fi

# --- 3. local settings -----------------------------------------------------
echo
echo "3) Local settings..."
LOCAL="$ROOT/.claude/settings.local.json"
EXAMPLE="$ROOT/.claude/settings.local.json.example"
if [ -f "$LOCAL" ]; then ok "settings.local.json already present"
elif [ -f "$EXAMPLE" ]; then cp "$EXAMPLE" "$LOCAL"; ok "created settings.local.json from example (gitignored)"
else warn "no settings.local.json.example to copy"; fi

# --- 4. reference tree (your own game data — never redistributed) ----------
echo
echo "4) Base-game reference (you unpack your OWN copy):"
echo "   X4 stores content in 01.cat/01.dat … 09.cat/09.dat. Unpack to a local reference/"
echo "   folder with Egosoft's XRCatTool, then point x4validate at it:"
echo "       export X4_REFERENCE=\"/path/to/your/reference\""
echo "   The toolkit ships NO game data and the reference/ folder is gitignored."

# --- 5. Nexus API (optional, your own key) ---------------------------------
echo
echo "5) Nexus mod triage (optional):"
echo "   x4modlist uses the official Nexus API with YOUR OWN free key."
echo "   Get one at https://www.nexusmods.com/users/myaccount?tab=api then:"
echo "       setx X4_NEXUS_KEY \"<your-key>\"     # never commit or share it"

echo
echo "=== setup complete ==="
echo "Open Claude Code in this folder and start modding. See README.md for examples."

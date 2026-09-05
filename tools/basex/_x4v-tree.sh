#!/usr/bin/env bash
# Resolve WHICH x4validate checkout drives a BaseX build -- and say so out loud.
#
# WHY THIS EXISTS.  Both build scripts defaulted X4VALIDATE_DIR to "$HERE/../x4validate",
# and `staleness.py::_defaults()` does the same. That path is a *position*, not an identity:
# when several checkouts of x4validate exist side by side (git worktrees, one per concurrent
# session), whichever one happens to occupy `tools/x4validate` supplies the ENGINE bytes that
# get hashed into the artifact's freshness fingerprint. A build launched from one tree could
# therefore stamp the artifact with a DIFFERENT tree's engine identity, silently.
#
# MEASURED 2026-08-29 on the machine where this was written: two checkouts existed and all 7
# ENGINE_SOURCES were byte-identical, so the fingerprint was correct by luck. The defect is
# latent, not active -- which is exactly when it is cheap to close.
#
# The fix is to make the choice VISIBLE, and to refuse only when it is genuinely AMBIGUOUS.
# A normal install has one checkout, so the refusal below can never fire for it.

# x4v_resolve <basex_dir> -> prints the chosen x4validate root, or exits 2 if ambiguous.
x4v_resolve() {
  local here="$1" cand found="" n=0

  if [ -n "${X4VALIDATE_DIR:-}" ]; then
    printf '%s' "$X4VALIDATE_DIR"
    return 0
  fi

  # A sibling only counts if it really is an engine checkout. Matching the NAME alone would
  # make a stray `x4validate-backup/` or an editor's `x4validate.orig/` look like a rival
  # and refuse a build that was never ambiguous.
  for cand in "$here"/../x4validate*; do
    [ -d "$cand" ] || continue
    [ -f "$cand/x4validate/_merge.py" ] || continue
    n=$((n + 1))
    found="$cand"
  done

  if [ "$n" -gt 1 ]; then
    {
      echo "REFUSING: $n x4validate checkouts sit beside $here, and X4VALIDATE_DIR is unset."
      echo "  The freshness fingerprint hashes the ENGINE BYTES of whichever tree is used, so"
      echo "  building without choosing would stamp this artifact with an arbitrary tree's"
      echo "  identity -- and a wrong engine hash reads as FRESH, not as an error."
      echo "  Candidates:"
      for cand in "$here"/../x4validate*; do
        [ -d "$cand" ] && [ -f "$cand/x4validate/_merge.py" ] && echo "    $(cd "$cand" && pwd)"
      done
      echo "  Set X4VALIDATE_DIR to the one you mean, e.g."
      echo "    X4VALIDATE_DIR=/path/to/your/x4validate bash $(basename "${BASH_SOURCE[1]:-build}")"
    } >&2
    exit 2
  fi

  # 0 candidates: keep the historical default so preflight reports the real problem
  # (a missing tree) rather than this helper inventing a different one.
  #
  # The REASON is recorded here, where it is known, rather than guessed by the
  # announce below. The glob is `x4validate*`, so the single surviving candidate can
  # be a differently-named sibling -- and "chosen by default position
  # (tools/x4validate)" then names a directory that was not chosen and may not exist.
  # The absolute path is printed either way so nothing was ever WRONG on screen, but
  # this helper exists to make provenance auditable and a reason line that can name
  # the wrong tree is the part that gets quoted later.
  [ "$n" -eq 1 ] && printf '%s' "$found" || printf '%s' "$here/../x4validate"
}

# x4v_announce <resolved_dir> -- state the tree in the build log, always.
# Printing this unconditionally is the half with real value: a build whose provenance is
# in its own output can be audited afterwards; one that resolved silently cannot.
x4v_announce() {
  local dir="$1" abs branch head
  abs="$(cd "$dir" 2>/dev/null && pwd)" || abs="$dir"
  echo "== engine tree =="
  echo "   $abs"
  # The reason is DERIVED from the resolved directory, not carried from the resolver:
  # every caller writes `X4VALIDATE="$(x4v_resolve "$HERE")"`, and a command
  # substitution is a subshell, so a variable the resolver set would never arrive here.
  # A first cut did exactly that and would have printed "unrecorded path" on every real
  # build -- strictly worse than the message it replaced.
  #
  # What was wrong: the candidate glob is `x4validate*`, so the single survivor can be a
  # differently-named sibling, and "chosen by default position (tools/x4validate)" then
  # named a directory that was not chosen and need not exist. The absolute path above is
  # right either way, so nothing on screen was ever false -- but this helper exists to
  # make provenance auditable, and the reason line is the half that gets quoted later.
  if [ -n "${X4VALIDATE_DIR:-}" ]; then
    echo "   chosen by X4VALIDATE_DIR"
  elif [ ! -f "$abs/x4validate/_merge.py" ]; then
    # The 0-candidate fallback. Say it is a fallback: preflight will report the missing
    # tree, and a line claiming this was CHOSEN would be the confident half of that.
    echo "   NO engine checkout matched ${dir%/*}/x4validate* -- this is the historical"
    echo "   default position, a fallback rather than a find; set X4VALIDATE_DIR"
  elif [ "${abs##*/}" = "x4validate" ]; then
    echo "   chosen by default position (tools/x4validate); set X4VALIDATE_DIR to override"
  else
    echo "   chosen as the only engine checkout matching x4validate* (${abs##*/});"
    echo "   set X4VALIDATE_DIR to override"
  fi
  if branch=$(cd "$abs" 2>/dev/null && git rev-parse --abbrev-ref HEAD 2>/dev/null); then
    head=$(cd "$abs" && git rev-parse --short HEAD 2>/dev/null)
    echo "   git: $branch @ $head"
  fi
}

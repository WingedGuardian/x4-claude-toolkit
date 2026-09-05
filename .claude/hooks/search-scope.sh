#!/bin/bash
# PreToolUse (Grep|Glob): a content search under the game's extensions/ folder returns a
# PARTIAL answer that looks complete.
#
# WHY. X4 mods ship as packed `.cat`/`.dat` archives, loose XML, or BOTH. Grep and Glob read
# loose files only. So a search over a mod that ships a .cat does not fail and does not say
# "some content was unreadable" -- it returns the loose subset, silently, in the same shape a
# complete answer would have. MEASURED on the reference machine: of 133 installed mods, 54
# (41%) ship a .cat AND loose XML, so the misleading case is the COMMON one, not an edge.
#
# The cost is documented: two sessions of a real investigation were spent on a `No matches`
# that meant "that mod is packed", not "the string is absent". The routing table in CLAUDE.md
# already said so and did not prevent it, which is the argument for a hook rather than a
# sentence -- a rule you have to remember is not a control.
#
# DELIBERATELY NARROW, because a guard that fires on ordinary work gets bypassed:
#   * a DIRECTORY target only. Searching one named file is not a survey and cannot mislead.
#   * that directory must be the extensions root, or sit inside a mod that actually ships a
#     .cat. A loose-only mod is fully visible to Grep and must not prompt.
# MEASURED against 21 transcripts / 311 Grep calls: this fires on 4 of them.
JQ="${JQ:-jq}"
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$HOOK_DIR/_x4-env.sh"

# ADVISE, never ask. A partial-answer warning is about MY instrument choice, so it
# must cost me a note and the user nothing. Renamed from ask() 2026-08-29, when
# fixing the stdin defect turned five newly-live hooks into a prompt storm.
advise() { x4_advise "$1"; exit 0; }   # shared emitter: survives a missing jq

INPUT=$(x4_hook_input)
# ADVISE, never ask -- this file's own header says so, and it escalated to a PROMPT on
# every Grep/Glob if the stdin defect ever recurred. A partial-answer warning is about
# MY instrument choice: it must cost me a note and the user nothing.
# x4validate-on-edit.sh makes the same (correct) call for the same situation.
if [ -z "$INPUT" ]; then
  x4_advise "X4 SEARCH-SCOPE INERT: this hook received NO INPUT, so it checked nothing. Your search may be reading a partial picture (packed mods are invisible to a text search). Nothing is blocked."
  exit 0
fi
# COULD WE READ THIS PAYLOAD AT ALL? `x4_field` returns empty for "field absent" AND
# for "could not parse", and its own docstring concedes it -- but the INERT branch
# three lines above is proof this hook has something to say about the second. Probing
# a field that is always present separates them. MEASURED 2026-09-05: a truncated
# payload produced 0 bytes and silence, where an EMPTY one produced 288 bytes of INERT.
# Same condition, opposite reporting.
if [ -z "$(x4_field "$INPUT" 'tool_name')" ]; then
  x4_advise "X4 SEARCH-SCOPE INERT: this payload could not be parsed, so the hook checked NOTHING. Your search may be reading a partial picture (packed mods are invisible to a text search). Nothing is blocked."
  exit 0
fi
FP=$(x4_field "$INPUT" 'tool_input.path')   # shared reader: survives a missing jq
[ -z "${X4_EXTENSIONS:-}" ] && exit 0

# NO PATH AT ALL is the BROADEST search, not the narrowest. Grep/Glob without `path`
# search the cwd -- and the cwd for this project IS the game root, a strict superset
# of extensions/. This exited silently while a narrower search rooted INSIDE
# extensions/ advised, so coverage was inverted with respect to breadth. MEASURED over
# 26 transcripts / 397 Grep+Glob calls: 6 no-path and 4 above-extensions, all
# unguarded, against 15 that fired.
if [ -z "$FP" ]; then
  advise "PARTIAL ANSWER: this search names no path, so it runs from the working directory -- which here contains the whole extensions/ folder. A text search reads LOOSE files only, so mods shipping .cat archives are invisible and a 'no matches' means 'not found in the loose subset', NOT 'absent'. Use _scan.iter_corpus_xml (packed-inclusive) for a corpus sweep, or confirm you want the loose-only view."
fi

# Pure-string prefilter first: the overwhelming majority of searches are nowhere near the
# game folder, and they must not pay for a filesystem probe.
nFP="$(x4_norm "$FP")"; nFP="${nFP%/}"
nEXT="$(x4_norm "$X4_EXTENSIONS")"; nEXT="${nEXT%/}"
# A search root that CONTAINS extensions/ (the game root, or any ancestor) covers a
# strict superset of it -- including every packed mod -- and was exiting silently
# while the subset advised.
case "$nEXT" in
  "$nFP"/*)
    advise "PARTIAL ANSWER: this search is rooted ABOVE the extensions/ folder, so it covers every installed mod -- and a text search reads LOOSE files only. Mods shipping .cat archives are invisible to it, so a 'no matches' here means 'not found in the loose subset', NOT 'absent'. Use _scan.iter_corpus_xml (packed-inclusive) for a corpus sweep, or confirm you want the loose-only view."
    ;;
esac
case "$nFP" in
  "$nEXT"|"$nEXT"/*) ;;
  *) exit 0 ;;
esac

# A literal backslash cannot be written safely through every layer that touches this
# file, so it is built from its byte value. MEASURED 2026-08-29: writing it as an
# escaped pair collapsed to a single backslash, turning this substitution into
# "delete every forward slash" -- the path became C:Program Files... and the hook
# silently never fired. Every must-fire probe went red and every must-NOT-fire probe
# went green, which is what an inert guard looks like.
BS=$(printf '\134')
F="${FP//"$BS"//}"
[ -d "$F" ] || exit 0            # a single file is not a survey

if [ "$nFP" = "$nEXT" ]; then
  advise "PARTIAL ANSWER: a search rooted at the whole extensions/ folder reads LOOSE files only. Mods that ship .cat archives are invisible to it, so a 'no matches' here means 'not found in the loose subset', NOT 'absent'. Use _scan.iter_corpus_xml (packed-inclusive) for a corpus sweep, or confirm you want the loose-only view."
fi

# Which mod folder is this inside? First path component under extensions/.
REL="${nFP#"$nEXT"/}"
MOD="${REL%%/*}"
[ -z "$MOD" ] && exit 0

# Resolve the mod folder against the REAL (un-normalised) extensions root so the .cat probe
# looks at the actual directory, not a lowercased string.
EXTDIR="${X4_EXTENSIONS//"$BS"//}"
for c in "$EXTDIR/$MOD"/*.cat; do
  if [ -e "$c" ]; then
    advise "PARTIAL ANSWER: '$MOD' ships packed .cat archives as well as loose files, and this search reads LOOSE files only. A zero result here is 'not in the loose subset', NOT 'absent'. Use _scan.iter_mod_xml_bytes / _scan.iter_corpus_xml to include packed content, or confirm you want the loose-only view."
  fi
done
exit 0

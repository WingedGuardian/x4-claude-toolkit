#!/bin/bash
# Shared classifier for scan-identifiers.py's exit code -- one implementation, so
# "was this a LEAK or a scanner FAILURE" cannot be decided two different ways in
# two different places.
#
# MEASURED: a scan-identifiers.py hung by the TMP-length bug (see test-hooks.sh's
# own SBX_TMP rename and its header comment) and then killed with `taskkill /F`
# exits 1 with NO stdout at all -- the SAME rc scan-identifiers.py uses for "a
# personal identifier reached a tracked file" (its main() prints one or more
# `::error file=<path>,line=<n>::` lines and then returns 1). rc alone cannot tell
# the two apart, so reading rc==1 as "leak" misattributes a kill (or any other
# rc-1 crash with no evidence) as a finding -- test-hooks.sh reported "FAIL a
# personal identifier reached a tracked file" for a process someone had just
# killed to end a hang.
#
# So the rule is: a real finding ALWAYS prints at least one `::error file=` line.
# Anything else -- rc 1 with no such line, rc 2, or any other non-zero rc -- is
# "could not confirm a finding", not "found something".
#
# classify_scan_result <rc> <captured stdout+stderr of scan-identifiers.py>
#   echoes exactly one of: clean | leak | unknown
classify_scan_result() {
  local rc="$1" out="$2"
  if [ "$rc" -eq 0 ]; then
    echo clean
    return
  fi
  if printf '%s' "$out" | grep -q '::error file='; then
    echo leak
    return
  fi
  echo unknown
}

# classify_selftest_result <rc> <captured stdout+stderr of scan-identifiers.py --selftest>
#   echoes exactly one of: pass | fail | unknown
#
# The same positive-evidence rule, for the selftest. scan-identifiers.py refuses
# BEFORE --selftest when the caller's TMP is too long to spawn safely (rc 2), and
# test-hooks.sh reported that refusal as "selftest FAILED" -- a selftest that never
# ran has not failed. A real failure is rc 1 WITH the selftest's own summary line;
# anything else is "could not run".
classify_selftest_result() {
  local rc="$1" out="$2"
  if [ "$rc" -eq 0 ]; then
    echo pass
    return
  fi
  if [ "$rc" -eq 1 ] && printf '%s' "$out" | grep -q 'selftest: [0-9]*/[0-9]* passed'; then
    echo fail
    return
  fi
  echo unknown
}

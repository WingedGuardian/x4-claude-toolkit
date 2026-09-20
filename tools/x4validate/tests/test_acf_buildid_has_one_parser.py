"""ONE reader for the Steam app manifest's build id.

A real `appmanifest_392160.acf` carries more than one `"buildid"` key: the INSTALLED
build directly under `AppState`, and one per beta branch under `PrivateDepots`.
MEASURED 2026-09-14 on the reference machine: AppState 23660954, `public_beta` 23524486.

Two hand-rolled greps read it and disagreed. `bin/unpack-reference.sh` took the LAST
match, so the next re-unpack would have stamped the BETA's build into the lock sentinel,
and the SessionStart hook would then have announced a stale `reference/` at every
session start. `check-reference-version.sh` took the FIRST, which is right only while
Steam writes AppState's key above the branches. The hook suite's fixture manifest had a
single buildid, so neither shape could go red.

Both now call `x4_acf_buildid` in `.claude/hooks/_x4-env.sh`, which reads the key at
depth 1. Its behaviour is probed in `scripts/test-hooks.sh` (both key orders); this file
stops a third hand-rolled copy from appearing.

⚠ The pattern below carries its own hits/misses fixture, checked before it is used.
MEASURED by the release review 2026-09-20: the original `grep[^\n]*'"buildid"'` matched
2 of 6 realistic re-implementations and missed an escaped-quote grep, an awk field
split and a sed extraction — an inert pattern reporting a comfortable zero, which is the
shape `gates/instrument_hygiene.py` makes every one of its own patterns prove against.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HELPER = REPO / ".claude" / "hooks" / "_x4-env.sh"

#: Any hand-rolled read of the acf's QUOTED key, in whatever tool. The sentinel is read
#: with an UNQUOTED `buildid` pattern (`check-reference-version.sh`), which is a different
#: file and must not match — that is the near-miss fixture below.
_Q = r"""(?:"|\\"|'")"""
_HAND_ROLLED = re.compile(
    r"(?:grep|awk|sed|jq|perl|python)[^\n]*" + _Q + r"buildid" + _Q, re.IGNORECASE)

#: Known-bad: each of these SHOULD be caught. Written as real shell, from the six shapes
#: the review enumerated.
_HITS = (
    """    CUR=$(grep -oE '"buildid"[^0-9]*[0-9]+' "$ACF" | head -1)""",
    '''    CUR=$(grep "\\"buildid\\"" "$ACF" | head -1)''',
    """    CUR=$(awk -F'"' '/"buildid"/ {print $4}' "$ACF")""",
    """    CUR=$(sed -n 's/.*"buildid"[^0-9]*\\([0-9]*\\).*/\\1/p' "$ACF" | head -1)""",
)

#: Near-misses: each of these MUST NOT be caught, or the guard would fire on legitimate
#: code and be turned off.
_MISSES = (
    '''    STORED=$(grep -oE 'buildid[^0-9]*[0-9]+' "$SENTINEL" | head -1)''',
    '''    CUR=$(x4_acf_buildid "$ACF")''',
    '''    echo "the installed buildid is $CUR"''',
)


def test_the_pattern_proves_itself_before_it_is_trusted():
    """A pattern that matches nothing reports a comfortable zero forever. This is the
    falsification twin the review found missing: without it, narrowing the regex to a
    single quoting style passed silently while three realistic re-implementations walked
    straight through."""
    missed = [s for s in _HITS if not _HAND_ROLLED.search(s)]
    assert not missed, f"the pattern does not catch a hand-rolled reader: {missed}"
    over = [s for s in _MISSES if _HAND_ROLLED.search(s)]
    assert not over, f"the pattern fires on legitimate code: {over}"


def _shell_files() -> list[Path]:
    files = [*(REPO / "bin").glob("*.sh"), *(REPO / ".claude" / "hooks").glob("*.sh"),
             REPO / "install.sh"]
    return sorted(p for p in files if p.is_file())


def test_the_helper_exists_and_is_the_only_acf_reader():
    text = HELPER.read_text(encoding="utf-8")
    assert "x4_acf_buildid()" in text, "the shared reader is gone from _x4-env.sh"
    files = _shell_files()
    # A population, not a pass-by-absence: the scan must actually have read the two
    # known callers, or an emptied glob would report 'no hand-rolled copy' over nothing.
    names = {p.name for p in files}
    assert {"unpack-reference.sh", "check-reference-version.sh"} <= names, names
    offenders = [f"{p.relative_to(REPO)}:{i}"
                 for p in files if p != HELPER
                 for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if _HAND_ROLLED.search(line)]
    assert not offenders, f"hand-rolled acf buildid greps: {offenders}"


def test_both_known_callers_use_the_helper():
    for rel in ("bin/unpack-reference.sh", ".claude/hooks/check-reference-version.sh"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert re.search(r"\bx4_acf_buildid\b", text), f"{rel} does not call x4_acf_buildid"

r"""No tracked shell script may reassign `TMP`, `TEMP` or `TMPDIR`.

MEASURED (reproduced twice), the fu-hang investigation: on Windows, `TMP` is an
INHERITED, EXPORTED environment variable. In bash, once a variable is exported,
a later plain `VAR=value` assignment -- no `export` keyword needed -- keeps the
export attribute, so every native child process this script spawns afterward
inherits the NEW value.

`scripts/test-hooks.sh:28` did exactly that: `TMP="$(mktemp -d "$_SBX/hooks.XXXXXX")"`.
When `$X4_TEST_SANDBOX` (or the repo path) is long enough that the resulting `TMP`
exceeds 260 characters, a native Windows process started later -- here,
`scan-identifiers.py`'s first `git` child -- spins forever inside `CreateProcessW`
(`-> BasepQueryAppCompat -> GetTempPathW`) the first time IT starts a child of its
own. Threshold measured directly: TMP length 260 is fine, 261 hangs. This is what
made `scan-identifiers.py` spin for 15 hours in one real run.

`tools/basex/smoke-basex.sh:22` had the identical shape (`TMP="$(mktemp -d)"`);
short today only because nothing lengthens it yet, which is exactly the kind of
"recorded cost of zero" CLAUDE.md warns hides a wrong denominator (#23) -- the
same shape in the same repository, waiting for its own `X4_TEST_SANDBOX`.

The fix is mechanical: never reassign `TMP`/`TEMP`/`TMPDIR` in a script that
spawns native children. A freshly-named variable (`SBX_TMP` in both fixed
files) carries no export attribute, so it cannot leak into a child's
environment this way.

Scoped to `scripts/`, `tools/basex/` and `.claude/hooks/` -- the three
directories a real Claude Code session or CI job actually shells out from, per
the fu-hang task brief -- rather than the whole repository, so a hit in, say,
a vendored third-party script does not flood a check whose whole point is to
stay actionable.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

#: The three roots this scan covers, and why: everything a session or CI job
#: actually shells out from. NOT `**/*.sh` repo-wide -- see the module docstring.
ROOTS = ("scripts", "tools/basex", ".claude/hooks")

#: A bare or `export`-prefixed assignment to TMP/TEMP/TMPDIR, anchored to the
#: start of the (stripped) line so a mention inside a comment or a string
#: literal on the RIGHT-hand side ("see $TMP for details") is not itself an
#: assignment and must not trip this.
_TMP_REASSIGN = re.compile(r"^\s*(export\s+)?(TMP|TEMP|TMPDIR)=")


def _tracked_sh(roots=ROOTS) -> list[Path]:
    """Every tracked `*.sh` under *roots*, via `git ls-files` -- the tracked
    INDEX, not a directory walk, so an untracked scratch script never enters
    the population and a renamed/deleted file never lingers in it."""
    out = subprocess.run(
        ["git", "ls-files", *(f"{r}/*.sh" for r in roots)],
        cwd=REPO, capture_output=True, text=True, check=False)
    inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=REPO,
                            capture_output=True, text=True, check=False)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        # NOT a git checkout: the release bundle, or the cold-clone verification's
        # extract. Every file in it IS the shipped set, so the walk is the tracked set.
        return sorted(p for r in roots for p in (REPO / r).rglob("*.sh") if p.is_file())
    return [REPO / n for n in out.stdout.split() if n]


def _tmp_reassignments(text: str) -> list[int]:
    """1-based line numbers where TMP/TEMP/TMPDIR is (re)assigned. Pure, so the
    twins below can call it directly instead of re-deriving the predicate."""
    return [i for i, line in enumerate(text.splitlines(), 1)
            if _TMP_REASSIGN.match(line)]


def test_no_tracked_script_reassigns_tmp_temp_or_tmpdir():
    offenders = []
    scanned = 0
    per_root = {r: 0 for r in ROOTS}
    for path in _tracked_sh():
        scanned += 1
        rel = path.relative_to(REPO).as_posix()
        for root in ROOTS:
            if rel.startswith(root + "/"):
                per_root[root] += 1
                break
        hits = _tmp_reassignments(path.read_text(encoding="utf-8", errors="replace"))
        offenders.extend(f"{rel}:{n}" for n in hits)

    # A root contributing zero files is a silently narrowed population, exactly
    # the shape CLAUDE.md's "a step that narrows data must announce it" bans --
    # a rename or an empty directory must be loud, not quietly pass.
    empty = sorted(r for r, c in per_root.items() if c == 0)
    assert not empty, (
        f"root(s) {empty} contributed ZERO tracked .sh files -- this guard no "
        f"longer covers them. Counts: {per_root}")
    assert scanned >= 8, (
        f"only {scanned} script(s) scanned across {ROOTS} -- population looks "
        f"too small to be the real one")
    assert not offenders, (
        "TMP/TEMP/TMPDIR is an inherited, EXPORTED env var on Windows: a plain "
        "reassignment here keeps the export attribute, and every native child "
        "this script spawns afterward inherits it. A long enough value hangs "
        "the first native process that starts a child of its own (MEASURED: "
        "260 chars fine, 261 hangs). Rename the variable (e.g. SBX_TMP):\n  "
        + "\n  ".join(offenders))


def test_the_pattern_fires_on_the_real_shape_that_hung():
    """Falsification twin, positive side: the exact line that caused the hang."""
    hits = _tmp_reassignments('TMP="$(mktemp -d "$_SBX/hooks.XXXXXX")"\n')
    assert hits == [1], "the ORIGINAL offending line no longer trips the guard"


def test_the_pattern_fires_on_export_and_on_temp_and_tmpdir():
    text = (
        'export TMP="$(mktemp -d)"\n'
        'TEMP="$(mktemp -d)"\n'
        'TMPDIR="$(mktemp -d)"\n'
    )
    assert _tmp_reassignments(text) == [1, 2, 3]


def test_the_pattern_does_NOT_fire_on_a_renamed_variable():
    """Falsification twin, negative side: the FIXED shape must stay silent."""
    hits = _tmp_reassignments('SBX_TMP="$(mktemp -d "$_SBX/hooks.XXXXXX")"\n')
    assert hits == [], "the fixed variable name must not trip the guard"


def test_the_pattern_does_NOT_fire_on_a_mention():
    """A comment or a read of $TMP is not an assignment and must not flood the check."""
    text = (
        "# TMP is exported on Windows, so we never reassign it here\n"
        'echo "using $TMP for scratch"\n'
        "cat_TMP_thing=1\n"  # not TMP at the start; a different identifier entirely
    )
    assert _tmp_reassignments(text) == []


def test_scripts_test_hooks_and_smoke_basex_are_clean():
    """The two files this bug was found in, named directly so a regression here
    cannot hide behind an aggregate 'offenders' list going quiet for some other
    reason (e.g. the glob silently stopping matching one of them)."""
    for rel in ("scripts/test-hooks.sh", "tools/basex/smoke-basex.sh"):
        p = REPO / rel
        assert p.is_file(), f"{rel} is expected to exist"
        hits = _tmp_reassignments(p.read_text(encoding="utf-8"))
        assert hits == [], f"{rel} still reassigns TMP/TEMP/TMPDIR at line(s) {hits}"

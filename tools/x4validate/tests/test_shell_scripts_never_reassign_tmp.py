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

Scoped to `scripts/`, `tools/basex/`, `bin/` and every agent's hook tree (`.claude/`,
`.codex/`, `.opencode/hooks/` and their source `agent/guards/`) -- the directories a real
session or CI job actually shells out from -- rather than the whole repository, so a hit in, say,
a vendored third-party script does not flood a check whose whole point is to
stay actionable.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

#: The roots this scan covers, and why: everything a session or CI job actually shells out
#: from. NOT `**/*.sh` repo-wide -- see the module docstring. `agent/guards` (the hook SOURCE,
#: and codex-entry.sh, which Codex starts for every hook), the generated `.codex/hooks` and
#: `.opencode/hooks` trees and `bin` joined in the v4.0 release review (R7-9).
ROOTS = ("scripts", "tools/basex", ".claude/hooks", "agent/guards", ".codex/hooks",
         ".opencode/hooks", "bin")

#: A bare or `export`-prefixed assignment to TMP/TEMP/TMPDIR, anchored to the
#: start of the (stripped) line so a mention inside a comment or a string
#: literal on the RIGHT-hand side ("see $TMP for details") is not itself an
#: assignment and must not trip this.
_TMP_REASSIGN = re.compile(r"^\s*(export\s+)?(TMP|TEMP|TMPDIR)=")


def _roots() -> tuple:
    """ROOTS, or -- in an INSTALLED toolkit (R2-B1) -- the ones present there: an install carries
    no agent/ source, and only the agent targets it was installed for. What is on disk there IS the
    shipped population; the repository run keeps every root mandatory."""
    from _layout import installed_layout
    if not installed_layout():
        return ROOTS
    return tuple(r for r in ROOTS if (REPO / r).is_dir())


def _tracked_sh(roots=None) -> list[Path]:
    """Every tracked `*.sh` under *roots*, via `git ls-files` -- the tracked
    INDEX, not a directory walk, so an untracked scratch script never enters
    the population and a renamed/deleted file never lingers in it."""
    from _layout import installed_layout
    roots = _roots() if roots is None else roots
    if installed_layout(REPO):
        # An INSTALLED toolkit: what is on disk IS the shipped set. v4.0.0 delta review: the
        # git branch below ran here too, and an install inside ANOTHER repo (the in-game
        # method installs into the game root, which can be a git repo) asked THAT repo's
        # index -- which tracks none of these files -- so the population came back EMPTY.
        return _walk_sh(roots)
    out = subprocess.run(
        ["git", "ls-files", *(f"{r}/*.sh" for r in roots)],
        cwd=REPO, capture_output=True, text=True, check=False)
    inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=REPO,
                            capture_output=True, text=True, check=False)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        # NOT a git checkout: the release bundle, or the cold-clone verification's
        # extract. Every file in it IS the shipped set, so the walk is the tracked set.
        return _walk_sh(roots)
    return [REPO / n for n in out.stdout.split() if n]


def _walk_sh(roots) -> list[Path]:
    return sorted(p for r in roots for p in (REPO / r).rglob("*.sh") if p.is_file())


def _skip_if_installed_and_empty(population, roots, installed=None) -> None:
    """An installed toolkit installed for an agent whose tree carries no .sh can have an empty
    population; that is a counted SKIP there. In a checkout an empty population is a broken
    scan and the assertions below FAIL it -- never skipped."""
    from _layout import REASON, installed_layout
    installed = installed_layout(REPO) if installed is None else installed
    if installed and not population:
        pytest.skip(f"{REASON}: no shell script under {list(roots)} in this install -- "
                    "the TMP-reassignment scan has nothing to examine")


def test_TWIN_an_empty_population_skips_only_in_an_install():
    with pytest.raises(pytest.skip.Exception, match="nothing to examine"):
        _skip_if_installed_and_empty([], ("scripts",), installed=True)
    _skip_if_installed_and_empty([], ("scripts",), installed=False)      # checkout: no skip
    _skip_if_installed_and_empty([REPO / "x.sh"], ("scripts",), installed=True)


def test_an_install_INSIDE_another_git_repo_still_walks_its_own_files(tmp_path, monkeypatch):
    """The in-game layout: the toolkit sits in a game root that is its OWN git repo, tracking
    none of the toolkit's scripts. The population must come from disk, not that index."""
    import sys
    game = tmp_path / "game"
    (game / "scripts").mkdir(parents=True)
    (game / "scripts" / "a.sh").write_text("echo hi\n", encoding="utf-8")
    (game / "readme.txt").write_text("x", encoding="utf-8")
    for a in (("init", "-q"), ("add", "readme.txt"),
              ("-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
               "commit", "-qm", "game")):
        assert subprocess.run(["git", *a], cwd=game, capture_output=True).returncode == 0, a
    monkeypatch.setattr(sys.modules[__name__], "REPO", game)
    assert [p.name for p in _tracked_sh(("scripts",))] == ["a.sh"]


def _tmp_reassignments(text: str) -> list[int]:
    """1-based line numbers where TMP/TEMP/TMPDIR is (re)assigned. Pure, so the
    twins below can call it directly instead of re-deriving the predicate."""
    return [i for i, line in enumerate(text.splitlines(), 1)
            if _TMP_REASSIGN.match(line)]


def test_no_tracked_script_reassigns_tmp_temp_or_tmpdir():
    offenders = []
    scanned = 0
    roots = _roots()
    _skip_if_installed_and_empty(_tracked_sh(), roots)
    per_root = {r: 0 for r in roots}
    for path in _tracked_sh():
        scanned += 1
        rel = path.relative_to(REPO).as_posix()
        for root in roots:
            if rel.startswith(root + "/"):
                per_root[root] += 1
                break
        hits = _tmp_reassignments(path.read_text(encoding="utf-8", errors="replace"))
        offenders.extend(f"{rel}:{n}" for n in hits)

    # A root contributing zero files is a silently narrowed population, exactly
    # the shape the x4-toolkit-dev skill's "a step that narrows data must announce it" bans --
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


def test_the_population_includes_every_agent_hook_tree_and_the_codex_entry():
    """v4.0 release review R7-9: the roots were `scripts`, `tools/basex` and `.claude/hooks`, so
    `agent/guards/adapters/codex-entry.sh` -- the script Codex starts for EVERY hook -- and the
    generated `.codex/hooks/` and `.opencode/hooks/` trees were never scanned, though each is
    shelled out from by a real session. Named directly, so a narrowed glob cannot hide them."""
    scanned = {p.relative_to(REPO).as_posix() for p in _tracked_sh()}
    for rel in ("agent/guards/adapters/codex-entry.sh", "agent/guards/claude-hooks/protect-bash.sh",
                ".codex/hooks/protect-bash.sh", ".opencode/hooks/protect-bash.sh",
                "bin/unpack-reference.sh"):
        if not any(rel.startswith(r + "/") for r in _roots()):
            continue              # R2-B1: a root an installed toolkit does not carry
        assert rel in scanned, f"{rel} is not in the scanned population"

r"""The release bundle must be REPRODUCIBLE, and the build must prove it is the tag.

WHY. v3.0.0 shipped `X4.Foundations.Claude.Code.Toolkit.v3.0.0.zip` and nothing in the
repo made it. A bundle assembled by hand cannot be diffed against the tag, so nothing
could have said whether its contents were the reviewed contents -- and this repo has
already shipped a release whose bundle carried a MUTATED `_merge.py`, picked up from a
working tree while a mutation gate was running (CLAUDE.md #27). `git archive` reads the
committed object store and cannot see a working-tree edit at all, so it is immune to
that window by construction rather than by anyone remembering.

MEASURED 2026-09-07: `git archive --format=zip v3.0.0` reproduces the published asset
BYTE FOR BYTE. That is what makes `--selftest` a control rather than a claim.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "build-release.sh"

# NEVER a bare "bash": on Windows `shutil.which("bash")` returns the WSL stub in
# System32 (a bash.exe that is not a shell), which runs a Linux bash in a
# filesystem where the C: drive does not exist -- so every path-shaped assertion
# silently changes meaning. `scripts/gitbash.py` exists because that cost three
# debugging sessions here, and my first draft of this file walked straight into it.
_spec = importlib.util.spec_from_file_location("_gitbash", REPO / "scripts" / "gitbash.py")
_gitbash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gitbash)


def _bash():
    b = _gitbash.find_bash()
    if not b:
        pytest.skip("no real (non-WSL) bash on this machine -- not checked")
    return str(b)


def _git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True)


def _needs(cond, why):
    if not cond:
        pytest.skip(why)          # skip, never a bare return -- a return is invisible


def test_the_build_script_exists_and_is_syntactically_valid():
    _needs(SCRIPT.is_file(), "no scripts/build-release.sh (dev-only script) — not checked")
    r = subprocess.run([_bash(), "-n", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_SELFTEST_still_reproduces_the_published_v300_asset():
    """The control. If `git archive` ever stops reproducing the one asset whose bytes
    are publicly known, this says so BEFORE a release does."""
    _needs(SCRIPT.is_file(), "no scripts/build-release.sh (dev-only script) — not checked")
    _needs(_git("rev-parse", "--git-dir").returncode == 0,
           "not a git checkout, so no ref can be archived — not checked")
    _needs(_git("rev-parse", "-q", "--verify", "v3.0.0^{}").returncode == 0,
           "tag v3.0.0 not present in this clone — not checked")
    r = subprocess.run([_bash(), str(SCRIPT), "--selftest"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SELFTEST PASSED" in r.stdout


def test_a_bundle_that_is_NOT_the_ref_is_REFUSED():
    """The twin, and the point of the whole script: not "did a zip appear" but "is
    what is in it what the tag says". Both directions matter -- a missing file ships a
    broken toolkit, an extra file ships something nobody reviewed. Checked by handing
    the verifier a v3.0.0 bundle against HEAD, which has more files."""
    _needs(SCRIPT.is_file(), "no scripts/build-release.sh (dev-only script) — not checked")
    _needs(_git("rev-parse", "-q", "--verify", "v3.0.0^{}").returncode == 0,
           "tag v3.0.0 not present in this clone — not checked")
    src = SCRIPT.read_text(encoding="utf-8")
    body = src[src.index("import subprocess, sys, zipfile"):src.index("\nPY\n")]
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        z = os.path.join(td, "x.zip")
        assert _git("archive", "--format=zip", "v3.0.0", "-o", z).returncode == 0
        v = Path(td) / "v.py"
        v.write_text(body, encoding="utf-8")
        r = subprocess.run([sys.executable, str(v), z, "HEAD"],
                           cwd=str(REPO), capture_output=True, text=True)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "MISSING FROM THE BUNDLE" in r.stderr


def test_the_bundle_carries_the_whole_TRACKED_set_and_no_wrapper_folder():
    """v3.0.0 shipped the tag's tracked set exactly -- no exclusions, no additions and
    no top-level wrapper directory. Pinned because an install script that resolves
    paths relative to the archive root breaks the moment someone adds a wrapper."""
    _needs(_git("rev-parse", "-q", "--verify", "v3.0.0^{}").returncode == 0,
           "tag v3.0.0 not present in this clone — not checked")
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        z = os.path.join(td, "x.zip")
        assert _git("archive", "--format=zip", "v3.0.0", "-o", z).returncode == 0
        members = {i.filename for i in zipfile.ZipFile(z).infolist() if not i.is_dir()}
    tracked = set(_git("ls-tree", "-r", "--name-only", "v3.0.0").stdout.split())
    assert members == tracked, sorted(members ^ tracked)[:10]
    assert "install.sh" in members, "the installer must sit at the archive ROOT"


def test_an_EXTRA_file_in_the_bundle_is_REFUSED_too(planted_verifier):
    """Both the script and the sibling test say "Both directions matter", and only
    MISSING was exercised: a mutant setting `extra = []` left all four tests green.

    A hand-assembled zip, a stray wrapper directory, or an `export-ignore` inversion
    ships content nobody reviewed, and the verifier passed it. This is the direction
    that matters for a RELEASE, because a bundle with an extra file is a bundle
    carrying something outside the reviewed range.
    """
    verify, repo, ref = planted_verifier
    import zipfile, subprocess, sys, os
    z = os.path.join(repo, "extra.zip")
    assert subprocess.run(["git", "-C", repo, "archive", "--format=zip", ref, "-o", z],
                          capture_output=True).returncode == 0
    with zipfile.ZipFile(z, "a") as zf:
        zf.writestr("NOT_IN_THE_REF.txt", "shipped without review\n")
    r = subprocess.run([sys.executable, str(verify), z, ref],
                       cwd=repo, capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "IN THE BUNDLE, NOT IN THE REF" in r.stderr, r.stderr


@pytest.fixture()
def planted_verifier(tmp_path):
    """The verifier body, extracted from the script, plus a tiny repo to run it on."""
    _needs(SCRIPT.is_file(), "no scripts/build-release.sh (dev-only script) - not checked")
    import subprocess
    src = SCRIPT.read_text(encoding="utf-8")
    body = src[src.index("import subprocess, sys, zipfile"):src.index("\nPY\n")]
    v = tmp_path / "verify.py"
    v.write_text(body, encoding="utf-8")
    r = tmp_path / "repo"
    r.mkdir()
    for a in (["init", "-q", "."], ["config", "user.name", "t"],
              ["config", "user.email", "t@t"]):
        subprocess.run(["git", "-C", str(r), *a], capture_output=True)
    (r / "a.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(r), "add", "a.txt"], capture_output=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], capture_output=True)
    return v, str(r), "HEAD"

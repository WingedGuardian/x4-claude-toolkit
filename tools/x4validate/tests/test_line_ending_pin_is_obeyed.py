r"""The `.gitattributes` line-ending pin must be OBEYED BY THE BYTES, not merely declared (F67).

F53 added `*.py text eol=lf` so the engine fingerprint would stop depending on how a
file happened to arrive on disk. That pin is correct and **it is not self-enforcing**:
it normalises on CHECKOUT, and a file already sitting in the tree from before the pin
keeps its endings until something rewrites it. Nothing counted the bytes.

MEASURED 2026-08-27: `_effective.py` sat fully CRLF (1205 lines) while HEAD and its six
sibling `ENGINE_SOURCES` were LF. The engine hash reads raw BYTES, so this box computed
`b25a2a99853d4c84` where a fresh clone of the SAME commit computes `3239fa6c515b83b6`.
Every recorded "the engine hash is X" was machine-local. It survived two days precisely
because it fails SAFE -- a false STALE, never a false FRESH, so the only symptom is a
rebuild you did not need, which reads as normal operation.

Widening the scan from `ENGINE_SOURCES` to the pin's actual scope found **8 of 129**
tracked files still CRLF, including three production modules -- so the defect was wider
than the finding that exposed it.

TWO DESIGN CHOICES, both load-bearing:

* **Ask git what the pin resolves to** (`git check-attr eol --stdin`), never re-implement
  gitattributes pattern matching. A second implementation of a normaliser is the exact
  shape that made an independent measurement of F64 report 2.6% where the truth was
  65.4%. `--stdin` also keeps it to ONE subprocess: a per-file spawn measured ~92%
  overhead on Windows in an earlier benchmark.
* **Read the WORKING TREE, never `git show`.** Git normalises on read, so a
  committed-blob comparison reports clean whatever is on disk -- the same
  committed-vs-working-tree distinction that made `diff -rq` useless as a port proof
  (F60). The bytes on disk are the whole question.

There is deliberately **no allow-list**. An offender is normalised, not excused; a
grandfathered list is the silent-narrowing shape this register exists to catch.
"""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str, stdin: str | None = None) -> str | None:
    """Run git in ROOT and return stdout, or None when git/the repo is unavailable.

    BINARY I/O ON PURPOSE. With `text=True`, Python translates newlines on the way
    IN on Windows, so a stdin payload separated by LF reaches git separated by CRLF
    -- and `check-attr` then answers about a path with a trailing CR, reporting
    `unspecified` for every file. MEASURED: 141 of 141.

    Note the direction, because the first diagnosis got it backwards and fitted the
    evidence anyway: the CR was ADDED ON THE WAY IN by this call, not left behind by
    splitting `ls-files` output. A surprising observation is a question, not an answer.
    """
    try:
        r = subprocess.run(("git", *args), cwd=ROOT,
                           input=stdin.encode("utf-8") if stdin is not None else None,
                           capture_output=True)
    except (OSError, ValueError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace")


def files_pinned_to_lf() -> list[str] | None:
    """Tracked files whose resolved `eol` attribute is `lf`, per GIT ITSELF.

    None when the question cannot be asked (no git, not a repo) -- which is a
    NON-ANSWER and must never be rendered as "nothing is pinned".
    """
    listing = _git("ls-files")
    if listing is None:
        return None
    # splitlines(), NOT split on a bare newline: `git ls-files` emits CRLF on this
    # platform, so a trailing CR rode on every path and check-attr answered
    # "unspecified" for all 141 -- a line-ending guard defeated by a line ending in
    # its own input. Caught only by the denominator assert below (F67).
    tracked = [p for p in listing.splitlines() if p.strip()]
    if not tracked:
        return None
    out = _git("check-attr", "eol", "--stdin", stdin="\n".join(tracked) + "\n")
    if out is None:
        return None
    pinned = []
    for line in out.splitlines():
        # `path: eol: lf` -- a path may contain ": ", so split from the RIGHT
        head, _, value = line.rpartition(": ")
        path, _, attr = head.rpartition(": ")
        if attr == "eol" and value == "lf":
            pinned.append(path)
    return pinned


def crlf_offenders(paths, root: Path) -> list[tuple[str, int]]:
    """(path, CRLF count) for each file carrying CRLF **on disk**."""
    out = []
    for rel in paths:
        p = root / rel
        if not p.is_file():
            continue
        n = p.read_bytes().count(b"\r\n")
        if n:
            out.append((rel, n))
    return out


def test_the_offender_detector_can_actually_fail(tmp_path):
    """Proven-to-fail guard. A check that cannot go red is not evidence (#26), and
    three names for that one defect now sit in CLAUDE.md #26."""
    (tmp_path / "crlf.py").write_bytes(b"a = 1\r\nb = 2\r\n")
    (tmp_path / "lf.py").write_bytes(b"a = 1\nb = 2\n")
    found = crlf_offenders(["crlf.py", "lf.py", "absent.py"], tmp_path)
    assert found == [("crlf.py", 2)], found


def test_the_pin_resolver_reports_a_NON_ANSWER_rather_than_an_empty_list():
    """`files_pinned_to_lf()` must distinguish "nothing is pinned" from "I could not
    ask". Returning [] for an unavailable git would make the assertion below
    vacuously green -- the founding defect shape, inside its own guard."""
    import test_line_ending_pin_is_obeyed as m
    real = m._git
    try:
        m._git = lambda *a, **k: None
        assert m.files_pinned_to_lf() is None
    finally:
        m._git = real


def test_every_file_pinned_to_LF_actually_holds_LF_on_disk():
    """The guard itself. The pin is a statement of intent; the bytes are the fact."""
    pinned = files_pinned_to_lf()
    if pinned is None:
        pytest.skip("git unavailable or not a repository -- pin compliance NOT CHECKED")
    assert len(pinned) > 20, (
        f"only {len(pinned)} files resolved to eol=lf -- the resolver has gone blind, "
        "and a blind resolver makes the assertion below meaningless")
    offenders = crlf_offenders(pinned, ROOT)
    assert not offenders, (
        f"{len(offenders)} of {len(pinned)} files pinned `eol=lf` carry CRLF ON DISK: "
        f"{offenders}. The pin normalises on CHECKOUT and does not repair a file already "
        "in the tree. Rewrite them with LF -- git already stores them LF, so this is a "
        "working-tree repair with no diff. See F67.")

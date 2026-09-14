#!/usr/bin/env python
"""Every FIXED blind-spot entry must name the check that re-derives it.

WHY THIS EXISTS. `docs/BLIND-SPOTS.md` is where this workspace records what its
tools got wrong and how it was fixed. A fix that is only PROSE decays: the code
moves, the test is renamed or deleted, and the entry goes on asserting that the
defect is closed. The register's own doctrine is that a claim carries its
evidence, and an entry naming no check is a claim with none.

FOUND BY DOING THE AUDIT BY HAND (2026-08-29), which is the argument for the
gate. Two instruments were tried first and both were wrong:

  * a KEYWORD scan for "gates/" or "tests/" produced a false NEGATIVE on F69
    (its test exists and the entry simply did not name it) and a right answer for
    the wrong reason on F70 (it matched a file unrelated to the pinned figure);
  * a NUMBER grep -- looking for each entry's headline figure under tests/ --
    produced false POSITIVES everywhere, because "200" and "165" occur in
    unrelated fixtures. A bare number is not provenance.

What works is the question this gate asks: does the entry NAME a check, and does
that file exist? That is answerable, and it is the property that actually matters
to a reader trying to confirm a fix is still real.

MEASURED at the time of writing: 36 entries marked FIXED/CLOSED, 22 naming an
existing check, 14 naming none. Four of those fourteen were closed the same day
(three by naming a test that already existed, one by stating why its census
number is deliberately not asserted). The remaining ten are OLDER entries and are
recorded in a baseline rather than fixed in a rush -- a gate that fires on ten
known items every run is the flood that trains you to ignore the runner, which is
the same mistake as an uncalibrated threshold.

So: the backlog is ACCEPTED and NAMED, and only a NEW unnamed entry fails.

    uv run python gates/register_rederivation.py [--record]

Exit: 0 clean (or recorded) - 1 a new entry names no check - 2 cannot run.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "docs" / "BLIND-SPOTS.md"
BASELINE = ROOT / ".register-rederivation-baseline.json"
RECORD = "--record" in sys.argv

#: A heading is FIXED when it says so. An OPEN entry owes nothing yet.
_CLOSED = re.compile(r"FIXED|CLOSED")

#: What counts as naming a check: a repo-relative test/gate path, a SHELL suite
#: under scripts/ or .claude/hooks/, a bare `test_name` in backticks, or the word
#: selftest (several tools carry one).
#:
#: The shell forms were added 2026-08-29, on this gate's first serious use: F79's
#: re-derivation is `scripts/test-hooks.sh` and `.claude/hooks/test-protect-bash.sh`,
#: which are every bit as much a check as a pytest file and which the original
#: pattern could not see. A gate that only recognises evidence in ONE language
#: reports a real proof as missing -- the false-negative half of this register's
#: recurring shape.
#:
#: EXTENDED 2026-08-31, and the recurrence is the point: the 08-29 fix admitted
#: shell suites under those two directories but only `.sh`, and those directories
#: now hold PYTHON checks too (scripts/verify-port.py, scripts/verify-hook-tests.py,
#: .claude/hooks/test_hook_facts.py). So the identical false negative came back --
#: inside the pattern whose own comment warns about it -- and reported F87 and F89
#: as naming no check when both name a real one. Widening cannot admit a mere
#: MENTION: the caller requires the named file to exist in one of the trees.
_NAMES = re.compile(
    r"(?:tests/|gates/)[A-Za-z0-9_./-]+\.py"
    r"|(?:scripts/|\.claude/hooks/)[A-Za-z0-9_./-]+\.(?:sh|py)"
    r"|`(test_[A-Za-z0-9_]+)`|selftest")

#: The explicit opt-out. An entry whose figure genuinely cannot be re-derived
#: says so IN THE ENTRY -- that is a statement a reader can weigh, unlike silence.
_EXEMPT = "NO RE-DERIVATION"


def entries(text: str) -> dict[str, str]:
    """F-id -> its body. An id with a CONTINUATION heading keeps the FIRST one, and
    every later body for that id is appended to it.

    This was a dict comprehension until 2026-08-31, which is LAST-WINS -- and the
    sibling gate `tests/test_blind_spots_ids.py` documents the opposite convention in
    as many words: *"First heading wins: a continuation heading does not redeclare
    status"*, naming F11 as the legitimate two-heading case. So the two gates read the
    SAME FILE and disagreed about which heading an entry has.

    MEASURED: exactly 1 of 92 entries differs, and it is F11 -- whose declaring heading
    has said FIXED since 2026-08-13 while this gate silently audited its CONTINUATION
    instead, where no status is declared. The entry was therefore invisible to the
    "a FIXED entry must name its check" rule for eighteen days, and it named none.

    Later bodies are APPENDED rather than discarded, so a check cited only in a
    continuation section still counts.
    """
    parts = re.split(r"(?m)^## (F\d+)", text)
    out: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        fid, body = parts[i], parts[i + 1]
        out[fid] = out[fid] + body if fid in out else body
    return out


_PATH_PREFIXES = ("tests/", "gates/", "scripts/", ".claude/")

#: A test DEFINITION. A name in a comment or a string is not a test.
_DEF = re.compile(r"^[ \t]*def (test_[A-Za-z0-9_]+)\(", re.M)


def _defined_tests(files) -> set[str]:
    names: set[str] = set()
    for f in files:
        try:
            names.update(_DEF.findall(f.read_bytes().decode("utf-8", "replace")))
        except OSError:
            # silent-ok: an unreadable file defines nothing we can SEE, so a bare
            # name that only it could satisfy stays unresolved -- the strict side.
            continue
    return names


def _pool(roots: list[Path]) -> list[Path]:
    """Every file a bare test name may be DEFINED in without being cited."""
    out: list[Path] = []
    for base in roots:
        out.extend(sorted(base.glob("tests/**/*.py")))
        out.extend(sorted(base.glob(".claude/hooks/*.py")))
    return out


def names_a_check(body: str, root: Path) -> str | None:
    """The first named check that EXISTS, or None.

    Existence is the point. An entry naming a test that was deleted is worse than
    one naming nothing, because it reads as covered.

    BARE `test_name` CITATIONS (review of KB `7915dc4`, 2026-09-13). These used to be
    rewritten to `tests/<name>.py` and then lost to FIRST-WINS: a cited FILE resolved
    and returned before a stale test name beside it was ever looked at, so
    `.claude/hooks/test_hook_facts.py` plus a test never written there read as
    covered -- F112's own worst case. Now a bare name resolves iff `tests/<name>.py`
    exists OR `def <name>(` is defined in a cited file or anywhere in `_pool()`, and
    EVERY bare name must resolve. MEASURED before the change: 30 bare citations in the
    register, 0 of 57 covered FIXED entries flip. The pool is the whole tests tree,
    not only the cited files, because F40 and F74 name tests defined in files they do
    not cite -- a cited-files-only rule would have flagged two true citations.
    Pinned clause by clause in `tests/test_register_rederivation_bare_names.py`.
    """
    roots = _roots(root)
    first: str | None = None
    cited: list[Path] = []
    bare: list[str] = []
    for m in _NAMES.finditer(body):
        s = m.group(0).strip("`")
        if s == "selftest":
            first = first or "selftest"
            continue
        if not s.startswith(_PATH_PREFIXES):
            bare.append(s)
            continue
        # Existence is checked at BOTH roots (see `_roots`): the hook suites live at
        # the repo root, not under the package, and requiring them here would reject
        # a check that demonstrably exists and runs.
        for base in roots:
            if (base / s).is_file():
                cited.append(base / s)
                first = first or s
                break
    if bare:
        defined: set[str] | None = None
        for name in bare:
            stem = "tests/" + name + ".py"
            if any((base / stem).is_file() for base in roots):
                first = first or stem
                continue
            if defined is None:     # built once, and only when a stem did not resolve
                defined = _defined_tests(cited) | _defined_tests(_pool(roots))
            if name in defined:
                first = first or name
                continue
            return None             # a named test that exists nowhere: NOT covered
    return first


def _roots(root: Path) -> list[Path]:
    """The package root, plus the repository root that nests it.

    Citations come at two depths: `tests/...` and `gates/...` are PACKAGE-relative, while
    `.claude/hooks/...` and the repo-level `scripts/...` (fuzz-guard.py, test-hooks.sh)
    are REPO-relative. Until 2026-09-13 this gate lived in a separate dev repository
    whose root WAS the package, and it reached the repo-level checks by importing a port
    script's idea of where the public mirror was. With one repository the layout answers
    by itself: the package is `<repo>/tools/x4validate`, so the repo root is two levels
    up -- offered only when that nesting is real, never assumed.
    """
    out = [root]
    repo = root.parent.parent
    try:
        nested = (repo / "tools" / "x4validate").resolve() == root.resolve()
    except OSError:          # silent-ok: an unresolvable parent offers no second root,
        nested = False       # which is a narrower answer, never a wrong one
    if nested:
        out.append(repo)
    return out


def audit(text: str, root: Path) -> tuple[list[str], list[str]]:
    """(entries that name a check, entries that do not). Fixed entries only."""
    ok, missing = [], []
    for fid, body in entries(text).items():
        head = body.split(chr(10))[0]
        if not _CLOSED.search(head):
            continue
        if _EXEMPT in body or names_a_check(body, root):
            ok.append(fid)
        else:
            missing.append(fid)
    return ok, missing


def _baseline() -> list[str]:
    if not BASELINE.exists():
        return []
    try:
        return list(json.loads(BASELINE.read_text(encoding="utf-8"))["missing"])
    except (OSError, ValueError, KeyError) as exc:
        # Never [] on a damaged baseline: that would flood the run with false NEW
        # rows while looking like a clean first run -- absence and non-answer
        # collapsing into one value, which is what this register is about.
        raise RuntimeError(f"{BASELINE} exists but cannot be read: {exc}") from exc


def main() -> int:
    if not REGISTER.is_file():
        print(f"REFUSING: no register at {REGISTER}", file=sys.stderr)
        return 2
    text = REGISTER.read_text(encoding="utf-8", errors="replace")
    ok, missing = audit(text, ROOT)
    total = len(ok) + len(missing)
    if total == 0:
        print("REFUSING: no FIXED entries found — a clean result would prove nothing.",
              file=sys.stderr)
        return 2

    print(f"REGISTER RE-DERIVATION — {total} entr(ies) marked FIXED/CLOSED")
    print(f"  name an existing check, or state why not: {len(ok)}")
    print(f"  name none:                               {len(missing)}")

    if RECORD:
        BASELINE.write_text(json.dumps({"missing": sorted(missing)}, indent=2) + chr(10),
                            encoding="utf-8")
        print(f"recorded baseline -> {BASELINE.name} ({len(missing)} accepted)")
        return 0

    accepted = set(_baseline())
    new = [f for f in missing if f not in accepted]
    stale = sorted(accepted - set(missing))
    if accepted:
        print(f"  accepted backlog (baseline): {len(accepted & set(missing))}")
    if stale:
        # Someone fixed one. Say so -- a baseline that only ever grows is a place
        # for work to go and never come back.
        print(f"  FIXED SINCE THE BASELINE: {', '.join(stale)} — re-record to lock it in")
    if new:
        print("")
        print(f"{len(new)} entr(ies) marked FIXED name no check that exists:")
        for f in new:
            print(f"    {f}")
        print("")
        print("  Name the test or gate that re-derives it, or state "
              f"'{_EXEMPT}' in the entry with the reason.")
        return 1
    print("")
    print("No new findings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

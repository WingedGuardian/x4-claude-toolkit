#!/usr/bin/env python3
r"""Fail if a contributor's personal identifier is embedded in a tracked FILE.

WHAT THIS IS FOR, and what it is deliberately NOT for
-----------------------------------------------------
A machine-local identifier -- a username inside a path, a personal folder name --
reaching a public file is an accident. **Deliberate attribution is not.** The
copyright holder in LICENSE and the repo owner in every clone URL are published
on purpose, and a check that flagged those would be wrong every single run and
would therefore be ignored within a week.

So the forbidden list is DERIVED, then narrowed:

    every name/email in this repo's own commit metadata
      MINUS anything appearing in LICENSE        (deliberate attribution)
      MINUS the repo owner's handle              (it is in every clone URL)
      MINUS generic platform words               (github, noreply, ...)
      PLUS  $EXTRA_FORBIDDEN, one per line       (optional, from a repo secret)

Deriving from `git log` rather than hardcoding means the workflow does not have
to spell out what it is guarding against, and it keeps working as contributors
change. The optional secret covers anything git does not know about -- an old
handle, a private folder name.

MEASURED on this repo 2026-08-24, which is why the narrowing exists: the naive
form (git log tokens, no narrowing) produced 9 hits across 3 tokens, and only
3 of them were real. `GitHub` matched 4 files including this very workflow, and
`WingedGuardian` matched LICENSE and README -- i.e. it would have demanded the
removal of the copyright line.

WHY IT PRINTS NO MATCHED TEXT
-----------------------------
CI logs are public. A guard that echoes the string it caught publishes the thing
it exists to suppress. Only `path:line` is ever printed.

Exit codes: 0 clean - 1 identifiers found - 2 cannot run (so a failure to scan
can never be mistaken for a clean scan).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

#: Platform and service words that show up as commit-metadata tokens but identify
#: nobody. Lowercase; compared case-insensitively.
GENERIC = {
    "github", "noreply", "users", "gmail", "yahoo", "hotmail", "outlook",
    "actions", "action", "anthropic", "claude", "localhost", "example",
}

#: Below this length a token is too collision-prone to be evidence of anything
#: ("Jay" would match "Jayne", "jayson", and any three letters in a hash).
MIN_TOKEN = 5


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()[:200]}")
    return out.stdout


def commit_identities() -> set[str]:
    """Names and emails from this repo's own history, plus email local parts."""
    toks: set[str] = set()
    for line in _git("log", "--format=%an%n%ae%n%cn%n%ce").splitlines():
        line = line.strip()
        if not line:
            continue
        toks.add(line)
        if "@" in line:
            toks.add(line.split("@", 1)[0])
    return toks


def allowed(repo: str | None) -> set[str]:
    """Identifiers that are published ON PURPOSE and must never be flagged."""
    ok = set(GENERIC)
    licence = Path("LICENSE")
    if licence.is_file():
        # Anything in the copyright notice is deliberate by definition.
        ok |= {w.lower() for w in re.findall(r"[A-Za-z0-9_.-]{%d,}" % MIN_TOKEN,
                                             licence.read_text(encoding="utf-8",
                                                               errors="replace"))}
    if repo:  # "owner/name" from $GITHUB_REPOSITORY -- it is in every clone URL
        ok |= {p.lower() for p in repo.replace("/", " ").split()}
    return ok


def forbidden_tokens() -> tuple[list[str], list[str]]:
    """Return (tokens_to_ban, notes_for_the_log)."""
    notes: list[str] = []
    derived = commit_identities()
    ok = allowed(os.environ.get("GITHUB_REPOSITORY"))

    banned = set()
    for t in derived:
        if len(t) < MIN_TOKEN:
            continue
        if t.lower() in ok:
            continue
        # A multi-word name ("Firstname Lastname") is allowed if either part is.
        # The placeholder is deliberately synthetic: an earlier draft used a REAL
        # contributor's name here as the illustration, which made this guard an
        # instance of the thing it bans. It caught itself on the next run.
        if any(part.lower() in ok for part in re.split(r"[\s@.]+", t) if part):
            continue
        banned.add(t)

    extra = [ln.strip() for ln in os.environ.get("EXTRA_FORBIDDEN", "").splitlines()]
    extra = [e for e in extra if e]
    if extra:
        notes.append(f"{len(extra)} extra identifier(s) supplied via EXTRA_FORBIDDEN")
    banned |= set(extra)

    notes.append(f"{len(derived)} identity token(s) in commit metadata, "
                 f"{len(banned)} banned after allowing deliberate attribution")
    return sorted(banned), notes


def population() -> tuple[list[str], list[str]]:
    """(tracked, untracked). Both ship; only one is in `git ls-files`.

    MEASURED 2026-08-29: this scanner reported "scanning 200 tracked file(s) ...
    clean" over a port whose NEW file was untracked -- so the file most likely to
    carry a leak was the one file never examined. `ls-files` reports the INDEX,
    and your newest work is by definition not in it yet.

    In CI this changes nothing: `actions/checkout` produces a tree with no
    untracked files, so the second list is empty. It is the LOCAL pre-push run
    that this fixes, which is exactly where the miss happened.

    `--exclude-standard` keeps ignored build output out -- that is not work.
    """
    tracked = [f for f in _git("ls-files").splitlines() if f]
    untracked = [f for f in _git("ls-files", "--others", "--exclude-standard")
                 .splitlines() if f]
    return tracked, untracked


def merged_population(tracked: list[str], untracked: list[str]) -> list[str]:
    """Pure, so the selftest can prove untracked files are really included."""
    return sorted(set(tracked) | set(untracked))


def selftest() -> int:
    """A guard that cannot be shown to fail proves nothing. One twin per clause."""
    checks = [
        ("a tracked file is scanned",
         merged_population(["a.py"], []) == ["a.py"]),
        ("an UNTRACKED file is scanned too -- the whole point",
         merged_population(["a.py"], ["new.py"]) == ["a.py", "new.py"]),
        ("a file that is both is counted once",
         merged_population(["a.py"], ["a.py"]) == ["a.py"]),
        ("an untracked file ALONE still forms a population",
         merged_population([], ["new.py"]) == ["new.py"]),
        ("an empty population stays empty, so the caller can refuse",
         merged_population([], []) == []),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print("")
    print(f"  selftest: {len(checks) - len(bad)}/{len(checks)} passed")
    return 1 if bad else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        tracked, untracked = population()
        banned, notes = forbidden_tokens()
    except RuntimeError as exc:
        print(f"::error::cannot run the identifier scan: {exc}")
        return 2

    for n in notes:
        print(f"  {n}")

    files = merged_population(tracked, untracked)
    if not files:
        print("::error::git reported no files at all — the scan population is "
              "empty, so a clean result would prove nothing.")
        return 2

    # A depth-1 checkout yields ONE commit, hence almost no tokens, hence a scan
    # that passes without checking anything. Say so rather than report success:
    # this workflow must use actions/checkout with fetch-depth: 0.
    depth = len(_git("log", "--format=%H").splitlines())
    print(f"  scanning {len(tracked)} tracked + {len(untracked)} untracked "
          f"file(s) against {len(banned)} identifier(s), derived from "
          f"{depth} commit(s)")
    if depth <= 1 and not os.environ.get("EXTRA_FORBIDDEN", "").strip():
        print("::error::only one commit is visible, so the identifier list is "
              "derived from almost nothing and this scan proves nothing. "
              "Use actions/checkout with fetch-depth: 0.")
        return 2
    if not banned:
        print("::warning::no identifiers to check — this run proves nothing.")
        return 0

    lowered = [t.lower() for t in banned]
    found = 0
    for rel in files:
        path = Path(rel)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue  # a submodule or a file git tracks but we cannot open
        for i, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if any(t in low for t in lowered):
                # path:line ONLY. Never the line, never the token -- CI logs are
                # public, and echoing the catch publishes what we are suppressing.
                print(f"::error file={rel},line={i}::a contributor identifier "
                      f"appears here; replace it with a generic description")
                found += 1

    if found:
        print(f"::error::{found} line(s) contain a contributor identifier.")
        return 1
    print(f"clean — no contributor identifiers in {len(files)} file(s) "
          f"({len(untracked)} of them not yet tracked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

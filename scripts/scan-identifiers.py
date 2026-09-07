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
import pathlib
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

#: ACCOUNT IDENTIFIERS, which commit metadata does not know about.
#:
#: The token scan above derives everything from git author names and emails, so it
#: catches a username and nothing else. MEASURED 2026-08-31: a test fixture carried a
#: real Windows username AND the author's 8-digit Egosoft profile id, which identifies
#: their game account. The username was caught; the profile id was caught only BY
#: ACCIDENT, because it sat on the same line. On a line of its own it would have shipped.
#:
#: Keyed on the surrounding PATH, never on the digits: a bare 8-digit number appears in
#: hashes, sizes and timestamps everywhere, and a check that floods is one you learn to
#: ignore.
ACCOUNT_PATTERNS = [
    (re.compile(r"egosoft[/\\]x4[/\\](\d{4,})", re.I), "an X4 profile id"),
    # An absolute Windows user path. Requires a trailing separator AND more path, so an
    # illustrative bare `C:\Users\...` in prose does not fire.
    #
    # This lived as a hand-rolled grep in ci.yml until 2026-09-01, where it had no idea
    # placeholders existed -- so the GENERIC fixtures that replaced a real leak made CI
    # red (7 hits across 2 files). Two implementations of one predicate that disagree is
    # worse than either alone: the workflow copy is the one nobody can test, and the
    # selftest below is what makes this copy honest.
    (re.compile(r"[a-z]:[/\\]+users[/\\]+([A-Za-z0-9_.-]+)[/\\]+[A-Za-z0-9_.-]", re.I),
     "an absolute user path"),
    # THE SAME PATH, SPELLED THE OTHER FOUR WAYS. The pattern above requires a DRIVE
    # LETTER, so it is blind to every non-`C:` spelling of the identical identifier --
    # and the selftest could not see that, because all six of its path twins are
    # drive-letter forms. An instrument that holds the spelling axis constant cannot
    # reach a defect on that axis, however many cases it carries (CLAUDE.md #37).
    #
    # MEASURED 2026-09-05: the Git Bash form (the shell this repo runs in), the cygwin
    # form, a UNC admin share and a POSIX home all passed unflagged. The Git Bash
    # spelling already appears in 5 tracked files.
    #
    # The capture requires a LEADING ALPHANUMERIC, so the elided form those five files
    # carry is not a hit -- an ellipsis is not a username.
    (re.compile(r"(?:/cygdrive)?/[a-z]/users/+([A-Za-z0-9][A-Za-z0-9_.-]*)/+[A-Za-z0-9_.-]", re.I),
     "an absolute user path (Git Bash / cygwin spelling)"),
    (re.compile(r"//[A-Za-z0-9_.-]+/[a-z][$]/users/+([A-Za-z0-9][A-Za-z0-9_.-]*)/+[A-Za-z0-9_.-]", re.I),
     "an absolute user path (UNC admin share)"),
    # `/home/` ONLY, and deliberately not a bare `/Users/`. Case-insensitive `/users/`
    # would match every REST URL of the shape `api.example.com/users/<name>/repos`, and
    # a check that floods is one you learn to ignore -- this file's own standard, three
    # comments up. The macOS `/Users/<name>/` spelling is therefore NOT covered; it is
    # reachable only for a contributor on macOS whose OS username differs from their git
    # identity, since the token scan catches the name itself in every other case.
    (re.compile(r"/home/+([A-Za-z0-9][A-Za-z0-9_.-]*)/+[A-Za-z0-9_.-]", re.I),
     "a POSIX home path"),
]

#: Values that are obviously stand-ins. Without this the scan fires on the generic
#: fixture that REPLACED the real one, which would train everyone to pass --no-verify.
PLACEHOLDER_IDS = {"12345678", "00000000", "11111111", "1234", "99999999"}

#: Stand-in USERNAMES for the user-path pattern. Kept separate from the ids above on
#: purpose: `87654321` is a placeholder-looking number that the profile-id twin needs
#: to FIRE on, so one shared set would have made that twin silently vacuous.
PLACEHOLDER_USERS = {"tester", "user", "username", "you", "x", "someone", "youruser",
                     "public", "all users", "default", "example", "me", "dev"}


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


def account_match(line: str) -> str | None:
    """What account identifier this line carries, or None. Placeholders excluded.

    ONE implementation, called by both the scan and the selftest. A selftest that
    re-implements the predicate can only ever prove the two copies agree, which is the
    least interesting thing it could tell you.
    """
    for rx, what in ACCOUNT_PATTERNS:
        m = rx.search(line)
        if not m:
            continue
        val = m.group(1)
        if val in PLACEHOLDER_IDS or val.lower() in PLACEHOLDER_USERS:
            continue
        # An ELISION is not a name. `C:/Users/.../AppData/...` is how these comments
        # already redact a path, and firing on it would demand "fixing" three lines
        # that are the redaction. MEASURED: 3 of 3 first hits were exactly this.
        if not re.search(r"[A-Za-z0-9]", val):
            continue
        return what
    return None


def _account_hit(line: str) -> bool:
    return account_match(line) is not None


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
        # --- account identifiers: one twin per clause, both directions ---
        # The must-FIRE id is ASSEMBLED, never written as a literal 8-digit run. A
        # realistic id spelled out here would be caught by this very scan on its own
        # file -- which it was, on the first run, and the id it caught was the real one
        # this check exists to stop. The must-NOT-fire cases can be literals: they are
        # placeholders by definition.
        ("a REAL-shaped X4 profile id in a path is caught",
         _account_hit("PROF = 'C:/Users/x/Documents/Egosoft/X4/" + "8765" + "4321'")),
        ("...with BACKSLASHES too, which is how Windows writes it",
         _account_hit(r"PROF = 'C:\Users\x\Documents\Egosoft\X4" + chr(92) + "8765" + "4321'")),
        ("a PLACEHOLDER id is NOT caught, or the fix would trip the check",
         not _account_hit("PROF = 'C:/Users/tester/Documents/Egosoft/X4/12345678'")),
        ("a bare 8-digit number is NOT caught -- a flooding check gets ignored",
         not _account_hit("blob sha " + "8765" + "4321 size 12345678")),
        ("an unrelated Egosoft path with no id is NOT caught",
         not _account_hit("see Documents/Egosoft/X4/ for the profile folder")),
        # --- absolute user paths: moved here from ci.yml, which had no placeholders ---
        ("a REAL-shaped absolute user path is caught",
         _account_hit("SRC = 'C:/Users/" + "dev" + "user/Desktop/Modding'")),
        ("...with BACKSLASHES too",
         _account_hit(r"SRC = 'C:\Users" + chr(92) + "dev" + r"user\Desktop\Modding'")),
        ("a PLACEHOLDER username is NOT caught, or the generic fixtures trip CI",
         not _account_hit("PROF = 'C:/Users/tester/Documents/Egosoft/X4/12345678'")),
        ("an illustrative bare C:\\Users\\... in prose is NOT caught",
         not _account_hit("paths look like C:" + chr(92) + "Users" + chr(92) + "...")),
        # --- THE SPELLING AXIS, which every twin above holds constant ------------
        # All six path cases above are DRIVE-LETTER forms, so no number of them could
        # ever reach a defect in a non-`C:` spelling -- and there was one. MEASURED
        # 2026-09-05: the Git Bash form (the shell this repo runs in), cygwin, a UNC
        # admin share and a POSIX home all passed unflagged.
        ("the GIT BASH spelling of an absolute user path is caught",
         _account_hit("SRC = '/c/Users/" + "dev" + "user/Desktop/Modding'")),
        ("the CYGWIN spelling is caught",
         _account_hit("SRC = '/cygdrive/c/Users/" + "dev" + "user/Desktop'")),
        ("a UNC ADMIN SHARE spelling is caught",
         _account_hit("SRC = '//host/c$/Users/" + "dev" + "user/Desktop'")),
        ("a POSIX HOME path is caught",
         _account_hit("SRC = '/home/" + "dev" + "user/work'")),
        ("the ELIDED Git Bash form already in 5 tracked files is NOT caught",
         not _account_hit("Git Bash writes '/c/Users/...' and Windows 'C:/Users/...'")),
        ("a REST url with a /users/ segment is NOT caught -- a flooding check gets ignored",
         not _account_hit("GET https://api.example.com/users/alice/repos")),
        ("a path with a user segment but nothing after it is NOT caught",
         not _account_hit("cd C:/Users/")),
        ("an ELIDED user path is NOT caught -- that IS the redaction",
         not _account_hit('received "C:/Users/.../AppData/Local/Temp/x/docs"')),
        ("...but a name that merely CONTAINS a dot still is",
         _account_hit("SRC = 'C:/Users/" + "ada" + ".lovelace/Desktop'")),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print("")
    print(f"  selftest: {len(checks) - len(bad)}/{len(checks)} passed")
    return 1 if bad else 0


#: The scan is anchored to THIS FILE's repository, never to the caller's directory.
#:
#: MEASURED 2026-09-01, the same script from three places:
#:   repo root   234 tracked, 6 identifiers, clean            (correct)
#:   scripts/      6 tracked, 7 identifiers, FALSE FAILURE    (LICENSE unreadable, so
#:                                                             the owner handle stopped
#:                                                             being allow-listed)
#:   another repo 186 tracked, 34 hits -- a report about a COMPLETELY DIFFERENT
#:                repository, in the toolkit's name. That is the dangerous direction:
#:                a wrong population that still prints a verdict.
#: scripts/test-hooks.sh invokes this without cd'ing, which is how it stayed unnoticed.
def _anchor_to_repo_root() -> None:
    import os
    os.chdir(pathlib.Path(__file__).resolve().parent.parent)


def scan_history(rng: str, banned: list[str]) -> int:
    """Scan the diff every commit in *rng* INTRODUCES. Tree-clean is not enough.

    ★ `git push` publishes COMMITS, not the working tree. An identifier that was
    committed and later removed is still in the objects and still public after the
    push -- and every other check in this repo, this script's own default mode
    included, scans the TREE. So all of them return clean on exactly the case that
    matters, which is the case where somebody noticed and fixed it.

    MEASURED 2026-09-07, and the trigger was real rather than hypothetical: a
    concurrent session hardcoded a profile path (`.../Documents/Egosoft/X4/<profile
    id>/save/...`) into a tracked test file, caught it themselves, and replaced it.
    Only a history scan could establish whether it had reached a commit. It had not
    -- zero occurrences of the username or the profile id across all 274 commits --
    but "clean" and "assumed clean" are different states and only this told them
    apart.

    ⚠ Two TREE-scanning instruments disagreeing about this is expected and is not a
    bug in either: they run at different moments, and the tree changes between them.
    Two moments, not two populations.

    Only ADDED lines (`+`) count: a commit that REMOVES an identifier is the fix, not
    the defect, and flagging it would make the remedy trip the check.
    """
    # `git rev-list A..A` is an ERROR ("Invalid revision range"), not an empty
    # list, so an empty range arrives here as a RuntimeError from `_git` rather
    # than as `[]`. Both are the same state -- nothing was scanned -- and both must
    # refuse rather than fall through to a clean-looking exit.
    try:
        shas = _git("rev-list", rng).split()
    except RuntimeError as exc:
        print(f"::error::cannot resolve the range {rng} ({exc}), so a clean "
              f"history result would prove nothing.")
        return 2
    if not shas:
        print(f"::error::no commits in {rng}, so a clean history result would "
              f"prove nothing.")
        return 2
    lowered = [t.lower() for t in banned]
    found = 0
    # `git show` prints "Binary files ... differ" with no `+` line, so a binary
    # blob's CONTENT is unreadable here while the TREE scan can read it. Counted
    # and disclosed rather than rounded away: measured 0 in v3.0.0..HEAD and 1 in
    # all history (the vendored BaseX jar, still tracked, so tree mode covers its
    # current content). The residual hole is a binary committed then removed.
    binary = 0
    for sha in shas:
        try:
            raw = subprocess.run(["git", "show", "--format=", "--unified=0", sha],
                                 capture_output=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"::error::could not read commit {sha[:9]}: {exc}")
            return 2
        # THE MESSAGE IS PART OF THE COMMIT, and `git show --format=` suppresses it.
        # A mode whose whole premise is "a push publishes COMMITS, not the working
        # tree" applied that premise to the BLOB only, so neither this scan nor the
        # tree scan could see a path pasted into a commit message.
        #
        # NOT hypothetical: the round-2 reviewer measured exactly one commit-message
        # hit in this repository's 278-commit history, an absolute user path carrying
        # a real identity token, present in NO tracked file (so tree mode is correctly
        # clean about it). It predates v3.0.0 and is already public, so it does not
        # gate -- but it is the single case this instrument was built for and the
        # instrument walked past it.
        try:
            msg = _git("log", "-1", "--format=%B", sha)
        except RuntimeError as exc:
            print(f"::error::could not read the message of {sha[:9]} ({exc}); "
                  f"a commit whose message was not read cannot be reported clean")
            return 2
        if b"Binary files" in raw or b"GIT binary patch" in raw:
            binary += 1
        scanned_lines = [("message", l) for l in msg.splitlines()]
        for line in raw.decode("utf-8", "replace").splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue
            scanned_lines.append(("diff", line))

        for _channel, line in scanned_lines:
            low = line.lower()
            hit = any(t in low for t in lowered) or account_match(line)
            if hit:
                # The SHA and nothing else. Echoing the line would publish the very
                # thing being suppressed, in a log that is itself public.
                print(f"::error::commit {sha[:9]} introduces a contributor "
                      f"identifier; it is in the history and a push publishes it")
                found += 1
                break
    print(f"  history: {len(shas)} commit(s) in {rng} scanned against "
          f"{len(banned)} identifier(s), channels: commit MESSAGE + added "
          f"diff lines"
          + (f"; {binary} commit(s) carry a BINARY diff whose CONTENT this "
             f"mode cannot read" if binary else ""))
    if found:
        print(f"::error::{found} commit(s) in {rng} carry a contributor identifier. "
              f"Removing it from the TREE does not remove it from the history.")
        return 1
    print(f"clean {chr(8212)} no commit in {rng} introduces one.")
    return 0


def main() -> int:
    _anchor_to_repo_root()
    if "--selftest" in sys.argv:
        return selftest()
    # --history <range>: scan COMMITS instead of the tree. See scan_history().
    hist = None
    if "--history" in sys.argv:
        i = sys.argv.index("--history")
        if i + 1 >= len(sys.argv):
            print("::error::--history needs a rev range, e.g. --history v3.0.0..HEAD")
            return 2
        hist = sys.argv[i + 1]
    try:
        tracked, untracked = population()
        banned, notes = forbidden_tokens()
    except RuntimeError as exc:
        print(f"::error::cannot run the identifier scan: {exc}")
        return 2

    for n in notes:
        print(f"  {n}")

    if hist is not None:
        if not banned:
            print("::error::no identifiers could be derived, so a history "
                  "scan proves nothing. Refusing rather than reporting a "
                  "vacuous pass.")
            return 2
        return scan_history(hist, banned)

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
        # REFUSE, do not pass. This sat ABOVE the account-pattern scan, so a fork whose
        # only committer appears in LICENSE yielded an empty token list and a GREEN exit
        # -- while a real profile id or absolute user path sailed through untested. The
        # depth-1 branch a few lines up already returns 2 for exactly this reason: a run
        # that checked nothing must never look like a run that found nothing.
        print("::error::no identifiers could be derived, so the token scan proves "
              "nothing. Refusing rather than reporting a vacuous pass.")
        return 2

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
                continue        # one report per line; the fix is the same either way
            what = account_match(line)
            if what:
                print(f"::error file={rel},line={i}::{what} appears here; "
                      f"replace it with a placeholder")
                found += 1

    if found:
        print(f"::error::{found} line(s) contain a contributor identifier.")
        return 1
    print(f"clean — no contributor identifiers in {len(files)} file(s) "
          f"({len(untracked)} of them not yet tracked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

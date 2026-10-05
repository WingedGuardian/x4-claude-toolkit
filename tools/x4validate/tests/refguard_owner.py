"""Make a Windows Layer 2 test's OWN scratch tree owned by the current user, or skip (counted).

WHY. `x4refguard apply` refuses a root the user does not own (a deny on a tree you do not own
may not be removable unelevated -- x4lock's lockout history), and that refusal stays. But on
an ELEVATED token -- the GitHub windows runner, MEASURED in CI run 37172347642 -- the default
owner of an object a process creates is BUILTIN\\Administrators, not the user. Every test that
built its tree with Python and then applied the deny got "REFUSED: ... is not owned by you"
(20 setup errors + 12 failures), while the one test whose tree Git Bash created (MSYS writes
the user as owner) passed. On an unelevated machine the user already owns it and this is a
no-op.

So the fixture -- never the product -- takes ownership of the test's own root, through
x4refguard's sandboxed choke point (it refuses any path outside the test's scratch tree), and
re-reads the owner. If it still is not the user, the test SKIPS with the reason: a skip is
counted, a bare return or a weakened refusal would not be.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def take_ownership(root, x4refguard):
    """`icacls /setowner` this user on `root`, then GRANT this user full control back, both
    through x4refguard's sandboxed choke point. Returns the first failing step's result, else
    the last one.

    WHY THE GRANT (FX-R2, 2026-10-05). MEASURED: under Python 3.13 pytest's temp root is made
    with mkdir(0o700), whose ACL reaches the user only through an OWNER RIGHTS ACE. After
    `/setowner` -- even to the SAME owner -- the folder was unreadable and undeletable (WinError
    5), and each run stranded one in pytest's garbage (20 found). The owner keeps WRITE_DAC, so
    an explicit grant restores access without elevation; nothing here may leave a tree the user
    cannot remove."""
    root = Path(root)
    sid = x4refguard._user_sid()
    first = x4refguard._mutate_run(["icacls", root, "/setowner", "*" + sid, "/C", "/Q"], root)
    if first.returncode != 0:
        return first
    return x4refguard._mutate_run(["icacls", root, "/grant", "*%s:(OI)(CI)F" % sid, "/T", "/C",
                                   "/Q"], root)


def own_or_skip(root, x4refguard, windows: bool | None = None) -> None:
    """Ensure `root` (inside the X4_REFGUARD_SANDBOX scratch tree) is owned by this user.
    `windows` defaults to this OS; the fixture's own tests pass True to run on every OS."""
    if not ((os.name == "nt") if windows is None else windows):
        return
    root = Path(root)
    if x4refguard._owner_is_user(root):
        return
    res = take_ownership(root, x4refguard)
    if x4refguard._owner_is_user(root):
        return
    pytest.skip("the test's scratch tree is not owned by this user and /setowner could not change "
                "that (rc %s: %s) -- Layer 2 apply NOT CHECKED here"
                % (res.returncode, (res.stdout + res.stderr).strip()[:200]))

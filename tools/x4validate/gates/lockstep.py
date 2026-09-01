"""The two halves of the live channel must agree IN THE COMMITTED BLOBS.

WHY THIS EXISTS — F87, and it is the cleanest specimen this register has of a check
that was performed and still missed the defect.

The channel's identity is spelled in TWO REPOSITORIES:

    mod side   dev/<probe>/ui.xml      <savedvariable name="__x4live_dump" .../>
    CLI side   x4validate/_livedump.py DEFAULT_VAR = "__x4live_dump"

A rename touches both. On 2026-08-28 one was committed and the other left unstaged for
two days, and BOTH sessions "verified" it — by reading their WORKING TREES, where the
rename was complete and correct:

    working tree  ui.xml:6   __x4live_dump      <- the rename, complete and correct
    git HEAD      ui.xml:6   __<the old name>   <- the artifact that would ship

(The old name is elided deliberately: it was a personal identifier, and this file
ships. The port's identifier scan caught it here on the first run -- in the gate
written to make shipping safe, which is the joke and also the point.)

Two eyeball checks of two artifacts is not a check of the PAIR. The control is to
**assert the two sides agree in the same view, and that view must be the one that
ships** — which is the committed blob, never the working tree.

WHAT THIS GATE REFUSES TO DO
  * It never reads the working tree to decide PASS/FAIL. A working-tree comparison is
    exactly the check that failed.
  * It never returns 0 when it could not look. A repo it cannot reach, a path it cannot
    find, or a pattern that matches nothing exits **2 — could not check** — because a
    gate that cannot tell "they agree" from "I did not look" is worse than no gate.
  * It does not hard-code the mod's folder name. The probe carries a personal prefix
    and this file ships; the mod is located by GLOB, the same way
    tests/test_modlua_rearm.py does.

Exit codes:  0 agree · 1 MISMATCH · 2 could not check
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The gates are run BOTH as `python -m gates.lockstep` and imported flat by
# tests/conftest.py's import_gate, which puts gates/ on sys.path. A relative import
# works only in the first. Every other gate uses this preamble; copied, not invented.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: E402

#: The CLI half. One assignment, in the module that owns the name.
CLI_PATH = "x4validate/_livedump.py"
CLI_RE = re.compile(r'^DEFAULT_VAR\s*=\s*"([^"]+)"', re.M)

#: The mod half. `ui.xml` declares the lua global the probe writes.
MOD_GLOB = "*/ui.xml"
MOD_RE = re.compile(r'<savedvariable\s+name="([^"]+)"')


def committed(repo: Path, rel: str) -> str | None:
    """The file as GIT HAS IT — the artifact that ships. None if unreadable.

    Deliberately `git show HEAD:` and not a file read. Reading the path would
    reintroduce the exact defect: the working tree is where both sessions looked.
    """
    try:
        out = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=repo,
                             capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        # silent-ok: None is the CHANNEL, not a swallow. Every caller treats it as
        # "could not read this half" and then FAILS (rc 1) or REFUSES (rc 2) -- it is
        # never folded into agreement. Distinguishing "git is missing" from "the path
        # is not committed" would change no outcome: both mean we did not see the
        # artifact that ships.
        return None
    return out.stdout.decode("utf-8", errors="replace") if out.returncode == 0 else None


def _rel_to_repo(repo: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        # silent-ok: "not under this repo" is the ANSWER, not a failure to compute one,
        # and the caller records it as an unreadable half that fails the run.
        return None


def _repo_root(start: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start,
                             capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        # silent-ok: None means "no git checkout here", and both callers turn that
        # into an explicit REFUSAL (rc 2) naming which half could not be located.
        # It is never treated as agreement.
        return None
    return Path(out.stdout.decode().strip()) if out.returncode == 0 else None


def find_mod_uis(mods: Path) -> list[Path]:
    """Every mod `ui.xml` that declares a savedvariable, by glob.

    Returns the candidates rather than picking one, so "two probes declare a variable"
    is reported instead of silently resolving to whichever sorted first.
    """
    return [p for p in sorted(mods.glob(MOD_GLOB))
            if MOD_RE.search(p.read_text(encoding="utf-8", errors="replace"))]


def main(argv=None) -> int:
    print("LOCKSTEP — the mod's savedvariable vs the CLI's DEFAULT_VAR, "
          "both from COMMITTED blobs")
    print("=" * 78)

    # ---- CLI half ------------------------------------------------------------
    cli_repo = _repo_root(ROOT)
    if cli_repo is None:
        _env.skip("the toolkit is not a git checkout",
                  "this gate compares COMMITTED blobs; there is nothing to read")
    cli_text = committed(cli_repo, CLI_PATH)
    if cli_text is None:
        _env.skip(f"could not read HEAD:{CLI_PATH} in {cli_repo}",
                  "is the file committed? a gate that cannot look must not pass")
    cli_m = CLI_RE.search(cli_text)
    if cli_m is None:
        _env.skip(f"no DEFAULT_VAR assignment in HEAD:{CLI_PATH}",
                  "the pattern found nothing -- that is a NON-ANSWER, not agreement")
    cli_var = cli_m.group(1)

    # ---- mod half ------------------------------------------------------------
    mods = _env.mods_dir()                     # exits 2 by itself if unconfigured
    uis = find_mod_uis(mods)
    if not uis:
        _env.skip(f"no mod ui.xml under {mods} declares a savedvariable",
                  "the mod half of the pair is missing; nothing to compare against")

    rows, bad = [], []
    mod_repo = _repo_root(mods)
    if mod_repo is None:
        _env.skip(f"{mods} is not inside a git checkout",
                  "the mod half must be read from a COMMITTED blob, not the tree")

    for ui in uis:
        rel = _rel_to_repo(mod_repo, ui)
        if rel is None:
            bad.append((ui.name, "outside the mod repo", None))
            continue
        text = committed(mod_repo, rel)
        if text is None:
            # UNCOMMITTED is the F87 state exactly: present and correct in the tree,
            # absent from what ships. It is a FAILURE, never a skip.
            bad.append((rel, "not committed (present in the working tree only)", None))
            continue
        m = MOD_RE.search(text)
        if m is None:
            bad.append((rel, "committed blob declares no savedvariable", None))
            continue
        rows.append((rel, m.group(1)))

    for rel, var in rows:
        mark = "ok " if var == cli_var else "!! "
        print(f"  {mark}{rel:<52} {var}")
    print(f"  cli {CLI_PATH:<52} {cli_var}")

    mismatched = [(r, v) for r, v in rows if v != cli_var]
    print()
    if bad:
        for rel, why, _ in bad:
            print(f"  UNREADABLE  {rel}: {why}", file=sys.stderr)
    if mismatched or bad:
        print(f"MISMATCH: {len(mismatched)} of {len(rows)} committed mod declaration(s) "
              f"disagree with the CLI, {len(bad)} unreadable.", file=sys.stderr)
        print("  The two halves ship together. Commit BOTH sides of the rename, then "
              "re-run -- and note that checking your working tree will show them "
              "agreeing, which is how F87 survived two verifications.", file=sys.stderr)
        return 1

    print(f"OK — {len(rows)} committed mod declaration(s) agree with the CLI "
          f"({cli_var}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

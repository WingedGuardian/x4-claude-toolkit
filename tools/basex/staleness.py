r"""Does this BaseX index still describe the world it was built from?

`ask.py` already refuses to render a zero-result as a finding without a coverage
denominator. This adds the missing dimension: the denominator must also be
**current**. A stale index is not an absence and not a non-answer — it is an
answer from a world that no longer exists, and until 2026-08-13 nothing here
detected one.

**Why the fingerprint covers CODE and not just DATA.** `x4eff` was built
2026-08-02. The merge engine was then fixed twice: root-`<replace>` ops were being
dropped while reported applied (2026-08-08 — 858 ops, VRO alone 848), and nested
cross-mod patches were invisible from one of two doors (2026-08-11). **Neither
date changed any content.** A checker watching only inputs would have called the
index fresh for eleven days while it served 858 wrong values. So `x4eff` carries
an ENGINE fingerprint as well as a CONTENT one.

Engine identity is hashed from source BYTES, not a git commit: a dirty working
tree does not move a commit hash, and merge changes here are routinely used
before they are committed.

Usage::

    python staleness.py --write --db x4eff     # stamp after a build
    python staleness.py --check --db x4eff     # exit 5 if stale
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASEX_DIR = HERE / "basex"

# NOTE: there is deliberately NO local copy of the engine-source list here.
# There used to be, and it was DEAD -- defined, never read, because hashing has
# always delegated to `_freshness.hash_engine` via `_core()`. A dead copy is
# worse than no copy: the next person to extend the real list would reasonably
# edit this one and change nothing, or edit the real one and leave this one
# quietly lying about what the fingerprint covers. Same shape as the x4similar
# weights (F8) -- two tables, nothing tying them together.
# The one list lives in `x4validate/_freshness.py::ENGINE_SOURCES`.

#: Databases built from the merged tree, i.e. the ones an engine change invalidates.
ENGINE_DEPENDENT = frozenset({"x4eff"})


class EngineUnavailable(RuntimeError):
    """x4validate could not be imported, so freshness cannot be computed.

    Neither FRESH nor STALE — UNANSWERED. Raised as its own type so the CLI can
    say that plainly instead of dying on a ModuleNotFoundError traceback, which
    tells the reader nothing about which of the three states they are in.
    """


def _core():
    """The ONE implementation, in x4validate. Delegating rather than copying is
    the whole lesson of this register: the DLC-enumeration bug was written five
    times because every caller rolled its own. Falls back to nothing -- if the
    package is unavailable the caller cannot judge freshness and must say so."""
    try:
        from x4validate import _freshness
    except ImportError as exc:
        raise EngineUnavailable(str(exc)) from exc
    return _freshness


def _hash_engine(engine_dir: Path) -> str:
    return _core().hash_engine(engine_dir)


def _hash_content(reference: Path, extensions: Path) -> str:
    return _core().hash_content(reference, extensions)


def fingerprint(reference: Path, extensions: Path, engine_dir: Path) -> dict:
    return {"content": _hash_content(reference, extensions),
            "engine": _hash_engine(engine_dir)}


@dataclass
class Verdict:
    fresh: bool
    reasons: list[str] = field(default_factory=list)
    db: str = ""
    #: False when freshness could not be EVALUATED at all (the engine is not
    #: importable, or its paths do not resolve). Distinct from `fresh=False`,
    #: which is a positive finding that the world moved. Collapsing the two would
    #: print "no longer describes the current world" — an assertion — when the
    #: honest statement is "nobody could check". Absence, non-answer and a
    #: superseded world are three states, and this register exists to keep them
    #: apart; a banner that says STALE when it means UNKNOWN sends the reader to
    #: rebuild an index that may have been perfectly current.
    determinable: bool = True

    def banner(self) -> str:
        """The text `ask.py` prints on EVERY query until the index is rebuilt."""
        if self.fresh:
            return ""
        if not self.determinable:
            return ("\n" + "!" * 78
                    + f"\n!! FRESHNESS UNKNOWN — {self.db} could not be CHECKED.\n!!   "
                    + "\n!!   ".join(self.reasons)
                    + "\n!! This is not 'stale' and not 'fresh'. Nobody established which."
                    + "\n!! Run it through the project environment:"
                    + "\n!!   cd tools/x4validate && uv run python ../basex/ask.py ..."
                    + "\n!! Until then this index cannot back a NEGATIVE claim.\n"
                    + "!" * 78 + "\n")
        return ("\n" + "!" * 78
                + f"\n!! STALE INDEX — {self.db} no longer describes the current world.\n!!   "
                + "\n!!   ".join(self.reasons)
                + "\n!! Rebuild:  cd tools/basex && bash build-corpus.sh && bash build-effective.sh"
                + "\n!! Until then this index cannot back a NEGATIVE claim, and its\n"
                  "!! positive answers describe the world as of the build, not now.\n"
                + "!" * 78 + "\n")


def check(coverage_path: Path, reference: Path, extensions: Path,
          engine_dir: Path, db: str = "") -> Verdict:
    db = db or coverage_path.stem.replace("coverage-", "")
    if not coverage_path.is_file():
        return Verdict(False, [f"no coverage report at {coverage_path}"], db)
    try:
        data = json.loads(coverage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return Verdict(False, [f"coverage report unreadable ({exc})"], db)

    stored = data.get("fingerprint")
    if not stored:
        # Absent is UNKNOWN, never fresh. Every coverage file written before
        # 2026-08-13 lacks this field, and those are precisely the databases
        # whose staleness prompted the check.
        return Verdict(False, ["no fingerprint recorded — built before staleness "
                               "tracking existed, so freshness cannot be established"], db)

    now = fingerprint(reference, extensions, engine_dir)
    reasons = []
    if stored.get("content") != now["content"]:
        reasons.append("content changed: a mod was added, removed or updated "
                       "(or the reference tree moved)")
    if db in ENGINE_DEPENDENT and stored.get("engine") != now["engine"]:
        reasons.append("engine changed: the merge code that produced this tree has "
                       "been edited, so the SAME inputs would now merge differently")
    return Verdict(not reasons, reasons, db)


def write(coverage_path: Path, reference: Path, extensions: Path,
          engine_dir: Path) -> dict:
    """Stamp *coverage_path* in place, preserving every existing key.

    Additive on purpose: `status` and `supports_negative_claim` are what make a
    negative admissible at all, and a stamp that dropped them would trade one
    guarantee for another.
    """
    data = {}
    if coverage_path.is_file():
        try:
            data = json.loads(coverage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    data["fingerprint"] = fingerprint(reference, extensions, engine_dir)
    coverage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data["fingerprint"]


def _defaults() -> tuple[Path, Path, Path]:
    """Resolve reference/extensions/engine, or RAISE.

    These used to fall back to one developer's absolute paths. On anyone else's
    machine that silently resolved to a directory that does not exist, and the
    fingerprint was then computed over nothing -- a guessed default wearing the
    grammar of a measured one, which is the defect this toolkit exists to stop.
    (It also shipped a username.)

    `x4validate._paths` is the ONE resolver (env var -> .claude/x4-paths.env ->
    project-relative). Delegating rather than copying is the same lesson as
    `_core()` above: the DLC-enumeration bug was written seven times because
    every caller rolled its own.
    """
    # Read the environment through `_paths`, not around it. Checking os.environ
    # FIRST and only then falling back was redundant — `_paths` already tries the
    # real environment before the config file — and it re-created the two-door
    # shape: the same variable resolved by two rules that could diverge.
    try:
        from x4validate import _paths
    except ImportError as exc:  # noqa: BLE001
        raise EngineUnavailable(
            f"cannot resolve paths: x4validate is not importable ({exc}), and "
            f"$X4_REFERENCE/$X4_EXTENSIONS are not both set") from exc
    reference = _paths.reference()
    extensions = _paths.game_extensions()
    missing = [n for n, v in (("reference", reference), ("extensions", extensions)) if v is None]
    if missing:
        raise EngineUnavailable(
            f"cannot resolve {' and '.join(missing)}. Set $X4_REFERENCE / $X4_EXTENSIONS, "
            f"or configure .claude/x4-paths.env. Refusing to guess: a fingerprint taken "
            f"over a path that does not exist reports FRESH forever.")
    # RESOLVING is not EXISTING, and only the second one makes a fingerprint mean
    # anything. `_paths` returns a Path for any non-empty setting, so until now a typo
    # or a moved install was accepted and then hashed over nothing.
    #
    # MEASURED 2026-09-02: two DIFFERENT nonexistent trees both fold to
    # fb2018359186a6be, and so does an EMPTY directory -- `_fold` writes
    # `<NO-EXTENSIONS-DIR>` for an empty vector, which is exactly the collision. An
    # index stamped in that state reads FRESH against any other broken world forever,
    # and `ask.py` gates `NEGATIVE CONFIRMED over N of M documents` on that verdict. The
    # headline safety property -- a negative needs a denominator AND a freshness stamp --
    # was defeated in the one direction that produces a confident wrong answer.
    #
    # Reachable without contrivance: install.sh writes X4_REFERENCE and then tells the
    # user to run bin/unpack-reference.sh to CREATE that directory, so the documented
    # post-install state points at a tree that is not there yet.
    #
    # `libraries/wares.xml` is the probe because it is already `_fold`'s own reference
    # marker -- the same file whose absence silently drops the reference axis from the
    # digest -- so this refuses precisely when the fold would have gone blind.
    if not (Path(reference) / "libraries" / "wares.xml").is_file():
        raise EngineUnavailable(
            f"the reference tree at {reference} has no libraries/wares.xml, so there is "
            f"nothing to fingerprint. Unpack it with bin/unpack-reference.sh, or point "
            f"$X4_REFERENCE at a tree that exists. Refusing to guess: every missing tree "
            f"folds to the same digest, which reads as FRESH forever.")
    # An EMPTY extensions directory is a legitimate state and stays accepted -- it means
    # no mods, and it fingerprints honestly. A MISSING one is refused, because the fold
    # cannot tell it apart from the empty case and would call a broken path fresh.
    if not Path(extensions).is_dir():
        raise EngineUnavailable(
            f"the extensions directory at {extensions} does not exist. Point "
            f"$X4_EXTENSIONS at your game's extensions/ folder. Refusing to guess: a "
            f"missing directory folds to the same digest as an empty one, so a broken "
            f"path would read as FRESH forever. An empty extensions/ is fine.")
    # env-ok: $X4VALIDATE_DIR points at a CHECKOUT of the engine source, for
    # fingerprinting. It is a developer override for where this repo lives, not a
    # user-configured X4 location, and `_paths`' layers deliberately cover only
    # `X4_`-prefixed settings — routing it there would widen that contract.
    engine = Path(os.environ.get(
        "X4VALIDATE_DIR", str(HERE.parent / "x4validate"))) / "x4validate"
    # VALIDATED, like reference and extensions above, for the reason written there:
    # "a fingerprint taken over a path that does not exist reports FRESH forever."
    #
    # That sentence used to be false where it stood. When this check was added, the two
    # axes it claimed to be copying tested only that their paths RESOLVED -- so the
    # comment asserted a validation that did not exist, and a reader (including the next
    # reviewer) had no reason to doubt it. Both are real checks as of 2026-09-02. MEASURED
    # 2026-09-02: `hash_engine` over a missing tree hashes seven fixed names plus seven
    # <ABSENT> markers, so EVERY nonexistent path folds to the SAME constant --
    # 2e797cf6683200c5 -- and `check()` then reports the artifact fresh against any of
    # them, forever. The `<ABSENT>` marker distinguishes ONE missing file, which is what
    # it was written for; it cannot distinguish "I hashed nothing".
    #
    # Reachable by ordinary misconfiguration: X4VALIDATE_DIR is documented as the
    # engine CHECKOUT, this line appends "/x4validate" to it, and pointing it at the
    # PACKAGE directory -- which the variable's name invites -- yields
    # .../x4validate/x4validate/x4validate, which does not exist. `cd` into the package
    # dir succeeds and `uv run` works, so nothing else in the build notices.
    if not (engine / "_merge.py").is_file():
        raise EngineUnavailable(
            f"the engine tree at {engine} has no _merge.py, so there is nothing to "
            f"fingerprint. Set X4VALIDATE_DIR to an x4validate CHECKOUT (the directory "
            f"CONTAINING the x4validate package), not the package itself. Refusing to "
            f"guess: every missing tree hashes to the same constant, which reads as "
            f"FRESH forever.")
    return reference, extensions, engine


def _report_unknown(db: str, exc: Exception) -> int:
    """Freshness could not be DETERMINED. Distinct from fresh and from stale.

    One implementation, because there are two ways to get here — the engine is not
    importable, or its paths do not resolve — and two copies of this message would
    be two chances to describe the same state differently. The exception text is
    quoted rather than assumed, so the reader is told WHICH of the two it was
    instead of a guess that was right only for the case its author had in mind.
    """
    print(f"cannot determine freshness for {db}: {exc}", file=sys.stderr)
    print("  This is UNKNOWN, not fresh and not stale — do not treat a clean "
          "exit as a clean index.", file=sys.stderr)
    print("  Run it through the project environment:", file=sys.stderr)
    print("    cd tools/x4validate && uv run python ../basex/staleness.py "
          f"--check --db {db}", file=sys.stderr)
    return 6


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="staleness",
        description="Does a BaseX index still describe the current world?")
    p.add_argument("--db", required=True, help="x4raw | x4eff")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="stamp after a build")
    mode.add_argument("--check", action="store_true", help="exit 5 if stale")
    p.add_argument("--coverage", help="path to coverage-<db>.json")
    args = p.parse_args(argv)

    # `_defaults()` is the EARLIEST thing that can fail, and until 2026-08-24 it sat
    # outside every handler below — so an unconfigured machine got a raw traceback
    # and rc 1 ("your thing has findings") instead of rc 6 ("this is UNKNOWN"). The
    # sibling test monkeypatched `_core`, which fails INSIDE the guarded `check()`
    # call, so it passed honestly while never reaching this line. F44's family.
    try:
        reference, extensions, engine = _defaults()
    except (EngineUnavailable, ImportError) as exc:
        return _report_unknown(args.db, exc)
    cov = Path(args.coverage) if args.coverage else BASEX_DIR / f"coverage-{args.db}.json"

    if args.write:
        try:
            fp = write(cov, reference, extensions, engine)
        except (EngineUnavailable, ImportError) as exc:
            print(f"cannot stamp {args.db}: x4validate is not importable here "
                  f"({exc}). Run via `uv run` from tools/x4validate.", file=sys.stderr)
            return 6
        print(f"  fingerprint stamped on {cov.name}: "
              f"content={fp['content']} engine={fp['engine']}")
        return 0

    try:
        verdict = check(cov, reference, extensions, engine, args.db)
    except (EngineUnavailable, ImportError) as exc:
        return _report_unknown(args.db, exc)
    if verdict.fresh:
        print(f"  {args.db}: FRESH — still describes the current world.")
        return 0
    print(verdict.banner(), file=sys.stderr)
    return 5


if __name__ == "__main__":
    raise SystemExit(main())

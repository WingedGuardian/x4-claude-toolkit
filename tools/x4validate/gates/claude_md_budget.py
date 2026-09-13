#!/usr/bin/env python
"""CLAUDE.md may not grow silently. A RATCHET, not a ceiling.

WHY A RATCHET. `CLAUDE.md` is loaded into every session, so making it smaller is a
standing objective rather than a one-time cleanup (user-set 2026-09-12). "Under
40,000 characters" is a threshold that **cannot go red in the way that matters**:
it reports PASS on a file full of content that has a better home, and being under
budget is not evidence that anything in the file earns its place.

THE WORKED EXAMPLE, MEASURED 2026-09-12. The two CLAUDE.md files on this machine
moved in OPPOSITE directions and nobody noticed for ten days:

    game root (this workspace's)   154,425 -> 38,056 chars   (-75%, deliberate)
    the SHIPPED one (repo root)     18,420 -> 70,118 chars   (+3.8x, in ONE commit)

That commit is `8289d5a` "promote the working principles and merge the knowledgebase
head": +624 lines, unannounced. **This gate would not have blocked it. It would have
made it name what it displaced.** That is the whole design.

⚠ MEASURE CHARACTERS FROM BYTES, NEVER `read_text()`. `Path.read_text()` applies
UNIVERSAL NEWLINES and silently deletes one character per line, so a ratchet built
on it is lax by the file's LINE COUNT and gets laxer as the file grows -- a gate
that is systematically permissive by a growing margin is worse than no gate.
MEASURED on the real file: 38,056 preserving vs 37,460 normalised, a gap of exactly
its 596 CRLF pairs. `wc -c` errs the other way (332 multi-byte glyphs here).

⚠ PATHS COME FROM `__file__`, NOT FROM `$X4_TOOLKIT`. MEASURED 2026-09-12: that
variable had two different live values on one machine at the same moment -- a
running session had the pre-switch value while a new shell had the post-switch one.
A gate keyed to it would resolve differently for two people simultaneously.

THE BASELINE IS LOCAL AND GITIGNORED. A committed one would be wrong for every
other clone and would fail their first run -- `toolkit_usage.py`'s reasoning, and
`perf_guard`'s before it. No baseline is reported as "drift is NOT being checked",
never as a pass.

Run:  uv run python gates/claude_md_budget.py [--record]
Exit: 0 within baseline - 1 a file grew, named with its overage - 2 nothing could
      be measured (a ratchet that passes having measured nothing is the defect).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from x4validate import _paths  # noqa: E402

#: `<repo>/tools/x4validate/gates/this.py` -> `<repo>`. From __file__ deliberately.
REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_ROOT = Path(__file__).resolve().parents[1]

BASELINE = TOOL_ROOT / ".claude-md-budget-baseline.json"

#: A backstop only. The RATCHET is the operative check -- see the docstring.
HARD_CEILING = 40_000


class Unmeasurable(Exception):
    """A file that could not be read, so no verdict about it is admissible."""


@dataclass(frozen=True)
class Violation:
    name: str
    measured: int
    baseline: int

    @property
    def over(self) -> int:
        return self.measured - self.baseline


def char_count(path: Path) -> int:
    """Characters, newlines PRESERVED. See the docstring for why this matters."""
    try:
        return len(Path(path).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise Unmeasurable(f"{path}: {type(exc).__name__}: {exc}") from exc


def budget_files() -> list[tuple[str, Path]]:
    """(label, path) for every CLAUDE.md that resolves. Absent ones are omitted,
    never guessed at -- and resolving none is a refusal in main()."""
    out: list[tuple[str, Path]] = []
    shipped = REPO_ROOT / "CLAUDE.md"
    if shipped.is_file():
        out.append(("shipped (repo root)", shipped))
    root = _paths.game_root()
    if root is not None:
        gm = Path(root) / "CLAUDE.md"
        if gm.is_file() and gm.resolve() != shipped.resolve():
            out.append(("game root", gm))
    return out


def violations(measured: dict[str, int], baseline: dict[str, int]) -> list[Violation]:
    """Files that exceed their recorded floor.

    A file absent from the baseline is NOT a violation: first sight is not growth,
    and treating it as one would make adding a file impossible.
    """
    return [Violation(n, c, baseline[n])
            for n, c in sorted(measured.items())
            if n in baseline and c > baseline[n]]


def _load() -> dict[str, int] | None:
    if not BASELINE.is_file():
        return None
    try:
        data = json.loads(BASELINE.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        # Not swallowed: an unreadable baseline must not silently mean "nothing
        # recorded", which would read as a clean first run forever.
        raise Unmeasurable(f"baseline {BASELINE.name} is unreadable: {exc}") from exc
    return {str(k): int(v) for k, v in data.items()}


def main(record: bool = False) -> int:
    record = record or "--record" in sys.argv
    files = budget_files()
    if not files:
        print("REFUSING: no CLAUDE.md resolved, so there is nothing to ratchet\n"
              "      expected one at the repo root and/or via the configured game "
              "root ($X4_GAME)", file=sys.stderr)
        return 2

    measured: dict[str, int] = {}
    print("CLAUDE.md BUDGET -- ratchet (the 40,000 ceiling is a backstop, not the check)")
    try:
        for name, path in files:
            chars = char_count(path)
            measured[name] = chars
            size = path.stat().st_size
            print(f"  {name:22s} {chars:7d} chars  {size:7d} bytes  "
                  f"headroom {HARD_CEILING - chars:+7d}   {path}")
    except Unmeasurable as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2

    try:
        baseline = _load()
    except Unmeasurable as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2

    if record:
        BASELINE.write_bytes(
            (json.dumps(measured, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        print(f"  recorded {len(measured)} floor(s) to {BASELINE.name}")
        return 0

    if baseline is None:
        # rc 2, never 0: run-gates.sh buckets 0 as `ok` and discards stdout, so a
        # ratchet that has measured nothing would read as a passing one in the summary
        # on every fresh clone forever. perf_guard returns 2 in the same state.
        print(f"  no baseline at {BASELINE.name} -- run with --record to create one.")
        print("  drift is NOT being checked.", file=sys.stderr)
        return 2

    # NAME the population that is not being checked. violations() skips a file with no
    # baseline entry (first sight is not growth), which silently narrowed the check: with
    # X4_GAME unset, or a baseline recorded for different files, it passed having compared
    # nothing (review, 2026-09-13).
    for n in sorted(set(measured) - set(baseline)):
        print(f"  NOT CHECKED  {n}: no baseline entry (run --record to start ratcheting it)")
    for n in sorted(set(baseline) - set(measured)):
        print(f"  NOT RESOLVED {n}: in the baseline but not found on this machine now")
    if not set(measured) & set(baseline):
        print("REFUSING: no measured file has a baseline entry, so nothing was compared.",
              file=sys.stderr)
        return 2
    bad = violations(measured, baseline)
    over_ceiling = [n for n, c in sorted(measured.items()) if c > HARD_CEILING]
    for n in over_ceiling:
        print(f"  NOTE  {n} is over the {HARD_CEILING} backstop "
              f"({measured[n]}). Pinned, not condoned.")
    if bad:
        print("", file=sys.stderr)
        for v in bad:
            print(f"GREW: {v.name} {v.baseline} -> {v.measured} (+{v.over} chars)",
                  file=sys.stderr)
            print(f"      Name what this displaces, or remove {v.over} chars "
                  f"elsewhere. Re-baseline with --record only when the growth is "
                  f"a decision.", file=sys.stderr)
        return 1
    print(f"  all {len(measured)} file(s) within their recorded floor.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

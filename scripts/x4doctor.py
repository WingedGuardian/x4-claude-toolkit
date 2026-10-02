#!/usr/bin/env python3
"""x4doctor -- are this root's guards LIVE, per agent target? Read-only.

WHY THIS EXISTS. Every way the guards have failed here looked, from outside, exactly like a
guarded install: a hook that read zero bytes of stdin and exited 0; `bash` resolving to the
WSL stub, which cannot run a Windows-path script; a Store `python` stub that resolves and
then cannot run; Codex skipping a hook it has not reviewed, SILENTLY (MEASURED 2026-09-30).
None of those says anything. This command asks, per installed agent target:

  * toolchain  -- the bash, python and jq the GUARDS resolve, asked of the guards' own
                  resolver (never re-implemented: a parallel resolver answers an adjacent
                  question), and EXECUTED, because resolving is not running;
  * roots      -- the reference/game roots the guards see vs the ones the tools see;
  * parity     -- the deployed tree against the toolkit source (gates/deploy_parity.py);
  * self-test  -- `x4guard.py check` controls that MUST deny and controls that MUST allow,
                  so a guard that denies everything cannot read as healthy;
  * liveness   -- Claude's hook wiring; Codex's project trust and per-hook review state;
                  X4_GUARD; the OS-level reference protection; the x4lock state.

THE CONTRACT -- ABSENCE vs NON-ANSWER, structurally:
  every row is OK, FAIL, UNKNOWN or N/A. N/A means only "this target is not installed
  here" (or "this check cannot apply on this OS"). A check that RAISES becomes UNKNOWN
  with the exception named, never a dropped row.

    exit 0  every applicable check is OK, and at least one answered
    exit 1  any FAIL
    exit 3  no FAIL, but at least one UNKNOWN   (x4validate's degraded exit)
    exit 2  could not run: no agent target at --root, nothing answered, or a usage error

The verdict line is printed FIRST (CLAUDE.md #38: a truncated report keeps its head).

It executes nothing it judges: the guard self-test goes through `x4guard.py check`, which
is side-effect-free, against a probe path that does not exist. It writes no file and never
touches Codex's config. Stdlib only, Python >= 3.10, so a broken uv or venv cannot take
down the tool that diagnoses it.

USAGE
    python scripts/x4doctor.py [--root DIR] [--agent claude|codex|generic] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

OK, FAIL, UNKNOWN, NA = "OK", "FAIL", "UNKNOWN", "N/A"
STATUSES = (OK, FAIL, UNKNOWN, NA)
TARGETS = ("claude", "codex", "generic")
HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Check:
    id: str
    target: str
    status: str
    detail: str


@dataclass
class Ctx:
    root: Path
    toolkit: Path | None = None
    env: dict = field(default_factory=lambda: dict(os.environ))
    targets: dict = field(default_factory=dict)

    def __post_init__(self):
        self.root = Path(self.root)
        if self.toolkit is None and self.env.get("X4_TOOLKIT"):
            self.toolkit = Path(self.env["X4_TOOLKIT"])
        if not self.targets:
            self.targets = detect_targets(self.root)


def exit_code(rows) -> int:
    """0 all OK, 1 any FAIL, 3 UNKNOWN without FAIL, 2 nothing answered."""
    rows = list(rows)
    answered = [r for r in rows if r.status in (OK, FAIL)]
    if not answered:
        return 2
    if any(r.status == FAIL for r in rows):
        return 1
    return 3 if any(r.status == UNKNOWN for r in rows) else 0


def run_check(cid: str, target: str, fn, ctx) -> Check:
    """One check, one row. Whatever happens inside fn, a row comes out -- and a row whose
    status is not one of the four is UNKNOWN, never trusted."""
    try:
        status, detail = fn(ctx)
    except Exception as exc:  # noqa: BLE001 -- the whole point: no check may vanish
        tb = traceback.extract_tb(exc.__traceback__)
        where = ("%s:%d" % (Path(tb[-1].filename).name, tb[-1].lineno)) if tb else "?"
        return Check(cid, target, UNKNOWN, "the check itself failed: %s: %s (at %s)"
                     % (type(exc).__name__, exc, where))
    if status not in STATUSES:
        return Check(cid, target, UNKNOWN, "the check returned an unknown status %r: %s"
                     % (status, detail))
    return Check(cid, target, status, str(detail))


def detect_targets(root: Path) -> dict[str, bool]:
    """Which agent targets are installed at `root`. Keyed on each target's GUARDS, not a
    bare folder: every install writes `.claude/x4-paths.env` (a Codex-only one included),
    and Codex reads a project `.codex/config.toml` of its own."""
    root = Path(root)
    return {
        "claude": (root / ".claude" / "settings.json").is_file(),
        "codex": (root / ".codex" / "hooks").is_dir() or (root / ".codex" / "hooks.json").is_file(),
        "generic": (root / "AGENTS.md").is_file(),
    }


def default_root(start: Path) -> Path:
    """The nearest ancestor of `start` that holds an agent target, else `start`."""
    start = Path(start).resolve()
    for d in (start, *start.parents):
        if any(detect_targets(d).values()):
            return d
    return start


#: Check groups, in report order. Each takes a Ctx and returns rows.
GROUPS: list = []


def group(fn):
    GROUPS.append(fn)
    return fn


def collect(ctx: Ctx, only: str | None = None) -> list[Check]:
    rows: list[Check] = []
    for g in GROUPS:
        try:
            got = list(g(ctx))
        except Exception as exc:  # noqa: BLE001
            got = [Check(g.__name__, "all", UNKNOWN, "the check group itself failed: %s: %s"
                         % (type(exc).__name__, exc))]
        rows.extend(got)
    if only:
        rows = [r for r in rows if r.target in (only, "all")]
    return rows


def _verdict(code: int) -> str:
    return {0: "OK -- every applicable check passed",
            1: "FAIL -- at least one guard is NOT live (see FAIL rows)",
            3: "UNKNOWN -- nothing failed, but some checks could not answer (see UNKNOWN rows)",
            2: "COULD NOT RUN -- nothing was checked; this is not a pass"}[code]


def render_text(ctx: Ctx, rows: list[Check], code: int, elapsed: float) -> str:
    present = [t for t in TARGETS if ctx.targets.get(t)]
    out = ["x4doctor: %s" % _verdict(code),
           "  root:    %s" % ctx.root,
           "  targets: %s" % (", ".join(present) or "NONE (no .claude/settings.json, .codex/hooks or AGENTS.md here)"),
           "  checked: %d row(s) in %.1fs -- %s" % (
               len(rows), elapsed,
               ", ".join("%d %s" % (sum(r.status == s for r in rows), s) for s in STATUSES)),
           ""]
    w = max([len(r.id) for r in rows] + [10])
    for r in rows:
        out.append("  %-7s %-8s %-*s %s" % (r.status, r.target, w, r.id, r.detail))
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    if sys.version_info < (3, 10):
        print("x4doctor: COULD NOT RUN -- needs Python >= 3.10 (this is %d.%d)" % sys.version_info[:2])
        return 2
    ap = argparse.ArgumentParser(prog="x4doctor", description=__doc__.splitlines()[0])
    ap.add_argument("--root", help="the folder an agent runs in (default: nearest ancestor holding a target)")
    ap.add_argument("--agent", help="report only this target: " + ", ".join(TARGETS))
    ap.add_argument("--json", action="store_true", help="one JSON document on stdout")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if a.agent and a.agent not in TARGETS:
        print("x4doctor: COULD NOT RUN -- unknown --agent %r (one of: %s)" % (a.agent, ", ".join(TARGETS)))
        return 2
    root = Path(a.root).resolve() if a.root else default_root(Path.cwd())
    ctx = Ctx(root=root)
    t0 = time.monotonic()
    rows = collect(ctx, a.agent) if any(ctx.targets.values()) else []
    elapsed = time.monotonic() - t0
    code = exit_code(rows)
    if a.json:
        print(json.dumps({"v": 1, "root": str(ctx.root),
                          "targets": {t: ("present" if ctx.targets.get(t) else "absent") for t in TARGETS},
                          "checks": [asdict(r) for r in rows],
                          "summary": _verdict(code), "exit": code,
                          "elapsed_s": round(elapsed, 2)}, indent=1))
    else:
        sys.stdout.write(render_text(ctx, rows, code, elapsed))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

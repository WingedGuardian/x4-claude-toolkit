"""Every argument of every toolkit CLI must say what it is -- and a non-trivial default must be stated.

WHY THIS EXISTS. The generated `x4-cli-reference` skill reproduces each CLI's argparse help
verbatim, so a CLI with no `help=` ships a reference that says nothing. MEASURED 2026-09-13:
a cold agent answering from that skill tripped on three undocumented arguments, and walking
every parser found **41** -- 34 with no help at all (22 of them in `x4effective`) and 7 whose
default was never stated. "Write good help text" was a habit, and a habit is how 41 accrued.
This is the check that refuses instead.

The parsers are captured by intercepting `ArgumentParser.parse_args` while calling each
entry point's `main([])`, then walking every sub-parser -- the real objects, never a scrape of
`--help`, which cannot tell an empty description from a wrapped one.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import tomllib
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parent.parent

#: Defaults that need no statement: an unset option, an off switch, an empty list.
_TRIVIAL_DEFAULTS = (None, False, [], argparse.SUPPRESS)


def entry_points() -> dict[str, str]:
    data = tomllib.loads((PKG / "pyproject.toml").read_bytes().decode("utf-8"))
    return dict(sorted(data["project"]["scripts"].items()))


def capture_parser(target: str) -> argparse.ArgumentParser | None:
    """The root parser `main()` builds, or None if it never reached parse_args."""
    captured: list[argparse.ArgumentParser] = []
    real = argparse.ArgumentParser.parse_args

    def spy(self, *a, **k):
        captured.append(self)
        raise SystemExit(0)

    modname, fn = target.split(":")
    argparse.ArgumentParser.parse_args = spy
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            getattr(importlib.import_module(modname), fn)([])
    except SystemExit:
        pass
    finally:
        argparse.ArgumentParser.parse_args = real
    return captured[0] if captured else None


def undocumented(parser: argparse.ArgumentParser, path: list[str]) -> list[str]:
    """Rows naming every argument with no help, or with an unstated non-trivial default."""
    rows: list[str] = []
    for act in parser._actions:
        if isinstance(act, argparse._SubParsersAction):
            for name, sub in act.choices.items():
                rows += undocumented(sub, path + [name])
            continue
        if isinstance(act, (argparse._HelpAction, argparse._VersionAction)):
            continue
        if act.help is argparse.SUPPRESS:
            continue                                  # deliberately hidden, e.g. a test hook
        name = "/".join(act.option_strings) or act.dest
        where = " ".join(path)
        if not (act.help or "").strip():
            rows.append(f"{where}: {name} has no help")
        elif (act.option_strings and act.default not in _TRIVIAL_DEFAULTS
              and "%(default)" not in act.help and "default" not in act.help.lower()):
            rows.append(f"{where}: {name} does not state its default ({act.default!r})")
    return rows


def count_actions(parser: argparse.ArgumentParser) -> int:
    n = 0
    for act in parser._actions:
        if isinstance(act, argparse._SubParsersAction):
            n += sum(count_actions(s) for s in act.choices.values())
        elif not isinstance(act, (argparse._HelpAction, argparse._VersionAction)):
            n += 1
    return n


# --------------------------------------------------------------------- the real CLIs


def test_every_cli_parser_is_captured_and_has_a_denominator():
    """A walker that captured nothing would pass everything vacuously."""
    eps = entry_points()
    assert len(eps) >= 11, eps
    missing = [cli for cli, t in eps.items() if capture_parser(t) is None]
    assert missing == [], f"parser not captured for: {missing}"
    total = sum(count_actions(capture_parser(t)) for t in eps.values())
    assert total >= 100, f"only {total} arguments walked -- the walk is not reaching sub-parsers"


def test_every_cli_argument_has_help_and_states_its_default():
    rows = []
    for cli, target in entry_points().items():
        rows += undocumented(capture_parser(target), [cli])
    assert rows == [], (
        f"{len(rows)} undocumented CLI argument(s) -- the generated x4-cli-reference skill "
        "would ship them blank:\n  " + "\n  ".join(rows))


# ------------------------------------------------------------- falsification twins


def test_TWIN_an_argument_with_no_help_is_reported():
    p = argparse.ArgumentParser(prog="t")
    p.add_argument("thing")
    assert undocumented(p, ["t"]) == ["t: thing has no help"]


def test_TWIN_a_subparser_argument_with_no_help_is_reported():
    p = argparse.ArgumentParser(prog="t")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("go", help="go somewhere")
    s.add_argument("--fast", action="store_true")
    assert undocumented(p, ["t"]) == ["t go: --fast has no help"]


def test_TWIN_an_unstated_nontrivial_default_is_reported():
    p = argparse.ArgumentParser(prog="t")
    p.add_argument("--limit", type=int, default=20, help="how many rows")
    assert undocumented(p, ["t"]) == ["t: --limit does not state its default (20)"]


def test_TWIN_a_stated_default_and_a_trivial_default_pass():
    p = argparse.ArgumentParser(prog="t")
    p.add_argument("--limit", type=int, default=20, help="how many rows (default: %(default)s)")
    p.add_argument("--quiet", action="store_true", help="less output")
    p.add_argument("--name", help="a name")
    p.add_argument("--hidden", help=argparse.SUPPRESS)
    assert undocumented(p, ["t"]) == []


def test_TWIN_the_spy_restores_parse_args():
    before = argparse.ArgumentParser.parse_args
    capture_parser(next(iter(entry_points().values())))
    assert argparse.ArgumentParser.parse_args is before

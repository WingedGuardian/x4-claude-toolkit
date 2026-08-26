r"""While a mutating gate runs, every tool must say so — and none may PERSIST.

THE PROBLEM. `gates/mutation_probe.py` deliberately breaks `_merge.py`,
`_registry.py` and `_compat.py` while it runs. During that window `x4effective`,
`x4compat` and `x4validate` all answer from broken code at once, and the tree
looks entirely normal because the mutated file is a TRACKED file (gotcha #27).

Two sessions remembering to message each other is not a control. The parallel
session put it best, and the sentence is theirs:

    "A control only one side can see is still an assurance."

TWO DIFFERENT SEVERITIES, deliberately handled differently:

  READS  -> a BANNER. A wrong answer can be re-taken once the window closes, and
            refusing outright would break an unrelated session's work for the
            ~70s a probe run takes.
  WRITES -> REFUSE. A poisoned ARTIFACT outlives the window and is trusted later
            by everything downstream. There are exactly two stamping sites, and
            refusing AT THE STAMP rather than at argument-parsing means no other
            entry path can slip past it.

⚠ THE TRAP THIS AVOIDS. The marker lives in the PACKAGE ROOT, but the common case
is running `x4effective` from the game directory. A CWD-relative lookup would find
nothing and cheerfully report all-clear from the one place it matters most —
F46's `Path("")` fallback wearing new clothes.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from x4validate import _mutation


def test_the_marker_is_resolved_from_the_PACKAGE_ROOT_not_the_cwd(tmp_path, monkeypatch):
    """The whole point. Run from anywhere; the answer must not change."""
    here = _mutation.marker_path()
    monkeypatch.chdir(tmp_path)
    assert _mutation.marker_path() == here, (
        "a CWD-relative marker lookup reports all-clear from the game directory, "
        "which is exactly where these tools are run")


def test_the_marker_path_is_where_the_probe_actually_writes_it():
    """Pins the two halves together: if either side moves, this fails rather than
    silently never matching."""
    import importlib.util, sys
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("mp_probe", root / "gates" / "mutation_probe.py")
    mp = importlib.util.module_from_spec(spec)
    sys.modules["mp_probe"] = mp
    spec.loader.exec_module(mp)
    assert mp.MARKER == _mutation.marker_path()


def test_no_marker_means_no_banner_and_no_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(_mutation, "marker_path", lambda: tmp_path / "absent")
    assert _mutation.active() is None
    assert _mutation.banner() == ""
    _mutation.refuse_if_mutating("build the store")      # must not raise


def test_a_marker_produces_a_banner_naming_the_file_and_the_risk(tmp_path, monkeypatch):
    m = tmp_path / ".mutation-probe-active"
    m.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(_mutation, "marker_path", lambda: m)
    assert _mutation.active() == m
    text = _mutation.banner()
    assert ".mutation-probe-active" in text
    assert "mutat" in text.lower(), "the reader must learn WHY the answer is suspect"


def test_a_marker_REFUSES_a_write(tmp_path, monkeypatch):
    """A poisoned artifact outlives the window; a poisoned read does not."""
    m = tmp_path / ".mutation-probe-active"
    m.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(_mutation, "marker_path", lambda: m)
    with pytest.raises(_mutation.TreeMutating) as exc:
        _mutation.refuse_if_mutating("build the effective store")
    assert "build the effective store" in str(exc.value)


def test_the_refusal_can_actually_fire_and_can_actually_not(tmp_path, monkeypatch):
    """Falsification twin: without this, 'never raises' and 'always raises' would
    both satisfy the tests above taken singly."""
    m = tmp_path / ".mutation-probe-active"
    monkeypatch.setattr(_mutation, "marker_path", lambda: m)
    _mutation.refuse_if_mutating("x")            # absent -> silent
    m.write_text("{}", encoding="utf-8")
    with pytest.raises(_mutation.TreeMutating):
        _mutation.refuse_if_mutating("x")        # present -> raises


def test_every_cli_entry_point_emits_the_banner(tmp_path, monkeypatch, capsys):
    """The banner rides on the decorator every entry point already carries, so
    coverage is guaranteed by the existing test that pins the decorator."""
    from x4validate import _paths
    m = tmp_path / ".mutation-probe-active"
    m.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(_mutation, "marker_path", lambda: m)

    @_paths.refuses_unconfigured
    def fake_main(argv=None):
        return 0

    assert fake_main([]) == 0, "a read must still RUN; only writes are refused"
    assert ".mutation-probe-active" in capsys.readouterr().err


def test_the_banner_goes_to_stderr_so_it_cannot_corrupt_piped_output(tmp_path, monkeypatch, capsys):
    """`x4effective dump` output gets piped and diffed. A warning on stdout would
    silently corrupt exactly the workflows this is meant to protect."""
    from x4validate import _paths
    m = tmp_path / ".mutation-probe-active"
    m.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(_mutation, "marker_path", lambda: m)

    @_paths.refuses_unconfigured
    def fake_main(argv=None):
        print("PAYLOAD")
        return 0

    fake_main([])
    out = capsys.readouterr()
    assert out.out.strip() == "PAYLOAD"
    assert ".mutation-probe-active" in out.err


def test_a_refused_WRITE_exits_2_and_does_not_traceback(tmp_path, monkeypatch, capsys):
    """rc 2 is "cannot run"; rc 1 means "the thing you asked about has findings".
    A caller that cannot tell them apart is told to fix the wrong thing.

    MEASURED 2026-08-26: the first cut of this raised through the CLI and gave a
    raw `TreeMutating` traceback with rc 1 -- the same defect F39/F47 fixed
    elsewhere, reintroduced by the very change whose docstring warns about it.
    Found by running the real CLI, not by reading the code.
    """
    from x4validate import _paths
    m = tmp_path / ".mutation-probe-active"
    m.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(_mutation, "marker_path", lambda: m)

    @_paths.refuses_unconfigured
    def fake_build(argv=None):
        _mutation.refuse_if_mutating("build the effective store")
        return 0

    rc = fake_build([])
    err = capsys.readouterr().err
    assert rc == 2, "a refusal is 'cannot run' (2), never 'has findings' (1)"
    assert "Traceback" not in err
    assert "refusing to build the effective store" in err

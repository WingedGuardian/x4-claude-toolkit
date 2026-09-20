"""Did the helper mod LOAD this session? -- read from a LIVE debug.txt, or refused.

WHY THIS EXISTS. When X4 is running but nothing connects, the refusal could not say WHICH of
two very different things was wrong: the mod is not installed/enabled, or it is loaded and the
frame loop is not executing (minimized). The fix for one is not the fix for the other, and the
hint told the user to go grep debug.txt by hand. This reads that marker for them.

THE SOUNDNESS RULE, and the reason most of these tests are about refusing: debug.txt OUTLIVES
the run that wrote it. A marker in a stale log proves the mod loaded in SOME session, not THIS
one -- so concluding "loaded" from it would be exactly the "a set difference is a QUESTION"
error. Staleness therefore DOMINATES content in both directions: a stale log answers None
whether or not it carries the marker.

Like `game_is_running`, this only ever shapes a MESSAGE. It never decides an outcome, so a
machine whose log is unreadable loses specificity and never gets a different verdict.
"""
from __future__ import annotations

import time

import pytest

from x4validate import _livepipe as lp

#: The GENERIC suffix, never the deployment-specific prefix -- F73: spelling the full marker in
#: a shipped file put a personal identifier into it. The mod's own line ends with this.
MARKER = "_LIVE loaded"


def _log(tmp_path, body: str, age_s: float = 0.0):
    p = tmp_path / "debug.txt"
    p.write_text(body, encoding="utf-8")
    if age_s:
        old = time.time() - age_s
        import os
        os.utime(p, (old, old))
    return p


def _with_log(monkeypatch, path):
    monkeypatch.setattr(lp._paths, "debug_log", lambda: path)


def test_a_LIVE_log_carrying_the_marker_reports_LOADED(tmp_path, monkeypatch):
    _with_log(monkeypatch, _log(tmp_path, f"[=ERROR=] 0.03 X4TOOLKIT{MARKER}: proto=1\n"))
    assert lp.helper_loaded_this_session() is True


def test_a_LIVE_log_WITHOUT_the_marker_reports_NOT_LOADED(tmp_path, monkeypatch):
    """The twin. Without this, a function that always answered None would pass the test
    above's negation and still be useless."""
    _with_log(monkeypatch, _log(tmp_path, "[=ERROR=] 0.03 something else entirely\n"))
    assert lp.helper_loaded_this_session() is False


def test_a_STALE_log_REFUSES_even_though_it_carries_the_marker(tmp_path, monkeypatch):
    """THE soundness case. debug.txt outlives its run; a marker in a stale file proves the mod
    loaded in SOME session, not this one. Answering True here would assert a thing not measured."""
    _with_log(monkeypatch, _log(tmp_path, f"X4TOOLKIT{MARKER}\n",
                                age_s=lp.LOG_LIVE_WINDOW_S + 60))
    assert lp.helper_loaded_this_session() is None


def test_a_STALE_log_WITHOUT_the_marker_ALSO_refuses(tmp_path, monkeypatch):
    """Staleness dominates content in BOTH directions -- otherwise 'not loaded' could be
    asserted from a log written before the mod was ever installed."""
    _with_log(monkeypatch, _log(tmp_path, "nothing here\n", age_s=lp.LOG_LIVE_WINDOW_S + 60))
    assert lp.helper_loaded_this_session() is None


def test_an_UNRESOLVED_log_refuses(monkeypatch):
    _with_log(monkeypatch, None)
    assert lp.helper_loaded_this_session() is None


def test_an_UNREADABLE_log_refuses(tmp_path, monkeypatch):
    _with_log(monkeypatch, tmp_path / "does-not-exist.txt")
    assert lp.helper_loaded_this_session() is None


# --- the message the user actually reads ------------------------------------ #

def test_NOT_RUNNING_names_the_game_and_does_not_mention_the_mod():
    msg = lp._no_connection_reason(r"\\.\pipe\x4live", 10.0, running=False, loaded=None)
    assert "NOT RUNNING" in msg
    assert "minimi" not in msg.lower(), "a closed game must not get the minimized essay"


def test_RUNNING_and_LOADED_points_at_the_frame_loop_not_the_deployment():
    msg = lp._no_connection_reason(r"\\.\pipe\x4live", 10.0, running=True, loaded=True)
    assert "DID load" in msg
    assert "MINIMIZE" in msg, "this is the case the minimized hint is for"


def test_RUNNING_and_NOT_LOADED_points_at_the_DEPLOYMENT(tmp_path):
    """The narrowing that motivated the whole file: this user should be told to check the
    install, NOT to un-minimize a window."""
    msg = lp._no_connection_reason(r"\\.\pipe\x4live", 10.0, running=True, loaded=False)
    assert "did NOT log" in msg and "extensions" in msg
    assert "MINIMIZE" not in msg, (
        "a mod that never loaded is not a minimized-window problem; sending that user to the "
        "window is the exact mis-diagnosis this replaces")


def test_RUNNING_but_marker_UNKNOWN_keeps_the_old_hedged_text():
    msg = lp._no_connection_reason(r"\\.\pipe\x4live", 10.0, running=True, loaded=None)
    assert "MINIMIZE" in msg and "did NOT log" not in msg


@pytest.mark.parametrize("loaded", [True, False, None])
def test_every_message_names_the_pipe_and_the_timeout(loaded):
    msg = lp._no_connection_reason(r"\\.\pipe\x4live", 7.0, running=True, loaded=loaded)
    assert r"\\.\pipe\x4live" in msg and "7" in msg

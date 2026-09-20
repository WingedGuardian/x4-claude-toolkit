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


# --- is the extension one the ENGINE would load? ---------------------------- #
#
# The marker alone cannot separate "not installed" from "no save loaded yet", because the mod
# initialises on GAME LOAD -- at the main menu its marker is legitimately absent. This reads
# the install directly instead of inferring it from a log.

def _with_active(monkeypatch, ids, scopes=None):
    """Stub `_registry.mods`, recording the scope it was asked for."""
    from x4validate import _registry

    def fake(scope, *a, **kw):
        if scopes is not None:
            scopes.append(scope)
        return [{"id": i, "enabled": True} for i in (ids if scope == "active" else [*ids, "off"])]

    monkeypatch.setattr(_registry, "mods", fake)


def test_helper_is_deployed_TRUE_when_the_id_is_in_the_ACTIVE_set(monkeypatch):
    _with_active(monkeypatch, ["ws_2042901274", lp.HELPER_EXTENSION_ID])
    assert lp.helper_is_deployed() is True


def test_helper_is_deployed_FALSE_when_the_id_is_ABSENT(monkeypatch):
    """The twin. Without it, a function that always answered True would pass the test above."""
    _with_active(monkeypatch, ["ws_2042901274", "something_else"])
    assert lp.helper_is_deployed() is False


def test_helper_is_deployed_asks_for_ACTIVE_not_INSTALLED(monkeypatch):
    """CLAUDE.md #24. A folder on disk the profile has switched off is NOT something the engine
    loads; calling it deployed is the false pass that made the scope argument mandatory. The
    stub answers a DIFFERENT set per scope, so an `installed` caller would still read True."""
    scopes: list[str] = []

    def per_scope(scope, *a, **kw):
        scopes.append(scope)
        # on disk but profile-disabled: present under "installed", absent under "active"
        return [] if scope == "active" else [{"id": lp.HELPER_EXTENSION_ID, "enabled": False}]

    monkeypatch.setattr("x4validate._registry.mods", per_scope)
    assert lp.helper_is_deployed() is False
    assert scopes == ["active"], f"scope must be 'active', got {scopes}"


def test_an_UNCONFIGURED_toolkit_REFUSES_rather_than_claiming_NOT_deployed(monkeypatch):
    """"I was never told where extensions\\ is" is a fact about our configuration, not about
    the user's install. Answering False would put the second claim in the first one's grammar."""
    from x4validate import _paths

    def boom(scope, *a, **kw):
        raise _paths.Unconfigured("extensions root not configured")

    monkeypatch.setattr("x4validate._registry.mods", boom)
    assert lp.helper_is_deployed() is None


def test_an_UNREADABLE_extensions_root_REFUSES(monkeypatch):
    def boom(scope, *a, **kw):
        raise OSError("extensions root is gone")

    monkeypatch.setattr("x4validate._registry.mods", boom)
    assert lp.helper_is_deployed() is None


# --- the message the user actually reads ------------------------------------ #

def test_NOT_RUNNING_names_the_game_and_does_not_mention_the_mod():
    msg = lp._no_connection_reason(r"\\.\pipe\x4live", 10.0,
                                   running=False, loaded=None, deployed=None)
    assert "NOT RUNNING" in msg
    assert "minimi" not in msg.lower(), "a closed game must not get the minimized essay"


def test_RUNNING_and_LOADED_points_at_the_frame_loop_not_the_deployment():
    msg = lp._no_connection_reason(r"\\.\pipe\x4live", 10.0,
                                   running=True, loaded=True, deployed=True)
    assert "DID load" in msg
    assert "MINIMIZE" in msg, "this is the case the minimized hint is for"


def test_NOT_DEPLOYED_points_at_the_install(tmp_path):
    """The narrowing the deployment read exists for: this user should be told to check the
    install, NOT to un-minimize a window."""
    msg = lp._no_connection_reason(r"\\.\pipe\x4live", 10.0,
                                   running=True, loaded=False, deployed=False)
    assert "NOT in the set the engine would load" in msg and "extensions" in msg
    assert "MINIMIZE" not in msg, (
        "a mod that never loaded is not a minimized-window problem; sending that user to the "
        "window is the exact mis-diagnosis this replaces")


def test_NOT_DEPLOYED_outranks_an_UNKNOWN_marker():
    """A log we could not read must not downgrade a deployment we COULD measure."""
    msg = lp._no_connection_reason(r"\\.\pipe\x4live", 10.0,
                                   running=True, loaded=None, deployed=False)
    assert "NOT in the set the engine would load" in msg
    assert "MINIMIZE" not in msg


def test_a_LOADED_marker_OUTRANKS_a_not_deployed_read():
    """The twin that stops the branch above over-reaching. A mod cannot log from a live run
    without being installed, so this combination means the mod set moved under the running
    game -- it is NOT evidence that the mod never loaded."""
    msg = lp._no_connection_reason(r"\\.\pipe\x4live", 10.0,
                                   running=True, loaded=True, deployed=False)
    assert "DID load" in msg and "NOT in the set the engine would load" not in msg


def test_MENU_no_save_loaded_does_NOT_say_not_installed():
    """★ THE DEFECT THIS FIXES, found in game 2026-09-20. At the main menu the mod is installed
    and enabled and its marker is legitimately absent, because it initialises on GAME LOAD. The
    old text concluded "most likely not installed" and sent the user to check their install."""
    msg = lp._no_connection_reason(r"\\.\pipe\x4live", 10.0,
                                   running=True, loaded=False, deployed=True)
    assert "IS installed and enabled" in msg
    assert "GAME LOAD" in msg and "save" in msg
    assert "not installed" not in msg, "the exact false positive this replaces"
    assert "MINIMIZE" not in msg


def test_marker_absent_and_deployment_UNKNOWN_names_BOTH_causes():
    """With no deployment reading there is no evidence separating the two causes, so the
    message must name both. Picking one is what made the menu case wrong."""
    msg = lp._no_connection_reason(r"\\.\pipe\x4live", 10.0,
                                   running=True, loaded=False, deployed=None)
    assert "TWO possibilities" in msg
    assert "load a save" in msg.lower() and "extensions" in msg


def test_RUNNING_but_marker_UNKNOWN_keeps_the_old_hedged_text():
    msg = lp._no_connection_reason(r"\\.\pipe\x4live", 10.0,
                                   running=True, loaded=None, deployed=True)
    assert "MINIMIZE" in msg and "did NOT log" not in msg


@pytest.mark.parametrize("loaded", [True, False, None])
@pytest.mark.parametrize("deployed", [True, False, None])
def test_every_message_names_the_pipe_and_the_timeout(loaded, deployed):
    msg = lp._no_connection_reason(r"\\.\pipe\x4live", 7.0,
                                   running=True, loaded=loaded, deployed=deployed)
    assert r"\\.\pipe\x4live" in msg and "7" in msg

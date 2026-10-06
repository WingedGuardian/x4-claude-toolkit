"""The live Codex e2e rows must not be satisfiable by the model ECHOING the prompt.

v4.0.0 review R4-8: the `validator-context` row passed when the transcript contained
"X4 VALIDATION" (case-folded) -- and its own prompt asked for "any message about X4
validation", which `codex exec` echoes into the very transcript the check reads. The row could
not go red. The check now looks only for strings the VALIDATOR emits, after removing the
prompt from the transcript, and the prompt no longer contains any of them.

No Codex runs here: the rows' check functions are pure over a transcript string.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "codex-e2e.py"


@pytest.fixture(scope="module")
def e2e():
    return _load()


def test_a_MISSING_codex_e2e_script_FAILS_rather_than_skips(monkeypatch, tmp_path):
    monkeypatch.setattr(sys.modules[__name__], "SCRIPT", tmp_path / "codex-e2e.py")
    with pytest.raises(AssertionError, match="ships in every layout"):
        _load()


def _load():
    # v4.0.0 delta review: this was an unconditional skip. scripts/codex-e2e.py is tracked,
    # not export-ignored, and copied by both installers (`scripts` is in the copy set), so
    # every layout carries it: a missing one is a broken tree, never a reason to skip.
    assert SCRIPT.is_file(), f"{SCRIPT} is missing -- it ships in every layout"
    spec = importlib.util.spec_from_file_location("codex_e2e_rows", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["codex_e2e_rows"] = mod
    spec.loader.exec_module(mod)
    return mod


def _check(e2e, text):
    prompt, check, _blocks = e2e.ROWS["validator-context"]
    return check(None, text)


def test_the_ECHOED_prompt_alone_does_NOT_satisfy_the_validator_row(e2e):
    prompt = e2e.ROWS["validator-context"][0]
    transcript = "user\n" + prompt + "\ncodex\nI received no such message.\n"
    assert not _check(e2e, transcript)


@pytest.mark.parametrize("said", ["x4validate (advisory) flagged this edit:",
                                  "VALIDATION NOT COMPLETED: one or more requested checks could not run"])
def test_TWIN_a_message_the_VALIDATOR_emits_does(e2e, said):
    prompt = e2e.ROWS["validator-context"][0]
    assert _check(e2e, "user\n" + prompt + "\ncodex\nThe message was: " + said + "\n")


@pytest.mark.parametrize("said", [
    "X4 VALIDATION DID NOT RUN for dev/mymod/libraries/wares.xml: x",
    "X4 VALIDATION DID NOT RUN: the toolkit hook failed (boom). x4validate (advisory) earlier"])
def test_FXB2_a_DID_NOT_RUN_context_FAILS_the_row(e2e, said):
    """FX-B2 (delta review): "X4 VALIDATION DID NOT RUN" is the ADAPTER saying the hook FAILED
    -- no validator ran -- and it passed the row whose point is that the validator's context
    reached the model. It now fails it, even beside a validator marker."""
    prompt = e2e.ROWS["validator-context"][0]
    assert not _check(e2e, "user\n" + prompt + "\ncodex\nThe message was: " + said + "\n")


def test_FXB2_the_prompt_does_not_name_the_failure_marker_either(e2e):
    assert e2e.VALIDATOR_FAILED.lower() not in e2e.ROWS["validator-context"][0].lower()


def test_the_prompt_names_none_of_the_markers(e2e):
    prompt = e2e.ROWS["validator-context"][0]
    for marker in e2e.VALIDATOR_MARKERS:
        assert marker.lower() not in prompt.lower(), marker
